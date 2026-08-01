#!/usr/bin/env python3
"""app.py — the backend.

It does two jobs:
  1. serves the static page (static/index.html, app.js, styles.css)
  2. answers a small JSON API that runs the SQLite queries

Recipes can be created/edited/deleted in the app (source='app'); recipes from
seed.py (source='seed') are read-only here (edit them in seed.py).

Run it with:  python3 app.py   then open http://localhost:8000
"""
import datetime
import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_login import LoginManager, current_user
from sqlalchemy import create_engine, delete, event, func, insert, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert       # dialect-agnostic upserts (2b-2):
from sqlalchemy.dialects.postgresql import insert as pg_insert       # pick per engine dialect at runtime
from sqlalchemy.orm import Session

from weights import build_index, match_weight
from stepscale import api_spans
from import_cleanup import split_qty   # shared qty->quantity+unit split (backfill/seed/import use it too)
# SQLAlchemy migration (Stage 1 complete): the entire serve path queries through orm_session() below —
# reads, writes, and the 5 SQLite-dialect upserts. Build-time modules (build_db/import/migrate) keep
# their own raw sqlite3 connections (out of Stage 1 scope). Stage 2 swaps the engine to Postgres
# (see docs/migration-plan.md).
from models import (
    Ingredient, IngredientSeason, IngredientRegion, Region, Recipe, RecipeIngredient, RecipeStep,
    Rating, CookLog, CookPhoto, User, Friendship, SharedPost, Comment, RecipeQueue, ingredient_weights,
)
from auth import auth_bp   # JSON auth endpoints (auth-2); auth.py imports models only, so no import cycle
import images              # shared image brain: resize + the save_image storage seam (Stage 1/2)

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
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024    # S7: 10 MB wire cap -> 413 before decode (upload guard)
DB = BASE_DIR / "recipes.db"

# --- authentication (auth-2): Flask-Login + a server-side session cookie -------------------------
# SECRET_KEY signs the session cookie Flask-Login uses. FAIL CLOSED (docs/SECURITY.md): production is
# signalled by a Postgres DATABASE_URL — the SAME switch that selects the prod database (CLAUDE.md) — so
# there we REQUIRE SECRET_KEY from the env and REFUSE TO START if it's unset, rather than sign sessions
# with a publicly-known dev key (which would make every session forgeable). Locally / in tests (SQLite,
# DATABASE_URL unset) a clearly dev-only fallback is used; it is structurally unable to reach production
# because the moment DATABASE_URL points at Postgres the fallback is rejected. (So running Postgres
# locally also requires SECRET_KEY — correct: you can't drive the prod DB with a dev session key.)
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    if (os.environ.get("DATABASE_URL") or "").startswith("postgresql"):
        raise RuntimeError(
            "SECRET_KEY must be set when DATABASE_URL is Postgres (production): refusing to start with "
            "the dev-only fallback, which would sign session cookies with a publicly-known key."
        )
    _secret_key = "dev-only-not-a-secret-set-SECRET_KEY-in-prod"   # dev/test ONLY (SQLite); see above
app.config["SECRET_KEY"] = _secret_key

login_manager = LoginManager()
login_manager.init_app(app)
app.register_blueprint(auth_bp)   # /api/signup | /api/login | /api/logout | /api/me (all public; auth-3 gates the rest)


@login_manager.unauthorized_handler
def _unauthorized():
    # This is a JSON API, not a server-rendered app: answer an unauthenticated request with 401 JSON,
    # never a 302 redirect to a login page. Fired by the before_request gate below and by @login_required.
    return jsonify({"error": "authentication required"}), 401


# Routes reachable WITHOUT login: the SPA shell + its hashed assets/images/fonts (so the login page can
# load before anyone is authenticated) and the auth entry points. EVERYTHING else — all /api/* reads and
# writes — requires login (auth-3b; the pilot is private, so reads are gated too). /api/invites is
# ADDITIONALLY admin-gated by its own @admin_required (a logged-in non-admin gets 403 there, not 401).
# Keyed on request.endpoint (not the path) so it's robust to URL params and can't be defeated by casing.
PUBLIC_ENDPOINTS = frozenset({
    "home", "static", "recipe_image", "font_file",     # SPA shell + /assets, /images, /fonts
    "auth.login", "auth.signup", "auth.me",            # log in / sign up / "who am I" (returns {user:null})
})


@app.before_request
def _require_login():
    # Fail-closed default-deny (docs/SECURITY.md): any matched route NOT on the allowlist needs a
    # logged-in user. New routes are therefore gated by default (you must opt INTO public), the safe way.
    if request.endpoint is None:                       # unmatched path → let Flask 404 (don't 401 typos)
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not current_user.is_authenticated:
        return jsonify({"error": "authentication required"}), 401
    return None


# Recipe source tiers the app may edit/delete. 'test' is the scratch/throwaway tier (a removable
# bridge feature — production would use separate dev/staging DBs); 'seed' stays read-only (edit in
# seed.py). Keeping the set in one place holds the create / edit / delete gates in sync.
EDITABLE_SOURCES = ("app", "test")


# Engine cache keyed on the resolved URL, so ORM queries hit the intended database and each URL reuses
# one engine (prod: one; each test's temp DB: its own). Read at call time so BOTH env-driven overrides
# and the test harness's redirect of the module-global `DB` are honored (never frozen at import).
_engines = {}


def orm_session():
    # Stage 2b-3: env-driven, reversible. DATABASE_URL set (e.g. postgresql+psycopg://…) overrides;
    # UNSET falls back to sqlite:///<DB> composed from the LIVE module-global DB — which the test
    # harness (make_kitchen) rebinds per test, so reading it at call time keeps the redirect working
    # (freezing it would silently hit the real recipes.db — the Stage-1b miss). Default = today's SQLite.
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{DB}"
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


@login_manager.user_loader
def load_user(user_id):
    # Flask-Login stores get_id() (str(id)) in the session cookie; this reloads the User on each request
    # via the SAME call-time orm_session() (so it honors DATABASE_URL + the test-harness DB redirect,
    # never a frozen engine). Returns a detached User with all columns loaded — fine for current_user's
    # attribute reads — or None if the id is unknown (a stale/forged cookie → treated as logged out).
    with orm_session() as s:
        return s.get(User, int(user_id))


