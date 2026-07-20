"""The heading backfill (scripts/backfill_headings.py) — promoting is_heading=0 rows that are really
SECTION HEADINGS (Bucket A: for/to flagged rows; Bucket B: detector via section_signal — emphasis /
X-Ingredients / unit-system / Day-N / prep allowlist). Tests the PURE classifier (plan_heading) + the
DB promote/idempotency against a throwaway DB. No live-DB access."""
import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(db_path=None):
    spec = importlib.util.spec_from_file_location(
        "backfill_headings", REPO / "scripts" / "backfill_headings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if db_path is not None:
        mod.DB = Path(db_path)
    return mod


M = _load()
plan = M.plan_heading


# ------------------------------------------------------------------ the PURE classifier
def test_bucket_a_for_to_flagged():
    # flagged suggest-section -> promote; text is unchanged (already clean, strip is a no-op)
    assert plan("For the dal", True) == {"action": "auto", "bucket": "for/to", "text": "For the dal"}
    assert plan("To finish", True)["bucket"] == "for/to"


def test_bucket_b_markdown_colon_stripped():
    # whole-line bold wrapper -> stripped to a colon heading -> promote with the CLEAN text
    assert plan("**Other Ingredients:**", False) == {
        "action": "auto", "bucket": "detector", "text": "Other Ingredients:"}
    assert plan("**Whole Spices:**", False)["text"] == "Whole Spices:"


def test_bucket_b_detector_new_rules():
    # the 4 section_signal rules all route through Bucket B (detector)
    assert plan("Italian Beef Ingredients", False)["bucket"] == "detector"     # Rule 1
    assert plan("Metric", False)["bucket"] == "detector"                       # Rule 2
    assert plan("**Day 1**", False) == {"action": "auto", "bucket": "detector", "text": "Day 1"}  # Rule 3
    assert plan("Egg wash", False)["bucket"] == "detector"                     # Rule 4
    assert plan("Flour Dredge", False)["bucket"] == "detector"                 # Rule 4 (ends-in)


def test_bold_label_no_signal_not_promoted():
    # a bold label matching no rule (no colon/caps/signal) -> skip
    assert plan("**Some Label**", False)["action"] == "skip"


def test_excluded_one_offs_not_promoted():
    # section-word-ending + excluded food/count words stay for manual review (no matching bucket)
    for t in ("Fresh parsley for garnish", "Brown Butter-Cream Cheese Frosting", "Loaves",
              "Salsa", "Meatballs", "Cheddar Mashed Potatoes", "Spice Mix"):
        assert plan(t, False)["action"] == "skip", t


def test_empty_skipped():
    assert plan("", False)["action"] == "skip"


# ------------------------------------------------------------------ DB promote + idempotency (temp DB)
def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id TEXT, position INTEGER,
        is_heading INTEGER NOT NULL DEFAULT 0, qty TEXT, quantity TEXT, unit TEXT,
        label TEXT, raw_text TEXT, grams REAL, secondary_measure TEXT)""")
    c.execute("""CREATE TABLE import_flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id TEXT, position INTEGER, flag TEXT, reason TEXT)""")
    c.executemany(
        "INSERT INTO recipe_ingredients "
        "(recipe_id, position, is_heading, qty, quantity, unit, label, raw_text) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("r1", 0, 0, None, "", "", "For the dal", "For the dal"),           # Bucket A (flagged below)
            ("r1", 1, 0, "1 cup", "1", "cup", "lentils", "1 cup lentils"),      # real ingredient -> keep
            ("r2", 0, 0, "", "", "", None, "**Whole Spices:**"),               # detector (markdown colon)
            ("r2", 1, 0, None, "", "", "Fresh parsley for garnish", "Fresh parsley for garnish"),  # manual -> keep
            ("r2", 2, 1, None, None, None, None, "EXISTING HEADING:"),          # already a heading -> untouched
            ("r3", 0, 0, "", "", "", None, "Italian Beef Ingredients"),        # detector Rule 1
            ("r3", 1, 0, "", "", "", None, "**Day 1**"),                       # detector Rule 3 -> "Day 1"
            ("r3", 2, 0, None, "", "", "Egg wash", "Egg wash"),                # detector Rule 4
            ("r3", 3, 0, None, "", "", "Metric", "Metric"),                    # detector Rule 2
            ("r3", 4, 0, None, "", "", "Loaves", "Loaves"),                    # EXCLUDED -> keep
            ("r3", 5, 0, "2", "2", "", "eggs", "2 eggs"),                       # amount-bearing -> keep
        ])
    c.execute("INSERT INTO import_flags (recipe_id, position, flag, reason) VALUES (?,?,?,?)",
              ("r1", 0, "ambiguous_section", "no amount and not clearly a section — suggest section"))
    c.commit(); c.close()


def test_apply_promotes_expected_and_leaves_the_rest(tmp_path):
    db = tmp_path / "t.db"; _make_db(db)
    mod = _load(db)
    mod.run(apply=True)
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row

    def row(rid, pos): return c.execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id=? AND position=?", (rid, pos)).fetchone()

    # for/to promoted, canonical shape
    a = row("r1", 0)
    assert a["is_heading"] == 1 and a["raw_text"] == "For the dal"
    assert a["label"] is None and a["quantity"] is None and a["unit"] is None and a["qty"] is None
    # detector rows promoted; markdown + Day-N stored CLEAN
    assert row("r2", 0)["is_heading"] == 1 and row("r2", 0)["raw_text"] == "Whole Spices:"
    assert row("r3", 0)["is_heading"] == 1 and row("r3", 0)["raw_text"] == "Italian Beef Ingredients"
    assert row("r3", 1)["is_heading"] == 1 and row("r3", 1)["raw_text"] == "Day 1"    # ** stripped
    assert row("r3", 2)["is_heading"] == 1 and row("r3", 2)["raw_text"] == "Egg wash"
    assert row("r3", 3)["is_heading"] == 1 and row("r3", 3)["raw_text"] == "Metric"

    # NOT promoted: real ingredient, garnish, excluded "Loaves", amount-bearing "eggs", pre-existing heading
    assert row("r1", 1)["is_heading"] == 0 and row("r1", 1)["qty"] == "1 cup"
    assert row("r2", 1)["is_heading"] == 0
    assert row("r3", 4)["is_heading"] == 0          # Loaves excluded
    assert row("r3", 5)["is_heading"] == 0          # amount-bearing

    total = c.execute("SELECT COUNT(*) FROM recipe_ingredients WHERE is_heading=1").fetchone()[0]
    assert total == 7                                # 6 promoted (1 for/to + 5 detector) + 1 pre-existing
    c.close()


def test_apply_is_idempotent(tmp_path):
    db = tmp_path / "t.db"; _make_db(db)
    mod = _load(db)
    mod.run(apply=True)
    c = sqlite3.connect(db)
    before = c.execute("SELECT id, is_heading, qty, label, raw_text FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    mod.run(apply=True)                                                   # second run: promoted rows are is_heading=1
    c = sqlite3.connect(db)
    after = c.execute("SELECT id, is_heading, qty, label, raw_text FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    assert before == after                                                # no further change
