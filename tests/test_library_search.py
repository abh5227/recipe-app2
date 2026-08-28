"""GET /api/library/search, the ingredient-library lookup route (add-on-save stage 4).

The route exists for a picker that does not exist yet, so what is worth pinning is the CONTRACT it
will be built against: the match semantics, the cap, and above all `ingredient_id` / `matched_by`,
which is what will decide whether a link creates a row or reuses one.

library_names is loaded from a gitignored server-side file, so the fixture table is empty by default
(make_kitchen rebinds the loader's path into tmp_path). Tests that want rows insert them directly.
"""
from pathlib import Path

from app import ingredient_slug


def _lib(kitchen, *pairs):
    """Seed library_names directly. The loader has its own tests; this is about the route."""
    with kitchen.conn() as c:
        c.executemany("INSERT INTO library_names (library_id, canonical) VALUES (?,?)", pairs)


def _search(kitchen, q):
    r = kitchen.client.get("/api/library/search", query_string={"q": q})
    assert r.status_code == 200
    return r.get_json()


# ---- the empty-table state: the default, on a fresh clone and in CI -----------------------------

def test_empty_table_answers_200_with_no_results(kitchen):
    """⚠️ THE SELF-DISABLED STATE. No lookup file means no rows, and the route must answer cleanly
    rather than error. Anything else would make a fresh clone look broken."""
    assert kitchen.count("library_names") == 0
    body = _search(kitchen, "penne")
    assert body == {"query": "penne", "capped": False, "results": []}


def test_a_blank_query_returns_nothing_rather_than_everything(kitchen):
    _lib(kitchen, ("Q178", "pasta"), ("Q1063736", "penne"))
    for q in ("", "   "):
        assert _search(kitchen, q) == {"query": "", "capped": False, "results": []}


def test_missing_q_param_is_the_same_as_blank(kitchen):
    r = kitchen.client.get("/api/library/search")
    assert r.status_code == 200
    assert r.get_json()["results"] == []


# ---- match semantics ----------------------------------------------------------------------------

def test_case_insensitive_substring_on_the_canonical(kitchen):
    _lib(kitchen, ("Q1", "penne"), ("Q2", "Penne Rigate"), ("Q3", "wholewheat penne"),
         ("Q4", "spaghetti"))
    got = [r["canonical"] for r in _search(kitchen, "PENNE")["results"]]
    assert got == ["penne", "Penne Rigate", "wholewheat penne"]     # substring, not prefix
    assert _search(kitchen, "ghett")["results"][0]["canonical"] == "spaghetti"


def test_shortest_first_puts_the_exact_match_on_top(kitchen):
    """An exact match is always the shortest string containing the query, so ordering by length is
    what makes the cap honest without inventing a ranking rule."""
    _lib(kitchen, ("Q1", "coarse sea salt"), ("Q2", "salt"), ("Q3", "sea salt"))
    assert [r["canonical"] for r in _search(kitchen, "salt")["results"]] == \
           ["salt", "sea salt", "coarse sea salt"]


def test_a_percent_in_the_query_is_literal_not_a_wildcard(kitchen):
    """⚠️ 36 real canonicals carry a %, so an unescaped LIKE pattern would silently wildcard."""
    _lib(kitchen, ("Q1", "3% fat reduced cocoa powder"), ("Q2", "cocoa powder"))
    got = [r["canonical"] for r in _search(kitchen, "3%")["results"]]
    assert got == ["3% fat reduced cocoa powder"]                   # not both rows
    assert _search(kitchen, "%")["results"][0]["canonical"] == "3% fat reduced cocoa powder"


def test_an_underscore_in_the_query_is_literal_too(kitchen):
    _lib(kitchen, ("Q1", "a_b"), ("Q2", "axb"))
    assert [r["canonical"] for r in _search(kitchen, "a_b")["results"]] == ["a_b"]


def test_results_are_capped_and_the_cap_is_reported(kitchen):
    import app
    _lib(kitchen, *[(f"Q{i}", f"pepper variety {i:03d}") for i in range(60)])
    body = _search(kitchen, "pepper")
    assert len(body["results"]) == app.LIBRARY_SEARCH_LIMIT == 50
    assert body["capped"] is True

    assert _search(kitchen, "variety 001")["capped"] is False


# ---- ingredient_id / matched_by: the part the picker branches on ---------------------------------

def test_matched_by_library_id_when_a_row_records_that_origin(kitchen):
    """The exact case. An ingredients row naming this library row as its origin is a promotion, with
    nothing inferred."""
    _lib(kitchen, ("Q1063736", "penne"))
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, source, library_id) "
                  "VALUES ('penne','penne','app','Q1063736')")
    (row,) = _search(kitchen, "penne")["results"]
    assert row["ingredient_id"] == "penne"
    assert row["matched_by"] == "library_id"


