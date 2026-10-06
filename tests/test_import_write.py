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
        # ⚠️ An imported rating now rides on a COOK, not a recipe-level ratings row. A rating means
        # the dish was cooked, so the import records that cooking; 'rating-inferred' marks the date
        # as provisional. This is what keeps a verdict from existing with nothing behind it.
        cook = conn.execute(
            "SELECT rating, source FROM cook_log WHERE recipe_id='acqua-pazza'").fetchone()
        assert cook["rating"] == 4 and cook["source"] == "rating-inferred"
        assert conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE recipe_id='acqua-pazza'").fetchone()[0] == 0
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
    with kitchen.session() as s_:
        uid_index, taken = iw.db_state(s_)
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
            "SELECT position, is_heading, heading_level, text FROM recipe_steps "
            "WHERE recipe_id='stepped-dish' ORDER BY position").fetchall()
    assert [tuple(r) for r in rows] == [
        # ⚠️ "Prep:", NOT "PREP:". An ALL-CAPS colon line is still a heading, and the heading is now
        #    stored in sentence case (import_cleanup.plan_step_rows rule 5). The corpus had 49 of
        #    these shouting at the reader, and the repair pass and the importer share the rule so a
        #    recipe imported tomorrow matches the corpus that was just repaired.
        (0, 1, 1, "Prep:"),                              # a SECTION heading
        (1, 0, 1, "Chop the onion."),
        (2, 0, 1, "Cook it."),
    ]


def test_an_imported_lead_in_label_opens_a_section_then_the_next_sits_under_it(kitchen):
    """The shape birria-tacos and butter-chicken arrive in.

    ⚠️ ANDY'S LEVEL RULE, WHICH READS THE RECIPE AND NOT THE LABEL. The FIRST lifted label has
    nothing opening a group above it, so it opens one (level 1). The second now does have a section
    above it, so it belongs to that group (level 2). The step under each keeps the author's
    remaining words either way."""
    c = _cleaned(name="Labelled Dish", ingredient_lines=["1 egg"],
                 directions=["Deseed – Trim and discard the stems.",
                             "Bake for 30 – 35 minutes.",
                             "Marinade: Mix the chicken with the yogurt."])
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT position, is_heading, heading_level, text FROM recipe_steps "
            "WHERE recipe_id='labelled-dish' ORDER BY position").fetchall()
    assert [tuple(r) for r in rows] == [
        (0, 1, 1, "Deseed"),                 # the first heading: it opens the group
        (1, 0, 1, "Trim and discard the stems."),
        # ⚠️ A NUMERIC RANGE IS NOT A LABEL. Without that guard this row would have become a heading
        #    reading "Bake for 30" with "35 minutes." as the step under it.
        (2, 0, 1, "Bake for 30 – 35 minutes."),
        (3, 1, 2, "Marinade"),               # a section is open above it now, so it sits under it
        (4, 0, 1, "Mix the chicken with the yogurt."),
    ]


def test_an_imported_note_step_moves_into_the_notes(kitchen):
    """bagel's yeast note and KFC's serving note are both steps that are not instructions. They go
    where a reader looks for them, blank-line separated from whatever the publisher already wrote."""
    c = _cleaned(name="Noted Dish", ingredient_lines=["1 egg"],
                 directions=["Mix it.", "Note: Check your brand of yeast."], notes="Keeps 3 days.")
    plan = _plan(c)
    # ⚠️ THE LABEL COMES WITH IT. It is what the kind headers group on, and stripping it meant a
    #    "Tip:" step imported as bare prose and printed under Notes with no way back.
    assert plan["recipe"]["notes"] == "Keeps 3 days.\n\nNote: Check your brand of yeast."
    assert [r["text"] for r in plan["steps"]] == ["Mix it."]
    moved = [f for f in plan["review_flags"] if f["flag"] == "step_note_moved"]
    assert len(moved) == 1 and "Check your brand of yeast" in moved[0]["reason"]


