#!/usr/bin/env python3
"""plan_ahead_proposals_v3.py - the plan-ahead proposals, v3.

READ-ONLY. Reads live with mode=ro, reads previews/plan-ahead-proposals.csv (v2), and writes
previews/plan-ahead-proposals-v3.csv. It writes NOTHING to any database.

v3 does three things v2 did not.

⚠️ EVERY EXCLUDED ROW WAS RE-READ. v2 excluded 8. The new rule is narrower: a row is excluded only
when it is not a wait at all (active cooking, which belongs to cook time) or the duration belongs to
another verb. 5 of the 8 come back.

⚠️ AN ALTERNATIVE IS AN EXTENSION, NOT AN EXCLUSION. "or overnight if you want" beside a marinade
with no stated length is the same shape as chicken-tikka-masala's, and v2 threw two of them away.

⚠️ OPTIONAL AND CONDITIONAL WAITS ARE KEPT, WITH THEIR when. Measured: only 3 of the 98 v2 wait rows
carry an optional or conditional marker in their source sentence, and all 3 were already handled as
extensions, so the existing rows stay 'always'. The conditional ones all came out of the exclusions.
"""
import csv
import pathlib
import re
import sqlite3
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import planahead                                                  # noqa: E402

V2 = BASE / "previews" / "plan-ahead-proposals.csv"
OUT = BASE / "previews" / "plan-ahead-proposals-v3.csv"
DB = BASE / "recipes.db"

FIELDS = ["recipe_id", "type", "kind", "when_kind", "when_label", "step_position", "label",
          "min_minutes", "max_minutes", "ext_label", "ext_min_minutes", "ext_max_minutes",
          "reads_as", "source_sentence", "reason"]

# ---------------------------------------------------------------------------------------------
# The eight v2 exclusions, re-read one at a time. Each entry says what it becomes and why.
# ---------------------------------------------------------------------------------------------
# A row keyed (recipe_id, step_position) is REPLACED by the rows in `becomes`. An empty list keeps
# the exclusion, with `reason` rewritten to say why under the NEW rule.
REREAD = {
    ("brioche-bread", "10"): dict(
        drop=True,
        # ⚠️ ATTACHES TO THE EXISTING 8-12 HOUR COLD PROOF rather than standing alone. It is the
        #    SHORTER direction of the same extension shape as chocolate-chip-cookies'.
        extend=("brioche-bread", "8",
                "or an hour of fridge rest if you skip the overnight proof", 60, 60),
        note="reclassified: a SHORTER extension on the 8-12 hr cold proof"),
    ("beans", "3"): dict(
        drop=True,
        # ⚠️ NOT A SECOND SOAK. The recipe heads step 2 "OVERNIGHT SOAK" and step 3 "QUICK SOAK",
        #    and step 4 adds that you can skip soaking altogether. They are two ways to do the SAME
        #    soak, so counting both told a cook to allow 9 hr 30 min for one of them. Found by
        #    reading every pair of waits within 3 steps of each other while auditing morning-buns.
        extend=("beans", "2", "or a 90 minute quick soak instead", 90, 90),
        note="reclassified: the QUICK SOAK is an ALTERNATIVE to the overnight soak, so it is a "
             "shorter extension rather than a second wait"),
    ("chocolate-chip-cookies", "22"): dict(
        becomes=[dict(type="wait", kind="resting", label="5 min", when_kind="always",
                      source="Allow the cookies to rest for 5 minutes on the baking sheets, then "
                             "use a metal spatula to transfer the cookies to a wire rack to cool.",
                      reason="reclassified: a passive rest, not active cooking")]),
    ("coconut-curried-golden-lentils", "0"): dict(
        becomes=[dict(type="wait", kind="soaking", label="", when_kind="optional",
                      source="Note: Soaking lentils is optional but can improve digestibility and "
                             "speed cook time.",
                      reason="reclassified: optional, and the recipe states NO duration anywhere")]),
    ("no-knead-bread", "3"): dict(
        # ⚠️ TWO ROWS OUT OF ONE EXCLUSION. v2 read the two sentences as one thing and dropped both.
        becomes=[dict(type="wait", kind="chilling", label="up to 3 days", when_kind="optional",
                      source="Optional: refrigerate up to 3 days for more flavour.",
                      reason="reclassified: an optional cold ferment, not storage (it is 'for more "
                             "flavour', and the dough is still raw)"),
                 dict(type="wait", kind="resting", label="45\u201360 min", when_kind="only_if",
                      when_label="chilled",
                      source="If chilled, let the bowl sit out 45–60 minutes before shaping.",
                      reason="reclassified: conditional on the optional chill above")]),
    ("nandos-portuguese-chicken-and-rice", "3"): dict(
        becomes=[dict(type="wait", kind="marinating", label="", when_kind="always",
                      ext_label="or overnight if you want, though not necessary",
                      source="Set aside while you prepare the rest of the ingredients, or overnight "
                             "if you want (though not necessary).",
                      reason="reclassified: a marinade with no stated length, and the overnight is "
                             "an ALTERNATIVE, so it is an extension")]),
    ("vietnamese-caramel-ginger-chicken", "0"): dict(
        becomes=[dict(type="wait", kind="marinating", label="", when_kind="always",
                      ext_label="or overnight, though not necessary",
                      source="Toss chicken with fish sauce and chilli, then set aside while you "
                             "prepare the other ingredients. You could marinate even overnight but "
                             "it's not necessary.",
                      reason="reclassified: same shape as nandos, an alternative is an extension")]),
    # ---- the two that STAY excluded ----
    ("warm-buttered-hummus", "0"): dict(
        becomes=[], reason="NOT A WAIT: a 45 min simmer is active cooking and belongs to cook_time. "
                           "⚠️ this recipe has NO cook_time at all (see the separate gap)"),
    ("homemade-pasta-dough", "5.1"): dict(
        becomes=[], reason="NOT A WAIT: a storage claim, and it is already carried by this recipe's "
                           "two storage rows"),
}


