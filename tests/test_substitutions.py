"""load_substitutions.py, the fifth hand file's loader.

⚠️ IT IS THE ONLY WRITER of library_substitutions, so what it refuses matters as much as what it
writes. load_relations.py states the rule these tests enforce: an edge whose id does not resolve
STOPS the load rather than being skipped, because Phase C measured what a silent no-op costs. A
fold with a wrong anchor did nothing, said nothing, and was caught only because a count came back
one higher than expected.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import load_substitutions as LS  # noqa: E402

HEAD = "from,from_name,to,to_name,decision,ratio,n,note,decided\n"


@pytest.fixture
def bench(kitchen, tmp_path):
    """A built database with two catalog rows to point at, and a hand file to write."""
    with kitchen.conn() as c:
        c.execute("INSERT OR IGNORE INTO library_names (library_id, canonical) VALUES (?,?)",
                  ("Q34172", "butter"))
        c.execute("INSERT OR IGNORE INTO library_names (library_id, canonical) VALUES (?,?)",
                  ("Q4287", "margarine"))
    hand = tmp_path / "hand_substitutions.csv"
    hand.write_text("# a comment, which is skipped\n\n" + HEAD)
    return str(kitchen.db), str(hand)


def rows(db):
    c = sqlite3.connect(db)
    out = c.execute("SELECT from_id,to_id,origin,ratio,n,source_slug FROM library_substitutions "
                    "ORDER BY from_id").fetchall()
    c.close()
    return out


def write(hand, *lines):
    Path(hand).write_text("# a comment\n\n" + HEAD + "".join(l + "\n" for l in lines))


def test_an_empty_file_loads_nothing_and_that_is_the_normal_state(bench):
    db, hand = bench
    assert LS.load(db, hand, verbose=False) == (0, 0)
    assert rows(db) == []


def test_a_confirmed_row_becomes_a_fact_carrying_its_support(bench):
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,confirmed,1,35,,2026-09-11")
    LS.load(db, hand, verbose=False)
    assert rows(db) == [("Q34172", "Q4287", "mined-confirmed", 1.0, 35, "recipenlg-2020")]


def test_an_authored_row_says_so_and_claims_no_corpus_support(bench):
    """⚠️ n IS NULL, NOT ZERO. Zero would say the corpus looked and found nothing. NULL says the
    question does not apply, which is the true thing about a substitution nobody mined."""
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,authored,,,it is what my mother did,2026-09-11")
    LS.load(db, hand, verbose=False)
    assert rows(db) == [("Q34172", "Q4287", "authored", None, None, "hand")]


def test_a_rejection_writes_nothing_and_is_still_the_point_of_the_file(bench):
    """The queue is rebuilt whole by the next mining run. A rejection kept anywhere but here would
    be proposed again the next morning."""
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,rejected,,35,tastes nothing like it,2026-09-11")
    n_facts, n_rej = LS.load(db, hand, verbose=False)
    assert (n_facts, n_rej) == (0, 1)
    assert rows(db) == []


def test_the_last_line_for_a_pair_wins_and_the_first_one_stays(bench):
    """⚠️ APPEND, NEVER EDIT. Changing your mind writes a second line, so the file reads as a
    record of what was decided and when rather than only of what stands now."""
    db, hand = bench
    write(hand,
          "Q34172,butter,Q4287,margarine,confirmed,,35,,2026-09-11",
          "Q34172,butter,Q4287,margarine,rejected,,35,changed my mind,2026-09-12")
    LS.load(db, hand, verbose=False)
    assert rows(db) == []
    assert len(LS.read(hand)) == 2, "both lines must survive in the file"
    # and back again
    write(hand,
          "Q34172,butter,Q4287,margarine,confirmed,,35,,2026-09-11",
          "Q34172,butter,Q4287,margarine,rejected,,35,changed my mind,2026-09-12",
          "Q34172,butter,Q4287,margarine,confirmed,,35,changed it back,2026-09-13")
    LS.load(db, hand, verbose=False)
    assert len(rows(db)) == 1


def test_the_table_is_rebuilt_from_the_file_rather_than_added_to(bench):
    """⚠️ A ROW THAT EXISTS ONLY IN recipes.db IS GONE THE NEXT TIME THIS RUNS, and that is the
    contract rather than a hazard. The durable record is the file, which is in git."""
    db, hand = bench
    c = sqlite3.connect(db)
    c.execute("INSERT INTO library_substitutions (from_id,to_id,origin,source_slug) "
              "VALUES ('Q34172','Q4287','typed-straight-in','nowhere')")
    c.commit(); c.close()
    assert len(rows(db)) == 1
    LS.load(db, hand, verbose=False)
    assert rows(db) == [], "a row with nothing behind it in the file must not survive a load"


def test_an_unresolvable_id_stops_the_load_rather_than_skipping_the_row(bench):
    db, hand = bench
    write(hand, "Q34172,butter,unobtainium,unobtainium,confirmed,,35,,2026-09-11")
    with pytest.raises(SystemExit, match="does not resolve"):
        LS.load(db, hand, verbose=False)


def test_a_decision_that_is_not_one_of_the_three_stops_the_load(bench):
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,maybe,,35,,2026-09-11")
    with pytest.raises(SystemExit, match="is not one of"):
        LS.load(db, hand, verbose=False)


def test_an_authored_row_with_no_note_stops_the_load(bench):
    """⚠️ NOTHING PROPOSED IT BUT YOU. A confirmed row does not need a reason, since the
    candidate's n and pattern already are one. An authored row has neither."""
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,authored,,,,2026-09-11")
    with pytest.raises(SystemExit, match="carries no note"):
        LS.load(db, hand, verbose=False)


