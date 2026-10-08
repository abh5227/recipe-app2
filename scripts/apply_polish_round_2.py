#!/usr/bin/env python3.13
"""apply_polish_round_2.py - polish round 2, every part, from committed decisions.

Reads three COMMITTED decision files, because a pass that cannot be re-run from a fresh clone is a
hand edit with more steps:

    docs/data-repairs/heading-levels-2026-10-08.csv            78 heading levels
    docs/data-repairs/ingredient-name-case-2026-10-08.csv     112 ingredient names
    docs/data-repairs/polish-round-2-decisions-2026-10-08.csv  the row decisions a rule could not make

THE PARTS, in the order they run, and the order is the point:

  1  heading LEVELS, from the heading CSV and re-derived by the rule.
  2  ingredient NAMES: `fix:` applied literally, `defer: heading` converted to a heading,
     `group: Optional` moved under an inserted heading.
  3  the green-beans FOOTNOTE: two sentences into a linked note, the step deleted, the marker off.
  4  the dangling footnote MARKER on vanilla-mug-cake.
  5  note LABELS that name their own kind: stripped, or lifted into the title.
  6  karak-chai's LETTERING and homemade-pasta-dough's number and capital.

⚠️ THE LEVELS GO FIRST BECAUSE THEY ARE THE ONLY PART WHOSE RULE READS ANOTHER PART'S OUTPUT.
A heading's level depends on whether an AUTHOR-WRITTEN heading sits above it, and part 6 can make a
step into a heading. Nothing in this round actually does (karak-chai's parent is already a heading),
which is measured rather than assumed: the pass re-derives all 78 levels AFTER every other part has
run and aborts if any answer moved.

⚠️ PROVENANCE IS READ OFF THE ROWS, NOT OFF THE REVIEWED CSVs, and that is a correction. 263 headings
= 136 pre-existing rows + 127 the lift passes INSERTED, and only 104 of the 127 are in
step-leadin-labels / step-dash-labels. The other 23 were lifted by RULE after that candidate list was
reviewed. Reading provenance from the CSVs made those 23 look author-written, which made them parents
that demoted the lifted headings under them and meant they were never judged themselves. That is
where 6 of the 78 come from. See `lifted_heading_ids`.

⚠️ LOCKSTEP, PER RECIPE, IN ONE TRANSACTION, AND THE GATE RUNS BEFORE THE COMMIT. Every part except
the notes writes baseline content, so the reason='original' entry moves with the row or the cook is
told they made a change they never made. The notes are outside recipe_snapshots.content by Andy's
ruling, so part 5 has no baseline work at all, which is stated here because the ABSENCE of a patch is
the kind of thing a reader assumes is an omission.

⚠️ heading_level IS IN THE SNAPSHOT ONLY WHEN IT IS 2. snapshot_serialize.snapshot_step_row adds the
key for a level 2 and omits it otherwise, so a 2 -> 1 change REMOVES the key from the baseline entry.
Setting it to 1 instead leaves bytes that no current serialization will ever produce, and every one of
these 78 recipes would leave the byte-equal set with nothing on the page to show why.

⚠️ A SECOND RUN IS A NO-OP. Every part detects its own applied state during the PLANNING phase, which
is what makes the dry run a faithful preview of the real run.
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live                                          # noqa: E402

REPAIRS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data-repairs"
LEVELS_CSV = REPAIRS / "heading-levels-2026-10-08.csv"
NAMES_CSV = REPAIRS / "ingredient-name-case-2026-10-08.csv"
ROWS_CSV = REPAIRS / "polish-round-2-decisions-2026-10-08.csv"

# The whole vocabulary of the ingredient file's decision column. Anything else aborts.
NAME_VERBS = ("fix:", "keep", "defer: round-b", "defer: ingredient-note", "defer: heading",
              "group: Optional")
UNTOUCHED = ("keep", "defer: round-b", "defer: ingredient-note")
# The row file's actions, and what each one writes.
ROW_ACTIONS = {"footnote_to_note", "delete_step", "strip_footnote_marker", "strip_author_letter",
               "strip_author_number", "capitalize_after_heading", "heading_section",
               "note_label_to_title_beyond_the_list"}


class BadDecision(Exception):
    """The decision file itself is wrong, which is not the same as the pass failing."""


# --------------------------------------------------------------------------------------------- #
# the decision files
# --------------------------------------------------------------------------------------------- #

def read_decisions():
    for path in (LEVELS_CSV, NAMES_CSV, ROWS_CSV):
        if not path.is_file():
            raise BadDecision(f"no decision file at {path}")
    with LEVELS_CSV.open(newline="") as fh:
        levels = list(csv.DictReader(fh))
    with NAMES_CSV.open(newline="") as fh:
        names = list(csv.DictReader(fh))
    with ROWS_CSV.open(newline="") as fh:
        rows = list(csv.DictReader(fh))

    for n, r in enumerate(levels, start=2):
        if (r.get("DECISION") or "").strip() not in ("section", "subheading"):
            raise BadDecision(f"{LEVELS_CSV.name} line {n}: DECISION is "
                              f"{r.get('DECISION')!r}, not section or subheading")
    for n, r in enumerate(names, start=2):
        d = (r.get("decision") or "").strip()
        if not d:
            raise BadDecision(f"{NAMES_CSV.name} line {n}: the decision column is empty")
        if not d.startswith("fix:") and d not in NAME_VERBS:
            raise BadDecision(f"{NAMES_CSV.name} line {n}: {d!r} is not in the vocabulary "
                              f"({', '.join(NAME_VERBS)})")
        if d.startswith("fix:") and not d[4:].strip():
            raise BadDecision(f"{NAMES_CSV.name} line {n}: fix: with no text after it")
    for n, r in enumerate(rows, start=2):
        if (r.get("action") or "").strip() not in ROW_ACTIONS:
            raise BadDecision(f"{ROWS_CSV.name} line {n}: {r.get('action')!r} is not an action this "
                              f"pass knows ({', '.join(sorted(ROW_ACTIONS))})")
    return levels, names, rows


# --------------------------------------------------------------------------------------------- #
# provenance: which headings a lift CREATED
# --------------------------------------------------------------------------------------------- #

def author_section_inserts():
    """The inserted headings that are the AUTHOR'S OWN, recorded rather than guessed."""
    out = set()
    with (REPAIRS / "round-a-fix-decisions-2026-10-01.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("action") or "").strip() == "insert_section_before":
                out.add((r["recipe_id"], (r.get("value") or "").strip()))
    return out


_LIFT_CSVS = ("step-leadin-labels-2026-09-30.csv", "step-dash-labels-2026-09-30.csv")


def _norm_label(text):
    return " ".join((text or "").strip().rstrip(":").split()).casefold()


def reviewed_lift_ids(steps_by_recipe):
    """The heading rows the 2026-09-30 review recorded as lifts -> their ids.

    ⚠️ THE CSV NAMES THE STEP, NOT THE HEADING. A lift INSERTS a new heading row above the step and
    leaves the step's own id alone with the label removed, so `step_row_id` is the STEP. Matching on
    that id alone finds 0 headings out of 263. The heading is the nearest row ABOVE that step whose
    text is the label.

    ⚠️ AND THIS IS A CROSS-CHECK, NOT THE RULE. It covers 104 of the 126 lifts, because the other 22
    were lifted by RULE after that candidate list was reviewed. It is here to hold the id test to
    evidence of a different kind, so a partial answer is exactly what is wanted."""
    at = {}
    for steps in steps_by_recipe.values():
        for i, s in enumerate(steps):
            at[s["id"]] = (steps, i)
    out = set()
    for name in _LIFT_CSVS:
        path = REPAIRS / name
        if not path.is_file():
            raise BadDecision(f"no lift record at {path}, so the id test cannot be cross-checked")
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("DECISION_make_heading_yes_no") or "").strip().lower() != "yes":
                    continue
                found = at.get(int(r["step_row_id"]))
                if found is None:
                    continue                       # the step row is gone, which is not this check's
                steps, i = found                   # business to judge
                for j in range(i - 1, -1, -1):
                    if steps[j]["is_heading"]:
                        if _norm_label(steps[j]["text"]) == _norm_label(r["label"]):
                            out.add(steps[j]["id"])
                        break
                    break
    return out