# ---------------------------------------------------------------------------------------------
# Rows v2 never found at all. NOT asked for by the brief, and flagged so they can be removed in one
# line each. Each was turned up by re-scanning the corpus while answering the short-rest question,
# and each is the same shape as rows v2 already carries.
# ---------------------------------------------------------------------------------------------
ADDITIONS = [
    dict(recipe_id="za-atar-bread", step_position="6", type="wait", kind="rising",
         label="20\u201330 min", when_kind="always",
         source="Cover with plastic wrap and set aside to rise for 20 to 30 minutes.",
         reason="\u26a0\ufe0f NOT IN THE BRIEF: a real rise v2 missed entirely"),
    dict(recipe_id="beef-and-pepper-stir-fry", step_position="0", type="wait", kind="marinating",
         label="30 min", when_kind="always",
         source="Add all the marinade ingredients to the beef in a bowl, mix well, and set aside "
                "for 30 minutes at room temperature.",
         reason="\u26a0\ufe0f NOT IN THE BRIEF: a real 30 min marinade v2 missed entirely"),
    dict(recipe_id="toum", step_position="1", type="storage", where_kept="fridge",
         label="up to 5 days", when_kind="always",
         source="Use immediately or cover and refrigerate in an airtight container for up to 5 days.",
         reason="\u26a0\ufe0f NOT IN THE BRIEF: a storage claim v2 missed entirely"),
]


def _minutes(label):
    return planahead.read_duration(label) if label else (None, None)


PLACE = {"fridge": "in the fridge", "freezer": "in the freezer",
         "room temp": "at room temperature", "other": ""}


def _storage_reads_as(where_kept, applies_to, label):
    """⚠️ MIRRORS static/app.js. The preposition belongs to the place: 11 of the 30 storage rows
    keep at room temperature and 3 say 'other', which read 'in the room temp' and 'in the other'."""
    place = PLACE.get(where_kept, "")
    what = f"{applies_to} " if applies_to else ""
    return f"Keeps {what}{place + ' ' if place else ''}{label}"


def _reads_as(row):
    """The one line the page would print, so the CSV can be read without running the app."""
    if row["type"] == "storage":
        # v2 stored where_kept in the `kind` column and applies_to nowhere; the sentence it wrote
        # carries the subject, so recover it from there rather than guessing.
        prev = row.get("reads_as") or ""
        what = ""
        m = re.match(r"Keeps (.+?) (?:in the|at) ", prev)
        if m:
            what = m.group(1)
        return _storage_reads_as(row["kind"], what, row["label"])
    lo, hi = row["min_minutes"], row["max_minutes"]
    head = f"Plan ahead {row['label']}" if row["label"] else "(no duration stated)"
    q = {"optional": " (optional)", "only_if": f" if {row['when_label']}"}.get(row["when_kind"], "")
    if row["when_kind"] != "always":
        head = f"{row['label'] or '(no duration stated)'} {row['kind']}{q}"
    elif row["kind"]:
        head += f" ({row['kind']})"
    return head + (f" / {row['ext_label']}" if row["ext_label"] else "")


