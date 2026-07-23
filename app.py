#!/usr/bin/env python3
"""app.py — the backend.

It does two jobs:
  1. serves the static page (static/index.html, app.js, styles.css)
  2. answers a small JSON API that runs the SQLite queries

Recipes can be created/edited/deleted in the app (source='app'); recipes from
seed.py (source='seed') are read-only here, but several people can each keep their
own version of one by layering changes on top (see the change endpoints below).

Run it with:  python3 app.py   then open http://localhost:8000
"""
import datetime
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import create_engine, delete, event, func, insert, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert   # Stage 2b swaps to the postgresql dialect
from sqlalchemy.orm import Session

from weights import build_index, match_weight
from stepscale import api_spans
from import_cleanup import split_qty   # shared qty->quantity+unit split (backfill/seed/import use it too)
# SQLAlchemy migration (Stage 1 complete): the entire serve path queries through orm_session() below —
# reads, writes, and the 5 SQLite-dialect upserts. Build-time modules (build_db/import/migrate) keep
# their own raw sqlite3 connections (out of Stage 1 scope). Stage 2 swaps the engine to Postgres
# (see docs/migration-plan.md).
from models import (
    Person, Ingredient, IngredientSeason, IngredientRegion, Region, Recipe, RecipeIngredient, RecipeStep,
    RecipeLineChange, RecipeAddition, Rating, CookLog, ingredient_weights,
)

# Anchor everything to this file's folder so the app runs from any directory.
BASE_DIR = Path(__file__).resolve().parent
# The frontend is built by Vite (npm run build) into dist/: a hashed entry + dist/assets/*.[hash].*.
# Flask serves those bundles at /assets/ (static mount below) and the shell via home(); recipe photos
# live outside the bundle in static/images/ and are served by the /images route.
app = Flask(__name__, static_folder=str(BASE_DIR / "dist" / "assets"), static_url_path="/assets")
# Built assets cache for a year — SAFE because Vite content-hashes every filename, so a changed file
# gets a new name (the cache-bust is the hash). The shell (home()) stays no-cache, so it always
# re-emits the current hashed names. (This replaces the old ?v=<mtime> query-string scheme.)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31_536_000   # 1 year
DB = BASE_DIR / "recipes.db"

# Recipe source tiers the app may edit/delete. 'test' is the scratch/throwaway tier (a removable
# bridge feature — production would use separate dev/staging DBs); 'seed' stays read-only (edit in
# seed.py). Keeping the set in one place holds the create / edit / delete gates in sync.
EDITABLE_SOURCES = ("app", "test")


# Engine cache keyed on the CURRENT DB path (module-global `DB`), so ORM queries hit the database the
# module-global points at — including the test harness's redirect of app.DB. Read at call time (so the
# redirect is honored); one engine reused per path (prod: one; each test's temp DB: its own). Stage 2
# replaces this with a single pooled engine bound to DATABASE_URL.
_engines = {}


