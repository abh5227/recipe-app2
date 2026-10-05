#!/usr/bin/env python3
"""The per-round go-live gate: the before and after readings against the round's OWN declaration.

    python3.13 scripts/gates/rounds.py --round golive/rounds/<date>-<name>.json \
                                       --before before.json --after after.json \
                                       [--a-db before.db --b-db after.db]

Exit status is 0 only when every move the round declared happened and nothing else did.

⚠️ A ROUND DECLARES WHAT IT MOVES, AND "NOTHING MOVES" IS A DECLARATION. The gate this replaces
carried an INTENDED block inside the script, hardcoded to one round's expected moves. Two rounds
later it was still asserting that migrations should go 59 to 61 and steps 2466 to 2486, against a
database that already had them, so it printed ten failures that were all stale and none real. A
reader learns in one round to ignore a gate like that. The declaration moves OUT of the script and
into a file the round commits, so the gate has nothing of its own to go out of date.

⚠️ AND EVERY KEY IS REQUIRED, SO SILENCE IS NEVER CONSENT. A round that leaves `short_circuit` out
is refused rather than defaulted to "unchanged". The whole failure mode here is a check that passes
because it was not asked the question: the stale block above, and a reading with nothing in it. An
omission is the most likely way a real move goes undeclared, so an omission fails.

⚠️ A MISSING ROUND FILE FAILS. A go-live with no declaration is not a go-live with an empty one.

The file's shape, with every key required:

    {
      "round":          "2026-10-05-remove-demo-accounts",
      "why":            "one sentence, for whoever reads this in a year",
      "short_circuit":  "unchanged" | {"joined": [...], "left": [...]},
      "annotations":    "unchanged" | {"<recipe>": "changed", ...},
      "counts":         {"users": [4, 1]},        # every count NOT named here must not move
      "tables":         "identical" | {"except": ["users", ...]}
    }

`counts` names only what moves. A count that moves and is not named is a failure, which is the
point: the round has to know what it is doing. `tables` is checked only when both databases are
given, because it needs them rather than the readings.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import compare as gcompare        # noqa: E402
import tablediff as gtablediff    # noqa: E402

REQUIRED = ("round", "why", "short_circuit", "annotations", "counts", "tables")


class BadRound(Exception):
    """The declaration itself is wrong, which is not the same as the gate failing."""


def load_round(path):
    """The round's declaration. A missing or incomplete file raises rather than defaulting."""
    p = pathlib.Path(path)
    if not p.exists():
        raise BadRound(f"no round file at {p}\n"
                       f"  A go-live declares what it moves. There is no default, because the one "
                       f"thing a gate must never do is pass for lack of a question.")
    try:
        spec = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise BadRound(f"{p} is not valid JSON: {e}") from None
    if not isinstance(spec, dict):
        raise BadRound(f"{p} must hold an object, not a {type(spec).__name__}")
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise BadRound(
            f"{p} leaves out {', '.join(missing)}\n"
            f"  Every key is required, so silence is never consent. If this round moves none of "
            f'them, say so: "short_circuit": "unchanged", "tables": "identical", "counts": {{}}.')
    if spec["short_circuit"] != "unchanged" and not isinstance(spec["short_circuit"], dict):
        raise BadRound('"short_circuit" must be "unchanged" or {"joined": [...], "left": [...]}')
    if spec["annotations"] != "unchanged" and not isinstance(spec["annotations"], dict):
        raise BadRound('"annotations" must be "unchanged" or an object keyed by recipe id')
    if not isinstance(spec["counts"], dict):
        raise BadRound('"counts" must be an object of {name: [from, to]}')
    for name, move in spec["counts"].items():
        if not (isinstance(move, list) and len(move) == 2):
            raise BadRound(f'"counts"[{name!r}] must be [from, to], not {move!r}')
    if spec["tables"] != "identical" and not (isinstance(spec["tables"], dict)
                                              and isinstance(spec["tables"].get("except"), list)):
        raise BadRound('"tables" must be "identical" or {"except": ["table", ...]}')
    return spec


