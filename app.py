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
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from weights import build_index, match_weight
from stepscale import api_spans

# Anchor everything to this file's folder so the app runs from any directory.
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="")
DB = BASE_DIR / "recipes.db"


def db():
    # Open a fresh connection to the database file.
    conn = sqlite3.connect(DB)
    # row_factory = Row lets us read a column by name (row["name"]) instead of by
    # numeric position (row[0]) — easier to read and less error-prone.
    conn.row_factory = sqlite3.Row
    # Turn on foreign-key enforcement (SQLite leaves it off by default). With it on,
    # deleting a recipe cascades to its ingredient/step/change rows automatically.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def slugify(name):
    """Turn a title into a URL-safe id: 'Andy's Roast Chicken' -> 'andys-roast-chicken'."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)     # drop punctuation
    s = re.sub(r"[\s_]+", "-", s)      # spaces / underscores -> hyphen
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def recipe_stats(c, rid):
    """Derive the cooking stats for a recipe from the log + ratings tables.
    cook_count and last_cooked are computed, never stored, so they can't drift.
    last_cooked_provisional flags that the most-recent cook is provisional — ANY non-app cook
    source (e.g. 'paprika-import', 'rating-inferred'), i.e. a seeded/inferred date rather than
    a confirmed app-logged cook — so the UI can mark it (the '~'/.approx treatment) as a date
    still to be corrected."""
    count = c.execute(
        "SELECT COUNT(*) AS n FROM cook_log WHERE recipe_id = ?", (rid,)
    ).fetchone()["n"]
    last = c.execute(
        "SELECT cooked_on, source FROM cook_log WHERE recipe_id = ? ORDER BY cooked_on DESC, id DESC LIMIT 1",
        (rid,),
    ).fetchone()
    rating_row = c.execute("SELECT rating FROM ratings WHERE recipe_id = ?", (rid,)).fetchone()
    return {
        "cook_count": count,
        "last_cooked": last["cooked_on"] if last else None,                  # None if never cooked
        "last_cooked_provisional": bool(last and last["source"] != "app"),
        "rating": rating_row["rating"] if rating_row else None,
    }


def changes_for(c, rid):
    """Every saved per-person change for a recipe, grouped by person:

        { person_id: { "edits":     { position: new_qty, ... },
                       "removes":   [ position, ... ],
                       "additions": [ { id, qty, ingredient_id, label, note, raw_text }, ... ] } }

    (JSON turns the integer position keys in "edits" into strings; the front end
    looks them up with the numeric position, which coerces to the same string.)
    """
    changes = {}

    def bucket(person_id):
        return changes.setdefault(person_id, {"edits": {}, "removes": [], "additions": []})

    for row in c.execute(
        "SELECT person_id, position, kind, new_qty FROM recipe_line_changes WHERE recipe_id = ?",
        (rid,),
    ):
        b = bucket(row["person_id"])
        if row["kind"] == "edit":
            b["edits"][row["position"]] = row["new_qty"]
        else:
            b["removes"].append(row["position"])

    for row in c.execute(
        """SELECT id, person_id, qty, ingredient_id, label, note, raw_text, section
           FROM recipe_additions WHERE recipe_id = ? ORDER BY id""",
        (rid,),
    ):
        bucket(row["person_id"])["additions"].append({
            "id": row["id"], "qty": row["qty"], "ingredient_id": row["ingredient_id"],
            "label": row["label"], "note": row["note"], "raw_text": row["raw_text"],
            "section": row["section"],
        })

    return {"changes": changes}


def seed_recipe_person_error(c, rid, pid):
    """Validate that changes are allowed here. Returns (message, status) on failure,
    or None when the recipe is a seed recipe and the person exists. Changes apply
    only to seed recipes, because app recipes you simply edit directly."""
    r = c.execute("SELECT source FROM recipes WHERE id = ?", (rid,)).fetchone()
    if r is None:
        return ("recipe not found", 404)
    if r["source"] != "seed":
        return ("changes apply to cookbook (seed) recipes only", 400)
    if c.execute("SELECT 1 FROM people WHERE id = ?", (pid,)).fetchone() is None:
        return ("unknown person", 404)
    return None


def validate_recipe_payload(c, payload):
    """Return (clean, error). Requires a name, and checks that any *linked*
    ingredient (a line with 'item', or a [[key]] in a step) exists in the library.
    Brand-new ingredients are fine as plain text — they just aren't links."""
    name = (payload.get("name") or "").strip()
    if not name:
        return None, "a name is required"
    ingredients = payload.get("ingredients")
    steps = payload.get("steps")
    if not isinstance(ingredients, list) or not isinstance(steps, list):
        return None, "ingredients and steps must be lists"

    known = {row[0] for row in c.execute("SELECT id FROM ingredients")}

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