def lifted_heading_ids(steps_by_recipe):
    """Heading rows a lift CREATED -> their ids.

    ⚠️ A LIFT INSERTS A ROW. A conversion changes an existing step row in place, and an author's own
    heading arrived as one. So the question is which heading rows did not exist before the lift
    passes ran, and the answer is on the rows: every inserted row's id is above every ordinary step's,
    because the lifts ran after all content was imported. Measured on live: ordinary steps run to
    5972 and the 127 inserted headings are 5973 to 6099, with no ordinary step among them.
    ⚠️ THE ONE EXCEPTION IS RECORDED, NOT INFERRED. brioche-bread's "Baking" is a new row and is the
    author's own section, recovered from the source ld+json by the 2026-10-01 round. It is in that
    round's decision file, which is where this reads it from."""
    allrows = [s for steps in steps_by_recipe.values() for s in steps]
    plain = [s["id"] for s in allrows if not s["is_heading"]]
    if not plain:
        return set()
    max_plain = max(plain)
    author_own = author_section_inserts()
    derived = {s["id"] for s in allrows
               if s["is_heading"] and s["id"] > max_plain
               and (s["recipe_id"], s["text"]) not in author_own}
    # ⚠️ THE ID TEST IS CROSS-CHECKED AGAINST EVIDENCE THAT IS NOT IDS, BECAUSE THE WHOLE HEADING
    #    RULE RESTS ON IT. "Every inserted heading has an id above every ordinary step" is true of
    #    this corpus and is not a law. One step row added after the lifts raises max_plain, and the
    #    lifted headings below it drop out of `derived` and start being treated as author-written,
    #    which does not fail loudly: it stops promoting them AND makes them parents that demote the
    #    headings under them. An earlier version of this guard compared ids against each other and
    #    was VACUOUS on exactly that case, which a test found by constructing it.
    #    The 104 lifts a person reviewed in 2026-09-30 are evidence of a different kind, so they are
    #    what the id test is held to.
    missing = reviewed_lift_ids(steps_by_recipe) - derived
    if missing:
        raise BadDecision(
            f"provenance cannot be read off the row ids on this database: "
            f"{len(missing)} heading(s) the 2026-09-30 review recorded as LIFTED do not come out of "
            f"the id test, so 'inserted' and 'author-written' are no longer separable by id. An "
            f"ordinary step row added after the lifts does this. First few: {sorted(missing)[:5]}")
    return derived


