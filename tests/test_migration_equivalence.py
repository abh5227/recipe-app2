"""Wrapping a migration in a transaction changes WHEN it commits and nothing about the result.

⚠️ THIS IS THE HALF THE ATOMICITY TESTS CANNOT STATE. test_migration_atomicity.py proves that an
interrupted migration leaves nothing behind, which is the point of a BEGIN. It says nothing about
whether adding that BEGIN changed what an UNINTERRUPTED run produces, and that is the question a
fresh install asks: the seven older additive migrations (009, 013, 015, 018, 027, 031, 048) were
wrapped on 2026-10-07, and live is long past them, so a fresh clone is the only thing that still
runs those files at all.

The proof is stated over the FOLDER rather than over the seven, so it keeps holding as migrations
are added: build a fresh install the ordinary way, build a second one with every BEGIN and COMMIT
line stripped out of every migration, and compare the two databases row for row and byte for byte.
A wrap that changed a result would show up as a difference in the dump.

⚠️ THE COMPARISON IS `iterdump`, NOT A ROW COUNT. A count agrees while a value differs, and the
thing being checked is that a DEFAULT, a backfilling UPDATE or an index is unaffected by the
transaction around it. The dump carries the schema, every row of every table, and the indexes.
"""
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / "migrations"

# the seven wrapped in the safety round, kept by name so the test says what it was written for
WRAPPED_2026_10_07 = [
    "009_recipe_import_uid.sql", "013_ingredient_weight_convert_flag.sql",
    "015_recipe_ingredient_qty_unit.sql", "018_ownership_user_columns.sql",
    "027_cook_photo_position.sql", "031_ingredient_identity.sql", "048_ratings_cluster.sql",
]

_BUILD = """
import pathlib, sys
sys.path.insert(0, {repo!r})
import migrate, build_db
migrate.MIGRATIONS_DIR = pathlib.Path({folder!r})
migrate.DB = build_db.DB = pathlib.Path({db!r})
build_db.build()
"""


def _build(folder, db):
    """A fresh install through build_db's own code path, in a child process.

    ⚠️ A CHILD PROCESS, NOT AN IMPORT. build_db and migrate hold module-global paths, and the suite's
    own guards watch them. Rebinding them twice inside one test run leaves whichever ran last
    pointing somewhere unexpected for everything after it.

    ⚠️ AND THE CHILD GETS A CLEAN ENVIRONMENT, which it did not. A child inherits os.environ, and
    app.orm_session() prefers $DATABASE_URL over the path it is handed, so one earlier test leaving
    that variable set pointed this build at Postgres and compared two databases that were never
    written. It passed on its own and failed in a full run, which is the signature. The same applies
    to $RECIPE_APP_LIVE_DB, which decides what corpus_guard calls live."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("DATABASE_URL", "RECIPE_APP_LIVE_DB")}
    r = subprocess.run([sys.executable, "-c",
                        _BUILD.format(repo=str(REPO), folder=str(folder), db=str(db))],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"fresh install failed with {folder}:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
    return db


# ⚠️ ONE NORMALIZATION, NAMED, AND IT IS NOT THE THING UNDER TEST. migrate.py stamps every applied
# file with an applied_at to the SECOND, so two fresh installs a fraction of a second apart differ
# whenever they straddle a second boundary. The test passed on its own and failed inside a full suite
# run, which is that signature exactly. The filenames and their ORDER still have to match, so the
# stamp is replaced rather than the row dropped.
_STAMP = re.compile("(INSERT INTO \"schema_migrations\" VALUES\\('[^']+',)'[^']*'\\)")


def _dump(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return _STAMP.sub("\\1'<applied_at>')", "\n".join(con.iterdump()))
    finally:
        con.close()


def _copy_migrations(dest, strip_transactions=False):
    dest.mkdir(parents=True, exist_ok=True)
    stripped = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        text = p.read_text()
        if strip_transactions:
            out = re.sub(r"^\s*(BEGIN|COMMIT)\s*;\s*$\n?", "", text, flags=re.I | re.M)
            if out != text:
                stripped.append(p.name)
            text = out
        (dest / p.name).write_text(text)
    return stripped


def test_a_fresh_install_is_identical_with_and_without_the_transactions(tmp_path):
    """The whole folder, built both ways, compared as a full SQL dump."""
    plain = tmp_path / "mig-plain"
    bare = tmp_path / "mig-bare"
    _copy_migrations(plain)
    stripped = _copy_migrations(bare, strip_transactions=True)

    assert set(WRAPPED_2026_10_07) <= set(stripped), (
        "the seven wrapped in the safety round no longer carry a transaction: "
        f"{sorted(set(WRAPPED_2026_10_07) - set(stripped))}")

    a = _dump(_build(plain, tmp_path / "with.db"))
    b = _dump(_build(bare, tmp_path / "without.db"))
    if a != b:
        import difflib
        diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                         "with the transactions", "without them", lineterm="", n=0))
        raise AssertionError(
            "a migration's transaction changed the RESULT of a fresh install, not just when it "
            "commits:\n" + "\n".join(d[:120] for d in diff[:40]))
    assert "'<applied_at>'" in a, "the applied_at normalization stopped matching anything"
    assert "schema_migrations" in a and "ingredient_weights" in a, "the dump looks empty"


def test_the_fresh_install_the_comparison_runs_on_is_not_empty(tmp_path):
    """⚠️ THE ANTI-VACUITY HALF. Two empty databases are identical too. A fresh install seeds the
    King Arthur weights, the library names and the note kinds, and records every migration, so the
    comparison above is comparing something."""
    plain = tmp_path / "mig"
    _copy_migrations(plain)
    db = _build(plain, tmp_path / "fresh.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                  for (t,) in con.execute(
                      "SELECT name FROM sqlite_master WHERE type='table' "
                      "AND name NOT LIKE 'sqlite_%' ORDER BY name")}
    finally:
        con.close()
    assert counts["schema_migrations"] == len(list(MIGRATIONS.glob("*.sql")))
    assert counts["ingredient_weights"] >= 100, counts["ingredient_weights"]
    assert counts["library_names"] >= 1000, counts["library_names"]
    assert counts["note_kinds"] >= 5, counts["note_kinds"]