def write_recipe_rows(c, rid, clean, preserve=None):
    """(Re)write a recipe's ingredient lines and steps from a validated payload.

    `preserve` (edit path only) maps a line's _preserve_key -> (grams, secondary_measure),
    snapshotted from the rows about to be replaced, so an UNCHANGED line keeps its import-harvested
    weight; a changed or new line (key absent) gets NULL — exactly as on create, which passes none."""
    preserve = preserve or {}
    c.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (rid,))
    c.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (rid,))

    for pos, row in enumerate(clean["ingredients"]):
        row = row or {}
        if row.get("heading"):
            c.execute(
                "INSERT INTO recipe_ingredients (recipe_id, position, is_heading, raw_text) VALUES (?,?,1,?)",
                (rid, pos, row["heading"]),
            )
        elif row.get("item"):
            label = row.get("label") or row["item"]
            note = row.get("note") or ""
            grams, secondary = preserve.get(_preserve_key(row.get("qty"), label), (None, None))
            c.execute(
                """INSERT INTO recipe_ingredients
                   (recipe_id, position, qty, ingredient_id, label, note, raw_text, grams, secondary_measure)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (rid, pos, row.get("qty"), row["item"], label, note,
                 f"{row.get('qty','')} {label}{note}".strip(), grams, secondary),
            )
        else:
            text = row.get("text", "") or ""
            grams, secondary = preserve.get(_preserve_key(row.get("qty"), text), (None, None))
            c.execute(
                "INSERT INTO recipe_ingredients (recipe_id, position, qty, raw_text, grams, secondary_measure) VALUES (?,?,?,?,?,?)",
                (rid, pos, row.get("qty"), text, grams, secondary),
            )

    for pos, step in enumerate(clean["steps"]):
        if isinstance(step, dict) and step.get("heading"):
            c.execute(
                "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,1,?)",
                (rid, pos, step["heading"]),
            )
        else:
            text = step if isinstance(step, str) else ""
            c.execute(
                "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,0,?)",
                (rid, pos, text),
            )


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/recipes")
def list_recipes():
    with db() as c:
        rows = c.execute(
            """SELECT r.id, r.name, r.author, r.category, r.servings,
                      r.prep_time, r.cook_time, r.total_time, r.image, r.created_at, r.source,
                      (SELECT rating FROM ratings WHERE recipe_id = r.id)              AS rating,
                      (SELECT COUNT(*) FROM cook_log WHERE recipe_id = r.id)           AS cook_count,
                      (SELECT MAX(cooked_on) FROM cook_log WHERE recipe_id = r.id)     AS last_cooked
               FROM recipes r
               ORDER BY r.name"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    """Create a new app-owned recipe. Rejects a name whose slug already exists."""
    payload = request.get_json(silent=True) or {}
    with db() as c:
        clean, err = validate_recipe_payload(c, payload)
        if err:
            return jsonify({"error": err}), 400
        slug = slugify(clean["name"])
        if not slug:
            return jsonify({"error": "couldn't make a URL name from that title — try adding letters"}), 400
        if c.execute("SELECT 1 FROM recipes WHERE id = ?", (slug,)).fetchone():
            return jsonify({
                "error": f"a recipe named \u201c{clean['name']}\u201d already exists — please pick a different name"
            }), 409
        c.execute(
            """INSERT INTO recipes
               (id, name, author, source_url, category, servings, prep_time,
                cook_time, total_time, descr, notes, image, created_at, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'app')""",
            (slug, clean["name"], payload.get("author"), payload.get("source_url"),
             payload.get("category"), payload.get("servings"), payload.get("prep_time"),
             payload.get("cook_time"), payload.get("total_time"), payload.get("descr"),
             payload.get("notes"), payload.get("image"), now_utc()),
        )
        write_recipe_rows(c, slug, clean)
    return jsonify({"id": slug}), 201


def attach_weights(c, ings):
    """Attach grams_per_ml (or None) to each ingredient-line dict by matching its name
    against the weight table. Matching is server-side (weights.match_weight) so the live
    converter and the build-time coverage report always agree. Headings are left as-is."""
    rows = c.execute(
        "SELECT lookup_key, display_name, grams_per_ml, convert_to_grams FROM ingredient_weights"
    ).fetchall()
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
    with db() as c:
        r = c.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone()
        if r is None:
            return jsonify({"error": "recipe not found"}), 404
        ings = c.execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY position", (rid,)
        ).fetchall()
        steps = c.execute(
            "SELECT * FROM recipe_steps WHERE recipe_id = ? ORDER BY position", (rid,)
        ).fetchall()
        people = [
            dict(p) for p in
            c.execute("SELECT id, name, color FROM people ORDER BY position, name")
        ]
        # Only seed recipes carry per-person changes; app recipes are edited directly.
        changes = changes_for(c, rid)["changes"] if r["source"] == "seed" else {}
        stats = recipe_stats(c, rid)   # computed here, while the connection is open
    return jsonify(
        {
            "recipe": dict(r),
            "ingredients": attach_weights(c, ings),
            "steps": serialize_steps(steps),
            "stats": stats,
            "people": people,
            "changes": changes,
            "is_editable": r["source"] == "app",       # app recipes get edit/delete
            "is_seed": r["source"] == "seed",           # seed recipes get the change layers
        }
    )


@app.route("/api/recipes/<rid>", methods=["PUT"])
def update_recipe(rid):
    """Edit an app-owned recipe. The slug (id) stays fixed so references don't break."""
    payload = request.get_json(silent=True) or {}
    with db() as c:
        row = c.execute("SELECT source FROM recipes WHERE id = ?", (rid,)).fetchone()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row["source"] != "app":
            return jsonify({"error": "this recipe is from seed.py and is read-only here — edit it in seed.py"}), 403
        clean, err = validate_recipe_payload(c, payload)
        if err:
            return jsonify({"error": err}), 400
        c.execute(
            """UPDATE recipes SET
                name=?, author=?, source_url=?, category=?, servings=?, prep_time=?,
                cook_time=?, total_time=?, descr=?, notes=?, image=?
                WHERE id=?""",
            (clean["name"], payload.get("author"), payload.get("source_url"),
             payload.get("category"), payload.get("servings"), payload.get("prep_time"),
             payload.get("cook_time"), payload.get("total_time"), payload.get("descr"),
             payload.get("notes"), payload.get("image"), rid),
        )
        # Preserve import-harvested grams/secondary_measure across the edit: snapshot the rows
        # about to be replaced, keyed by (qty, name); write_recipe_rows re-applies them to the
        # UNCHANGED lines (a changed qty/name, or a new line, gets NULL — see write_recipe_rows).
        preserve = {}
        for o in c.execute(
            "SELECT qty, label, raw_text, grams, secondary_measure "
            "FROM recipe_ingredients WHERE recipe_id = ? AND is_heading = 0", (rid,)
        ):
            if o["grams"] is not None or o["secondary_measure"] is not None:
                preserve[_preserve_key(o["qty"], o["label"] or o["raw_text"])] = (o["grams"], o["secondary_measure"])
        write_recipe_rows(c, rid, clean, preserve)
    return jsonify({"id": rid})


@app.route("/api/recipes/<rid>", methods=["DELETE"])
def delete_recipe(rid):
    """Delete an app-owned recipe. Its ratings, cook history, ingredient lines, and steps
    are removed automatically by ON DELETE CASCADE (foreign keys are on, set in db())."""
    with db() as c:
        row = c.execute("SELECT source FROM recipes WHERE id = ?", (rid,)).fetchone()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row["source"] != "app":
            return jsonify({"error": "seed recipes can't be deleted here — remove them from seed.py"}), 403
        c.execute("DELETE FROM recipes WHERE id = ?", (rid,))
    return jsonify({"deleted": rid})


# ---- per-person change layers (seed recipes only) ----

@app.route("/api/people")
def list_people():
    """The people who can keep a version of a recipe — used by the view switcher."""
    with db() as c:
        rows = c.execute("SELECT id, name, color FROM people ORDER BY position, name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/recipes/<rid>/people/<pid>/lines/<int:pos>", methods=["PUT"])
def set_line_change(rid, pid, pos):
    """Set this person's change to an existing ingredient line: a new quantity
    (kind='edit', with 'qty') or a removal (kind='remove')."""
    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind")
    with db() as c:
        err = seed_recipe_person_error(c, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        is_line = c.execute(
            "SELECT 1 FROM recipe_ingredients WHERE recipe_id = ? AND position = ? AND is_heading = 0",
            (rid, pos),
        ).fetchone()
        if not is_line:
            return jsonify({"error": "there's no ingredient line at that position"}), 400

        if kind == "edit":
            qty = (payload.get("qty") or "").strip()
            if not qty:
                return jsonify({"error": "a quantity is required to change a line"}), 400
            c.execute(
                """INSERT INTO recipe_line_changes (recipe_id, person_id, position, kind, new_qty)
                VALUES (?, ?, ?, 'edit', ?)
                ON CONFLICT(recipe_id, person_id, position)
                DO UPDATE SET kind = 'edit', new_qty = excluded.new_qty""",
                (rid, pid, pos, qty),
            )
        elif kind == "remove":
            c.execute(
                """INSERT INTO recipe_line_changes (recipe_id, person_id, position, kind, new_qty)
                VALUES (?, ?, ?, 'remove', NULL)
                ON CONFLICT(recipe_id, person_id, position)
                DO UPDATE SET kind = 'remove', new_qty = NULL""",
                (rid, pid, pos),
            )
        else:
            return jsonify({"error": "kind must be 'edit' or 'remove'"}), 400
        result = changes_for(c, rid)
    return jsonify(result)


@app.route("/api/recipes/<rid>/people/<pid>/lines/<int:pos>", methods=["DELETE"])
def clear_line_change(rid, pid, pos):
    """Undo this person's change to a line, reverting it to the original."""
    with db() as c:
        err = seed_recipe_person_error(c, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        c.execute(
            "DELETE FROM recipe_line_changes WHERE recipe_id = ? AND person_id = ? AND position = ?",
            (rid, pid, pos),
        )
        result = changes_for(c, rid)
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
    with db() as c:
        err = seed_recipe_person_error(c, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        # A section, if given, must match one of this recipe's actual headings.
        if section is not None:
            is_heading = c.execute(
                "SELECT 1 FROM recipe_ingredients WHERE recipe_id = ? AND is_heading = 1 AND raw_text = ?",
                (rid, section),
            ).fetchone()
            if not is_heading:
                return jsonify({"error": "that section isn't a heading in this recipe"}), 400
        if item:
            known = c.execute("SELECT name FROM ingredients WHERE id = ?", (item,)).fetchone()
            if known is None:
                return jsonify({"error": f"'{item}' isn't in your ingredient library"}), 400
            label = (payload.get("label") or known["name"]).strip()
            c.execute(
                """INSERT INTO recipe_additions
                   (recipe_id, person_id, qty, ingredient_id, label, note, raw_text, section)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rid, pid, qty, item, label, note, f"{label}{note}".strip(), section),
            )
        else:
            text = (payload.get("text") or "").strip()
            if not text:
                return jsonify({"error": "type an ingredient, or pick one from your library"}), 400
            c.execute(
                "INSERT INTO recipe_additions (recipe_id, person_id, qty, raw_text, section) VALUES (?, ?, ?, ?, ?)",
                (rid, pid, qty, text, section),
            )
        result = changes_for(c, rid)
    return jsonify(result)


@app.route("/api/recipes/<rid>/people/<pid>/additions/<int:add_id>", methods=["DELETE"])
def delete_addition(rid, pid, add_id):
    """Remove one of this person's added ingredients."""
    with db() as c:
        err = seed_recipe_person_error(c, rid, pid)
        if err:
            return jsonify({"error": err[0]}), err[1]
        c.execute(
            "DELETE FROM recipe_additions WHERE id = ? AND recipe_id = ? AND person_id = ?",
            (add_id, rid, pid),
        )
        result = changes_for(c, rid)
    return jsonify(result)


# ---- ingredient field guide ----

@app.route("/api/ingredients")
def list_ingredients():
    """The whole library as {id, name} — used to populate the recipe form and the
    'add ingredient' picker in a person's version."""
    with db() as c:
        rows = c.execute("SELECT id, name FROM ingredients ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/ingredients/<iid>")
def get_ingredient(iid):
    with db() as c:
        ing = c.execute("SELECT * FROM ingredients WHERE id = ?", (iid,)).fetchone()
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404

        season = [
            row["month"]
            for row in c.execute(
                "SELECT month FROM ingredient_seasons WHERE ingredient_id = ? ORDER BY month",
                (iid,),
            )
        ]
        regions = [
            row["name"]
            for row in c.execute(
                """SELECT rg.name
                   FROM ingredient_regions ir
                   JOIN regions rg ON rg.id = ir.region_id
                   WHERE ir.ingredient_id = ?
                   ORDER BY ir.position""",
                (iid,),
            )
        ]
        used = c.execute(
            """SELECT DISTINCT r.id, r.name
               FROM recipes r
               JOIN recipe_ingredients ri ON ri.recipe_id = r.id
               WHERE ri.ingredient_id = ?
               ORDER BY r.name""",
            (iid,),
        ).fetchall()

    d = dict(ing)
    d["season"] = season
    d["regions"] = regions
    d["used_in"] = [dict(u) for u in used]
    return jsonify(d)


@app.route("/api/in-season")
@app.route("/api/in-season/<int:month>")
def in_season(month=None):
    if month is None:
        month = datetime.date.today().month
    with db() as c:
        rows = c.execute(
            """SELECT i.id, i.name
               FROM ingredients i
               JOIN ingredient_seasons s ON s.ingredient_id = i.id
               WHERE s.month = ?
               ORDER BY i.name""",
            (month,),
        ).fetchall()
    return jsonify({"month": month, "ingredients": [dict(r) for r in rows]})


# ---- cooking log + ratings ----

@app.route("/api/recipes/<rid>/cooked", methods=["POST"])
def log_cook(rid):
    """Record that you cooked this today (or on an optional given date)."""
    payload = request.get_json(silent=True) or {}
    cooked_on = payload.get("date")  # optional 'YYYY-MM-DD'; otherwise defaults to today
    with db() as c:
        if c.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone() is None:
            return jsonify({"error": "recipe not found"}), 404
        if cooked_on:
            c.execute("INSERT INTO cook_log (recipe_id, cooked_on) VALUES (?, ?)", (rid, cooked_on))
        else:
            c.execute("INSERT INTO cook_log (recipe_id) VALUES (?)", (rid,))
        stats = recipe_stats(c, rid)
    return jsonify(stats)


@app.route("/api/recipes/<rid>/uncook", methods=["POST"])
def undo_cook(rid):
    """Remove the most recent cook entry — for fixing an accidental tap. If this returns the recipe
    to uncooked (cook_count -> 0), also clear its rating in the same transaction, so we never leave
    an uncooked-but-rated recipe (the inconsistency the cook-gate prevents). If other cooks remain,
    the rating stands — you've still cooked it."""
    with db() as c:
        if c.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone() is None:
            return jsonify({"error": "recipe not found"}), 404
        last = c.execute(
            "SELECT id FROM cook_log WHERE recipe_id = ? ORDER BY id DESC LIMIT 1", (rid,)
        ).fetchone()
        if last:
            c.execute("DELETE FROM cook_log WHERE id = ?", (last["id"],))
            remaining = c.execute(
                "SELECT COUNT(*) AS n FROM cook_log WHERE recipe_id = ?", (rid,)
            ).fetchone()["n"]
            if remaining == 0:
                c.execute("DELETE FROM ratings WHERE recipe_id = ?", (rid,))   # back to uncooked -> drop the rating
        stats = recipe_stats(c, rid)
    return jsonify(stats)


@app.route("/api/recipes/<rid>/rating", methods=["POST"])
def set_rating(rid):
    """Set (or change) your 1-5 rating for a recipe."""
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    if rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "rating must be an integer from 1 to 5"}), 400
    with db() as c:
        if c.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone() is None:
            return jsonify({"error": "recipe not found"}), 404
        c.execute(
            """INSERT INTO ratings (recipe_id, rating, rated_on)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(recipe_id) DO UPDATE SET rating = excluded.rating, rated_on = excluded.rated_on""",
            (rid, rating),
        )
        stats = recipe_stats(c, rid)
    return jsonify(stats)


@app.route("/api/recipes/<rid>/cooked-and-rated", methods=["POST"])
def log_cook_and_rate(rid):
    """Atomically log a cook (today; source defaults to 'app' — a real confirmed cook) AND set the
    rating, in one transaction. The cook-gated 'Mark cooked & rate?' path; returns recipe_stats."""
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    if rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "rating must be an integer from 1 to 5"}), 400
    with db() as c:
        if c.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone() is None:
            return jsonify({"error": "recipe not found"}), 404
        c.execute("INSERT INTO cook_log (recipe_id) VALUES (?)", (rid,))
        c.execute(
            """INSERT INTO ratings (recipe_id, rating, rated_on)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(recipe_id) DO UPDATE SET rating = excluded.rating, rated_on = excluded.rated_on""",
            (rid, rating),
        )
        stats = recipe_stats(c, rid)
    return jsonify(stats)


if __name__ == "__main__":
    app.run(port=8000, debug=True)
