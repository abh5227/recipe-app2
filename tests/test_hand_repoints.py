"""hand_repoints.csv and apply_repoints.py — the link decisions a rule cannot reach.

⚠️ THE FILE IS KEYED ON (recipe_id, row_id) SINCE COMMIT 6, and it was (recipe_id, position). The
reason for the old key was written into the file: "the id column is a rowid that build_db
regenerates". That was true while the 5 seed recipes existed and build_db rebuilt their rows, and
migration 016 flipped them to source='app' and emptied seed.py's RECIPES. Measured before converting:
build_db.build() over a copy of live returned all 3,572 ingredient rows byte-identical, same ids.

This file is the first test coverage apply_repoints has had. It pins the key, the guard, and the two
failure modes that must stay loud.
"""
import pathlib
import sqlite3

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("""CREATE TABLE recipe_ingredients (
        id INTEGER PRIMARY KEY, recipe_id TEXT, position INT, raw_text TEXT, label TEXT,
        catalog_id TEXT, link_confidence TEXT, link_rule TEXT, link_matched TEXT)""")
    c.executemany("INSERT INTO recipe_ingredients (id, recipe_id, position, raw_text, label) "
                  "VALUES (?,?,?,?,?)",
                  [(10, "dish", 0, "plain flour", "plain flour"),
                   (11, "dish", 1, "white miso", "white miso"),
                   (12, "dish", 2, "caster sugar", "caster sugar")])
    c.commit()
    return p


def _hand(tmp_path, *rows):
    p = tmp_path / "hand.csv"
    p.write_text("# a comment\naction,recipe_id,row_id,catalog_id,link_confidence,link_rule,"
                 "link_matched,line_check\n" + "".join(",".join(r) + "\n" for r in rows),
                 encoding="utf-8")
    return str(p)


def _apply(db, hand):
    import apply_repoints
    return apply_repoints.apply(db=str(db), hand=hand, verbose=False)


def _row(db, rid):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return dict(c.execute("SELECT * FROM recipe_ingredients WHERE id=?", (rid,)).fetchone())


def test_a_repoint_is_applied_to_the_row_its_id_names(db, tmp_path):
    _apply(db, _hand(tmp_path, ("repoint", "dish", "10", "en:all-purpose-flour", "repoint",
                                "repoint:plain-ap", "plain flour", "plain flour")))
    got = _row(db, 10)
    assert (got["catalog_id"], got["link_confidence"]) == ("en:all-purpose-flour", "repoint")
    assert _row(db, 11)["catalog_id"] is None, "no other row was touched"


def test_the_decision_survives_a_line_inserted_above_it(db, tmp_path):
    """⚠️ THE WHOLE REASON FOR THE RE-KEY. Adding an ingredient shifts every position below it, so the
    old key pointed one row further down and line_check stopped the run. Correct, and still a failure
    that had to be repaired by hand. An id does not move."""
    hand = _hand(tmp_path, ("repoint", "dish", "12", "en:caster-sugar", "repoint",
                            "repoint:caster", "caster sugar", "caster sugar"))
    c = sqlite3.connect(db)
    c.execute("UPDATE recipe_ingredients SET position = position + 1 WHERE recipe_id='dish'")
    c.execute("INSERT INTO recipe_ingredients (id, recipe_id, position, raw_text, label) "
              "VALUES (99, 'dish', 0, 'a new line', 'a new line')")
    c.commit()
    c.close()
    _apply(db, hand)
    assert _row(db, 12)["catalog_id"] == "en:caster-sugar"
    assert _row(db, 99)["catalog_id"] is None


def test_a_rewritten_line_still_stops_the_run(db, tmp_path):
    """⚠️ line_check IS NOT MADE REDUNDANT BY THE ID. The id says which row; the check says the
    decision was made about THIS TEXT. A cook who rewrites a line has made a different line of it."""
    hand = _hand(tmp_path, ("repoint", "dish", "10", "en:all-purpose-flour", "repoint",
                            "repoint:plain-ap", "plain flour", "plain flour"))
    c = sqlite3.connect(db)
    c.execute("UPDATE recipe_ingredients SET label='strong bread flour' WHERE id=10")
    c.commit()
    c.close()
    with pytest.raises(SystemExit, match="not"):
        _apply(db, hand)
    assert _row(db, 10)["catalog_id"] is None, "and nothing was written"


def test_an_id_that_is_not_in_the_corpus_stops_the_run(db, tmp_path):
    hand = _hand(tmp_path, ("repoint", "dish", "404", "en:x", "repoint", "r", "m", "plain flour"))
    with pytest.raises(SystemExit, match="no line in"):
        _apply(db, hand)


def test_the_right_id_under_the_wrong_recipe_does_not_apply(db, tmp_path):
    """recipe_id is in the WHERE beside the id on purpose: an id names one row in the whole table."""
    hand = _hand(tmp_path, ("repoint", "other-dish", "10", "en:x", "repoint", "r", "m", "plain flour"))
    with pytest.raises(SystemExit, match="no line in"):
        _apply(db, hand)
    assert _row(db, 10)["catalog_id"] is None


def test_a_suppress_withholds_a_link(db, tmp_path):
    c = sqlite3.connect(db)
    c.execute("UPDATE recipe_ingredients SET catalog_id='en:miso', link_confidence='exact' WHERE id=11")
    c.commit()
    c.close()
    _apply(db, _hand(tmp_path, ("suppress", "dish", "11", "", "", "", "", "white miso")))
    assert _row(db, 11)["catalog_id"] is None


def test_the_shipped_file_is_keyed_on_row_id_and_every_row_is_unique():
    """The real file, read as a file. A duplicate key would silently let one decision override
    another, and the header has to name row_id or every reader is reading the wrong column."""
    import csv
    lines = [l for l in (REPO / "hand_repoints.csv").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    header = next(csv.reader([lines[0]]))
    assert header[:3] == ["action", "recipe_id", "row_id"]
    rows = [next(csv.reader([l])) for l in lines[1:]]
    assert len(rows) == 61, f"expected the 61 shipped decisions, found {len(rows)}"
    assert all(len(r) == len(header) for r in rows)
    keys = [(r[1], r[2]) for r in rows]
    assert len(set(keys)) == len(keys), "a duplicate (recipe_id, row_id) would hide a decision"
    assert {r[0] for r in rows} == {"repoint", "suppress", "relabel"}