def check(before, after, spec):
    """Every way this run disagrees with what the round declared, as a list of lines."""
    out = []
    # The empty-reading refusals come first, and they are compare.py's, not a second copy.
    out += gcompare.nothing_to_compare(before, "before")
    out += gcompare.nothing_to_compare(after, "after")

    sb = set(before.get("short_circuit") or ())
    sa = set(after.get("short_circuit") or ())
    joined, left = sorted(sa - sb), sorted(sb - sa)
    if spec["short_circuit"] == "unchanged":
        if joined or left:
            out.append(f"the round declared the short-circuit set unchanged, and "
                       f"{len(left)} left, {len(joined)} joined")
            if left:
                out.append(f"  left  : {left}")
            if joined:
                out.append(f"  joined: {joined}")
    else:
        want_j = sorted(spec["short_circuit"].get("joined", []))
        want_l = sorted(spec["short_circuit"].get("left", []))
        if joined != want_j:
            out.append(f"short-circuit joined: declared {want_j}, got {joined}")
        if left != want_l:
            out.append(f"short-circuit left: declared {want_l}, got {left}")

    ab = before.get("annotations") or {}
    aa = after.get("annotations") or {}
    moved = sorted(r for r in set(ab) | set(aa)
                   if [tuple(x) for x in ab.get(r, ())] != [tuple(x) for x in aa.get(r, ())])
    if spec["annotations"] == "unchanged":
        if moved:
            out.append(f"the round declared the annotations unchanged, and these moved: {moved}")
    else:
        declared = sorted(spec["annotations"])
        if moved != declared:
            out.append(f"annotations: declared changes on {declared}, got {moved}")

    cb, ca = before.get("counts") or {}, after.get("counts") or {}
    declared_counts = spec["counts"]
    for name in sorted(set(cb) | set(ca)):
        got = [cb.get(name), ca.get(name)]
        if name in declared_counts:
            want = list(declared_counts[name])
            if got != want:
                out.append(f"count {name}: declared {want[0]} -> {want[1]}, got {got[0]} -> {got[1]}")
        elif got[0] != got[1]:
            out.append(f"count {name} moved {got[0]} -> {got[1]} and the round did not declare it")
    for name in sorted(set(declared_counts) - (set(cb) | set(ca))):
        out.append(f"count {name} is declared and the readings do not carry it")

    out += gcompare.integrity_problems(before, after)
    return out


def check_tables(a_db, b_db, spec, report=lambda *a: None):
    """The row-for-row half, which needs the two databases rather than the two readings."""
    differ = set(gtablediff.differences(a_db, b_db, report=report))
    allowed = set() if spec["tables"] == "identical" else set(spec["tables"]["except"])
    out = []
    for t in sorted(differ - allowed):
        out.append(f"table {t} differs and the round did not declare it")
    for t in sorted(allowed - differ):
        out.append(f"table {t} is declared as changing and is identical")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="gate a go-live against the round's own declaration")
    ap.add_argument("--round", required=True, help="the round's expected-changes file")
    ap.add_argument("--before", required=True, help="the before reading from gates/state.py")
    ap.add_argument("--after", required=True, help="the after reading from gates/state.py")
    ap.add_argument("--a-db", help="the before database, for the row-for-row check")
    ap.add_argument("--b-db", help="the after database, for the row-for-row check")
    a = ap.parse_args(argv)
    try:
        spec = load_round(a.round)
    except BadRound as e:
        print(f"\nTHE ROUND FILE IS NOT USABLE:\n  {e}\n")
        return 2
    before, after = gcompare.load(a.before), gcompare.load(a.after)
    print(f"round : {spec['round']}")
    print(f"why   : {spec['why']}")
    print(f"declared: short_circuit={spec['short_circuit']!r} annotations={spec['annotations']!r} "
          f"counts={spec['counts']} tables={spec['tables']!r}")
    fails = check(before, after, spec)
    # ⚠️ THE TABLE HALF IS NEVER OPTIONAL, AND IT USED TO BE SKIPPED SILENTLY ON THE STRONGEST
    #    CLAIM. This ran check_tables only when both databases were given, and complained about
    #    their absence only when the round declared an exception. So `"tables": "identical"`, which
    #    is the claim that NO table differs, was the one declaration that went unverified, and the
    #    run still printed that the round did exactly what it declared. Measured: two databases
    #    agreeing on every reading key and differing in one users row passed, exit 0. `tables` is a
    #    required key, so the databases that answer it are required too.
    if a.a_db and a.b_db:
        fails += check_tables(a.a_db, a.b_db, spec)
    else:
        fails.append(f'the round declares tables {spec["tables"]!r} and no databases were given to '
                     f'check that, so the table half would go unverified (pass --a-db and --b-db)')
    if not fails:
        print("\nTHE ROUND DID EXACTLY WHAT IT DECLARED")
        return 0
    print("\nNOT WHAT THE ROUND DECLARED:")
    for line in fails:
        print(f"  {line}")
    print("\nGATE FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
