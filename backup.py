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


def main():
    if not DB.exists():
        print(f"No database to back up yet ({DB}). Run build_db.py first.")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"recipes-{stamp}.db"
    shutil.copy2(DB, dest)
    print(f"Backed up to {dest}")

    # prune oldest backups beyond KEEP, so the folder doesn't grow forever
    backups = sorted(BACKUP_DIR.glob("recipes-*.db"))
    for old in backups[:-KEEP]:
        old.unlink()
        print(f"Pruned old backup {old.name}")


if __name__ == "__main__":
    main()
