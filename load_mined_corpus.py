#!/usr/bin/env python3
"""load_mined_corpus.py - put a source's N into mined_corpus.

⚠️ N IS THE ONE MINED NUMBER WITH NO LOADER UNTIL NOW, and that is why this file exists.
migration 042 backfills RecipeNLG's 2,231,142 by name, and Wikibooks' 3,774 was written by hand
from a scratch script. A third source made the gap real: a number typed at a prompt is not a
number anything can re-derive, and N is the denominator under every lift in the table.

⚠️ IT TAKES N FROM THE PAIRING ARTIFACT, NOT FROM AN ARGUMENT. pairing_run.py computed each
stored lift as n * N / (n_a * n_b) using `recipes_read` from its own run. That is the only N
consistent with the rows, so it is the N read here. Passing a different one by hand is how
mined_corpus and the pairing rows come apart, which is the failure
tests/test_mined_combine.py::test_the_stored_n_is_rederivable_from_the_pairing_rows exists to
catch after the fact. This catches it before the write.

⚠️ IT REFUSES WHEN THE OCCURRENCE RUN DISAGREES. Both runs read the same corpus with the same
reader, so `recipes_read` has to match. A mismatch means the two artifacts came from different
runs and their marginals do not belong to each other.

Idempotent per source_slug, which is the whole primary key.
"""
import argparse, json, sqlite3, time
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load(db, pairings, occurrences=None, dry=False):
    pj = json.load(open(pairings))
    slug, n = pj["source_slug"], pj["recipes_read"]
    if occurrences:
        oj = json.load(open(occurrences))
        if oj["source_slug"] != slug:
            raise SystemExit(f"REFUSED: the pairing artifact is {slug!r} and the occurrence "
                             f"artifact is {oj['source_slug']!r}. Two different sources.")
        if oj["recipes_read"] != n:
            raise SystemExit(f"REFUSED: the pairing run read {n:,} recipes and the occurrence "
                             f"run read {oj['recipes_read']:,}. The marginals in mined_occurrences "
                             f"do not belong to the pairs in mined_pairings.")

    conn = sqlite3.connect(db)
    # ⚠️ RE-DERIVED FROM THE ROWS ABOUT TO SIT UNDER IT, when they are already loaded. Every
    #    stored row satisfies lift = n * N / (n_a * n_b), so each implies N. The median is the
    #    corpus size and a wrong N is wrong by a factor, not by a rounding step.
    implied = sorted(lf * na * nb / k for k, na, nb, lf in conn.execute(
        "SELECT n,n_a,n_b,lift FROM mined_pairings WHERE source_slug=? "
        "AND lift>0 AND n_a>0 AND n_b>0", (slug,)))
    if implied:
        med = implied[len(implied) // 2]
        if abs(med - n) / n > 1e-4:
            raise SystemExit(f"REFUSED: the {len(implied):,} loaded pairing rows for {slug!r} "
                             f"imply N = {med:,.0f} and this artifact says {n:,}.")
        print(f"  {len(implied):,} loaded pairing rows imply N = {med:,.0f}, artifact says {n:,}")
    else:
        print(f"  no pairing rows loaded yet for {slug!r}, nothing to cross-check N against")

    print(f"  source_slug {slug!r}, N = {n:,}")
    if dry:
        print("  dry run, nothing written")
        conn.close()
        return
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM mined_corpus WHERE source_slug=?", (slug,))
        conn.execute("INSERT INTO mined_corpus (source_slug, n, mined_at) VALUES (?,?,?)",
                     (slug, n, int(time.time())))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    rows = conn.execute("SELECT source_slug, n FROM mined_corpus ORDER BY n DESC").fetchall()
    print(f"  committed. mined_corpus now holds {len(rows)} sources, combined N "
          f"{sum(r[1] for r in rows):,}")
    for s, v in rows:
        print(f"    {s:<20}{v:>12,}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pairings", nargs="?", default="previews/pairings.json",
                    help="the pairing_run.py artifact. Its recipes_read IS N.")
    ap.add_argument("--occurrences", default=None,
                    help="the occurrence_run.py artifact, cross-checked against the pairing one")
    ap.add_argument("--db", default=str(BASE / "recipes.db"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load(a.db, a.pairings, a.occurrences, a.dry_run)
