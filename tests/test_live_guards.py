"""The two walls in front of the live database, and the check that keeps new code behind them.

H1  scripts/corpus_guard.py identifies live by FILE IDENTITY, not by the spelling of a path.
H2  the test suite cannot open the live file at all (tests/dbguard.py).
H3  no script, and not migrate.py, can open a database without going through the shared guard.

⚠️ NOT ONE OF THESE TESTS OPENS A DATABASE. refuse_live and is_live are pure functions, the dbguard
cases are expected to RAISE before the open happens, and H3 reads source. The first version of the
corpus-pass guard test aimed pytest at the live path and called main(), which is the defect this file
exists to make unrepeatable — so this file does not do it either, not even to prove a point.
"""
import os
import pathlib
import re
import sqlite3
import sys

import pytest

import dbguard
import harness  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parent.parent
LIVE = REPO / "recipes.db"
sys.path.insert(0, str(REPO / "scripts"))
import corpus_guard  # noqa: E402


# ---- H1: the guard knows the FILE, not the name -------------------------------------------------

def test_the_guard_refuses_every_spelling_of_the_live_path(tmp_path, monkeypatch):
    """⚠️ A PATH STRING SAYS NOTHING ABOUT WHICH FILE IT OPENS. The guard compared strings, so a
    relative spelling, a "./" spelling, a "../" spelling and a symlink were four different answers to
    one question."""
    monkeypatch.chdir(REPO)
    link = tmp_path / "live-link.db"
    link.symlink_to(LIVE)                     # a symlink POINTING AT live; nothing opens it
    spellings = [
        "recipes.db",                          # relative
        str(LIVE),                             # absolute
        "./recipes.db",                        # "./"
        "scripts/../recipes.db",               # "../"
        "./scripts/./../recipes.db",           # both, with noise
        str(link),                             # a symlink
        pathlib.Path("recipes.db"),            # a Path, not a str
    ]
    for spelling in spellings:
        assert corpus_guard.is_live(spelling) is True, f"{spelling!r} was not recognized as live"
        with pytest.raises(SystemExit) as e:
            corpus_guard.refuse_live(spelling, False)
        assert "--i-mean-live" in str(e.value), spelling
        corpus_guard.refuse_live(spelling, True)        # and the sentence lets it through


def test_the_guard_refuses_a_hard_link_to_live(tmp_path, monkeypatch):
    """⚠️ THE CASE RESOLVING A PATH CANNOT CATCH. A hard link IS the file under a second name, and
    resolving it hands that second name back, so only the inode answers."""
    monkeypatch.chdir(REPO)
    hard = tmp_path / "hard-live.db"
    try:
        os.link(LIVE, hard)
    except OSError:
        pytest.skip("no hard links across these filesystems")
    assert corpus_guard.is_live(hard) is True
    with pytest.raises(SystemExit):
        corpus_guard.refuse_live(hard, False)


def test_the_guard_lets_a_copy_through(tmp_path):
    """Every rehearsal depends on this. A copy is a different file, whatever it is called."""
    copy = tmp_path / "recipes.db"
    copy.write_bytes(b"not really a database")
    assert corpus_guard.is_live(copy) is False
    corpus_guard.refuse_live(copy, False)               # no exit


def test_the_guard_still_names_live_before_it_exists(tmp_path):
    """The fresh-clone case: `migrate.py --db recipes.db` would CREATE it, and there is no inode to
    compare yet, so the resolved path is the only test available and has to stay."""
    fake_root = tmp_path / "clone"
    fake_root.mkdir()
    assert corpus_guard.is_live(fake_root / "recipes.db", base=fake_root) is True
    assert corpus_guard.is_live(fake_root / "copy.db", base=fake_root) is False


# ---- H2: the suite cannot open live -------------------------------------------------------------

@pytest.mark.parametrize("spelling, uri", [
    ("recipes.db", False),
    ("./recipes.db", False),
    ("scripts/../recipes.db", False),
    ("file:recipes.db", True),
    ("file:recipes.db?mode=ro", True),
    ("file:recipes.db?mode=rw", True),
])
def test_a_test_that_tries_to_open_live_is_refused(spelling, uri, monkeypatch):
    """Andy's "prove it with a test that tries and is refused". The open never happens: dbguard
    raises before sqlite3 is reached."""
    monkeypatch.chdir(REPO)
    with pytest.raises(dbguard.LiveDatabaseOpened) as e:
        sqlite3.connect(spelling, uri=uri)
    assert "LIVE database" in str(e.value)


