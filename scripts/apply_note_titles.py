#!/usr/bin/env python3.13
"""apply_note_titles.py - give the corpus's notes their titles, from Andy's recorded decisions.

Reads two COMMITTED decision files, because a pass that cannot be re-run from a fresh clone is a
hand edit with more steps:

    docs/data-repairs/note-titles-2026-10-05.csv     27 notes that open with a short label
    docs/data-repairs/emphasis-marks-2026-10-05.csv  all 30 wrapping emphasis marks in the corpus

⚠️ THE DECISION COLUMN IS THE INPUT AND A BLANK ONE STOPS THE RUN. Both files carry a DECISION
Andy filled in and a REASON explaining it. A row with no decision, or with a word this does not
know, aborts before anything is written. A pass that skipped the rows it could not read would
apply a silent subset and report success.

⚠️ AND THE RULE HAS TO STILL AGREE. Every row is re-read through import_cleanup.note_title_plan
against the text the database holds NOW, and a row whose text has moved since the decision was
made aborts rather than being written from a stale reading. The decision was made about a
sentence, not about a row id.

⚠️ NOTES ARE A PLAYGROUND, SO 34 OF THE 36 ROWS NEED NO BASELINE AT ALL. Andy's ruling: a note
takes no part in "your changes" and costs a recipe nothing, which is why neither the note rows nor
the derived column are in recipe_snapshots.content and snapshot_diff does not compare them. Titling
27 notes mints no annotation entry.

⚠️ THE TWO INGREDIENT HEADINGS ARE A DIFFERENT MATTER AND GO IN LOCKSTEP. recipe_ingredients
.raw_text IS baseline content, so brioche-cinnamon-rolls' rows 9213 and 9217 are patched together
with their reason='original' entries in ONE transaction, or that recipe leaves the byte-equal set
and the page reports a change the cook never made.

⚠️ recipe_notes_original IS NEVER TOUCHED. It is the only record of the author's own words, written
once by notes_to_rows.py, read by nothing on the page and unknown to snapshot_diff. A playground is
only safe if there is a way back.

⚠️ AND THE RETIRED recipes.notes COLUMN IS LEFT ALONE, DELIBERATELY. It is a derived copy of the
note rows, 7 of the emphasis survey's 30 marks live only in it, and Andy's decision on all 7 is
`derived`. Rewriting it here would be a second answer to what a note says.

⚠️ THE GATE PROVES ITSELF BEFORE THE COMMIT, per recipe, inside that recipe's own transaction. A
gate that ran afterwards would be a post-mortem on data already on disk.

⚠️ A SECOND RUN IS A NO-OP. Every decision is checked against what is already in place during the
PLANNING phase, which is what makes the dry run a faithful preview of the real run.
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live                                        # noqa: E402

REPAIRS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data-repairs"
TITLES_CSV = REPAIRS / "note-titles-2026-10-05.csv"
MARKS_CSV = REPAIRS / "emphasis-marks-2026-10-05.csv"

# The whole vocabulary. A DECISION outside this aborts.
VERBS = {"title", "no", "label", "strip", "merge-title-into-next", "keep", "derived"}


class BadDecision(Exception):
    """The decision file itself is wrong, which is not the same as the pass failing."""


def parse_decision(raw):
    """A DECISION cell -> (verbs, title or None, kind or None, flag or None).

    The vocabulary is `title`, `title: <text>`, `no`, `label`, `strip`, `keep`, `derived` and
    `merge-title-into-next`, joined with "; ", each optionally followed by "; kind=<kind>" or
    "; flag <name>"."""
    text = (raw or "").strip()
    if not text:
        raise BadDecision("the DECISION column is empty")
    verbs, title, kind, flag = set(), None, None, None
    for part in [p.strip() for p in text.split(";")]:
        if not part:
            raise BadDecision(f"{text!r} has an empty part")
        if part.startswith("title:"):
            verbs.add("title")
            title = part[len("title:"):].strip()
            if not title:
                raise BadDecision(f"{text!r} names a title and gives none")
        elif part.startswith("kind="):
            kind = part[len("kind="):].strip()
        elif part.startswith("flag "):
            flag = part[len("flag "):].strip()
        elif part in VERBS:
            verbs.add(part)
        else:
            raise BadDecision(f"{text!r} uses {part!r}, which is not in the vocabulary "
                              f"({', '.join(sorted(VERBS))}, title: <text>, kind=<kind>, flag <x>)")
    if not verbs:
        raise BadDecision(f"{text!r} names no action")
    return verbs, title, kind, flag


def read_decisions():
    """Every row of both files, parsed. A blank or unknown DECISION raises here, before the pass
    has opened a database."""
    rows = []
    for path, id_col, where_col in ((TITLES_CSV, "note_id", None), (MARKS_CSV, "id", "where")):
        if not path.is_file():
            raise BadDecision(f"no decision file at {path}")
        with path.open(newline="") as fh:
            got = list(csv.DictReader(fh))
        for n, r in enumerate(got, start=2):
            where = (r.get(where_col) or "note") if where_col else "note"
            try:
                verbs, title, kind, flag = parse_decision(r.get("DECISION"))
            except BadDecision as e:
                raise BadDecision(f"{path.name} line {n}: {e}") from None
            rows.append({"file": path.name, "line": n, "where": where, "recipe": r["recipe"],
                         "row_id": r[id_col], "decision": r["DECISION"].strip(),
                         "verbs": verbs, "title": title, "kind": kind, "flag": flag,
                         "reason": r.get("REASON", ""),
                         # the label the review list read, which is what a bare `title` means. It is
                         # how a second run recognises its own work: the title comes OFF the text,
                         # so the rule can no longer tell you what it was.
                         "candidate": (r.get("candidate_title") or "").strip()})
    # ⚠️ A CHECK THAT READ NOTHING FAILS. A truncated decision file would otherwise make the pass
    #    report success having applied a subset, which is how three committed records were reduced
    #    to their header lines during an earlier round and nobody noticed until a diff was read.
    if not rows:
        raise BadDecision(f"neither {TITLES_CSV.name} nor {MARKS_CSV.name} holds a single row")
    return rows


def _plan_one(ic, row, notes, ings):
    """One decision against the database as it is now -> (action, detail) or ("REFUSE", why).

    action is one of: title, label, strip, merge, ing_strip, noop, skip.
    """
    verbs, want_title, want_kind = row["verbs"], row["title"], row["kind"]

    # Rows this round does not touch at all, and says so rather than staying quiet about them.
    if "derived" in verbs:
        return "skip", "the retired recipes.notes copy, which this round leaves alone"
    if "keep" in verbs:
        return "skip", "in-sentence emphasis or a footnote marker, left as written"

    if row["where"] != "note":
        rid = int(row["row_id"])
        got = ings.get(rid)
        if got is None:
            return "REFUSE", f"no ingredient row {rid}"
        if got["recipe_id"] != row["recipe"]:
            return "REFUSE", f"ingredient {rid} is on {got['recipe_id']}, not {row['recipe']}"
        stripped, marks = ic.strip_wrapping_marks(got["raw_text"])
        if marks is None:
            if got["raw_text"] == (want_title or got["raw_text"]):
                return "noop", "already stripped"
            return "noop", "already stripped"
        return "ing_strip", {"id": rid, "recipe": row["recipe"], "raw_text": stripped,
                             "was": got["raw_text"], "marks": marks}

    nid = int(row["row_id"])
    note = notes.get(nid)
    if note is None:
        if "merge-title-into-next" in verbs:
            return "noop", "already merged and removed"
        return "REFUSE", f"no note {nid}"
    if note["recipe_id"] != row["recipe"]:
        return "REFUSE", f"note {nid} is on {note['recipe_id']}, not {row['recipe']}"

    plan = ic.note_title_plan(note["text"])

    if "merge-title-into-next" in verbs:
        # The rule declines this shape on purpose: no rule reading one row can see that the body
        # was split into the next one. So the decision carries it, and what is checked is that the
        # row still IS that shape and the row it moves onto is still there and still untitled.
        if plan.verdict != "unclear" or not plan.marks:
            return "REFUSE", (f"note {nid} is no longer a wrapped title line with nothing under "
                              f"it (the rule now says {plan.verdict!r})")
        nxt = min((o for o in notes.values()
                   if o["recipe_id"] == note["recipe_id"] and o["position"] > note["position"]),
                  key=lambda o: o["position"], default=None)
        if nxt is None:
            return "REFUSE", f"note {nid} has no next note to move its title onto"
        if nxt["title"]:
            return "REFUSE", f"note {nxt['id']} already carries the title {nxt['title']!r}"
        return "merge", {"id": nid, "recipe": row["recipe"], "title": plan.text,
                         "onto": nxt["id"], "position": note["position"]}

    if "no" in verbs:
        if plan.verdict != "no title":
            return "REFUSE", f"note {nid}: the rule now says {plan.verdict!r}, not 'no title'"
        if note["title"]:
            return "REFUSE", f"note {nid} carries a title {note['title']!r} and the decision is no"
        return "noop", "no title, and it has none"

    if "label" in verbs:
        if plan.verdict != "label":
            return "REFUSE", f"note {nid}: the rule now says {plan.verdict!r}, not 'label'"
        kind = want_kind or plan.kind
        if plan.kind != kind:
            return "REFUSE", f"note {nid}: the rule says kind {plan.kind!r}, the decision {kind!r}"
        want_text = plan.text if "strip" in verbs else note["text"]
        if note["kind"] == kind and note["text"] == want_text and not note["title"]:
            return "noop", f"already a {kind} label"
        return "label", {"id": nid, "recipe": row["recipe"], "kind": kind, "text": want_text,
                         "was_kind": note["kind"], "marks": plan.marks}

    if "title" in verbs:
        # ⚠️ THE APPLIED STATE IS READ BEFORE THE RULE IS ASKED, AND THAT WAS FOUND BY RUNNING THE
        #    PASS TWICE. Applying the decision DESTROYS the evidence the rule reads: the title comes
        #    off the front of the text, so a second run hands note_title_plan a body with no label
        #    in it and is told "no title". Asking the rule first refused all 27 titles on a database
        #    this pass had just written correctly, which is the opposite of a no-op.
        expected = want_title or ic._title_case(row["candidate"])
        if note["title"] and (not expected or note["title"] == expected):
            return "noop", f"already titled {note['title']!r}"
        if plan.verdict != "title":
            return "REFUSE", f"note {nid}: the rule now says {plan.verdict!r}, not 'title'"
        title = want_title or plan.title
        if expected and title != expected:
            return "REFUSE", (f"note {nid}: the decision names {expected!r} and the rule now reads "
                              f"{title!r}")
        if plan.title != title:
            return "REFUSE", (f"note {nid}: the rule reads the title as {plan.title!r} and the "
                              f"decision says {title!r}")
        kind = want_kind or note["kind"]
        if want_kind and plan.kind != want_kind:
            return "REFUSE", (f"note {nid}: the decision sets kind {want_kind!r} and the rule "
                              f"reads {plan.kind!r}")
        if note["title"] == title and note["text"] == plan.text and note["kind"] == kind:
            return "noop", "already titled"
        return "title", {"id": nid, "recipe": row["recipe"], "title": title, "text": plan.text,
                         "kind": kind, "was_kind": note["kind"], "marks": plan.marks}

    if "strip" in verbs:
        if plan.marks is None:
            return "noop", "already stripped"
        if plan.text == note["text"]:
            return "noop", "already stripped"
        return "strip", {"id": nid, "recipe": row["recipe"], "text": plan.text,
                         "marks": plan.marks}

    return "REFUSE", f"note {nid}: {row['decision']!r} names no action this pass can take"


def _state(s, sqlalchemy, app, rid):
    """What the gate is stated against: this recipe's annotation ENTRIES and whether it is
    byte-equal to its baseline. The entries, never their count."""
    cur = app.serialize_recipe_content(s, rid)
    got = s.execute(sqlalchemy.text(
        "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
        {"r": rid}).scalar_one_or_none()
    return {"byte_equal": got is not None and cur == got,
            "marks": json.dumps(app._recipe_annotations(s, rid), sort_keys=True)}


def run(db, apply=False):
    import app
    import import_cleanup as ic
    import models
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    decisions = read_decisions()
    per_file = collections.Counter(r["file"] for r in decisions)
    print(f"  decisions read            : {len(decisions)}")
    for name in (TITLES_CSV.name, MARKS_CSV.name):
        print(f"      {per_file.get(name, 0):<4} {name}")

    with app.orm_session() as s:
        notes = {r["id"]: dict(r) for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, position, kind, text, title FROM recipe_notes")).mappings()}
        ings = {r["id"]: dict(r) for r in s.execute(sqlalchemy.text(
            "SELECT id, recipe_id, raw_text FROM recipe_ingredients "
            "WHERE raw_text IS NOT NULL")).mappings()}

    todo, noop, skip, refused = [], [], [], []
    for row in decisions:
        action, detail = _plan_one(ic, row, notes, ings)
        if action == "REFUSE":
            refused.append((row, detail))
        elif action == "noop":
            noop.append((row, detail))
        elif action == "skip":
            skip.append((row, detail))
        else:
            todo.append((action, row, detail))

    print(f"  to write                  : {len(todo)}")
    for action, row, d in todo:
        extra = (f"title={d.get('title')!r}" if d.get("title") else
                 f"kind={d.get('kind')!r}" if d.get("kind") else
                 f"marks={d.get('marks')!r}")
        print(f"      {action:9s} {d['recipe'][:30]:30s} row {d['id']:<6} {extra}")
    print(f"  already in place (no-op)  : {len(noop)}")
    for row, why in noop:
        print(f"      {row['where']:4s} {row['row_id']:<6} {row['recipe'][:30]:30s} {why}")
    print(f"  not this round's business : {len(skip)}")
    for row, why in skip:
        print(f"      {row['where']:4s} {str(row['row_id'])[:30]:30s} {why}")
    print(f"  refused                   : {len(refused)}")
    for row, why in refused:
        print(f"      {row['file']} line {row['line']}: {why}")

    if refused:
        sys.exit("ABORT: a recorded decision no longer matches the row it was made about.")
    if not apply:
        print("  DRY RUN. Nothing written. Pass --apply to write.")
        return todo
    if not todo:
        print("  nothing to do. Every decision is already in place.")
        return todo

    touched = sorted({d["recipe"] for _a, _r, d in todo})
    before = {}
    with app.orm_session() as s:
        for rid in touched:
            before[rid] = _state(s, sqlalchemy, app, rid)

    for rid in touched:
        mine = [(a, d) for a, _r, d in todo if d["recipe"] == rid]
        with app.orm_session() as s:
            stored = s.execute(sqlalchemy.text(
                "SELECT content FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'"),
                {"r": rid}).scalar_one_or_none()
            doc = json.loads(stored) if stored is not None else None
            baseline_moved = False
            for action, d in mine:
                if action == "title":
                    s.execute(sqlalchemy.text(
                        "UPDATE recipe_notes SET title=:t, text=:x, kind=:k WHERE id=:n"),
                        {"t": d["title"], "x": d["text"], "k": d["kind"], "n": d["id"]})
                elif action == "label":
                    s.execute(sqlalchemy.text(
                        "UPDATE recipe_notes SET kind=:k, text=:x WHERE id=:n"),
                        {"k": d["kind"], "x": d["text"], "n": d["id"]})
                elif action == "strip":
                    s.execute(sqlalchemy.text("UPDATE recipe_notes SET text=:x WHERE id=:n"),
                              {"x": d["text"], "n": d["id"]})
                elif action == "merge":
                    s.execute(sqlalchemy.text("UPDATE recipe_notes SET title=:t WHERE id=:n"),
                              {"t": d["title"], "n": d["onto"]})
                    s.execute(sqlalchemy.text("DELETE FROM recipe_notes WHERE id=:n"),
                              {"n": d["id"]})
                    # ⚠️ THE GAP IS CLOSED AND THE SURVIVORS GO OUT OF THE WAY FIRST.
                    #    recipe_notes carries UNIQUE (recipe_id, position), so renumbering in place
                    #    collides the moment one row takes another's slot. Negative positions in
                    #    one pass, final positions in a second, which is the dance write_plan_ahead
                    #    does for waits and storage.
                    left = [r["id"] for r in s.execute(sqlalchemy.text(
                        "SELECT id FROM recipe_notes WHERE recipe_id=:r ORDER BY position, id"),
                        {"r": rid}).mappings()]
                    for i, nid in enumerate(left):
                        s.execute(sqlalchemy.text(
                            "UPDATE recipe_notes SET position=:p WHERE id=:n"),
                            {"p": -(i + 1), "n": nid})
                    for i, nid in enumerate(left):
                        s.execute(sqlalchemy.text(
                            "UPDATE recipe_notes SET position=:p WHERE id=:n"), {"p": i, "n": nid})
                elif action == "ing_strip":
                    s.execute(sqlalchemy.text(
                        "UPDATE recipe_ingredients SET raw_text=:x WHERE id=:i"),
                        {"x": d["raw_text"], "i": d["id"]})
                    # ⚠️ LOCKSTEP. This one IS baseline content, so the entry moves in the same
                    #    transaction or the cook is told they edited an ingredient heading.
                    if doc is not None:
                        hit = [e for e in doc.get("ingredients", []) if e.get("id") == d["id"]]
                        if not hit:
                            s.rollback()
                            sys.exit(f"ABORT on {rid}: the baseline carries no ingredient row "
                                     f"{d['id']}, so the strip cannot go in lockstep with it.")
                        for e in hit:
                            e["raw_text"] = d["raw_text"]
                        baseline_moved = True
            if baseline_moved:
                s.execute(sqlalchemy.text(
                    "UPDATE recipe_snapshots SET content=:c WHERE recipe_id=:r "
                    "AND reason='original'"),
                    {"c": json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")), "r": rid})
            # ⚠️ PROVE IT BEFORE COMMITTING, inside the same transaction, against the state read
            #    before this run wrote anything.
            now = _state(s, sqlalchemy, app, rid)
            if now["marks"] != before[rid]["marks"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: the annotation set moved, so nothing was written. "
                         f"before={before[rid]['marks'][:200]} after={now['marks'][:200]}")
            if before[rid]["byte_equal"] and not now["byte_equal"]:
                s.rollback()
                sys.exit(f"ABORT on {rid}: it left the byte-equal set, so nothing was written.")
            s.commit()

    print(f"  WROTE {len(todo)} change(s) over {len(touched)} recipe(s) -> {db}")
    print(f"  no recipe's annotation set moved and none left the byte-equal set")
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