def test_every_structural_conversion_reaches_the_review_queue(kitchen):
    """⚠️ THE QUEUE IS THE UNDO PATH. An importer that restructures a recipe silently leaves the
    owner with no way to know it happened, and the step row menu can only undo what they can see."""
    c = _cleaned(name="Flagged Dish", ingredient_lines=["1 egg"],
                 directions=["**FOR THE SAUCE**", "Simmer – Reduce by half.", "Tip: Use a wide pan."])
    plan = _plan(c)
    flags = {f["flag"] for f in plan["review_flags"]}
    assert {"step_heading_unwrapped", "step_label_lifted", "step_note_moved",
            "step_heading_recased"} <= flags


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


# ----------------------------------------------- the publisher's number, stored apart (item 9)

def test_source_rating_writes_its_own_row_and_never_a_cook(kitchen):
    """⚠️ A publisher's average and a cook's verdict must not meet. The snapshot lands in
    recipe_source_ratings with its scale and its date; cook_log stays empty because nobody cooked it."""
    c = _cleaned(name="Snapshot Dish", uid="SNAP-UID", source_url="https://www.kingarthurbaking.com/r/x",
                 ingredient_lines=["1 cup flour"], directions=["Mix."],
                 source_rating={"value": 4.7, "count": 885, "scale": 5.0, "scale_assumed": True})
    plan = _plan(c)
    rid = plan["recipe"]["id"]
    import app
    with app.orm_session() as s:
        assert iw.commit_plan(s, plan) is True
        s.commit()
    with kitchen.conn() as conn:
        row = conn.execute("SELECT * FROM recipe_source_ratings WHERE recipe_id=?", (rid,)).fetchone()
        assert (row["value"], row["rating_count"], row["scale"]) == (4.7, 885, 5.0)
        assert row["scale_assumed"] == 1                      # bestRating was absent -> a guess
        assert row["source_name"] == "kingarthurbaking.com"   # 'www.' dropped as noise
        assert row["captured_at"] == plan["recipe"]["created_at"]
        # the dish was never cooked, so there is no verdict anywhere
        assert conn.execute("SELECT COUNT(*) FROM cook_log WHERE recipe_id=?", (rid,)).fetchone()[0] == 0


def test_no_source_rating_writes_no_row(kitchen):
    """Paprika supplies none, so the common path must write nothing rather than a zero row."""
    plan = _plan(_cleaned(name="No Snapshot", uid="NOSNAP-UID",
                          ingredient_lines=["1 cup flour"], directions=["Mix."]))
    import app
    with app.orm_session() as s:
        iw.commit_plan(s, plan)
        s.commit()
    with kitchen.conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recipe_source_ratings WHERE recipe_id=?",
                            (plan["recipe"]["id"],)).fetchone()[0] == 0