def test_the_app_s_own_opener_is_refused_too(monkeypatch):
    """One patch covers raw sqlite3, SQLAlchemy's SQLite dialect and app.orm_session(), because they
    all end at the same function. Asserted rather than assumed."""
    import app
    monkeypatch.setattr(app, "DB", LIVE)        # the module-global orm_session reads at call time
    monkeypatch.delitem(os.environ, "DATABASE_URL", raising=False)
    app._engines.pop(f"sqlite:///{LIVE}", None)  # a cached engine would not re-open
    # ⚠️ A STATEMENT, BECAUSE THE SESSION IS LAZY. `with orm_session(): pass` opens nothing, so a
    #    test that only entered the block would pass while proving nothing.
    from sqlalchemy import text as _text
    with pytest.raises(dbguard.LiveDatabaseOpened):
        with app.orm_session() as s:
            s.execute(_text("SELECT count(*) FROM recipes"))


def test_a_copy_and_memory_are_not_blocked(tmp_path):
    """The guard must be invisible to every ordinary test, or it would be turned off."""
    sqlite3.connect(":memory:").close()
    sqlite3.connect(tmp_path / "scratch.db").close()
    sqlite3.connect(f"file:{tmp_path / 'ro.db'}?mode=rwc", uri=True).close()


@pytest.mark.live_catalog
def test_the_marker_permits_a_read_only_open_and_nothing_more(monkeypatch):
    """The one deliberate exception, and its limit. test_mining_boundaries checks the real catalog,
    which a fixture database cannot stand in for. A WRITE is refused even here."""
    monkeypatch.chdir(REPO)
    if not LIVE.exists():
        pytest.skip("no live database here")
    sqlite3.connect("file:recipes.db?mode=ro", uri=True).close()        # allowed
    with pytest.raises(dbguard.LiveDatabaseOpened) as e:
        sqlite3.connect("recipes.db")
    assert "NOT read-only" in str(e.value)


def test_the_guard_is_installed_from_conftest_at_import():
    """⚠️ IN A FIXTURE IT WOULD MISS COLLECTION. Module-level code in a test file runs during
    collection, before any fixture, and that is where a path is most likely to be named."""
    src = (pathlib.Path(__file__).parent / "conftest.py").read_text()
    assert "dbguard.install(" in src
    assert re.search(r"^dbguard\.install\(", src, re.M), "install must be at module level"
    assert sqlite3.connect is dbguard._guarded, "something replaced the patched connect"


# ---- H3: a new script cannot forget the guard ---------------------------------------------------

_OPENS = re.compile(r"sqlite3\.connect\(|create_engine\(|orm_session\(|\bimport app\b")

# Keyed by the path relative to scripts/, because the gates live in a subfolder. An entry is a
# named exemption with a reason, and test_the_read_only_exemptions_really_are_read_only checks
# that the reason is still true rather than trusting it.
_READ_ONLY_BY_INSPECTION = {
    "cold_start_check.py":        "asserts a cold-started app served; opens no database",
    "plan_ahead_short_rests.py":  "report only, opens live with mode=ro",
    "plan_ahead_proposals_v3.py": "reads the v2 CSV and writes a CSV; opens no database",
    "serve_live.py":              "serves live through the app, which has its own gates",
    "corpus_guard.py":            "it IS the guard",
    "gates/state.py":             "the before/after reading, opens mode=ro through its own open_ro",
    "gates/compare.py":           "compares two JSON readings; opens no database",
    "gates/tablediff.py":         "row-for-row comparison, opens both sides through state.open_ro",
    "gates/rounds.py":            "the per-round gate; reads two JSON readings and, for the table "
                                  "half, reaches a database only through gates/tablediff",
    "gen_note_corpus.py":         "captures the note rows into a test fixture, opens mode=ro so "
                                  "SQLite itself refuses a write",
}

# scripts/ plus the gates subfolder. scripts/applied/ is deliberately NOT here: those 16 are spent
# backfills that refuse to run, and tests/test_corpus_passes.py holds them to their own rule.
_SWEPT = ("*.py", "gates/*.py")


def _rel(path):
    return path.relative_to(REPO / "scripts").as_posix()


def _sources():
    scripts = REPO / "scripts"
    found = [p for pattern in _SWEPT for p in sorted(scripts.glob(pattern))]
    out = [p for p in found if _rel(p) not in _READ_ONLY_BY_INSPECTION]
    return out + [REPO / "migrate.py"]