def orm_session():
    url = f"sqlite:///{DB}"
    eng = _engines.get(url)
    if eng is None:
        eng = _engines[url] = create_engine(url, future=True)

        # SQLite leaves foreign keys OFF by default, but ON DELETE CASCADE (e.g. deleting a recipe
        # removes its ingredients/steps/ratings/cook_log/changes) only fires with them ON. Enforce
        # per connection — SQLITE ONLY (Stage 2b-1): PRAGMA is a syntax error on Postgres, which
        # enforces FKs + CASCADE always, so on PG the listener is simply not registered (a no-op).
        if eng.dialect.name == "sqlite":
            @event.listens_for(eng, "connect")
            def _fk_on(dbapi_conn, _rec):
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return Session(eng)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def slugify(name):
    """Turn a title into a URL-safe id: 'Andy's Roast Chicken' -> 'andys-roast-chicken'."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)     # drop punctuation
    s = re.sub(r"[\s_]+", "-", s)      # spaces / underscores -> hyphen
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def recipe_stats(s, rid):
    """Derive the cooking stats for a recipe from the log + ratings tables.
    cook_count and last_cooked are computed, never stored, so they can't drift.
    last_cooked_provisional flags that the most-recent cook is provisional — ANY non-app cook
    source (e.g. 'paprika-import', 'rating-inferred'), i.e. a seeded/inferred date rather than
    a confirmed app-logged cook — so the UI can mark it (the '~'/.approx treatment) as a date
    still to be corrected.

    Takes an ORM session (Stage 1c Batch 4): the 5 cook/rating routes call it AFTER their write
    on the SAME session (before commit), so it reads the just-written rows in-transaction."""
    count = s.scalar(select(func.count()).select_from(CookLog).where(CookLog.recipe_id == rid))
    last = s.execute(
        select(CookLog.cooked_on, CookLog.source)
        .where(CookLog.recipe_id == rid)
        .order_by(CookLog.cooked_on.desc(), CookLog.id.desc())
        .limit(1)
    ).first()
    rating_row = s.execute(select(Rating.rating).where(Rating.recipe_id == rid)).first()
    return {
        "cook_count": count,
        "last_cooked": last.cooked_on if last else None,                     # None if never cooked
        "last_cooked_provisional": bool(last and last.source != "app"),
        "rating": rating_row.rating if rating_row else None,
    }


def upsert_rating(s, rid, rating):
    """Set-or-replace a recipe's single rating, stamping rated_on = datetime('now'). Shared by the
    3 rating writers (set_rating, redo_cook, log_cook_and_rate). SQLite-dialect ON CONFLICT(recipe_id)
    upsert; Stage 2b swaps sqlite_insert for the postgresql dialect."""
    stmt = sqlite_insert(Rating).values(recipe_id=rid, rating=rating, rated_on=text("datetime('now')"))
    s.execute(stmt.on_conflict_do_update(
        index_elements=[Rating.recipe_id],
        set_={"rating": stmt.excluded.rating, "rated_on": stmt.excluded.rated_on},
    ))


def changes_for(s, rid):
    """Every saved per-person change for a recipe, grouped by person:

        { person_id: { "edits":     { position: new_qty, ... },
                       "removes":   [ position, ... ],
                       "additions": [ { id, qty, ingredient_id, label, note, raw_text }, ... ] } }

    (JSON turns the integer position keys in "edits" into strings; the front end
    looks them up with the numeric position, which coerces to the same string.)

    Stage 1c: reads via the caller's ORM session `s`, so a write route that calls this after its
    own (uncommitted) writes still sees them (same session/transaction) — as before."""
    changes = {}

    def bucket(person_id):
        return changes.setdefault(person_id, {"edits": {}, "removes": [], "additions": []})

    for row in s.execute(select(
        RecipeLineChange.person_id, RecipeLineChange.position, RecipeLineChange.kind, RecipeLineChange.new_qty
    ).where(RecipeLineChange.recipe_id == rid)).mappings():
        b = bucket(row["person_id"])
        if row["kind"] == "edit":
            b["edits"][row["position"]] = row["new_qty"]
        else:
            b["removes"].append(row["position"])

    for row in s.execute(select(
        RecipeAddition.id, RecipeAddition.person_id, RecipeAddition.qty, RecipeAddition.ingredient_id,
        RecipeAddition.label, RecipeAddition.note, RecipeAddition.raw_text, RecipeAddition.section,
    ).where(RecipeAddition.recipe_id == rid).order_by(RecipeAddition.id)).mappings():
        bucket(row["person_id"])["additions"].append({
            "id": row["id"], "qty": row["qty"], "ingredient_id": row["ingredient_id"],
            "label": row["label"], "note": row["note"], "raw_text": row["raw_text"],
            "section": row["section"],
        })

    return {"changes": changes}


def seed_recipe_person_error(s, rid, pid):
    """Validate that changes are allowed here. Returns (message, status) on failure,
    or None when the recipe is a seed recipe and the person exists. Changes apply
    only to seed recipes, because app recipes you simply edit directly.
    Reads via the caller's ORM session `s` (Stage 1c)."""
    src = s.execute(select(Recipe.source).where(Recipe.id == rid)).scalar_one_or_none()
    if src is None:
        return ("recipe not found", 404)
    if src != "seed":
        return ("changes apply to cookbook (seed) recipes only", 400)
    if s.execute(select(Person.id).where(Person.id == pid)).first() is None:
        return ("unknown person", 404)
    return None


def validate_recipe_payload(s, payload):
    """Return (clean, error). Requires a name, and checks that any *linked*
    ingredient (a line with 'item', or a [[key]] in a step) exists in the library.
    Brand-new ingredients are fine as plain text — they just aren't links.
    Reads via the caller's ORM session `s` (Stage 1c)."""
    name = (payload.get("name") or "").strip()
    if not name:
        return None, "a name is required"
    ingredients = payload.get("ingredients")
    steps = payload.get("steps")
    if not isinstance(ingredients, list) or not isinstance(steps, list):
        return None, "ingredients and steps must be lists"

    known = set(s.scalars(select(Ingredient.id)))

    for row in ingredients:
        item = (row or {}).get("item")
        if item and item not in known:
            return None, f"an ingredient line links to '{item}', which isn't in your library"
    for step in steps:
        text = step if isinstance(step, str) else (step or {}).get("heading", "")
        for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text or ""):
            key = m.group(1).strip()
            if key not in known:
                return None, f"a step links to '{key}', which isn't in your library"
    return {"name": name, "ingredients": ingredients, "steps": steps}, None


def _preserve_key(qty, name):
    """Match key for carrying import-harvested grams/secondary_measure across an edit. Light and
    predictable on purpose: trim + lowercase ONLY, on the quantity and the line's display name
    (its label, or raw_text when there's no label) — keyed identically on both sides. It does NOT
    strip units or fold fractions, so " 1 Cup " matches "1 cup" but "1 cup" != "1 c" (a unit change
    is a real change). `note` is deliberately excluded, so a note-only edit keeps the weight."""
    return ((qty or "").strip().lower(), (name or "").strip().lower())