def test_the_import_baseline_carries_the_inserted_row_ids(kitchen):
    """⚠️ A PLAN ROW HAS NO ID — IT DOES NOT EXIST UNTIL THE INSERT. commit_plan used to serialize the
    plan, which would now write a baseline full of nulls where the ids belong: every imported recipe
    would fail the byte-equal short-circuit on the day it landed, and the id-matched diff would have
    nothing to match on, permanently and invisibly. It reads the rows back instead."""
    import json
    c = _cleaned(name="Id Dish", source="BA", categories=["Fish"],
                 ingredient_lines=["SAUCE:", "2 tbsp oil", "1 cup water"],
                 directions=["Mix.", "Bake."], servings_raw="4", uid="ID-UID")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        doc = json.loads(conn.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id='id-dish' AND reason='original'"
        ).fetchone()["content"])
        live_ing = [r["id"] for r in conn.execute(
            "SELECT id FROM recipe_ingredients WHERE recipe_id='id-dish' ORDER BY position, id")]
        live_step = [r["id"] for r in conn.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id='id-dish' ORDER BY position, id")]
    assert live_ing and live_step
    assert [r["id"] for r in doc["ingredients"]] == live_ing
    assert [r["id"] for r in doc["steps"]] == live_step


# ------------------------------------------------- the notes are ROWS, and the importer makes them
# ⚠️ WHY THESE EXIST. The importer wrote recipes.notes as TEXT and no recipe_notes rows at all, and
# once get_recipe started serving notes from the rows that made every imported note invisible: the
# API returned "notes": [], the page showed nothing, and the first ordinary save rebuilt the derived
# column from 0 rows and deleted the publisher's text. The URL import path opens the recipe straight
# in the editor, so that save is the next thing that happens. This is clause (2) of FIX BY RULE, and
# the rule set is notes.paragraphs plus notes.kind_of, which is what moved the corpus.

def test_an_imported_recipe_s_notes_become_rows(kitchen):
    c = _cleaned(name="Noted Import", directions=["Mix."], uid="NOTE-UID",
                 notes="Flour. Use bread flour.\n\nStoring. Keeps three days.")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT position, kind, text, title FROM recipe_notes WHERE recipe_id='noted-import' "
            "ORDER BY position").fetchall()
    # ⚠️ THE TITLE RULE RUNS IN THE IMPORTER NOW, which is clause (2) of FIX BY RULE: a note
    #    imported today lands in the shape the 300 were moved into. "Flour" is a one-word name over
    #    a three-word body, so it is lifted and the body keeps the rest.
    assert [r["text"] for r in rows] == ["Use bread flour.", "Storing. Keeps three days."]
    assert [r["title"] for r in rows] == ["Flour", None]
    # the kind comes from the shared table, so a labelled paragraph lands under its own header
    # ⚠️ AND A KNOWN LABEL IS A KIND RATHER THAN A TITLE. "Storing" passes every title test on its
    #    shape, and promoting it would print a heading over a note already filed under Storage.
    assert [r["kind"] for r in rows] == ["notes", "storage"]

    # ⚠️ AND THE RECORD KEEPS THE PARAGRAPH THE TITLE WAS LIFTED FROM. recipe_notes_original has no
    #    title column on purpose: a title is a thing the app lifted out of the publisher's words.
    with kitchen.conn() as conn:
        orig = conn.execute(
            "SELECT position, text FROM recipe_notes_original WHERE recipe_id='noted-import' "
            "ORDER BY position").fetchall()
    assert [r["text"] for r in orig] == ["Flour. Use bread flour.", "Storing. Keeps three days."]

    # and the lift is in the review queue, because a person should see what was moved
    with kitchen.conn() as conn:
        flags = [r["flag"] for r in conn.execute(
            "SELECT flag FROM import_flags WHERE recipe_id='noted-import'").fetchall()]
    assert "note_title_lifted" in flags, flags


def test_an_imported_recipe_s_notes_survive_the_first_save(kitchen):
    """The failure this closes: the editor sends back what the API gave it, so with 0 rows it sent
    notes: [] and the column was rebuilt as NULL."""
    import harness
    c = _cleaned(name="Saved Import", directions=["Mix."], uid="SAVE-UID",
                 notes="Keep this paragraph.")
    # Owned by the client's own user, the way the URL import route does it (app.py sets
    # plan["recipe"]["owner"] before committing), because the SAVE is what this test is about.
    uid = harness.ensure_test_user()
    plan = _plan(c)
    plan["recipe"]["owner"] = uid
    with kitchen.session() as s:
        assert iw.commit_plan(s, plan, owner_id=uid) is True
        s.commit()
    d = kitchen.client.get("/api/recipes/saved-import").get_json()
    assert [n["text"] for n in d["notes"]] == ["Keep this paragraph."]
    r = kitchen.client.put("/api/recipes/saved-import", json={
        "name": d["recipe"]["name"],
        "ingredients": [],
        "steps": [{"id": s_["id"], "text": s_["text"]} for s_ in d["steps"]],
        "notes": [{"text": n["text"], "kind": n["kind"],
                   "step_id": n["step_id"], "refs": n.get("refs") or []} for n in d["notes"]]})
    assert r.status_code == 200, r.get_json()
    after = kitchen.client.get("/api/recipes/saved-import").get_json()
    assert [n["text"] for n in after["notes"]] == ["Keep this paragraph."]


