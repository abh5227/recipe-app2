"""Import runner (import_runner.run_import) — the all-or-nothing full-archive writer.

The dangerous failures this pins down: a PARTIAL import (some recipes written, then a crash),
a SILENT DROP (an entry that lands in no bucket), and importing WITHOUT a fresh backup. Tests
call run_import directly (bypassing the CLI's --yes gate) against a throwaway kitchen DB and a
small fixture archive, never the real recipes.db."""
from pathlib import Path

import pytest

import import_runner
import import_write as iw
from harness import write_paprika_archive


def _rec(uid, name, **over):
    """A raw Paprika-shape recipe dict (what iter_entries yields; reader.normalize maps it).
    'Salt to taste' is an amountless line, so each recipe records one review flag."""
    base = dict(
        uid=uid, name=name, hash="h-" + uid,
        ingredients="1 cup flour\n2 eggs\nSalt to taste",
        directions="Mix everything.\nBake until done.",
        categories=["Test"], source="Tester", rating=0,
    )
    base.update(over)
    return base


@pytest.fixture
def archive(tmp_path):
    """3 good recipes (synthetic uids — no seed-twin collision) + 1 malformed entry."""
    recs = [_rec("fix-1", "Alpha Cake"), _rec("fix-2", "Beta Stew"), _rec("fix-3", "Gamma Soup")]
    return write_paprika_archive(tmp_path / "fix.paprikarecipes", recs,
                                 malformed=["999.paprikarecipe"])


def test_end_to_end_writes_and_accounts_for_every_entry(kitchen, archive, tmp_path):
    s = import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk")

    # --- three outcome buckets, asserted separately and exhaustively ---
    assert s.written == 3                       # the three good recipes
    assert s.skipped == 0                       # nothing deduped on a first run...
    assert len(s.reader_errors) == 1            # ...and the malformed entry is REPORTED
    assert s.reader_errors[0][0] == "999.paprikarecipe"
    # every .paprikarecipe entry landed in exactly one bucket — nothing silently dropped
    assert s.entries_seen == 4
    assert s.written + s.skipped + len(s.reader_errors) == 4

    # rows actually written, app-tier, with children + flags
    assert kitchen.count("recipes", "source='app'") == 3
    assert kitchen.count("recipe_ingredients") > 0
    assert kitchen.count("recipe_steps") > 0
    assert kitchen.count("import_flags") == s.flags == 3   # one 'Salt to taste' flag each
    assert kitchen.fk_orphans() == []

    # a fresh backup was actually made
    assert s.backup_path is not None and Path(s.backup_path).exists()


def test_idempotent_second_run_skips_all_via_dedup(kitchen, archive, tmp_path):
    import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk")
    before = kitchen.count("recipes", "source='app'")
    s2 = import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk")

    assert before == 3
    assert s2.written == 0
    assert s2.skipped == 3                       # all three now skip — attributable to uid-dedup
    assert len(s2.reader_errors) == 1           # malformed still reported, not counted as skip
    assert kitchen.count("recipes", "source='app'") == 3   # no duplicates created


def test_write_failure_mid_batch_rolls_back_everything(kitchen, archive, tmp_path, monkeypatch):
    real = iw.commit_plan
    calls = {"n": 0}

    def flaky(conn, plan):
        calls["n"] += 1
        if calls["n"] == 2:                     # fail on the SECOND recipe (first already written)
            raise RuntimeError("injected write failure")
        return real(conn, plan)

    monkeypatch.setattr(iw, "commit_plan", flaky)   # the runner calls iw.commit_plan -> patched

    seed_before = kitchen.count("recipes", "source='seed'")
    with pytest.raises(RuntimeError, match="injected write failure"):
        import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk")

    # full rollback: not one app recipe, child, or flag survived the aborted batch
    assert kitchen.count("recipes", "source='app'") == 0
    assert kitchen.count("import_flags") == 0
    assert kitchen.count("recipes", "source='seed'") == seed_before   # pre-existing untouched
    assert kitchen.fk_orphans() == []


def test_aborts_without_backup_before_any_side_effect(tmp_path, archive):
    missing_db = tmp_path / "nope.db"           # does not exist -> backup must fail
    bk = tmp_path / "bk"

    with pytest.raises(FileNotFoundError):
        import_runner.run_import(missing_db, archive, backup_dir=bk)

    # the abort happened before ANY side effect: no DB created, no backup written
    assert not missing_db.exists()
    assert not bk.exists() or not any(bk.glob("recipes-*.db"))


def test_deterministic_slugs_across_fresh_dbs(kitchen, archive, tmp_path):
    """Same archive -> same minted ids, regardless of run (namelist-order iteration)."""
    import harness

    s1 = import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk1")
    k2dir = tmp_path / "k2"
    k2dir.mkdir()                                # make_kitchen doesn't create its parent dir
    other = harness.make_kitchen(k2dir)
    s2 = import_runner.run_import(other.db, archive, backup_dir=tmp_path / "bk2")

    def app_ids(k):
        with k.conn() as c:
            return sorted(r[0] for r in c.execute("SELECT id FROM recipes WHERE source='app'"))

    assert s1.written == s2.written == 3
    assert app_ids(kitchen) == app_ids(other) == ["alpha-cake", "beta-stew", "gamma-soup"]
