#!/usr/bin/env python3
"""import_runner.py — the full-archive IMPORT RUNNER (the only committing runner).

Turns the whole Paprika native export into database rows, all-or-nothing:

  backup first (or abort) -> ONE transaction over EVERY entry, in stable zip order:
    paprika_native_reader.iter_entries  (source -> raw; per-entry-safe; namelist order)
    -> import_cleanup.clean_recipe       (raw -> structured/flagged)
    -> import_write.plan_recipe          (pure: uid-dedup + slug mint + row mapping)
    -> import_write.commit_plan          (THE writer)
  -> COMMIT once, at the very end. ANY exception -> ROLLBACK the whole batch (a no-op).

It reuses import_write's plan_recipe/commit_plan/db_state and the reader's iter_entries
unchanged. Because iter_entries walks zf.namelist() in order and mint_slug is deterministic,
the same archive yields the same slugs on every run. It NEVER uses the dry-run's
author-sampling selector (select_distinct_authors / rng.shuffle).

Recovery: imports are source='app'; with foreign_keys ON (set here) a later
`DELETE FROM recipes WHERE source='app'` cascades their children away cleanly.

Run (this WRITES — the real import):  python3 import_runner.py --yes
"""
import argparse
import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import backup
import import_cleanup as cleanup
import import_write as iw
import paprika_native_reader as reader

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
ARCHIVE = BASE_DIR / "My Recipes.paprikarecipes"


@dataclass
class Summary:
    """Outcome of one run. Every archive entry the reader yields lands in exactly one of
    three buckets — written, skipped (uid-dedup), or reader_errors — so entries_seen is the
    total and nothing is ever silently dropped."""
    written: int = 0
    skipped: int = 0                                    # uid already present (dedup) only
    reader_errors: list = field(default_factory=list)   # [(entry_name, repr(err))]
    flags: int = 0                                       # import_flags rows recorded
    backup_path: Path = None

    @property
    def entries_seen(self):
        return self.written + self.skipped + len(self.reader_errors)


def run_import(db_path=DB, archive_path=ARCHIVE, *, backup_dir=None):
    """Import EVERY recipe in `archive_path` into `db_path`, all-or-nothing.

    Backs up first; if the backup can't be made it raises BEFORE opening any connection, so
    a failed backup writes NOTHING. Then runs reader -> cleanup -> plan_recipe -> commit_plan
    for every entry inside ONE transaction and commits once. Any exception rolls the whole
    transaction back and re-raises, leaving the DB exactly as before.

    Reader per-entry errors are collected (not raised) so one bad entry can't abort the
    batch's parsing; a genuine write error DOES abort + roll back. Returns a Summary.
    """
    kwargs = {} if backup_dir is None else {"backup_dir": backup_dir}
    dest = backup.create_backup(db_path, **kwargs)          # (1) backup or abort — pre-connection

    uid_index, taken = iw.db_state(db_path)                 # dedup + slug state from existing rows
    summary = Summary(backup_path=dest)

    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None                             # we drive BEGIN / COMMIT / ROLLBACK
    try:
        conn.execute("PRAGMA foreign_keys = ON")            # (3) enforce cascades (before BEGIN)
        conn.execute("BEGIN")                               # (4) one transaction for the batch
        with zipfile.ZipFile(str(archive_path)) as zf:
            for name, rec, err in reader.iter_entries(zf):  # (2) namelist order, per-entry safe
                if err is not None or rec is None:
                    summary.reader_errors.append((name, repr(err)))   # (5) collect, keep going
                    continue
                cleaned = cleanup.clean_recipe(reader.normalize(rec))
                plan = iw.plan_recipe(cleaned, uid_index, taken)
                if iw.commit_plan(conn, plan):              # module ref -> monkeypatchable
                    summary.written += 1
                    summary.flags += len(plan["review_flags"])
                    uid = plan["recipe"]["uid"]
                    if uid:                                 # thread dedup across the batch
                        uid_index[uid] = (plan["recipe"]["id"], plan["recipe"]["name"])
                else:
                    summary.skipped += 1                    # uid already present
        conn.execute("COMMIT")                              # (4) commit once, at the very end
    except Exception:
        if conn.in_transaction:                             # any error -> undo the ENTIRE batch
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return summary


def _print_summary(s):
    print("IMPORT COMPLETE (committed)")
    print(f"  backup      : {s.backup_path}")
    print(f"  written     : {s.written} recipe(s)  (source='app')")
    print(f"  skipped     : {s.skipped}  (uid already present)")
    if s.reader_errors:
        print(f"  reader errs : {len(s.reader_errors)}")
        for name, err in s.reader_errors:
            print(f"                - {name}: {err}")
    else:
        print("  reader errs : 0")
    print(f"  flags       : {s.flags} import_flags row(s) recorded")
    print(f"  entries seen: {s.entries_seen}  (= written + skipped + reader errs)")


def main():
    ap = argparse.ArgumentParser(
        description="Import the full Paprika archive into recipes.db (all-or-nothing).")
    ap.add_argument("--db", default=str(DB), help="database path (default: repo recipes.db)")
    ap.add_argument("--archive", default=str(ARCHIVE),
                    help="Paprika .paprikarecipes archive (default: repo archive)")
    ap.add_argument("--yes", action="store_true",
                    help="REQUIRED to write. Without it the runner refuses and does nothing.")
    args = ap.parse_args()

    if not args.yes:
        print("Refusing to import without --yes (this writes to the database). "
              "Nothing was read or written.")
        return 2

    try:
        s = run_import(Path(args.db), Path(args.archive))
    except Exception as e:                                   # noqa: BLE001 — report + nonzero exit
        print(f"IMPORT FAILED: {e!r}")
        print("  rolled back — database unchanged (0 recipes written).")
        return 1

    _print_summary(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