def slugify(name):
    """Turn a title into a URL-safe id: 'Andy's Roast Chicken' -> 'andys-roast-chicken'."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)     # drop punctuation
    s = re.sub(r"[\s_]+", "-", s)      # spaces / underscores -> hyphen
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def recipe_stats(s, rid, user_id):
    """Derive THIS user's cooking stats for a recipe from the log + ratings tables (rescoping R5:
    per-user — MY cook_count, MY last_cooked, MY rating). cook_count and last_cooked are computed,
    never stored, so they can't drift. last_cooked_provisional flags that the most-recent cook is
    provisional — ANY non-app cook source (e.g. 'paprika-import', 'rating-inferred'), i.e. a
    seeded/inferred date rather than a confirmed app-logged cook — so the UI can mark it (the
    '~'/.approx treatment) as a date still to be corrected.

    Empty case (the common one now): I haven't cooked -> cook_count 0, last_cooked None; I haven't
    rated -> rating None. Takes an ORM session: the 5 cook/rating routes call it AFTER their write on
    the SAME session (before commit), so it reads the just-written rows in-transaction."""
    count = s.scalar(select(func.count()).select_from(CookLog)
                     .where(CookLog.recipe_id == rid, CookLog.user_id == user_id))
    last = s.execute(
        select(CookLog.cooked_on, CookLog.source)
        .where(CookLog.recipe_id == rid, CookLog.user_id == user_id)
        .order_by(CookLog.cooked_on.desc(), CookLog.id.desc())
        .limit(1)
    ).first()
    rating_row = s.execute(
        select(Rating.rating).where(Rating.recipe_id == rid, Rating.user_id == user_id)
    ).first()
    return {
        "cook_count": count,
        "last_cooked": last.cooked_on if last else None,                     # None if never cooked
        "last_cooked_provisional": bool(last and last.source != "app"),
        "rating": rating_row.rating if rating_row else None,
    }


def dialect_insert(s, table):
    """Return the engine-appropriate INSERT construct for an ON CONFLICT upsert (Stage 2b-2). Both the
    sqlite and postgresql dialects expose insert(...).on_conflict_do_update(index_elements=, set_=) +
    .excluded with the same signature for our usage, so the same upsert code works on both — SQLite
    (dev/tests today) and Postgres (once the engine flips in 2b-5)."""
    ins = pg_insert if s.get_bind().dialect.name == "postgresql" else sqlite_insert
    return ins(table)


def upsert_rating(s, rid, user_id, rating):
    """Set-or-replace THIS user's rating of a recipe, stamping rated_on with a Python UTC timestamp
    (dialect-neutral now_utc()). Shared by the 3 rating writers (set_rating, redo_cook, log_cook_and_rate).
    Rescoping R3: the conflict target is the composite PK (recipe_id, user_id) — one rating per (recipe,
    user) — and user_id is supplied (it's NOT NULL). Callers pass current_user.id. (Broader write-scoping
    of cooks + owner is R4; this is the minimal change to keep rating writes working under the new PK.)"""
    stmt = dialect_insert(s, Rating).values(recipe_id=rid, user_id=user_id, rating=rating, rated_on=now_utc())
    s.execute(stmt.on_conflict_do_update(
        index_elements=[Rating.recipe_id, Rating.user_id],
        set_={"rating": stmt.excluded.rating, "rated_on": stmt.excluded.rated_on},
    ))


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
    # Per-recipe rating/cook_count/last_cooked are correlated scalar subqueries, kept as verbatim SQL via
    # text() (identical rating→NULL / COUNT→0 / MAX→NULL empty semantics + sort on both dialects).
    # Rescoping R5: each subquery is scoped to the current user via the :uid BINDPARAM (never string-
    # interpolated) — so the list shows MY rating and MY cook stats. The recipe rows themselves are NOT
    # owner-filtered (FROM recipes r, unchanged) — EVERY recipe still appears; only the personal-layer
    # aggregates are per-user (an untouched recipe shows rating=NULL, cook_count=0, last_cooked=NULL).
    with orm_session() as s:
        rows = s.execute(text(
            """SELECT r.id, r.name, r.author, r.category, r.servings,
                      r.prep_time, r.cook_time, r.total_time, r.image, r.created_at, r.source, r.owner,
                      (SELECT rating FROM ratings WHERE recipe_id = r.id AND user_id = :uid)          AS rating,
                      (SELECT COUNT(*) FROM cook_log WHERE recipe_id = r.id AND user_id = :uid)       AS cook_count,
                      (SELECT MAX(cooked_on) FROM cook_log WHERE recipe_id = r.id AND user_id = :uid) AS last_cooked,
                      (SELECT COUNT(*) FROM recipe_queue WHERE recipe_id = r.id AND user_id = :uid)   AS queued_count
               FROM recipes r
               ORDER BY r.name"""
        ), {"uid": current_user.id}).mappings().all()
    # is_mine: an additive least-exposure signal (mirrors the feed) so the compose picker can filter to
    # recipes you can actually share (POST /api/shares 404s a non-owned one). The raw `owner` id is
    # popped, never leaked — the client only ever learns "mine or not", not who owns it.
    # is_queued: MY want-to-make state (stage 3a) — the queued_count subquery above is per-user (:uid),
    # UNIQUE(user_id, recipe_id) so it's 0/1; popped to a clean JSON boolean, never leaked as a count.
    out = []
    for r in rows:
        d = dict(r)
        owner = d.pop("owner")
        d["is_mine"] = owner == current_user.id
        d["is_queued"] = bool(d.pop("queued_count"))
        out.append(d)
    return jsonify(out)


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
            owner=current_user.id,   # R4: a created recipe lands in the creator's box
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
        stats = recipe_stats(s, rid, current_user.id)
        ingredients = attach_weights(s, ings)
        # is_queued (stage 3a): MY want-to-make state — per-user EXISTS against recipe_queue, scoped to
        # current_user.id like stats above. Any recipe is queueable, so this is independent of ownership.
        is_queued = s.scalar(
            select(RecipeQueue.id)
            .where(RecipeQueue.recipe_id == rid, RecipeQueue.user_id == current_user.id)
        ) is not None
        # Cook-photo album (Stage 4 build 3a — display). Rides along in the recipe payload (like stats/
        # ingredients/steps) so the album paints with the page, no second request. Per photo: path, caption,
        # the cook's DATE (cook_log.cooked_on, LEFT JOIN — NULL for a standalone photo), and is_hero
        # (recipes.image == path — the POINT/linked hero). Least-exposure: no user_id/added_at in the output.
        # ORDER: cook-linked photos NEWEST cook first (cooked_on desc), then undated/standalone photos last
        # (added_at desc among themselves). `(cooked_on IS NULL)` asc pushes NULLs last portably (no reliance
        # on NULLS LAST). The hero is NOT floated — it wears the badge in its natural cooked_on position.
        photo_rows = s.execute(
            select(CookPhoto.id, CookPhoto.path, CookPhoto.caption, CookPhoto.cook_log_id, CookLog.cooked_on)
            .join(CookLog, CookLog.id == CookPhoto.cook_log_id, isouter=True)
            .where(CookPhoto.recipe_id == rid)
            .order_by(
                CookLog.cooked_on.is_(None),      # cook-linked (False=0) before standalone (True=1) — NULLs last
                CookLog.cooked_on.desc(),         # newest cook first
                CookPhoto.added_at.desc(), CookPhoto.id.desc(),   # tiebreak + ordering among undated photos
            )
        ).all()
        hero_path = r["image"]
        photos = [
            {
                "id": p.id, "path": p.path, "caption": p.caption,
                "cooked_on": p.cooked_on,                          # the cook's date if cook-linked, else None
                "is_hero": bool(hero_path and p.path == hero_path),
            }
            for p in photo_rows
        ]
    return jsonify(
        {
            "recipe": dict(r),
            "ingredients": ingredients,
            "steps": serialize_steps(steps),
            "stats": stats,
            "photos": photos,                           # stage 4 (3a): the album — newest cook first, undated last
            "is_editable": r["source"] in EDITABLE_SOURCES,   # app + test recipes get edit/delete
            "is_seed": r["source"] == "seed",           # seed tier stays read-only (edit in seed.py)
            "is_test": r["source"] == "test",           # scratch tier — gets the visible test marker
            "is_queued": is_queued,                     # stage 3a: my want-to-make queue membership
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


# ---- POINT/linked-hero cleanup helpers (Stage 4 build 2c) ---------------------------------------
# The hero (recipes.image) may POINT at a cook photo's own file (promote / auto-promote), so removing a
# cook photo — by explicit delete OR by cascade (undo_cook / delete_recipe) — must not leave the hero
# dangling or the file orphaned. "Is this the hero?" is a PATH comparison (recipes.image == photo.path),
# used consistently on every deletion path.

def clear_hero_if_matches(s, recipe_id, paths):
    """If the recipe's hero points at any of `paths` (a promoted cook photo about to be removed), NULL
    recipes.image so it doesn't dangle — a single guarded UPDATE, a no-op when the hero isn't one of them.
    In-transaction (a DB change), on the session `s`. For a SURVIVING recipe (explicit delete / undo_cook)."""
    paths = [p for p in paths if p]
    if not paths:
        return
    s.execute(update(Recipe.__table__)
              .where(Recipe.__table__.c.id == recipe_id, Recipe.__table__.c.image.in_(paths))
              .values(image=None))


def unlink_unreferenced(paths):
    """After a delete/cascade has COMMITTED, unlink each file — but ONLY if no surviving recipe still points
    at it as its hero. Guards the copy-shares-image case: copy_recipe carries the image PATH, so two recipes
    can share one file; deleting one must not unlink a file the other still uses. Opens its own session for
    the reference check (the rows are already gone). Idempotent (delete_image no-ops a missing file)."""
    paths = [p for p in dict.fromkeys(paths) if p]   # de-dup, drop falsy
    if not paths:
        return
    with orm_session() as s:
        still = set(s.scalars(select(Recipe.image).where(Recipe.image.in_(paths))))
    for p in paths:
        if p not in still:
            images.delete_image(p)


@app.route("/api/recipes/<rid>", methods=["DELETE"])
def delete_recipe(rid):
    """Delete an app-owned recipe. Its ratings, cook history, ingredient lines, steps, and cook_photos
    are removed automatically by ON DELETE CASCADE (foreign keys are enforced per connection by
    orm_session). The DB cascade removes ROWS but not FILES, so gather every cook-photo path + the hero's
    own file BEFORE the delete and unlink them AFTER commit (2c) — this also fixes the pre-existing
    hero-orphan (delete_recipe used to leave the hero file on disk). unlink_unreferenced skips any file a
    surviving recipe still references (the copy-shares-image guard)."""
    with orm_session() as s:
        row = s.execute(select(Recipe.source, Recipe.image).where(Recipe.id == rid)).first()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row.source not in EDITABLE_SOURCES:
            return jsonify({"error": "seed recipes can't be deleted here — remove them from seed.py"}), 403
        files = list(s.scalars(select(CookPhoto.path).where(CookPhoto.recipe_id == rid)))   # all album files
        if row.image:
            files.append(row.image)                          # + the hero's own file (the orphan fix)
        s.execute(delete(Recipe.__table__).where(Recipe.__table__.c.id == rid))   # cascades cook_photos ROWS
        s.commit()
    unlink_unreferenced(files)                               # AFTER commit: unlink files no surviving recipe uses
    return jsonify({"deleted": rid})


@app.route("/api/recipes/<rid>/image", methods=["POST"])
def upload_recipe_image(rid):
    """Upload a dish photo for a recipe you OWN (multipart, field 'image'). Owner-checked (mirrors the
    shares owner-gate); resizes + strips metadata + stores via images.save_image (the swappable
    local-disk seam); updates recipes.image through the same ORM path as update_recipe. Returns ONLY the
    new path (least-exposure — no owner/uid/hash). First endpoint that writes user bytes to disk; the
    S1–S7 hardening lives in images.py. Login-gated by before_request (NOT in PUBLIC_ENDPOINTS)."""
    with orm_session() as s:
        rec = s.get(Recipe, str(rid))
        if rec is None:
            return jsonify({"error": "recipe not found"}), 404
        if rec.owner != current_user.id:                     # default-deny: only the owner may write (SECURITY.md)
            return jsonify({"error": "not your recipe"}), 403
        f = request.files.get("image")                       # owner-checked BEFORE any file work
        if f is None:
            return jsonify({"error": "no image file provided"}), 400
        try:
            path = images.save_image(f.read(), slug=rec.id)  # validate + resize + strip + atomic write (S1–S6)
        except images.ImageValidationError as e:
            return jsonify({"error": str(e)}), 400           # bad/blocked/bomb input -> 400, nothing written
        s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rec.id).values(image=path))
        s.commit()                                           # DB updated ONLY after the file is on disk (S6)
    return jsonify({"image": path})


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
            owner=current_user.id,   # R4 (box model): the copy is owned by whoever made it, even copying your own
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
    /api/recipes/<rid> so it can't be shadowed by a recipe slugged 'test'. Mirrors delete_recipe's 2c
    file cleanup: the cascade removes ROWS but not FILES, so gather every test recipe's cook-photo paths
    + hero files BEFORE the delete and unlink them AFTER commit — otherwise a bulk test-delete orphans
    those files on disk. unlink_unreferenced skips any file a surviving recipe still references as its hero
    (the copy-shares-image guard: a test recipe whose hero is shared with a surviving app copy keeps it)."""
    with orm_session() as s:
        files = list(s.scalars(select(CookPhoto.path)
                               .join(Recipe, CookPhoto.recipe_id == Recipe.id)
                               .where(Recipe.source == "test")))          # every test recipe's album files
        files += list(s.scalars(select(Recipe.image)
                                .where(Recipe.source == "test", Recipe.image.isnot(None))))   # + their heroes
        n = s.execute(delete(Recipe).where(Recipe.source == "test")).rowcount   # children cascade (FK ON)
        s.commit()
    unlink_unreferenced(files)   # AFTER commit: unlink files no surviving recipe uses (copy-share guarded)
    return jsonify({"deleted": n})


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

