#!/usr/bin/env python3.13
"""The shared write guards: which database a script may open, and where its report may land.

⚠️ ONE RULE, ONE COPY, FOUR CALLERS. It lived in four places: three verbatim copies of
`refuse_live` and a fourth inlined in `apply_plan_ahead_proposals.main()`. That is the shape this
round spent its length fixing everywhere else (`move_link_out_of_label` was the one that got away),
and it is a poor shape for the single rule the whole safety story rests on.

⚠️ AND THE TEST THAT COVERS IT MUST NOT CALL `main()`. The first version of that test set
`sys.argv` to the live database path and called `main()`, so the guard was the only thing between an
ordinary `pytest` run and a real migration of the 300-recipe live database. For
`apply_plan_ahead_proposals`, which wrote by default, there was not even an `--apply` to withhold.
`refuse_live` is a pure function and the test calls it directly.
"""
import functools
import os
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent

LIVE_DB_NAME = "recipes.db"
LIVE_DB_ENV = "RECIPE_APP_LIVE_DB"
LIVE_DB_CONFIG = pathlib.Path("~/.config/chefs-choice/live-db")


class LiveLocationUnknown(RuntimeError):
    """Where the live database lives could not be determined, so no path may be assumed safe."""


@functools.cache
def _main_worktree(start):
    """The MAIN checkout, found through git, which is the same answer from every worktree.

    A linked worktree's COMMON git dir is the main checkout's `.git`, so its parent is the main
    working tree. `scripts/serve_live.py` already finds the live data this way from the pinned
    checkout. Cached because `tests/dbguard.py` asks the guard on every `sqlite3.connect`, and a
    `git` subprocess per connection would cost the suite minutes.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    common = pathlib.Path(out.stdout.strip() or ".")
    return common.parent if common.name == ".git" else None


def live_db():
    """The ONE absolute path of the live database, the same answer from every checkout.

    ⚠️ THE GUARD USED TO ASK ITS OWN CHECKOUT, WHICH IS WHY THIS FUNCTION EXISTS. `is_live` compared
    against `BASE / "recipes.db"`, and BASE is the repo root of the file it was imported from. From
    the main working tree it answered correctly. From a detached worktree it answered
    `is_live(real live) == False`, because it looked for `recipes.db` beside its own copy of this
    file and found nothing, so a script run out of a worktree and pointed at the real path was NOT
    refused. Measured 2026-10-01 from two worktrees, False in both, with the real 328MB database
    sitting where it always was. Three checkouts had three different ideas of what live meant, and
    the pinned `../recipe-app-serve` is a worktree that exists to run against live.

    Resolution order, first answer wins:
      1. $RECIPE_APP_LIVE_DB                an explicit absolute path, for an odd layout or a test
      2. ~/.config/chefs-choice/live-db     one line holding that path, read by every checkout
      3. git                                the main working tree's recipes.db, the normal answer

    Raises LiveLocationUnknown when none of the three answers, which the callers read as "every
    path might be live" rather than "no path is live".
    """
    env = (os.environ.get(LIVE_DB_ENV) or "").strip()
    if env:
        return pathlib.Path(env).expanduser()
    try:
        cfg = LIVE_DB_CONFIG.expanduser()
        if cfg.is_file():
            line = cfg.read_text(encoding="utf-8").strip()
            if line:
                return pathlib.Path(line).expanduser()
    except OSError:
        pass
    main = _main_worktree(BASE)
    if main is not None:
        return main / LIVE_DB_NAME
    raise LiveLocationUnknown(
        f"cannot tell where the live database is, so no path can be called safe.\n"
        f"  Set {LIVE_DB_ENV} to its absolute path, or put that path in\n"
        f"  {LIVE_DB_CONFIG}.")


def reset_live_db_cache():
    """Forget the cached git lookup, for a test that moves the repo or changes the environment."""
    _main_worktree.cache_clear()


def _identity(path):
    """(device, inode) for `path`, or None when it does not exist.

    ⚠️ THE FILE, NOT THE SPELLING OF ITS NAME. A path string says nothing about which file it opens.
    `./recipes.db`, `scripts/../recipes.db`, a symlink in /tmp and a HARD LINK anywhere all open the
    live database, and a guard that compared strings would have let three of those four through.
    Resolving the path handles the first three; only the inode handles a hard link, because a hard
    link IS the file under a second name and resolving it gives that second name back."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


def is_live(db, base=None):
    """True when `db` names the live database, whatever it is spelled as and whichever checkout asks.

    Live is the ONE file `live_db()` names. A copy under any other name or in any other directory
    passes straight through, which is what every rehearsal relies on.

    TWO TESTS, AND THE UNION OF THEM, because each answers a case the other cannot:
      * file identity  catches every alias of an EXISTING file, including a hard link.
      * resolved path  catches live BEFORE IT EXISTS, which is the fresh-clone case, where there is
                       no inode to compare and `migrate.py --db recipes.db` would create it.

    `base` names a repo root explicitly and is the test seam for the fresh-clone case. Without it
    the answer comes from `live_db()`, and a location that cannot be determined FAILS CLOSED: every
    path is treated as live, so a write needs the sentence typed out.
    """
    if base is not None:
        live = pathlib.Path(base).resolve() / LIVE_DB_NAME
    else:
        try:
            live = live_db()
        except LiveLocationUnknown:
            return True
    live = pathlib.Path(live).resolve()
    if pathlib.Path(db).resolve() == live:
        return True
    here = _identity(db)
    return here is not None and here == _identity(live)


