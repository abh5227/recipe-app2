"""The refusal every archived script shares.

⚠️ ARCHIVED, NOT DELETED, AND NOT RUNNABLE. A spent one-time backfill is the most dangerous file in
the repository: it names live recipes.db with no --db to point it elsewhere, it writes on a flag
somebody could type from muscle memory, and its work is already done, so running it again is pure
risk with no upside. Three of them are irreversible on SQLite (backfill_rescoping DROPs and rebuilds
the ratings table).

Deleting them would lose the record of what was done to the data and why, which is the one thing
these files are still good for. So they move here, they keep their docstrings and their tests, and
running one prints what it did and exits 2.

⚠️ THE REFUSAL IS AT RUN TIME, NOT IMPORT TIME, and that is deliberate. Eight of these carry a test
file that imports the module to pin the transform it applied. An exit on import would delete that
record as surely as deleting the file. `python3.13 scripts/applied/<name>.py` is what refuses.
"""
import pathlib
import sys


def refuse_spent(script_file, what_it_did, when=""):
    """Print what this script already did and exit 2. Called from `if __name__ == "__main__"`."""
    name = pathlib.Path(script_file).name
    sys.stderr.write(
        f"{name} is a spent one-time backfill and will not run.\n"
        f"  what it did: {what_it_did}\n"
        + (f"  applied: {when}\n" if when else "")
        + f"  it is archived in scripts/applied/ for the record, with its tests.\n"
        f"  If the work genuinely needs doing again, copy it out, give it a --db argument and the\n"
        f"  shared live guard (scripts/corpus_guard.py), and rehearse it on a copy first.\n")
    raise SystemExit(2)
