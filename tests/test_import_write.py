"""Phase 15 — import write layer (import_write).

The dangerous failure here is the WRITE: a wrong field mapping or a dropped line silently
corrupts an imported recipe, and a missed dedup duplicates one. So the weight is on the pure
write PLAN — field mapping, slug minting + collisions, the uid-dedup skip, the rating CHECK
guard, and "nothing is ever dropped" — plus end-to-end commits against a throwaway DB."""
import pytest

import import_cleanup as cleanup
import import_write as iw
from fixtures import TEST_RECIPES


def _norm(**over):
    """A normalized recipe (reader's shape); override any field. Mirrors test_import_cleanup."""
    base = dict(
        name="X", uid="u", hash="h", ingredient_lines=[], directions=[],
        servings_raw="", categories=[], source="", source_url="", notes="",
        description="", rating=0, prep_time="", cook_time="", total_time="",
        images=[], primary_photo=None,
    )
    base.update(over)
    return base


def _cleaned(**over):
    return cleanup.clean_recipe(_norm(**over))


def _plan(cleaned, uid_index=None, taken=None):
    return iw.plan_recipe(cleaned, uid_index or {}, set() if taken is None else taken)


# ----------------------------------------------------------------- slug minting (the PK)
def test_mint_slug_basic():
    assert iw.mint_slug("Acqua Pazza", set()) == "acqua-pazza"


def test_mint_slug_punctuation_and_unicode():
    assert iw.mint_slug("Mom's Thai-Style Curry!", set()) == "mom-s-thai-style-curry"
    assert iw.mint_slug("Açaí Bowl", set()) == "acai-bowl"     # accents folded, not dropped


def test_mint_slug_collision_appends_and_grows_taken():
    taken = {"acqua-pazza"}
    assert iw.mint_slug("Acqua Pazza", taken) == "acqua-pazza-2"
    assert iw.mint_slug("Acqua Pazza", taken) == "acqua-pazza-3"   # taken grew between calls


def test_mint_slug_empty_name_falls_back():
    assert iw.mint_slug("!!!", set()) == "recipe"


# ----------------------------------------------------------------- field mapping
def test_plan_maps_recipe_fields():
    c = _cleaned(name="Acqua Pazza", source="Bon Appétit", source_url="http://x",
                 categories=["Fish", "Italian"], servings_raw="Serves 4",
                 prep_time="10 min", description="d", notes="n", uid="U1", hash="H1")
    r = _plan(c)["recipe"]
    assert r["id"] == "acqua-pazza"
    assert r["author"] == "Bon Appétit"          # Paprika source -> author
    assert r["category"] == "Fish · Italian"      # list joined with the · convention
    assert r["servings"] == "4"                   # parsed
    assert r["source"] == "app"
    assert r["uid"] == "U1" and r["hash"] == "H1"
    assert r["image"] is None                     # full image storage is a later pass


def test_plan_servings_blank_when_unparsed():
    assert _plan(_cleaned(servings_raw="a few"))["recipe"]["servings"] is None


def test_plan_category_none_when_empty():
    assert _plan(_cleaned(categories=[]))["recipe"]["category"] is None


def test_plan_category_strips_whitespace_and_drops_blanks():
    r = _plan(_cleaned(categories=["Fish ", " Italian", ""]))["recipe"]
    assert r["category"] == "Fish · Italian"


# ----------------------------------------------------------------- dedup (uid)
def test_plan_skips_when_uid_already_present():
    c = _cleaned(name="Thai BBQ Chicken", uid="21FB182C")
    p = _plan(c, uid_index={"21FB182C": ("gai-yang", "Thai BBQ Chicken (Gai Yang)")})
    assert p["decision"] == "skip"
    assert p["twin"]["slug"] == "gai-yang"        # names the twin it skipped


def test_plan_writes_when_uid_absent():
    assert _plan(_cleaned(uid="NEW"))["decision"] == "write"


