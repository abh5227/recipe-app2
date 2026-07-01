#!/usr/bin/env python3
"""import_write.py — Phase 15 recipe-write: turn a CLEANED recipe (the import_cleanup
core's output) into database rows, with uid-dedup and a review queue.

PIPELINE:  paprika_native_reader (source -> normalized shape)
        -> import_cleanup        (normalized -> structured/flagged)
        -> THIS                  (structured/flagged -> recipes / recipe_ingredients /
                                  recipe_steps / ratings / import_flags)

Imported recipes are source='app', so they live alongside the seed recipes and SURVIVE
every rebuild (build_db only ever rebuilds source='seed').

Two halves, kept apart on purpose:
  - plan_recipe(...)        PURE. cleaned recipe + the uids/slugs already present -> a write
                            PLAN. Decides dedup, mints the slug, maps every field/line/step/
                            flag. Touches NO database — so the dry-run can show exactly what
                            WOULD happen without writing.
  - commit_plan(conn, plan) THE ONLY WRITER. Inserts a plan's rows. Used by the real import
                            run; NEVER by the dry-run.

SLUG vs UID — two different jobs:
  - slug = recipes.id, the human-readable PRIMARY KEY minted from the title; every child row
    (ingredients, steps, ratings, flags) references it. Collisions get -2/-3/....
  - uid  = the SEPARATE dedup key (the source's stable id). If a recipe's uid is already in
    the DB we SKIP it (this is how the 5 tagged seed twins are skipped on import).

STILL SEPARATE LATER PASSES (not done here): library LINKAGE (ingredient_id stays NULL) and
full IMAGE storage (image stays NULL — we don't extract photos[]).

Run the DRY-RUN (writes nothing):  python3 import_write.py [--seed N] [--count 15]
"""
import argparse
import datetime
import gzip
import json
import random
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import import_cleanup as cleanup
import paprika_native_reader as reader

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
ARCHIVE = BASE_DIR / "My Recipes.paprikarecipes"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Slug minting (the PK) — separate from uid (the dedup key)
# --------------------------------------------------------------------------- #
def _ascii_fold(s):
    """Drop accents so 'Açaí' -> 'acai' instead of vanishing under the a-z filter."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")


def _base_slug(name):
    """Title -> the base slug (lowercase, hyphenated, punctuation stripped, accents folded),
    BEFORE any -2/-3 collision suffix. Shared by mint_slug and the --all dry-run's collision
    detector, so 'did mint_slug append a suffix?' can't drift from how the base is built."""
    return _SLUG_STRIP.sub("-", _ascii_fold(name).lower()).strip("-") or "recipe"


def mint_slug(name, taken):
    """Title -> slug (lowercase, hyphenated, punctuation stripped). On collision with an
    already-taken slug, append -2, -3, .... `taken` is updated in place, so planning a whole
    batch can't mint the same slug twice."""
    base = _base_slug(name)
    slug = base
    n = 2
    while slug in taken:
        slug = "%s-%d" % (base, n)
        n += 1
    taken.add(slug)
    return slug


# --------------------------------------------------------------------------- #
# The write PLAN (pure — no DB access)
# --------------------------------------------------------------------------- #
def _qty_text(line):
    """qty for an ingredient row: amount + unit ('2 tbsp', '1 – 2 tbsp'). When no leading
    amount was parsed (e.g. a flagged 'N x SIZE'), qty is None and the full original text
    survives in raw_text — nothing is dropped."""
    qty = ((line.get("amount") or "") + " " + (line.get("unit") or "")).strip()
    return qty or None


def _category_text(categories):
    """Paprika's categories LIST -> the single category TEXT column (existing · convention).
    Each category is whitespace-stripped and blanks dropped (some source categories carry a
    trailing space)."""
    cats = [c.strip() for c in categories if c and c.strip()]
    return " · ".join(cats) if cats else None


