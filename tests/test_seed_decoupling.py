"""The suite builds its fixtures from tests/fixtures.py, NOT from production seed.py.

⚠️ THIS IS WHAT STAGE A BOUGHT, AND IT IS INVISIBLE WITHOUT A TEST. TEST_INGREDIENTS is a verbatim
copy of seed.py's 36, so every other test passes whichever dict it was built from. That is the point
(stage A changes no behavior) and it is also the danger: a change that silently re-couples the
harness to seed.py would go unnoticed until seed.py is emptied and CI collapses with 465 fixture
errors, which is what the seed-tier diagnostic measured.

So these assert the WIRING, not the data.
"""
import build_db
import fixtures
import harness
import seed


# ---- the wiring ---------------------------------------------------------------------------------

def test_the_harness_binds_the_fixture_dict_not_seed_py(kitchen):
    """make_kitchen must leave build_db pointing at the fixtures. Identity, not equality: today the
    two dicts are equal, so `==` would pass even fully re-coupled."""
    assert build_db.INGREDIENTS is fixtures.TEST_INGREDIENTS
    assert build_db.RECIPES is fixtures.TEST_RECIPES


def test_the_pg_harness_reads_the_fixture_too(kitchen):
    """⚠️ pg_harness does `from X import Y`, which binds a name in ITS module namespace, so
    make_kitchen's rebind of build_db.INGREDIENTS does NOT reach it. It has to import the fixture
    itself. This is the same shape as the bug that took CI red in 3ac4799, where pg_harness was the
    third writer to `ingredients` and the SQLite suite could not see it."""
    import pg_harness
    assert pg_harness.INGREDIENTS is fixtures.TEST_INGREDIENTS


def test_nothing_in_the_test_tree_imports_seed_ingredients():
    """The grep, as an assertion. A new `from seed import INGREDIENTS` anywhere under tests/ puts the
    coupling back without touching either harness."""
    import ast
    import pathlib
    offenders = []
    for p in sorted(pathlib.Path(__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "seed":
                for a in node.names:
                    if a.name == "INGREDIENTS":
                        offenders.append(p.name)
    assert offenders == [], f"these re-couple the suite to seed.py: {offenders}"


# ---- the rebind actually drives the build --------------------------------------------------------

def test_a_fixture_only_ingredient_reaches_the_built_database(tmp_path, monkeypatch):
    """⚠️ THE STRONGEST FORM. Binding the name proves nothing on its own if seed_content read a
    different copy. A sentinel that exists in NO production file must appear in the built database.

    Runs in its own temp database, so the count-36 assertions elsewhere are untouched."""
    k = harness.make_kitchen(tmp_path)
    assert k.count("ingredients") == 36

    sentinel = dict(fixtures.TEST_INGREDIENTS)
    sentinel["stage_a_sentinel"] = {
        "name": "Stage A Sentinel",
        "descr": "Exists only in this test. If it reaches the database, the rebind drove the build.",
        "season": [7],
        "regions": ["Nowhere"],
        "pairs": "Nothing.",
    }
    monkeypatch.setattr(build_db, "INGREDIENTS", sentinel)
    k.rebuild()

    assert k.count("ingredients", "id = 'stage_a_sentinel'") == 1
    assert k.count("ingredients") == 37
    assert "stage_a_sentinel" not in seed.INGREDIENTS          # never in production
    assert "stage_a_sentinel" not in fixtures.TEST_INGREDIENTS  # nor in the real fixture


def test_the_sentinel_carries_its_children_too(tmp_path, monkeypatch):
    """The season and region rows follow the same rebind. Stage B changes how these are stored, so
    pinning that they flow from the fixture now is what makes that change checkable."""
    k = harness.make_kitchen(tmp_path)
    sentinel = dict(fixtures.TEST_INGREDIENTS)
    sentinel["stage_a_sentinel"] = {"name": "Stage A Sentinel", "descr": "d",
                                    "season": [7], "regions": ["Nowhere"], "pairs": "p"}
    monkeypatch.setattr(build_db, "INGREDIENTS", sentinel)
    k.rebuild()

    assert k.count("ingredient_seasons", "ingredient_id = 'stage_a_sentinel' AND month = 7") == 1
    assert k.count("regions", "name = 'Nowhere'") == 1


# ---- the fixture is the shape the rest of the suite assumes --------------------------------------

def test_the_fixture_holds_what_the_suite_counts_on(kitchen):
    """Pins the fixture's own shape rather than comparing it to seed.py, deliberately. 23 assertions
    across 9 files hard-code 36, and test_api reads /api/in-season/6, so those numbers are load
    bearing. Comparing to seed.INGREDIENTS instead would pass today and have to be DELETED the moment
    seed.py is emptied, which is the stage this work exists to enable."""
    ing = fixtures.TEST_INGREDIENTS
    assert len(ing) == 36
    assert all(v.get("name") for v in ing.values())
    assert sum(len(v.get("season", [])) for v in ing.values()) == 65
    assert sum(len(v.get("regions", [])) for v in ing.values()) == 102
    assert len({r for v in ing.values() for r in v.get("regions", [])}) == 44
    assert [k for k, v in ing.items() if 6 in v.get("season", [])]   # /api/in-season/6 has content
    assert "garlic" in ing                                           # named 66 times across 14 files
