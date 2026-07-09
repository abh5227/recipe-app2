"""The heading backfill (scripts/backfill_headings.py) — promoting is_heading=0 rows that are really
SECTION HEADINGS (two high-confidence buckets: for/to flagged rows + markdown **…:** rows). Tests the
PURE classifier (plan_heading) + the DB promote/idempotency against a throwaway DB. No live-DB access."""
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
        "action": "auto", "bucket": "markdown", "text": "Other Ingredients:"}
    assert plan("**Whole Spices:**", False)["text"] == "Whole Spices:"


def test_bold_without_colon_not_promoted():
    # "**Day 1**" strips to "Day 1" (no colon/caps) -> NOT a section -> skip
    assert plan("**Day 1**", False)["action"] == "skip"


def test_section_word_ending_not_promoted():
    # a section-word-ending line is NOT a bucket (left for manual review) — not flagged, not markdown
    assert plan("Fresh parsley for garnish", False)["action"] == "skip"
    assert plan("Brown Butter-Cream Cheese Frosting", False)["action"] == "skip"


def test_x_ingredients_not_promoted():
    # "X Ingredients" (title-case, no colon, no wrapper, not flagged) -> manual review, not a bucket
    assert plan("Italian Beef Ingredients", False)["action"] == "skip"


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
            ("r2", 0, 0, "", "", "", None, "**Whole Spices:**"),               # Bucket B (markdown)
            ("r2", 1, 0, None, "", "", "Fresh parsley for garnish", "Fresh parsley for garnish"),  # manual -> keep
            ("r2", 2, 1, None, None, None, None, "EXISTING HEADING:"),          # already a heading -> untouched
        ])
    c.execute("INSERT INTO import_flags (recipe_id, position, flag, reason) VALUES (?,?,?,?)",
              ("r1", 0, "ambiguous_section", "no amount and not clearly a section — suggest section"))
    c.commit(); c.close()


def test_apply_promotes_only_the_two_buckets(tmp_path):
    db = tmp_path / "t.db"; _make_db(db)
    mod = _load(db)
    mod.run(apply=True)
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row

    a = c.execute("SELECT * FROM recipe_ingredients WHERE recipe_id='r1' AND position=0").fetchone()
    assert a["is_heading"] == 1 and a["raw_text"] == "For the dal"
    assert a["label"] is None and a["quantity"] is None and a["unit"] is None and a["qty"] is None

    b = c.execute("SELECT * FROM recipe_ingredients WHERE recipe_id='r2' AND position=0").fetchone()
    assert b["is_heading"] == 1 and b["raw_text"] == "Whole Spices:"     # ** stripped, colon kept
    assert b["label"] is None and b["qty"] is None

    # a real ingredient, a section-word line, and an existing heading are ALL untouched
    ing = c.execute("SELECT * FROM recipe_ingredients WHERE label='lentils'").fetchone()
    assert ing["is_heading"] == 0 and ing["qty"] == "1 cup"
    manual = c.execute("SELECT * FROM recipe_ingredients WHERE label='Fresh parsley for garnish'").fetchone()
    assert manual["is_heading"] == 0
    total_headings = c.execute("SELECT COUNT(*) FROM recipe_ingredients WHERE is_heading=1").fetchone()[0]
    assert total_headings == 3                                            # 2 promoted + 1 pre-existing
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