def levels_the_rule_wants(ic, steps_by_recipe):
    """{step id: the level the rule says} for every LIFTED heading."""
    lifted = lifted_heading_ids(steps_by_recipe)
    want = {}
    for steps in steps_by_recipe.values():
        author_above = False
        for s in steps:
            if not s["is_heading"]:
                continue
            if s["id"] not in lifted:
                author_above = True            # never changed, so the parents are given not derived
                continue
            want[s["id"]] = ic.label_level(s["text"], section_above=author_above)
    return want


# --------------------------------------------------------------------------------------------- #
# reading the database
# --------------------------------------------------------------------------------------------- #

def _load(s, sqlalchemy):
    steps = collections.OrderedDict()
    for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, position, is_heading, heading_level, text FROM recipe_steps "
            "ORDER BY recipe_id, position")).mappings():
        steps.setdefault(r["recipe_id"], []).append(dict(r))
    ings = collections.OrderedDict()
    for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, position, is_heading, label, raw_text, heading "
            "FROM recipe_ingredients ORDER BY recipe_id, position")).mappings():
        ings.setdefault(r["recipe_id"], []).append(dict(r))
    notes = [dict(r) for r in s.execute(sqlalchemy.text(
        "SELECT id, recipe_id, position, kind, title, text, step_id FROM recipe_notes "
        "ORDER BY recipe_id, position")).mappings()]
    return steps, ings, notes


# --------------------------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------------------------- #