def main():
    v2 = list(csv.DictReader(V2.open()))
    out, changes = [], {"kept": 0, "reclassified": 0, "from_exclusions": 0, "still_excluded": 0,
                        "extensions_added": 0, "recomputed": 0, "not_in_brief": 0}
    extensions, extension_note = {}, {}
    for key, spec in REREAD.items():
        if spec.get("extend"):
            rid, step, lbl, lo, hi = spec["extend"]
            extensions[(rid, step)] = (lbl, lo, hi)
            extension_note[(rid, step)] = spec["note"]

    for r in v2:
        key = (r["recipe_id"], str(r["step_position"]))
        row = {f: r.get(f, "") for f in FIELDS}
        row["when_kind"] = "always"
        row["when_label"] = ""
        if key in REREAD:
            spec = REREAD[key]
            if spec.get("drop"):
                changes["reclassified"] += 1
                continue
            if not spec.get("becomes"):                    # stays excluded, new reason
                row["reason"] = spec["reason"]
                changes["still_excluded"] += 1
                out.append(row)
                continue
            for b in spec["becomes"]:
                lo, hi = _minutes(b.get("label"))
                elo, ehi = _minutes(b.get("ext_label"))
                nr = dict.fromkeys(FIELDS, "")
                nr.update(recipe_id=r["recipe_id"], type=b["type"], kind=b.get("kind", ""),
                          when_kind=b.get("when_kind", "always"), when_label=b.get("when_label", ""),
                          step_position=r["step_position"], label=b.get("label", ""),
                          min_minutes="" if lo is None else lo, max_minutes="" if hi is None else hi,
                          ext_label=b.get("ext_label", ""),
                          ext_min_minutes="" if elo is None else elo,
                          ext_max_minutes="" if ehi is None else ehi,
                          source_sentence=b.get("source", ""), reason=b["reason"])
                nr["reads_as"] = _reads_as(nr)
                changes["from_exclusions"] += 1
                out.append(nr)
            changes["reclassified"] += 1          # one v2 exclusion resolved
            continue
        # ⚠️ EVERY SURVIVING ROW'S MINUTES ARE RECOMPUTED, because read_duration changed: "up to X"
        #    is now a ceiling with a floor of 0, where it used to be a flat figure at X.
        if row["label"]:
            lo, hi = _minutes(row["label"])
            before = (row["min_minutes"], row["max_minutes"])
            after = ("" if lo is None else str(lo), "" if hi is None else str(hi))
            if before != after:
                changes["recomputed"] += 1
                row["reason"] = ((row["reason"] + "; ") if row["reason"] else "") + \
                    f"minutes recomputed {before[0]}–{before[1]} -> {after[0]}–{after[1]} " \
                    f"('up to' is a ceiling)"
            row["min_minutes"], row["max_minutes"] = after
        if row["type"] == "storage":
            row["reads_as"] = _reads_as(row)
        if key in extensions:
            lbl, lo, hi = extensions[key]
            row["ext_label"], row["ext_min_minutes"], row["ext_max_minutes"] = lbl, lo, hi
            row["reason"] = ((row["reason"] + "; ") if row["reason"] else "") + \
                extension_note[key]
            changes["extensions_added"] += 1
            row["reads_as"] = _reads_as(row)
        changes["kept"] += 1
        out.append(row)

    for a in ADDITIONS:
        lo, hi = _minutes(a["label"])
        nr = dict.fromkeys(FIELDS, "")
        nr.update({k: v for k, v in a.items() if k in FIELDS})
        nr.update(min_minutes="" if lo is None else lo, max_minutes="" if hi is None else hi,
                  source_sentence=a["source"], when_label="")
        if a["type"] == "storage":
            what = a.get("applies_to") or ""
            nr["reads_as"] = _storage_reads_as(a["where_kept"], what, a["label"])
            nr["kind"] = a["where_kept"]          # the storage column the applier reads
        else:
            nr["reads_as"] = _reads_as(nr)
        changes["not_in_brief"] += 1
        out.append(nr)

    def _pos(r):
        """⚠️ NUMERIC. Sorting step_position as text put step 5 after step 24."""
        try:
            return float(str(r["step_position"]))
        except (TypeError, ValueError):
            return float("inf")

    out.sort(key=lambda r: (r["recipe_id"], _pos(r), r["type"]))
    with OUT.open("w", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"wrote {OUT.name}: {len(out)} rows")
    for k, v in changes.items():
        print(f"  {k}: {v}")
    return out


if __name__ == "__main__":
    main()
