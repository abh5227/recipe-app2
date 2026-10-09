"""build_db.py names its database, reads its arguments before it opens anything, and refuses an
EXISTING live database without --i-mean-live.

⚠️ WHY. On 2026-10-09 `build_db.py --help`, typed to read the arguments, ran a full build against
live. The script read no arguments at all, and it sat outside the scripts/ folder the live-guard
sweep walks. The rows came back identical and the fingerprint moved, in a session forbidden to write.
"""
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import build_db          # noqa: E402
import corpus_guard      # noqa: E402
import migrate as migrate_module  # noqa: E402


@pytest.fixture
def calls(monkeypatch):
    """build() and sqlite3.connect record what they were asked instead of building anything."""
    seen = []
    monkeypatch.setattr(build_db, "DB", build_db.DB)          # main() rebinds it, so restore it
    monkeypatch.setattr(build_db, "build", lambda: seen.append(("build", build_db.DB)))
    real = sqlite3.connect

    def connect(*a, **k):
        seen.append(("connect", a[0] if a else k.get("database")))
        return real(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return seen


def _live_at(monkeypatch, path):
    monkeypatch.setattr(corpus_guard, "live_db", lambda: path)


def test_help_prints_and_exits_before_any_database_is_opened(calls, capsys):
    with pytest.raises(SystemExit) as stop:
        build_db.main(["--help"])
    assert stop.value.code == 0
    assert calls == [], f"--help reached {calls}"
    assert "--i-mean-live" in capsys.readouterr().out


def test_an_existing_live_database_is_refused_without_the_sentence(calls, monkeypatch, tmp_path):
    live = tmp_path / "recipes.db"
    live.write_bytes(b"")
    _live_at(monkeypatch, live)
    monkeypatch.setattr(build_db, "DB", live)                 # the default, as in the main tree
    for argv in ([], ["--db", str(live)]):
        with pytest.raises(SystemExit) as stop:
            build_db.main(argv)
        assert "--i-mean-live" in str(stop.value.code)
    assert calls == [], f"a refused run still reached {calls}"


def test_the_sentence_lets_it_through(calls, monkeypatch, tmp_path):
    live = tmp_path / "recipes.db"
    live.write_bytes(b"")
    _live_at(monkeypatch, live)
    build_db.main(["--db", str(live), "--i-mean-live"])
    assert calls == [("build", live)]


def test_a_database_that_does_not_exist_yet_is_created_without_the_sentence(calls, monkeypatch,
                                                                             tmp_path):
    """The fresh-clone setup. README runs this bare and the cold-start CI job runs README verbatim,
    and a file that does not exist yet holds nothing to protect."""
    live = tmp_path / "recipes.db"
    _live_at(monkeypatch, live)
    build_db.main(["--db", str(live)])
    assert calls == [("build", live)]


def test_a_copy_needs_no_sentence(calls, monkeypatch, tmp_path):
    live = tmp_path / "live" / "recipes.db"
    live.parent.mkdir()
    live.write_bytes(b"")
    copy = tmp_path / "copy.db"
    copy.write_bytes(b"")
    _live_at(monkeypatch, live)
    build_db.main(["--db", str(copy)])
    assert calls == [("build", copy)]


def test_a_real_build_migrates_and_seeds_the_same_file(monkeypatch, tmp_path):
    """⚠️ build() used to call migrate() with no path, and migrate() falls back to ITS OWN module
    global. Redirecting build_db.DB alone migrated one database and seeded another."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(build_db, "DB", build_db.DB)
    elsewhere = tmp_path / "must-not-be-created.db"
    monkeypatch.setattr(migrate_module, "DB", elsewhere)
    _live_at(monkeypatch, tmp_path / "live" / "recipes.db")
    target = tmp_path / "new.db"
    build_db.main(["--db", str(target)])
    con = sqlite3.connect(target)
    applied = con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    weights = con.execute("SELECT COUNT(*) FROM ingredient_weights").fetchone()[0]
    con.close()
    assert applied == len(list((REPO / "migrations").glob("*.sql")))
    assert weights > 0
    assert not elsewhere.exists(), "migrate() ran against its own default instead of --db"