@app.route("/api/cooks")
def list_cooks():
    """The signed-in user's OWN cook-log entries (cook_log.user_id == current_user), NEWEST-FIRST, for
    the feed compose modal's cook picker. Joins cook_log -> recipes for the name/image. Scoped STRICTLY
    to my own cooks (default-deny — never another user's; login-gated by the before_request allowlist).
    Exposing MY OWN cook_log_id is what lets the client POST /api/shares {cook_log_id} to share a cook
    I'm proud of."""
    with orm_session() as s:
        rows = s.execute(
            select(CookLog.id, CookLog.recipe_id, CookLog.cooked_on, Recipe.name, Recipe.image)
            .join(Recipe, Recipe.id == CookLog.recipe_id)
            .where(CookLog.user_id == current_user.id)
            .order_by(CookLog.cooked_on.desc(), CookLog.id.desc())   # newest cook first (id tiebreak, as recipe_stats)
        ).all()
    return jsonify([
        {
            "cook_log_id": r.id,
            "recipe_id": r.recipe_id,
            "recipe_name": r.name,
            "image": r.image,
            "cooked_on": r.cooked_on,
        }
        for r in rows
    ])


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
            res = s.execute(insert(cl).values(recipe_id=rid, user_id=current_user.id, cooked_on=cooked_on))
        else:
            res = s.execute(insert(cl).values(recipe_id=rid, user_id=current_user.id))   # cooked_on omitted -> DB default date('now')
        cook_log_id = res.inserted_primary_key[0]   # returned so the client can attach a photo to THIS cook (2b)
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    return jsonify({**stats, "cook_log_id": cook_log_id})