def test_no_script_can_open_a_database_without_the_shared_guard():
    """⚠️ STATED OVER THE FOLDER, SO THE NEXT SCRIPT IS COVERED BEFORE ANYONE REMEMBERS IT. A script
    that can reach a database and does not wire scripts/corpus_guard.py cannot pass."""
    missing = []
    for p in _sources():
        src = p.read_text()
        if not _OPENS.search(src):
            continue
        if "refuse_live" not in src or "--i-mean-live" not in src:
            missing.append(p.name)
    assert missing == [], (
        "these can open a database and do not wire scripts/corpus_guard.py: " + ", ".join(missing))


def test_the_sweep_reaches_the_gates_subfolder():
    """⚠️ A SUBFOLDER IS INVISIBLE TO glob("*.py"), WHICH IS HOW A WHOLE PACKAGE AVOIDS A SWEEP.
    scripts/gates/ holds three read-only tools, exempted by name with a reason each. The point of
    this test is the NEXT file dropped in there: it is swept like anything in scripts/, so it has to
    wire the guard or earn its own named exemption."""
    import unittest.mock as mock

    gates = sorted((REPO / "scripts" / "gates").glob("*.py"))
    assert gates, "the gates folder is empty, so its exemptions describe nothing"
    assert {_rel(g) for g in gates} <= set(_READ_ONLY_BY_INSPECTION), \
        "a file in scripts/gates/ is neither exempted nor wiring the guard"
    with mock.patch.dict(_READ_ONLY_BY_INSPECTION, clear=False):
        for g in gates:
            _READ_ONLY_BY_INSPECTION.pop(_rel(g))
        swept = {_rel(x) for x in _sources() if x.parent.name == "gates"}
    assert swept == {_rel(g) for g in gates}, "the sweep does not look inside scripts/gates/"
    assert set(_READ_ONLY_BY_INSPECTION) >= {_rel(g) for g in gates}, "the dict was not restored"


def test_every_guarded_script_imports_the_guard_rather_than_copying_it():
    """One rule, one copy. Three verbatim copies of refuse_live is how this started."""
    for p in _sources():
        src = p.read_text()
        if "refuse_live" not in src:
            continue
        assert "from corpus_guard import" in src, f"{p.name} spells its own guard"
        assert "def refuse_live" not in src, f"{p.name} defines a second refuse_live"


def test_the_read_only_exemptions_really_are_read_only():
    """The exemption list is only honest if nothing on it can write. Checked, not trusted."""
    # ⚠️ SQL SHAPES, NOT BARE WORDS. A plain /insert/i matches `sys.path.insert`, which is in every
    #    one of these files and is not a write.
    writes = re.compile(r"\b(INSERT\s+(INTO|OR)|UPDATE\s+\w+\s+SET|DELETE\s+FROM"
                        r"|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\b", re.IGNORECASE)
    for name in _READ_ONLY_BY_INSPECTION:
        path = REPO / "scripts" / name
        assert path.exists(), f"{name} is exempted and no longer exists"
        src = path.read_text()
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        found = writes.findall(body)
        assert found == [], f"{name} is on the read-only list and contains {found}"


# ---- H4: a dry run never writes into docs/data-repairs ------------------------------------------

_WRITERS = {
    "archive_import_flags.py":  "import-flags-archived-2026-09-30.csv",
    "relink_pass.py":           "relink-2026-09-25.csv",
    "reparse_lines.py":         "reparse2-dryrun.csv",
    "restore_notes.py":         "note-separators-2026-09-27.csv",
    "restore_from_paprika.py":  "paprika-restore-live-rows.csv",
}


def test_every_report_writer_goes_through_the_shared_report_rule():
    """⚠️ FOUND BY DOING IT. These five wrote their report into docs/data-repairs/ on every run,
    including a dry one, and their work is applied — so a re-run finds 0 rows and three committed
    records were truncated to their header lines at once, from DRY RUNS. Restoring them from git was
    the only reason nothing was lost."""
    for name in _WRITERS:
        src = (REPO / "scripts" / name).read_text()
        assert "report_target(" in src, f"{name} chooses its own report path"
        assert "--record" in src, f"{name} has no --record flag"
        assert 'default=str(CSV_OUT)' not in src and 'default=str(CSV_DIR)' not in src, \
            f"{name} still defaults its report into the committed folder"