# ----------------------------------------------------------------- nothing dropped
def test_plan_keeps_every_line_incl_sections_and_flagged():
    c = _cleaned(ingredient_lines=["SAUCE:", "2 tbsp oil", "2 x 6oz fillets", "For garnish"])
    rows = _plan(c)["ingredients"]
    assert len(rows) == 4                                   # nothing dropped
    assert rows[0]["is_heading"] == 1                       # section -> heading
    assert rows[1]["is_heading"] == 0 and rows[1]["qty"] == "2 tbsp"
    assert rows[2]["raw_text"] == "2 x 6oz fillets"         # flagged line preserved verbatim
    assert rows[2]["qty"] is None                           # couldn't parse -> raw_text carries it


def test_plan_bold_colon_heading_stored_clean():
    # "**Other Ingredients:**" -> heading; raw_text drops the ** wrapper (reading renders raw_text)
    rows = _plan(_cleaned(ingredient_lines=["**Other Ingredients:**", "2 tbsp oil"]))["ingredients"]
    assert rows[0]["is_heading"] == 1
    assert rows[0]["raw_text"] == "Other Ingredients:"       # clean, no markers
    assert rows[0]["label"] is None


def test_plan_ingredient_footnote_raw_text_preserved():
    # a trailing-* footnote is an INGREDIENT; the original-line contract is intact (markers kept)
    rows = _plan(_cleaned(ingredient_lines=["2 teaspoons salt*"]))["ingredients"]
    assert rows[0]["is_heading"] == 0
    assert rows[0]["raw_text"] == "2 teaspoons salt*"        # original preserved verbatim


def test_plan_flagged_line_enters_review_queue():
    p = _plan(_cleaned(ingredient_lines=["2 x 6oz halibut fillets"], directions=["Cook it."]))
    line_flags = [f for f in p["review_flags"] if f["position"] is not None]
    assert "multiplier" in [f["flag"] for f in line_flags]
    assert all(f["position"] == 0 for f in line_flags)   # line flag carries its line's position


def test_plan_ingredient_id_always_null():
    rows = _plan(_cleaned(ingredient_lines=["2 tbsp oil"]))["ingredients"]
    assert rows[0]["ingredient_id"] is None                # linkage = separate later pass


# ----------------------------------------------------------------- steps
def test_plan_step_section_header_marked():
    steps = _plan(_cleaned(directions=["For the sauce:", "Simmer gently."]))["steps"]
    assert steps[0]["is_heading"] == 1
    assert steps[1]["is_heading"] == 0


def test_plan_steps_plain_no_markup():
    steps = _plan(_cleaned(directions=["Add the [[garlic]] and stir."]))["steps"]
    assert steps[0]["text"] == "Add the [[garlic]] and stir."   # carried as-is, not converted


# ----------------------------------------------------------------- rating CHECK guard
@pytest.mark.parametrize("rating,expected", [(0, None), (None, None), (3, 3), (5, 5), (6, None)])
def test_plan_rating_guard(rating, expected):
    assert _plan(_cleaned(rating=rating))["rating"] == expected


# ----------------------------------------------------------------- incomplete recipes
def test_plan_incomplete_carries_recipe_flags_to_queue():
    p = _plan(_cleaned(ingredient_lines=[], directions=[]))
    assert {"no_ingredients", "no_directions"} <= set(p["recipe_flags"])
    recipe_level = [f for f in p["review_flags"] if f["position"] is None]
    assert {f["flag"] for f in recipe_level} == {"no_ingredients", "no_directions"}


def test_plan_photo_only_still_writes():
    p = _plan(_cleaned(ingredient_lines=[], directions=[], images=[{"bytes": 1}]))
    assert p["decision"] == "write"                        # never dropped
    assert "photo_only" in p["recipe_flags"]


# ----------------------------------------------------------------- grams-declined soft flag
def test_plan_grams_declined_flagged_but_line_still_written():
    line = '2/3 cup chillies (1/2 cup (15g) once soaked)'
    p = _plan(_cleaned(ingredient_lines=[line]))
    assert len(p["ingredients"]) == 1                      # written as a normal ingredient
    assert "grams_declined" in [f["flag"] for f in p["review_flags"]]