@app.route("/api/recipes/<rid>/uncook", methods=["POST"])
def undo_cook(rid):
    """Remove the most recent cook entry — for fixing an accidental tap. If this returns the recipe
    to uncooked (cook_count -> 0), also clear its rating in the same transaction, so we never leave
    an uncooked-but-rated recipe (the inconsistency the cook-gate prevents). If other cooks remain,
    the rating stands — you've still cooked it."""
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        # R4: everything here is scoped to current_user — MY last cook, MY remaining count, MY rating.
        # Without the user filter, my undo would drop ANOTHER user's rating on the same recipe (the
        # consideration-#3 cross-bleed). recipes stay visible to all, but the personal layer is per-user.
        last = s.execute(
            select(CookLog.id, CookLog.cooked_on, CookLog.source)
            .where(CookLog.recipe_id == rid, CookLog.user_id == current_user.id)
            .order_by(CookLog.id.desc()).limit(1)
        ).first()
        undone = None   # what this undo removed, so a one-shot redo can reverse exactly it
        photo_paths = []   # 2c: this cook's photo files, cascade-deleted with the cook_log row -> unlink after commit
        if last:
            photo_paths = list(s.scalars(select(CookPhoto.path).where(CookPhoto.cook_log_id == last.id)))
            s.execute(delete(CookLog).where(CookLog.id == last.id))   # cascade-deletes this cook's cook_photos ROWS
            clear_hero_if_matches(s, rid, photo_paths)   # 2c: the recipe SURVIVES the undo, so a hero pointing at
                                                         # a vanished photo must be cleared (POINT/linked)
            remaining = s.scalar(   # MY cooks remaining, counted AFTER the delete — drop MY rating iff 0
                select(func.count()).select_from(CookLog)
                .where(CookLog.recipe_id == rid, CookLog.user_id == current_user.id)
            )
            cleared_rating = None
            if remaining == 0:
                rr = s.execute(select(Rating.rating)
                               .where(Rating.recipe_id == rid, Rating.user_id == current_user.id)).first()
                cleared_rating = rr.rating if rr else None
                s.execute(delete(Rating)   # back to uncooked (for ME) -> drop MY rating, never anyone else's
                          .where(Rating.recipe_id == rid, Rating.user_id == current_user.id))
            undone = {"cooked_on": last.cooked_on, "source": last.source, "cleared_rating": cleared_rating}
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    unlink_unreferenced(photo_paths)   # 2c: AFTER commit, unlink the cascade-orphaned files (copy-share guarded)
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
        s.execute(insert(CookLog.__table__).values(recipe_id=rid, user_id=current_user.id, cooked_on=cooked_on, source=source))
        if rating is not None:
            upsert_rating(s, rid, current_user.id, rating)
        stats = recipe_stats(s, rid, current_user.id)
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
        upsert_rating(s, rid, current_user.id, rating)   # NOT cook-gated: rating an uncooked recipe is allowed (as before)
        stats = recipe_stats(s, rid, current_user.id)
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
        res = s.execute(insert(CookLog.__table__).values(recipe_id=rid, user_id=current_user.id))   # today's cook, source default 'app'
        cook_log_id = res.inserted_primary_key[0]   # returned for at-log-time photo attach (2b), like log_cook
        upsert_rating(s, rid, current_user.id, rating)
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    return jsonify({**stats, "cook_log_id": cook_log_id})


# ---- cook-photo album (Stage 4 build 2b) --------------------------------------------------------
# CRUD for cook photos over the cook_photos table (schema: migration 025/026). Reuses the 2a image seams
# (images.save_cook_photo for the file, images.delete_image for removal), the CookPhoto model, and the
# hero endpoint's owner-check pattern. Login-gated by default (NOT in PUBLIC_ENDPOINTS). NO promote-to-hero
# and NO POINT/linked-hero deletion logic here — that's 2c (so in 2b no cook photo can be a hero yet,
# which is why the DELETE below needs no hero-clear).

COOK_PHOTO_CAPTION_MAX = 100   # album captions are short; mirrors create_share's CAPTION_MAX rule (400 on over-length)