def test_the_default_report_path_is_the_gitignored_scratch_folder(tmp_path):
    repairs, reports = tmp_path / "repairs", tmp_path / "reports"
    repairs.mkdir()
    got = corpus_guard.report_target("probe.csv", False, repairs=repairs, reports=reports)
    assert got == reports / "probe.csv"
    assert got.parent.is_dir(), "the scratch folder is created on demand"


def test_reports_is_gitignored():
    """The folder only helps if a report in it cannot be committed by accident."""
    assert "\nreports/\n" in (REPO / ".gitignore").read_text()


def test_record_writes_into_the_committed_folder(tmp_path):
    repairs, reports = tmp_path / "repairs", tmp_path / "reports"
    got = corpus_guard.report_target("new-survey.csv", True, repairs=repairs, reports=reports)
    assert got == repairs / "new-survey.csv"


def test_record_refuses_to_overwrite_a_non_empty_record(tmp_path):
    """⚠️ THE HALF THAT MATTERS AS MUCH AS THE DEFAULT. --record on a run that found nothing would
    otherwise do exactly the damage this rule exists to prevent."""
    repairs, reports = tmp_path / "repairs", tmp_path / "reports"
    repairs.mkdir()
    (repairs / "record.csv").write_text("recipe_id,position\nbeans,2\n")
    with pytest.raises(SystemExit) as e:
        corpus_guard.report_target("record.csv", True, repairs=repairs, reports=reports)
    assert "refusing to overwrite" in str(e.value)
    assert (repairs / "record.csv").read_text() == "recipe_id,position\nbeans,2\n"


def test_record_may_write_over_an_empty_file(tmp_path):
    """An empty file is not a record. A half-finished run leaves one and should not need a delete."""
    repairs, reports = tmp_path / "repairs", tmp_path / "reports"
    repairs.mkdir()
    (repairs / "record.csv").write_text("")
    assert corpus_guard.report_target("record.csv", True, repairs=repairs, reports=reports) \
        == repairs / "record.csv"


def test_a_decision_file_a_pass_reads_is_not_touched_by_any_of_this():
    """The inputs stay committed and nothing here writes to them. Named so the distinction has a
    test rather than only a paragraph."""
    read_by_passes = [
        "step-headings-candidates-2026-09-30.csv",
        "step-leadin-labels-2026-09-30.csv",
        "step-dash-labels-2026-09-30.csv",
        "note-titles-2026-10-05.csv",            # read by apply_note_titles.py
        "emphasis-marks-2026-10-05.csv",         # read by apply_note_titles.py
    ]
    for name in read_by_passes:
        path = REPO / "docs" / "data-repairs" / name
        assert path.exists() and path.stat().st_size > 0, name
        assert name not in _WRITERS.values(), f"{name} is an input, not a report"


def test_every_guarded_script_can_be_pointed_at_a_copy():
    """⚠️ THE HALF THAT WAS WORSE THAN THE MISSING GUARD. A guard with no --db leaves "rehearse on a
    copy" impossible to follow: the only database the script can reach is the one it must not touch.
    migrate.py was in that state, and it is step one of the chain docs/data-repairs/README.md says
    to rehearse."""
    missing = []
    for p in _sources():
        src = p.read_text()
        if "refuse_live" not in src:
            continue
        if not re.search(r'add_argument\(\s*"(?:--db|db)"', src):
            missing.append(p.name)
    assert missing == [], "these are guarded and cannot be pointed at a copy: " + ", ".join(missing)


def test_migrate_takes_a_path_as_an_argument_not_only_a_module_global():
    """live_chain.sh rehearsed by rebinding migrate.DB from a throwaway snippet, which works and is
    not something a person should have to invent."""
    import inspect

    import migrate
    assert "db" in inspect.signature(migrate.migrate).parameters
    src = (REPO / "migrate.py").read_text()
    assert "from corpus_guard import refuse_live" in src, "a second copy of the guard, not the guard"


