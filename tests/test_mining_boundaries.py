"""The machine-checked half of docs/mining-decision.md.

⚠️ THESE TESTS ARE THE AUTHORIZATION GATE. The decision says a boundary with no test beside it is
not yet a boundary, and that extraction is blocked until boundary (g) has one. This file is that
test. It is written BEFORE the first extraction rather than after, because a boundary retrofitted
to a schema that already broke it is not a boundary.

⚠️ IT CHECKS EVERY DATABASE THE PROJECT OWNS, and that is not a flourish. The first version of
test_mined_tables_hold_no_corpus_text ran only against the sources.db fixture. Mined facts key on
library_id and would live in recipes.db, which has all 13 library_* tables while sources.db has
none, so that test guarded a database the mined tables will never appear in. It would have passed
vacuously forever. Anything named mined_* is checked wherever it turns up.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import brand_guard  # noqa: E402
import build_sources_db as bsd  # noqa: E402
from harness import make_kitchen  # noqa: E402

MINED_PREFIX = "mined_"
# ⚠️ A COLUMN GETS ON THIS LIST BY A DECISION, NEVER BY BEING CONVENIENT. Each one holds a value
#    from a vocabulary this repo declares, not a span the extractor read. Two were added for the
#    substitution work in migration 037 and both are checked further down:
#      pattern   the name of the rule that fired, one of five labels in substitution_run.RULES.
#                test_a_stored_pattern_is_a_rule_label_not_a_sentence asserts the vocabulary.
#      origin    mined-confirmed or authored, which says who decided, not what the corpus said.
ALLOWED_MINED_TEXT_COLS = {"source_slug", "source_url", "library_id", "a_id", "b_id",
                           "from_id", "to_id", "dish_type", "method", "role", "cuisine",
                           "technique", "course", "fact_kind", "pattern", "origin"}
# the columns a mined fact would carry a NAME in, which is what the brand check reads
NAME_COLS = {"library_id", "a_id", "b_id", "from_id", "to_id", "dish_type", "name", "canonical"}


# ⚠️ A PREFIX IS A NAMING CONVENTION AND WAS DOING SECURITY WORK. Anything corpus-derived that
#    happened to be called library_something was invisible to this scan and passed the checks
#    without being looked at. Proved rather than supposed: a table named library_substitutions
#    carrying a free-text `note` column was waved through, while the identical table named
#    mined_substitution_candidates was refused.
#
#    So a table is guarded by a DECISION recorded here, not by what somebody called it. Add a
#    table to this list when it will hold anything derived from the corpus, and add it BEFORE the
#    table exists. A guard added after the table it was meant to guard is not a guard.
GUARDED_TABLES = {
    # the substitution work of migration 037. Listed here BEFORE either table existed, and the
    # listing did its job on the day they arrived: library_substitutions.origin was refused on
    # sight, before a single row could be loaded into it.
    "library_substitutions",              # confirmed facts, replayed from hand_substitutions.csv
    "mined_substitution_candidates",      # the queue. The prefix reaches it, the decision is here
    "library_substitution_candidates",    # in case the candidate table is ever renamed off mined_
}


def mined_tables(conn):
    """Every table the boundary checks must read: the mined_ prefix plus the declared list."""
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return sorted({t for t in have if t.startswith(MINED_PREFIX)} | (have & GUARDED_TABLES))


@pytest.fixture
def dbs(tmp_path):
    """Every database the project owns, so a mined table cannot hide in one of them."""
    kdir = tmp_path / "k"
    kdir.mkdir()
    k = make_kitchen(kdir)
    recipes = sqlite3.connect(str(k.db))
    sources = sqlite3.connect(bsd.build(tmp_path / "sources.db"))
    yield {"recipes.db": recipes, "sources.db": sources}
    recipes.close(); sources.close()


def check_no_corpus_text(conn):
    for t in mined_tables(conn):
        cols = list(conn.execute(f"PRAGMA table_info({t})"))
        for col in cols:
            name, decl = col[1], (col[2] or "").upper()
            if "CHAR" in decl or "TEXT" in decl or "CLOB" in decl:
                assert name in ALLOWED_MINED_TEXT_COLS, (
                    f"{t}.{name} is a free-text column on a mined table. Facts leave the "
                    f"extractor as tuples and the sentence is never retained. "
                    f"docs/mining-decision.md boundary (b) and (f).")
        assert "n" in {c[1] for c in cols}, (
            f"{t} has no `n` column. Boundary (c): only aggregates across recipes are stored, "
            f"and a row that cannot say how many recipes it came from is not an aggregate.")


def check_no_brand_names(conn, brands=None):
    b = brands if brands is not None else brand_guard.load_brands()
    assert b, "brands.csv is empty or missing. Boundary (g) has no list to enforce."
    for t in mined_tables(conn):
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})")]
        for col in [c for c in cols if c in NAME_COLS]:
            for (v,) in conn.execute(f"SELECT DISTINCT {col} FROM {t} WHERE {col} IS NOT NULL"):
                verdict, mark = brand_guard.classify(v, brands=b)
                assert verdict != "brand", (
                    f"{t}.{col} holds {v!r}, which is the mark {mark}. Boundary (g): a brand is "
                    f"never stored as a generic ingredient or dish type, and it is not mapped to "
                    f"a near neighbor either.")


def test_mined_tables_hold_no_corpus_text(dbs):
    for name, conn in dbs.items():
        check_no_corpus_text(conn)


def test_mined_facts_carry_no_brand_names(dbs):
    """⚠️ BOUNDARY (g). This test existing is what unblocks extraction."""
    for name, conn in dbs.items():
        check_no_brand_names(conn)


# ── the list itself has to hold up, or the test above enforces nothing ──────────────────────

def test_brand_list_loads_and_is_not_trivially_small():
    b = brand_guard.load_brands()
    assert len(b) >= 40, f"only {len(b)} surface forms. The probe found more than that."
    assert len(set(b.values())) >= 20, "too few distinct marks to be the real list"


def test_known_marks_are_caught_in_every_surface_form_seen():
    for form in ("velveeta", "velveeta cheese", "crisco", "crisco oil", "strawberry jello",
                 "jell o", "bisquick mix", "campbell s tomato soup", "cool whip", "oreos"):
        assert brand_guard.is_brand(form), f"{form!r} is a mark and was not caught"


def test_the_guarded_list_covers_a_table_the_prefix_would_miss():
    """⚠️ THE GAP THIS CLOSES. A corpus-derived table named library_* used to be invisible.

    Three cases, because the list is only useful if it catches what the prefix misses AND leaves
    everything else alone.
    """
    db = sqlite3.connect(":memory:")
    # 1. a DECLARED library_ table holding free text is now seen, and refused
    db.execute("CREATE TABLE library_substitutions (from_id TEXT, to_id TEXT, n INTEGER, "
               "note TEXT)")
    assert "library_substitutions" in mined_tables(db), "the declared table must be scanned"
    with pytest.raises(AssertionError):
        check_no_corpus_text(db)

    # 2. an undeclared text column is refused even when the name sounds harmless. `source_text`
    #    is the erosion boundary (b) actually describes: source_slug is allowed, so a column one
    #    word away from it reads as a small extension and is the whole sentence.
    db2 = sqlite3.connect(":memory:")
    db2.execute("CREATE TABLE library_substitutions (from_id TEXT, to_id TEXT, n INTEGER, "
                "source_text TEXT)")
    with pytest.raises(AssertionError):
        check_no_corpus_text(db2)

    # 3. an ORDINARY library table, not corpus-derived and not listed, is untouched
    db3 = sqlite3.connect(":memory:")
    db3.execute("CREATE TABLE library_entries (entry_id TEXT, name TEXT, scope_note TEXT)")
    assert mined_tables(db3) == [], "an unlisted library table must not be scanned"
    check_no_corpus_text(db3)          # no exception


# ── the substitution tables, migration 037 ─────────────────────────────────────────────────────

def has(conn, table):
    """sources.db carries none of the library tables, so a check that assumes one is there fails
    on the wrong database rather than on the thing it guards."""
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (table,)).fetchone())


def live_db():
    """The real catalog, when there is one. A fixture DB has the tables and no rows, so a check
    written only against it is vacuous and proves nothing about what got loaded."""
    live = BASE / "recipes.db"
    if not live.exists():
        pytest.skip("no live catalog here")
    return sqlite3.connect(f"file:{live}?mode=ro", uri=True)


def check_patterns(conn):
    """⚠️ THE PATTERN COLUMN IS A CLOSED VOCABULARY, AND THIS IS WHAT CLOSES IT.

    Labels are read from substitution_run.RULES rather than copied here, so renaming a rule
    cannot leave the test asserting a vocabulary the extractor stopped using. Same idea as
    tests/js/factor-sync.test.js, which keeps scaler.js honest against weights.py."""
    import substitution_run
    ok = {name for name, _ in substitution_run.RULES}
    assert len(ok) == 5, f"expected five rules, found {len(ok)}"
    if not has(conn, "mined_substitution_candidates"):
        return
    for (v,) in conn.execute("SELECT DISTINCT pattern FROM mined_substitution_candidates"):
        for lab in (v or "").split("+"):
            assert lab in ok, (
                f"pattern {v!r} carries {lab!r}, which is not one of the rule labels "
                f"{sorted(ok)}. Boundary (b): the column holds the name of the rule that fired, "
                f"never the clause it read.")


def test_a_stored_pattern_is_a_rule_label_not_a_sentence(dbs):
    for conn in dbs.values():
        check_patterns(conn)
    conn = live_db()
    n = conn.execute("SELECT COUNT(*) FROM mined_substitution_candidates").fetchone()[0]
    check_patterns(conn)
    conn.close()
    assert n, "the live queue is empty, so the check above proved nothing about loaded rows"


def test_a_sentence_in_the_pattern_column_fails_the_check():
    """The check above is only worth having if it catches the thing it exists for."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE mined_substitution_candidates (pattern TEXT)")
    db.execute("INSERT INTO mined_substitution_candidates VALUES "
               "('you can use margarine instead of butter')")
    with pytest.raises(AssertionError):
        check_patterns(db)