def _row_qty_parts(row):
    """Resolve (qty, quantity, unit) for an ingredient write — the qty/unit-split hybrid.
    IF the payload row carries explicit `quantity`/`unit` (the Stage-4 editor sends the structured
    parts), they are authoritative and `qty` is their recombination — split_qty's inverse, a normal
    combined string ("3 cups", "4 cloves", "pinch") the untouched scaler parses fine.
    ELSE (Stage 3 / today's client, which sends only `qty`) `qty` is authored and `quantity`/`unit`
    are derived from it via split_qty. Keyed off PRESENCE of the parts, so it stays dormant until a
    client sends them (a normal edit is unchanged)."""
    q, u = row.get("quantity"), row.get("unit")
    if q is not None or u is not None:                 # IF: explicit structured parts -> recombine qty
        quantity, unit = (q or ""), (u or "")
        return (f"{quantity} {unit}").strip(), quantity, unit
    qty = row.get("qty")                               # ELSE: authored qty -> derive the split
    quantity, unit = split_qty(qty)
    return qty, quantity, unit


def write_recipe_rows(s, rid, clean, preserve=None):
    """(Re)write a recipe's ingredient lines and steps from a validated payload.

    `preserve` (edit path only) maps a line's _preserve_key -> (grams, secondary_measure),
    snapshotted from the rows about to be replaced, so an UNCHANGED line keeps its import-harvested
    weight; a changed or new line (key absent) gets NULL — exactly as on create, which passes none.

    Stage 1c: runs on the caller's ORM session `s` (Core delete/insert on the same tables, exact
    column-for-column parity with the prior raw SQL); the caller commits."""
    preserve = preserve or {}
    ri, rs = RecipeIngredient.__table__, RecipeStep.__table__
    s.execute(delete(ri).where(ri.c.recipe_id == rid))
    s.execute(delete(rs).where(rs.c.recipe_id == rid))

    for pos, row in enumerate(clean["ingredients"]):
        row = row or {}
        if row.get("heading"):
            s.execute(insert(ri).values(recipe_id=rid, position=pos, is_heading=1, raw_text=row["heading"]))
        elif row.get("item"):
            label = row.get("label") or row["item"]
            note = row.get("note") or ""
            # Hybrid: recombine qty from explicit parts (Stage-4 editor) or derive the split from the
            # authored qty (Stage 3). preserve/raw_text key off the RESOLVED qty (a recombined change
            # correctly misses the preserve map, clearing stale grams).
            qty, quantity, unit = _row_qty_parts(row)
            grams, secondary = preserve.get(_preserve_key(qty, label), (None, None))
            s.execute(insert(ri).values(
                recipe_id=rid, position=pos, qty=qty, quantity=quantity, unit=unit,
                ingredient_id=row["item"], label=label, note=note,
                raw_text=f"{qty} {label}{note}".strip(), grams=grams, secondary_measure=secondary,
            ))
        else:
            text_val = row.get("text", "") or ""
            note = row.get("note") or ""
            qty, quantity, unit = _row_qty_parts(row)   # hybrid: recombine from parts, or derive from qty
            grams, secondary = preserve.get(_preserve_key(qty, text_val), (None, None))
            s.execute(insert(ri).values(
                recipe_id=rid, position=pos, qty=qty, quantity=quantity, unit=unit,
                raw_text=text_val, note=note, grams=grams, secondary_measure=secondary,
            ))

    for pos, step in enumerate(clean["steps"]):
        if isinstance(step, dict) and step.get("heading"):
            s.execute(insert(rs).values(recipe_id=rid, position=pos, is_heading=1, text=step["heading"]))
        else:
            text_val = step if isinstance(step, str) else ""
            s.execute(insert(rs).values(recipe_id=rid, position=pos, is_heading=0, text=text_val))


@app.route("/")
def home():
    # Serve the Vite-built shell verbatim. It references content-hashed assets (/assets/*.[hash].*),
    # so it stays no-cache (always revalidated → always names the current build), while those hashed
    # assets cache for a year. Requires `npm run build` to have produced dist/index.html.
    html = (BASE_DIR / "dist" / "index.html").read_text(encoding="utf-8")
    resp = app.make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/images/<path:filename>")
def recipe_image(filename):
    # Recipe hero photos live in static/images/ (not the Vite bundle) and are referenced as
    # absolute /images/<file> in the client; serve them from their on-disk home.
    return send_from_directory(BASE_DIR / "static" / "images", filename)


@app.route("/fonts/<path:filename>")
def font_file(filename):
    # In PROD the fonts are bundled+hashed into /assets by Vite, so this route is unused there.
    # In DEV the Vite server proxies /fonts here (styles.css references /fonts/<file>), so the
    # self-hosted faces must be reachable from Flask too — serve them from static/fonts/.
    return send_from_directory(BASE_DIR / "static" / "fonts", filename)