def clean_caption(raw):
    """Normalize + validate an optional cook-photo caption. Returns (caption_or_None, error): blanks strip
    to None (clears it), non-strings and over-length are rejected — the create_share CAPTION_MAX idiom, so
    attach and caption-edit enforce the cap identically."""
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, "caption must be text"
    caption = raw.strip() or None
    if caption is not None and len(caption) > COOK_PHOTO_CAPTION_MAX:
        return None, f"caption must be {COOK_PHOTO_CAPTION_MAX} characters or fewer"
    return caption, None


@app.route("/api/recipes/<rid>/photos", methods=["POST"])
def add_cook_photo(rid):
    """Attach a photo to the recipe's album (multipart, field 'image'). OPTIONAL form field 'cook_log_id':
    attach to that cook, or omit for a STANDALONE album photo (cook_log_id NULL, made possible by 2a).
    Owner-split gating: attaching to a cook checks the COOK is yours AND belongs to this recipe (undo_cook's
    cook-owner scoping) — you can photograph your own cook of anyone's recipe; a STANDALONE album photo has
    no cook, so it checks the RECIPE is yours (rec.owner, the hero owner-check). Gating runs BEFORE any file
    work (mirrors the hero endpoint). Reuses save_cook_photo (2a: shared validation/resize/uuid write).
    Returns the created photo (least-exposure)."""
    raw_cook_id = request.form.get("cook_log_id")
    caption, cap_err = clean_caption(request.form.get("caption"))
    if cap_err:
        return jsonify({"error": cap_err}), 400
    with orm_session() as s:
        rec = s.get(Recipe, str(rid))
        if rec is None:
            return jsonify({"error": "recipe not found"}), 404
        cook_log_id = None
        cooked_on = None
        if raw_cook_id not in (None, ""):
            try:
                cook_log_id = int(raw_cook_id)
            except (ValueError, TypeError):
                return jsonify({"error": "cook_log_id must be an integer"}), 400
            cook = s.get(CookLog, cook_log_id)
            if cook is None or cook.recipe_id != rec.id:      # not this recipe's cook (or absent) -> 404
                return jsonify({"error": "cook not found for this recipe"}), 404
            if cook.user_id != current_user.id:               # your cook only (cook-owner gate)
                return jsonify({"error": "not your cook"}), 403
            cooked_on = cook.cooked_on
        elif rec.owner != current_user.id:                    # standalone album photo -> recipe-owner gate
            return jsonify({"error": "not your recipe"}), 403
        f = request.files.get("image")                        # checks passed BEFORE any file work
        if f is None:
            return jsonify({"error": "no image file provided"}), 400
        try:
            path = images.save_cook_photo(f.read())           # 2a seam: validate + resize + strip + atomic write
        except images.ImageValidationError as e:
            return jsonify({"error": str(e)}), 400            # bad/blocked/bomb input -> 400, nothing inserted
        res = s.execute(insert(CookPhoto.__table__).values(
            cook_log_id=cook_log_id, recipe_id=rec.id, user_id=current_user.id,
            path=path, caption=caption, added_at=now_utc(),
        ))
        photo_id = res.inserted_primary_key[0]
        # 2c AUTO-PROMOTE: if the recipe has NO hero yet, this photo becomes it (POINT/linked, same path).
        # No-hijack guard — only when YOU own the recipe: attaching a photo to your cook of someone else's
        # recipe must NOT auto-set their empty hero. (Standalone attach already required recipe-owner.)
        is_hero = False
        if not rec.image and rec.owner == current_user.id:
            s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rec.id).values(image=path))
            is_hero = True
        s.commit()
    return jsonify({
        "id": photo_id, "path": path, "caption": caption,
        "cook_log_id": cook_log_id, "cooked_on": cooked_on,   # the cook's date if cook-linked, else None
        "is_hero": is_hero,                                   # auto-promoted (recipe had no hero + you own it)
    }), 201


@app.route("/api/photos/<int:photo_id>", methods=["PATCH"])
def edit_cook_photo(photo_id):
    """Edit a cook photo's caption (JSON {caption}). Photo-owner gated (cook_photo.user_id == current_user).
    Caption optional + capped (clean_caption); a blank/absent caption CLEARS it. Returns the updated caption."""
    payload = request.get_json(silent=True) or {}
    caption, cap_err = clean_caption(payload.get("caption"))
    if cap_err:
        return jsonify({"error": cap_err}), 400
    with orm_session() as s:
        photo = s.get(CookPhoto, photo_id)
        if photo is None:
            return jsonify({"error": "photo not found"}), 404
        if photo.user_id != current_user.id:
            return jsonify({"error": "not your photo"}), 403
        s.execute(update(CookPhoto.__table__).where(CookPhoto.__table__.c.id == photo_id).values(caption=caption))
        s.commit()
    return jsonify({"id": photo_id, "caption": caption})


@app.route("/api/photos/<int:photo_id>/promote", methods=["POST"])
def promote_cook_photo(photo_id):
    """Make this cook photo the recipe's hero — POINT/linked: set recipes.image = the photo's OWN path
    (images/cooks/<uuid>.jpg), so hero and album entry SHARE the file (NO copy). Gated on the RECIPE owner
    (rec.owner == current_user) — writing recipes.image is the recipe owner's call, even if the photo/cook is
    yours. Reuses the hero-upload write (update Recipe .values(image=path)). Returns the new hero path."""
    with orm_session() as s:
        photo = s.get(CookPhoto, photo_id)
        if photo is None:
            return jsonify({"error": "photo not found"}), 404
        rec = s.get(Recipe, photo.recipe_id)
        if rec is None:
            return jsonify({"error": "recipe not found"}), 404
        if rec.owner != current_user.id:                      # recipe-owner gate (writing recipes.image)
            return jsonify({"error": "not your recipe"}), 403
        path = photo.path                                     # capture before commit (ORM obj detaches after)
        s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rec.id).values(image=path))
        s.commit()
    return jsonify({"image": path})


@app.route("/api/photos/<int:photo_id>", methods=["DELETE"])
def delete_cook_photo(photo_id):
    """Delete a cook photo — photo-owner gated (cook_photo.user_id == current_user). 2c POINT/linked-hero
    clear: if this photo IS the recipe's hero (recipes.image == photo.path), NULL the hero too (-> empty
    upload frame); deleting a NON-hero photo leaves the hero untouched. Then delete the row and unlink the
    file (unlink_unreferenced — skips it if a copy still shares it)."""
    with orm_session() as s:
        photo = s.get(CookPhoto, photo_id)
        if photo is None:
            return jsonify({"error": "photo not found"}), 404
        if photo.user_id != current_user.id:
            return jsonify({"error": "not your photo"}), 403
        path = photo.path
        clear_hero_if_matches(s, photo.recipe_id, [path])     # 2c: if this photo is the hero, clear recipes.image
        s.delete(photo)
        s.commit()                                            # row authoritatively gone before the file unlink
    unlink_unreferenced([path])                               # unlink unless a copy still references it (2c guard)
    return jsonify({"ok": True})


