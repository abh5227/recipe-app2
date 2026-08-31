"""build_library.write_library_names, the generator for the lookup build_db loads.

The generator cannot be exercised end to end here. Producing a real rowset needs join.db (894 MB) and
sources.db (5.18 GB), neither of which is committed or present in CI. So what is tested is the half
that has no such dependency: rows in, CSV out.

⚠️ THE ROUND-TRIP IS THE POINT. A file written by write_library_names is fed straight to
build_db.seed_library_names and the rows are read back out of the database. Two modules agree on two
column names and a comment convention, and nothing but this test stops them drifting apart.
"""
import csv

import pytest

import build_db
import build_library


def _row(ident, canonical, cut_by="", commonality="obscure"):
    """The four keys write_library_names reads. A real row carries ~36 more."""
    return {"id": ident, "canonical": canonical, "cut_by": cut_by, "commonality": commonality}


# Every id shape the real library actually uses, plus the two characters that break hand-formatted
# CSV. Measured over the 10,515 kept rows: Q-ids 61.1%, OFF ids 38.4%, authored slugs 0.5%.
ROWS = [
    _row("Q1063736", "penne"),                                  # Wikidata
    _row("en:egg-pasta", "egg pasta"),                          # Open Food Facts
    _row("salt", "salt"),                                       # authored
    _row("Q2140646", "sugar, brown"),                           # a comma inside the value
    _row("Q42527", 'cream, "heavy"'),                           # a quote inside the value
]


def test_round_trips_through_the_loader(kitchen, tmp_path):
    """⚠️ THE ONE THAT MATTERS. Generator writes, loader reads, database holds the right rows. If
    either side changes a column name or the comment convention, this fails."""
    path = tmp_path / "library_names.csv"
    assert build_library.write_library_names(ROWS, path) == 5

    build_db.LIBRARY_NAMES_CSV = path      # make_kitchen already rebound this into tmp_path
    with kitchen.conn() as c:
        build_db.seed_library_names(c)

    with kitchen.conn() as c:
        got = {r["library_id"]: r["canonical"]
               for r in c.execute("SELECT library_id, canonical FROM library_names")}
    assert got == {"Q1063736": "penne", "en:egg-pasta": "egg pasta", "salt": "salt",
                   "Q2140646": "sugar, brown", "Q42527": 'cream, "heavy"'}


def test_header_and_comments_match_what_the_loader_parses(tmp_path):
    """The contract in full: `#` provenance lines the loader filters, then the headers.

    ⚠️ THREE COLUMNS SINCE COMMONALITY, and the third is additive. build_db.seed_library_names pulls
    its two by NAME through a DictReader, so it ignores the extra rather than breaking on it, which
    test_library_names_loader covers from the other side."""
    path = tmp_path / "library_names.csv"
    build_library.write_library_names(ROWS, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert all(ln.startswith("#") for ln in lines[:3])
    assert lines[3] == "library_id,canonical,commonality"


def test_cut_rows_are_excluded(tmp_path):
    """Same `not row['cut_by']` predicate write_sheet uses for the kept sheet, so the lookup and the
    review sheet always describe the same list."""
    path = tmp_path / "library_names.csv"
    rows = ROWS + [_row("Q999", "dropped thing", cut_by="a cut rule")]
    assert build_library.write_library_names(rows, path) == 5
    assert "dropped thing" not in path.read_text(encoding="utf-8")


def test_sorted_by_canonical_so_a_regenerated_file_diffs_readably(tmp_path):
    """Read back with csv.reader, not by splitting on commas. Two of these canonicals contain a
    comma, which is the whole reason the writer quotes."""
    path = tmp_path / "library_names.csv"
    build_library.write_library_names(ROWS, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(ln for ln in f if not ln.lstrip().startswith("#")))
    names = [canonical for _ident, canonical, *_rest in rows[1:]]
    assert names == sorted(names, key=str.casefold)


def test_quoting_survives_a_comma_and_a_quote(tmp_path):
    """csv.writer's job, pinned. A hand-formatted line turns 'sugar, brown' into two columns."""
    path = tmp_path / "library_names.csv"
    build_library.write_library_names(ROWS, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = {r[0]: r[1] for r in csv.reader(ln for ln in f if not ln.lstrip().startswith("#"))}
    assert rows["Q2140646"] == "sugar, brown"
    assert rows["Q42527"] == 'cream, "heavy"' 


def test_a_duplicate_id_refuses_to_write(tmp_path):
    """⚠️ Stopping here beats stopping in build_db. library_names.library_id is a primary key, so a
    duplicate would raise at load time, which is a worse place to find out."""
    path = tmp_path / "library_names.csv"
    with pytest.raises(SystemExit, match="DUPLICATE library id"):
        build_library.write_library_names(ROWS + [_row("Q1063736", "penne rigate")], path)


def test_an_empty_rowset_writes_a_loadable_empty_file(kitchen, tmp_path):
    """A file with headers and no rows still loads, and leaves the table empty rather than erroring."""
    path = tmp_path / "library_names.csv"
    assert build_library.write_library_names([], path) == 0
    build_db.LIBRARY_NAMES_CSV = path
    with kitchen.conn() as c:
        build_db.seed_library_names(c)
    assert kitchen.count("library_names") == 0


def test_the_commonality_column_is_written_and_is_additive(tmp_path):
    """⚠️ The third column carries the tier to the app. It is additive on purpose: the loader reads
    library_id and canonical BY NAME, so an older two-column file still loads and a newer three-column
    one does not break a machine that has not migrated. A row with no tier writes an empty cell rather
    than the string 'None'."""
    path = tmp_path / "library_names.csv"
    build_library.write_library_names(ROWS + [{"id": "Q9", "canonical": "zucchini", "cut_by": ""}], path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#")))
    assert set(rows[0]) == {"library_id", "canonical", "commonality"}
    assert {r["library_id"]: r["commonality"] for r in rows}["Q1063736"] == "obscure"
    assert {r["library_id"]: r["commonality"] for r in rows}["Q9"] == "", "a missing tier is blank, not 'None'"