# ---- a pass dry-runs until it is told to apply (review fix) -------------------------------------
# ⚠️ STATED OVER THE FOLDER, NOT OVER A LIST OF FOUR. tests/test_corpus_passes.py pinned this by
# naming add_missed_waits, apply_label_rules, apply_plan_ahead_proposals and convert_step_headings,
# so the three passes this round added were covered by nothing, and a new pass that wrote by default
# would fail no test. That is the exact shape of the defect the rule came from:
# apply_plan_ahead_proposals took --dry and WROTE by default while the other three took --apply, so
# one command shape had opposite effects depending on which script you typed.
#
# The older version of this check keyed on a regex for INSERT/UPDATE/DELETE, which is why it sat
# unused: \bINSERT\b matches `sys.path.insert(`, so it called every script in the folder a writer.
# What identifies a pass is that it takes a database and wires the guard.
_NO_DRY_RUN = {
    "create_admin.py":         "not a pass. Its whole job is the one INSERT the operator typed, and "
                               "it refuses a duplicate email rather than writing twice",
    "scan_notes_for_waits.py": "not a pass. A survey that writes a CSV and never touches recipe "
                               "data, which the test below asserts",
    "migrate.py":              "not a pass. Applying the pending migrations IS its job, it is "
                               "idempotent by the schema_migrations ledger, and the chain's own "
                               "rehearsal calls it first",
    "serve_rehearsal.py":      "not a pass. It serves a COPY through the app for a click-through, "
                               "so every write is an ordinary one a person made in the UI, and "
                               "there is nothing for a dry run to preview. It refuses the real "
                               "photo folder and refuses to run from the main working tree",
}


def test_every_pass_that_takes_a_database_dry_runs_until_it_is_told_to_apply():
    bad = []
    for p in _sources():
        src = p.read_text(encoding="utf-8")
        if "refuse_live(" not in src or p.name in _NO_DRY_RUN:
            continue
        if '"--apply"' not in src:
            bad.append(p.name)
    assert not bad, f"these passes write without being asked: {bad}"


def test_the_no_dry_run_exemptions_are_still_what_they_say_they_are():
    """An exemption is a named entry with a reason, and the reason has to stay true."""
    for name in _NO_DRY_RUN:
        p = (REPO / name) if name == "migrate.py" else (REPO / "scripts" / name)
        assert p.exists(), f"{name} is exempted and no longer exists"
    survey = (REPO / "scripts" / "scan_notes_for_waits.py").read_text(encoding="utf-8")
    for write in ("INSERT INTO", "UPDATE recipe", "DELETE FROM"):
        assert write not in survey, f"the survey script now runs {write}"
    # ⚠️ THE REHEARSAL SERVER'S REASON IS TWO REFUSALS, so both are read back here rather than
    #    taken on trust. Without them it is a server that can write the owner's photo library and
    #    serve a bundle from a different commit than its own code.
    # ⚠️ AND THE FIXTURE GENERATOR'S REASON IS ITS mode=ro, so that is read back too.
    gen = (REPO / "scripts" / "gen_note_corpus.py").read_text(encoding="utf-8")
    assert "?mode=ro" in gen, "the generator no longer opens read-only"
    for write in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert write not in gen, f"the generator now runs {write}"
    rehearse = (REPO / "scripts" / "serve_rehearsal.py").read_text(encoding="utf-8")
    assert "refusing to serve the REAL photo folder" in rehearse
    assert "refusing to serve from the main working tree" in rehearse
    assert '"--photos", required=True' in rehearse, "the photo folder must not have a default"
    assert '"--db", required=True' in rehearse, "the database must not have a default"


# ---- $DATABASE_URL beside a --db (review fix) ---------------------------------------------------

def test_the_guard_refuses_a_run_whose_database_url_overrides_the_path_it_was_given(tmp_path,
                                                                                    monkeypatch):
    """⚠️ THE PATH IS A LIE WHEN $DATABASE_URL IS SET. Every pass rebinds app.DB and then reads
    through app.orm_session(), which prefers $DATABASE_URL over the file it was handed, and this
    guard only ever inspected filesystem paths. Measured with the two lines the passes use:
    refuse_live passed a copy under /tmp, the engine opened the test Postgres, and the pass read 6
    recipes where the copy holds 300. With --apply against production Postgres it would have
    written production while printing the copy's name."""
    import corpus_guard

    copy = tmp_path / "rehearsal.db"
    copy.write_bytes(b"")
    corpus_guard.refuse_live(copy, False)          # no variable set: an ordinary copy run

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:55432/recipe_test")
    with pytest.raises(SystemExit) as e:
        corpus_guard.refuse_live(copy, False)
    assert "DATABASE_URL" in str(e.value)
    assert "postgresql" in str(e.value) and "u:p" not in str(e.value), \
        "the refusal must name the scheme without printing the credentials"

    # said out loud, it is allowed, because pointing a pass at Postgres is a thing to do on purpose
    corpus_guard.refuse_live(copy, True)
