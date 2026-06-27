"""Phase 15 — import write layer (import_write).

The dangerous failure here is the WRITE: a wrong field mapping or a dropped line silently
corrupts an imported recipe, and a missed dedup duplicates one. So the weight is on the pure
write PLAN — field mapping, slug minting + collisions, the uid-dedup skip, the rating CHECK
guard, and "nothing is ever dropped" — plus end-to-end commits against a throwaway DB."""
import pytest

import import_cleanup as cleanup
import import_write as iw


def _norm(**over):
    """A normalized recipe (reader's shape); override any field. Mirrors test_import_cleanup."""
    base = dict(
        name="X", uid="u", hash="h", ingredient_lines=[], directions="",
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


def test_plan_flagged_line_enters_review_queue():
    p = _plan(_cleaned(ingredient_lines=["2 x 6oz halibut fillets"], directions="Cook it."))
    line_flags = [f for f in p["review_flags"] if f["position"] is not None]
    assert "multiplier" in [f["flag"] for f in line_flags]
    assert all(f["position"] == 0 for f in line_flags)   # line flag carries its line's position


def test_plan_ingredient_id_always_null():
    rows = _plan(_cleaned(ingredient_lines=["2 tbsp oil"]))["ingredients"]
    assert rows[0]["ingredient_id"] is None                # linkage = separate later pass


# ----------------------------------------------------------------- steps
def test_plan_step_section_header_marked():
    steps = _plan(_cleaned(directions="For the sauce:\nSimmer gently."))["steps"]
    assert steps[0]["is_heading"] == 1
    assert steps[1]["is_heading"] == 0


def test_plan_steps_plain_no_markup():
    steps = _plan(_cleaned(directions="Add the [[garlic]] and stir."))["steps"]
    assert steps[0]["text"] == "Add the [[garlic]] and stir."   # carried as-is, not converted


# ----------------------------------------------------------------- rating CHECK guard
@pytest.mark.parametrize("rating,expected", [(0, None), (None, None), (3, 3), (5, 5), (6, None)])
def test_plan_rating_guard(rating, expected):
    assert _plan(_cleaned(rating=rating))["rating"] == expected


# ----------------------------------------------------------------- incomplete recipes
def test_plan_incomplete_carries_recipe_flags_to_queue():
    p = _plan(_cleaned(ingredient_lines=[], directions=""))
    assert {"no_ingredients", "no_directions"} <= set(p["recipe_flags"])
    recipe_level = [f for f in p["review_flags"] if f["position"] is None]
    assert {f["flag"] for f in recipe_level} == {"no_ingredients", "no_directions"}


def test_plan_photo_only_still_writes():
    p = _plan(_cleaned(ingredient_lines=[], directions="", images=[{"bytes": 1}]))
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
                 directions="Step one.\nStep two.", rating=4, servings_raw="4",
                 uid="ACQUA-UID", hash="HH")
    plan = _plan(c)
    with kitchen.conn() as conn:
        assert iw.commit_plan(conn, plan) is True
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


def test_commit_skip_writes_nothing(kitchen):
    # a real tagged seed twin uid -> dedup must skip and write nothing
    c = _cleaned(name="Dup", uid="21FB182C-8CED-4E3A-B20C-893310AA4631")
    uid_index, taken = iw.db_state(kitchen.db)
    plan = iw.plan_recipe(c, uid_index, taken)
    assert plan["decision"] == "skip"
    with kitchen.conn() as conn:
        assert iw.commit_plan(conn, plan) is False
        assert conn.execute("SELECT COUNT(*) FROM recipes WHERE name='Dup'").fetchone()[0] == 0


def test_commit_rating_zero_writes_no_ratings_row(kitchen):
    c = _cleaned(name="Unrated Dish", rating=0, ingredient_lines=["1 egg"], directions="Cook.")
    plan = _plan(c)
    with kitchen.conn() as conn:
        iw.commit_plan(conn, plan)
    with kitchen.conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE recipe_id=?", (plan["recipe"]["id"],)
        ).fetchone()[0] == 0


def test_commit_persists_harvested_grams_and_clean_label(kitchen):
    # end-to-end: FIX 1 (gram-paren stripped from the label) + FIX 2 (gram value persisted)
    c = _cleaned(name="Hummus Test", ingredient_lines=["14 cups (250g) dried chickpeas"],
                 directions="Blend.")
    plan = _plan(c)
    with kitchen.conn() as conn:
        iw.commit_plan(conn, plan)
    with kitchen.conn() as conn:
        row = conn.execute(
            "SELECT label, grams, raw_text FROM recipe_ingredients WHERE recipe_id=? AND position=0",
            (plan["recipe"]["id"],)).fetchone()
    assert row["label"] == "dried chickpeas"             # FIX 1: harvested paren removed from name
    assert row["grams"] == 250.0                         # FIX 2: harvested gram persisted
    assert row["raw_text"] == "14 cups (250g) dried chickpeas"   # original preserved


def test_commit_persists_secondary_measure_both_orders(kitchen):
    # dual-measure capture lands grams + secondary_measure regardless of source order
    c = _cleaned(name="Dual Test", directions="Mix.",
                 ingredient_lines=["100 g (1 cup) granulated sugar", "1 cup (250g) flour"])
    plan = _plan(c)
    with kitchen.conn() as conn:
        iw.commit_plan(conn, plan)
    with kitchen.conn() as conn:
        rows = conn.execute(
            "SELECT label, grams, secondary_measure FROM recipe_ingredients "
            "WHERE recipe_id=? ORDER BY position", (plan["recipe"]["id"],)).fetchall()
    assert tuple(rows[0]) == ("granulated sugar", 100.0, "1 cup")   # weight-first
    assert tuple(rows[1]) == ("flour", 250.0, "1 cup")              # volume-first