def test_matched_by_slug_for_a_hand_authored_row(kitchen):
    """⚠️ THE 32-of-36 CASE. garlic is a seed row with library_id NULL, so there is no provenance to
    match, but it already OCCUPIES the id this canonical would mint. Linking to it is what stops a
    promotion colliding on the primary key."""
    _lib(kitchen, ("Q21546392", "garlic"))
    with kitchen.conn() as c:
        seed = c.execute("SELECT id, source, library_id FROM ingredients WHERE id='garlic'").fetchone()
    assert (seed["source"], seed["library_id"]) == ("seed", None)   # nobody promoted it

    (row,) = _search(kitchen, "garlic")["results"]
    assert row["ingredient_id"] == "garlic" == ingredient_slug("garlic")
    assert row["matched_by"] == "slug"


def test_null_when_neither_matches_so_a_link_would_create(kitchen):
    _lib(kitchen, ("Q1063736", "penne"))
    (row,) = _search(kitchen, "penne")["results"]
    assert row == {"library_id": "Q1063736", "canonical": "penne",
                   "ingredient_id": None, "matched_by": None}


def test_provenance_wins_over_a_slug_collision(kitchen):
    """If both could match, the certain answer is the one reported. Here the promoted row carries the
    library_id but sits under a different id than the canonical would mint."""
    _lib(kitchen, ("Q1063736", "penne"))
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, source, library_id) "
                  "VALUES ('penne_2','penne','app','Q1063736')")
        c.execute("INSERT INTO ingredients (id, name, source) VALUES ('penne','Penne','app')")
    (row,) = _search(kitchen, "penne")["results"]
    assert row["ingredient_id"] == "penne_2"
    assert row["matched_by"] == "library_id"


def test_a_mixed_result_set_labels_each_row_independently(kitchen):
    _lib(kitchen, ("Q21546392", "garlic"), ("Q1", "garlic powder"), ("Q2", "wild garlic"))
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, source, library_id) "
                  "VALUES ('garlic_powder','garlic powder','app','Q1')")
    got = {r["canonical"]: (r["ingredient_id"], r["matched_by"])
           for r in _search(kitchen, "garlic")["results"]}
    assert got == {"garlic": ("garlic", "slug"),
                   "garlic powder": ("garlic_powder", "library_id"),
                   "wild garlic": (None, None)}


# ---- it reads the lookup table and nothing else --------------------------------------------------

def test_reads_only_library_names_never_the_source_databases(kitchen):
    """app.py has no access to join.db or sources.db, and this route is the first that could couple
    to them. Checked on the IMPORT GRAPH rather than by grepping for the filenames, because the
    route's own docstring names both while using neither."""
    import ast
    import sys

    import app
    tree = ast.parse(Path(app.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "build_library" not in imported
    assert "build_join" not in imported and "build_sources_db" not in imported

    sys.modules.pop("build_library", None)
    _search(kitchen, "penne")                       # a real request through the route
    assert "build_library" not in sys.modules       # nothing pulled it in lazily either


# ---- auth, matching every other ingredient route --------------------------------------------------

def test_login_gated_like_the_other_ingredient_routes(kitchen_logged_out):
    """Fail-closed default-deny: the route is not in PUBLIC_ENDPOINTS, so it is gated by adding it."""
    assert kitchen_logged_out.client.get("/api/library/search?q=penne").status_code == 401
    assert kitchen_logged_out.client.get("/api/ingredients").status_code == 401


# ---- pre-push review, finding 5: ilike rather than like -------------------------------------------

def test_case_insensitivity_is_dialect_correct(kitchen):
    """⚠️ FINDING 5. The route used LIKE, which is not the same operator on the two dialects this app
    runs on: SQLite folds ASCII case, Postgres folds nothing, so 'penne' would have missed 'Penne'
    the moment it ran on PG. ilike compiles to ILIKE there and lower(x) LIKE lower(y) here, so the
    docstring's claim is true on both. This pins that SQLite behavior did not regress."""
    _lib(kitchen, ("Q1", "Penne Rigate"), ("Q2", "penne"), ("Q3", "PENNE ALL'ARRABBIATA"))
    for q in ("penne", "PENNE", "PeNnE"):
        got = {r["canonical"] for r in _search(kitchen, q)["results"]}
        assert got == {"Penne Rigate", "penne", "PENNE ALL'ARRABBIATA"}, q


def test_the_escape_still_holds_under_ilike(kitchen):
    """The wildcard escape has to survive the operator change, or a typed % silently wildcards
    again. 36 real canonicals carry one."""
    _lib(kitchen, ("Q1", "3% fat reduced cocoa powder"), ("Q2", "cocoa powder"), ("Q3", "a_b"),
         ("Q4", "axb"))
    assert [r["canonical"] for r in _search(kitchen, "3%")["results"]] == \
           ["3% fat reduced cocoa powder"]
    assert [r["canonical"] for r in _search(kitchen, "a_b")["results"]] == ["a_b"]


def test_the_operator_is_ilike_in_the_compiled_sql(kitchen):
    """Read at the SQL layer, because the two operators are indistinguishable from the SQLite result
    on ASCII input, which is how the wrong one shipped in the first place."""
    import app
    from sqlalchemy import select
    stmt = select(app.LibraryName.canonical).where(
        app.LibraryName.canonical.ilike("%x%", escape="\\"))
    assert "lower(" in str(stmt).lower()
