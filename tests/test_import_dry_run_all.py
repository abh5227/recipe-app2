"""Full-corpus dry-run (import_write --all path) — the writes-nothing preview over EVERY
archive entry.

Pins the properties the real import depends on: it covers every entry (nothing sampled
away), threads slug/uid state across the batch the way the runner does (so collisions and
dedup are predicted, not guessed), and — critically — WRITES NOTHING and never touches the
author sampler. Everything runs against a throwaway kitchen DB + fixture archive, never the
real recipes.db."""
import zipfile

import pytest

import import_write as iw
from harness import write_paprika_archive


def _rec(uid, name, **over):
    """A raw Paprika-shape recipe dict (what iter_entries yields; reader.normalize maps it)."""
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
    """3 good recipes (synthetic uids, no seed-twin collision) + 1 malformed entry."""
    recs = [_rec("dr-1", "Alpha Cake"), _rec("dr-2", "Beta Stew"), _rec("dr-3", "Gamma Soup")]
    return write_paprika_archive(tmp_path / "fix.paprikarecipes", recs,
                                 malformed=["999.paprikarecipe"])


def test_plan_all_covers_every_entry_and_writes_nothing(kitchen, archive):
    before = kitchen.count("recipes", "source='app'")
    with zipfile.ZipFile(archive) as zf:
        uid_index, taken = iw.db_state(kitchen.db)
        plans, errs = iw.plan_all(zf, uid_index, taken)

    # every good entry planned, malformed REPORTED — nothing sampled away, nothing lost
    assert len(plans) == 3
    assert all(p["decision"] == "write" for p in plans)
    assert len(errs) == 1 and errs[0][0] == "999.paprikarecipe"

    # writes nothing: not one app row appeared from planning the whole archive
    assert kitchen.count("recipes", "source='app'") == before == 0


def test_dry_run_all_leaves_app_count_unchanged(kitchen, archive, capsys):
    before = kitchen.count("recipes", "source='app'")
    iw.dry_run_all(db=kitchen.db, archive=archive, verbose=False)
    out = capsys.readouterr().out

    assert kitchen.count("recipes", "source='app'") == before == 0
    assert "WRITES NOTHING" in out
    assert "nothing written" in out


def test_verbose_prints_per_recipe_plan(kitchen, archive, capsys):
    iw.dry_run_all(db=kitchen.db, archive=archive, verbose=True)
    out = capsys.readouterr().out
    # verbose adds a WRITE block per recipe (print_plan), naming each planned slug
    assert "alpha-cake" in out and "beta-stew" in out and "gamma-soup" in out
    assert kitchen.count("recipes", "source='app'") == 0


def test_sampler_is_never_on_the_all_path(kitchen, archive, monkeypatch):
    """Direct proof the distinct-author sampler is off the --all path: make it explode, then
    confirm the full-corpus dry-run runs to completion regardless."""
    def boom(*a, **k):
        raise AssertionError("select_distinct_authors must not run on the --all path")

    monkeypatch.setattr(iw, "select_distinct_authors", boom)
    iw.dry_run_all(db=kitchen.db, archive=archive, verbose=False)   # must NOT raise


def test_duplicate_titles_collide_and_are_detected(kitchen, tmp_path):
    """Two DISTINCT uids with the SAME title -> the second must mint <slug>-2 (taken threaded
    across the batch), and summarize_all must report exactly that one collision."""
    recs = [_rec("c-1", "Zzz Collision Dish"), _rec("c-2", "Zzz Collision Dish")]
    arc = write_paprika_archive(tmp_path / "dup.paprikarecipes", recs)
    with zipfile.ZipFile(arc) as zf:
        uid_index, taken = iw.db_state(kitchen.db)
        plans, errs = iw.plan_all(zf, uid_index, taken)
    stats = iw.summarize_all(plans, errs)

    assert [p["recipe"]["id"] for p in plans] == ["zzz-collision-dish", "zzz-collision-dish-2"]
    assert stats["collisions"] == [("Zzz Collision Dish", "zzz-collision-dish-2")]
    assert ("Zzz Collision Dish", 2) in stats["dup_titles"]


def test_already_imported_uids_are_skipped_not_rewritten(kitchen, archive, tmp_path):
    """After a real import of the fixture, the dry-run must classify all three as uid-dedup
    SKIPs (attributable to the twins just written) and still write nothing itself."""
    import import_runner
    import_runner.run_import(kitchen.db, archive, backup_dir=tmp_path / "bk")

    with zipfile.ZipFile(archive) as zf:
        uid_index, taken = iw.db_state(kitchen.db)
        plans, errs = iw.plan_all(zf, uid_index, taken)
    stats = iw.summarize_all(plans, errs)

    assert stats["would_write"] == 0
    assert len(stats["skips"]) == 3
    assert kitchen.count("recipes", "source='app'") == 3   # unchanged by the dry-run