# ----------------------------------------------------------------- end-to-end commit (throwaway DB)
def test_commit_writes_all_tables(kitchen):
    c = _cleaned(name="Acqua Pazza", source="BA", categories=["Fish"],
                 ingredient_lines=["SAUCE:", "2 tbsp oil", "2 x 6oz fillets"],
                 directions=["Step one.", "Step two."], rating=4, servings_raw="4",
                 uid="ACQUA-UID", hash="HH")
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        rec = conn.execute(
            "SELECT source, uid FROM recipes WHERE id='acqua-pazza'").fetchone()
        assert rec["source"] == "app" and rec["uid"] == "ACQUA-UID"
        assert conn.execute(
            "SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id='acqua-pazza'"
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT COUNT(*) FROM recipe_steps WHERE recipe_id='acqua-pazza'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT rating FROM ratings WHERE recipe_id='acqua-pazza'").fetchone()[0] == 4
        assert conn.execute(
            "SELECT COUNT(*) FROM import_flags WHERE recipe_id='acqua-pazza'"
        ).fetchone()[0] >= 1


# ----------------------------------------------------------------- O-a: original-baseline snapshot
def test_commit_writes_original_snapshot(kitchen):
    # Every imported recipe gets a reason='original' baseline snapshot (cook-less), captured atomically
    # in the same import transaction — the pristine content the annotations (O-c) diff the current against.
    c = _cleaned(name="Original Dish", ingredient_lines=["2 tbsp oil"], directions=["Step one."], uid="ORIG-UID")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT cook_log_id, reason, content FROM recipe_snapshots WHERE recipe_id='original-dish'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "original"
    assert rows[0]["cook_log_id"] is None                  # cook-less baseline
    assert '"name":"Original Dish"' in rows[0]["content"]   # the pristine content captured


def test_original_blob_matches_orm_serialization(kitchen):
    # THE load-bearing Option-A test: the import-plan-serialized ORIGINAL blob and the ORM
    # serialize_recipe_content blob for the SAME recipe are BYTE-IDENTICAL. Both route through the single
    # shared formatter (snapshot_serialize.content_blob), so an import-origin original diffs cleanly against
    # an app-origin current — a drifted format would break the annotations diff for import-origin recipes.
    import app
    c = _cleaned(name="Byte Dish", source="BA", categories=["Fish"],
                 ingredient_lines=["SAUCE:", "2 tbsp oil", "1 cup water"],
                 directions=["Mix.", "Bake."], servings_raw="4", uid="BYTE-UID")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        import_blob = conn.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id='byte-dish' AND reason='original'"
        ).fetchone()["content"]
    with app.orm_session() as s:
        orm_blob = app.serialize_recipe_content(s, "byte-dish")
    assert import_blob == orm_blob                          # byte-identical -> the diff won't drift by origin


def test_commit_skip_writes_nothing(kitchen):
    # a real tagged seed twin uid -> dedup must skip and write nothing
    c = _cleaned(name="Dup", uid="21FB182C-8CED-4E3A-B20C-893310AA4631")
    uid_index, taken = iw.db_state(kitchen.db)
    plan = iw.plan_recipe(c, uid_index, taken)
    assert plan["decision"] == "skip"
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is False
        s.commit()
    with kitchen.conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recipes WHERE name='Dup'").fetchone()[0] == 0


def test_commit_rating_zero_writes_no_ratings_row(kitchen):
    c = _cleaned(name="Unrated Dish", rating=0, ingredient_lines=["1 egg"], directions=["Cook."])
    plan = _plan(c)
    with kitchen.session() as s:
        iw.commit_plan(s, plan)
        s.commit()
    with kitchen.conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE recipe_id=?", (plan["recipe"]["id"],)
        ).fetchone()[0] == 0


