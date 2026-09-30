#!/usr/bin/env python3
"""apply_repoints.py - replay hand_repoints.csv onto recipe_ingredients.

⚠️ THIS RUNS AFTER THE MATCHER, never before. Every row in the hand file overrides what the
matcher would otherwise decide: plain flour matches the generic flour row on its own, and the
repoint sends it to all-purpose flour instead. Applied first, the matcher would overwrite it.

⚠️ KEYED ON (recipe_id, row_id). It was (recipe_id, position), because the id "is a rowid build_db
regenerates" — true while the 5 seed recipes existed and build_db rebuilt their rows, and false since
migration 016 flipped them to source='app' and emptied seed.py's RECIPES. Measured before the file was
converted: build_db.build() over a copy of live returned all 3,572 ingredient rows byte-identical.
A position is a slot, so inserting one line above a corrected line moved every correction below it.

⚠️ A LINE THAT NO LONGER READS THE SAME STOPS THE RUN. The hand file carries the line as it was
when the decision was made. If the text on that row has changed the decision may no longer
apply, and repointing it silently would move a link onto an unrelated ingredient. Phase C showed
what a silent no-op costs, so this fails loudly instead.

Idempotent. Re-running writes the same three columns to the same rows and changes nothing else.
"""
import csv, sqlite3, sys

DB = "recipes.db"
HAND = "hand_repoints.csv"


def _rows(path):
    out = []
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("action,"):
            continue
        out.append(next(csv.reader([line])))
    return out


def apply(db=DB, hand=HAND, verbose=True):
    conn = sqlite3.connect(db)
    rows = _rows(hand)
    applied = unchanged = suppressed = relabelled = 0
    try:
        conn.execute("BEGIN")
        for action, recipe_id, row_id, catalog_id, conf, rule, matched, check in rows:
            # recipe_id is in the WHERE beside the id on purpose: an id names one row in the whole
            # table, so a file naming the right id under the wrong recipe would otherwise apply.
            cur = conn.execute(
                "SELECT COALESCE(label, raw_text), catalog_id, link_confidence, link_rule "
                "FROM recipe_ingredients WHERE recipe_id=? AND id=?",
                (recipe_id, int(row_id))).fetchone()
            if cur is None:
                raise SystemExit(f"⚠️  no line in {recipe_id!r} with row id {row_id}. The hand file "
                                 "names a row that is not in the corpus. Fix the file rather than "
                                 "skipping it.")
            # ⚠️ line_check IS STILL CHECKED, and the id does not make it redundant. The id says which
            # row; this says the decision was made about THIS TEXT. A rewritten line is a different
            # line, and its repoint may no longer name the right target.
            if check and (cur[0] or "")[:120] != check:
                raise SystemExit(f"⚠️  the line in {recipe_id!r} with row id {row_id} now reads "
                                 f"{(cur[0] or '')[:60]!r}, not {check[:60]!r}. The decision was "
                                 "made about different text, so it is not replayed.")
            if action == "relabel":
                # the matcher reached the right row. Only the rule string, written by a hand
                # pass, is restored.
                if cur[3] == rule:
                    unchanged += 1
                else:
                    conn.execute("UPDATE recipe_ingredients SET link_rule=? WHERE recipe_id=? "
                                 "AND id=?", (rule, recipe_id, int(row_id)))
                    relabelled += 1
                continue
            if action == "suppress":
                # ⚠️ a decision NOT to link. The matcher would bind this line and the row it
                #    reaches carries another ingredient's prose, so the match is withheld.
                if cur[1] is None:
                    unchanged += 1
                else:
                    conn.execute("UPDATE recipe_ingredients SET catalog_id=NULL, "
                                 "link_confidence=NULL, link_rule=NULL, link_matched=NULL "
                                 "WHERE recipe_id=? AND id=?", (recipe_id, int(row_id)))
                    suppressed += 1
                continue
            if (cur[1], cur[2], cur[3]) == (catalog_id, conf, rule):
                unchanged += 1
                continue
            conn.execute(
                "UPDATE recipe_ingredients SET catalog_id=?, link_confidence=?, link_rule=?, "
                "link_matched=? WHERE recipe_id=? AND id=?",
                (catalog_id, conf, rule, matched or None, recipe_id, int(row_id)))
            applied += 1
        want = sum(1 for r in rows if r[0] == "repoint")
        n = conn.execute("SELECT COUNT(*) FROM recipe_ingredients "
                         "WHERE link_confidence='repoint'").fetchone()[0]
        assert n == want, f"{n} repointed rows in the database, expected {want}"
        conn.execute("COMMIT")
        if verbose:
            print(f"repointed {applied}, suppressed {suppressed}, relabelled {relabelled}, "
                  f"already correct {unchanged}, {len(rows)} decisions in {hand}")
        return applied, unchanged, suppressed
    except Exception:
        conn.execute("ROLLBACK"); raise
    finally:
        conn.close()


if __name__ == "__main__":
    apply(db=sys.argv[1] if len(sys.argv) > 1 else DB,
          hand=sys.argv[2] if len(sys.argv) > 2 else HAND)