def test_an_imported_note_that_names_a_step_is_recorded_and_flagged_not_guessed(kitchen):
    """⚠️ THE NUMBER IS THE AUTHOR'S. It is counted over the list they wrote, and the app's own
    numbering has already moved away from it. The reference row keeps the mention's ordinal with
    step_id NULL, and the recipe is flagged so a person decides."""
    c = _cleaned(name="Mention Import", directions=["Mix.", "Bake."], uid="MENT-UID",
                 notes="Tip. Do this before step 2.")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        refs = conn.execute(
            "SELECT r.ref_index, r.match_text, r.step_id FROM recipe_note_step_refs r "
            "JOIN recipe_notes n ON n.id=r.note_id WHERE n.recipe_id='mention-import'").fetchall()
        flags = [r["flag"] for r in conn.execute(
            "SELECT flag FROM import_flags WHERE recipe_id='mention-import'").fetchall()]
    assert [(r["ref_index"], r["match_text"], r["step_id"]) for r in refs] == [(0, "step 2", None)]
    assert "note_step_mention" in flags


def test_an_imported_recipe_is_byte_equal_to_its_own_baseline(kitchen):
    """The baseline has to describe the note ROWS, or an imported recipe with notes never matches
    its own origin and carries a permanent invisible handicap: the diff runs on every page view."""
    import app
    c = _cleaned(name="Baseline Notes", directions=["Mix."], uid="BLN-UID",
                 notes="One paragraph.\n\nTip. Another one.")
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        stored = conn.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id='baseline-notes' "
            "AND reason='original'").fetchone()["content"]
    with app.orm_session() as s:
        assert app.serialize_recipe_content(s, "baseline-notes") == stored
        assert app._recipe_annotations(s, "baseline-notes") == []


# ---- the title rule in the importer -------------------------------------------------------------

def _imported_notes(kitchen, notes, uid, slug):
    c = _cleaned(name=slug.replace("-", " ").title(), directions=["Mix."], uid=uid, notes=notes)
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT position, kind, text, title FROM recipe_notes WHERE recipe_id=? "
            "ORDER BY position", (slug,)).fetchall()]
        flags = [dict(r) for r in conn.execute(
            "SELECT flag, reason FROM import_flags WHERE recipe_id=?", (slug,)).fetchall()]
        orig = [r["text"] for r in conn.execute(
            "SELECT text FROM recipe_notes_original WHERE recipe_id=? ORDER BY position",
            (slug,)).fetchall()]
    return rows, flags, orig


def test_an_imported_note_wrapped_in_emphasis_marks_loses_them_and_keeps_the_record(kitchen):
    """⚠️ THE MARKS ARE TITLES IN MARKDOWN CLOTHING, which is what decided the rule. Every one of
    the corpus's note cases is a bold or italic line of its own over a body, and there is not one
    in-sentence emphasis in the 300 recipes."""
    rows, flags, orig = _imported_notes(
        kitchen, "**Chinese black vinegar**\nIt is made from fermented black rice.",
        "WRAP-UID", "wrap-import")
    assert [r["title"] for r in rows] == ["Chinese black vinegar"]
    assert [r["text"] for r in rows] == ["It is made from fermented black rice."]
    assert orig == ["**Chinese black vinegar**\nIt is made from fermented black rice."], \
        "the record has to keep the marks, or there is no way back to what arrived"
    assert any(f["flag"] == "step_heading_unwrapped" for f in flags), flags


def test_an_imported_note_the_rule_cannot_decide_is_flagged_and_stored_whole(kitchen):
    """DECLINE OVER GUESS. A title guessed here is a heading nothing on the page says is wrong."""
    rows, flags, _orig = _imported_notes(
        kitchen, "Made with Vedant and Sophia. It was a good evening.",
        "UNCLEAR-UID", "unclear-import")
    assert [r["title"] for r in rows] == [None]
    assert [r["text"] for r in rows] == ["Made with Vedant and Sophia. It was a good evening."]
    unclear = [f for f in flags if f["flag"] == "note_title_unclear"]
    assert unclear, flags
    assert "longer than a heading" in unclear[0]["reason"], unclear


def test_an_imported_note_with_a_tiny_body_takes_no_title_and_no_flag(kitchen):
    """french-baguette's note 69 is "If using fresh Yeast: 8g". A heading over an amount is worse
    than no heading, and the rule can say so, so there is nothing to ask a person."""
    rows, flags, _orig = _imported_notes(
        kitchen, "If using fresh Yeast: 8g", "TINY-UID", "tiny-import")
    assert [r["title"] for r in rows] == [None]
    assert [r["text"] for r in rows] == ["If using fresh Yeast: 8g"]
    assert not [f for f in flags if f["flag"].startswith("note_title")], flags