# ---- want-to-make queue (stage 2) ---------------------------------------------------------------
# Per-user planning state promoted out of the old GLOBAL "To Make" tag (recipe_queue, migration 024,
# backfilled stage 1). Login-gated by default (NOT in PUBLIC_ENDPOINTS); current_user is ALWAYS the
# actor. A want-to-make queue is for recipes you MEAN to cook — including OTHERS' — so queueing is NOT
# owner-restricted (unlike sharing): any visible recipe is queueable. Mirrors list_cooks (read) /
# upsert_rating (idempotent add) / undo_cook (recipe_id-keyed remove) verbatim in idiom.

@app.route("/api/queue")
def list_queue():
    """The signed-in user's want-to-make queue, NEWEST-FIRST. Joins recipe_queue -> recipes for the
    name/image. Scoped STRICTLY to my own queue (default-deny). queue_id is exposed for a known future
    consumer (per-entry reorder / notes)."""
    with orm_session() as s:
        rows = s.execute(
            select(RecipeQueue.id, RecipeQueue.recipe_id, RecipeQueue.added_at, Recipe.name, Recipe.image)
            .join(Recipe, Recipe.id == RecipeQueue.recipe_id)
            .where(RecipeQueue.user_id == current_user.id)
            .order_by(RecipeQueue.added_at.desc(), RecipeQueue.id.desc())   # newest add first (id tiebreak)
        ).all()
    return jsonify([
        {
            "queue_id": r.id,
            "recipe_id": r.recipe_id,
            "recipe_name": r.name,
            "image": r.image,
            "added_at": r.added_at,
        }
        for r in rows
    ])


@app.route("/api/queue", methods=["POST"])
def add_to_queue():
    """Add a recipe to my want-to-make queue — IDEMPOTENT. Any visible recipe is queueable (NOT owner-
    restricted: the point is recipes you haven't made, incl. others'). Re-adding an already-queued recipe
    is a clean no-op via ON CONFLICT DO NOTHING on UNIQUE(user_id, recipe_id) — never a 500 or duplicate."""
    payload = request.get_json(silent=True) or {}
    recipe_id = payload.get("recipe_id")
    if not recipe_id or not isinstance(recipe_id, str):
        return jsonify({"error": "recipe_id required"}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == recipe_id)) is None:
            return jsonify({"error": "recipe not found"}), 404
        stmt = dialect_insert(s, RecipeQueue).values(
            user_id=current_user.id, recipe_id=recipe_id, added_at=now_utc())
        s.execute(stmt.on_conflict_do_nothing(
            index_elements=[RecipeQueue.user_id, RecipeQueue.recipe_id]))   # already queued -> no-op
        s.commit()
    return jsonify({"ok": True}), 201


@app.route("/api/queue/<recipe_id>", methods=["DELETE"])
def remove_from_queue(recipe_id):
    """Remove a recipe from MY queue, keyed by recipe_id (the undo_cook idiom). Scoped to my own entry;
    absent-or-not-mine is a uniform {ok:true} (idempotent remove — the queue simply doesn't contain it,
    and we never leak whether another user queued it)."""
    with orm_session() as s:
        s.execute(delete(RecipeQueue)
                  .where(RecipeQueue.recipe_id == recipe_id, RecipeQueue.user_id == current_user.id))
        s.commit()
    return jsonify({"ok": True}), 200


# ---- social: the friend graph (sub-stage 1) -----------------------------------------------------
# Additive — nothing else reads friendships yet (the feed/sharing sub-stages consume it). All four
# routes are login-gated by default (NOT in PUBLIC_ENDPOINTS); current_user is ALWAYS the actor (never
# client-supplied), so authorization is structural: accept keys on addressee=current_user, delete/list
# key on current_user's membership. Friend-by-exact-email, no directory (private-by-default); the
# request path returns a UNIFORM response whether or not the email is a user, so it can't be used to
# enumerate accounts (the same non-leak posture as login) — and that unknown-email branch is the seam
# sub-stage 3 upgrades to share-as-invite.
FRIEND_REQUEST_OK = {"ok": True, "message": "If they have an account, they'll get your request."}


def _user_by_email(s, email):
    """Resolve a normalized (lowercased/stripped) email to its User, or None. Callers lowercase first,
    matching how signup/login store + look up users.email."""
    return s.execute(select(User).where(User.email == email)).scalar_one_or_none()


def friendship_edge(s, a_id, b_id):
    """The friendship row between two users in EITHER direction, or None — the one-row/query-both-
    directions read. Reusable by the feed/sharing sub-stages to answer 'are these two friends'."""
    return s.get(Friendship, (a_id, b_id)) or s.get(Friendship, (b_id, a_id))


def accepted_friend_ids(s, user_id):
    """The set of user_ids who are ACCEPTED friends of `user_id` — both directions (a friendship is one
    row; the other party may be requester OR addressee). The 'all my friends' set the feed (sub-stage 2a)
    and later sharing/reco sub-stages need — distinct from friendship_edge (pairwise) and list_friends
    (buckets, inline)."""
    rows = s.execute(
        select(Friendship.requester_id, Friendship.addressee_id)
        .where(Friendship.status == "accepted",
               or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id))
    ).all()
    return {(addr if req == user_id else req) for req, addr in rows}


@app.route("/api/friends/requests", methods=["POST"])
def request_friend():
    """Send a friend request to a user identified by email. Enumeration-safe: an unknown email returns
    the SAME success shape as a real request (no row created — sub-stage 3 turns this branch into an
    invite). The one real subtlety is the reverse-duplicate: if THEY already have a pending request to
    ME, this is mutual intent -> auto-accept it (one row becomes 'accepted', never a second row)."""
    email = (request.get_json(silent=True) or {}).get("email")
    email = (email or "").strip().lower()
    if not email:
        return jsonify({"error": "an email is required"}), 400
    with orm_session() as s:
        target = _user_by_email(s, email)
        if target is None:
            return jsonify(FRIEND_REQUEST_OK), 200          # unknown email -> uniform no-op (enumeration-safe)
        if target.id == current_user.id:
            return jsonify({"error": "you can't friend yourself"}), 400   # you already know your own email
        rev = s.get(Friendship, (target.id, current_user.id))   # THEY -> me
        if rev is not None and rev.status == "pending":         # mutual intent -> auto-accept, no 2nd row
            rev.status = "accepted"
            rev.accepted_at = now_utc()
            s.commit()
            return jsonify(FRIEND_REQUEST_OK), 200
        fwd = s.get(Friendship, (current_user.id, target.id))   # me -> them
        if fwd is None and rev is None:                         # nothing yet -> a fresh pending request
            s.add(Friendship(requester_id=current_user.id, addressee_id=target.id,
                             status="pending", created_at=now_utc()))
            s.commit()
        # else: already sent (fwd) or already friends (rev accepted) -> idempotent success, no dup
        return jsonify(FRIEND_REQUEST_OK), 200