def test_the_confirmed_table_carries_no_note_column(dbs):
    """⚠️ A NOTE IS A PERSON'S WORDS AND LIVES IN hand_substitutions.csv.

    check_no_corpus_text already refuses an undeclared text column. This says the specific thing
    out loud, because `note` is the column somebody adds in good faith. It starts as somewhere to
    keep a reason and ends holding the sentence the extractor read.
    """
    for conn in dbs.values():
        for t in ("library_substitutions", "mined_substitution_candidates"):
            if not has(conn, t):
                continue
            cols = {c[1] for c in conn.execute(f"PRAGMA table_info({t})")}
            assert "note" not in cols, f"{t} grew a note column. It belongs in the hand file."


def test_a_one_to_many_candidate_is_flagged_rather_than_left_null(dbs):
    """⚠️ A NULL to_id IS A RECORDED GAP, NOT A MISSING VALUE.

    143 matches read as one ingredient replaced by two, which (from_id, to_id) cannot express.
    They are stored flagged so the queue shows the shape this schema cannot hold. A NULL without
    the flag would be indistinguishable from a load that half worked.
    """
    for conn in list(dbs.values()) + [live_db()]:
        if not has(conn, "mined_substitution_candidates"):
            continue
        bad = conn.execute(
            "SELECT COUNT(*) FROM mined_substitution_candidates "
            "WHERE (to_id IS NULL) <> (one_to_many=1)").fetchone()[0]
        assert bad == 0, f"{bad} candidate rows disagree about whether they are one-to-many"


