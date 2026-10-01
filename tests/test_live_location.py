"""The live database has ONE location, and every checkout gets the same answer.

⚠️ THE DEFECT THIS FILE EXISTS FOR. `corpus_guard.is_live` compared its target against
`BASE / "recipes.db"`, where BASE is the repo root of the file it was imported from. From the main
working tree that is correct. From a detached worktree it is a path that does not exist, so
`is_live(the real live database)` returned **False** and `refuse_live` refused nothing. Measured
2026-10-01 from two worktrees with the real 328MB database sitting where it always was. The pinned
`../recipe-app-serve` is itself a worktree, and it exists precisely to run against live.

So the fix is a single absolute answer (`corpus_guard.live_db()`) and these tests prove it holds
from a worktree, which is the case the old code got wrong. They build a THROWAWAY git repo with its
own linked worktree rather than touching this repo's `.git/worktrees`, and they run the guard in a
subprocess so it is imported from the worktree's own copy, which is the thing under test.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "corpus_guard.py"
sys.path.insert(0, str(REPO / "scripts"))
import corpus_guard                                                            # noqa: E402

GIT_ID = ["-c", "user.email=t@example.com", "-c", "user.name=t"]


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _throwaway(tmp_path, worktree_name):
    """A git repo with a linked worktree, each holding its own copy of the guard, and a stand-in
    live database in the MAIN tree only. That is the real layout: a worktree has no recipes.db."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", str(main))
    (main / "README").write_text("x\n")
    _git("add", "README", cwd=main)
    _git(*GIT_ID, "commit", "-qm", "init", cwd=main)
    (main / "scripts").mkdir()
    shutil.copy(GUARD, main / "scripts" / "corpus_guard.py")
    (main / "recipes.db").write_bytes(b"SQLite format 3\x00" + bytes(200))
    wt = tmp_path / worktree_name
    _git("worktree", "add", "--detach", "-q", str(wt), cwd=main)
    (wt / "scripts").mkdir(exist_ok=True)
    shutil.copy(GUARD, wt / "scripts" / "corpus_guard.py")
    return main, wt


# the probe runs INSIDE the worktree, importing that worktree's own copy of the guard
_PROBE = r"""
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
import corpus_guard
spellings = json.loads(sys.argv[2])
out = {}
for name, spelling in spellings.items():
    try:
        live = corpus_guard.is_live(spelling)
    except Exception as e:
        out[name] = {"error": repr(e)}
        continue
    refused = None
    try:
        corpus_guard.refuse_live(spelling, False)
        refused = False
    except SystemExit:
        refused = True
    allowed = None
    try:
        corpus_guard.refuse_live(spelling, True)
        allowed = True
    except SystemExit:
        allowed = False
    out[name] = {"is_live": live, "refused_without_flag": refused, "allowed_with_flag": allowed}
try:
    out["_live_db"] = str(corpus_guard.live_db())
except Exception as e:
    out["_live_db"] = None
    out["_live_db_error"] = type(e).__name__
print(json.dumps(out))
"""


def _probe(worktree, cwd, spellings, env_extra=None):
    env = dict(os.environ)
    env.pop("RECIPE_APP_LIVE_DB", None)
    env["HOME"] = str(worktree.parent / "fakehome")      # never read the real ~/.config
    (worktree.parent / "fakehome").mkdir(exist_ok=True)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-c", _PROBE, str(worktree / "scripts"),
                        json.dumps({k: str(v) for k, v in spellings.items()})],
                       cwd=str(cwd), capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"probe failed: {r.stderr}"
    return json.loads(r.stdout)


@pytest.mark.parametrize("worktree_name", ["detached-wt", "recipe-app-serve"])
def test_a_worktree_recognises_live_in_every_spelling(tmp_path, worktree_name):
    """The case the old guard got wrong, and the pinned serving checkout is one of these."""
    main, wt = _throwaway(tmp_path, worktree_name)
    live = main / "recipes.db"
    sym = tmp_path / "symlink.db"
    os.symlink(live, sym)
    hard = tmp_path / "hardlink.db"
    os.link(live, hard)

    out = _probe(wt, cwd=main, spellings={
        "absolute": live,
        "relative": "recipes.db",                 # cwd is the main tree
        "dot": "./recipes.db",
        "dotdot": f"scripts/../{live.name}",
        "symlink": sym,
        "hardlink": hard,
    })
    # ⚠️ THE REFUSAL IS ASSERTED FIRST, so a regression reports the defect and not a missing name.
    #    The old guard answered is_live=False here and let the write through, which is exactly what
    #    this reads as when it fails.
    for name, r in out.items():
        if name.startswith("_"):
            continue
        assert r.get("is_live") is True, f"{name} was not recognized as live: {r}"
        assert r["refused_without_flag"] is True, f"{name} was NOT refused: {r}"
        assert r["allowed_with_flag"] is True, f"{name} was refused even with the flag: {r}"
    assert out["_live_db"] == str(live), out["_live_db"]