@app.route("/api/recipes")
def list_recipes():
    # Stage 1c (Batch 1): routed through orm_session() (the harness-redirected engine). The list's
    # per-recipe rating/cook_count/last_cooked are correlated scalar subqueries — kept as verbatim SQL
    # via text() for exact-parity (identical COUNT→0 / MAX→NULL / rating→NULL semantics and sort); the
    # SQL is standard and carries to Postgres unchanged. Migrates the DB-access path, not the query.
    with orm_session() as s:
        rows = s.execute(text(
            """SELECT r.id, r.name, r.author, r.category, r.servings,
                      r.prep_time, r.cook_time, r.total_time, r.image, r.created_at, r.source,
                      (SELECT rating FROM ratings WHERE recipe_id = r.id)              AS rating,
                      (SELECT COUNT(*) FROM cook_log WHERE recipe_id = r.id)           AS cook_count,
                      (SELECT MAX(cooked_on) FROM cook_log WHERE recipe_id = r.id)     AS last_cooked
               FROM recipes r
               ORDER BY r.name"""
        )).mappings().all()
    return jsonify([dict(r) for r in rows])


@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    """Create a new app-owned recipe. Rejects a name whose slug already exists."""
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        clean, err = validate_recipe_payload(s, payload)
        if err:
            return jsonify({"error": err}), 400
        slug = slugify(clean["name"])
        if not slug:
            return jsonify({"error": "couldn't make a URL name from that title — try adding letters"}), 400
        if s.execute(select(Recipe.id).where(Recipe.id == slug)).first():
            return jsonify({
                "error": f"a recipe named \u201c{clean['name']}\u201d already exists — please pick a different name"
            }), 409
        source = "test" if payload.get("is_test") else "app"   # only ever 'app' | 'test' from create
        s.execute(insert(Recipe.__table__).values(
            id=slug, name=clean["name"], author=payload.get("author"), source_url=payload.get("source_url"),
            category=payload.get("category"), servings=payload.get("servings"), prep_time=payload.get("prep_time"),
            cook_time=payload.get("cook_time"), total_time=payload.get("total_time"), descr=payload.get("descr"),
            notes=payload.get("notes"), image=payload.get("image"), created_at=now_utc(), source=source,
        ))
        write_recipe_rows(s, slug, clean)
        s.commit()
    return jsonify({"id": slug}), 201


def attach_weights(s, ings):
    """Attach grams_per_ml (or None) to each ingredient-line dict by matching its name
    against the weight table. Matching is server-side (weights.match_weight) so the live
    converter and the build-time coverage report always agree. Headings are left as-is.

    Takes an ORM session (Stage 1c Batch 5); ingredient_weights is a Core Table (no PK), so
    this is a select() on the Table object, not an ORM-class query."""
    rows = s.execute(
        select(
            ingredient_weights.c.lookup_key, ingredient_weights.c.display_name,
            ingredient_weights.c.grams_per_ml, ingredient_weights.c.convert_to_grams,
        )
    ).mappings().all()
    index = build_index(rows)
    out = []
    for x in ings:
        d = dict(x)
        if not d.get("is_heading"):
            m = match_weight(d.get("label") or d.get("raw_text") or "", index)
            # Attach a density only when the chart row opts into gram conversion (013): oils &
            # raw produce match the chart but stay in their authored volume under Metric.
            d["grams_per_ml"] = m[0] if (m and m[2]) else None
        out.append(d)
    return out


def serialize_steps(steps):
    """Attach display spans to each non-heading step (Phase 1d). Raw `text` is kept for the
    editor; `spans` is the render form — {{...}} markup stripped, scalable quantities tagged.
    Headings have no spans."""
    out = []
    for x in steps:
        d = dict(x)
        if not d.get("is_heading"):
            d["spans"] = api_spans(d.get("text") or "")
        out.append(d)
    return out


@app.route("/api/recipes/<rid>")
def get_recipe(rid):
    # Fully ORM (Stage 1c Batch 5, the finale): get_recipe's own reads join the SAME session as its
    # helpers, so the read-only bridge from Batches 3/4 collapses — one orm_session() for the whole read.
    # Core-table selects (SELECT * equivalents) preserve the exact column set/order of the raw rows.
    with orm_session() as s:
        r = s.execute(select(Recipe.__table__).where(Recipe.id == rid)).mappings().first()
        if r is None:
            return jsonify({"error": "recipe not found"}), 404
        ings = s.execute(
            select(RecipeIngredient.__table__).where(RecipeIngredient.recipe_id == rid)
            .order_by(RecipeIngredient.position)
        ).mappings().all()
        steps = s.execute(
            select(RecipeStep.__table__).where(RecipeStep.recipe_id == rid)
            .order_by(RecipeStep.position)
        ).mappings().all()
        people = [
            dict(p) for p in s.execute(
                select(Person.id, Person.name, Person.color).order_by(Person.position, Person.name)
            ).mappings().all()
        ]
        # Only seed recipes carry per-person changes; app recipes are edited directly.
        changes = {}
        if r["source"] == "seed":
            changes = changes_for(s, rid)["changes"]
        stats = recipe_stats(s, rid)
        ingredients = attach_weights(s, ings)
    return jsonify(
        {
            "recipe": dict(r),
            "ingredients": ingredients,
            "steps": serialize_steps(steps),
            "stats": stats,
            "people": people,
            "changes": changes,
            "is_editable": r["source"] in EDITABLE_SOURCES,   # app + test recipes get edit/delete
            "is_seed": r["source"] == "seed",           # seed recipes get the change layers
            "is_test": r["source"] == "test",           # scratch tier — gets the visible test marker
        }
    )


