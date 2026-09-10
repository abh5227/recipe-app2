#!/usr/bin/env python3
"""build_links.py - rebuild every recipe-to-catalog link from committed files.

Two stages, and the order is the whole point.

  1. the matcher writes what a rule can derive. 2,746 of the 2,778 links.
  2. hand_repoints.csv replays the 35 decisions a rule cannot reach.

⚠️ THE HAND FILE GOES SECOND. Every row in it overrides what the matcher just wrote. Plain flour
reaches the generic flour row on its own and a cook means all-purpose flour, so applying the hand
file first would let the matcher overwrite the decision.

⚠️ ONLY THREE TIERS BECOME LINKS. EXACT, DECIDED and FORM_STRIP. AMBIGUOUS refused to choose and
UNMATCHED found nothing, so neither is written, and the /uncovered view exists to show them.

⚠️ A SUPPRESSION IS A DECISION, NOT AN ABSENCE. Three FORM_STRIP matches are withheld on purpose,
because white miso is not the generic miso row. Written as links they would make 2,781 where the
library holds 2,778, which is how a rebuild quietly gains rows nobody authored.

Idempotent. Running it twice leaves the same 2,778 links.
"""
import sqlite3, sys

DB = "recipes.db"
WRITE_TIERS = ("EXACT", "DECIDED", "FORM_STRIP")
TIER_CONF = {"EXACT": "exact", "DECIDED": "decided", "FORM_STRIP": "form_strip"}


def build(db=DB, hand="hand_repoints.csv", verbose=True):
    import linkage_matcher, apply_repoints
    rows, _ = linkage_matcher.propose(db=db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE recipe_ingredients SET catalog_id=NULL, link_confidence=NULL, "
                     "link_rule=NULL, link_matched=NULL")
        n = 0
        for r in rows:
            if r.get("tier") not in WRITE_TIERS or not r.get("catalog_id"):
                continue
            conn.execute("UPDATE recipe_ingredients SET catalog_id=?, link_confidence=?, "
                         "link_rule=?, link_matched=? WHERE id=?",
                         (r["catalog_id"], TIER_CONF[r["tier"]], r["rule"], r.get("matched"), r["id"]))
            n += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    finally:
        conn.close()
    if verbose:
        print(f"matcher wrote {n} links")
    ap, un, sup = apply_repoints.apply(db=db, hand=hand, verbose=verbose)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    total = conn.execute("SELECT COUNT(*) FROM recipe_ingredients "
                         "WHERE catalog_id IS NOT NULL").fetchone()[0]
    conn.close()
    if verbose:
        print(f"{total} links total")
    return total


if __name__ == "__main__":
    build(db=sys.argv[1] if len(sys.argv) > 1 else DB)