def test_a_worktree_still_lets_a_copy_through(tmp_path):
    """The guard has to stay useful. Every rehearsal runs on a copy."""
    main, wt = _throwaway(tmp_path, "wt")
    copy = tmp_path / "copy.db"
    shutil.copy(main / "recipes.db", copy)
    out = _probe(wt, cwd=main, spellings={"copy": copy, "absent": tmp_path / "nope.db"})
    for name in ("copy", "absent"):
        assert out[name]["is_live"] is False, f"{name}: {out[name]}"
        assert out[name]["refused_without_flag"] is False, f"{name} was refused: {out[name]}"


def test_the_main_tree_and_its_worktree_give_the_identical_answer(tmp_path):
    main, wt = _throwaway(tmp_path, "wt")
    from_main = _probe(main, cwd=main, spellings={"a": main / "recipes.db"})
    from_wt = _probe(wt, cwd=wt, spellings={"a": main / "recipes.db"})
    assert from_main["_live_db"] == from_wt["_live_db"] == str(main / "recipes.db")
    assert from_main["a"]["is_live"] is from_wt["a"]["is_live"] is True


def test_the_environment_variable_names_live(tmp_path):
    """An explicit path wins, for an unusual layout or a test."""
    main, wt = _throwaway(tmp_path, "wt")
    elsewhere = tmp_path / "elsewhere.db"
    elsewhere.write_bytes(b"x")
    out = _probe(wt, cwd=main,
                 spellings={"named": elsewhere, "the_git_one": main / "recipes.db"},
                 env_extra={"RECIPE_APP_LIVE_DB": str(elsewhere)})
    assert out["_live_db"] == str(elsewhere)
    assert out["named"]["is_live"] is True
    assert out["the_git_one"]["is_live"] is False


def test_the_config_file_names_live(tmp_path):
    """One line in a file outside the repo, read by every checkout without a shell variable."""
    main, wt = _throwaway(tmp_path, "wt")
    elsewhere = tmp_path / "configured.db"
    elsewhere.write_bytes(b"x")
    home = tmp_path / "fakehome"
    cfg = home / ".config" / "chefs-choice" / "live-db"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"{elsewhere}\n")
    out = _probe(wt, cwd=main, spellings={"configured": elsewhere, "git_one": main / "recipes.db"})
    assert out["_live_db"] == str(elsewhere)
    assert out["configured"]["is_live"] is True
    assert out["git_one"]["is_live"] is False


def test_an_undeterminable_location_fails_closed(tmp_path):
    """No git, no variable, no config file. Every path might be live, so every write needs the
    sentence typed out. Failing OPEN here would be a guard that silently protects nothing, which is
    the whole defect this file is about, one layer further out."""
    loose = tmp_path / "loose"
    (loose / "scripts").mkdir(parents=True)
    shutil.copy(GUARD, loose / "scripts" / "corpus_guard.py")
    anything = tmp_path / "anything.db"
    anything.write_bytes(b"x")
    out = _probe(loose, cwd=tmp_path, spellings={"anything": anything},
                 env_extra={"PATH": "/nonexistent"})          # git cannot be found
    assert out["_live_db"] is None, "a location was somehow determined"
    assert out["_live_db_error"] == "LiveLocationUnknown", out
    r = out["anything"]
    assert r["is_live"] is True, f"an unknown location failed OPEN: {r}"
    assert r["refused_without_flag"] is True, f"not refused: {r}"
    assert r["allowed_with_flag"] is True, f"refused even with the flag: {r}"


def test_the_suite_guards_the_shared_location_not_its_own_checkout(tmp_path):
    """H2 from a worktree. conftest installed dbguard against `parent.parent / recipes.db`, so a
    suite run from a worktree guarded that worktree's absent database and left the real one open."""
    import dbguard
    assert dbguard._LIVE_PATH == os.path.realpath(corpus_guard.live_db()), (
        f"the suite is guarding {dbguard._LIVE_PATH}, not {corpus_guard.live_db()}")


def test_every_registered_worktree_of_this_repo_resolves_to_one_main_tree():
    """Not a throwaway: the real checkouts, including the pinned ../recipe-app-serve."""
    listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    trees = [pathlib.Path(l.split(" ", 1)[1]) for l in listing.splitlines()
             if l.startswith("worktree ")]
    assert len(trees) >= 2, f"expected the main tree and at least one worktree, got {trees}"
    answers = {}
    for t in trees:
        if not t.exists():
            continue
        corpus_guard.reset_live_db_cache()
        answers[str(t)] = corpus_guard._main_worktree(t)
    corpus_guard.reset_live_db_cache()
    assert len(set(answers.values())) == 1, f"checkouts disagree about the main tree: {answers}"
    only = next(iter(answers.values()))
    assert (only / "recipes.db") == corpus_guard.live_db().resolve() or \
        (only / "recipes.db").resolve() == corpus_guard.live_db().resolve(), (only, corpus_guard.live_db())