def _rating_row(rating):
    """1–5 -> that value; 0 ('unrated' in Paprika) or missing -> None, so no ratings row is
    written and the CHECK(rating BETWEEN 1 AND 5) is never violated."""
    return rating if isinstance(rating, int) and 1 <= rating <= 5 else None


def _ingredient_row(pos, line):
    """One recipe_ingredients row from a cleaned line. A section -> heading (text in raw_text);
    ingredient_id stays NULL (linkage = later pass). grams + secondary_measure are the dual-measure
    capture (the weight and the volume); both are persisted (migrations 011/012)."""
    heading = line["kind"] == "section"
    return {
        "position": pos,
        "is_heading": 1 if heading else 0,
        "qty": None if heading else _qty_text(line),
        "ingredient_id": None,                           # linkage = separate later pass
        "label": None if heading else (line["name"] or None),
        "note": None,                                    # name kept whole; no note split yet
        "raw_text": line["raw"].strip(),                 # original line, ALWAYS preserved
        "grams": None if heading else line.get("grams_harvested"),       # the WEIGHT (captured)
        "secondary_measure": None if heading else line.get("secondary_measure"),  # the VOLUME
    }


def _line_flag_rows(pos, line):
    """Review-queue rows for one line's flags. The line is still written; this just marks it."""
    return [{
        "position": pos,
        "flag": f,
        "reason": ("a gram value was present but not confidently harvested"
                   if f == "grams_declined" else (line["flag_reason"] or None)),
    } for f in line["flags"]]


def _ingredient_rows(cleaned):
    """Cleaned ingredient lines -> (recipe_ingredients rows, review-queue flag rows). Flagged
    lines are WRITTEN (raw_text preserved) AND recorded in the queue; nothing is dropped."""
    rows, flags = [], []
    for pos, line in enumerate(cleaned["ingredients"]):
        rows.append(_ingredient_row(pos, line))
        flags.extend(_line_flag_rows(pos, line))
    return rows, flags


def _step_rows(cleaned):
    """directions (already split into lines by the cleanup core) -> recipe_steps rows: plain
    text, position-ordered, NO {{...}} markup. A heading line (colon / ALL-CAPS, or a trailing
    dash) -> is_heading=1, with the trailing dash stripped from the text (cleanup.classify_step)."""
    rows = []
    for pos, text in enumerate(cleaned["directions"]):
        is_h, clean = cleanup.classify_step(text)
        rows.append({"position": pos, "is_heading": 1 if is_h else 0, "text": clean})
    return rows


def plan_recipe(cleaned, uid_index, taken_slugs, now=None):
    """PURE: a cleaned recipe -> a write plan. No DB access.

    uid_index : {uid: (slug, name)} of recipes already present, so a dedup SKIP can name the
                twin it matched.
    taken_slugs : slugs already in use (existing rows + any minted earlier in this batch);
                  mint_slug grows it so a batch can't collide with itself.
    """
    uid = cleaned["uid"] or None
    if uid and uid in uid_index:
        twin_slug, twin_name = uid_index[uid]
        return {"decision": "skip", "name": cleaned["name"], "uid": uid,
                "twin": {"slug": twin_slug, "name": twin_name}}

    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    slug = mint_slug(cleaned["name"], taken_slugs)
    ing_rows, line_flags = _ingredient_rows(cleaned)
    recipe_flag_rows = [{"position": None, "flag": f, "reason": None}
                        for f in cleaned["recipe_flags"]]

    servings = cleaned["servings"]
    recipe_row = {
        "id": slug,
        "name": cleaned["name"],
        "author": cleaned["source"] or None,             # Paprika 'source' (book/site) -> author
        "source_url": cleaned["source_url"] or None,
        "category": _category_text(cleaned["categories"]),
        "servings": str(servings) if servings is not None else None,   # parsed, else blank
        "prep_time": cleaned["times"]["prep"] or None,
        "cook_time": cleaned["times"]["cook"] or None,
        "total_time": cleaned["times"]["total"] or None,
        "descr": cleaned["description"] or None,
        "notes": cleaned["notes"] or None,
        "image": None,                                   # full image storage = separate pass
        "uid": uid,
        "hash": cleaned["hash"] or None,
        "created_at": now,
        "source": "app",
    }
    return {
        "decision": "write",
        "recipe": recipe_row,
        "ingredients": ing_rows,
        "steps": _step_rows(cleaned),
        "rating": _rating_row(cleaned["rating"]),
        "recipe_flags": cleaned["recipe_flags"],
        "review_flags": line_flags + recipe_flag_rows,
    }


