#!/usr/bin/env python3
"""harvest_marks.py: pull your marks out of the spreadsheet into hand_removals.csv.

    python3.13 harvest_marks.py             read the sheet, merge into the CSV
    python3.13 harvest_marks.py --dry-run   show what it would write, change nothing

WHY THIS EXISTS. build_library.py regenerates the spreadsheet, so anything marked in
it is lost on the next build. The decision has to live in a committed file. This is the
round trip that makes marking in the sheet safe: mark as you read, run this, and the
reading survives every rebuild.

HOW TO MARK. In the "ingredients (kept)" sheet, two columns are yours:

    My call    drop             the whole entry is not an ingredient
               trim            every alias-only variation goes, the entry stays
               drop: <name>     that one named variation goes, the entry stays
               keep             an explicit keep. Recorded, changes nothing, and
                                useful for saying "I looked at this and it is fine".
    My note    ⚠️ REQUIRED for anything but keep. The reason, in your words.

The key is read from the row's "Anchored on" column, which prints as "Wikidata  Q23400".
You never type an identifier.

⚠️ MERGING, NOT OVERWRITING. Existing rows in hand_removals.csv are kept unless the sheet
marks the same entry differently, in which case the sheet wins and the change is printed.
A row you delete from the sheet's marks is NOT removed from the CSV, because a blank cell
is indistinguishable from "not looked at yet". Delete the CSV row by hand to reverse a
removal, which is the same shape as reversing anything else here.
"""
import csv
import os
import sys
import datetime

CSV_PATH = os.environ.get("HAND_REMOVALS", "hand_removals.csv")
SHEET = os.environ.get("LIBRARY_XLSX", "previews/ingredient-list-pass1.xlsx")
FIELDS = ["anchor", "id", "action", "variation", "reason", "marked"]
SOURCE_KEY = {"Wikidata": "wikidata", "OFF": "off_taxonomy", "AGROVOC": "agrovoc",
              "Wiktionary": "wiktextract", "Wikipedia": "wikipedia_redirect"}


def read_csv(path=CSV_PATH):
    """Existing removals, plus the comment header so a rewrite keeps it."""
    if not os.path.exists(path):
        return [], ""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    header = "".join(l for l in lines if l.startswith("#"))
    rows = list(csv.DictReader(l for l in lines if not l.startswith("#")))
    return rows, header


def write_csv(rows, header, path=CSV_PATH):
    """Sorted, so git shows which decision changed rather than a reshuffle."""
    rows = sorted(rows, key=lambda r: (r["anchor"], str(r["id"]), r["action"],
                                       r.get("variation") or ""))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(header)
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def parse_call(call):
    """'drop' -> ('drop', ''). 'trim' -> ('trim_alias_only', ''). 'drop: X' -> the name."""
    call = (call or "").strip()
    if not call:
        return None, ""
    low = call.casefold()
    if low.startswith("drop:"):
        return "drop_variation", call.split(":", 1)[1].strip()
    if low in ("drop", "remove", "not an ingredient"):
        return "drop", ""
    if low in ("trim", "trim_alias_only", "trim aliases"):
        return "trim_alias_only", ""
    if low in ("keep", "ok", "fine"):
        return "keep", ""
    return None, call                       # unrecognised, reported not guessed


def harvest(sheet=SHEET, path=CSV_PATH, dry_run=False):
    import openpyxl
    if not os.path.exists(sheet):
        raise SystemExit(f"{sheet} not found. Run build_library.py first.")
    book = openpyxl.load_workbook(sheet, read_only=True)

    heads = None
    marks, unrecognised, missing_reason = [], [], []
    for ws in book:
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            if i == 2:
                heads = {str(v): j for j, v in enumerate(row) if v}
                continue
            if i < 3 or heads is None:
                continue
            def cell(name):
                j = heads.get(name)
                return row[j] if j is not None and j < len(row) else None
            call, note, anchored = cell("My call"), cell("My note"), cell("Anchored on")
            if not (call and str(call).strip()):
                continue
            action, extra = parse_call(str(call))
            if action is None:
                unrecognised.append((cell("Ingredient"), call))
                continue
            if action != "keep" and not (note and str(note).strip()):
                missing_reason.append((cell("Ingredient"), call))
                continue
            parts = str(anchored or "").split()
            if len(parts) < 2 or parts[0] not in SOURCE_KEY:
                unrecognised.append((cell("Ingredient"), f"unreadable key {anchored!r}"))
                continue
            marks.append({"anchor": SOURCE_KEY[parts[0]], "id": " ".join(parts[1:]),
                          "action": action, "variation": extra,
                          "reason": str(note or "").strip(),
                          "marked": datetime.date.today().isoformat(),
                          "_name": cell("Ingredient")})

    existing, header = read_csv(path)
    index = {(r["anchor"], str(r["id"]), r["action"], r.get("variation") or ""): r
             for r in existing}
    added, changed = [], []
    for m in marks:
        if m["action"] == "keep":
            continue                        # recorded in the sheet, nothing to remove
        key = (m["anchor"], m["id"], m["action"], m["variation"])
        row = {k: m[k] for k in FIELDS}
        if key not in index:
            index[key] = row
            added.append(m)
        elif index[key].get("reason") != row["reason"]:
            index[key] = row
            changed.append(m)

    print(f"read {sheet}")
    print(f"  marks found in the sheet : {len(marks)}")
    print(f"  new removals             : {len(added)}")
    print(f"  reasons updated          : {len(changed)}")
    keeps = sum(1 for m in marks if m["action"] == "keep")
    print(f"  explicit keeps, no action: {keeps}")
    print(f"  already recorded         : {len(marks) - keeps - len(added) - len(changed)}")
    for name, call in unrecognised:
        print(f"  ⚠️  UNRECOGNISED CALL, skipped: {name!r} -> {call!r}")
    if missing_reason:
        print(f"  ⚠️  {len(missing_reason)} mark(s) SKIPPED for having no note. A removal "
              "without a reason is not recorded, the same rule as an override:")
        for name, call in missing_reason[:10]:
            print(f"        {name!r} marked {call!r}")
    for m in added[:20]:
        print(f"  + {m['action']:16s} {m['_name']}  ({m['anchor']} {m['id']})")

    if dry_run:
        print("\n--dry-run, nothing written")
        return
    write_csv(list(index.values()), header, path)
    print(f"\nwrote {path}: {len(index)} removals total")


if __name__ == "__main__":
    harvest(dry_run="--dry-run" in sys.argv)
