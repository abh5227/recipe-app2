#!/usr/bin/env python3.13
"""apply_round_b.py - round B, the one plan, from the committed decisions.

Reads docs/data-repairs/round-b-decisions-2026-10-08.csv, because a pass that cannot be re-run from
a fresh clone is a hand edit with more steps.

WHAT IT WRITES, in one pass:

  the RULES   import_cleanup.amount_plan over every ingredient row: the author's second amount into
              secondary_measure, a unit or a measure or a number word out of the front of the name,
              a compound amount joined, a broken amount repaired where one reading is proved.
  the JOINS   import_cleanup.joins_the_row_above: four rows that are the rest of the row above them
              and two that are only the measure of it.
  the CALLS   the five single-row decisions Andy made, each named below.

⚠️ ONE READ OF EVERY ROW, AND THE COMPOSITION HAPPENS IN MEMORY. A joined row's final text is built
   from the two STORED rows and amount_plan is then asked about that constructed row, so no rule
   reads text another rule has written to the database. Polish round 2's worst defect was part 6
   reading text part 4 had already changed.

⚠️ HAND EDITS ARE PROTECTED BY ROW, NOT BY RECIPE. A row carrying an annotation entry is never
   changed and is listed. Other rows in the same recipe change in lockstep, which is the whole
   reason the protection can be this fine-grained: the row and its baseline entry move together, so
   the cook's own edits to OTHER rows of that recipe are untouched and still show.

⚠️ LOCKSTEP, PER RECIPE, IN ONE TRANSACTION, AND THE GATE RUNS BEFORE THE COMMIT. A pass that
   rewrites a row without rewriting the reason='original' baseline is indistinguishable from the
   cook having hand-edited it. The baseline is patched SURGICALLY, never rebuilt: rebuilding
   declares the recipe born in whatever state it is in, which erases the annotations the layer
   exists to show.

⚠️ A SECOND RUN IS A NO-OP. Every part detects its own applied state in the PLANNING phase, which is
   what makes the dry run a faithful preview of the real run. amount_plan returns no changes for a
   row already in its final state, a join finds no continuation once it is absorbed, and each single
   -row call checks for its own result first.
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "gates"))      # for gates/state.py's entry_key, the gate's own key
sys.path.insert(0, str(HERE.parent))
from corpus_guard import refuse_live, report_target                           # noqa: E402

DECISIONS = (HERE.parent / "docs" / "data-repairs"
             / "round-b-decisions-2026-10-08.csv")
RESIDUAL = "round-b-residual-2026-10-08.csv"

# ---- revision 1: Andy's click-through, and the residual rows he settled ---------------------- #
DECISIONS_2 = (HERE.parent / "docs" / "data-repairs"
               / "round-b-decisions-2-2026-10-08.csv")
RESIDUAL_DECISIONS = (HERE.parent / "docs" / "data-repairs"
                      / "round-b-residual-decisions-2026-10-08.csv")
# ---- revision 2: Andy's click-through of revision 1, and the 36 residual rows it left --------- #
DECISIONS_3 = (HERE.parent / "docs" / "data-repairs"
               / "round-b-decisions-3-2026-10-08.csv")
RESIDUAL_DECISIONS_2 = (HERE.parent / "docs" / "data-repairs"
                        / "round-b-residual-decisions-2-2026-10-08.csv")
# ---- revision 3a: the same 36 rows, with kachumber-tilapia 4145 answered again ---------------- #
RESIDUAL_DECISIONS_3 = (HERE.parent / "docs" / "data-repairs"
                        / "round-b-residual-decisions-3-2026-10-09.csv")

# ⚠️ ONE ROW OF THE RESIDUAL FILE IS DELIBERATELY NOT APPLIED. tahini-brioche 7462's "1 ¾ cups" is
#    a lower-confidence pre-fill: King Arthur's Tahini Brioche matches the recipe's order and its
#    butter, and nothing proves it IS the source. Andy's instruction is that the row stays flagged
#    until he confirms where the recipe came from, so the decision file carries the fix and this
#    pass does not run it. It is in the residual list again, with its reason.
RESIDUAL_HELD = {7462: "the fix needs Andy to confirm the recipe's source, so the row stays as it is"}

# The six residual rows the pass DOES apply, each spelled out from the DECISION column of
# round-b-residual-decisions-2026-10-08.csv. The file is READ, and these are what reading it means
# for each row: a DECISION column holds a sentence, and a sentence is not a column list.
RESIDUAL_FIXES = {
    # "fix: 352 grams | second amount 2 ¾ cups" — the second amount is already right.
    2834: {"what": "row", "changes": {"qty": "352 grams", "quantity": "352", "unit": "grams",
                                      "grams": 352.0},
           "why": "Andy's residual decision: the digit lost from '35 grams' is 352, which is 2 ¾ "
                  "cups at the corpus's own spooned-and-leveled 128 grams a cup"},
    # "fix: 3 ¼ cups | second amount 416 grams"
    4320: {"what": "row", "changes": {"qty": "3 ¼ cups", "quantity": "3 ¼", "unit": "cups",
                                      "secondary_measure": "416 grams"},
           "why": "Andy's residual decision: '3/4 cups' is a broken '3 ¼ cups', and 416 grams is "
                  "exactly that at 128 grams a cup"},
    # "fix: join with the row BELOW -> amount 1¼ cups + 2 tablespoons | name buttermilk, shaken well"
    3135: {"what": "join_below", "absorb": 3136,
           "changes": {"qty": "1¼ cups + 2 tablespoons", "quantity": "1¼ cups + 2 tablespoons",
                       "unit": "", "label": "buttermilk, shaken well",
                       "raw_text": "1¼ cups plus 2 tablespoons buttermilk, shaken well"},
           # ⚠️ THE LIBRARY LINK LIVES ON THE ROW BEING ABSORBED, so it has to travel. 3136 is
           #    linked to buttermilk and 3135 is linked to nothing, and a join that kept the
           #    survivor's empty link would have dropped it in silence. catalog_id is not a
           #    snapshot field, so there is no baseline entry to keep in step with it.
           "carry": {"catalog_id": "Q106612"},
           "why": "Andy's residual decision: the amount is on top and the name is below it, the "
                  "mirror of the four tail splits the rules already join"},
    # "fix: restore the missing '(' -> amount 1 stick | second amount ½ cup / 113 grams |
    #  name joined with row 3518"
    3517: {"what": "join_below", "absorb": 3518,
           "changes": {"qty": "1 stick", "quantity": "1", "unit": "stick",
                       "secondary_measure": "½ cup / 113 grams",
                       "label": "cold unsalted butter, cut into ½-inch cubes",
                       "raw_text": "1 stick (½ cup/113 grams) cold unsalted butter, cut into "
                                   "½-inch cubes"},
           "why": "Andy's residual decision: the opening bracket is missing, and with it restored "
                  "the line is the ordinary \"N stick (cups/grams) butter\" shape"},
    # "fix: 'sifted' moves to the note column; name natural, unsweetened cocoa powder"
    # ⚠️ AND THE SECOND AMOUNT IS SPELLED OUT HERE, BECAUSE A DECIDED ROW IS NOT RULED ON. Found
    #    by reading the rehearsed row: the slot held "¼ cup", a copy of the row's own first
    #    amount, which is one of the 130 the round exists to repair. The rule would have written
    #    "23 grams" off the author's line, and claiming the row for a decision about the NAME
    #    silently kept the wrong figure. Andy's decision is about "sifted"; this is the repair the
    #    rule was already going to make, written out so owning the row does not lose it.
    # ---- revision 2's residual file ------------------------------------------------------- #
    # "fix: same as buttermilk-biscuits 3135 -> amount 1 cup + 2 tablespoons | name tahini (light
    #  roast)". ⚠️ NOT A JOIN, AND THE DECISION'S "SAME AS" IS ABOUT THE RESULT. 3135's two halves
    #  sat on two rows; this one row holds both, "1 cup" in its amount and "plus 2 tablespoons
    #  tahini (light roast)" in its raw text, with no name column at all. ⚠️ AND THE SLOT GOES
    #  EMPTY: it held "1 cup", a copy of the old first amount, which is one of the 130 copies the
    #  round exists to clear. The raw text is the row's own amount in front of its own raw text,
    #  which is how the joins rebuild a line.
    7613: {"what": "row", "changes": {"qty": "1 cup + 2 tablespoons",
                                      "quantity": "1 cup + 2 tablespoons", "unit": "",
                                      "label": "tahini (light roast)", "secondary_measure": None,
                                      "raw_text": "1 cup plus 2 tablespoons tahini (light roast)"},
           "why": "Andy's residual decision: the amount is 1 cup plus 2 tablespoons and the name "
                  "is tahini (light roast), the shape of buttermilk-biscuits 3135"},
    # "fix: restore the missing closing ')'" — the line ends inside its own list of oils.
    4767: {"what": "row",
           "changes": {"label": "oil (neutral flavored coconut oil, regular coconut oil, avocado "
                                "oil, or vegetable oil)",
                       "raw_text": "1/2 cup oil (neutral flavored coconut oil, regular coconut "
                                   "oil, avocado oil, or vegetable oil)"},
           "why": "Andy's residual decision: the closing bracket is missing at the end of the "
                  "line, after the last oil it lists"},
    # "fix: restore the missing '(' as in chocolate-hazelnut-wedges 3517". With the bracket back,
    # the line is the ordinary "<cups> flour (<grams>)" shape, spelled out the way 3517 was.
    5204: {"what": "row",
           "changes": {"label": "spooned and leveled all-purpose flour",
                       "secondary_measure": "288 grams",
                       "raw_text": "2 ¼ cups spooned and leveled all-purpose flour (288 grams)"},
           "why": "Andy's residual decision: the opening bracket is missing before 288 grams, and "
                  "with it restored the grams are the line's second amount"},
    4422: {"what": "join_below", "absorb": 4423,
           "changes": {"label": "natural, unsweetened cocoa powder", "note": "sifted",
                       "secondary_measure": "23 grams",
                       "raw_text": "¼ cup (23 grams) natural, unsweetened cocoa powder, sifted"},
           "why": "Andy's residual decision: 'sifted' is preparation and the note column exists "
                  "for it, which keeps the library match without a hand_repoints row"},
}
# ⚠️ EVERY "FIX" IN REVISION 2'S RESIDUAL FILE IS ACCOUNTED FOR, AND THE PASS REFUSES OTHERWISE. A
#    decision a pass silently skips is a hand edit nobody made. Each row is either spelled out in
#    RESIDUAL_FIXES above, settled by a rule, or not run, with the reason the report repeats.
RESIDUAL_2_BY_RULE = {
    4604: "R5's count arm writes it: 'or 2 pureed tomatoes' names a different food from the row's "
          "tomato sauce, so it is the row's note (decisions-3)",
    # The second file sent this line to the note, against decisions-3's first row. The third file
    # answers it again with what R2 writes, so the decision and the rule agree and nothing is
    # left unrun.
    4145: "R2 writes it: 'or ½ English cucumber' is the same food as the row's Persian cucumber, "
          "so it is a line of the second amount, 'or ½ English' (decisions-3)",
}
RESIDUAL_2_NOT_RUN = {
    # "fix ONLY if it is just a missing ')' at the end ... otherwise leave as is". It is not: the
    # line is "3 tbsp Thai tea mix (" with NOTHING after the bracket, so restoring ")" gives "()"
    # around nothing. Whatever the bracket held was lost before the import, and the name the page
    # prints is already "Thai tea mix" with no stray bracket in it.
    5835: "left as is: the bracket opens at the very end of the line with nothing inside it, so a "
          "closing bracket would enclose nothing, and the stored name already reads 'Thai tea mix'",
}

# ⚠️ bananas-foster 2832 IS NOT HERE, AND IT WAS IN AN EARLIER DRAFT OF THIS LIST. Its decision
#    ("amount 300 grams | second amount 2 large / about 1 ¼ cups | name semi-ripe bananas, peeled
#    and roughly chopped") is now what R2 produces on its own, because the count fragment is split
#    into what measures and what names the food. A decided row that a rule can reach is a rule,
#    which is the whole point of fixing by rule rather than by row.


def _residual_decisions_all():
    """The three residual files, a later one winning where a row is in more than one. Every "fix"
    in the two later files has to be spelled out, settled by a rule, or named as not run."""
    merged = _residual_decisions(RESIDUAL_DECISIONS)
    later = _residual_decisions(RESIDUAL_DECISIONS_2)
    later.update(_residual_decisions(RESIDUAL_DECISIONS_3))
    merged.update(later)
    unaccounted = [rid for rid, (decision, _r) in later.items()
                   if decision.lower().startswith("fix") and rid not in RESIDUAL_FIXES
                   and rid not in RESIDUAL_2_BY_RULE and rid not in RESIDUAL_2_NOT_RUN]
    if unaccounted:
        raise SystemExit(f"{RESIDUAL_DECISIONS_3.name}: row(s) {unaccounted} say fix and nothing "
                         f"in this pass runs them, and a decision skipped in silence is a hand "
                         f"edit nobody made")
    return merged


def _residual_decisions(path=None):
    """Read the residual file and return {row_id: (decision, reason)}, refusing a blank DECISION.

    ⚠️ THE FILE IS OPENED, which is what makes it a committed decision rather than a survey. A
       pass that cannot be re-run from a fresh clone is a hand edit with more steps.
    """
    path = path or RESIDUAL_DECISIONS
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for n, r in enumerate(csv.DictReader(fh), start=2):
            rid = (r.get("row_id") or "").strip()
            if not rid:
                continue
            decision = (r.get("DECISION") or "").strip()
            if not decision:
                raise SystemExit(f"{path.name} line {n}: row {rid} has a blank DECISION, and a "
                                 f"blank is not an answer")
            out[int(rid)] = (decision, (r.get("REASON") or "").strip())
    return out


def _click_through_decisions(path=None):
    """Read the click-through file, so a fresh clone proves the rules it authorizes are present."""
    path = path or DECISIONS_2
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append({k: (v or "").strip() for k, v in r.items() if k})
    if not out:
        raise SystemExit(f"{path.name} is empty, and this round's rules are what it authorizes")
    return out


def _residual_calls(rows, writes, decided):
    """The residual rows Andy settled, each checking for its own result first."""
    by_id = {r["id"]: r for rs in rows.values() for r in rs}
    for rid, fix in sorted(RESIDUAL_FIXES.items()):
        row = by_id.get(rid)
        if row is None:
            continue
        decision, _reason = decided.get(rid, ("", ""))
        if not decision.lower().startswith("fix"):
            raise SystemExit(f"row {rid} is applied by this pass and the residual file says "
                             f"{decision!r}, which is not a fix")
        changes = {k: v for k, v in fix["changes"].items() if (row.get(k) or None) != (v or None)}
        absorb = fix.get("absorb")
        if not changes and (absorb is None or absorb not in by_id):
            continue                                        # already applied
        if fix["what"] == "join_below":
            writes[row["recipe_id"]].append(
                {"what": "join", "id": rid, "absorb": [absorb] if absorb in by_id else [],
                 "why": fix["why"]})
        writes[row["recipe_id"]].append(
            {"what": "row", "id": rid, "changes": changes, "why": fix["why"],
             "rules": ["residual_decision"], "carry": fix.get("carry")})

# The five single-row calls, by the row they name. Each one is a judgement about these words that no
# rule can read, and each is recorded in the decisions file with its reason.
HUMMUS_GARNISH_ROW = 4060
HUMMUS_HEADING = "Any of the following garnishes"
HUMMUS_LINES = ("drizzle of olive oil or zhoug sauce",
                "sprinkle of ground sumac or paprika",
                "chopped fresh parsley")
BEANS_CHART_ROWS = tuple(range(2866, 2881))      # 15 rows, the simmer-time chart
BEANS_CHART_HEADING = 2865                       # "BEANS AND LEGUMES COOKING TIME ON THE STOVETOP"
BEANS_NOTE_STEP = 1783                           # "Use the guide below for how long to let beans..."
BEANS_NOTE_TITLE = "Simmer times"
FLATBREADS_ROW = 3824
MISO_TOFU_ROW = 9135
MISO_TOFU_SECOND = "1 block"
# Every row a single-row call owns. A rule never writes to one of these.
# ⚠️ AND THE RESIDUAL ROWS JOIN IT, for the reason the declared set exists at all: on a SECOND run
#    each call finds its work done and produces nothing, so a set derived from the writes would be
#    empty and the rules would claim those rows back.
_RESIDUAL_ROW_IDS = frozenset({2834, 4320, 3135, 3136, 3517, 3518, 4422, 4423,
                               7613, 4767, 5204})
# ⚠️ RESIDUAL_HELD IS NOT IN THIS SET, AND THAT IS THE POINT OF IT. A row Andy is holding has to
#    stay FLAGGED, which means the rule still has to look at it and still has to refuse it. Adding
#    it here made the rule stand aside, and a row that is neither changed nor flagged is a row that
#    has quietly left the review list.
DECIDED_ROWS = frozenset({HUMMUS_GARNISH_ROW, FLATBREADS_ROW, MISO_TOFU_ROW,
                          BEANS_CHART_HEADING} | set(BEANS_CHART_ROWS) | _RESIDUAL_ROW_IDS)
# The rows a residual fix absorbs, so the join rule's "decided elsewhere" flag does not report a
# row that IS settled, by the decided join directly above it.
_RESIDUAL_ABSORBED = frozenset({3136, 3518, 4423})


def _load_rows(con):
    rows = collections.defaultdict(list)
    for r in con.execute("SELECT * FROM recipe_ingredients ORDER BY recipe_id, position, id"):
        rows[r["recipe_id"]].append(dict(r))
    return rows


def plan(con, ic, density_for, hand_edited, snapshot_fields=()):
    """Every write this round makes, per recipe, computed from the rows as stored.

    Returns (writes, flags, notes) where writes is {recipe_id: [change, ...]}.
    """
    rows = _load_rows(con)
    writes = collections.defaultdict(list)
    flags, notes = [], []
    # ⚠️ THE CALLS GO FIRST AND CLAIM THEIR ROWS, because a decision and a rule that both write one
    #    column fight on every run. miso-tofu's "block" is the second amount by Andy's call and is
    #    nothing at all by the rule, so the pass set it and then unset it, run after run.
    _single_row_calls(con, rows, writes)
    # ⚠️ AND THE RESIDUAL ROWS, FOR THE SAME REASON: a decision and a rule that both write one
    #    column fight on every run. _click_through_decisions is read here so a clone that cannot
    #    open the file cannot run the pass, which is what makes the rules below re-runnable.
    _click_through_decisions()
    _click_through_decisions(DECISIONS_3)
    _residual_calls(rows, writes, _residual_decisions_all())
    # ⚠️ THE OWNED ROWS ARE A DECLARED SET, NOT THE SET OF WRITES THE CALLS HAPPEN TO PRODUCE. On a
    #    SECOND run each call finds its work already done and produces nothing, so a set derived
    #    from the writes was empty and the rules claimed those rows back. miso-tofu's "1 block" and
    #    flatbreads' "150g" were set by the call and unset by the rule, run after run.
    decided = DECIDED_ROWS
    for rid, rs in rows.items():
        # (1) the joins, read off the stored rows. A row absorbed into the one above it is deleted,
        #     and the row above takes both texts.
        absorbed = {}
        for i, r in enumerate(rs):
            above = rs[i - 1] if i else None
            if above is None or above["id"] in absorbed:
                continue
            why = ic.joins_the_row_above(above, r)
            if not why:
                continue
            # ⚠️ AN ABSORBED ROW IS DELETED, SO IT NEEDS THE SAME GUARD THE SURVIVOR GETS. The
            #    row-level protection ran on the row that SURVIVES, and the absorbed one was taken
            #    out of the list before any guard saw it. A row the cook had edited would have been
            #    deleted with its baseline entry and named in no flag of the residual list.
            if r["id"] in hand_edited.get(rid, ()) or above["id"] in hand_edited.get(rid, ()):
                flags.append({"recipe_id": rid, "row_id": r["id"], "part": "lockstep",
                              "reason": "this row joins the one above it and the cook has edited "
                                        "one of the two, so neither is changed"})
                continue
            if r["id"] in DECIDED_ROWS or above["id"] in DECIDED_ROWS:
                # A row a residual fix absorbs is settled by that fix, so it is not a residual row.
                if r["id"] not in _RESIDUAL_ABSORBED:
                    flags.append({"recipe_id": rid, "row_id": r["id"], "part": "decided elsewhere",
                                  "reason": "this row joins the one above it and one of the two "
                                            "is a row Andy decided about, so the rule stands "
                                            "aside"})
                continue
            absorbed[r["id"]] = (above["id"], why)
        final = []
        for r in rs:
            if r["id"] in absorbed:
                continue
            r = dict(r)
            tail = [x for x in rs if absorbed.get(x["id"], (None,))[0] == r["id"]]
            if tail:
                joined_raw = ic._norm_ws(" ".join(
                    [(r.get("raw_text") or r.get("label") or "").strip()]
                    + [(x.get("raw_text") or x.get("label") or "").strip() for x in tail]))
                # ⚠️ THE JOINED NAME COMES OFF THE JOINED SOURCE LINE, NOT OFF THE TWO NAMES. The
                #    importer had already taken the amount out of each row's label, so concatenating
                #    the labels dropped whatever sat between them: tseke-com-peix-frito's two rows
                #    joined to "whole mackerel (about cleaned and cut in half crosswise", with the
                #    "1½ pounds each)" gone and the bracket left hanging. The row's own amount is a
                #    literal prefix of its source line, so taking that prefix off is exact.
                qty = (r.get("qty") or "").strip()
                rest = joined_raw[len(qty):].lstrip() if qty and joined_raw.startswith(qty) else None
                if rest is None:
                    rest = ic._norm_ws(" ".join(
                        [(r.get("label") or r.get("raw_text") or "").strip()]
                        + [(x.get("label") or x.get("raw_text") or "").strip() for x in tail]))
                r["raw_text"] = joined_raw
                r["label"] = rest
                r["_joined"] = [x["id"] for x in tail]
                r["_join_why"] = absorbed[tail[0]["id"]][1]
            final.append(r)

        # (1b) R6: a row that is only a remark, directly under an ingredient heading, is a note
        #      about that SECTION. One row in the corpus, and ten more that look like it sit under
        #      an ordinary row where the remark belongs to the line above them.
        remarked = set()
        for i, r in enumerate(final):
            above = final[i - 1] if i else None
            note = ic.remark_row_to_note(above, r)
            if not note:
                continue
            if r["id"] in hand_edited.get(rid, ()) or r["id"] in decided:
                flags.append({"recipe_id": rid, "row_id": r["id"], "part": "lockstep",
                              "reason": "this row would become a note and the cook has edited it, "
                                        "so it is left where it is"})
                continue
            writes[rid].append({"what": "table_to_note", "ids": [r["id"]], "title": note["title"],
                                "text": note["text"], "step_id": None, "why": note["why"]})
            remarked.add(r["id"])

        for r in final:
            if r.get("is_heading"):
                continue
            if r["id"] in remarked:                 # R6 took the row out of the ingredients
                continue
            if r["id"] in decided:                  # a row Andy decided about is not also ruled on
                continue
            if r["id"] in hand_edited.get(rid, ()):  # a row the cook edited is never changed
                flags.append({"recipe_id": rid, "row_id": r["id"], "part": "lockstep",
                              "reason": "the cook has edited this row, so the pass leaves it"})
                continue
            p = ic.amount_plan(r, density_for)
            for flag, reason in p["flags"]:
                flags.append({"recipe_id": rid, "row_id": r["id"], "part": flag,
                              "reason": reason})
            for flag, reason in p["notes"]:
                notes.append({"recipe_id": rid, "row_id": r["id"], "part": flag,
                              "reason": reason})
            changes = dict(p["changes"])
            if r.get("_joined"):
                if p["flags"]:
                    continue                        # the join is part of a row the rules refused
                changes.setdefault("label", r["label"])
                changes["raw_text"] = r["raw_text"]
                writes[rid].append({"what": "join", "id": r["id"], "absorb": r["_joined"],
                                    "why": r["_join_why"]})
            # ⚠️ R4 ASKS FOR A ROW OF ITS OWN, AND split_row IS THE WRITE THAT MAKES ONE. The
            #    `first` half is this row's own changes and the `second` is the new food, which
            #    lands directly under it. flatbreads' decided split uses the same write, so there
            #    is one insert path rather than two.
            if p.get("insert"):
                writes[rid].append({"what": "split_row", "id": r["id"],
                                    "first": {k: v for k, v in changes.items()
                                              if k in snapshot_fields},
                                    "second": dict(p["insert"]),
                                    "why": "; ".join(p["why"])})
                changes = {k: v for k, v in changes.items() if k not in snapshot_fields}
            if changes:
                writes[rid].append({"what": "row", "id": r["id"], "changes": changes,
                                    "why": "; ".join(p["why"]) or "the author's second amount",
                                    "rules": p["rules"]})

    return writes, flags, notes


def _single_row_calls(con, rows, writes):
    """The five decisions Andy made about one row each. Each checks for its own result first."""
    by_id = {r["id"]: r for rs in rows.values() for r in rs}

    # hummus-2: one line holding a heading and three garnishes, as the author wrote them.
    row = by_id.get(HUMMUS_GARNISH_ROW)
    if row is not None and not row["is_heading"]:
        writes[row["recipe_id"]].append(
            {"what": "list_to_heading", "id": row["id"], "heading": HUMMUS_HEADING,
             "lines": list(HUMMUS_LINES),
             "why": "Andy's call: an ingredient heading like \"Optional\", with the three garnishes "
                    "under it as the author wrote them"})

    # beans: the 15-row simmer-time chart leaves the ingredients and becomes ONE note.
    chart = [by_id[i] for i in BEANS_CHART_ROWS if i in by_id]
    if chart:
        # ⚠️ THE AUTHOR'S OWN WORDING, FROM raw_text. The labels are half-recased by the name-case
        #    round ("• black beans:" against the author's "• Black beans:"), and a chart of bean
        #    names is exactly where that shows.
        # ⚠️ AND THE AUTHOR'S BULLET STAYS. Measured: .notes-para is white-space: pre-wrap and
        #    nothing in the note display draws a bullet of its own, so dropping the "•" would
        #    leave 15 lines with no marker at all rather than one marker instead of two.
        text = "\n".join((r["raw_text"] or r["label"] or "").strip() for r in chart)
        heading = by_id.get(BEANS_CHART_HEADING)
        writes["beans"].append(
            {"what": "table_to_note", "ids": [r["id"] for r in chart]
             + ([heading["id"]] if heading is not None else []),
             "title": BEANS_NOTE_TITLE, "text": text, "step_id": BEANS_NOTE_STEP,
             "why": "Andy's option 1: the chart is a note on the step that points at it, and the "
                    "recipe is left with no ingredients"})

    # flatbreads: two ingredients run together in one row.
    row = by_id.get(FLATBREADS_ROW)
    if row is not None and "extra virgin olive oil" in (row["label"] or ""):
        writes[row["recipe_id"]].append(
            {"what": "split_row", "id": row["id"],
             "first": {"qty": "about ⅔ cup", "quantity": "about ⅔ cup", "unit": "",
                       "label": "unflavored yogurt", "secondary_measure": "150g",
                       "raw_text": "about ⅔ cup/150g unflavored yogurt"},
             "second": {"qty": None, "quantity": None, "unit": None,
                        "label": "extra virgin olive oil", "secondary_measure": None,
                        "raw_text": "extra virgin olive oil"},
             "why": "Andy's decision 11: two ingredients run together, and no rule can tell where "
                    "one ends"})

    # miso-tofu: the amount stays 16 oz and "block" becomes the second amount.
    row = by_id.get(MISO_TOFU_ROW)
    if row is not None and (row["secondary_measure"] or "") != MISO_TOFU_SECOND:
        writes[row["recipe_id"]].append(
            {"what": "row", "id": row["id"],
             "changes": {"secondary_measure": MISO_TOFU_SECOND,
                         "label": "extra firm tofu (drained and pressed)"},
             "why": "Andy's call: the amount stays 16 oz and \"block\" leaves the name as the "
                    "second amount",
             "rules": ["decided"]})


# --------------------------------------------------------------------------------------------- #
# the write
# --------------------------------------------------------------------------------------------- #

def _half_applied(rid, done, why):
    """The abort message, saying where the run stopped rather than claiming it never started."""
    return (f"ABORT on {rid}: {why}. This recipe's writes were rolled back.\n"
            f"  {len(done)} recipe(s) BEFORE it are already COMMITTED, so the corpus is part way "
            f"through this round. Each recipe is its own transaction on purpose, because a gate run "
            f"over the whole pass would be a post-mortem on data already on disk.\n"
            f"  Running the pass again is safe (it is a no-op on what is in place), but do not "
            f"assume it will get further: fix what this recipe tripped on first, or restore the "
            f"database from the backup named in the go-live file.\n"
            f"  committed: {', '.join(done[-8:]) if done else '(none)'}")


def _state(s, sqlalchemy, app, rid):
    """This recipe's byte-equal place and its annotation SET, as the declared gate reads them.

    ⚠️ THE KEY IS gates/state.py's OWN, NOT THE RAW ENTRIES. An entry carries new_pos and
       old_pos, the heading-excluded index of the row it sits on, and this round inserts 4 rows and
       deletes 21, so every entry BELOW a changed row gets a different index while saying the same
       thing. Comparing the raw entries would abort a recipe over a re-index the round declares as
       "annotations: unchanged", leaving the corpus half migrated. Two answers to one question, and
       this is the one the go-live gate is held to.
    """
    import state as gate_state
    cur = app.serialize_recipe_content(s, rid)
    got = s.execute(sqlalchemy.text(
        "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
        {"r": rid}).scalar_one_or_none()
    marks = sorted(gate_state.entry_key(e) for e in app._recipe_annotations(s, rid))
    return {"byte_equal": got is not None and cur == got,
            "marks": json.dumps(marks, sort_keys=True)}


def _entry(doc, row_id):
    for e in doc.get("ingredients") or []:
        if e.get("id") == row_id:
            return e
    return None


def _write_recipe(s, sqlalchemy, snapshot_serialize, rid, writes, doc):
    """Apply one recipe's writes and patch its baseline in the same transaction."""
    def ex(sql, **kw):
        s.execute(sqlalchemy.text(sql), kw)

    moved = False
    gone = []

    for w in [x for x in writes if x["what"] == "row"]:
        # ⚠️ A COLUMN THE SNAPSHOT DOES NOT HOLD IS CARRIED SEPARATELY, AND IT CANNOT BE USED TO
        #    BYPASS LOCKSTEP. catalog_id is the library link (migration 033) and no baseline entry
        #    records it, so there is nothing to keep in step; the assert is what stops a snapshot
        #    field being smuggled through this door. buttermilk-biscuits' decided join needs it:
        #    the link lives on the row being absorbed, and a join that kept the survivor's empty
        #    link would have dropped it in silence.
        carry = w.get("carry") or {}
        for k in carry:
            if k in snapshot_serialize.SNAPSHOT_ING_FIELDS:
                raise RuntimeError(f"{k} is a snapshot field and must move in lockstep, not as a "
                                   f"carried column")
        if carry:
            ex("UPDATE recipe_ingredients SET "
               + ", ".join(f"{k}=:{k}" for k in carry) + " WHERE id=:_id", _id=w["id"], **carry)
        if not w["changes"]:
            continue
        sets = ", ".join(f"{k}=:{k}" for k in w["changes"])
        ex(f"UPDATE recipe_ingredients SET {sets} WHERE id=:_id",
           _id=w["id"], **w["changes"])
        if doc is not None:
            e = _entry(doc, w["id"])
            if e is None:
                raise RuntimeError(f"the baseline has no ingredient {w['id']}")
            for k, v in w["changes"].items():
                if k not in snapshot_serialize.SNAPSHOT_ING_FIELDS:
                    raise RuntimeError(f"{k} is written to the row and is not in the snapshot, so "
                                       f"the two cannot be kept in step")
                e[k] = v
            moved = True

    for w in [x for x in writes if x["what"] == "join"]:
        for other in w["absorb"]:
            ex("DELETE FROM recipe_ingredients WHERE id=:i", i=other)
            gone.append(other)

    for w in [x for x in writes if x["what"] == "list_to_heading"]:
        ex("UPDATE recipe_ingredients SET is_heading=1, heading=:h WHERE id=:i",
           h=w["heading"], i=w["id"])
        at = s.execute(sqlalchemy.text("SELECT position FROM recipe_ingredients WHERE id=:i"),
                       {"i": w["id"]}).scalar_one()
        # ⚠️ THE ROWS BELOW ARE PUSHED OUT OF THE WAY FIRST. recipe_ingredients carries no
        #    uniqueness on (recipe_id, position), so inserting into an occupied slot does not
        #    collide, it just puts two rows there, and the next read of that position finds both.
        ex("UPDATE recipe_ingredients SET position=position+:k WHERE recipe_id=:r AND position>:p",
           k=len(w["lines"]), r=rid, p=at)
        for n, line in enumerate(w["lines"], start=1):
            new_id = s.execute(sqlalchemy.text(
                "INSERT INTO recipe_ingredients (recipe_id, position, is_heading, label, "
                "raw_text) VALUES (:r, :p, 0, :t, :t) RETURNING id"),
                {"r": rid, "p": at + n, "t": line}).scalar_one()
            if doc is not None:
                doc["ingredients"].append(snapshot_serialize.snapshot_ing_row(
                    {"id": new_id, "position": at + n, "is_heading": 0, "label": line,
                     "raw_text": line, "qty": None, "ingredient_id": None, "note": None,
                     "grams": None, "secondary_measure": None, "quantity": None, "unit": None}))
        if doc is not None:
            e = _entry(doc, w["id"])
            if e is None:
                raise RuntimeError(f"the baseline has no ingredient {w['id']}")
            # ⚠️ A HEADING'S TITLE IS PROJECTED INTO raw_text BY snapshot_ing_row, so the baseline
            #    entry has to carry it the same way or the diff reports the heading renamed.
            e["is_heading"], e["raw_text"] = 1, w["heading"]
            moved = True

    for w in [x for x in writes if x["what"] == "split_row"]:
        sets = ", ".join(f"{k}=:{k}" for k in w["first"])
        ex(f"UPDATE recipe_ingredients SET {sets} WHERE id=:_id", _id=w["id"], **w["first"])
        at = s.execute(sqlalchemy.text("SELECT position FROM recipe_ingredients WHERE id=:i"),
                       {"i": w["id"]}).scalar_one()
        ex("UPDATE recipe_ingredients SET position=position+1 WHERE recipe_id=:r AND position>:p",
           r=rid, p=at)
        cols = ", ".join(w["second"])
        new_id = s.execute(sqlalchemy.text(
            f"INSERT INTO recipe_ingredients (recipe_id, position, is_heading, {cols}) "
            f"VALUES (:_r, :_p, 0, {', '.join(':' + k for k in w['second'])}) RETURNING id"),
            dict(w["second"], _r=rid, _p=at + 1)).scalar_one()
        if doc is not None:
            e = _entry(doc, w["id"])
            if e is None:
                raise RuntimeError(f"the baseline has no ingredient {w['id']}")
            for k, v in w["first"].items():
                e[k] = v
            doc["ingredients"].append(snapshot_serialize.snapshot_ing_row(
                dict({"id": new_id, "position": at + 1, "is_heading": 0, "ingredient_id": None,
                      "note": None, "grams": None}, **w["second"])))
            moved = True

    for w in [x for x in writes if x["what"] == "table_to_note"]:
        at = s.execute(sqlalchemy.text(
            "SELECT COALESCE(MAX(position)+1, 0) FROM recipe_notes WHERE recipe_id=:r"),
            {"r": rid}).scalar_one()
        # ⚠️ step_id MAY BE None, AND THAT IS NOT THE SAME AS BEANS' CASE. beans' chart is a note
        #    ON the step that points at it. R6's remark is about an ingredient SECTION, and a
        #    section is not a step, so there is nothing for the note to point at and a guessed
        #    pointer would be worse than none.
        ex("INSERT INTO recipe_notes (recipe_id, position, kind, title, text, step_id) "
           "VALUES (:r, :p, 'notes', :h, :t, :s)",
           r=rid, p=at, h=w["title"], t=w["text"], s=w.get("step_id"))
        # ⚠️ NO recipe_notes_original ENTRY. That table is the record of what the AUTHOR wrote in
        #    the notes field, and these words were in the INGREDIENTS. Writing them there would
        #    claim the author put a simmer chart in the notes.
        for i in w["ids"]:
            ex("DELETE FROM recipe_ingredients WHERE id=:i", i=i)
            gone.append(i)

    # ⚠️ EVERY DELETE AND EVERY INSERT RENUMBERS, AND THE BASELINE IS RENUMBERED WITH IT. The
    #    position is a structural fact about the recipe, so a baseline left at the old numbering
    #    reads as the cook having reordered the list.
    if gone and doc is not None:
        doc["ingredients"] = [e for e in doc["ingredients"] if e.get("id") not in set(gone)]
        moved = True
    live = list(s.execute(sqlalchemy.text(
        "SELECT id, position FROM recipe_ingredients WHERE recipe_id=:r ORDER BY position, id"),
        {"r": rid}).mappings())
    for n, row in enumerate(live):
        if row["position"] != n:
            ex("UPDATE recipe_ingredients SET position=:p WHERE id=:i", p=n, i=row["id"])
            moved = True
    if doc is not None:
        where = {row["id"]: n for n, row in enumerate(live)}
        for e in doc["ingredients"]:
            if e.get("id") in where and e.get("position") != where[e["id"]]:
                e["position"] = where[e["id"]]
                moved = True
        doc["ingredients"].sort(key=lambda e: (e.get("position") is None, e.get("position") or 0))
    return moved