# --------------------------------------------------------------------------- #
# The ONLY writer (used by the real import run, NOT by the dry-run)
# --------------------------------------------------------------------------- #
def commit_plan(conn, plan):
    """Persist one write plan; returns True if it wrote, False for a SKIP. The caller owns
    the transaction (commit/rollback). Requires migration 010 (import_flags)."""
    if plan["decision"] != "write":
        return False
    r = plan["recipe"]
    conn.execute(
        """INSERT INTO recipes
           (id, name, author, source_url, category, servings, prep_time, cook_time,
            total_time, descr, notes, image, uid, hash, created_at, source)
           VALUES (:id,:name,:author,:source_url,:category,:servings,:prep_time,:cook_time,
                   :total_time,:descr,:notes,:image,:uid,:hash,:created_at,:source)""", r)
    for row in plan["ingredients"]:
        conn.execute(
            """INSERT INTO recipe_ingredients
               (recipe_id, position, is_heading, qty, ingredient_id, label, note, raw_text, grams,
                secondary_measure)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (r["id"], row["position"], row["is_heading"], row["qty"],
             row["ingredient_id"], row["label"], row["note"], row["raw_text"], row["grams"],
             row["secondary_measure"]))
    for row in plan["steps"]:
        conn.execute(
            "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,?,?)",
            (r["id"], row["position"], row["is_heading"], row["text"]))
    if plan["rating"] is not None:
        conn.execute("INSERT INTO ratings (recipe_id, rating) VALUES (?,?)",
                     (r["id"], plan["rating"]))
    for fl in plan["review_flags"]:
        conn.execute(
            "INSERT INTO import_flags (recipe_id, position, flag, reason) VALUES (?,?,?,?)",
            (r["id"], fl["position"], fl["flag"], fl["reason"]))
    return True


# --------------------------------------------------------------------------- #
# DB state (read-only) used to plan
# --------------------------------------------------------------------------- #
def db_state(db=DB):
    """Read the existing uids (-> twin slug/name for skip reporting) and taken slugs.
    Read-only: opens, SELECTs, closes. Writes nothing."""
    conn = sqlite3.connect(str(db))
    uid_index = {u: (i, n) for i, n, u in conn.execute(
        "SELECT id, name, uid FROM recipes WHERE uid IS NOT NULL")}
    taken = {row[0] for row in conn.execute("SELECT id FROM recipes")}
    conn.close()
    return uid_index, taken


# --------------------------------------------------------------------------- #
# DRY-RUN: selector + preview (PRINTS, WRITES NOTHING)
# --------------------------------------------------------------------------- #
def _norm_author(a):
    """Light fold for distinctness: lowercase + drop all whitespace, so 'RecipeTin Eats'
    and 'recipetineats' count as the same author."""
    return _WS.sub("", (a or "").strip().lower())


def _load_rec(zf, entry):
    return json.loads(gzip.decompress(zf.read(entry)))


def load_light(zf):
    """One light pass: [{entry, name, author, uid}] for every recipe (no images retained)."""
    light = []
    for name, rec, err in reader.iter_entries(zf):
        if err or not rec:
            continue
        light.append({
            "entry": name,
            "name": reader.strip_quotes(rec.get("name") or ""),
            "author": rec.get("source") or "",
            "uid": rec.get("uid") or "",
        })
    return light


def select_distinct_authors(light, count, rng):
    """Pick `count` recipes with DISTINCT (lightly-normalized) authors, chosen randomly. One
    recipe per author group means at most one no-author recipe falls out automatically."""
    by_author = {}
    for r in light:
        by_author.setdefault(_norm_author(r["author"]), []).append(r)
    authors = list(by_author.keys())
    rng.shuffle(authors)
    chosen = []
    for a in authors:
        if len(chosen) >= count:
            break
        chosen.append(rng.choice(by_author[a]))
    return chosen


def _fmt(v):
    return "—" if v is None or v == "" else v


def _print_recipe_fields(index, r):
    print("#%-2d  WRITE   %s" % (index, r["name"]))
    print("       recipes row:")
    print("         id (slug) : %s" % r["id"])
    print("         author    : %s" % _fmt(r["author"]))
    print("         source_url: %s" % _fmt(r["source_url"]))
    print("         category  : %s" % _fmt(r["category"]))
    print("         servings  : %s" % _fmt(r["servings"]))
    print("         times     : prep=%s  cook=%s  total=%s"
          % (_fmt(r["prep_time"]), _fmt(r["cook_time"]), _fmt(r["total_time"])))
    print("         uid / hash: %s / %s" % (_fmt(r["uid"]), _fmt(r["hash"])))
    print("         image     : %s    source: %s" % (_fmt(r["image"]), r["source"]))
    if r["descr"]:
        print("         descr     : %s" % cleanup.trunc(r["descr"], 74))


def _print_ingredient_rows(ings, flagged_pos):
    nhead = sum(i["is_heading"] for i in ings)
    print("       ingredient rows (%d: %d heading, %d line):"
          % (len(ings), nhead, len(ings) - nhead))
    for i in ings:
        if i["is_heading"]:
            tag = "[H?]" if i["position"] in flagged_pos else "[H ]"   # H? = section_suggested
            print("         %s %2d. %s" % (tag, i["position"], i["raw_text"]))
            continue
        tag = "[F]" if i["position"] in flagged_pos else "   "
        sec = ("   [2nd %s]" % i["secondary_measure"]) if i.get("secondary_measure") else ""
        gr = ("   [%gg]" % i["grams"]) if i.get("grams") else ""
        print("         %s %2d. qty=%-11s| %s%s%s"
              % (tag, i["position"], _fmt(i["qty"]),
                 cleanup.trunc(i["label"] or i["raw_text"], 50), sec, gr))


def print_plan(plan, index):
    """Print what one plan WOULD write (writes nothing)."""
    print("\n" + "-" * 90)
    if plan["decision"] == "skip":
        t = plan["twin"]
        print("#%-2d  SKIP — uid already present   %s" % (index, plan["name"]))
        print("       uid %s already held by '%s' (%s)" % (plan["uid"], t["slug"], t["name"]))
        return
    _print_recipe_fields(index, plan["recipe"])
    flagged_pos = {f["position"] for f in plan["review_flags"] if f["position"] is not None}
    _print_ingredient_rows(plan["ingredients"], flagged_pos)
    steps = plan["steps"]
    sh = [s["text"] for s in steps if s["is_heading"]]
    print("       step rows : %d (%d heading)%s"
          % (len(steps), len(sh), ("  -> " + " | ".join(sh)) if sh else ""))
    print("       rating    : %s" % ("no row (0 / unrated)" if plan["rating"] is None
                                      else "%d  -> ratings row" % plan["rating"]))
    if plan["recipe_flags"]:
        print("       INCOMPLETE: %s" % ", ".join(plan["recipe_flags"]))
    if plan["review_flags"]:
        kinds = dict(Counter(f["flag"] for f in plan["review_flags"]))
        print("       review queue: %d import_flags row(s) -> %s" % (len(plan["review_flags"]), kinds))


def _print_dry_summary(plans):
    writes = [p for p in plans if p["decision"] == "write"]
    skips = [p for p in plans if p["decision"] == "skip"]
    print("\n" + "=" * 90)
    print("DRY-RUN SUMMARY")
    print("=" * 90)
    print("  would WRITE : %d recipe(s)" % len(writes))
    print("  would SKIP  : %d recipe(s)%s" % (
        len(skips), ("  -> " + ", ".join(p["twin"]["slug"] for p in skips)) if skips else ""))
    print("  ingredient rows  : %d" % sum(len(p["ingredients"]) for p in writes))
    print("  step rows        : %d" % sum(len(p["steps"]) for p in writes))
    print("  review-queue rows: %d" % sum(len(p["review_flags"]) for p in writes))
    print("  ratings rows     : %d" % sum(1 for p in writes if p["rating"] is not None))
    incomplete = [p["recipe"]["name"] for p in writes if p["recipe_flags"]]
    print("  incomplete (written + flagged): %s" % (incomplete or "none"))
    print("\n(nothing written — this was a dry run.)")


def dry_run(seed=None, count=15, db=DB, archive=ARCHIVE):
    """Select `count` distinct-author recipes and PRINT the write plan for each. WRITES
    NOTHING: it only SELECTs existing uids/slugs (for dedup + collision) and prints."""
    if not Path(archive).is_file():
        raise SystemExit("Archive not found: %s" % archive)
    rng = random.Random(seed)
    uid_index, taken = db_state(db)

    with zipfile.ZipFile(archive) as zf:
        light = load_light(zf)
        chosen = select_distinct_authors(light, count, rng)

        print("=" * 90)
        print("DRY-RUN — recipe-write on %d of %d recipes (distinct authors). WRITES NOTHING."
              % (len(chosen), len(light)))
        print("  rng seed = %s        db = %s"
              % ("fresh-random" if seed is None else seed, Path(db).name))
        print("=" * 90)
        print("Selected (title | author):")
        for i, r in enumerate(chosen, 1):
            print("  %2d. %-52s | %s" % (i, cleanup.trunc(r["name"], 52), _fmt(r["author"])))

        plans = []
        for i, r in enumerate(chosen, 1):
            cleaned = cleanup.clean_recipe(reader.normalize(_load_rec(zf, r["entry"])))
            plan = plan_recipe(cleaned, uid_index, taken)
            print_plan(plan, i)
            plans.append(plan)

    _print_dry_summary(plans)


# --------------------------------------------------------------------------- #
# FULL-CORPUS DRY-RUN (--all): EVERY recipe, namelist order, WRITES NOTHING.
# Mirrors the runner's iteration (reader.iter_entries -> clean_recipe -> plan_recipe)
# but collects plans instead of committing. The author sampler is never used here.
# --------------------------------------------------------------------------- #
def _is_non_ascii(s):
    return any(ord(c) > 127 for c in s or "")


def plan_all(zf, uid_index, taken):
    """Plan EVERY entry in the archive, mirroring the runner's namelist-order loop
    (reader.iter_entries -> clean_recipe -> plan_recipe) but WRITING NOTHING: it collects
    plans instead of committing. `uid_index` is threaded across the batch exactly as the
    runner threads it, so intra-batch dedup is predicted identically. Returns
    (plans, reader_errors) with reader_errors = [(entry_name, repr(err))]."""
    plans, reader_errors = [], []
    for name, rec, err in reader.iter_entries(zf):          # same walk the runner uses
        if err is not None or rec is None:
            reader_errors.append((name, repr(err)))
            continue
        cleaned = cleanup.clean_recipe(reader.normalize(rec))
        plan = plan_recipe(cleaned, uid_index, taken)
        plans.append(plan)
        if plan["decision"] == "write":
            uid = plan["recipe"]["uid"]
            if uid:                                         # thread dedup across the batch
                uid_index[uid] = (plan["recipe"]["id"], plan["recipe"]["name"])
    return plans, reader_errors


def summarize_all(plans, reader_errors):
    """PURE: fold plans + reader errors into the full-corpus report stats. Returned as a
    dict so tests assert on the numbers without parsing printed output."""
    writes = [p for p in plans if p["decision"] == "write"]
    skips = [p for p in plans if p["decision"] == "skip"]

    # slug collision: the minted slug differs from the base -> mint_slug appended a -N suffix
    collisions = [(p["recipe"]["name"], p["recipe"]["id"])
                  for p in writes if p["recipe"]["id"] != _base_slug(p["recipe"]["name"])]
    title_counts = Counter(p["recipe"]["name"] for p in writes)   # the collision cause
    dup_titles = sorted((t, c) for t, c in title_counts.items() if c > 1)

    incomplete = {}                                          # recipe-level flag -> [names]
    for p in writes:
        for f in p["recipe_flags"]:
            incomplete.setdefault(f, []).append(p["recipe"]["name"])

    line_flag_counts = Counter()                             # review_flags rows WITH a position
    flagged_per_recipe = []
    for p in writes:
        positions = set()
        for fl in p["review_flags"]:
            if fl["position"] is not None:
                line_flag_counts[fl["flag"]] += 1
                positions.add(fl["position"])
        if positions:
            flagged_per_recipe.append((len(positions), p["recipe"]["name"]))
    flagged_per_recipe.sort(key=lambda t: (-t[0], t[1]))

    servings_parsed = sum(1 for p in writes if p["recipe"]["servings"] is not None)
    grams_lines = grams_recipes = secondary_lines = secondary_recipes = 0
    for p in writes:
        g = sum(1 for i in p["ingredients"] if i["grams"] is not None)
        s = sum(1 for i in p["ingredients"] if i["secondary_measure"] is not None)
        grams_lines += g
        secondary_lines += s
        grams_recipes += 1 if g else 0
        secondary_recipes += 1 if s else 0

    return {
        "entries_seen": len(writes) + len(skips) + len(reader_errors),
        "would_write": len(writes),
        "skips": [(p["name"], p["twin"]["slug"], p["twin"]["name"]) for p in skips],
        "reader_errors": list(reader_errors),
        "collisions": collisions,
        "dup_titles": dup_titles,
        "incomplete": incomplete,
        "line_flag_counts": dict(line_flag_counts),
        "total_flagged_lines": sum(n for n, _ in flagged_per_recipe),
        "recipes_with_flags": len(flagged_per_recipe),
        "most_flagged": flagged_per_recipe,
        "servings_parsed": servings_parsed,
        "servings_blank": len(writes) - servings_parsed,
        "grams_lines": grams_lines,
        "grams_recipes": grams_recipes,
        "secondary_lines": secondary_lines,
        "secondary_recipes": secondary_recipes,
        "non_ascii": [(p["recipe"]["name"], p["recipe"]["id"])
                      for p in writes if _is_non_ascii(p["recipe"]["name"])],
        "blank_author": [(p["recipe"]["name"], p["recipe"]["id"])
                         for p in writes if p["recipe"]["author"] is None],
    }


def _fmt_status(ok):
    return "MATCH" if ok else "MISMATCH"


def _print_reconciliation(stats, seed_ids):
    """Line-by-line: each earlier read-only prediction vs. this run's actual, MATCH/MISMATCH.
    Same pure functions on the runner's iteration path, so exacts should match; the two ~
    line-flag rows were review estimates (tolerance ±10)."""
    inc = stats["incomplete"]
    lfc = stats["line_flag_counts"]
    skips = stats["skips"]
    skips_all_seed = len(skips) > 0 and all(ts in seed_ids for _, ts, _ in skips)
    total_inc = sum(len(v) for v in inc.values())
    total_rows = sum(lfc.values())
    amb = lfc.get("ambiguous_section", 0)

    def n(flag):
        return len(inc.get(flag, []))

    rows = [
        ("entries seen", "298", stats["entries_seen"], stats["entries_seen"] == 298),
        ("skip / uid-dup", "5", len(skips), len(skips) == 5),
        ("  skips are seed twins", "all seed", ("yes" if skips_all_seed else "NO"), skips_all_seed),
        ("slug collisions", "2", len(stats["collisions"]), len(stats["collisions"]) == 2),
        ("incomplete (total)", "31", total_inc, total_inc == 31),
        ("  no_directions", "26", n("no_directions"), n("no_directions") == 26),
        ("  no_ingredients", "3", n("no_ingredients"), n("no_ingredients") == 3),
        ("  photo_only", "2", n("photo_only"), n("photo_only") == 2),
        ("line flags (rows)", "~504", total_rows, abs(total_rows - 504) <= 10),
        ("  ambiguous_section", "~480", amb, abs(amb - 480) <= 10),
        ("servings parsed", "162", stats["servings_parsed"], stats["servings_parsed"] == 162),
        ("servings blank", "136", stats["servings_blank"], stats["servings_blank"] == 136),
        ("accented titles", "8", len(stats["non_ascii"]), len(stats["non_ascii"]) == 8),
        ("blank-author", "1", len(stats["blank_author"]), len(stats["blank_author"]) == 1),
    ]
    print("\n" + "=" * 88)
    print("RECONCILIATION  (earlier read-only review  vs  this run)")
    print("=" * 88)
    print("  %-24s %-11s %-9s %s" % ("metric", "predicted", "actual", "status"))
    print("  " + "-" * 58)
    for label, pred, actual, ok in rows:
        print("  %-24s %-11s %-9s %s" % (label, pred, str(actual), _fmt_status(ok)))
    mism = [r for r in rows if not r[3]]
    if mism:
        print("\n  %d MISMATCH(es) to review before the real import:" % len(mism))
        for label, pred, actual, _ in mism:
            print("      - %s: predicted %s, actual %s" % (label.strip(), pred, actual))
    else:
        print("\n  all metrics MATCH the earlier read-only review.")


def _print_all_summary(stats, seed_ids=frozenset()):
    print("\n" + "=" * 88)
    print("TOTALS")
    print("=" * 88)
    print("  entries seen   : %d   (= would-write + skip + reader errors)" % stats["entries_seen"])
    print("  would WRITE    : %d" % stats["would_write"])
    print("  skip (uid dup) : %d" % len(stats["skips"]))
    for name, twin_slug, _twin_name in stats["skips"]:
        mark = "seed" if twin_slug in seed_ids else "NOT seed"
        print("      - %-40s -> twin %s  [%s]" % (cleanup.trunc(name, 40), twin_slug, mark))
    print("  reader errors  : %d" % len(stats["reader_errors"]))
    for name, e in stats["reader_errors"]:
        print("      ! %s -> %s" % (name, e))

    print("\nSLUG COLLISIONS (mint_slug appended -N)")
    if stats["collisions"]:
        for name, slug in stats["collisions"]:
            print("  %-44s -> %s" % (cleanup.trunc(name, 44), slug))
    else:
        print("  (none)")
    if stats["dup_titles"]:
        print("  source duplicate titles: %s"
              % ", ".join("%s x%d" % (t, c) for t, c in stats["dup_titles"]))

    print("\nINCOMPLETE RECIPES (recipe-level flags)")
    inc = stats["incomplete"]
    if any(inc.values()):
        known = ("no_directions", "no_ingredients", "photo_only")
        for flag in known:
            names = inc.get(flag, [])
            if names:
                print("  %s (%d):" % (flag, len(names)))
                for nm in names:
                    print("      - %s" % cleanup.trunc(nm, 66))
        for flag, names in inc.items():
            if flag not in known:
                print("  %s (%d): %s" % (flag, len(names), ", ".join(names)))
    else:
        print("  (none)")

    print("\nLINE-FLAG SUMMARY (across would-write recipes)")
    lfc = stats["line_flag_counts"]
    if lfc:
        for flag in sorted(lfc, key=lambda k: -lfc[k]):
            print("  %-18s: %d" % (flag, lfc[flag]))
    else:
        print("  (none)")
    print("  total flag rows    : %d" % sum(lfc.values()))
    print("  total flagged lines: %d across %d recipe(s)"
          % (stats["total_flagged_lines"], stats["recipes_with_flags"]))
    if stats["most_flagged"]:
        print("  most-flagged recipes:")
        for cnt, name in stats["most_flagged"][:12]:
            print("      %3d  %s" % (cnt, cleanup.trunc(name, 60)))

    print("\nCOVERAGE")
    print("  servings parsed : %d / %d   (blank: %d)"
          % (stats["servings_parsed"], stats["would_write"], stats["servings_blank"]))
    print("  grams harvested : %d line(s) across %d recipe(s)"
          % (stats["grams_lines"], stats["grams_recipes"]))
    print("  secondary meas. : %d line(s) across %d recipe(s)"
          % (stats["secondary_lines"], stats["secondary_recipes"]))

    print("\nTITLES TO EYEBALL")
    print("  non-ASCII / accented (%d):" % len(stats["non_ascii"]))
    for name, slug in stats["non_ascii"]:
        print("      - %-46s -> %s" % (cleanup.trunc(name, 46), slug))
    print("  blank-author (%d):" % len(stats["blank_author"]))
    for name, slug in stats["blank_author"]:
        print("      - %-46s -> %s" % (cleanup.trunc(name, 46), slug))

    _print_reconciliation(stats, seed_ids)
    print("\n(nothing written — this was a dry run.)")


def dry_run_all(db=DB, archive=ARCHIVE, verbose=False):
    """FULL-CORPUS dry-run: plan EVERY recipe in `archive` (namelist order, the runner's
    path) and print what WOULD be written. WRITES NOTHING — only read-only db_state (+ a
    read-only seed-id query for the reconciliation). Never opens a write connection, backs
    up, or calls commit_plan; the author sampler is never used."""
    if not Path(archive).is_file():
        raise SystemExit("Archive not found: %s" % archive)
    uid_index, taken = db_state(db)                         # read-only
    conn = sqlite3.connect(str(db))                         # read-only: seed ids for reconciliation
    seed_ids = {r[0] for r in conn.execute("SELECT id FROM recipes WHERE source='seed'")}
    conn.close()

    with zipfile.ZipFile(archive) as zf:
        plans, reader_errors = plan_all(zf, uid_index, taken)
        print("=" * 88)
        print("FULL-CORPUS DRY-RUN — recipe-write on ALL %d entries (namelist order). "
              "WRITES NOTHING." % (len(plans) + len(reader_errors)))
        print("  archive = %s    db = %s" % (Path(archive).name, Path(db).name))
        print("=" * 88)
        if verbose:
            for i, p in enumerate(plans, 1):
                print_plan(p, i)

    _print_all_summary(summarize_all(plans, reader_errors), seed_ids)


def main():
    ap = argparse.ArgumentParser(
        description="Phase 15 recipe-write DRY-RUN — prints write plans, writes nothing.")
    ap.add_argument("--all", action="store_true",
                    help="preview EVERY recipe in the archive (full corpus, namelist order); "
                         "ignores --seed/--count and never uses the author sampler")
    ap.add_argument("--verbose", action="store_true",
                    help="with --all: also print the per-recipe plan before the summary")
    ap.add_argument("--seed", type=int, default=None,
                    help="fixed RNG seed for a reproducible selection (default: fresh-random)")
    ap.add_argument("--count", type=int, default=15,
                    help="how many distinct-author recipes to preview (default: 15)")
    args = ap.parse_args()
    if args.all:
        dry_run_all(verbose=args.verbose)
    else:
        dry_run(seed=args.seed, count=args.count)


if __name__ == "__main__":
    main()
