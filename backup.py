#!/usr/bin/env python3
"""backup.py — make a timestamped copy of recipes.db.

recipes.db is now your one irreplaceable file: your ratings and cook history live
ONLY there (unlike the recipe content, which can be regenerated from seed.py). This
makes a dated copy in a backups/ folder so a mistake or a disk problem isn't fatal.

Run it whenever (or before anything risky):  python3 backup.py
"""
import datetime
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
BACKUP_DIR = BASE_DIR / "backups"
KEEP = 30  # keep the most recent N backups; older ones are pruned


def create_backup(db=DB, backup_dir=BACKUP_DIR, keep=KEEP):
    """Copy `db` to a timestamped file in `backup_dir`, prune to the newest `keep`, and
    return the destination Path. Raises FileNotFoundError if `db` doesn't exist — the
    import runner treats that as an ABORT-before-writing signal (never import without a
    fresh backup). Does the side effect and returns; prints nothing (main() reports)."""
    db, backup_dir = Path(db), Path(backup_dir)
    if not db.exists():
        raise FileNotFoundError(f"No database to back up: {db}")
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"recipes-{stamp}.db"
    shutil.copy2(db, dest)
    # prune oldest backups beyond `keep`, so the folder doesn't grow forever.
    #
    # ⚠️ THE GLOB MATCHES A TIMESTAMP, NOT A WILDCARD, AND THAT IS THE WHOLE FIX. It used to read
    #    "recipes-*.db", which also caught the hand-named recipes-preview-*.db copies sitting in the
    #    same folder. Digits sort before letters, so a fresh recipes-<stamp>.db sorted to position 0
    #    and was the FIRST thing pruned once 30 preview files existed. This function deleted the
    #    backup it had just made, every single run, and the folder held 31 preview copies and not one
    #    of recipes.db. Found before migration 046, when the backup taken for it vanished.
    #
    #    A backup routine that silently destroys its own output is worse than none, because the
    #    caller is told a backup exists. create_backup returns dest and the import runner treats a
    #    missing database as abort-before-writing, so both callers believed it.
    for old in sorted(backup_dir.glob("recipes-[0-9]*.db"))[:-keep]:
        old.unlink()
    return dest


def main():
    try:
        dest = create_backup()
    except FileNotFoundError as e:
        print(f"{e}. Run build_db.py first.")
        sys.exit(1)
    print(f"Backed up to {dest}")


if __name__ == "__main__":
    main()