def test_commit_persists_harvested_grams_and_clean_label(kitchen):
    # end-to-end: FIX 1 (gram-paren stripped from the label) + FIX 2 (gram value persisted)
    c = _cleaned(name="Hummus Test", ingredient_lines=["14 cups (250g) dried chickpeas"],
                 directions=["Blend."])
    plan = _plan(c)
    with kitchen.session() as s:
        iw.commit_plan(s, plan)
        s.commit()
    with kitchen.conn() as conn:
        row = conn.execute(
            "SELECT label, grams, raw_text FROM recipe_ingredients WHERE recipe_id=? AND position=0",
            (plan["recipe"]["id"],)).fetchone()
    assert row["label"] == "dried chickpeas"             # FIX 1: harvested paren removed from name
    assert row["grams"] == 250.0                         # FIX 2: harvested gram persisted
    assert row["raw_text"] == "14 cups (250g) dried chickpeas"   # original preserved


def test_commit_persists_secondary_measure_both_orders(kitchen):
    # dual-measure capture lands grams + secondary_measure regardless of source order
    c = _cleaned(name="Dual Test", directions=["Mix."],
                 ingredient_lines=["100 g (1 cup) granulated sugar", "1 cup (250g) flour"])
    plan = _plan(c)
    with kitchen.session() as s:
        iw.commit_plan(s, plan)
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT label, grams, secondary_measure FROM recipe_ingredients "
            "WHERE recipe_id=? ORDER BY position", (plan["recipe"]["id"],)).fetchall()
    assert tuple(rows[0]) == ("granulated sugar", 100.0, "1 cup")   # weight-first
    assert tuple(rows[1]) == ("flour", 250.0, "1 cup")              # volume-first


# ----------------------------------------------------------------- W1 characterisation
# commit_plan's 7 raw-SQL statements are about to become SQLAlchemy Core inserts (forced: its `?` and
# `:named` placeholders are invalid for psycopg's pyformat, so it cannot run on Postgres, which is
# production). These tests pin WHAT IT WRITES, never HOW — no test below names sqlite3, a placeholder
# style, or a connection type on the WRITE side — so they must pass UNCHANGED after the conversion and
# are the reference it is checked against.
#
# The eight end-to-end tests above are already characterisation of this kind and are deliberately NOT
# duplicated here; these cover only what they leave untested: every recipe column (they assert 2 of 16),
# step text/heading/order (they only COUNT steps), the additive qty split, the snapshot's owner and
# timestamp, and the flag rows' position semantics.
def test_session_helper_lands_on_the_test_db(kitchen):
    """Kitchen.session() must obey the same redirect Kitchen.conn() does — this is what makes the
    conversion's call-site changes one-liners, so it is pinned before anything depends on it."""
    from sqlalchemy import text as sa_text
    with kitchen.session() as s:
        assert str(kitchen.db) in str(s.get_bind().url)          # the temp DB, never the real recipes.db
        assert s.execute(sa_text("SELECT COUNT(*) FROM recipes")).scalar() == len(TEST_RECIPES)


def test_commit_writes_every_recipe_column(kitchen):
    """All 16 recipe columns round-trip. The existing end-to-end test asserts source + uid only, so a
    conversion that dropped or mis-mapped any of the other 14 would pass it."""
    c = _cleaned(name="Full Dish", source="Some Book", source_url="https://example.test/r",
                 categories=["Fish", "Weeknight"], servings_raw="4", prep_time="10 min",
                 cook_time="25 min", total_time="35 min", description="A description.",
                 notes="Some notes.", rating=3, uid="FULL-UID", hash="FULL-HASH",
                 ingredient_lines=["2 tbsp oil"], directions=["Cook."])
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        r = conn.execute("SELECT * FROM recipes WHERE id='full-dish'").fetchone()
    assert r["name"] == "Full Dish"
    assert r["author"] == "Some Book"                    # cleanup's `source` -> the author column
    assert r["source_url"] == "https://example.test/r"
    assert r["category"] == "Fish \u00b7 Weeknight"         # list joined with the ' \u00b7 ' convention
    assert r["servings"] == "4"                          # parsed to an int, stored as text
    assert (r["prep_time"], r["cook_time"], r["total_time"]) == ("10 min", "25 min", "35 min")
    assert r["descr"] == "A description."                # `description` -> the descr column
    assert r["notes"] == "Some notes."
    assert r["image"] is None                            # image storage is a separate pass
    assert (r["uid"], r["hash"]) == ("FULL-UID", "FULL-HASH")
    assert r["source"] == "app"                          # imports are app-owned, never seed
    assert r["created_at"] == plan["recipe"]["created_at"]


