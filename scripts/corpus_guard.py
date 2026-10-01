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
import os
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent


def _identity(path):
    """(device, inode) for `path`, or None when it does not exist.

    ⚠️ THE FILE, NOT THE SPELLING OF ITS NAME. A path string says nothing about which file it opens.
    `./recipes.db`, `scripts/../recipes.db`, a symlink in /tmp and a HARD LINK anywhere all open the
    live database, and a guard that compared strings would have let three of those four through.
    Resolving the path handles the first three; only the inode handles a hard link, because a hard
    link IS the file under a second name and resolving it gives that second name back."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def is_live(db, base=None):
    """True when `db` names the live database, whatever it is spelled as.

    Live is `recipes.db` in the repo root and nothing else. A copy under any other name or in any
    other directory passes straight through, which is what every rehearsal relies on.

    TWO TESTS, AND THE UNION OF THEM, because each answers a case the other cannot:
      * file identity  catches every alias of an EXISTING file, including a hard link.
      * resolved path  catches live BEFORE IT EXISTS, which is the fresh-clone case, where there is
                       no inode to compare and `migrate.py --db recipes.db` would create it.
    """
    root = pathlib.Path(base or BASE).resolve()
    live = root / "recipes.db"
    if pathlib.Path(db).resolve() == live:
        return True
    here = _identity(db)
    return here is not None and here == _identity(live)


def refuse_live(db, i_mean_live, base=None):
    """Exit unless the caller said `--i-mean-live`, when `db` is the live database."""
    if is_live(db, base) and not i_mean_live:
        sys.exit("refusing to write live recipes.db without --i-mean-live")


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
    """
    repairs = pathlib.Path(repairs or REPAIRS)
    reports = pathlib.Path(reports or REPORTS)
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
