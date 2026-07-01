"""First tests for paprika_native_reader — the source reader (previously untested).

Confirms the normalized shape, the (name, rec, err) three-tuple yield contract of
iter_entries over a fixture archive, and that a malformed entry is REPORTED as an error
rather than crashing the batch (the property the runner relies on)."""
import zipfile

import paprika_native_reader as reader
from harness import write_paprika_archive


def test_normalize_representative_entry():
    raw = {
        "name": '"Almost Za\'atar"',                     # Paprika wraps some names in literal quotes
        "ingredients": "1 cup flour\n\n2 eggs\nSalt",    # blank line between ingredient groups
        "directions": "Mix.\nBake.",
        "categories": ["Bread"], "source": "Nana", "source_url": "http://x",
        "servings": "4", "uid": "u-1", "hash": "h-1", "rating": 5,
    }
    n = reader.normalize(raw)

    assert n["name"] == "Almost Za'atar"                 # surrounding quotes stripped
    assert n["ingredient_lines"] == ["1 cup flour", "2 eggs", "Salt"]   # blanks dropped
    assert n["uid"] == "u-1" and n["hash"] == "h-1"
    assert n["rating"] == 5                              # passthrough (int, incl. 0/None untouched)
    assert n["categories"] == ["Bread"]
    assert n["source"] == "Nana"


def test_normalize_tolerates_missing_fields():
    n = reader.normalize({"name": "Bare"})               # only a name; everything else absent
    assert n["name"] == "Bare"
    assert n["ingredient_lines"] == [] and n["uid"] == "" and n["categories"] == []


def test_ingredient_lines_collapses_blanks():
    lines, blanks = reader.ingredient_lines("a\n\n\nb\n")
    assert lines == ["a", "b"]
    assert blanks == 3                                   # 3 empty segments counted, not lost


def test_strip_quotes_only_balanced_wrapping():
    assert reader.strip_quotes('"x"') == "x"
    assert reader.strip_quotes("x") == "x"
    assert reader.strip_quotes('"x') == '"x'             # unbalanced leading quote kept


def test_iter_entries_yields_name_rec_err_triples_and_reports_malformed(tmp_path):
    recs = [{"name": "A", "uid": "a"}, {"name": "B", "uid": "b"}]
    arc = write_paprika_archive(tmp_path / "r.paprikarecipes", recs,
                                malformed=["bad.paprikarecipe"])

    with zipfile.ZipFile(arc) as zf:
        got = list(reader.iter_entries(zf))              # must NOT raise despite the bad entry

    assert len(got) == 3                                 # 2 good + 1 malformed, all yielded
    assert all(len(t) == 3 for t in got)                # the (name, rec, err) contract
    ok = [(nm, rc) for nm, rc, er in got if er is None]
    bad = [(nm, rc, er) for nm, rc, er in got if er is not None]
    assert len(ok) == 2 and all(isinstance(rc, dict) for _, rc in ok)
    assert len(bad) == 1
    assert bad[0][0] == "bad.paprikarecipe" and bad[0][1] is None   # name kept, rec is None
    assert bad[0][2] is not None                         # error object present, not swallowed