def test_commit_writes_step_rows_text_heading_and_order(kitchen):
    """Step TEXT, is_heading and position ordering. The existing test only counts step rows.

    This is the highest-value new case: recipe_steps is the one table whose ORM attribute (`body`) is
    NOT its column name (`text`), so a Core insert written from the attribute name compiles to
    `Unconsumed column names: body` — or, if silently defaulted, writes the wrong thing."""
    c = _cleaned(name="Stepped Dish", ingredient_lines=["1 egg"],
                 directions=["PREP:", "Chop the onion.", "Cook it."])
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT position, is_heading, text FROM recipe_steps WHERE recipe_id='stepped-dish' "
            "ORDER BY position").fetchall()
    assert [tuple(r) for r in rows] == [
        (0, 1, "PREP:"),                                 # ALL-CAPS colon line -> a step heading
        (1, 0, "Chop the onion."),
        (2, 0, "Cook it."),
    ]


def test_commit_writes_every_ingredient_column(kitchen):
    """The ingredient columns the existing tests leave untested: the additive quantity/unit split,
    note, ingredient_id and explicit position ordering."""
    c = _cleaned(name="Cols Dish", directions=["Mix."],
                 ingredient_lines=["SAUCE:", "2 tbsp olive oil", "1 egg"])
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT position, is_heading, qty, quantity, unit, label, note, ingredient_id, raw_text "
            "FROM recipe_ingredients WHERE recipe_id='cols-dish' ORDER BY position").fetchall()
    assert rows[0]["is_heading"] == 1 and rows[0]["qty"] is None      # a heading carries no quantity
    assert rows[0]["raw_text"] == "SAUCE:"                            # heading text lives in raw_text
    assert rows[0]["label"] is None
    assert (rows[1]["qty"], rows[1]["quantity"], rows[1]["unit"]) == ("2 tbsp", "2", "tbsp")
    assert rows[1]["label"] == "olive oil"
    assert (rows[2]["qty"], rows[2]["quantity"], rows[2]["unit"]) == ("1", "1", "")
    assert [r["position"] for r in rows] == [0, 1, 2]                 # positions are dense + ordered
    assert all(r["note"] is None for r in rows)                       # note is never split out at import
    assert all(r["ingredient_id"] is None for r in rows)              # library linkage is a later pass


def test_commit_snapshot_carries_owner_and_recipe_created_at(kitchen):
    """The snapshot's user_id and created_at. The existing snapshot test asserts reason, cook_log_id
    and content, but not these two — and created_at is deliberately the RECIPE's birth timestamp
    rather than 'now', which a conversion could quietly change."""
    c = _cleaned(name="Owned Dish", ingredient_lines=["1 egg"], directions=["Cook."], uid="OWN-UID")
    plan = _plan(c)
    with kitchen.session() as s:
        owner = iw.resolve_owner(s)
        assert iw.commit_plan(s, plan, owner) is True
        s.commit()
    with kitchen.conn() as conn:
        row = conn.execute(
            "SELECT user_id, created_at, reason FROM recipe_snapshots WHERE recipe_id='owned-dish'"
        ).fetchone()
    assert row["user_id"] == owner
    assert row["created_at"] == plan["recipe"]["created_at"]     # the recipe's birth stamp, not now()
    assert row["reason"] == "original"