@app.route("/api/friends/accept", methods=["POST"])
def accept_friend():
    """Accept a pending request FROM the given email. Structural authz: the row is keyed
    (requester=them, addressee=current_user), so you can only ever accept a request addressed to YOU —
    accepting someone else's request is impossible, not merely forbidden. Unknown email and
    no-such-pending-request return the SAME 404 (no enumeration)."""
    email = (request.get_json(silent=True) or {}).get("email")
    email = (email or "").strip().lower()
    if not email:
        return jsonify({"error": "an email is required"}), 400
    with orm_session() as s:
        requester = _user_by_email(s, email)
        row = s.get(Friendship, (requester.id, current_user.id)) if requester else None
        if row is None or row.status != "pending":
            return jsonify({"error": "no pending request from that person"}), 404
        row.status = "accepted"
        row.accepted_at = now_utc()
        s.commit()
    return jsonify({"ok": True}), 200


@app.route("/api/friends")
def list_friends():
    """My social graph in three buckets: accepted friends, incoming pending (requests to me), outgoing
    pending (requests I sent). Scoped to edges where I'm a party, so I only ever see my own edges; each
    entry projects the OTHER party's display_name, never the raw ids. LEAST-EXPOSURE (docs/SECURITY.md):
    the accepted-FRIENDS list omits email — another user's email is private and the feed's Your-Friends
    render needs only the name. The pending incoming/outgoing lists still carry email (it identifies who
    to accept, accept-by-email) — that's a deferred follow-up to revisit when a friends UI lands."""
    me = current_user.id
    with orm_session() as s:
        edges = s.execute(
            select(Friendship).where(or_(Friendship.requester_id == me, Friendship.addressee_id == me))
        ).scalars().all()
        other_ids = {(e.addressee_id if e.requester_id == me else e.requester_id) for e in edges}
        users = {u.id: u for u in s.execute(select(User).where(User.id.in_(other_ids))).scalars()} \
            if other_ids else {}
        friends, incoming, outgoing = [], [], []
        for e in edges:
            other = users[e.addressee_id if e.requester_id == me else e.requester_id]
            if e.status == "accepted":
                friends.append({"display_name": other.display_name})            # NO email (least-exposure)
            elif e.requester_id == me:
                outgoing.append({"email": other.email, "display_name": other.display_name})   # follow-up
            else:
                incoming.append({"email": other.email, "display_name": other.display_name})   # follow-up
    return jsonify({"friends": friends, "incoming": incoming, "outgoing": outgoing})


@app.route("/api/friends", methods=["DELETE"])
def remove_friend():
    """One handler for unfriend / decline / cancel — they're mechanically identical (drop the single
    edge between me and them, in whichever direction it exists). Membership authz: both lookup keys
    include current_user, so a non-party can't remove someone else's edge. Uniform 404 if there's none."""
    email = (request.get_json(silent=True) or {}).get("email")
    email = (email or "").strip().lower()
    if not email:
        return jsonify({"error": "an email is required"}), 400
    with orm_session() as s:
        other = _user_by_email(s, email)
        row = friendship_edge(s, current_user.id, other.id) if other else None
        if row is None:
            return jsonify({"error": "no such friendship"}), 404
        s.delete(row)
        s.commit()
    return jsonify({"ok": True}), 200


# ---- social: the deliberate-share feed (sub-stage 2a) -------------------------------------------
# Logging stays private; SHARING is a separate opt-in act that creates a first-class feed post. You
# share YOUR OWN things — a cook you logged, or a recipe you own (copy-then-share for others'); test-tier
# recipes can't be shared (scratch). The feed is BOUNDED by design (connection-not-consumption): a 14-day
# window, capped at 50, pure chronological, NO pagination/load-more — you can see the end.
CAPTION_MAX = 280
FEED_WINDOW_DAYS = 14
FEED_LIMIT = 50


@app.route("/api/shares", methods=["POST"])
def create_share():
    """Deliberately share a cook OR a recipe (exactly one), with an optional caption. Authz: you share
    YOUR OWN things — a cook you logged (cook_log.user_id == you) or a recipe you own (owner == you);
    someone else's returns a uniform 404. test-tier recipes can't be shared (400). Repeat shares are
    allowed (no dedup — the surrogate PK permits 'cooked it again, still great')."""
    payload = request.get_json(silent=True) or {}
    cook_log_id = payload.get("cook_log_id")
    recipe_id = payload.get("recipe_id")
    caption = payload.get("caption")
    if (cook_log_id is None) == (recipe_id is None):                       # exactly one (mirrors the CHECK)
        return jsonify({"error": "share exactly one of a cook or a recipe"}), 400
    if caption is not None:
        if not isinstance(caption, str):
            return jsonify({"error": "caption must be text"}), 400
        caption = caption.strip() or None
        if caption is not None and len(caption) > CAPTION_MAX:
            return jsonify({"error": f"caption must be {CAPTION_MAX} characters or fewer"}), 400
    with orm_session() as s:
        if cook_log_id is not None:
            try:
                cook_log_id = int(cook_log_id)
            except (ValueError, TypeError):
                return jsonify({"error": "cook not found"}), 404
            cook = s.get(CookLog, cook_log_id)
            if cook is None or cook.user_id != current_user.id:           # only your own cook
                return jsonify({"error": "cook not found"}), 404
            rec = s.get(Recipe, cook.recipe_id)
            if rec is not None and rec.source == "test":                  # block test-tier at write
                return jsonify({"error": "test recipes can't be shared"}), 400
            post = SharedPost(user_id=current_user.id, cook_log_id=cook_log_id,
                              caption=caption, created_at=now_utc())
        else:
            rec = s.get(Recipe, str(recipe_id))
            if rec is None or rec.owner != current_user.id:               # only a recipe you own (option i)
                return jsonify({"error": "recipe not found"}), 404
            if rec.source == "test":
                return jsonify({"error": "test recipes can't be shared"}), 400
            post = SharedPost(user_id=current_user.id, recipe_id=rec.id,
                              caption=caption, created_at=now_utc())
        s.add(post)
        s.commit()
        pid = post.id
    return jsonify({"id": pid}), 201