def test_the_title_rule_runs_before_the_step_mentions_are_scanned(kitchen):
    """⚠️ THE ORDER IS THE POINT. The rule takes a label off the FRONT of the text, so a mention's
    ordinal counted over the old string would belong to words that are no longer there."""
    rows, _flags, _orig = _imported_notes(
        kitchen, "Shaping: fold it over, then proceed with step 3 as written.",
        "ORDER-UID", "order-import")
    assert [r["title"] for r in rows] == ["Shaping"]
    assert rows[0]["text"] == "Fold it over, then proceed with step 3 as written."
    with kitchen.conn() as conn:
        refs = [dict(r) for r in conn.execute(
            "SELECT r.match_text, r.step_id FROM recipe_note_step_refs r "
            "JOIN recipe_notes n ON n.id = r.note_id WHERE n.recipe_id='order-import'").fetchall()]
    assert [r["match_text"] for r in refs] == ["step 3"]
    assert [r["step_id"] for r in refs] == [None], "the number is the author's, so it is unresolved"
    # ⚠️ AND THE FIRST LETTER IS CAPITALIZED IN THE BODY, NOT IN THE LABEL. Capitalizing before the
    #    lift would have put the capital on "Shaping" and left "fold" lowercase on the page.
    assert rows[0]["text"][0] == "F"


def test_an_imported_note_with_a_known_label_gets_the_kind_and_no_title(kitchen):
    rows, flags, _orig = _imported_notes(
        kitchen, "Freezing - cool them first, then freeze on a tray in one layer.",
        "KIND-UID", "kind-import")
    assert [r["kind"] for r in rows] == ["storage"]
    assert [r["title"] for r in rows] == [None]
    assert rows[0]["text"].startswith("Freezing - "), "the author's words stay, label and all"
    assert not [f for f in flags if f["flag"].startswith("note_title")], flags


def test_an_ordinary_note_is_untouched_and_its_record_is_what_it_always_was(kitchen):
    """The regression that matters most: the overwhelming majority of imported notes have no title
    in them, and this round must leave every one of them exactly as it was."""
    rows, flags, orig = _imported_notes(
        kitchen, "Keep this paragraph as it is written.", "PLAIN-UID", "plain-import")
    assert [r["title"] for r in rows] == [None]
    assert [r["text"] for r in rows] == ["Keep this paragraph as it is written."]
    assert orig == ["Keep this paragraph as it is written."]
    # ⚠️ THE TITLE FLAGS, NOT THE WHOLE QUEUE. This fixture carries no ingredients, so the recipe
    #    always has a `no_ingredients` flag, and asserting over the list would make this test about
    #    the fixture's shape rather than about the rule.
    assert [f for f in flags if f["flag"].startswith("note_")] == [], flags
    assert [f for f in flags if f["flag"] == "step_heading_unwrapped"] == [], flags


def test_an_imported_abbreviation_is_not_promoted_to_a_title(kitchen):
    """⚠️ THE IMPORTER WAS THE DOOR THIS CAME THROUGH, so it is stated here as well as on the rule.
    "Mrs. Smith gave me this recipe" came out as title "Mrs" over "Smith gave me this recipe",
    which is a heading the author never wrote and a decapitated sentence."""
    rows, flags, orig = _imported_notes(
        kitchen, "Mrs. Smith gave me this recipe years ago in Kerala.",
        "ABBREV-UID", "abbrev-import")
    assert [r["title"] for r in rows] == [None]
    assert [r["text"] for r in rows] == ["Mrs. Smith gave me this recipe years ago in Kerala."]
    assert orig == ["Mrs. Smith gave me this recipe years ago in Kerala."]
    assert [f for f in flags if f["flag"].startswith("note_title")] == [], flags


def test_an_imported_parenthetical_dash_is_not_promoted_to_a_title(kitchen):
    rows, flags, _orig = _imported_notes(
        kitchen, "Salt — and this is important — goes in at the very end.",
        "PAREN-UID", "paren-import")
    assert [r["title"] for r in rows] == [None]
    assert rows[0]["text"] == "Salt — and this is important — goes in at the very end."
    assert [f for f in flags if f["flag"].startswith("note_title")] == [], flags