def test_commit_writes_exactly_one_original_snapshot(kitchen):
    """The invariant the WHERE-NOT-EXISTS guard protects: at most one reason='original' row per recipe.

    NB the guard's false branch is UNREACHABLE through commit_plan, which is create-only — a second
    call for the same recipe fails on the recipes PK long before reaching it (asserted below), which is
    exactly why the code calls it belt-and-suspenders. So what is pinned here is the invariant, plus the
    fact that a re-commit attempt leaves the existing snapshot untouched rather than adding a second."""
    c = _cleaned(name="Once Dish", ingredient_lines=["1 egg"], directions=["Cook."], uid="ONCE-UID")
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.session() as s:
        with pytest.raises(Exception):                   # recipes PK/uid collision, before the guard
            iw.commit_plan(s, plan)
        s.rollback()
    with kitchen.conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM recipe_snapshots WHERE recipe_id='once-dish' AND reason='original'"
        ).fetchone()[0] == 1


def test_commit_flag_rows_carry_position_and_reason(kitchen):
    """import_flags position semantics: a LINE flag carries its line's position, a RECIPE-level flag
    carries NULL. The existing tests assert flag NAMES and a count, never the position column that
    tells the two kinds apart — and backfill_headings joins on (recipe_id, position)."""
    c = _cleaned(name="Flagged Dish", ingredient_lines=["2 x 6oz fillets"], directions=[])
    plan = _plan(c)
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT position, flag, reason FROM import_flags WHERE recipe_id='flagged-dish'").fetchall()
    line = [r for r in rows if r["position"] is not None]
    recipe = [r for r in rows if r["position"] is None]
    assert [r["flag"] for r in line] == ["multiplier"]
    assert line[0]["position"] == 0                      # the flagged line's own position
    assert line[0]["reason"]                             # a human hint is carried, not NULL
    assert "no_directions" in [r["flag"] for r in recipe]
    assert all(r["reason"] is None for r in recipe)      # recipe-level flags carry no reason


def test_commit_section_suggested_heading_and_mult_one(kitchen):
    c = _cleaned(name="Promote Test", directions=["Mix."],
                 ingredient_lines=["crust", "1 x 397 grams can of condensed milk"])
    plan = _plan(c)
    with kitchen.session() as s:
        iw.commit_plan(s, plan)
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT is_heading, qty, label, grams FROM recipe_ingredients "
            "WHERE recipe_id=? ORDER BY position", (plan["recipe"]["id"],)).fetchall()
        flags = [r[0] for r in conn.execute(
            "SELECT flag FROM import_flags WHERE recipe_id=?", (plan["recipe"]["id"],))]
    assert rows[0]["is_heading"] == 1                        # "crust" promoted to a heading
    assert "section_suggested" in flags
    assert tuple(rows[1])[1:] == ("1 can", "condensed milk", 397.0)   # N=1 multiplier resolved


def test_import_populates_quantity_unit():
    """The import write splits qty into quantity+unit from the line dict's ALREADY-separate parts
    (no re-parse): quantity=amount, unit=unit; they recombine to qty. None when there's no qty."""
    import re
    plan = _plan(_cleaned(ingredient_lines=[
        "2 tbsp extra virgin olive oil", "1 cup flour", "salt",
    ]))
    rows = plan["ingredients"]
    norm = (lambda s: re.sub(r"\s+", " ", s or "").strip())
    for r in rows:                                           # recombine holds for every row
        assert norm(f"{r['quantity'] or ''} {r['unit'] or ''}") == norm(r["qty"] or "")
    olive = next(r for r in rows if "olive" in (r["raw_text"] or ""))
    assert (olive["qty"], olive["quantity"], olive["unit"]) == ("2 tbsp", "2", "tbsp")
    salt = next(r for r in rows if r["raw_text"] == "salt")  # no amount -> all None (no qty)
    assert (salt["qty"], salt["quantity"], salt["unit"]) == (None, None, None)
