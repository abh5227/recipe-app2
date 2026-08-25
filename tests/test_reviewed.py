"""reviewed.py holds hand-read verdicts and cannot be regenerated at any price, so the
tests here guard the two ways a verdict can go missing without anyone noticing.

Both are recorded near-misses rather than hypotheticals.
"""
import ast

import build_library
import reviewed


def _dict_keys(name):
    """Every key literal in a module-level dict, read from the SOURCE rather than the
    loaded object, because the loaded object is where a duplicate has already vanished."""
    tree = ast.parse(open(reviewed.__file__, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise AssertionError(f"{name} is not a module-level dict in reviewed.py")


def test_no_verdict_is_silently_overwritten_by_a_duplicate_key():
    """⚠️ A RECORDED NEAR-MISS. Adding the 2026-08-25 peppercorn ruling as a second
    'pepper' entry in HEAD_TERMS dropped the first one, and nothing failed. The dict
    still had 50 keys, counts() still said 50, and the reading that had been done by hand
    was gone. A duplicate key in this file destroys a reading."""
    for name in ("HEAD_TERMS", "WIKTIONARY_SAMPLE", "OFF_ONLY_SAMPLE", "LOW_GROUP_SAMPLE",
                 "MERGE_SAMPLE", "NEVER_MET_SAMPLE", "DRINKS_SAMPLE", "EXTRACTION_READ"):
        keys = _dict_keys(name)
        assert len(keys) == len(set(keys)), (
            f"{name} has duplicate keys, and the later one silently wins: "
            f"{sorted(k for k in keys if keys.count(k) > 1)}")


def test_the_header_count_matches_what_counts_reports():
    """The docstring said 250 for six samples while counts() said 265, which is how the
    prose came to be read off the function. It can drift again."""
    total = sum(reviewed.counts().values())
    assert f"This is {total} entries" in reviewed.__doc__


def test_every_lookup_key_survives_flattening():
    """_flatten() builds the index build_library reads. A group added to the file but not
    to _flatten is invisible to the sheet, which is how a reading gets done twice."""
    for holder in reviewed.EXTRACTION_READ:
        assert reviewed.lookup(holder), f"{holder} is recorded but not reachable"


def test_latin_is_kept_on_rows_and_excluded_from_members():
    """The two uses of the Latin tag are separate and a cut that conflates them stops the
    binomial flag. 56 rows carry that flag and all 56 rest on a Latin tag."""
    assert "la" in build_library.MEMBER_EXCLUDED_LANGS
    assert "la" not in build_library.load_dead_languages()