def plan(ic, steps_by_recipe, ings_by_recipe, notes, levels, names, rowdecs):
    """Everything this pass would write -> ({recipe: [write]}, [noop], [refusal])."""
    todo = collections.OrderedDict()
    noop, refused = [], []
    step_at = {s["id"]: s for steps in steps_by_recipe.values() for s in steps}
    ing_at = {r["id"]: r for rows in ings_by_recipe.values() for r in rows}
    note_at = {n["id"]: n for n in notes}

    def add(recipe, write):
        todo.setdefault(recipe, []).append(write)

    # ---- part 1: heading levels ----------------------------------------------------------------
    want = levels_the_rule_wants(ic, steps_by_recipe)
    for r in levels:
        sid = int(r["step_id"])
        decided = ic.SECTION if r["DECISION"].strip() == "section" else ic.SUBHEADING
        row = step_at.get(sid)
        if row is None:
            refused.append(f"{LEVELS_CSV.name}: step {sid} is gone")
            continue
        if row["text"] != r["text"]:
            refused.append(f"{LEVELS_CSV.name}: step {sid} now reads {row['text']!r}, and the "
                           f"decision was made about {r['text']!r}")
            continue
        if sid not in want:
            refused.append(f"{LEVELS_CSV.name}: step {sid} ({row['text']!r}) is not a lifted "
                           f"heading, so its level is not this round's to set")
            continue
        if want[sid] != decided:
            refused.append(f"{LEVELS_CSV.name}: step {sid} ({row['text']!r}) is decided "
                           f"{decided} and the rule now says {want[sid]}")
            continue
        if row["heading_level"] == decided:
            noop.append(f"step {sid} is already level {decided}")
            continue
        add(row["recipe_id"], {"part": 1, "what": "heading_level", "id": sid,
                              "was": row["heading_level"], "now": decided, "text": row["text"]})

    # ---- part 2: ingredient names --------------------------------------------------------------
    for r in names:
        d = r["decision"].strip()
        rid, row_id = r["recipe_id"], int(r["row_id"])
        row = ing_at.get(row_id)
        if d in UNTOUCHED:
            continue
        if row is None:
            refused.append(f"{NAMES_CSV.name}: ingredient row {row_id} is gone")
            continue
        if row["recipe_id"] != rid:
            refused.append(f"{NAMES_CSV.name}: row {row_id} belongs to {row['recipe_id']!r}, "
                           f"and the decision names {rid!r}")
            continue
        if d.startswith("fix:"):
            # ⚠️ APPLIED LITERALLY. Andy's text, not recomputed: 54 of the 71 change more than the
            #    first word, which is a decision about every word in the name and not something the
            #    rule can reproduce. Asking the rule here would refuse all 54.
            now = d[4:].strip()
            if row["label"] == now:
                noop.append(f"ingredient {row_id} already reads {now!r}")
                continue
            if row["label"] != r["name"]:
                refused.append(f"{NAMES_CSV.name}: ingredient {row_id} now reads "
                               f"{row['label']!r}, and the decision was made about {r['name']!r}")
                continue
            add(rid, {"part": 2, "what": "ing_label", "id": row_id, "was": row["label"],
                      "now": now})
        elif d == "defer: heading":
            if row["is_heading"]:
                noop.append(f"ingredient {row_id} is already a heading")
                continue
            if row["label"] != r["name"]:
                refused.append(f"{NAMES_CSV.name}: ingredient {row_id} now reads "
                               f"{row['label']!r}, and the decision was made about {r['name']!r}")
                continue
            add(rid, {"part": 2, "what": "ing_to_heading", "id": row_id, "text": row["label"]})
        elif d == "group: Optional":
            continue                           # handled as a RULE over the recipe, just below

    # the Optional runs, stated over every recipe rather than over the two decided rows
    decided_optional = {int(r["row_id"]) for r in names
                        if r["decision"].strip() == "group: Optional"}
    found_optional = set()
    for rid, rows in ings_by_recipe.items():
        groups = ic.optional_ingredient_groups(
            [{"id": r["id"], "is_heading": r["is_heading"],
              "text": r["label"] or r["raw_text"]} for r in rows])
        for g in groups:
            found_optional |= {i for i, _t in g["lines"]}
            if g["heading_id"] is None:
                add(rid, {"part": 2, "what": "insert_ing_heading", "at": g["at"],
                          "text": ic.OPTIONAL_HEADING_TEXT,
                          "before_id": g["lines"][0][0]})
            for row_id, now in g["lines"]:
                add(rid, {"part": 2, "what": "ing_label", "id": row_id,
                          "was": ing_at[row_id]["label"], "now": now})
    # ⚠️ A SUBSET, NOT AN EQUALITY, AND THAT IS WHAT MAKES A SECOND RUN A NO-OP. After the first run
    #    no line carries the prefix any more, so the rule finds NOTHING and an equality against the
    #    decision file aborted a pass that had nothing left to do. The direction that matters is the
    #    other one: a line the RULE moves that nobody decided is a surprise and is refused. A decided
    #    line the rule no longer finds has to be accounted for, so it is checked for being done.
    if not found_optional <= decided_optional:
        refused.append(f"the Optional rule moves {sorted(found_optional - decided_optional)}, "
                       f"which the decision file does not name")
    for row_id in sorted(decided_optional - found_optional):
        row = ing_at.get(row_id)
        if row is None:
            refused.append(f"{NAMES_CSV.name}: ingredient row {row_id} is gone")
            continue
        above = [r for r in ings_by_recipe[row["recipe_id"]] if r["position"] < row["position"]]
        under_one = any(r["is_heading"] and (r["heading"] or r["raw_text"] or "").strip().lower()
                        == ic.OPTIONAL_HEADING_TEXT.lower() for r in above[-3:])
        if under_one:
            noop.append(f"ingredient {row_id} already sits under an Optional heading")
        else:
            refused.append(f"{NAMES_CSV.name}: ingredient {row_id} no longer opens 'Optional:' and "
                           f"no Optional heading sits above it, so the rule cannot account for it")

    # ---- parts 3, 4 and 6: the row decisions ---------------------------------------------------
    for r in rowdecs:
        action, rid = r["action"].strip(), r["recipe_id"]
        row_id = int(r["row_id"]) if (r.get("row_id") or "").strip() else None
        if action == "heading_section":
            continue                           # part 1 owns the level; this row is the record of why
        if action == "note_label_to_title_beyond_the_list":
            continue                           # part 5 owns it; this row is the record and the flag
        if action == "footnote_to_note":
            # ⚠️ THE APPLIED STATE IS READ FIRST, BEFORE THE STEP IS LOOKED FOR, because this round
            #    DELETES that step. A second run cannot find it, let alone the step above it, so
            #    asking about the rows first aborted a pass with nothing left to do.
            if any(n["recipe_id"] == rid and n["text"] == r["value"] and n["step_id"]
                   for n in notes):
                noop.append(f"the footnote is already a note linked to a step on {rid}")
                continue
            # ⚠️ .get, NOT [], because a database that does not hold this recipe has to be REFUSED
            #    rather than crashed on. tests/test_lockstep_guard.py runs every pass against a small
            #    fixture, and a KeyError there is indistinguishable from the pass being broken.
            prev = _step_before(steps_by_recipe.get(rid, []), row_id)
            if prev is None:
                refused.append(f"{ROWS_CSV.name}: step {row_id} has no step above it to be the "
                               f"footnote of")
                continue
            got = ic.footnote_step_plan(prev["text"], step_at[row_id]["text"]) \
                if row_id in step_at else None
            if got is None:
                refused.append(f"{ROWS_CSV.name}: step {row_id} does not read as the footnote of "
                               f"step {prev['id']} any more")
                continue
            add(rid, {"part": 3, "what": "footnote_note", "step_id": prev["id"],
                      "text": r["value"], "kind": ic.note_kind(r["value"]) or "notes"})
        elif action == "delete_step":
            if row_id not in step_at:
                noop.append(f"step {row_id} is already gone")
                continue
            add(rid, {"part": 3, "what": "delete_step", "id": row_id,
                      "text": step_at[row_id]["text"]})
        elif action == "strip_footnote_marker":
            row = step_at.get(row_id)
            if row is None:
                refused.append(f"{ROWS_CSV.name}: step {row_id} is gone")
                continue
            now = ic.strip_footnote_markers(row["text"])
            if now == row["text"]:
                noop.append(f"step {row_id} carries no footnote marker")
                continue
            add(rid, {"part": 4, "what": "step_text", "id": row_id, "was": row["text"],
                      "now": now, "why": "the footnote marker came off"})
        elif action == "strip_author_letter":
            continue                           # part 6 owns it, stated over the run
        elif action in ("strip_author_number", "capitalize_after_heading"):
            continue                           # part 6 owns it, stated over the recipe

    # ---- part 5: note labels -------------------------------------------------------------------
    for n in notes:
        got = ic.note_label_plan(n["text"])
        if got is None:
            continue
        body = ic.capitalize_first_visible(got.text)
        if got.verdict == "restates the kind":
            if n["text"] == body:
                noop.append(f"note {n['id']} has no label on it")
                continue
            add(n["recipe_id"], {"part": 5, "what": "note_strip", "id": n["id"],
                                 "was": n["text"], "now": body, "label": got.label})
        else:
            if n["title"] == got.title and n["text"] == body:
                noop.append(f"note {n['id']} is already titled {got.title!r}")
                continue
            if n["title"]:
                refused.append(f"note {n['id']} already carries a title {n['title']!r} and the "
                               f"rule wants {got.title!r}")
                continue
            add(n["recipe_id"], {"part": 5, "what": "note_title", "id": n["id"],
                                 "was": n["text"], "now": body, "title": got.title,
                                 "label": got.label})

    # ---- part 6: the author's lettering, numbering and the capital after a heading --------------
    for rid, steps in steps_by_recipe.items():
        plain = [s for s in steps if not s["is_heading"]]
        lettered, runs = ic.strip_author_letters([s["text"] for s in plain])
        for s, now in zip(plain, lettered):
            if now != s["text"]:
                add(rid, {"part": 6, "what": "step_text", "id": s["id"], "was": s["text"],
                          "now": now, "why": "the author's own lettering came off"})
        # the numbers, read per section, over the text the lettering pass leaves
        after_letters = {s["id"]: now for s, now in zip(plain, lettered)}
        numbered = ic.strip_author_numbers_by_section(
            [(bool(s["is_heading"]), after_letters.get(s["id"], s["text"])) for s in steps])
        for s, now in zip(steps, numbered):
            if s["is_heading"]:
                continue
            was = after_letters.get(s["id"], s["text"])
            if now != was:
                add(rid, {"part": 6, "what": "step_text", "id": s["id"], "was": was, "now": now,
                          "why": "the author's numbering restarts under a heading"})
        # and the capital, over the text both passes leave
        latest = {s["id"]: now for s, now in zip(steps, numbered)}
        for i, s in enumerate(steps):
            if s["is_heading"]:
                continue
            prev = steps[i - 1] if i else None
            if ic.continues_the_line_above(latest.get(prev["id"], prev["text"]) if prev else None,
                                           bool(prev and prev["is_heading"])):
                continue
            was = latest[s["id"]]
            now = ic.capitalize_first_visible(was)
            if now != was:
                add(rid, {"part": 6, "what": "step_text", "id": s["id"], "was": was, "now": now,
                          "why": "a step after a heading is not a continuation"})

    # ⚠️ ONE ROW, ONE FINAL VALUE. Part 6 can produce two writes for one step (its number comes off
    #    and then its first letter is capitalized), which as two UPDATEs is fine and as two baseline
    #    patches is not: the second would look for text the first has already replaced. Collapsed
    #    here, where the chain is visible, rather than in the writer.
    for recipe, writes in todo.items():
        todo[recipe] = _collapse_step_text(writes)
    return todo, noop, refused