def refuse_live(db, i_mean_live, base=None):
    """Exit unless the caller said `--i-mean-live`, when `db` is (or might be) the live database.

    ⚠️ AND A $DATABASE_URL BESIDE A --db IS REFUSED OUTRIGHT, BECAUSE THE PATH IS THEN A LIE. Every
    pass rebinds app.DB and reads through app.orm_session(), which prefers $DATABASE_URL over the
    file it was handed, and this guard only ever inspected filesystem paths. Measured with the two
    lines the passes use: refuse_live passed a copy under /tmp, the engine opened
    postgresql+psycopg://…/recipe_test, and the pass read 6 recipes where the copy holds 300. With
    --apply against production Postgres it would have written production while printing the copy's
    name. Pointing a pass at Postgres is a thing to build deliberately, not a thing to reach by
    leaving a variable set in a shell."""
    url = os.environ.get("DATABASE_URL")
    if url and not i_mean_live:
        sys.exit(f"refusing to run with DATABASE_URL set ({url.split('://')[0]}://…): this pass "
                 f"takes a FILE and opens whatever that variable names instead. Unset it, or say "
                 f"--i-mean-live if that database really is the target.")
    if i_mean_live:
        return
    if base is None:
        try:
            live_db()
        except LiveLocationUnknown as e:
            sys.exit(f"refusing to write {db} without --i-mean-live.\n  {e}")
    if is_live(db, base):
        sys.exit(f"refusing to write live {LIVE_DB_NAME} without --i-mean-live")


# ---- where a report may land (H4) ---------------------------------------------------------------

REPORTS = BASE / "reports"            # gitignored scratch, created on demand
REPAIRS = BASE / "docs" / "data-repairs"


def report_target(filename, record, repairs=None, reports=None):
    """Where this run's report CSV goes, and whether writing it is allowed.

    ⚠️ A DRY RUN THAT DESTROYS A RECORD IS NOT A DRY RUN, AND THIS IS THE RULE THAT CAME OUT OF IT.
    Five scripts wrote their report into docs/data-repairs/, which holds the record of what was done
    to the data, and wrote it on every run including a dry one. Their work is applied, so a re-run
    finds 0 rows — and three committed records were truncated to their header lines at once, from
    DRY RUNS. Restoring them from git was the only reason nothing was lost.

    So the default is a gitignored scratch folder, and reaching the committed folder takes a word:

        no --record    reports/<filename>              scratch, overwritten freely
        --record       docs/data-repairs/<filename>    and NEVER over a non-empty file

    The second half matters as much as the first. `--record` on a run that found nothing would
    otherwise do exactly the damage this rule exists to prevent, so an existing non-empty file is a
    refusal rather than an overwrite. A record is replaced by deleting it on purpose, which is a
    thing a person does and a script does not.

    Decision files the passes READ are untouched by any of this: they are inputs, they stay
    committed, and nothing here writes to them.

    ⚠️ AND BOTH FOLDERS ARE REDIRECTABLE, BECAUSE THE TEST SUITE WAS WRITING INTO THE REAL ONE.
    `$RECIPE_APP_REPORTS` and `$RECIPE_APP_REPAIRS` move them, the same way `$RECIPE_APP_LIVE_DB`
    moves the database. Measured 2026-10-07: one plain `pytest` run replaced SIX files in the repo's
    `reports/` with fixture output, under the real names. `total-vs-waits.csv` is the one that made
    it visible: the file a person is told to read listed two recipes called `nocook` and `unclear`,
    which are fixture rows, where live's survey had put a real recipe id. Nothing committed was at
    risk, because the `--record` half refuses to overwrite a non-empty record. The damage is to the
    thing the folder is FOR, which is telling a person what a survey found.

    ⚠️ THE TEST THAT FOUND IT HAD A monkeypatch.setenv FOR `$RECIPE_APP_REPORTS` ALREADY, AND
    NOTHING READ IT. A redirect nobody reads is worse than no redirect, because it reads as a test
    that cannot touch the working tree while it rewrites a file in it on every run.
    """
    repairs = pathlib.Path(repairs or os.environ.get("RECIPE_APP_REPAIRS") or REPAIRS)
    reports = pathlib.Path(reports or os.environ.get("RECIPE_APP_REPORTS") or REPORTS)
    if not record:
        reports.mkdir(parents=True, exist_ok=True)
        return reports / filename
    target = repairs / filename
    if target.exists() and target.stat().st_size > 0:
        sys.exit(f"refusing to overwrite the existing record {target}\n"
                 f"  It is {target.stat().st_size} bytes. A record is replaced by deleting it on\n"
                 f"  purpose. Drop --record to write to {reports / filename} instead.")
    repairs.mkdir(parents=True, exist_ok=True)
    return target
