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


def mint_slug(name, taken):
    """Title -> slug (lowercase, hyphenated, punctuation stripped). On collision with an
    already-taken slug, append -2, -3, .... `taken` is updated in place, so planning a whole
    batch can't mint the same slug twice."""
    base = _SLUG_STRIP.sub("-", _ascii_fold(name).lower()).strip("-") or "recipe"
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
    text, position-ordered, NO {{...}} markup. A section-header line -> is_heading=1."""
    return [
        {"position": pos, "is_heading": 1 if cleanup.is_section(text) else 0, "text": text}
        for pos, text in enumerate(cleaned["directions"])
    ]


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
            print("         [H] %2d. %s" % (i["position"], i["raw_text"]))
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
    print("       step rows : %d (%d heading)" % (len(steps), sum(s["is_heading"] for s in steps)))
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


def main():
    ap = argparse.ArgumentParser(
        description="Phase 15 recipe-write DRY-RUN — prints write plans, writes nothing.")
    ap.add_argument("--seed", type=int, default=None,
                    help="fixed RNG seed for a reproducible selection (default: fresh-random)")
    ap.add_argument("--count", type=int, default=15,
                    help="how many distinct-author recipes to preview (default: 15)")
    args = ap.parse_args()
    dry_run(seed=args.seed, count=args.count)


if __name__ == "__main__":
    main()