def _step_before(steps, step_id):
    for i, s in enumerate(steps):
        if s["id"] == step_id:
            return next((x for x in reversed(steps[:i]) if not x["is_heading"]), None)
    return None


def _collapse_step_text(writes):
    """Several step_text writes on one row -> one, from its first `was` to its last `now`."""
    out, chain = [], collections.OrderedDict()
    for w in writes:
        if w["what"] != "step_text":
            out.append(w)
            continue
        if w["id"] in chain:
            first = chain[w["id"]]
            first["now"] = w["now"]
            first["why"] = f"{first['why']}, then {w['why']}"
        else:
            chain[w["id"]] = dict(w)
    return out + list(chain.values())


# --------------------------------------------------------------------------------------------- #
# the write
# --------------------------------------------------------------------------------------------- #

def _state(s, sqlalchemy, app, rid):
    cur = app.serialize_recipe_content(s, rid)
    got = s.execute(sqlalchemy.text(
        "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
        {"r": rid}).scalar_one_or_none()
    return {"byte_equal": got is not None and cur == got,
            "marks": json.dumps(app._recipe_annotations(s, rid), sort_keys=True)}


def _entry(doc, key, row_id):
    for e in doc.get(key) or []:
        if e.get("id") == row_id:
            return e
    return None


def _write_recipe(s, sqlalchemy, rid, writes, doc):
    """Apply one recipe's writes to the rows AND to its baseline. -> baseline touched?"""
    moved = False
    ex = lambda q, **kw: s.execute(sqlalchemy.text(q), kw)

    for w in writes:
        if w["what"] == "heading_level":
            ex("UPDATE recipe_steps SET heading_level=:l WHERE id=:i", l=w["now"], i=w["id"])
            if doc is None:
                continue
            e = _entry(doc, "steps", w["id"])
            if e is None:
                raise RuntimeError(f"{rid}: the baseline carries no step {w['id']}")
            # ⚠️ THE KEY IS PRESENT ONLY FOR A LEVEL 2. Writing 1 would leave bytes no current
            #    serialization produces, and the recipe would leave the byte-equal set.
            if w["now"] == 2:
                e["heading_level"] = 2
            else:
                e.pop("heading_level", None)
            moved = True

        elif w["what"] == "step_text":
            ex("UPDATE recipe_steps SET text=:t WHERE id=:i", t=w["now"], i=w["id"])
            if doc is None:
                continue
            e = _entry(doc, "steps", w["id"])
            if e is None:
                raise RuntimeError(f"{rid}: the baseline carries no step {w['id']}")
            e["text"] = w["now"]
            moved = True

        elif w["what"] == "ing_label":
            ex("UPDATE recipe_ingredients SET label=:t WHERE id=:i", t=w["now"], i=w["id"])
            if doc is None:
                continue
            e = _entry(doc, "ingredients", w["id"])
            if e is None:
                raise RuntimeError(f"{rid}: the baseline carries no ingredient {w['id']}")
            e["label"] = w["now"]
            moved = True

        elif w["what"] == "ing_to_heading":
            # ⚠️ ONLY is_heading MOVES. A heading converted from a line KEEPS every hidden column
            #    (app._ing_row_values), and `heading` stays NULL because the title IS the raw_text,
            #    which is how all 223 pre-052 heading rows are stored. So this writes exactly what a
            #    save through the editor would write, and nothing else.
            ex("UPDATE recipe_ingredients SET is_heading=1 WHERE id=:i", i=w["id"])
            if doc is None:
                continue
            e = _entry(doc, "ingredients", w["id"])
            if e is None:
                raise RuntimeError(f"{rid}: the baseline carries no ingredient {w['id']}")
            e["is_heading"] = 1
            moved = True

    # ---- the row-count changes, after the in-place edits -------------------------------------
    for w in [x for x in writes if x["what"] == "insert_ing_heading"]:
        at = s.execute(sqlalchemy.text(
            "SELECT position FROM recipe_ingredients WHERE id=:i"), {"i": w["before_id"]}).scalar_one()
        ex("UPDATE recipe_ingredients SET position=position+1 WHERE recipe_id=:r AND position>=:p",
           r=rid, p=at)
        new_id = s.execute(sqlalchemy.text(
            "INSERT INTO recipe_ingredients (recipe_id, position, is_heading, raw_text) "
            "VALUES (:r, :p, 1, :t) RETURNING id"), {"r": rid, "p": at, "t": w["text"]}).scalar_one()
        if doc is not None:
            for e in doc.get("ingredients") or []:
                if e.get("position") is not None and e["position"] >= at:
                    e["position"] += 1
            doc.setdefault("ingredients", []).append(
                {"id": new_id, "position": at, "is_heading": 1, "raw_text": w["text"],
                 "label": None, "note": None, "qty": None, "quantity": None, "unit": None,
                 "grams": None, "secondary_measure": None, "ingredient_id": None})
            doc["ingredients"].sort(key=lambda e: (e.get("position") is None, e.get("position")))
            moved = True

    for w in [x for x in writes if x["what"] == "footnote_note"]:
        at = s.execute(sqlalchemy.text(
            "SELECT COALESCE(MAX(position)+1, 0) FROM recipe_notes WHERE recipe_id=:r"),
            {"r": rid}).scalar_one()
        ex("INSERT INTO recipe_notes (recipe_id, position, kind, text, step_id) "
           "VALUES (:r, :p, :k, :t, :s)",
           r=rid, p=at, k=w["kind"], t=w["text"], s=w["step_id"])
        # ⚠️ NO BASELINE WORK, AND NO recipe_notes_original EITHER. A note is outside
        #    recipe_snapshots.content, and the original table is the record of what the AUTHOR wrote
        #    in the notes field. These words were in the METHOD, so adding them there would claim the
        #    author put them in the notes.

    for w in [x for x in writes if x["what"] == "delete_step"]:
        at = s.execute(sqlalchemy.text(
            "SELECT position FROM recipe_steps WHERE id=:i"), {"i": w["id"]}).scalar_one()
        ex("DELETE FROM recipe_steps WHERE id=:i", i=w["id"])
        ex("UPDATE recipe_steps SET position=position-1 WHERE recipe_id=:r AND position>:p",
           r=rid, p=at)
        if doc is not None:
            doc["steps"] = [e for e in doc.get("steps") or [] if e.get("id") != w["id"]]
            for e in doc["steps"]:
                if e.get("position") is not None and e["position"] > at:
                    e["position"] -= 1
            moved = True

    for w in [x for x in writes if x["what"] in ("note_strip", "note_title")]:
        if w["what"] == "note_strip":
            ex("UPDATE recipe_notes SET text=:t WHERE id=:i", t=w["now"], i=w["id"])
        else:
            ex("UPDATE recipe_notes SET text=:t, title=:h WHERE id=:i",
               t=w["now"], h=w["title"], i=w["id"])
    return moved


def run(db, apply=False):
    import app
    import import_cleanup as ic
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    levels, names, rowdecs = read_decisions()
    print(f"  decisions read            : {len(levels)} levels, {len(names)} names, "
          f"{len(rowdecs)} rows")

    with app.orm_session() as s:
        steps_by_recipe, ings_by_recipe, notes = _load(s, sqlalchemy)
    todo, noop, refused = plan(ic, steps_by_recipe, ings_by_recipe, notes, levels, names, rowdecs)

    per_part = collections.Counter(w["part"] for ws in todo.values() for w in ws)
    print(f"  to write                  : {sum(len(w) for w in todo.values())} over "
          f"{len(todo)} recipe(s)")
    for part in sorted(per_part):
        print(f"      part {part}: {per_part[part]}")
    print(f"  already in place (no-op)  : {len(noop)}")
    print(f"  refused                   : {len(refused)}")
    for why in refused:
        print(f"      {why}")
    if refused:
        sys.exit("ABORT: a recorded decision no longer matches the row it was made about.")
    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return todo
    if not todo:
        print("  nothing to do. Every decision is already in place.")
        return todo

    before = {}
    with app.orm_session() as s:
        for rid in todo:
            before[rid] = _state(s, sqlalchemy, app, rid)

    for rid, writes in todo.items():
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            doc = json.loads(stored) if stored is not None else None
            try:
                moved = _write_recipe(s, sqlalchemy, rid, writes, doc)
            except RuntimeError as exc:
                s.rollback()
                sys.exit(f"ABORT on {rid}: {exc}")
            if moved and doc is not None:
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r "
                    "AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            now = _state(s, sqlalchemy, app, rid)
            if now["marks"] != before[rid]["marks"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: the annotation set moved, so nothing was written.\n"
                         f"  before={before[rid]['marks'][:300]}\n  after ={now['marks'][:300]}")
            if before[rid]["byte_equal"] and not now["byte_equal"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: it left the byte-equal set, so nothing was written.")
            s.commit()

    # ⚠️ THE LEVELS ARE RE-DERIVED AFTER EVERY PART HAS RUN, because part 6 can turn a step into a
    #    heading and a heading's level depends on what sits above it. Nothing in this round does, and
    #    this is what says so rather than a comment claiming it.
    with app.orm_session() as s:
        again, _i, _n = _load(s, sqlalchemy)
    want = levels_the_rule_wants(ic, again)
    drift = [(int(r["step_id"]), want.get(int(r["step_id"])))
             for r in levels
             if want.get(int(r["step_id"])) !=
             (ic.SECTION if r["DECISION"].strip() == "section" else ic.SUBHEADING)]
    if drift:
        sys.exit(f"ABORT after the write: {len(drift)} level(s) the rule now answers differently: "
                 f"{drift[:8]}")
    print(f"  WROTE {sum(len(w) for w in todo.values())} change(s) over {len(todo)} recipe(s) "
          f"-> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
    print(f"  all {len(levels)} heading levels still read the same after every part ran")
    return todo


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply)


if __name__ == "__main__":
    main()
