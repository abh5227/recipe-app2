#!/usr/bin/env python3
"""Compare two gates/state.py readings as SETS, and FAIL when there is nothing to compare.

    python3.13 scripts/gates/compare.py <before.json> <after.json>

Exit status is 0 when the two readings are identical in every way this checks, and 1 otherwise.

⚠️ IT COMPARES THE ENTRIES, NOT THEIR COUNT. "short-circuit 275 of 300" was once quoted as a gate
figure for a whole round, and it is not a property of the corpus. It is a property of which recipes
have been saved. One recipe leaving the byte-equal set while another joins holds the number still,
and one annotation entry replacing another holds 49 at 49. Both are compared entry by entry, against
the BEFORE-STATE OF THE SAME RUN rather than a number somebody wrote down.

⚠️ AND AN EMPTY READING FAILS. A gate that passes because it found nothing is the failure mode worth
guarding: a reading taken against the wrong path, or against a database whose tables are not there
yet, agrees with anything. Two empty readings are byte-identical and mean nothing, so a reading with
no recipes, no byte-equal set or no annotation entries is refused before any comparison is reported.

⚠️ IT OPENS NO DATABASE. It reads two JSON files. That is what makes it safe to run anywhere, and it
is why the reading and the comparison are two scripts rather than one.
"""
import json
import pathlib
import sys

# What a reading must contain before it is worth comparing, with the reason stated per key.
_NOT_EMPTY = (
    ("short_circuit", "the short-circuit set is EMPTY, so there is nothing to compare"),
    ("annotations", "there are NO annotation entries, so there is nothing to compare"),
)


def load(path):
    return json.loads(pathlib.Path(path).read_text())


def nothing_to_compare(reading, side):
    """The refusals that come BEFORE any comparison. A gate with an empty side is not a pass."""
    out = []
    for key, why in _NOT_EMPTY:
        if not reading.get(key):
            out.append(f"{side}: {why}")
    if not (reading.get("counts") or {}).get("recipes"):
        out.append(f"{side}: 0 recipes, so this reading describes nothing")
    return out


def integrity_problems(before, after):
    """Whether the database is still sound, and still as sound as it was.

    ⚠️ ONE RULE, ONE FUNCTION, BECAUSE IT WAS TWO. gates/rounds.py carried a byte-identical copy of
    this block, four lines under a comment saying the refusals above were "compare.py's, not a
    second copy". A comment claiming a rule is shared is not a shared rule, which is the project's
    oldest standing lesson and the one this round repeated."""
    out = []
    for key in ("integrity_check", "foreign_key_violations"):
        if before.get(key) != after.get(key):
            out.append(f"{key}: {before.get(key)} -> {after.get(key)}")
    if after.get("integrity_check") not in (None, "ok"):
        out.append(f"integrity_check is not ok: {after.get('integrity_check')}")
    if after.get("foreign_key_violations"):
        out.append(f"{after['foreign_key_violations']} foreign-key violations after")
    return out


def differences(before, after):
    """Every way the two readings disagree, as a list of lines. Empty means identical."""
    out = nothing_to_compare(before, "before") + nothing_to_compare(after, "after")

    sb, sa = set(before.get("short_circuit") or ()), set(after.get("short_circuit") or ())
    if sb != sa:
        left, joined = sorted(sb - sa), sorted(sa - sb)
        out.append(f"the short-circuit set moved: {len(left)} left, {len(joined)} joined")
        if left:
            out.append(f"  left the byte-equal set  : {left}")
        if joined:
            out.append(f"  joined the byte-equal set: {joined}")

    ab, aa = before.get("annotations") or {}, after.get("annotations") or {}
    for rid in sorted(set(ab) | set(aa)):
        eb = [tuple(x) for x in ab.get(rid, ())]
        ea = [tuple(x) for x in aa.get(rid, ())]
        if eb != ea:
            out.append(f"the annotation entries changed on {rid}")
            for gone in sorted(set(eb) - set(ea)):
                out.append(f"  gone : {list(gone)}")
            for new in sorted(set(ea) - set(eb)):
                out.append(f"  new  : {list(new)}")

    out += integrity_problems(before, after)

    cb, ca = before.get("counts") or {}, after.get("counts") or {}
    for key in sorted(set(cb) | set(ca)):
        if cb.get(key) != ca.get(key):
            out.append(f"count {key}: {cb.get(key)} -> {ca.get(key)}")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    before, after = load(argv[0]), load(argv[1])
    sb, sa = before.get("short_circuit") or [], after.get("short_circuit") or []
    print(f"short-circuit : {len(sb)} -> {len(sa)}   identical set: {set(sb) == set(sa)}")
    print(f"annotations   : {before.get('annotation_entries')} over "
          f"{before.get('annotation_recipes')} recipes -> {after.get('annotation_entries')} over "
          f"{after.get('annotation_recipes')}   identical: "
          f"{(before.get('annotations') or {}) == (after.get('annotations') or {})}")
    print(f"integrity     : {before.get('integrity_check')} -> {after.get('integrity_check')}")
    print(f"fk violations : {before.get('foreign_key_violations')} -> "
          f"{after.get('foreign_key_violations')}")
    diffs = differences(before, after)
    if not diffs:
        print("\nIDENTICAL")
        return 0
    print("\nDIFFERENCES:")
    for line in diffs:
        print(f"  {line}")
    print("\nGATE FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