def test_a_shifted_column_stops_the_load(bench):
    """A line one field short would otherwise read the date as a note and load quietly."""
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,confirmed,,35,2026-09-11")
    with pytest.raises(SystemExit, match="fields, expected"):
        LS.load(db, hand, verbose=False)


def test_a_note_carrying_a_comma_survives_the_round_trip(bench):
    """The viewer writes with a csv writer rather than a format string. A comma in a note would
    otherwise shift every column after it and the loader would refuse the whole file."""
    db, hand = bench
    import csv
    Path(hand).write_text(HEAD)
    with open(hand, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["Q34172", "butter", "Q4287", "margarine", "authored", "",
                                 "", "half butter, half margarine reads best", "2026-09-11"])
    LS.load(db, hand, verbose=False)
    assert LS.read(hand)[0]["note"] == "half butter, half margarine reads best"
    assert len(rows(db)) == 1


def test_a_failed_load_leaves_the_table_as_it_was(bench):
    """The write is one transaction. A file that half validates must not half apply."""
    db, hand = bench
    write(hand, "Q34172,butter,Q4287,margarine,confirmed,,35,,2026-09-11")
    LS.load(db, hand, verbose=False)
    write(hand,
          "Q34172,butter,Q4287,margarine,confirmed,,35,,2026-09-11",
          "Q34172,butter,unobtainium,unobtainium,confirmed,,2,,2026-09-12")
    with pytest.raises(SystemExit):
        LS.load(db, hand, verbose=False)
    assert len(rows(db)) == 1, "the good row from the previous load must still be there"


def test_the_shipped_hand_file_is_readable_and_holds_only_decisions(bench):
    """⚠️ THE REAL FILE, not a fixture. It is in git and load_substitutions.py reads it on every
    build, so a stray line in it breaks a clone rather than a test."""
    real = BASE / "hand_substitutions.csv"
    assert real.exists(), "the fifth hand file is missing"
    for r in LS.read(str(real)):
        assert r["decision"] in LS.DECISIONS, f"line {r['_line']}: {r['decision']!r}"