@app.route("/api/recipes/<rid>", methods=["PUT"])
def update_recipe(rid):
    """Edit an app-owned recipe. The slug (id) stays fixed so references don't break."""
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        row = s.execute(select(Recipe.source).where(Recipe.id == rid)).first()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row.source not in EDITABLE_SOURCES:
            return jsonify({"error": "this recipe is from seed.py and is read-only here — edit it in seed.py"}), 403
        clean, err = validate_recipe_payload(s, payload)
        if err:
            return jsonify({"error": err}), 400
        s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rid).values(
            name=clean["name"], author=payload.get("author"), source_url=payload.get("source_url"),
            category=payload.get("category"), servings=payload.get("servings"), prep_time=payload.get("prep_time"),
            cook_time=payload.get("cook_time"), total_time=payload.get("total_time"), descr=payload.get("descr"),
            notes=payload.get("notes"), image=payload.get("image"),
        ))
        # Preserve import-harvested grams/secondary_measure across the edit: snapshot the rows
        # about to be replaced, keyed by (qty, name); write_recipe_rows re-applies them to the
        # UNCHANGED lines (a changed qty/name, or a new line, gets NULL — see write_recipe_rows).
        preserve = {}
        for o in s.execute(select(
            RecipeIngredient.qty, RecipeIngredient.label, RecipeIngredient.raw_text,
            RecipeIngredient.grams, RecipeIngredient.secondary_measure,
        ).where(RecipeIngredient.recipe_id == rid, RecipeIngredient.is_heading == 0)).mappings():
            if o["grams"] is not None or o["secondary_measure"] is not None:
                preserve[_preserve_key(o["qty"], o["label"] or o["raw_text"])] = (o["grams"], o["secondary_measure"])
        write_recipe_rows(s, rid, clean, preserve)
        s.commit()
    return jsonify({"id": rid})


@app.route("/api/recipes/<rid>", methods=["DELETE"])
def delete_recipe(rid):
    """Delete an app-owned recipe. Its ratings, cook history, ingredient lines, and steps
    are removed automatically by ON DELETE CASCADE (foreign keys are enforced per connection
    by orm_session)."""
    with orm_session() as s:
        row = s.execute(select(Recipe.source).where(Recipe.id == rid)).first()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row.source not in EDITABLE_SOURCES:
            return jsonify({"error": "seed recipes can't be deleted here — remove them from seed.py"}), 403
        s.execute(delete(Recipe.__table__).where(Recipe.__table__.c.id == rid))
        s.commit()
    return jsonify({"deleted": rid})


def _unique_copy_id(s, base_name):
    """Mint a distinguishable name + unique slug for a duplicate: '<name> (copy)', then
    '<name> (copy 2)', '(copy 3)', … bumping until the slug is free. Returns (name, slug).
    Reads via the caller's ORM session `s` (Stage 1c)."""
    n = 1
    while True:
        name = base_name + (" (copy)" if n == 1 else f" (copy {n})")
        slug = slugify(name)
        if slug and s.execute(select(Recipe.id).where(Recipe.id == slug)).first() is None:
            return name, slug
        n += 1


