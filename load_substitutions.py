#!/usr/bin/env python3
"""load_substitutions.py - replay hand_substitutions.csv into library_substitutions.

⚠️ THE HAND FILE IS THE ONLY WRITER, the same contract load_relations.py states for hand_links.csv.
library_substitutions is rebuilt from the file on every load, so a row that exists only in
recipes.db is gone the next time this runs. That is the point rather than a hazard: the durable
record is the file, which is in git, and the table is a projection of it.

⚠️ THE LAST LINE FOR A PAIR WINS. The file is append-only, so changing your mind about
butter -> margarine writes a second line rather than editing the first. The file then reads as a
record of what was decided and when. Confirming something and later rejecting it leaves both
lines and no database row.

⚠️ A REJECTION WRITES NOTHING HERE, and it is not supposed to. Its whole job is to sit in the file
so the next mining run does not re-propose it. mined_substitution_candidates is rebuilt whole
every run, so a rejection kept anywhere else would come straight back.

⚠️ AN UNRESOLVABLE ID STOPS THE LOAD. Phase C measured what a silently skipped row costs: a fold
with a wrong anchor did nothing, said nothing, and was caught only because a count came back one
higher than expected.
"""
import argparse, csv, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = str(BASE / "recipes.db")
HAND = str(BASE / "hand_substitutions.csv")
DECISIONS = ("confirmed", "rejected", "authored")
FIELDS = ("from", "from_name", "to", "to_name", "decision", "ratio", "n", "note", "decided")


def read(path=HAND):
    """Every line in the file, in order, as dicts. Comments and blanks are skipped."""
    out = []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("from,from_name,"):
            continue
        row = next(csv.reader([line]))
        if len(row) != len(FIELDS):
            raise SystemExit(f"⚠️  {path} line {i} has {len(row)} fields, expected {len(FIELDS)}. "
                             f"Fix the line rather than letting a shifted column load.")
        d = dict(zip(FIELDS, [c.strip() for c in row]))
        d["_line"] = i
        out.append(d)
    return out


def decided(path=HAND):
    """(from, to) -> the winning row. What the viewer reads to know a candidate's state."""
    out = {}
    for r in read(path):
        out[(r["from"], r["to"])] = r
    return out


def load(db=DB, hand=HAND, verbose=True):
    rows_in = read(hand)
    conn = sqlite3.connect(db)
    canon = {l: n for l, n in conn.execute("SELECT library_id, canonical FROM library_names")}
    for r in rows_in:
        if r["decision"] not in DECISIONS:
            raise SystemExit(f"⚠️  line {r['_line']}: decision {r['decision']!r} is not one of "
                             f"{', '.join(DECISIONS)}.")
        for side in ("from", "to"):
            if r[side] not in canon:
                raise SystemExit(f"⚠️  line {r['_line']}: {side} id {r[side]!r} does not resolve "
                                 f"in library_names. Fix the hand file rather than skipping it.")
        # ⚠️ AN AUTHORED ROW HAS NO EVIDENCE BEHIND IT BUT YOURS, so it has to say why. A confirmed
        #    row does not need one: the candidate's n and pattern are already the reason.
        if r["decision"] == "authored" and not r["note"]:
            raise SystemExit(f"⚠️  line {r['_line']}: an authored substitution carries no note. "
                             f"Nothing proposed it, so the line has to say why it is there.")
    winners = {}
    for r in rows_in:
        winners[(r["from"], r["to"])] = r
    facts = []
    for (f, t), r in winners.items():
        if r["decision"] == "rejected":
            continue
        origin = "mined-confirmed" if r["decision"] == "confirmed" else "authored"
        slug = "recipenlg-2020" if r["decision"] == "confirmed" else "hand"
        facts.append((f, t, origin, float(r["ratio"]) if r["ratio"] else None,
                      int(r["n"]) if r["n"] else None, slug))
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM library_substitutions")
        conn.executemany("INSERT INTO library_substitutions "
                         "(from_id,to_id,origin,ratio,n,source_slug) VALUES (?,?,?,?,?,?)", facts)
        n = conn.execute("SELECT COUNT(*) FROM library_substitutions").fetchone()[0]
        assert n == len(facts), f"wrote {n}, expected {len(facts)}"
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    finally:
        conn.close()
    n_rej = sum(1 for r in winners.values() if r["decision"] == "rejected")
    if verbose:
        print(f"loaded {len(facts)} substitutions from {Path(hand).name} "
              f"({len(rows_in)} lines, {len(winners)} pairs, {n_rej} standing rejections)")
    return len(facts), n_rej


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--hand", default=HAND)
    a = ap.parse_args()
    load(a.db, a.hand)
