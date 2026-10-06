#!/usr/bin/env python3.13
"""gen_note_corpus.py - capture the corpus's note rows into tests/fixtures/note-corpus.json.

⚠️ WHY A FIXTURE AT ALL. The two strongest tests of the note-title rule read every note in the 300
recipes: one checks the rule reproduces all 36 of Andy's recorded decisions, the other that it
writes a title or asks a question on exactly the rows he reviewed and on none of the other 143.
Both were marked live_catalog and therefore SKIPPED IN CI, and that marker exists for the real
10,020-entry library, not for 177 short strings. Captured once, they run everywhere.

    python3.13 scripts/gen_note_corpus.py <db> [--out tests/fixtures/note-corpus.json]

⚠️ READ-ONLY, THROUGH mode=ro, SO SQLITE ITSELF REFUSES A WRITE. It is on the read-only list in
tests/test_live_guards.py for the same reason the gates are: reading live IS the job, and a
generator that needed --i-mean-live typed out would not get run.
"""
import argparse
import json
import pathlib
import sqlite3

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "note-corpus.json"
WHY = ("Live's 177 recipe_notes rows as they stand BEFORE the titles round, captured once so the "
       "two strongest tests of the title rule can run in CI. They were marked live_catalog and "
       "skipped there, and that marker exists for the 10,020-entry library rather than for 177 "
       "short strings. tests/test_note_title_rule.py reads this and the two decision CSVs in "
       "docs/data-repairs/, so the comparison is against Andy's recorded decisions rather than "
       "against a copy of them. Regenerate with scripts/gen_note_corpus.py after a pass changes "
       "these rows.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{pathlib.Path(a.db)}?mode=ro", uri=True)
    rows = [{"id": r[0], "recipe": r[1], "kind": r[2], "text": r[3]} for r in con.execute(
        "SELECT id, recipe_id, kind, text FROM recipe_notes ORDER BY id")]
    if not rows:
        raise SystemExit(f"{a.db} holds no note rows, so there is nothing to capture")
    pathlib.Path(a.out).write_text(
        json.dumps({"_why": WHY, "notes": rows}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} notes -> {a.out}")


if __name__ == "__main__":
    main()