@app.route("/api/recipes/<rid>/copy", methods=["POST"])
def copy_recipe(rid):
    """Duplicate a recipe's CONTENT into a new recipe, resetting the accruing layer to zero.
    `is_test` picks the tier (test vs app). The copy starts with no cooks and no rating for free:
    cook_count/last_cooked are DERIVED from cook_log and rating lives in the ratings table — we
    copy neither. Content (incl. import-harvested grams/secondary_measure) is carried by a direct
    row-copy; uid/hash are import identity and left NULL (uid is UNIQUE-indexed — copying it throws)."""
    is_test = bool((request.get_json(silent=True) or {}).get("is_test"))   # thin, self-contained flag
    with orm_session() as s:
        src = s.execute(select(Recipe.__table__).where(Recipe.id == rid)).mappings().first()
        if src is None:
            return jsonify({"error": "recipe not found"}), 404
        new_name, new_id = _unique_copy_id(s, src["name"])
        s.execute(insert(Recipe.__table__).values(
            id=new_id, name=new_name, author=src["author"], source_url=src["source_url"],
            category=src["category"], servings=src["servings"], prep_time=src["prep_time"],
            cook_time=src["cook_time"], total_time=src["total_time"], descr=src["descr"],
            notes=src["notes"], image=src["image"], created_at=now_utc(),
            source=("test" if is_test else "app"), uid=None, hash=None,
        ))
        # Direct row-copy: carries all content INCL. harvested grams/secondary_measure (write_recipe_rows
        # would NULL those). cook_log / ratings / import_flags / per-person tables are deliberately NOT
        # copied — that's what makes the copy start clean. INSERT…SELECT kept verbatim via text() (exact
        # parity; standard SQL, Postgres-portable), executed on the ORM session.
        s.execute(text(
            """INSERT INTO recipe_ingredients
               (recipe_id, position, is_heading, qty, quantity, unit, ingredient_id, label, note, raw_text, grams, secondary_measure)
               SELECT :new_id, position, is_heading, qty, quantity, unit, ingredient_id, label, note, raw_text, grams, secondary_measure
               FROM recipe_ingredients WHERE recipe_id = :rid ORDER BY position"""
        ), {"new_id": new_id, "rid": rid})
        s.execute(text(
            """INSERT INTO recipe_steps (recipe_id, position, is_heading, text)
               SELECT :new_id, position, is_heading, text FROM recipe_steps WHERE recipe_id = :rid ORDER BY position"""
        ), {"new_id": new_id, "rid": rid})
        s.commit()
    return jsonify({"id": new_id}), 201


@app.route("/api/test-recipes", methods=["DELETE"])
def delete_test_recipes():
    """Delete ALL test-tier recipes at once (their children cascade via ON DELETE CASCADE).
    Inherently safe — matches only source='test', never app/seed. Sibling namespace to
    /api/recipes/<rid> so it can't be shadowed by a recipe slugged 'test'."""
    with orm_session() as s:
        n = s.execute(delete(Recipe).where(Recipe.source == "test")).rowcount   # children cascade (FK ON)
        s.commit()
    return jsonify({"deleted": n})


# ---- per-person change layers (seed recipes only) ----

@app.route("/api/people")
def list_people():
    """The people who can keep a version of a recipe — used by the view switcher."""
    with orm_session() as s:
        rows = s.execute(
            select(Person.id, Person.name, Person.color).order_by(Person.position, Person.name)
        ).all()
    return jsonify([dict(r._mapping) for r in rows])