@app.route("/api/shares/<int:post_id>", methods=["DELETE"])
def delete_share(post_id):
    """Unshare — retract a post. Only the sharer (user_id == current_user); anyone else, or a missing
    post, gets a uniform 404."""
    with orm_session() as s:
        post = s.get(SharedPost, post_id)
        if post is None or post.user_id != current_user.id:
            return jsonify({"error": "post not found"}), 404
        s.delete(post)
        s.commit()
    return jsonify({"ok": True}), 200


@app.route("/api/feed")
def get_feed():
    """The BOUNDED deliberate-share feed: my accepted friends' + my OWN shared posts (include-self),
    newest first, within a FEED_WINDOW_DAYS window, capped at FEED_LIMIT — NO pagination/load-more
    (connection-not-consumption: finite, you reach the end). The window is a lexicographic compare on the
    fixed-width now_utc() timestamp (the invite-expiry trick, dialect-safe). Each post serializes the
    sharer, the DERIVED post_type, the referenced recipe (id/name/image) [+ the cook's cooked_on for a
    'cook' post], the caption, and the share time."""
    me = current_user.id
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=FEED_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with orm_session() as s:
        author_ids = accepted_friend_ids(s, me) | {me}                    # {me} ∪ accepted friends
        posts = s.execute(
            select(SharedPost)
            .where(SharedPost.user_id.in_(author_ids), SharedPost.created_at >= cutoff)
            .order_by(SharedPost.created_at.desc(), SharedPost.id.desc())
            .limit(FEED_LIMIT)
        ).scalars().all()
        sharers = {u.id: u for u in s.execute(
            select(User).where(User.id.in_({p.user_id for p in posts}))).scalars()} if posts else {}
        # Comments embedded in the feed (the conversation under each post) — batched, NOT N+1: ONE query
        # for every post's comments (oldest-first, a thread reads top-to-bottom) + ONE author load,
        # grouped by post_id in Python. can_delete is computed per post below (needs the post owner).
        comments_by_post, comment_authors = {}, {}
        post_ids = [p.id for p in posts]
        if post_ids:
            crows = s.execute(
                select(Comment).where(Comment.post_id.in_(post_ids))
                .order_by(Comment.created_at, Comment.id)                 # oldest-first, stable tiebreak
            ).scalars().all()
            comment_authors = {u.id: u for u in s.execute(
                select(User).where(User.id.in_({c.author_id for c in crows}))).scalars()} if crows else {}
            for c in crows:
                comments_by_post.setdefault(c.post_id, []).append(c)
        out = []
        for p in posts:
            post_type = "cook" if p.cook_log_id is not None else "recipe"
            if post_type == "cook":
                cook = s.get(CookLog, p.cook_log_id)
                rec = s.get(Recipe, cook.recipe_id) if cook else None
                cooked_on = cook.cooked_on if cook else None
            else:
                rec = s.get(Recipe, p.recipe_id)
                cooked_on = None
            sharer = sharers.get(p.user_id)
            comments = [{
                "id": c.id,
                "author": {"display_name": (comment_authors.get(c.author_id).display_name
                                            if comment_authors.get(c.author_id) else None)},
                "body": c.body,
                "created_at": c.created_at,
                "is_mine": c.author_id == me,
                "can_delete": c.author_id == me or p.user_id == me,   # own comment OR I own the post
            } for c in comments_by_post.get(p.id, [])]
            out.append({
                "id": p.id,
                "post_type": post_type,
                "sharer": {"display_name": sharer.display_name, "email": sharer.email} if sharer else None,
                "recipe": {"id": rec.id, "name": rec.name, "image": rec.image} if rec is not None else None,
                "cooked_on": cooked_on,
                "caption": p.caption,
                "created_at": p.created_at,
                "is_mine": p.user_id == me,
                "comments": comments,
            })
    return jsonify(out)


# ---- social: comments on feed posts ------------------------------------------------------------
# The conversation under a post (docs/product-vision.md): comments YES, likes/reactions NEVER, no
# count-as-metric, NO notifications (a comment is just a row, seen only when the feed renders — the
# simplification that removes commenting's hard part). Friends-only == feed-visibility (the same
# accepted_friend_ids set that scopes the feed). Listing is embedded in GET /api/feed (batched above),
# so there is deliberately NO separate list endpoint — just add + delete.
COMMENT_MAX = 300


@app.route("/api/posts/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    """Comment on a feed post. AUTHZ (friends-only = feed-visibility): you may comment on your OWN post
    or an ACCEPTED FRIEND's post; anyone else gets a uniform 404 (a non-friend can't see the post and
    shouldn't learn it exists). Body is trimmed, required, and capped at COMMENT_MAX. Returns the created
    comment so the client appends it without a refetch."""
    body = (request.get_json(silent=True) or {}).get("body")
    body = (body or "").strip() if isinstance(body, str) else ""
    if not body:
        return jsonify({"error": "a comment can't be empty"}), 400
    if len(body) > COMMENT_MAX:
        return jsonify({"error": f"a comment must be {COMMENT_MAX} characters or fewer"}), 400
    with orm_session() as s:
        post = s.get(SharedPost, post_id)
        if post is None:
            return jsonify({"error": "post not found"}), 404
        if post.user_id != current_user.id and post.user_id not in accepted_friend_ids(s, current_user.id):
            return jsonify({"error": "post not found"}), 404       # non-friend: non-leaking (== feed-visibility)
        c = Comment(post_id=post_id, author_id=current_user.id, body=body, created_at=now_utc())
        s.add(c)
        s.commit()
        out = {"id": c.id, "author": {"display_name": current_user.display_name},
               "body": c.body, "created_at": c.created_at, "is_mine": True,
               "can_delete": True}                                  # author (and maybe post owner) — always deletable by you
    return jsonify(out), 201


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    """Delete a comment. AUTHZ: the comment's AUTHOR (delete your own) OR the OWNER of the post it's on
    (light 'it's your post' moderation). Anyone else, or a missing comment, gets a uniform 404."""
    with orm_session() as s:
        c = s.get(Comment, comment_id)
        if c is None:
            return jsonify({"error": "comment not found"}), 404
        post = s.get(SharedPost, c.post_id)                        # post owner may moderate
        if c.author_id != current_user.id and not (post and post.user_id == current_user.id):
            return jsonify({"error": "comment not found"}), 404
        s.delete(c)
        s.commit()
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    app.run(port=8000, debug=True)