def _imported_lines(kitchen, lines, uid, slug):
    c = _cleaned(name=slug.replace("-", " ").title(), directions=["Mix."], uid=uid,
                 ingredient_lines=lines)
    with kitchen.session() as s:
        assert iw.commit_plan(s, _plan(c)) is True
        s.commit()
    with kitchen.conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT position, is_heading, raw_text, qty, label FROM recipe_ingredients "
            "WHERE recipe_id=? ORDER BY position", (slug,)).fetchall()]
        flags = [r["flag"] for r in conn.execute(
            "SELECT flag FROM import_flags WHERE recipe_id=?", (slug,)).fetchall()]
    assert rows, f"no ingredient rows were written for {slug}"   # a check that read nothing fails
    return rows, flags


def test_a_wrapped_ingredient_heading_loses_its_marks_on_import(kitchen):
    """⚠️ CLAUSE (2) OF FIX BY RULE FOR THE ROUND'S OTHER TWO ROWS. The pass strips the wrapping
    emphasis off brioche-cinnamon-rolls' ingredient headings 9213 and 9217, and nothing in the
    importer did the same, so re-importing that recipe put both marks straight back. Measured in
    review: "_Cinnamon Filling_" classified as a section WITH its underscores, and
    "**Vanilla Cream Cheese Icing**" was not read as a section at all."""
    rows, flags = _imported_lines(
        kitchen, ["_Cinnamon Filling_", "200 g flour"], "IHEAD-UID", "ihead")
    head = next(r for r in rows if r["is_heading"])
    assert head["raw_text"] == "Cinnamon Filling", rows
    assert "cleaned_emphasis_wrap" in flags, flags


def test_a_wrapped_heading_the_classifier_cannot_place_reaches_the_queue_with_clean_words():
    """The second of brioche-cinnamon-rolls' two rows, and it stops one step short of the first.

    ⚠️ raw_text IS THE PUBLISHER'S BYTES FOR A LINE AND THE CLEAN NAME FOR A HEADING, which is the
    writer's existing design and not something this round changed. So "_Cinnamon Filling_" is read
    as a section and stored clean (the test above), while "**Vanilla Cream Cheese Icing**" is only
    FLAGGED as an ambiguous section, and a flagged row's raw_text keeps the markup. What the unwrap
    buys for the second one is that every parsed field a person reviews is clean, so the decision is
    made about the words rather than about the markup. Stated as the limit it is."""
    res = cleanup.classify_line("**Vanilla Cream Cheese Icing**")
    assert res["kind"] == "flagged" and "ambiguous_section" in res["flags"], res
    assert res["name"] == "Vanilla Cream Cheese Icing", res
    assert "cleaned_emphasis_wrap" in res["flags"], res
    # and the first one IS placed, which is the difference
    assert cleanup.classify_line("_Cinnamon Filling_")["kind"] == "section"


def test_a_footnote_marker_on_an_ingredient_line_is_left_alone_on_import(kitchen):
    """The other side. 19 of the corpus's 30 marks are footnote markers and 10 of them sit on
    ingredient rows, so the unwrap must not reach a single one."""
    rows, flags = _imported_lines(
        kitchen, ["\u00bc teaspoon salt*", "1/2 cup (113g) half-and-half*"],
        "FOOT-UID", "footnoted")
    assert len(rows) == 2, rows
    assert all("*" in (r["raw_text"] or "") for r in rows), rows
    assert "cleaned_emphasis_wrap" not in flags, flags


def test_a_note_of_nothing_but_marks_does_not_abort_the_import(kitchen):
    """⚠️ IT ABORTED THE WHOLE IMPORT. "*   *" stripped to "", note_title_plan handed back empty
    text, and commit_plan died on recipe_notes' CHECK (length(trim(text)) > 0)."""
    rows, _flags, _orig = _imported_notes(kitchen, "*   *", "EMPTY-UID", "empty-import")
    assert [r["text"] for r in rows] == ["*   *"]
    assert [r["title"] for r in rows] == [None]