@app.route("/api/recipes/<rid>/people/<pid>/lines/<int:pos>", methods=["PUT"])
def set_line_change(rid, pid, pos):
    """Set this person's change to an existing ingredient line: a new quantity
    (kind='edit', with 'qty') or a removal (kind='remove')."""
    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind")
    with orm_session() as s:
        err = seed_recipe_person_error(s, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        is_line = s.execute(select(RecipeIngredient.id).where(
            RecipeIngredient.recipe_id == rid, RecipeIngredient.position == pos, RecipeIngredient.is_heading == 0
        )).first()
        if not is_line:
            return jsonify({"error": "there's no ingredient line at that position"}), 400

        # SQLite-dialect upsert on the composite PK (recipe_id, person_id, position). The edit branch
        # writes the inserted qty (excluded.new_qty); the remove branch nulls it. An edit-then-edit
        # updates the same row in place (no duplicate). Stage 2b swaps sqlite_insert -> the postgresql
        # dialect's insert().on_conflict_do_update().
        conflict = [RecipeLineChange.recipe_id, RecipeLineChange.person_id, RecipeLineChange.position]
        if kind == "edit":
            qty = (payload.get("qty") or "").strip()
            if not qty:
                return jsonify({"error": "a quantity is required to change a line"}), 400
            stmt = sqlite_insert(RecipeLineChange).values(
                recipe_id=rid, person_id=pid, position=pos, kind="edit", new_qty=qty
            )
            s.execute(stmt.on_conflict_do_update(
                index_elements=conflict, set_={"kind": "edit", "new_qty": stmt.excluded.new_qty},
            ))
        elif kind == "remove":
            stmt = sqlite_insert(RecipeLineChange).values(
                recipe_id=rid, person_id=pid, position=pos, kind="remove", new_qty=None
            )
            s.execute(stmt.on_conflict_do_update(
                index_elements=conflict, set_={"kind": "remove", "new_qty": None},
            ))
        else:
            return jsonify({"error": "kind must be 'edit' or 'remove'"}), 400
        result = changes_for(s, rid)
        s.commit()
    return jsonify(result)


@app.route("/api/recipes/<rid>/people/<pid>/lines/<int:pos>", methods=["DELETE"])
def clear_line_change(rid, pid, pos):
    """Undo this person's change to a line, reverting it to the original."""
    with orm_session() as s:
        err = seed_recipe_person_error(s, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        s.execute(delete(RecipeLineChange).where(
            RecipeLineChange.recipe_id == rid, RecipeLineChange.person_id == pid, RecipeLineChange.position == pos
        ))
        result = changes_for(s, rid)
        s.commit()
    return jsonify(result)


@app.route("/api/recipes/<rid>/people/<pid>/additions", methods=["POST"])
def add_addition(rid, pid):
    """Add a new ingredient line to this person's version. Either link it to a library
    ingredient ('item' = its key) or pass plain 'text'. An optional 'section' (a heading's
    text) places it at the bottom of that section instead of the bottom of the whole list."""
    payload = request.get_json(silent=True) or {}
    item = payload.get("item")
    qty = (payload.get("qty") or "").strip()
    note = (payload.get("note") or "").strip()
    section = (payload.get("section") or "").strip() or None
    with orm_session() as s:
        err = seed_recipe_person_error(s, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        # A section, if given, must match one of this recipe's actual headings.
        if section is not None:
            is_heading = s.execute(select(RecipeIngredient.id).where(
                RecipeIngredient.recipe_id == rid, RecipeIngredient.is_heading == 1, RecipeIngredient.raw_text == section
            )).first()
            if not is_heading:
                return jsonify({"error": "that section isn't a heading in this recipe"}), 400
        if item:
            known_name = s.execute(select(Ingredient.name).where(Ingredient.id == item)).scalar_one_or_none()
            if known_name is None:
                return jsonify({"error": f"'{item}' isn't in your ingredient library"}), 400
            label = (payload.get("label") or known_name).strip()
            s.execute(insert(RecipeAddition.__table__).values(
                recipe_id=rid, person_id=pid, qty=qty, ingredient_id=item, label=label, note=note,
                raw_text=f"{label}{note}".strip(), section=section,
            ))
        else:
            text_val = (payload.get("text") or "").strip()
            if not text_val:
                return jsonify({"error": "type an ingredient, or pick one from your library"}), 400
            s.execute(insert(RecipeAddition.__table__).values(
                recipe_id=rid, person_id=pid, qty=qty, raw_text=text_val, section=section,
            ))
        result = changes_for(s, rid)
        s.commit()
    return jsonify(result)


@app.route("/api/recipes/<rid>/people/<pid>/additions/<int:add_id>", methods=["DELETE"])
def delete_addition(rid, pid, add_id):
    """Remove one of this person's added ingredients."""
    with orm_session() as s:
        err = seed_recipe_person_error(s, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        s.execute(delete(RecipeAddition).where(
            RecipeAddition.id == add_id, RecipeAddition.recipe_id == rid, RecipeAddition.person_id == pid
        ))
        result = changes_for(s, rid)
        s.commit()
    return jsonify(result)


# ---- ingredient field guide ----

@app.route("/api/ingredients")
def list_ingredients():
    """The whole library as {id, name} — used to populate the recipe form and the
    'add ingredient' picker in a person's version."""
    with orm_session() as s:
        rows = s.execute(select(Ingredient.id, Ingredient.name).order_by(Ingredient.name)).all()
    return jsonify([dict(r._mapping) for r in rows])


@app.route("/api/ingredients/<iid>")
def get_ingredient(iid):
    with orm_session() as s:
        ing = s.execute(select(Ingredient.__table__).where(Ingredient.id == iid)).first()
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404

        season = list(s.scalars(
            select(IngredientSeason.month)
            .where(IngredientSeason.ingredient_id == iid)
            .order_by(IngredientSeason.month)
        ))
        regions = list(s.scalars(
            select(Region.name)
            .join(IngredientRegion, IngredientRegion.region_id == Region.id)
            .where(IngredientRegion.ingredient_id == iid)
            .order_by(IngredientRegion.position)
        ))
        used = s.execute(
            select(Recipe.id, Recipe.name)
            .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
            .where(RecipeIngredient.ingredient_id == iid)
            .distinct()
            .order_by(Recipe.name)
        ).all()

    d = dict(ing._mapping)
    d["season"] = season
    d["regions"] = regions
    d["used_in"] = [dict(u._mapping) for u in used]
    return jsonify(d)


@app.route("/api/in-season")
@app.route("/api/in-season/<int:month>")
def in_season(month=None):
    if month is None:
        month = datetime.date.today().month
    with orm_session() as s:
        rows = s.execute(
            select(Ingredient.id, Ingredient.name)
            .join(IngredientSeason, IngredientSeason.ingredient_id == Ingredient.id)
            .where(IngredientSeason.month == month)
            .order_by(Ingredient.name)
        ).all()
    return jsonify({"month": month, "ingredients": [dict(r._mapping) for r in rows]})


# ---- cooking log + ratings ----

@app.route("/api/recipes/<rid>/cooked", methods=["POST"])
def log_cook(rid):
    """Record that you cooked this today (or on an optional given past date). A supplied
    date must be a real YYYY-MM-DD calendar date, not in the future; source stays 'app'
    (a backdated cook is still a real logged cook)."""
    payload = request.get_json(silent=True) or {}
    cooked_on = payload.get("date")  # optional 'YYYY-MM-DD'; otherwise defaults to today
    if cooked_on is not None:
        try:
            supplied = datetime.date.fromisoformat(cooked_on)
        except (ValueError, TypeError):
            return jsonify({"error": "date must be a real date in YYYY-MM-DD form"}), 400
        if supplied > datetime.date.today():
            return jsonify({"error": "cook date cannot be in the future"}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        cl = CookLog.__table__
        if cooked_on:
            s.execute(insert(cl).values(recipe_id=rid, cooked_on=cooked_on))
        else:
            s.execute(insert(cl).values(recipe_id=rid))   # cooked_on omitted -> DB default date('now')
        stats = recipe_stats(s, rid)
        s.commit()
    return jsonify(stats)


@app.route("/api/recipes/<rid>/uncook", methods=["POST"])
def undo_cook(rid):
    """Remove the most recent cook entry — for fixing an accidental tap. If this returns the recipe
    to uncooked (cook_count -> 0), also clear its rating in the same transaction, so we never leave
    an uncooked-but-rated recipe (the inconsistency the cook-gate prevents). If other cooks remain,
    the rating stands — you've still cooked it."""
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        last = s.execute(
            select(CookLog.id, CookLog.cooked_on, CookLog.source)
            .where(CookLog.recipe_id == rid).order_by(CookLog.id.desc()).limit(1)
        ).first()
        undone = None   # what this undo removed, so a one-shot redo can reverse exactly it
        if last:
            s.execute(delete(CookLog).where(CookLog.id == last.id))
            remaining = s.scalar(   # counted AFTER the delete — drop the rating iff this undo hit 0 cooks
                select(func.count()).select_from(CookLog).where(CookLog.recipe_id == rid)
            )
            cleared_rating = None
            if remaining == 0:
                rr = s.execute(select(Rating.rating).where(Rating.recipe_id == rid)).first()
                cleared_rating = rr.rating if rr else None
                s.execute(delete(Rating).where(Rating.recipe_id == rid))   # back to uncooked -> drop the rating
            undone = {"cooked_on": last.cooked_on, "source": last.source, "cleared_rating": cleared_rating}
        stats = recipe_stats(s, rid)
        s.commit()
    return jsonify({**stats, "undone": undone})


COOK_SOURCES = ("app", "paprika-import", "rating-inferred")


@app.route("/api/recipes/<rid>/redo-cook", methods=["POST"])
def redo_cook(rid):
    """Restore a cook that /uncook just removed — the SAME cooked_on and source (not a new
    today's cook), and optionally re-set a rating the undo cleared. Makes the redo arrow a
    faithful one-shot reversal of that specific undo. /cooked and /uncook are unchanged.
    All client-supplied inputs are validated (real non-future date; known source; rating in
    range) and nothing is written on bad input."""
    payload = request.get_json(silent=True) or {}
    cooked_on = payload.get("cooked_on")
    source = payload.get("source")
    rating = payload.get("rating")   # optional: only when the undo cleared a rating
    try:
        restored = datetime.date.fromisoformat(cooked_on) if cooked_on else None
    except (ValueError, TypeError):
        restored = None
    if restored is None:
        return jsonify({"error": "cooked_on must be a real date in YYYY-MM-DD form"}), 400
    if restored > datetime.date.today():
        return jsonify({"error": "cook date cannot be in the future"}), 400
    if source not in COOK_SOURCES:
        return jsonify({"error": "unknown cook source"}), 400
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "rating must be an integer from 1 to 5"}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        s.execute(insert(CookLog.__table__).values(recipe_id=rid, cooked_on=cooked_on, source=source))
        if rating is not None:
            upsert_rating(s, rid, rating)
        stats = recipe_stats(s, rid)
        s.commit()
    return jsonify(stats)


@app.route("/api/recipes/<rid>/rating", methods=["POST"])
def set_rating(rid):
    """Set (or change) your 1-5 rating for a recipe."""
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    if rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "rating must be an integer from 1 to 5"}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        upsert_rating(s, rid, rating)   # NOT cook-gated: rating an uncooked recipe is allowed (as before)
        stats = recipe_stats(s, rid)
        s.commit()
    return jsonify(stats)


@app.route("/api/recipes/<rid>/cooked-and-rated", methods=["POST"])
def log_cook_and_rate(rid):
    """Atomically log a cook (today; source defaults to 'app' — a real confirmed cook) AND set the
    rating, in one transaction. The cook-gated 'Mark cooked & rate?' path; returns recipe_stats."""
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    if rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "rating must be an integer from 1 to 5"}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        s.execute(insert(CookLog.__table__).values(recipe_id=rid))   # today's cook, source default 'app'
        upsert_rating(s, rid, rating)
        stats = recipe_stats(s, rid)
        s.commit()
    return jsonify(stats)


if __name__ == "__main__":
    app.run(port=8000, debug=True)