def test_a_catalog_canonical_is_food_unless_its_exact_form_is_listed():
    """⚠️ THE LIBRARY DECIDES WHAT IS FOOD.

    An interior word span used to be enough to call a name a brand, and it cut three real rows.
    "Tabasco pepper" is Capsicum frutescens, the variety, where the mark covers the sauce.
    "Castagna del Monte Amiata PGI" and "Pecorino del Monte Poro" are a chestnut and a cheese,
    and "del Monte" is Italian for "of the mountain". No listed surface form is itself a catalog
    canonical, so deferring to the library lets nothing real through.
    """
    import sqlite3 as _s
    from pathlib import Path as _P
    live = _P(__file__).resolve().parent.parent / "recipes.db"
    if not live.exists():
        pytest.skip("no live catalog here, the rule is exercised by the unit cases below")
    conn = _s.connect(f"file:{live}?mode=ro", uri=True)
    chk = brand_guard.catalog_name_check(conn)
    blocked = [n for (n,) in conn.execute("SELECT canonical FROM library_names")
               if brand_guard.is_brand(n, is_catalog_name=chk)]
    conn.close()
    assert blocked == [], f"real catalog rows classified as brands: {blocked}"


def test_a_listed_mark_is_still_blocked_inside_a_longer_name():
    for n in ("velveeta cheese spread", "crisco shortening", "strawberry jello mix"):
        assert brand_guard.is_brand(n, is_catalog_name=lambda _s: False), f"{n!r} slipped through"


def test_generic_foods_are_never_blocked():
    """⚠️ DEFAULT IS KEEP, and these two are why the rule exists.

    The probe's heuristic called `oleo` and `graham cracker` brands, 9,016 of the 30,114
    occurrences it flagged, 29.9% of them. `oleo` is short for oleomargarine, a generic term for
    margarine. `graham cracker` is a generic food and the mark in that aisle is Honey Maid.
    Blocking either would have cut a real food out of the library.
    """
    for food in ("oleo", "graham cracker crumbs", "graham cracker crust", "butter", "pecans",
                 "ground beef", "hamburger", "cherries", "mayo", "pretzels", "crabmeat",
                 "cream style corn", "brussels sprouts"):
        assert not brand_guard.is_brand(food), f"{food!r} is a real food and was blocked"


def test_the_heuristic_flags_and_never_excludes():
    """An unlisted mark is SUSPECT, which is a review queue and not an exclusion."""
    for unlisted in ("hellmann s mayonnaise", "kraft brand cheddar", "newman s own dressing"):
        verdict, _ = brand_guard.classify(unlisted)
        assert verdict == "suspect", f"{unlisted!r} should be flagged, got {verdict}"
        assert not brand_guard.is_brand(unlisted), "a suspect must never be excluded"
