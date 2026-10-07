"""A test run never rewrites the repo's reports folder.

⚠️ IT WAS REWRITING SIX FILES IN IT, ON EVERY RUN. Measured 2026-10-07 from the mtimes after one
plain `pytest`: `baseline-realign.csv`, `ingredient-name-case.csv`, `notes-only-waits.csv`,
`notes-to-rows.csv`, `reparse2-dryrun.csv` and `total-vs-waits.csv`, each replaced with fixture
output under the real name. `reports/` is gitignored scratch, so nothing committed was lost and no
live data was touched. The damage is to the only thing the folder is for: `total-vs-waits.csv` is a
review list a person reads to see which recipes a survey could not settle, and it listed two
recipes called `nocook` and `unclear`, which are fixture ids, where live's survey had put a real
recipe id.

⚠️ AND THE TEST THAT WROTE IT HAD A REDIRECT ALREADY, WHICH NOTHING READ. `monkeypatch.setenv(
"RECIPE_APP_REPORTS", ...)` sat two lines above the call, and `corpus_guard.report_target` had
never heard of that variable. A redirect nobody reads is worse than none, because it reads as proof
the test cannot reach the working tree while it rewrites a file in it. The same shape as the frozen
engine that bypassed `make_kitchen`: a redirect protects the door it is nailed to.
"""
import os
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import corpus_guard                                                            # noqa: E402

REPO_REPORTS = BASE / "reports"
REPO_REPAIRS = BASE / "docs" / "data-repairs"


def test_the_wall_is_up_for_this_very_test():
    """Anti-vacuity, and it comes first. Every assertion below is worthless if the autouse fixture
    is not running, and the way it stops running is a rename nobody notices."""
    for var in ("RECIPE_APP_REPORTS", "RECIPE_APP_REPAIRS"):
        got = os.environ.get(var)
        assert got, f"{var} is not set, so the autouse fixture in conftest is not running"
        assert not str(pathlib.Path(got).resolve()).startswith(str(BASE) + os.sep), \
            f"{var} points at {got}, which is inside the repo"


def test_report_target_honours_the_redirect(tmp_path):
    got = corpus_guard.report_target("x.csv", record=False)
    assert got.parent.resolve() == pathlib.Path(os.environ["RECIPE_APP_REPORTS"]).resolve()
    assert got.name == "x.csv"


def test_record_honours_the_redirect_too(tmp_path):
    """--record is the half that reaches the COMMITTED folder, so it is walled off as well."""
    got = corpus_guard.report_target("y.csv", record=True)
    assert got.parent.resolve() == pathlib.Path(os.environ["RECIPE_APP_REPAIRS"]).resolve()


def test_the_default_without_the_variable_is_still_the_repo(monkeypatch, tmp_path):
    """The redirect is a redirect, not a new home. An ordinary run from a shell still writes to
    `reports/`, and this proves the variable is what moved it rather than a changed default."""
    monkeypatch.delenv("RECIPE_APP_REPORTS", raising=False)
    monkeypatch.delenv("RECIPE_APP_REPAIRS", raising=False)
    # Patched so the assertion costs the real folder nothing, and the chain is still the real one:
    # explicit argument, then the variable, then the module's default.
    monkeypatch.setattr(corpus_guard, "REPORTS", tmp_path / "stand-in")
    assert corpus_guard.report_target("z.csv", record=False).parent == tmp_path / "stand-in"
    assert corpus_guard.REPAIRS == REPO_REPAIRS
    assert REPO_REPORTS.name == "reports" and REPO_REPORTS.parent == BASE


def test_an_explicit_argument_still_wins_over_the_variable(tmp_path):
    """The six passes that pass `reports=` keep deciding for themselves."""
    got = corpus_guard.report_target("w.csv", record=False, reports=tmp_path / "mine")
    assert got.parent == tmp_path / "mine"


def test_a_real_survey_writes_its_list_outside_the_repo(tmp_path):
    """The end to end version, run against the writer that made this visible.

    Snapshots the repo's own folder around the call rather than trusting the path arithmetic above,
    because the defect was precisely that the arithmetic looked right.
    """
    import sqlite3
    import migrate as migrate_mod
    import scan_total_vs_waits

    before = {p.name: p.stat().st_mtime_ns for p in REPO_REPORTS.glob("*")} \
        if REPO_REPORTS.is_dir() else {}

    db = tmp_path / "survey.db"
    migrate_mod.migrate(verbose=False, db=db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO recipes (id, name, source, total_time, prep_time, cook_time) "
                "VALUES ('r','R','app','25 min','15 min','10 min')")
    con.execute("INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes,"
                " when_kind) VALUES ('r',0,'resting','a rest',15,'always')")
    con.commit()
    con.close()

    rows = scan_total_vs_waits.run(str(db))
    assert [r["recipe_id"] for r in rows] == ["r"], rows

    landed = pathlib.Path(os.environ["RECIPE_APP_REPORTS"]) / "total-vs-waits.csv"
    assert landed.is_file(), "the survey wrote its list somewhere else"
    assert "nocook" not in landed.read_text()

    after = {p.name: p.stat().st_mtime_ns for p in REPO_REPORTS.glob("*")} \
        if REPO_REPORTS.is_dir() else {}
    assert after == before, (
        "the repo's reports/ changed while a test ran:\n"
        f"  appeared: {sorted(set(after) - set(before))}\n"
        f"  rewritten: {sorted(k for k in set(after) & set(before) if after[k] != before[k])}")