def run(db, apply=False, record=None):
    import app
    import import_cleanup as ic
    import snapshot_serialize
    import sqlalchemy
    import weights
    import sqlite3

    app.DB = db
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # ⚠️ THE DENSITIES COME OFF THE AUTHORS' OWN LINES, not off the secondary_measure column this
    #    round is repairing. Built from the column the index knew 3 foods.
    ing = [dict(r) for r in con.execute(
        "SELECT recipe_id, label, raw_text, qty, secondary_measure FROM recipe_ingredients "
        "WHERE is_heading=0")]
    corpus = ic.corpus_densities(ing)
    chart = weights.build_index([dict(r) for r in con.execute(
        "SELECT lookup_key, display_name, grams_per_ml, convert_to_grams FROM ingredient_weights")])

    def density_for(name):
        key = weights.normalize(name or "")
        if key in corpus:
            return corpus[key]
        m = weights.match_weight(name or "", chart)
        return m[0] if m else None

    hand_edited = {}
    with app.orm_session() as s:
        for (rid,) in s.execute(sqlalchemy.text("SELECT id FROM recipes")):
            marks = app._recipe_annotations(s, rid)
            touched = {e["row_id"] for e in marks
                       if e.get("kind") == "ingredient" and e.get("row_id") is not None}
            if touched:
                hand_edited[rid] = touched

    writes, flags, notes = plan(con, ic, density_for, hand_edited,
                                snapshot_fields=snapshot_serialize.SNAPSHOT_ING_FIELDS)
    # The linked rows whose NAME this round changes, read before the write so the matcher's two
    # answers can be compared. A row with no stored link has nothing to lose.
    import linkage_matcher
    derived = {r["id"]: (r.get("catalog_id") or "") for r in linkage_matcher.propose(db=db)[0]}
    # ⚠️ EVERY WRITE THAT RENAMES A ROW, NOT JUST THE RULE WRITES. split_row renames 3824 and
    #    list_to_heading takes 4060 out of the lines altogether, and neither is a "row" write, so
    #    neither reached the matcher comparison. 2,851 of live's ingredient rows carry a catalog_id.
    changing = {w["id"]: w for ws in writes.values() for w in ws
                if "id" in w and (
                    (w["what"] == "row" and "label" in w.get("changes", {}))
                    or w["what"] in ("split_row", "list_to_heading", "join"))}
    renamed_before = {}
    for row in con.execute("SELECT id, recipe_id, label, catalog_id FROM recipe_ingredients"):
        if row["id"] in changing and row["catalog_id"]:
            renamed_before[row["id"]] = {"recipe_id": row["recipe_id"], "label": row["label"],
                                         "derived": derived.get(row["id"], "")}
    con.close()

    rows_written = sum(1 for ws in writes.values() for w in ws if w["what"] == "row")
    print(f"ROUND B over {db}")
    print(f"  {sum(len(w) for w in writes.values())} write(s) over {len(writes)} recipe(s)")
    for what, n in collections.Counter(w["what"] for ws in writes.values()
                                       for w in ws).most_common():
        print(f"     {n:4}  {what}")
    print(f"  rules that fired:")
    for rule, n in collections.Counter(r for ws in writes.values() for w in ws
                                       for r in w.get("rules", [])).most_common():
        print(f"     {n:4}  {rule}")
    print(f"  {len(flags)} row(s) FLAGGED and left exactly as they are:")
    for part, n in collections.Counter(f["part"] for f in flags).most_common():
        print(f"     {n:4}  {part}")
    if notes:
        print(f"  {len(notes)} note(s), where one part of a row was declined and the rest applied")

    # ⚠️ ONE WRITE, AT THE END. It was written here and AGAIN after the drift survey, on the
    #    same path, which is how three committed records were truncated to their header lines. The
    #    overwrite refusal is report_target's, so it has to be asked once per run.
    out = report_target(RESIDUAL, record)   # it exits on its own over a non-empty record

    if not apply:
        _write_residual(out, flags, notes)
        print(f"  residual rows -> {out}")
        print("  DRY RUN. Nothing written to the database. Pass --apply to write.")
        return writes
    if not writes:
        _write_residual(out, flags, notes)
        print(f"  residual rows -> {out}")
        print("  nothing to do. Every decision is already in place.")
        return writes

    before, done = {}, []
    with app.orm_session() as s:
        for rid in writes:
            before[rid] = _state(s, sqlalchemy, app, rid)
    for rid, ws in writes.items():
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            doc = json.loads(stored) if stored is not None else None
            # ⚠️ THE ID GUARD ONLY BITES WHERE POSITIONS MOVE, AND THE FIRST VERSION REFUSED 19
            #    RECIPES FOR NOTHING. 24 baseline rows over 19 recipes carry no row id, because
            #    the commit-3 backfill found no content match for them. A write that only changes
            #    COLUMNS needs the rows it touches to be findable, which _entry raises about. A
            #    write that DELETES or INSERTS renumbers every row after it, and a baseline entry
            #    with no id cannot be renumbered with its row, so that one is refused.
            shifts = any(x["what"] in ("join", "list_to_heading", "split_row", "table_to_note")
                         for x in ws)
            if (shifts and doc is not None
                    and any(e.get("id") is None for e in doc.get("ingredients") or [])):
                s.rollback()
                sys.exit(_half_applied(rid, done, "this recipe's writes renumber its rows and its "
                                                  "baseline holds an ingredient with no row id, "
                                                  "so the two cannot be kept in step"))
            try:
                moved = _write_recipe(s, sqlalchemy, snapshot_serialize, rid, ws, doc)
            except Exception as exc:
                # ⚠️ NOT JUST RuntimeError. _write_recipe can raise IntegrityError from three
                #    real constraints on the note insert alone, and a bare traceback never tells
                #    the operator that N recipes before this one are already committed, which is
                #    the whole job of the message below.
                s.rollback()
                sys.exit(_half_applied(rid, done, f"{type(exc).__name__}: {exc}"))
            if moved and doc is not None:
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r "
                    "AND reason='original'"),
                    # ⚠️ ensure_ascii=False, AND THE GATE IS WHAT SAID SO. json.dumps' default
                    #    escapes a unicode fraction, so every patched baseline was byte-DIFFERENT
                    #    from its recipe's serialization while holding identical values. Measured:
                    #    the byte-equal set fell 280 to 214 with nothing wrong in the data. These
                    #    three flags are content_blob's own and have to stay its twin.
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            now = _state(s, sqlalchemy, app, rid)
            if now["marks"] != before[rid]["marks"]:
                s.rollback()
                sys.exit(_half_applied(rid, done, "the annotation set moved") +
                         f"\n  before={before[rid]['marks'][:300]}\n  after ={now['marks'][:300]}")
            if before[rid]["byte_equal"] and not now["byte_equal"]:
                s.rollback()
                sys.exit(_half_applied(rid, done, "it left the byte-equal set"))
            s.commit()
            done.append(rid)
    print(f"  WROTE {sum(len(w) for w in writes.values())} change(s) over {len(writes)} "
          f"recipe(s) -> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
    print(f"  {rows_written} ingredient row(s) updated")
    drift = _link_drift(db, renamed_before)
    print(f"  {len(renamed_before)} renamed row(s) carry a library link, and the matcher's answer "
          f"moves on {len(drift)}")
    for row in drift:
        print(f"     {row['row_id']} {row['recipe_id']}: {row['was']!r} -> {row['now']!r}")
        print(f"        the matcher said {row['before']!r}, it now says {row['after']!r}. The "
              f"stored link is untouched by this round.")
    _write_residual(out, flags + [
        {"recipe_id": d["recipe_id"], "row_id": d["row_id"], "part": "library link",
         "reason": (f"the name becomes {d['now']!r} and the matcher no longer derives "
                    f"{d['before']!r}, so a build_links rebuild would drop the link. Either the "
                    f"prep clause belongs in the note column or hand_repoints.csv needs a row.")}
        for d in drift], notes)
    print(f"  residual rows -> {out}")
    return writes


def _link_drift(db, renamed):
    """Which renamed rows the library matcher now answers differently about.

    ⚠️ THE STORED LINK IS NOT TOUCHED BY THIS ROUND, so nothing breaks today. What breaks is the
       next build_links.py rebuild, which derives every link from the names. A link that stops
       being derivable is a decision, so it goes in the residual list rather than being noticed
       the next time somebody rebuilds.
    """
    import sqlite3
    import linkage_matcher
    rows, _ = linkage_matcher.propose(db=db)
    now = {r["id"]: r for r in rows}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    current = {r["id"]: dict(r) for r in con.execute(
        "SELECT id, recipe_id, label FROM recipe_ingredients")}
    con.close()
    out = []
    for row_id, info in renamed.items():
        after = (now.get(row_id) or {}).get("catalog_id") or ""
        if after != info["derived"]:
            out.append({"row_id": row_id, "recipe_id": info["recipe_id"], "was": info["label"],
                        "now": (current.get(row_id) or {}).get("label"),
                        "before": info["derived"], "after": after})
    return out


def _write_residual(path, flags, notes):
    """The rows no rule settles, with a DECISION column for Andy.

    ⚠️ A ROW ANDY HAS ALREADY DECIDED CARRIES THAT DECISION, so the next list asks him only about
       what is new. 24 of revision 1's 36 rows are hand edits he answered "keep", and a list that
       blanked them again would ask the same question a third time. The REASON says which file
       the answer came from, so a carried answer never reads as a fresh one.
    """
    try:
        decided = _residual_decisions_all()
    except SystemExit:
        decided = {}
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The path comes from corpus_guard.report_target, which puts it in gitignored reports/ unless
    # --record is given and refuses to overwrite a non-empty committed record.
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "recipe_id", "row_id", "part", "reason", "DECISION", "REASON"])
        for f in flags:
            # ⚠️ A ROW ANDY IS HOLDING SAYS SO IN ITS REASON. 7462's decision exists and is
            #    waiting on him confirming where the recipe came from, so the row is back on this
            #    list and the list has to explain why rather than looking like a rule that failed.
            reason = f["reason"]
            held = RESIDUAL_HELD.get(f["row_id"])
            if held:
                reason = f"{reason} -- HELD: {held}"
            w.writerow(["flag", f["recipe_id"], f["row_id"], f["part"], reason]
                       + _carried(decided, f["row_id"]))
        for n in notes:
            w.writerow(["note", n["recipe_id"], n["row_id"], n["part"], n["reason"]]
                       + _carried(decided, n["row_id"]))


def _carried(decided, row_id):
    """[DECISION, REASON] for a row already decided in a committed residual file, else blanks."""
    if row_id not in decided:
        return ["", ""]
    decision, reason = decided[row_id]
    if row_id in RESIDUAL_2_NOT_RUN:
        return [decision, f"NOT RUN by this pass: {RESIDUAL_2_NOT_RUN[row_id]}"]
    return [decision, f"carried from a committed residual decisions file: {reason}"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="write the residual CSV into the committed docs/data-repairs/ instead of "
                         "gitignored reports/")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, record=a.record)


if __name__ == "__main__":
    main()
