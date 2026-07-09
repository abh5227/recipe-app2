"""The name->unit backfill (scripts/backfill_name_unit.py) — moving a leading size/count descriptor
out of the ingredient NAME into the empty unit field. Tests the PURE rule (plan_name_split) on
representative strings + the DB write/idempotency against a throwaway DB. No live-DB access."""
import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(db_path=None):
    spec = importlib.util.spec_from_file_location(
        "backfill_name_unit", REPO / "scripts" / "backfill_name_unit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if db_path is not None:
        mod.DB = Path(db_path)
    return mod


M = _load()
plan = M.plan_name_split


# ------------------------------------------------------------------ the PROMOTABLE recognizer (DB-free)
def test_split_leading_descriptor_is_pure_string_in_tuple_or_none_out():
    f = M.split_leading_descriptor
    # takes a plain string, returns (unit, name) or None — no DB, no row objects
    assert f("medium onion (diced)") == ("medium", "onion (diced)")
    assert f("large cloves of garlic") == ("large cloves", "garlic")   # size+count, size kept, "of" dropped
    assert f("cloves garlic, crushed") == ("cloves", "garlic, crushed")
    assert f("medium-to-large clove garlic") is None                   # hyphen compound -> no clean split
    assert f("medium grain rice") is None                              # intrinsic -> no clean split
    assert f("Cloves") is None                                         # empty remainder -> no clean split
    assert f("extra virgin olive oil") is None                        # no leading descriptor
    assert f("") is None


# ------------------------------------------------------------------ clean auto-transforms
def test_clean_size_leading():
    p = plan("large eggs, room temperature", "2")
    assert p == {"action": "auto", "unit": "large", "name": "eggs, room temperature", "qty": "2 large"}


def test_clean_count_leading():
    p = plan("cloves garlic, crushed", "4")
    assert (p["action"], p["unit"], p["name"], p["qty"]) == ("auto", "cloves", "garlic, crushed", "4 cloves")


def test_of_is_stripped():
    p = plan("Pinch of salt", "")                       # no quantity -> qty is just the unit
    assert (p["unit"], p["name"], p["qty"]) == ("pinch", "salt", "pinch")


def test_parenthetical_rides_with_name():
    p = plan("medium onion (cut into wedges)", "1")
    assert (p["unit"], p["name"], p["qty"]) == ("medium", "onion (cut into wedges)", "1 medium")


def test_unit_lowercased_remainder_casing_kept():
    p = plan("Clove of Garlic, Diced", "1")
    assert (p["unit"], p["name"]) == ("clove", "Garlic, Diced")   # unit lowercased; name casing preserved


def test_plural_not_folded():
    assert plan("sprigs fresh thyme", "5")["unit"] == "sprigs"    # NOT "sprig"
    assert plan("slices ginger", "4")["unit"] == "slices"


def test_qty_recombine_holds():
    p = plan("large sweet onions (like Vidalia), chopped", "1½")
    assert p["qty"] == f"{'1½'} {p['unit']}" == "1½ large"


# ------------------------------------------------------------------ SIZE + COUNT-noun (now auto; size KEPT)
def test_size_plus_count_keeps_size_in_unit():
    p = plan("large cloves garlic minced", "5")
    assert p == {"action": "auto", "unit": "large cloves", "name": "garlic minced", "qty": "5 large cloves"}


def test_size_plus_count_strips_of_and_keeps_paren_in_name():
    p = plan("small bunch of flatleaf parsley (finely chopped)", "")   # qty="" -> qty is just the unit
    assert (p["action"], p["unit"], p["name"], p["qty"]) == (
        "auto", "small bunch", "flatleaf parsley (finely chopped)", "small bunch")


def test_size_plus_count_unit_lowercased_name_casing_kept():
    p = plan("Large Cloves of Garlic, Sliced Thin", "3")
    assert (p["unit"], p["name"], p["qty"]) == ("large cloves", "Garlic, Sliced Thin", "3 large cloves")


def test_size_plus_count_head_and_handful():
    assert plan("large head cauliflower chopped into florets", "1")["unit"] == "large head"
    assert plan("small handful of cilantro, leaves and slim stems", "")["unit"] == "small handful"


# ------------------------------------------------------------------ still flagged (NOT transformed)


def test_flag_intrinsic():
    for name in ["medium grain rice", "large dice", "Small Dice"]:
        assert plan(name, "1") == {"action": "skip", "reason": "intrinsic"}, name


def test_flag_hyphen_compound():
    # descriptor immediately followed by a hyphen -> part of a hyphenated word, not the unit
    assert plan("medium-to-large clove garlic, roughly chopped", "1") == {"action": "skip", "reason": "hyphen-compound"}
    assert plan("medium-grain white rice", "1") == {"action": "skip", "reason": "hyphen-compound"}
    assert plan("large-flake coconut", "1")["reason"] == "hyphen-compound"


def test_flag_alternative():
    # remainder begins with "or …" -> an alternative-quantity phrasing, don't guess
    p = plan("large or 4 small onions, very finely sliced", "3")
    assert p == {"action": "skip", "reason": "alternative"}


def test_flag_pre_mangled():
    # a merged second ingredient (spelled-out spoon/cup qty OUTSIDE parens) -> not a clean single line
    merged = "small skin-on snapper fillets, 10 to 12 ounces each 2 teaspoons kosher salt, plus more"
    assert plan(merged, "2") == {"action": "skip", "reason": "pre-mangled"}
    # a truncated import ("(about" dangling at the end)
    assert plan("small whole mackerel (about", "4") == {"action": "skip", "reason": "pre-mangled"}


def test_legit_paren_weight_note_NOT_mangled():
    # a legit parenthetical weight note must NOT be mistaken for a merge (parens dropped before the check)
    assert plan("medium sea bass (around 10 oz./300g each)", "2")["action"] == "auto"
    assert plan("large eggs (3.5 oz / 100g)", "2")["action"] == "auto"
    assert plan("medium parsnips (3/4 pound), peeled and cut into 1/2-inch pieces", "3")["action"] == "auto"


def test_flag_empty_or_paren():
    assert plan("Cloves", "10")["reason"] == "empty/paren"                    # nothing left after strip
    assert plan("cloves (or 1/4 tsp ground cloves)", "10")["reason"] == "empty/paren"  # paren-only remainder


def test_non_descriptor_name_skipped():
    assert plan("garlic cloves, minced", "4")["reason"] == "no-leading-descriptor"   # trailing count = deferred
    assert plan("extra virgin olive oil", "2")["reason"] == "no-leading-descriptor"


def test_idempotent_on_already_stripped_name():
    # after a transform the name is "onion" (no leading descriptor) -> a re-run is a no-op
    assert plan("onion (cut into wedges)", "1")["action"] == "skip"


# ------------------------------------------------------------------ DB write + idempotency (temp DB)
def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT, is_heading INTEGER NOT NULL DEFAULT 0,
        qty TEXT, quantity TEXT, unit TEXT, label TEXT, raw_text TEXT)""")
    c.executemany(
        "INSERT INTO recipe_ingredients (is_heading, qty, quantity, unit, label, raw_text) VALUES (?,?,?,?,?,?)",
        [
            (0, "1", "1", "", "medium onion (diced)", "1 medium onion (diced)"),   # auto (single)
            (0, "4", "4", "", "cloves garlic, crushed", "4 cloves garlic, crushed"),  # auto (single count)
            (0, "3", "3", "", "large cloves garlic", "3 large cloves garlic"),      # auto (size+count, size kept)
            (0, "1", "1", "", "medium-grain white rice", "1 medium-grain white rice"),  # FLAGGED (hyphen) -> not touched
            (0, "2", "2", "cups", "flour", "2 cups flour"),                        # has unit -> not a candidate
            (1, None, None, None, None, "SAUCE"),                                  # heading -> skipped
        ])
    c.commit(); c.close()


def test_apply_updates_unit_label_qty_only(tmp_path):
    db = tmp_path / "t.db"; _make_db(db)
    mod = _load(db)
    mod.run(apply=True)
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    onion = c.execute("SELECT * FROM recipe_ingredients WHERE label='onion (diced)'").fetchone()
    assert (onion["unit"], onion["qty"], onion["quantity"]) == ("medium", "1 medium", "1")
    assert onion["raw_text"] == "1 medium onion (diced)"           # raw_text UNTOUCHED (still accurate)
    garlic = c.execute("SELECT * FROM recipe_ingredients WHERE label='garlic, crushed'").fetchone()
    assert (garlic["unit"], garlic["qty"]) == ("cloves", "4 cloves")
    # size+count row now auto-transforms with the size KEPT in the unit
    sc = c.execute("SELECT * FROM recipe_ingredients WHERE label='garlic' AND qty='3 large cloves'").fetchone()
    assert sc is not None and sc["unit"] == "large cloves"
    # the hyphen-compound row stays flagged (untouched); the unit row + heading untouched
    assert c.execute("SELECT unit FROM recipe_ingredients WHERE label='medium-grain white rice'").fetchone()["unit"] in (None, "")
    c.close()


def test_apply_is_idempotent(tmp_path):
    db = tmp_path / "t.db"; _make_db(db)
    mod = _load(db)
    mod.run(apply=True)
    c = sqlite3.connect(db)
    before = c.execute("SELECT id, qty, unit, label FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    mod.run(apply=True)                                            # second run: transformed rows now have a unit
    c = sqlite3.connect(db)
    after = c.execute("SELECT id, qty, unit, label FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    assert before == after                                        # no further change
