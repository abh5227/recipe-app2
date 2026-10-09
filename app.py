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
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from flask import Flask, jsonify, request, send_from_directory
from flask_login import LoginManager, current_user
from sqlalchemy import and_, create_engine, delete, event, func, insert, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert       # dialect-agnostic upserts (2b-2):
from sqlalchemy.dialects.postgresql import insert as pg_insert       # pick per engine dialect at runtime
from sqlalchemy.orm import Session

from weights import build_index, match_weight
from stepscale import api_spans, note_spans
from import_cleanup import clean_recipe, split_qty   # shared qty->quantity+unit split (backfill/seed/import use it too)
from units import canon_unit_str   # the Python mirror of scaler.js canonicalizeUnit, for the carry key
# SQLAlchemy migration (Stage 1 complete): the entire serve path queries through orm_session() below —
# reads, writes, and the 5 SQLite-dialect upserts. Build-time modules (build_db/import/migrate) keep
# their own raw sqlite3 connections (out of Stage 1 scope). Stage 2 swaps the engine to Postgres
# (see docs/migration-plan.md).
from models import (
    Ingredient, IngredientSeason, IngredientRegion, Region, Recipe, RecipeIngredient, RecipeStep, NoteKind, RecipeNote, RecipeNoteStepRef, RecipeNoteOriginal, RecipeStorage, RecipeWait,
    LibraryName,         # the id -> canonical lookup the library search reads (migration 029)
    # ⚠️ Rating (the `ratings` table) is INTENTIONALLY NOT IMPORTED. Migration 048 froze it: the
    # verdict lives on CookLog.rating now. Re-importing it here is how a stray read gets written.
    CookLog, CookPhoto, RecipeSnapshot, User, Friendship, SharedPost, Comment, RecipeQueue,
    ImportFlag,          # U5: the imported_via provenance row, and the gate on baseline-at-first-save
    ingredient_weights,
)
from auth import auth_bp   # JSON auth endpoints (auth-2); auth.py imports models only, so no import cycle
import images              # shared image brain: resize + the save_image storage seam (Stage 1/2)
import snapshot_serialize  # single-source recipe-content snapshot FORMAT (shared ORM/serve + raw import)
import planahead
import notes as notes_rules   # the shared notes brain: split, kind, step references
import snapshot_diff        # derived change-tracking DIFF (O-c): current-vs-original recipe-page annotations
import snapshot_headsync    # pure baseline TRANSFORM: keep the original's heading layout in step with current
import import_write         # U4 preview: the PURE planner (plan_recipe) + db_state; the writer stays unused here
import url_cascade          # U2: layered reader + provenance
import url_fetch            # U0: the fetcher (network boundary; monkeypatched in tests)
import url_image            # U3: the guarded hero-image fetch (after the commit, never inside it)

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
#
# The ONE production switch, named once so the SECRET_KEY fence below and the cookie policy under it
# cannot drift apart: production is signalled by a Postgres DATABASE_URL (CLAUDE.md), the same switch
# that selects the prod database.
_IS_PRODUCTION = (os.environ.get("DATABASE_URL") or "").startswith("postgresql")

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    if _IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY must be set when DATABASE_URL is Postgres (production): refusing to start with "
            "the dev-only fallback, which would sign session cookies with a publicly-known key."
        )
    _secret_key = "dev-only-not-a-secret-set-SECRET_KEY-in-prod"   # dev/test ONLY (SQLite); see above
app.config["SECRET_KEY"] = _secret_key

# --- session cookie policy -----------------------------------------------------------------------
# HONEST POSITION: this makes an IMPLICIT protection EXPLICIT. It does not close an open hole.
# Every current browser already treats a Set-Cookie with NO SameSite attribute as SameSite=Lax, and
# Lax is what withholds the cookie on a cross-site POST. That default is doing real work here,
# because nothing else would: every route reads its body as `request.get_json(silent=True) or {}`,
# so a cross-site form POST is NOT rejected on content-type, and the payload-optional ones (e.g.
# POST /api/recipes/<rid>/cooked, which needs no fields at all) would write if the cookie arrived.
# So today's protection is a browser default this app never asked for. Asking for it costs nothing
# and stops the guarantee resting on someone else's default — which is what SECURITY.md's
# fail-closed stance calls for.
#
# Lax rather than Strict: the extra thing Strict withholds is the cookie on cross-site TOP-LEVEL GET
# navigation, and no GET route here writes (all of them are read-only), so Strict buys nothing today
# while making a link from an email or a chat arrive logged-out. Revisit if a GET ever writes.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Flask's default is already True; pinned so that turning it off has to be a deliberate edit.
app.config["SESSION_COOKIE_HTTPONLY"] = True
# Secure keys off the SAME production switch as SECRET_KEY above: a Secure cookie is never sent over
# plain HTTP, so setting it unconditionally would break local dev on http://localhost.
app.config["SESSION_COOKIE_SECURE"] = _IS_PRODUCTION

login_manager = LoginManager()
login_manager.init_app(app)
app.register_blueprint(auth_bp)   # /api/signup | /api/login | /api/logout | /api/me (all public; auth-3 gates the rest)


# THE RELOAD BAR'S SERVER HALF (Andy, 9 Oct, decisions-4). The server names the commit it runs on
# every API answer, and writes the same commit into the index.html it serves (see home). An open tab
# compares the two and shows a quiet bar when the server under it has moved on (static/update-check.js).
# ⚠️ READ ONCE, WHEN THE SERVER STARTS, because that is the code this process is running. A checkout
#    moved on underneath a running server has not changed what the server does until it restarts.
# ⚠️ AND ONLY A COMMIT-SHAPED ANSWER IS TRUSTED. Anything else, including a checkout git cannot read,
#    is "", which sends no header and no meta, and a page that hears nothing never shows the bar.
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _running_commit():
    """The commit this checkout is at, or "" when git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(BASE_DIR), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and _COMMIT_RE.fullmatch(sha) else ""


APP_COMMIT = _running_commit()


@app.after_request
def _name_the_commit(resp):
    # Every /api/ answer, a refusal included: a tab whose session has lapsed still learns the
    # server has moved on.
    if APP_COMMIT and request.path.startswith("/api/"):
        resp.headers["X-App-Commit"] = APP_COMMIT
    return resp


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


def ingredient_slug(name):
    r"""Mint an ingredients.id from a library canonical: 'egg pasta' -> 'egg_pasta'.

    ⚠️ UNDERSCORES, AND THIS IS NOT slugify() ABOVE. slugify mints RECIPE ids and emits hyphens
    ('andys-roast-chicken'). Every one of the 36 hand-authored ingredient ids used underscores
    (red_onion, soy_sauce, chile_powder), so an ingredient minted with hyphens would sit in the same
    column in a different shape and would never match the ones already there. ⚠️ Those 36 were
    deleted in migration 046, so nothing is left to clash with today. The convention holds anyway,
    since a column with two id shapes in it is worse than a column with one.

    ⚠️ \w IS UNICODE-AWARE AND THAT IS THE POINT. Folding to ASCII first, which import_write's
    _base_slug does for recipe titles, erases 56 of the 10,515 library canonicals outright: 丸糯米,
    オーロラソース, لحم مقدد, клёцки all reduce to the empty string. This keeps them.

    ⚠️ THE SEARCH ROUTE AND THE FUTURE SAVE PATH MUST BOTH CALL THIS ONE FUNCTION. The route reports
    whether a library row's slug is already taken in `ingredients`; the save path (a later stage)
    mints the id. Two implementations that drift by one character make the route's answer a lie.
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)     # drop punctuation, keep letters in every script
    s = re.sub(r"[\s_-]+", "_", s)     # spaces, hyphens and underscores collapse to one underscore
    return s.strip("_")


def recipe_stats(s, rid, user_id):
    """Derive THIS user's cooking stats for a recipe from the cook log alone (rescoping R5: per-user
    — MY cook_count, MY last_cooked, MY rating). Migration 048 made the log the single source: the
    rating is the AVERAGE of my rated cooks, so nothing here reads the frozen ratings table. cook_count and last_cooked are computed,
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
        select(CookLog.id, CookLog.cooked_on, CookLog.source)
        .where(CookLog.recipe_id == rid, CookLog.user_id == user_id)
        .order_by(CookLog.cooked_on.desc(), CookLog.id.desc())
        .limit(1)
    ).first()
    last_id = last.id if last else None
    # Migration 048: the headline is the AVERAGE of this user's RATED cooks. An unrated cook is
    # EXCLUDED, never counted as zero, so logging a cook you haven't judged cannot drag the number
    # down. No rated cooks -> None -> "Unrated", the same empty state as before.
    rated = s.execute(
        select(func.avg(CookLog.rating), func.count(CookLog.rating))
        .where(CookLog.recipe_id == rid, CookLog.user_id == user_id, CookLog.rating.isnot(None))
    ).first()
    average, rated_count = (rated[0], rated[1]) if rated else (None, 0)
    return {
        "cook_count": count,
        "last_cooked": last.cooked_on if last else None,                     # None if never cooked
        "last_cooked_provisional": bool(last and last.source != "app"),
        "rating": float(average) if average is not None else None,
        # How many cooks the average is over, so the display can say so rather than presenting one
        # cook's verdict and an average over nine as the same kind of number.
        "rated_cooks": rated_count,
        "last_cook_id": last_id,
    }


def dialect_insert(s, table):
    """Return the engine-appropriate INSERT construct for an ON CONFLICT upsert (Stage 2b-2). Both the
    sqlite and postgresql dialects expose insert(...).on_conflict_do_update(index_elements=, set_=) +
    .excluded with the same signature for our usage, so the same upsert code works on both — SQLite
    (dev/tests today) and Postgres (once the engine flips in 2b-5)."""
    ins = pg_insert if s.get_bind().dialect.name == "postgresql" else sqlite_insert
    return ins(table)


# Half stars (migration 048). The whole set, written out, because it is also what the CHECK holds and
# the two must not drift. 0.5 is the floor: a zero-star rating and an unrated cook would look the same
# on screen, and NULL already means unrated.
RATING_STEPS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)


def clean_rating(raw, *, allow_none=True):
    """Normalize + validate a per-cook rating. Returns (rating_or_None, error).

    ⚠️ int AND float BOTH ARRIVE. JSON sends 4 for a whole star and 4.5 for a half, so a guard written
    as isinstance(x, float) rejects every whole rating and one written as isinstance(x, int) rejects
    every half. bool is excluded explicitly, since it is an int subclass and True would pass as 1."""
    if raw is None:
        return (None, None) if allow_none else (None, "rating is required")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, "rating must be a number"
    value = float(raw)
    if value not in RATING_STEPS:
        return None, "rating must be a whole or half star from 0.5 to 5"
    return value, None


def set_cook_rating(s, cook_log_id, rating):
    """Write a verdict onto ONE cooking. The rating and its timestamp move together: a rating with no
    rated_at cannot be told apart from one made the day of the cook, and clearing one must clear both."""
    s.execute(update(CookLog.__table__)
              .where(CookLog.__table__.c.id == cook_log_id)
              .values(rating=rating, rated_at=now_utc() if rating is not None else None))


def _promote_library_row(s, library_id, known):
    """Resolve a line's `item_library_id` to an ingredients.id, creating the row if it is new.

    Returns (ingredient_id, canonical, error). Called only by resolve_recipe_payload, and split out
    so the resolution order below is readable rather than nested inside the gate's loop.

    ⚠️ THE ORDER IS THE WHOLE CORRECTNESS ARGUMENT, AND GETTING IT WRONG WAS A REAL BUG. It reads
    lookup, then library_id, then slug, then insert:
      1. LOOKUP     an id library_names does not hold creates nothing. Outermost on purpose, so the
                    junk-proofing gate cannot be stepped around by any later branch.
      2. LIBRARY_ID an ingredients row already recording THIS library row as its origin. ⚠️ THIS
                    STEP WAS MISSING and a pre-push review found what that cost. Checking the slug
                    alone is not idempotent: promote Q1063736 as 'penne', let apply_renames change
                    its canonical to 'penne rigate' on the next rebuild, promote it again, and the
                    new slug misses the old row and inserts a SECOND row carrying the same
                    library_id. /api/library/search then resolves that library_id through a dict
                    built in a loop, so it answers with whichever row the database returned last.
                    Matching on library_id first makes a repeat promote a no-op and makes this
                    function agree with what search reports as already promoted.
      3. SLUG       the id this canonical would mint is already taken. See below.
      4. INSERT     nothing else claimed it.

    ⚠️ THE CANONICAL COMES FROM library_names, NEVER FROM THE REQUEST. That is the whole of the
    junk-proofing. A caller supplies a key and nothing else, this function looks the name up, and a
    key the table does not hold creates nothing. The id space is closed at whatever the lookup holds,
    every entry of which the library's admission rules already sanctioned. The canonical is returned
    as well as used, so the gate can default a line's label to it and a promoted line reads
    "egg pasta" rather than the slug's "egg_pasta".

    ⚠️ CHECK-THEN-LINK BEFORE INSERT, AND SKIPPING IT IS A PRIMARY-KEY CONFLICT. 32 of the 36
    hand-authored ingredient ids are reproduced exactly by slugifying some library canonical (garlic,
    red_onion, soy_sauce), and those rows carry no library_id because nobody promoted them. When the
    slug is already taken the existing row is linked to and left ALONE: its name, descr, pairs and
    library_id are not overwritten, because a hand-written row is not improved by a library name.

    ⚠️ ingredient_slug IS THE SHARED MINTING RULE, and /api/library/search calls the same function to
    decide its matched_by:"slug" answer. Re-implementing it here by one character would make that
    route's answer false.
    """
    canonical = s.scalars(
        select(LibraryName.canonical).where(LibraryName.library_id == library_id)).first()
    if not canonical:
        # 1. Not in the lookup, so nothing is created. This is also the whole of the self-disabled
        # state: on a fresh clone and in CI library_names is EMPTY, every item_library_id lands
        # here, and the gate behaves exactly as it did before add-on-save.
        return None, None, (f"an ingredient line links to library id '{library_id}', "
                            "which isn't in the library")

    promoted = s.scalars(
        select(Ingredient.id).where(Ingredient.library_id == library_id)).first()
    if promoted:
        return promoted, canonical, None       # 2. already promoted, whatever its slug is now

    slug = ingredient_slug(canonical)
    if not slug:
        return None, None, f"an ingredient line links to '{canonical}', which has no usable name"
    if slug in known:
        return slug, canonical, None           # 3. the id is taken, link and do not touch it

    # 4. Genuinely new. source='app' so the delete path may remove it and so it is distinguishable
    # from the hand-authored 36 (migration 030). descr and pairs stay NULL.
    # ⚠️ concept MUST BE SUPPLIED, NOT LEFT TO THE COLUMN DEFAULT (migration 031). The default is ''
    # and the partial unique index permits exactly ONE library row at any concept, so omitting it here
    # creates the first promoted ingredient and then fails on the second. concept == slug today
    # because this path mints the id FROM the canonical, so the two are the same string by
    # construction. owner stays NULL, which marks a LIBRARY row, and under the corrected model that is
    # PERMANENT for this path. Promoting a library entry always yields a library row. The Panel's stage 3
    # adds a separate user-create path for personal rows. See docs/ingredient-model.md.
    s.execute(insert(Ingredient.__table__).values(
        id=slug, name=canonical, concept=slug, source="app", library_id=library_id,
        created_at=now_utc()))
    known.add(slug)                            # a second line naming it in the same payload links
    return slug, canonical, None


def _step_parts(step):
    """(text, is_heading, heading_level) for ONE payload step, in either wire form.

    ⚠️ TWO WIRE FORMS, AND BOTH ARE LIVE.
      {"heading": "MAKE THE SAUCE"}   a section heading. The original form, unchanged.
      {"heading": "Deseed", "level": 2}   a SUBHEADING (migration 059).
      {"text": "Whisk it."}           a method step (option C, commit 1). Carries the row's `id`.
      "Whisk it."                     a method step as a BARE STRING. The original form, and it is
                                      not going away: the import review posts plain text, every
                                      hand-written test payload is a string, and a browser holding
                                      the old bundle across a deploy posts one too.

    ⚠️ IT EXISTS BECAUSE THE STRING CHECK WAS LOAD-BEARING IN TWO PLACES AND WOULD HAVE FAILED
    SILENTLY IN BOTH. write_recipe_rows read a step as `step if isinstance(step, str) else ""`, so
    a {"text": ...} step would have been written BLANK, and nonEmptySteps treats a blank step as a
    deletion. resolve_recipe_payload's [[key]] scan read `(step or {}).get("heading", "")`, so the
    links inside an object step would not have been checked at all. One reader now, not two.

    ⚠️ THE LEVEL IS NARROWED HERE, AND THAT IS THE ONLY GUARD THERE IS. Migration 059 ships without a
    CHECK, because SQLite cannot add one without recreating the table. Anything that is not 2 reads
    as 1, so a missing key, a null, a string and a 7 all land on the default rather than in the
    column. A NON-HEADING step is always 1: the level is meaningless there, and a step that carries 2
    dormantly from a conversion must not put a key on a content row (see snapshot_step_row).

    ⚠️ AN OLD BUNDLE POSTS NO LEVEL AND THAT IS WHY THE DEFAULT IS 1, not "whatever was stored". A
    browser holding the pre-059 bundle across a deploy sends {"heading": "Deseed"} for a row that IS
    a subheading, and honouring the absence would silently promote it. The cost is the honest one: a
    save from a stale bundle flattens the levels it did not know about, which is visible and fixable,
    where the alternative is a payload that can never demote a heading at all."""
    if isinstance(step, dict):
        heading = step.get("heading")
        if heading:
            return heading, True, (2 if step.get("level") == 2 else 1)
        return (step.get("text") or ""), False, 1
    return (step if isinstance(step, str) else ""), False, 1


def resolve_recipe_payload(s, payload, standing_step_links=frozenset()):
    """Return (clean, error). Validates a payload and RESOLVES its ingredient links, CREATING an
    ingredients row when a line names a library entry that has not been promoted yet.

    `standing_step_links` are the [[key]]s the recipe's stored steps ALREADY carry. They are let
    through even when nothing in `ingredients` answers to them. See the step loop below.

    ⚠️ THIS FUNCTION WRITES. It was called validate_recipe_payload and it was renamed when add-on-save
    gave it a create path, because a reader of create_recipe should not have to open a function named
    validate_* to discover that saving a recipe can add a row to a table every other recipe shares.
    The write is one INSERT into `ingredients`, described in _promote_library_row.

    ⚠️ IT WRITES ON THE CALLER'S SESSION AND DOES NOT COMMIT. Both callers (create_recipe,
    update_recipe) return early on error and on their own later failures, and `with orm_session()`
    closes without committing, so a created row is rolled back with everything else. A test pins this
    against the 409 duplicate-name path, which fails AFTER the gate has already created a row.

    THE THREE CASES for an ingredient line, and a line carries at most one of the two keys:
      1. `item`               an ingredients.id, meaning exactly what it has always meant. Rejected
                              if absent from the table, exactly as before.
      2. `item_library_id`    a library_names.library_id. Resolved to a slug and created if new,
                              linked if the slug is already taken. See _promote_library_row.
      3. neither              a plain-text line. Always fine, never a link.
    A line sending BOTH is refused rather than guessed at.

    ⚠️ STEP [[key]] LINKS ARE UNCHANGED AND CANNOT CREATE. Step-link promotion was dropped, so a
    step's key is still checked against existing ingredient ids and still refused when missing. The
    reverse lookup a step would need is not a function anyway: 63 slugs map to 129 library rows.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        return None, "a name is required"
    ingredients = payload.get("ingredients")
    steps = payload.get("steps")
    if not isinstance(ingredients, list) or not isinstance(steps, list):
        return None, "ingredients and steps must be lists"
    # ⚠️ CHECKED HERE, BEFORE ANYTHING IS WRITTEN, because write_plan_ahead deletes before it
    #    inserts and `or []` read a null, a string and a dict all as "delete them all". These two
    #    keys are OPTIONAL in a way ingredients and steps are not: absent means the save has no
    #    opinion and the stored rows stand (see write_plan_ahead). Present and the wrong type is a
    #    client bug, so it is refused rather than guessed at.
    for key in ("waits", "storage"):
        if key in payload and not isinstance(payload[key], list):
            return None, f"{key} must be a list"
    # ⚠️ NOTES TAKES A LIST OR A BARE STRING, AND NOTHING ELSE REACHES write_notes. The rows came
    #    with migration 060, and the string is the previous client's single textarea, split by the
    #    same rule the corpus move used. Every other type was read as "delete them all": a dict
    #    iterates to its KEYS and a list of numbers filters to nothing, so `notes: [1, 2, 3]`
    #    answered 200 and left the recipe with 0 note rows. Live carries 177 notes over 95 recipes,
    #    and the waits key two lines up is in this function for exactly the same reason.
    if "notes" in payload and not isinstance(payload["notes"], (list, str)):
        return None, "notes must be a list of notes, or text"
    # ⚠️ AND AN ENTRY OF THE WRONG TYPE IS THE SAME CLIENT BUG AS A LIST OF THE WRONG TYPE. An int
    #    in `waits` reached w.get("label") and raised a 500. The same int in `notes` was skipped in
    #    silence, which is the deletion above through a narrower door. `steps` is deliberately not
    #    on this list: a bare string IS a legitimate step, which is what _step_parts reads.
    for key in ("waits", "storage", "notes"):
        rows = payload.get(key)
        if isinstance(rows, list) and any(not isinstance(r, dict) for r in rows):
            return None, f"each entry in {key} must be an object"
    # ⚠️ AND A FIELD INSIDE A NOTE IS THE SAME CLIENT BUG ONE LAYER DOWN. The two checks above stop
    #    at the container and the entry, so every scalar inside a note reached write_notes untyped
    #    and five shapes were a 500 on ordinary malformed input: `text: 5` raised on .strip(),
    #    `step_id: [1]` and `kind: ["notes"]` raised on `in` against a set, `refs: 7` raised on
    #    iteration. Nothing was lost, because the 500 rolls the whole PUT back, but a save path
    #    REFUSES WHAT IT CANNOT READ rather than crashing on it.
    # ⚠️ A bool IS AN int IN PYTHON, so True would quietly mean row 1. _check_row_ids guards exactly
    #    this for ingredient and step ids, with a comment saying why; notes had no equivalent.
    # ⚠️ AN UNKNOWN KIND IS REFUSED HERE RATHER THAN RESET SILENTLY. The PATCH door already answers
    #    400 for one, and the save path turned it into DEFAULT_KIND, so the same value meant two
    #    things depending on which door it came through. A kind the table does not list is a caller
    #    that invented one.
    note_err = _note_payload_error(payload.get("notes"), set(s.scalars(select(NoteKind.kind))))
    if note_err:
        return None, note_err

    known = set(s.scalars(select(Ingredient.id)))

    resolved = []
    for row in ingredients:
        row = dict(row) if row else {}
        item, library_id = row.get("item"), row.pop("item_library_id", None)
        # ⚠️ TYPE FIRST, BECAUSE THE ALTERNATIVE IS A 500. `item not in known` on a list raises
        #    TypeError (unhashable), and a list bound into the library_id lookup raises in the
        #    driver. Both surfaced as a 500 with a traceback on ordinary malformed client input.
        #    The `item` half of this predates add-on-save and was found by the same review.
        # ⚠️ AND THE SECOND AMOUNT, WHICH IS WRITTEN STRAIGHT INTO A TEXT COLUMN. A list or a dict
        #    reaching that column is a 500 on the driver, which is what the two checks above exist
        #    for. Absent is fine and means the client has no opinion. See _ing_row_values.
        for key, value in (("item", item), ("library id", library_id),
                           ("second amount", row.get("secondary_measure"))):
            if value is not None and not isinstance(value, str):
                return None, f"an ingredient line's {key} must be text"
        if item and library_id:
            return None, "an ingredient line sends both an item and a library id, pick one"
        if item and item not in known:
            return None, f"an ingredient line links to '{item}', which isn't in your library"
        if library_id:
            item, canonical, err = _promote_library_row(s, library_id, known)
            if err:
                return None, err
            row["item"] = item                 # downstream sees an ordinary link and nothing new
            label = row.get("label")
            if not (isinstance(label, str) and label.strip()):
                # write_recipe_rows falls back to the ID when a label is missing, which renders the
                # slug: "egg_pasta". The canonical is the readable form of the same thing.
                row["label"] = canonical
        resolved.append(row)

    # ⚠️ A LINK THE RECIPE ALREADY CARRIES IS NOT A TYPO, AND REFUSING IT LOCKS THE RECIPE.
    #    The gate exists to catch a key the user just typed that names nothing. It was also
    #    refusing keys that were written long ago and whose target has since gone, which made five
    #    recipes unsaveable: aloo-gobhi, bulgogi-bowls, gai-yang, mussakhan and no-knead-bread all
    #    link to ingredients that migration 046 removed when it emptied the table. Every save of
    #    those five returned 400 and there was no way to edit them at all.
    #
    #    Letting a standing link through changes nothing on the page. linkify renders [[key|label]]
    #    as a button from the TEXT alone and never checks that the key resolves, so a step reads
    #    identically either way. The step text is stored verbatim, so nothing about it moves.
    for step in steps:
        text, _, _ = _step_parts(step)
        for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text or ""):
            key = m.group(1).strip()
            if key not in known and key not in standing_step_links:
                return None, f"a step links to '{key}', which isn't in your library"
    return {"name": name, "ingredients": resolved, "steps": steps}, None


# Everything a stored ingredient row carries that the client never sends back. A save that does not
# re-apply these DESTROYS them, which is what previews/save-path-scoping.md measured: a no-edit save
# was clearing label, overwriting raw_text with the displayed label and wiping all four linkage
# columns on every row of the recipe, 2,767 links over 293 recipes one save away from gone.
CARRIED = ("raw_text", "label", "note", "qty", "quantity", "unit",
           "catalog_id", "link_confidence", "link_rule", "link_matched",
           "grams", "secondary_measure")


def _heading_title(o):
    """A stored heading row's TITLE: `heading` when set, else raw_text. The Python mirror of the
    client's headingText(), and the compatibility story for migration 052 — all 223 pre-052 heading
    rows have heading NULL and their title in raw_text, so the fallback reads them unchanged."""
    h = o["heading"] if "heading" in o.keys() else None
    return h if h is not None else (o["raw_text"] or "")


def _name_key(name):
    """The display name, normalized for matching. Whitespace is COLLAPSED, not just trimmed,
    because the client sends every field through oneLine() and a stored name with a double space
    would otherwise never match itself."""
    return " ".join((name or "").split()).lower()


def _preserve_key(qty, name):
    """Match key for carrying a stored row's own columns across an edit. The amount and the line's
    display name (its label, or raw_text when there's no label), keyed identically on both sides.
    `note` is deliberately excluded, so a note-only edit keeps the weight.

    ⚠️ THE AMOUNT IS COMPARED THROUGH units.canon_unit_str, BECAUSE THE CLIENT REWRITES IT. The
    editor sends every unit through scaler.js canonicalizeUnit, so a row stored as "1 teaspoon"
    comes back as "1 tsp" on a save that changed nothing. Measured on live data: 1,157 of 3,349
    rows are rewritten that way and 66 of them carry a harvested weight. Comparing the raw strings
    made every one of those a key MISS, which silently cleared the weight on an untouched line.
    canon_unit_str is the Python mirror of that client function, held to it by
    tests/js/unit-abbrev-sync.test.js, so both sides collapse "1 teaspoon", "1 Teaspoon" and
    "1 tsp" to one key. It changes representation only and never a number.

    It still does NOT fold fractions, so "1 cup" != "1 c" and a real amount change is a real one."""
    return (canon_unit_str(qty or ""), _name_key(name))


class _Carry:
    """Match each incoming row to the stored row it replaces, and hand back what that row carried.

    ⚠️ TWO TIERS, AND THEY CARRY DIFFERENT THINGS.
      EXACT  (qty, name) unchanged  -> the row is untouched. Everything carries, grams included,
                                       and qty/quantity/unit carry VERBATIM so a no-edit save is
                                       byte-identical rather than merely equivalent.
      NAME   only the qty changed   -> the line still names the same food, so raw_text and the
                                       links carry. grams and secondary_measure do NOT: a harvested
                                       weight belongs to the amount it was harvested from, which is
                                       the rule test_edit_preserves_unchanged_harvested_grams pins.

    The name tier is an EXTENSION of the key previews/save-path-scoping.md proposed, added because
    the brief's own rule is that a row the user did not edit keeps everything. Changing "2 tbsp" to
    "3 tbsp" does not edit the ingredient, and dropping its link there would be the same class of
    silent loss this whole change exists to stop.

    ⚠️ ONE STORED ROW IS CONSUMED AT MOST ONCE, in order of appearance. Measured on live data:
    57 of 297 recipes (19%) repeat an ingredient NAME and 17 (6%) repeat the full (qty, name) key,
    25 keys over 50 rows. Without the consume-once rule those 50 rows would all carry the FIRST
    match's values. They happen to be byte-identical today, so nothing is visibly wrong yet, which
    is exactly the kind of latent many-to-one this guards against.
    """

    def __init__(self, stored):
        self.exact, self.by_name, self.headings = {}, {}, {}
        self.used = set()
        for o in stored:
            if o["is_heading"]:
                # ⚠️ THE TITLE, NOT raw_text. Since migration 052 a heading converted from a line
                # keeps the line's source text in raw_text and holds its title in `heading`, so
                # bucketing on raw_text would look this row up under the wrong string.
                self.headings.setdefault(_name_key(_heading_title(o)), []).append(o)
                continue
            name = o["label"] or o["raw_text"]
            self.exact.setdefault(_preserve_key(o["qty"], name), []).append(o)
            self.by_name.setdefault(_name_key(name), []).append(o)

    def _first_free(self, bucket):
        while bucket:
            o = bucket.pop(0)
            if o["id"] not in self.used:
                self.used.add(o["id"])
                return o
        return None

    def plan(self, lines):
        """Resolve every incoming line to the stored row it replaces. `lines` is
        [(qty, name) or None for a heading], aligned to the payload. Returns the same
        length, each entry (stored row, exact?) or None.

        ⚠️ THE TIERS ARE TWO PASSES OVER THE WHOLE RECIPE, never one pass per row. A line that
        matches only by NAME must not consume a stored row that some LATER line matches exactly.
        Resolving row by row, inserting "1 pinch salt" above an untouched "1 tsp salt" and
        "2 tbsp salt" did exactly that: the pinch row fell to the name tier and took the dough
        salt's raw_text and link, the dough row then took the brine's, and the brine row lost its
        link and its line. Two untouched rows corrupted by adding a third above them.
        """
        held = [None] * len(lines)
        for i, ln in enumerate(lines):                      # pass 1: every EXACT match, in order
            if ln is None:
                continue
            o = self._first_free(self.exact.get(_preserve_key(ln[0], ln[1]), []))
            if o is not None:
                held[i] = (o, True)
        for i, ln in enumerate(lines):                      # pass 2: NAME only, over what is left
            if ln is None or held[i] is not None:
                continue
            o = self._first_free(self.by_name.get(_name_key(ln[1]), []))
            if o is not None:
                held[i] = (o, False)
        return held

    def take_heading(self, text):
        return self._first_free(self.headings.get(_name_key(text), []))


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


def _label_key(text):
    """A wait's or storage row's wording, whitespace-folded. Case is NOT folded: changing a letter is
    an edit, and this decides whether a stored figure still describes what the row now says."""
    return " ".join((text or "").split())


def _match_rows(stored, incoming, has_ext, field="label"):
    """Pair each incoming row with the stored row it CONTINUES, or None when it is genuinely new.

    TWO PASSES, AND THEIR ORDER IS THE WHOLE RULE:

      1. by WORDING, each stored row usable ONCE. An unchanged save and a pure reorder land entirely
         here, which is what keeps every id and leaves the snapshot bytes untouched. Consume-once
         because a recipe may hold two waits reading identically, and the first incoming one must
         not take the second's row twice.
      2. by ORDER, over whatever is left. A REWORDED row is an edit of the row that was sitting
         there, not a deletion and an addition. Matching it keeps its id, so the page reports a
         change instead of one row vanishing and another appearing, and the id sequence stops
         climbing every time someone fixes a typo.

    Returns (pairs, leftovers) where pairs is [(stored row or None, matched_by_wording)] aligned
    with `incoming`, and leftovers is the stored rows nothing claimed, which are the deletions.

    ⚠️ matched_by_wording IS NOT THE SAME QUESTION AS matched. It decides whether the stored MINUTES
    still describe the row's words. A row matched in pass 2 keeps its id and is RE-READ, because its
    wording is what changed. A row matched in pass 1 keeps both. Collapsing the two would either
    re-read a wait nobody edited, which is the defect decision 1 fixed, or carry a stale figure onto
    wording it no longer describes."""
    # ⚠️ `field` IS THE COLUMN THE WORDING LIVES IN, and it is a parameter because a note's wording
    #    is its `text` while a wait's is its `label`. The RULE is identical for both and is stated
    #    once here, which is the point.
    pool = {}
    for m in stored:
        pool.setdefault(_label_key(m[field]), []).append(m)

    pairs = [None] * len(incoming)
    claimed = set()
    for i, (label, _ext) in enumerate(incoming):
        bucket = pool.get(_label_key(label))
        if bucket:
            row = bucket.pop(0)
            claimed.add(row["id"])
            pairs[i] = (row, True)

    spare = [m for m in stored if m["id"] not in claimed]
    for i, pair in enumerate(pairs):
        if pair is None and spare:
            row = spare.pop(0)
            claimed.add(row["id"])
            pairs[i] = (row, False)
    pairs = [pr if pr is not None else (None, False) for pr in pairs]
    return pairs, [m for m in stored if m["id"] not in claimed]


def _stored_rows(s, table, rid):
    return list(s.execute(select(table).where(table.c.recipe_id == rid)
                          .order_by(table.c.position)).mappings())


def _kept_minutes(pair, has_ext, ext_label):
    """(own minutes or None, extension minutes or None) for a matched row.

    ⚠️ THE TWO HALVES ARE DECIDED SEPARATELY, because they are two pieces of wording on one row. A
    cook who rewrites the extension and leaves the wait alone has edited the extension only, so the
    wait's own minutes still describe its own words and are kept."""
    row, by_wording = pair
    if row is None or not by_wording:
        return None, None
    own = (row["min_minutes"], row["max_minutes"])
    ext = None
    if has_ext and _label_key(row["ext_label"]) == _label_key(ext_label):
        ext = (row["ext_min_minutes"], row["ext_max_minutes"])
    return own, ext


def _apply_rows(s, table, plan, doomed):
    """Write one of a recipe's child lists: UPDATE what was matched, INSERT only what is new, DELETE
    only what nothing claimed. `plan` is a list of (stored row or None, values).

    ⚠️ THE SURVIVORS' POSITIONS ARE PUSHED OUT OF THE WAY FIRST. recipe_waits and recipe_storage both
    carry UNIQUE (recipe_id, position), so writing a reordered list straight back collides the moment
    two rows swap places, and a new row taking position 0 collides with the survivor still sitting
    there. Every matched row goes to a negative position first (-1 - its own, so they stay distinct
    and cannot meet the final 0..n-1 range), and then each row takes its final place. There is no
    CHECK on position, so the negative is legal in passing.

    recipe_steps has no such constraint, which is why write_recipe_rows can assign positions directly
    and why this dance lives here rather than there."""
    for m in doomed:
        s.execute(delete(table).where(table.c.id == m["id"]))
    for m, _v in plan:
        if m is not None:
            s.execute(update(table).where(table.c.id == m["id"])
                      .values(position=-1 - m["position"]))
    for m, v in plan:
        if m is None:
            s.execute(insert(table).values(**v))
        else:
            s.execute(update(table).where(table.c.id == m["id"]).values(**v))


def write_plan_ahead(s, rid, payload):
    """Replace a recipe's waits and storage from the save payload.

    ⚠️ THE NUMBERS ARE READ HERE, ONCE, FROM WHAT A PERSON TYPED. The editor sends one text box per
    wait and planahead.read_duration turns it into minutes. Text it cannot read keeps its words and
    leaves min and max NULL, which is the same contract normalize_time already has for a time column:
    a wrong value stays visible and fixable instead of disappearing.

    ⚠️ THE EXTENSION IS READ SEPARATELY AND NEVER FOLDED INTO THE RANGE. "or overnight if time
    allows" becomes ext_min 480 beside a normal range of 10 to 60, not a range of 10 to 480.

    ⚠️ UPDATE IN PLACE, matched by wording the same way the minutes are carried. This said
    "delete-and-reinsert ... there is no identity to carry across a save", and the row id IS an
    identity the snapshot records, so replacing the rows moved a recipe's bytes on a save that
    changed nothing.

    ⚠️ AN ABSENT KEY IS NOT AN EMPTY LIST, AND READING IT AS ONE DELETED EVERY WAIT ON THE RECIPE.
    This read `payload.get("waits") or []` and deleted first, so a PUT that simply did not mention
    waits removed all of them and answered 200. The browser always sends both keys, so nothing in the
    app reached it; the import review posts plain text, a script posts what it has, and a browser
    holding an older bundle posts the keys that bundle knew about. The step link is the part with
    nowhere else to live, since step_id exists only on the wait row.

    So the two lists are handled independently, and each one only when the payload names it. An
    explicit [] still deletes, which is how the editor clears the panel. The TYPE is checked in
    resolve_recipe_payload, before anything is written, for the same reason the ingredient and step
    lists are checked there: a wrong type must cost nothing."""
    rw, rs = RecipeWait.__table__, RecipeStorage.__table__
    # ⚠️ THE STORED ROWS ARE READ BEFORE THE DELETE, BECAUSE A SAVE MUST NOT CHANGE A WAIT THE COOK
    #    DID NOT EDIT. The minutes behind a wait are read from what a person typed, and some of them
    #    were read by a REVIEWER rather than by read_duration: brioche-bread's extension says "or an
    #    hour of fridge rest if you skip the overnight proof" and carries the reviewed 60, where
    #    read_duration answers 480 because the word overnight is in the sentence.
    #
    #    Re-deriving every row on every save therefore overwrote a reviewed figure with a worse one,
    #    and it did so on a save that changed nothing at all. Measured over the 107 stored waits: 0
    #    labels and exactly 1 extension re-read differently from what is stored, so the blast radius
    #    is one row today and the rule is what matters. The page showed it as a wait "modified" entry
    #    whose from and to were the same words, since the printed label does not include the minutes.
    #
    #    THE RULE: stored minutes are kept unless that wait's own wording changed. Only an edited
    #    wait is re-read. read_duration is untouched — its reading of that sentence is a separate
    #    defect and it is on the roadmap with the Round B parser item.
    #    ⚠️ AND THE ROW IS UPDATED IN PLACE RATHER THAN REPLACED, which is the other half of the
    #    same rule. Deleting every row and inserting fresh ones gave each wait a NEW id on a save
    #    that changed nothing, and the snapshot carries the wait id, so the recipe's bytes moved and
    #    it dropped out of the byte-equal short-circuit for good. A row only gets a new id when it is
    #    genuinely new, and a row nothing matched is deleted. See _row_carry and _apply_rows.
    #    ⚠️ THE ROWS ARE MATCHED AND UPDATED IN PLACE, NOT REPLACED, which is the other half of the
    #    same rule. Deleting every row and inserting fresh ones gave each wait a NEW id on a save
    #    that changed nothing, and the snapshot carries the wait id, so the recipe's bytes moved and
    #    it dropped out of the byte-equal short-circuit for good. See _match_rows and _apply_rows.
    in_w = [(((w.get("label") or "").strip()), ((w.get("ext_label") or "").strip() or None))
            for w in (payload.get("waits") or ()) if (w.get("label") or "").strip()]
    in_s = [(((x.get("label") or "").strip()), None)
            for x in (payload.get("storage") or ()) if (x.get("label") or "").strip()]
    pairs_w, doomed_w = _match_rows(_stored_rows(s, rw, rid), in_w, True)
    pairs_s, doomed_s = _match_rows(_stored_rows(s, rs, rid), in_s, False)
    plan_w, plan_s = [], []
    # ⚠️ THE STEP IDS THIS RECIPE ACTUALLY HAS, read AFTER write_recipe_rows so they are the rows this
    #    save just wrote. A payload arrives with the ids the editor was holding, and a step deleted in
    #    this same save is still named by any wait that pointed at it.
    # ⚠️ HEADINGS ARE IN THIS SET NOW, AND THAT IS THE POINT. It read `is_heading == 0`, which was
    #    right while nothing could convert a step: a heading's id could only arrive by mistake. The
    #    step row menu converts one now, and a cook who marks a linked step as a heading and then
    #    touches the plan-ahead panel would have had the link silently cleared with no way to get it
    #    back, because the id lives nowhere else. Keeping it stored means converting back restores
    #    the link, which is what a reversible conversion has to mean.
    #
    #    ⚠️ AND IT DOES NOT MAKE A HEADING PRINTABLE. planahead.resolve_steps numbers the ordinary
    #    steps only and hands back step_no None for a heading, so the link is held but never printed
    #    as "(step N)". Storing it and printing it are different questions and this answers the
    #    first. The two things this set still refuses are unchanged: an id naming NO row of this
    #    recipe (a deleted step) and an id belonging to a DIFFERENT recipe both become NULL.
    step_ids = {m["id"] for m in s.execute(
        select(RecipeStep.__table__.c.id)
        .where(RecipeStep.__table__.c.recipe_id == rid)).mappings()}
    pos = -1
    for w in (payload.get("waits") or ()):                        # absent -> nothing to insert
        label = (w.get("label") or "").strip()
        if not label:
            continue
        pos += 1
        # ⚠️ KEPT, NOT RE-READ, WHEN THE WORDING IS THE SAME. See the note above _match_rows.
        ext = (w.get("ext_label") or "").strip() or None
        pair = pairs_w[pos]
        kept = pair[0]
        own, ext_kept = _kept_minutes(pair, True, ext)
        lo, hi = own if own is not None else planahead.read_duration(label)
        if ext_kept is not None:
            elo, ehi = ext_kept
        else:
            elo, ehi = planahead.read_duration(ext) if ext else (None, None)
        kind = w.get("kind") if w.get("kind") in planahead.KINDS else "other"
        # ⚠️ only_if WITHOUT A CONDITION FALLS BACK TO always, because the CHECK rejects the row and
        #    a save must not 500 on a half-filled picker. "if" with nothing after it says nothing.
        when_kind = w.get("when_kind") if w.get("when_kind") in planahead.WHENS else "always"
        when_label = (w.get("when_label") or "").strip() or None
        if when_kind != "only_if":
            when_label = None
        elif not when_label:
            when_kind = "always"
        # ⚠️ AN ID THAT NAMES NO ORDINARY STEP OF THIS RECIPE BECOMES NULL, AND THIS IS WHAT CLEARS
        #    THE LINK WHEN A LINKED STEP IS DELETED. The user removes the step, the editor still holds
        #    the wait pointing at it, and this drops the pointer instead of inserting a row the foreign
        #    key would refuse. It also refuses a step id belonging to a DIFFERENT recipe, since the set
        #    is scoped to this one. The column's ON DELETE SET NULL is the backstop underneath, for any
        #    route to a deleted step that does not come through here.
        #
        #    Migration 053 replaced step_position and step_check. There is nothing to recompute now: a
        #    wait keeps its id through a reorder because a save updates step rows in place, which is the
        #    whole reason the snippet existed and the whole reason it is gone.
        sid = w.get("step_id")
        sid = sid if sid in step_ids else None
        # ⚠️ THE OVERLAP POINTER GETS THE SAME TREATMENT, AND alongside FALLS BACK THE WAY only_if DOES.
        #    A when_kind the picker has half filled in must not 500 the save, so an 'alongside' with no
        #    usable step to run alongside becomes an ordinary 'always' wait — which reads correctly and
        #    is fixable, where a refused save loses the whole edit. The three CHECKs on the table are
        #    the floor under this, not a substitute for it.
        #
        #    A wait cannot run alongside its OWN step: that says nothing, and the table refuses it.
        aside = w.get("alongside_step_id")
        aside = aside if (aside in step_ids and aside != sid) else None
        if when_kind == "alongside" and aside is None:
            when_kind = "always"
        if when_kind != "alongside":
            aside = None
        # ⚠️ THE ALTERNATIVE'S OWN STEP, AND NULL WHEN IT WOULD REPEAT step_id. 5 of the 7 stored
        #    extensions state the alternative in the wait's own step ("marinate 10 minutes to an
        #    hour, or overnight if time allows"), and a second "(step 1)" on that line says nothing.
        #    Only an alternative that is described SOMEWHERE ELSE carries a link: beans puts its
        #    quick soak at step 3, brioche-bread puts its shorter option at step 11.
        #    A link with no ext_label to hang on is dropped too, for the same reason the extension
        #    minutes are dropped without one.
        esid = w.get("ext_step_id")
        esid = esid if (ext and esid in step_ids and esid != sid) else None
        plan_w.append((kept, dict(
            recipe_id=rid, position=pos, kind=kind, label=label,
            min_minutes=lo, max_minutes=hi, step_id=sid, alongside_step_id=aside,
            ext_label=ext, ext_min_minutes=elo, ext_max_minutes=ehi, ext_step_id=esid,
            when_kind=when_kind, when_label=when_label)))
    pos = -1
    for x in (payload.get("storage") or ()):                      # absent -> nothing to insert
        label = (x.get("label") or "").strip()
        if not label:
            continue
        pos += 1
        # ⚠️ STORAGE RE-DERIVES ON SAVE TOO, so it gets the same rule. A storage row has one piece of
        #    wording and no extension, so there is one half to decide.
        pair = pairs_s[pos]
        kept = pair[0]
        own, _ = _kept_minutes(pair, False, None)
        lo, hi = own if own is not None else planahead.read_duration(label)
        where = x.get("where_kept") if x.get("where_kept") in planahead.WHERES else "other"
        plan_s.append((kept, dict(
            recipe_id=rid, position=pos, where_kept=where,
            applies_to=(x.get("applies_to") or "").strip() or None,
            label=label, min_minutes=lo, max_minutes=hi)))
    # ⚠️ EACH LIST IS WRITTEN ONLY WHEN THE PAYLOAD NAMES IT. An absent key is not an empty list,
    #    which is the rule the docstring above spends its length on, and it is now the thing that
    #    decides whether unmatched rows are deleted at all.
    if "waits" in payload:
        _apply_rows(s, rw, plan_w, doomed_w)
    if "storage" in payload:
        _apply_rows(s, rs, plan_s, doomed_s)


def _copy_row_map(s, table, old_rid, new_rid):
    """{old row id: the new row's id} for a table copied in position order.

    ⚠️ THE ORDER IS THE KEY, NOT THE POSITION VALUE. The copy is written row by row in
    (position, id) order, so the two sides line up by RANK in that order and by nothing else: the
    new ids are whatever AUTOINCREMENT handed out.

    ⚠️ IT KEYED ON THE POSITION VALUE AND CLAIMED THAT COULD NOT COLLIDE, WHICH IS FALSE FOR TWO OF
    THE FOUR TABLES IT SERVES. recipe_waits and recipe_storage carry UNIQUE (recipe_id, position);
    recipe_steps and recipe_ingredients carry no such constraint (migrations/001, and _apply_rows
    says so). Forced on a throwaway kitchen: two steps at position 0 collapsed to one entry in the
    dict and a wait pointing at the other was remapped to NULL, losing the link in silence. Live has
    no duplicate group today, so this is the defensive direction rather than a repair. Ranking is
    correct either way and needs no premise about the data."""
    def ranked(rid):
        return [m["id"] for m in s.execute(
            select(table.c.id, table.c.position).where(table.c.recipe_id == rid)
            .order_by(table.c.position, table.c.id)).mappings()]
    return dict(zip(ranked(old_rid), ranked(new_rid)))


def _pair_notes(stored, incoming, in_n):
    """Pair each incoming note with the stored row it IS, or None when it is new.

    ⚠️ BY ID WHEN THE PAYLOAD CARRIES IDS, AND THAT IS WHAT MAKES A DELETION A DELETION. Matching
    by wording and then by ORDER cannot tell "delete A, add B" from "reword A": both arrive as one
    list of the same length, so the added note took the deleted one's row. It cost a note nothing
    (recipe_notes is outside the snapshot blob and recipe_notes_original keys on (recipe_id,
    position), not on a row id), and it was still the server guessing at an answer the client knew.
    Edit mode holds the cook's own rows, so it sends their ids and the guess is gone.

    ⚠️ ONE ID IS CLAIMED ONCE, AND AN UNKNOWN ONE IS SIMPLY NEW. A repeated id, an id belonging
    to another recipe and an id that no longer exists all land in the same safe place: a new row.
    The pool is built from THIS recipe's stored rows, so a payload cannot reach another recipe's
    notes by naming one.

    ⚠️ AND THE FALLBACK IS KEPT FOR A PAYLOAD WITH NO IDS AT ALL. The previous bundle sends one
    string, split into rows that never had ids, and an older client sends a list without them. For
    those, wording-then-order is still the right rule and is still what keeps an unchanged save from
    moving a single row.

    Returns the same (pairs, leftovers) shape _match_rows does."""
    def real(nid):
        return isinstance(nid, int) and not isinstance(nid, bool) and nid > 0

    if not any(real(n.get("id")) for n in incoming):
        return _match_rows(stored, in_n, False, field="text")

    pool = {m["id"]: m for m in stored}
    claimed, pairs = set(), []
    for i, n in enumerate(incoming):
        nid = n.get("id")
        row = pool[nid] if (real(nid) and nid in pool and nid not in claimed) else None
        if row is not None:
            claimed.add(nid)
        # matched_by_wording means "the stored wording still describes this row", which notes do not
        # read today. It is answered honestly rather than left as a stand-in for "matched".
        pairs.append((row, row is not None and _label_key(row["text"]) == _label_key(in_n[i][0])))
    return pairs, [m for m in stored if m["id"] not in claimed]


def record_notes_original(s, rid):
    """Record a recipe's note rows as the words it was born with. Once per recipe, or never.

    ⚠️ A NOTE IS A PLAYGROUND ONLY IF THERE IS A WAY BACK, AND AN APP-CREATED RECIPE HAD NONE.
    Andy's ruling is that editing a note costs the recipe nothing: no annotation entry, no mark, no
    place in the byte-equal set. Both halves need the notes OUT of the snapshot, so the baseline is
    not the record of what the author wrote. recipe_notes_original is that record, and until now
    only scripts/applied/notes_to_rows.py (the corpus move) and import_write.commit_plan (an
    import) wrote it. A recipe typed into the app therefore got the playground without the way
    back: reword a note, reload, and the words it was created with are gone from the database.

    ⚠️ ONE RULE, THREE DOORS. copy_recipe already had this written out as its fallback for a source
    with no originals of its own, and a comment claiming two places share a rule is not a function.

    ⚠️ IT WRITES ONCE AND UPDATES NEVER. An original that moved with the rows would be a copy of
    the rows, which is what recipes.notes was and what migration 063 dropped. A recipe that already
    has a row here is left exactly as it is, so this is safe to call twice.
    """
    t = RecipeNoteOriginal.__table__
    if s.execute(select(func.count()).select_from(t).where(t.c.recipe_id == rid)).scalar():
        return 0
    rows = list(s.execute(select(RecipeNote.__table__)
                          .where(RecipeNote.__table__.c.recipe_id == rid)
                          .order_by(RecipeNote.__table__.c.position)).mappings())
    at = now_utc()
    for row in rows:
        s.execute(insert(t).values(recipe_id=rid, position=row["position"], kind=row["kind"],
                                   text=row["text"], recorded_at=at))
    return len(rows)


def write_notes(s, rid, payload):
    """Write a recipe's NOTE rows from a validated payload, in place, and rebuild the derived column.

    ⚠️ ABSENT IS NOT EMPTY, which is the rule that once erased a headnote. A PUT that does not name
    `notes` leaves the rows exactly as they are. An explicit [] clears them, which is how the editor
    empties the list.

    ⚠️ THE ROWS ARE MATCHED AND UPDATED IN PLACE FROM DAY ONE. _pair_notes pairs incoming to
    stored BY ID where the payload carries ids, and by wording then by order where it does not. An
    unchanged save therefore writes the same rows back with the same ids either way, the snapshot
    bytes do not move, and the recipe keeps its place in the byte-equal short-circuit. Waits got
    this late and it cost brioche-bread its place in the set. Notes started with it.

    ⚠️ A STEP MENTIONED IN THE TEXT IS RE-SCANNED ON EVERY SAVE, and a reference survives only while
    its mention does. Carrying by (ref_index, match_text) means inserting a sentence before "step 9"
    keeps the link, and deleting the words "step 9" drops it, which is what a reference to something
    that is no longer written should do."""
    if "notes" not in payload:
        return
    rn, rnr = RecipeNote.__table__, RecipeNoteStepRef.__table__
    sent = payload.get("notes")
    # ⚠️ A STRING IS THE OLD SHAPE AND IT STILL WORKS, which is what makes the deploy window safe in
    #    both directions. The previous client sends one textarea's worth of prose; it is split by the
    #    SAME rule the corpus move used, so it lands as the same rows the new client would have sent.
    if isinstance(sent, str):
        sent = [{"text": para, "kind": notes_rules.kind_of(para)}
                for para in notes_rules.paragraphs(sent)]
    incoming = [n for n in (sent or ())
                if isinstance(n, dict) and (n.get("text") or "").strip()]
    in_n = [((n.get("text") or "").strip(), None) for n in incoming]
    # ONE read of the stored rows, shared by the pairing, the reference carry and the write, so the
    # three cannot disagree about which rows this save is working on.
    stored_n = _stored_rows(s, rn, rid)
    pairs_n, doomed_n = _pair_notes(stored_n, incoming, in_n)

    # The ids this recipe actually has, read AFTER write_recipe_rows so they are the rows this save
    # just wrote. Headings are in the set for the reason write_plan_ahead gives: a conversion has to
    # be reversible, and the id lives nowhere else. Which of them a link may NAME is
    # _note_step_target's question, not this read's, and _note_step_ids is the one reader.
    step_ids = _note_step_ids(s, rid)
    # ⚠️ THE NUMBERS THE PAGE PRINTS, for the "step N" auto-link. A cook typing "step 3" means the
    #    third step they can see, which is the third non-heading row.
    numbers = notes_rules.step_numbers([dict(m) for m in s.execute(
        select(RecipeStep.__table__).where(RecipeStep.__table__.c.recipe_id == rid)
        .order_by(RecipeStep.__table__.c.position, RecipeStep.__table__.c.id)).mappings()])
    ing_ids = {m["id"] for m in s.execute(
        select(RecipeIngredient.__table__.c.id)
        .where(RecipeIngredient.__table__.c.recipe_id == rid)).mappings()}
    kinds = {m["kind"] for m in s.execute(select(NoteKind.__table__.c.kind)).mappings()}

    # The references each stored row carries, so a kept row can carry them forward.
    stored_refs = {}
    for ref in s.execute(select(rnr).where(rnr.c.note_id.in_(
            [m["id"] for m in stored_n] or [0]))).mappings():
        stored_refs.setdefault(ref["note_id"], {})[(ref["ref_index"], ref["match_text"])] = ref["step_id"]

    plan, want_refs = [], []
    pos = -1
    for i, n in enumerate(incoming):
        text_ = (n.get("text") or "").strip()
        pos += 1
        kept = pairs_n[i][0]
        # ⚠️ ABSENT MEANS KEEP ON A ROW MATCHED BY ID, which is what _kept does for the recipe's own
        #    header fields and _kept_minutes does for a wait. A PUT naming a row by id and sending
        #    only its text used to answer 200 and clear the cook's chosen type AND their step link,
        #    and the documented old-client shape (a bare string, split into paragraphs) carried
        #    neither key, so one save from anything older than migration 060 wiped every kind and
        #    every step link on the recipe. Measured through the real route.
        def _keep(key, default=None):
            if key in n:
                return n[key]
            return kept[key] if kept is not None else default
        sid = _note_step_target(_keep("step_id"), step_ids,
                                kept["step_id"] if kept is not None else None)
        iid = _keep("ingredient_row_id")
        iid = iid if iid in ing_ids else None
        kind = _keep("kind", notes_rules.DEFAULT_KIND)
        kind = kind if kind in kinds else notes_rules.DEFAULT_KIND
        # ⚠️ AND THE TITLE IS KEPT THE SAME WAY, which is the whole reason _keep exists. A PUT that
        #    named a row by id and sent only its text once cleared the cook's chosen kind and their
        #    step link, and the old client's bare-string shape carries no keys at all, so a title
        #    read as absent-means-empty would be wiped by one save from anything older than this.
        title = _note_title(_keep("title"))
        plan.append((kept, dict(recipe_id=rid, position=pos, kind=kind, text=text_, title=title,
                                step_id=sid, ingredient_row_id=iid)))
        # What this note's references should be after the save: one per "step N" in the text,
        # taking an explicit payload value when the editor sent one, else the stored link when the
        # same mention was there before.
        # ⚠️ A SENT REFERENCE NAMES THE WORDS IT BELONGS TO, NOT JUST THE ORDINAL. This was keyed on
        #    ref_index alone, and the editor round-trips refs VERBATIM while the cook types, so the
        #    ordinal matched across an edit that changed the words underneath it: "proceed with
        #    step 3" reworded to "step 1" came back still pointing at step 3, and the page prints
        #    the REFERENCED step's current number, so the sentence read "step 3" however it was
        #    typed. Measured through the real save path. The carry below has always been keyed this
        #    way, which is exactly the check the payload was skipping.
        sent = {(r.get("ref_index"), r.get("match_text")): r.get("step_id")
                for r in (n.get("refs") or ()) if isinstance(r, dict)}
        carried = stored_refs.get(kept["id"] if kept is not None else None, {})
        # ⚠️ THE AUTO-LINK REACHES THIS DOOR TOO, AND IT DID NOT. create_note and update_note resolve
        #    "step 2" to the step the page numbers 2; write_notes did not, so the same words typed
        #    in Edit mode stayed plain and left no marker on that step while the same words typed in
        #    reading view linked. One rule, two doors, two answers. _note_ref_rows holds the order.
        want_refs.append(_note_ref_rows(
            text_, step_ids, sent=sent, carried=carried,
            auto=_auto_link_mentions(text_, step_ids, numbers)))

    _apply_rows(s, rn, plan, doomed_n)

    # ⚠️ THE REFERENCES ARE WRITTEN AFTER THE ROWS, because an inserted note has no id until then.
    #    Re-read rather than guess: _apply_rows assigns positions, so position is the key that ties
    #    each written row back to the plan that built it.
    written = _stored_rows(s, rn, rid)
    by_pos = {m["position"]: m["id"] for m in written}
    for i, refs in enumerate(want_refs):
        note_id = by_pos.get(i)
        if note_id is None:
            continue
        s.execute(delete(rnr).where(rnr.c.note_id == note_id))
        for r in refs:
            s.execute(insert(rnr).values(note_id=note_id, **r))

    # ⚠️ THE DERIVED COPY IS GONE. recipes.notes was kept written through the notes round so the
    #    previous deploy could still serve a recipe during the window. That window closed, and
    #    migration 063 drops the column. The rows are the only place a note lives.


def read_notes(s, rid, steps=None):
    """A recipe's note rows, with their step references, resolved the way the page reads them.

    ⚠️ ONE READER, THREE CALLERS. The GET route built this inline, and the per-note endpoints need
    exactly the same shape or the row the client gets back from a PATCH would differ from the row it
    gets on the next page load. Same arrangement notes_rules has for the split and the kind table.

    `steps` is the recipe's step rows when the caller already has them (the GET route does), so the
    number each reference resolves to is counted off the SAME list the page numbers. Left out, they
    are read here.
    """
    rows = [dict(n) for n in s.execute(
        select(RecipeNote.__table__).where(RecipeNote.__table__.c.recipe_id == rid)
        .order_by(RecipeNote.__table__.c.position, RecipeNote.__table__.c.id)).mappings()]
    for n in rows:
        n["refs"] = []
    if rows:
        by_note = {}
        for ref in s.execute(
                select(RecipeNoteStepRef.__table__)
                .where(RecipeNoteStepRef.__table__.c.note_id.in_([n["id"] for n in rows]))
                .order_by(RecipeNoteStepRef.__table__.c.note_id,
                          RecipeNoteStepRef.__table__.c.ref_index)).mappings():
            by_note.setdefault(ref["note_id"], []).append(dict(ref))
        for n in rows:
            n["refs"] = by_note.get(n["id"], [])
    if steps is None:
        steps = list(s.execute(
            select(RecipeStep.__table__.c.id, RecipeStep.__table__.c.is_heading)
            .where(RecipeStep.__table__.c.recipe_id == rid)
            .order_by(RecipeStep.__table__.c.position, RecipeStep.__table__.c.id)).mappings())
    notes_rules.resolve(rows, steps)
    return rows


def _check_row_ids(clean, stored_ing, stored_step):
    """Return an error string, or None. Every row id the payload sends must name a row of THIS
    recipe, and must name it once.

    ⚠️ A FOREIGN ID IS REFUSED RATHER THAN IGNORED. Ignoring it would write the line as a new row,
    which reads like success and quietly loses whatever the client thought it was editing. Worse,
    an id belonging to ANOTHER recipe would be a cross-recipe write if it were ever honoured, so
    the check is against this recipe's own rows and nothing wider.

    ⚠️ A REPEATED ID IS REFUSED for the same reason the carry consumes a row once: two lines
    claiming one row means the second update overwrites the first and one line disappears."""
    for rows, stored in ((clean["ingredients"], stored_ing), (clean["steps"], stored_step)):
        known = {o["id"] for o in stored}
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue                                  # a bare-string step carries no id
            n = row.get("id")
            if n is None:
                continue
            # bool is an int in Python, and True would silently mean row 1.
            if isinstance(n, bool) or not isinstance(n, int):
                return "a row id in this save isn't a whole number"
            if n not in known:
                return f"a row id in this save ({n}) isn't part of this recipe"
            if n in seen:
                return f"a row id in this save ({n}) is used twice"
            seen.add(n)
    return None


class BlankedRowViolation(RuntimeError):
    """A save would have left a surviving row with nothing in it. See blanked_row_problems."""


def _row_display_text(row, kind):
    """What the reader would SEE on this row, trimmed. Empty means the row renders as nothing."""
    if kind == "step":
        return (row["text"] or "").strip()
    if row["is_heading"]:
        return _heading_title(row).strip()
    return ((row["label"] or row["raw_text"]) or "").strip()


def blanked_row_problems(before, after, kind):
    """Rows that read as something before this save and as nothing after it, on the SAME row id.
    Returns a list of human-readable problems, empty when the save is safe — the same shape as
    snapshot_headsync.content_safety_problems, which guards the baseline rather than the rows.

    ⚠️ A ROW THE PAYLOAD DROPPED IS NOT A PROBLEM. Deleting a row is an ordinary edit, and clearing a
    step's text IS how the editor deletes one (nonEmptySteps prunes it, so a deleted step simply does
    not arrive). The dangerous shape is the opposite: a row that IS in the payload, keeps its id, and
    comes out empty. The real editor cannot produce it, because nonEmptyRows and nonEmptySteps prune
    a blank row before the payload is built. So this firing means the server read the payload
    differently from how the client wrote it.

    ⚠️ IT HAS ALREADY NEARLY HAPPENED ONCE, which is why it is worth two SELECTs per save. Option C
    gave a non-heading step an object wire form so it could carry an id. write_recipe_rows read a step
    as `step if isinstance(step, str) else ""`, so every object step would have been written BLANK —
    the whole method of every recipe, on its first save, with a 200 and no sign anything was wrong.
    That was caught by reading the code. A guard that compares what was there against what is about
    to be there does not depend on anyone noticing."""
    by_id = {r["id"]: r for r in after}
    problems = []
    for old in before:
        new = by_id.get(old["id"])
        if new is None:
            continue                                    # removed by id: a deliberate delete
        was = _row_display_text(old, kind)
        if was and not _row_display_text(new, kind):
            problems.append(
                f"{kind} id={old['id']} (position {new['position']}) read {was!r} and this save "
                f"would leave it empty")
    return problems


def assert_no_blanked_rows(s, rid, before_ing, before_step):
    """Raise BlankedRowViolation unless every surviving row still reads as something.

    Called AFTER write_recipe_rows and BEFORE the caller's commit, so raising aborts the whole save
    and leaves no partial state — the same seam, and the same reasoning, as
    sync_original_heading_layout's assert_content_safe. A failed save costs one retry. A recipe whose
    method has been silently emptied costs the recipe."""
    after_ing = s.execute(
        select(RecipeIngredient.__table__).where(RecipeIngredient.recipe_id == rid)
        .order_by(RecipeIngredient.position, RecipeIngredient.id)).mappings().all()
    after_step = s.execute(
        select(RecipeStep.__table__).where(RecipeStep.recipe_id == rid)
        .order_by(RecipeStep.position, RecipeStep.id)).mappings().all()
    problems = (blanked_row_problems(before_ing, after_ing, "ingredient")
                + blanked_row_problems(before_step, after_step, "step"))
    if problems:
        raise BlankedRowViolation(
            "this save would empty a row that is still in the recipe:\n  - "
            + "\n  - ".join(problems))


def _kept_second(row, stored):
    """The second amount after this save: what the payload says, or what is stored when it is silent."""
    if "secondary_measure" not in row:
        return stored
    sent = row.get("secondary_measure")
    return (sent or "").strip() or None


def _ing_row_values(pos, row, parts, held, exact):
    """Every column an ingredient row is written with — the SAME dict for an INSERT and an UPDATE.

    ⚠️ ONE BUILDER FOR BOTH, AND THAT IS THE POINT. An UPDATE that leaves a column out keeps the
    OLD value where an INSERT would have left NULL, so a line toggled to a heading would silently
    keep its amount, its harvested weight and its four linkage columns. The insert path never had
    to think about it, having written every row from nothing. The heading branch below therefore
    spells out the NULLs an insert used to get for free, and the line branch spells out is_heading.

    `held` is the stored row whose columns carry, or None for a line that is new content. `exact`
    says the amount did not move, which is what decides whether the weight carries with it."""
    if parts is None:
        # ⚠️ A HEADING KEEPS EVERY HIDDEN COLUMN, AND IT USED TO KEEP NONE OF THEM. Converting a
        # line to a heading wrote the title over raw_text and NULLed the amount, the weight, the
        # note and the four linkage columns. The editor holds them in memory, so the toggle looked
        # lossless until you SAVED while it was a heading, and then converting back gave you a bare
        # name. The reading view renders a heading as its title alone (plainRow) and the diff
        # compares headings on the title alone (snapshot_diff ing_h), so there is nothing for the
        # kept values to leak into. See migration 052 for why the title needed its own column.
        title = row["heading"]
        if held is None:
            # Born a heading: nothing is dormant, and raw_text carries the title the way every
            # pre-052 heading row does.
            keep = {"raw_text": title, "label": None, "note": None,
                    "qty": None, "quantity": None, "unit": None, "ingredient_id": None,
                    "grams": None, "secondary_measure": None, "catalog_id": None,
                    "link_confidence": None, "link_rule": None, "link_matched": None}
        else:
            # Converted from a line, or an existing heading saved again. Everything here is the row
            # as it stood, untouched. raw_text in particular: 87% of live lines carry a source line
            # richer than their name, and overwriting it is what made the round trip lossy.
            keep = {k: held[k] for k in
                    ("raw_text", "label", "note", "qty", "quantity", "unit", "ingredient_id",
                     "grams", "secondary_measure", "catalog_id", "link_confidence",
                     "link_rule", "link_matched")}
        # ⚠️ THE TITLE COLUMN IS ONLY USED WHEN raw_text IS NOT ALREADY THE TITLE, which is the same
        # rule the readers apply from the other side (`heading` when set, else raw_text). It keeps
        # all 223 pre-052 heading rows on live exactly as they are: their title IS their raw_text,
        # so saving their recipe writes NULL where NULL already was, rather than stamping a
        # redundant copy onto every one of them the first time its recipe is touched.
        return {"position": pos, "is_heading": 1,
                "heading": None if title == keep["raw_text"] else title, **keep}

    (qty, quantity, unit), linked, text = parts
    note_in = row.get("note") or ""
    if held is not None:
        raw_text = held["raw_text"]
        label = held["label"] if not linked else (held["label"] or text)
        # A note-only edit must not look like a no-op, and an unchanged note must not drift
        # between NULL and ''. Equivalent -> keep the stored spelling. Different -> take the edit.
        note = held["note"] if (held["note"] or "") == note_in else (note_in or None)
        if exact:                                   # nothing about the amount moved
            qty, quantity, unit = held["qty"], held["quantity"], held["unit"]
        links = (held["catalog_id"], held["link_confidence"],
                 held["link_rule"], held["link_matched"])
        grams = held["grams"] if exact else None
        # ⚠️ A CHANGE TO THE FIRST AMOUNT USED TO DROP THE SECOND ONE IN SILENCE. The second amount
        #    is the AUTHOR'S figure for this line, so correcting a typo in the first one is no
        #    reason to delete it. grams keeps its old rule: it is a weight the import harvested
        #    FOR the amount that was there, so it does not travel with a new one.
        #
        #    ⚠️ AND A SENT EMPTY STRING IS AN ANSWER WHERE AN ABSENT KEY IS NOT. The cook clearing
        #    the field sends "", which stores NULL. A client too old to know about the field sends
        #    no key, and reading that silence as a deletion is what one save from an old bundle
        #    would have done to every row. Same rule a note's kind and step link follow.
        secondary = _kept_second(row, held["secondary_measure"])
    else:
        raw_text = text                             # a new line: the typed text IS the source line
        label = text
        note = note_in or None
        links = (None, None, None, None)
        grams = None
        secondary = _kept_second(row, None)

    return {
        "position": pos, "is_heading": 0, "qty": qty, "quantity": quantity, "unit": unit,
        "ingredient_id": linked or None, "label": label, "note": note, "raw_text": raw_text,
        "grams": grams, "secondary_measure": secondary,
        "catalog_id": links[0], "link_confidence": links[1],
        "link_rule": links[2], "link_matched": links[3],
        "heading": None,          # a line has no title, and NULLing it is what makes the round trip exact
    }


def _display_name(o):
    """A stored line's display name — its label, or raw_text when there is no label. The same
    reading _Carry keys on, so the id path and the fallback path agree on what 'the same line' is."""
    return o["label"] or o["raw_text"]


def write_recipe_rows(s, rid, clean, stored=None):
    """Write a recipe's ingredient lines and steps from a validated payload, IN PLACE.

    ⚠️ IT NO LONGER DELETES THE RECIPE AND WRITES IT AGAIN. It used to, which is why no row id
    survived a save: every id in both tables churned on every save, so nothing outside these two
    tables could ever point at a row. A row is now matched by its id and UPDATED, a row that is
    not in the payload is DELETED, and a row with no id is INSERTED. Same session, same single
    transaction as before, and the caller still commits.

    `stored` (edit path only) is (ingredient rows, step rows) as they stand, ordered by position
    then id. On create there is nothing stored, so every row is new and nothing is deleted.

    ⚠️ THE ID PASS RUNS FIRST AND THE CARRY GETS ONLY WHAT IT LEAVES. A line arriving without an
    id still falls back to the two-tier _Carry, exactly as before, but that carry is built over the
    stored rows the id pass did NOT consume. Built over all of them instead, an id-less line could
    match a row an id-carrying line has already claimed, and both would write to the one row: one
    save, two lines, one of them silently gone.

    ⚠️ AN ID IDENTIFIES THE ROW, NOT THE LINE. A row whose id matches is the same ROW however much
    its text has changed, so it is updated in place and keeps its id. What it CARRIES is a separate
    question with the same answer as before: the name changed, so it is new content, so raw_text
    becomes the typed text and the four linkage columns go to NULL. The id survives a rename. The
    link does not, which is the rule as it stands (ROADMAP holds the re-match-on-save follow-up).

    ⚠️ raw_text MEANS "THE LINE AS IT CAME IN" AND IS NEVER REBUILT. It used to be recomputed as
    f"{qty} {label}{note}" on the linked branch and set to the displayed text on the other, which
    is how "25 g (0.9 oz) guajillo chillies" became "(0.9 oz) guajillo chillies" on a save that
    changed nothing. The source line is the one thing a re-parse can still be run against, so it
    survives every edit that does not replace it.

    ⚠️ AN EDITED LINE IS A NEW LINE, AND DROPPING ITS LINK IS DELIBERATE. label and raw_text both
    become the typed text and the four linkage columns go to NULL. An unlinked line renders exactly
    as it reads; a wrongly linked one shows another ingredient's prose, safety flags and allergen
    warnings under the wrong name. The old line is still in the reason='original' snapshot, and
    build_links.py rebuilds a dropped link from committed files.

    Stage 1c: runs on the caller's ORM session `s` (Core statements on the same tables); the
    caller commits."""
    stored_ing, stored_step = stored if stored is not None else ([], [])
    ri, rs = RecipeIngredient.__table__, RecipeStep.__table__

    # Resolve every line's (qty, name) BEFORE writing any of them, so the carry can run its EXACT
    # tier over the whole recipe before a NAME-only match consumes a row. See _Carry.plan.
    prepared = []
    for row in clean["ingredients"]:
        row = row or {}
        if row.get("heading"):
            prepared.append((row, None))
            continue
        linked = row.get("item")
        text = (row.get("label") or row["item"]) if linked else (row.get("text", "") or "")
        # Hybrid: recombine qty from explicit parts (Stage-4 editor) or derive the split from the
        # authored qty (Stage 3).
        prepared.append((row, (_row_qty_parts(row), linked, text)))

    # PASS 1 — the id. update_recipe has already refused an id this recipe does not own and an id
    # the payload repeats, so a hit here is a row this payload may claim, once.
    by_id = {o["id"]: o for o in stored_ing}
    target = [by_id.get(row.get("id")) for row, _ in prepared]
    claimed = {o["id"] for o in target if o is not None}

    # PASS 2 — the carry, over ONLY the rows pass 1 left behind. See the warning above.
    carry = _Carry([o for o in stored_ing if o["id"] not in claimed]) if stored_ing else None
    held_for = (carry.plan([None if (target[i] is not None or p[1] is None) else (p[1][0][0], p[1][2])
                            for i, p in enumerate(prepared)])
                if carry else [None] * len(prepared))

    written = set()
    for pos, (row, parts) in enumerate(prepared):
        into = target[pos]
        if into is not None:
            if parts is None:
                held, exact = into, False           # a heading carries only its note
            else:
                name = parts[2]
                stored_name = _display_name(into)
                held = into if _name_key(name) == _name_key(stored_name) else None
                exact = (held is not None and _preserve_key(parts[0][0], name)
                         == _preserve_key(into["qty"], stored_name))
        elif parts is None:
            held = carry.take_heading(row["heading"]) if carry else None
            exact, into = False, held
        else:
            held, exact = held_for[pos] or (None, False)
            into = held                             # a fallback match updates that row in place too

        values = _ing_row_values(pos, row, parts, held, exact)
        if into is not None:
            # ⚠️ A RAISE, NOT AN assert, so it holds under python -O too. Two lines resolving to one
            # row is the silent-loss shape this whole function is arranged to make impossible, and a
            # 500 with nothing committed is the right answer to it. Reachable only through a bug in
            # the resolution above: the id check refuses a repeated id and _Carry consumes once.
            if into["id"] in written:
                raise RuntimeError(f"two payload lines resolved to stored row {into['id']}")
            s.execute(update(ri).where(ri.c.id == into["id"]).values(**values))
            written.add(into["id"])
        else:
            s.execute(insert(ri).values(recipe_id=rid, **values))

    gone = [o["id"] for o in stored_ing if o["id"] not in written]
    if gone:
        s.execute(delete(ri).where(ri.c.id.in_(gone)))

    # ⚠️ A STEP CARRIES NO COLUMNS, AND IT STILL HAS SOMETHING TO PRESERVE: ITS ID. This read
    # "steps carry nothing, so there is no carry tier and nothing to preserve across a rewrite",
    # which was true when a step row's id meant nothing to anything outside this table. The
    # reason='original' baseline now records every step row's id, so deleting an unchanged step and
    # inserting it again costs the recipe its byte-equal short-circuit for good — every page view
    # runs the diff, and after the id-matched diff lands, every step of that recipe reads as removed
    # and re-added. The app's own client sends an id on every existing step, so this fallback is for
    # a caller that does not (the string wire form, which is still legal).
    #
    # ONE TIER, EXACT, CONSUME-ONCE, IN ORDER. An id-less step whose kind and text match a stored row
    # the id pass did not claim updates THAT row. No similarity tier, unlike _Carry's second pass: a
    # step with changed text and no id is a new row exactly as it was before, so the only behaviour
    # this changes is the one case where preserving the id is unambiguously right.
    step_by_id = {o["id"]: o for o in stored_step}
    prepared_steps = [(_step_parts(step),
                       step_by_id.get(step.get("id") if isinstance(step, dict) else None))
                      for step in clean["steps"]]
    step_claimed = {o["id"] for _, o in prepared_steps if o is not None}
    step_carry = {}
    for o in stored_step:
        if o["id"] not in step_claimed:
            step_carry.setdefault((bool(o["is_heading"]), o["text"] or ""), []).append(o)

    kept = set()
    # ⚠️ THE CARRY KEY IS STILL (kind, text) AND heading_level IS NOT IN IT, on purpose. The key
    #    answers "is this the same row I already had", and a level is a property of the row rather
    #    than its identity: a heading whose level the user just changed is the same heading, and
    #    adding the level would make it read as a delete plus an insert and lose the row id.
    for pos, ((text_val, is_heading, level), into) in enumerate(prepared_steps):
        if into is None:
            pool = step_carry.get((bool(is_heading), text_val or ""))
            if pool:
                into = pool.pop(0)                      # consume-once, first stored row wins
        if into is not None:
            if into["id"] in kept:                      # see the ingredient guard above
                raise RuntimeError(f"two payload steps resolved to stored row {into['id']}")
            s.execute(update(rs).where(rs.c.id == into["id"]).values(
                position=pos, is_heading=1 if is_heading else 0, text=text_val,
                heading_level=level))
            kept.add(into["id"])
        else:
            s.execute(insert(rs).values(recipe_id=rid, position=pos,
                                        is_heading=1 if is_heading else 0, text=text_val,
                                        heading_level=level))

    gone = [o["id"] for o in stored_step if o["id"] not in kept]
    if gone:
        s.execute(delete(rs).where(rs.c.id.in_(gone)))


# ---- change-tracking (stage 1): recipe_snapshots — capture-on-cook ------------------------------
# The Cooking Journal's foundation (HYBRID): a snapshot is a JSON blob of a recipe's editable CONTENT,
# captured when a cook is logged. Snapshots are the STORED TRUTH; diffs are DERIVED from consecutive
# snapshots later (stage 3). Stage 1 only WRITES them (reason='cook') — nothing reads them yet.

def serialize_recipe_content(s, rid):
    """Serialize a recipe's editable CONTENT to a STABLE JSON blob (change-tracking) — the 11 content
    fields + all ingredient rows + all step rows, rows ordered by position (then id). Fetches the live rows
    (ORM) and delegates the FORMAT to snapshot_serialize.content_blob — the SINGLE SOURCE shared with the
    raw-SQL import writer (import_write.commit_plan), so an import-origin ORIGINAL and an app-origin CURRENT
    serialize byte-identically (the stage-3 diff depends on it). Steps resolve .body -> the 'text' key (the
    ORM maps the DB "text" column to .body). Pure w.r.t. the given session (a read + a deterministic dump)."""
    r = s.execute(select(Recipe).where(Recipe.id == rid)).scalar_one()
    ingredients = list(s.execute(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == rid)
        .order_by(RecipeIngredient.position, RecipeIngredient.id)
    ).scalars())
    steps = [
        # ⚠️ `id` IS NAMED HERE BECAUSE THIS PATH HAND-BUILDS ITS STEP DICTS. The ORM maps the DB
        # "text" column to .body (models.py renames it to avoid shadowing sqlalchemy.text), so a step
        # row cannot be handed to the serializer as-is the way an ingredient row is — every key the
        # snapshot format wants has to be spelled out on this line, and a new one is silently null
        # otherwise. Ingredients need no such line: they go in as ORM rows and _get reads the attribute.
        # heading_level is one of those keys, and it is read from the row rather than defaulted:
        # snapshot_step_row omits it at level 1, so a missing value here would read as level 1 on a
        # subheading and the baseline would silently disagree with the live row.
        {"id": row.id, "position": row.position, "is_heading": row.is_heading, "text": row.body,
         "heading_level": row.heading_level}
        for row in s.execute(
            select(RecipeStep).where(RecipeStep.recipe_id == rid)
            .order_by(RecipeStep.position, RecipeStep.id)
        ).scalars()
    ]
    waits = s.execute(select(RecipeWait.__table__).where(RecipeWait.recipe_id == rid)
                      .order_by(RecipeWait.position, RecipeWait.id)).mappings().all()
    storage = s.execute(select(RecipeStorage.__table__).where(RecipeStorage.recipe_id == rid)
                        .order_by(RecipeStorage.position, RecipeStorage.id)).mappings().all()
    # ⚠️ THE NOTES ARE NOT READ HERE, AND NOR IS THE DERIVED COLUMN PROJECTED. A note is a
    #    playground: it mints no "your changes" entry and editing one must not cost the recipe its
    #    place in the byte-equal set, so it cannot be in these bytes. The author's original words
    #    are kept in recipe_notes_original, which nothing compares. See content_blob.
    return snapshot_serialize.content_blob(r, ingredients, steps, waits, storage)


def snapshot_recipe(s, rid, cook_log_id, reason):
    """Capture the recipe's current content as a versioned snapshot (change-tracking stage 1). Writes one
    recipe_snapshots row on the caller's session (before their commit): the JSON-blob content, the trigger
    reason ('original' | 'cook'), the cook it belongs to (cook_log_id; NULL on an 'original' baseline), the
    actor (current_user), and a real UTC timestamp. Two reasons exist and no others. snapshot_original writes
    'original'. log_cook, redo_cook and log_cook_and_rate each write 'cook'. A third reason, 'manual', was
    designed and then DROPPED (docs/design-decisions.md, change-tracking). Snapshots ARE READ.
    _recipe_annotations diffs the 'original' baseline against current to build the recipe page's
    annotations."""
    s.execute(insert(RecipeSnapshot.__table__).values(
        recipe_id=rid, cook_log_id=cook_log_id, user_id=current_user.id,
        reason=reason, content=serialize_recipe_content(s, rid), created_at=now_utc(),
    ))


def snapshot_original(s, rid):
    """Capture a recipe's PRISTINE content as a reason='original' snapshot — the birth baseline the
    recipe-page annotations (O-c) will diff the CURRENT version against (original-baseline capture O-a).
    Reuses snapshot_recipe's stage-1 machinery; cook_log_id NULL (no cook). Guarded WHERE NOT EXISTS so a
    recipe's original is captured ONCE — belt-and-suspenders here (create/import are create-only) and the
    guard the O-b backfill relies on. Wired into app-create; the raw-SQL import path mirrors this guard +
    insert with the SAME shared serializer (import_write.commit_plan)."""
    already = s.execute(
        select(RecipeSnapshot.id)
        .where(RecipeSnapshot.recipe_id == rid, RecipeSnapshot.reason == "original")
    ).first()
    if already:
        return
    snapshot_recipe(s, rid, None, "original")


def sync_original_heading_layout(s, rid):
    """Bring the reason='original' baseline's HEADING LAYOUT into step with the recipe's rows as they
    stand NOW. Runs on the caller's session, BEFORE their commit. Returns True if the blob was
    rewritten, False if there was nothing to do.

    WHY. A removed row's `section` is the text of the heading that preceded it IN THE BASELINE
    (snapshot_diff._section_lookup), so once a heading moves, a struck row renders under a section
    that no longer describes where it sits on screen. Heading changes emit no annotations by existing
    ruling, so the baseline's heading layout carries no information worth keeping — syncing it costs
    nothing and makes placement match what the reader sees.

    TWO GUARDS, in this order:
      - NO original row -> do nothing and continue. Mirrors _recipe_annotations' fail-safe: a
        pre-O-b recipe that never got a baseline is not an error. NEVER create one here — birth
        capture is snapshot_original's job, and minting a baseline from the CURRENT content would
        declare the recipe born in its edited state and erase every annotation it should have had.
      - BYTE-IDENTICAL result -> skip the write. This is the common case (every save that doesn't
        touch a heading), so the UPDATE is rare rather than per-save.

    ⚠️ assert_content_safe RAISES and MUST be allowed to. The whole edit runs inside one
    `with orm_session() as s:` block with a single commit, so an exception here aborts the entire
    save and leaves NO partial state — the rows, the recipe fields and the baseline all roll back
    together. That property is the reason this seam was chosen over a post-commit hook or a separate
    session. Do not catch it and save anyway: a baseline that has silently absorbed the user's edits
    is unrecoverable (recipe_snapshots has no versioning, and snapshot_original's WHERE NOT EXISTS
    guard means it is never re-captured), whereas a failed save costs one retry."""
    stored = s.execute(
        select(RecipeSnapshot.content)
        .where(RecipeSnapshot.recipe_id == rid, RecipeSnapshot.reason == "original")
    ).scalar_one_or_none()
    if stored is None:
        return False
    # Read the rows through Core (mappings, not ORM entities) so this sees exactly what
    # write_recipe_rows just wrote on this transaction, with no identity-map staleness in play.
    ri, rs = RecipeIngredient.__table__, RecipeStep.__table__
    ingredients = [dict(m) for m in s.execute(
        select(ri).where(ri.c.recipe_id == rid).order_by(ri.c.position, ri.c.id)).mappings()]
    # ⚠️ THE WHOLE ROW, NOT A HAND-PICKED COLUMN LIST. This named position/is_heading/text and so
    # omitted the row id the snapshot format now carries, which put "id":null on every heading the
    # sync interleaved. Selecting the table lets snapshot_step_row decide what the snapshot needs,
    # the same way the ingredient select above already does.
    steps = [dict(m) for m in s.execute(
        select(rs).where(rs.c.recipe_id == rid).order_by(rs.c.position, rs.c.id)).mappings()]

    synced = snapshot_headsync.sync_heading_layout(stored, ingredients, steps)
    snapshot_headsync.assert_content_safe(stored, synced)   # raises -> the whole save aborts
    if synced == stored:
        return False
    s.execute(update(RecipeSnapshot.__table__)
              .where(RecipeSnapshot.__table__.c.recipe_id == rid,
                     RecipeSnapshot.__table__.c.reason == "original")
              .values(content=synced))
    return True


def _baseline_cook_time(s, rid):
    """The cook time the recipe was BORN with, or None when it has no baseline.

    ⚠️ THIS IS HOW A HAND EDIT TO THE COOK TIME IS DETECTED, and it is the same evidence the "your
       changes" layer reads. A cook who clears the cook time has said the dish has none, and an
       estimate that reappears over that deletion has overruled them. Measured over the 300:
       exactly one recipe differs from its baseline here, the smoothie, whose baseline said
       "0 mins" and whose cook cleared it.
    """
    original = s.execute(
        select(RecipeSnapshot.content)
        .where(RecipeSnapshot.recipe_id == rid, RecipeSnapshot.reason == "original")
    ).scalar_one_or_none()
    if original is None:
        return None
    try:
        return (json.loads(original).get("recipe") or {}).get("cook_time")
    except (ValueError, AttributeError):
        return None


def _recipe_annotations(s, rid):
    """The recipe-page annotation set (O-c-1): diff the recipe's CURRENT content against its
    reason='original' baseline and return the RAW diff_snapshots entries (the client renders them —
    abbreviation/anchoring are its concern). Single-recipe op: one original fetch + one serialize + one
    diff. Two guards make the common case free and safe:
      - no original row (a pre-O-b recipe that never got a baseline) -> [] (fail safe, never error);
      - byte-equal short-circuit: content_blob is byte-stable, so string-equal == content-equal — every
        UNEDITED recipe (the norm post-O-b, until its first edit) skips the diff entirely."""
    original = s.execute(
        select(RecipeSnapshot.content)
        .where(RecipeSnapshot.recipe_id == rid, RecipeSnapshot.reason == "original")
    ).scalar_one_or_none()
    if original is None:
        return []
    current = serialize_recipe_content(s, rid)
    if current == original:
        return []
    return snapshot_diff.diff_snapshots(original, current)   # old/original FIRST, new/current SECOND


@app.route("/")
def home():
    # Serve the Vite-built shell verbatim. It references content-hashed assets (/assets/*.[hash].*),
    # so it stays no-cache (always revalidated → always names the current build), while those hashed
    # assets cache for a year. Requires `npm run build` to have produced dist/index.html.
    html = (BASE_DIR / "dist" / "index.html").read_text(encoding="utf-8")
    # The commit that served this page, for the reload bar. The page compares it with the commit on
    # each API answer, so a tab learns the server has moved on without anything baked into the bundle.
    if APP_COMMIT:
        html = html.replace("</head>", f'<meta name="app-commit" content="{APP_COMMIT}">\n</head>', 1)
    resp = app.make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/images/<path:filename>")
def recipe_image(filename):
    # Recipe hero photos live in static/images/ (not the Vite bundle) and are referenced as
    # absolute /images/<file> in the client; serve them from their on-disk home.
    #
    # ⚠️ images.IMAGES_DIR, NOT BASE_DIR / "static" / "images". They are the same folder in an
    # ordinary checkout, and they are NOT the same folder when the photo directory is redirected —
    # which images.py documents IMAGES_DIR as being for ("a REDIRECTABLE module global"). This read
    # path computing its own answer meant a redirect moved where photos were WRITTEN and left where
    # they were SERVED behind. scripts/serve_live.py is the case that needs them to agree: a pinned
    # checkout serving its own dist while reading and writing the real photo folder.
    return send_from_directory(images.IMAGES_DIR, filename)


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
    # Migration 048: rating is now AVG over this user's RATED cooks, not a lookup in the frozen ratings
    # table. AVG over no rows is NULL on both dialects, which is the same "unrated" the client already
    # renders, so the empty case needs no special handling.
    # Rescoping R5: each subquery is scoped to the current user via the :uid BINDPARAM (never string-
    # interpolated) — so the list shows MY rating and MY cook stats. The recipe rows themselves are NOT
    # owner-filtered (FROM recipes r, unchanged) — EVERY recipe still appears; only the personal-layer
    # aggregates are per-user (an untouched recipe shows rating=NULL, cook_count=0, last_cooked=NULL).
    with orm_session() as s:
        rows = s.execute(text(
            """SELECT r.id, r.name, r.author, r.category, r.servings,
                      r.prep_time, r.cook_time, r.total_time, r.image, r.created_at, r.source, r.owner,
                      (SELECT AVG(rating) FROM cook_log
                        WHERE recipe_id = r.id AND user_id = :uid AND rating IS NOT NULL)            AS rating,
                      (SELECT COUNT(rating) FROM cook_log
                        WHERE recipe_id = r.id AND user_id = :uid AND rating IS NOT NULL)            AS rated_cooks,
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
        # ⚠️ AVG OVER numeric RETURNS Decimal ON POSTGRES, and jsonify cannot serialize one, so this
        # is a 500 rather than a wrong number. SQLite hands back a float and the cast is a no-op
        # there, which is exactly why the dual-dialect suite is what catches it.
        d["rating"] = float(d["rating"]) if d["rating"] is not None else None
        out.append(d)
    return jsonify(out)


@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    """Create a new app-owned recipe. Rejects a name whose slug already exists."""
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        clean, err = resolve_recipe_payload(s, payload)
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
            image=payload.get("image"), created_at=now_utc(), source=source,
            owner=current_user.id,   # R4: a created recipe lands in the creator's box
        ))
        write_recipe_rows(s, slug, clean)
        write_notes(s, slug, payload)   # after the rows, so a note's step_id names a step that exists
        # ⚠️ AFTER THE NOTES AND BEFORE THE BASELINE. The notes are not IN the baseline, so
        #    this is the only record of what this recipe was created saying.
        record_notes_original(s, slug)
        snapshot_original(s, slug)   # O-a: capture the pristine reason='original' baseline at birth (for O-c annotations)
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


def attach_note_spans(ings):
    """Attach `note_spans` to each ingredient line whose note opens "or <amount>" (round B
    revision 2). The note's raw text is kept for Edit mode and for "your changes"; the spans are
    the render form, tagged by the method text's own grammar so the amounts scale on display only.
    A note that is not a substitution carries no spans and renders exactly as stored."""
    out = []
    for x in ings:
        d = dict(x)
        if not d.get("is_heading"):
            spans = note_spans(d.get("note") or "")
            if spans:
                d["note_spans"] = spans
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
            .order_by(RecipeIngredient.position, RecipeIngredient.id)
        ).mappings().all()
        steps = s.execute(
            select(RecipeStep.__table__).where(RecipeStep.recipe_id == rid)
            .order_by(RecipeStep.position, RecipeStep.id)
        ).mappings().all()
        stats = recipe_stats(s, rid, current_user.id)
        ingredients = attach_note_spans(attach_weights(s, ings))
        # Plan-ahead waits and storage (round 2). Several rows per recipe by design, ordered by
        # position, and the TOTAL is summed in Python rather than in SQL: Postgres returns Decimal
        # from AVG over an integer column and nothing here should ever have to care.
        waits = [dict(w) for w in s.execute(
            select(RecipeWait.__table__).where(RecipeWait.recipe_id == rid)
            .order_by(RecipeWait.position, RecipeWait.id)).mappings().all()]
        storage = [dict(x) for x in s.execute(
            select(RecipeStorage.__table__).where(RecipeStorage.recipe_id == rid)
            .order_by(RecipeStorage.position, RecipeStorage.id)).mappings().all()]
        # ⚠️ THE LINK IS DECIDED HERE, against the steps as they stand now, and all it does is count
        #    the step NUMBER the page prints. Migration 053 made the link a step id, so there is
        #    nothing left to verify — a pointer either names a step of this recipe or is null.
        planahead.resolve_steps(waits, steps)
        # ⚠️ NOTES ARE ROWS SINCE MIGRATION 060, and the derived recipes.notes column that was kept
        #    for one deploy window is gone (migration 063). These rows are the notes.
        # ⚠️ THROUGH read_notes, WHICH THE PER-NOTE ENDPOINTS ALSO CALL. This was assembled inline
        #    here, and a PATCH that returned a differently-shaped row from the one the next page load
        #    produces is the drift the single-reader rule exists to stop. The number each reference
        #    resolves to is counted off the step list the page numbers, so it is passed in.
        note_rows = read_notes(s, rid, steps)
        note_kind_rows = [dict(k) for k in s.execute(
            select(NoteKind.__table__).order_by(NoteKind.position)).mappings()]
        # ⚠️ WHAT THE PAGE PRINTS FOR EACH WAIT IS DECIDED HERE, NOT IN JS. A stored "overnight" has
        #    480 minutes behind it already, and printing the author's word alone told a cook nothing
        #    they could plan around. display_label turns the 14 rows whose floor IS the word into
        #    "8 hr+ (overnight)" and leaves the 11 where it is a ceiling or an invitation untouched.
        #    Server-side for the reason planahead's header gives: one implementation, no mirror.
        # ⚠️ AND WHETHER IT REACHES THE FIGURE IS DECIDED HERE TOO, for the same reason. The client
        #    had its own `waits.filter(w => w.when_kind === "always")`, which is planahead.counts
        #    spelled a second time, and the two had drifted on the alongside row. in_total is the
        #    server's answer and the client filters on it, so there is one rule and one reader of it.
        for w in waits:
            w["label_text"] = planahead.display_label(w)
            w["in_total"] = planahead.counts(w)
        wait_min, wait_max = planahead.total(waits)
        # is_queued (stage 3a): MY want-to-make state — per-user EXISTS against recipe_queue, scoped to
        # current_user.id like stats above. Any recipe is queueable, so this is independent of ownership.
        is_queued = s.scalar(
            select(RecipeQueue.id)
            .where(RecipeQueue.recipe_id == rid, RecipeQueue.user_id == current_user.id)
        ) is not None
        # Recipe-page annotations (O-c-1): the derived current-vs-original change set, rides along in the
        # payload like stats/ingredients so the "your changes" layer paints with the page (no 2nd request).
        # RAW diff entries — the client abbreviates + position-anchors them. [] until the recipe is edited.
        annotations = _recipe_annotations(s, rid)
        # Cook-photo album (Stage 4 build 3a — display; 3d-i — STORED order). Rides along in the recipe
        # payload (like stats/ingredients/steps) so the album paints with the page, no second request. Per
        # photo: path, caption, the cook's DATE (cook_log.cooked_on, LEFT JOIN — NULL for a standalone photo),
        # and is_hero (recipes.image == path — the POINT/linked hero). Least-exposure: no user_id/added_at.
        # ORDER (3d-i, Model B): by the STORED cook_photos.position — seeded from the old cooked_on order
        # (scripts/backfill_cook_photo_position.py), authoritative once dragged, new photos APPEND (max+1).
        # position governs ORDER only; cooked_on is still returned + governs the displayed DATE (independent —
        # reordering never changes dates). `position IS NULL` asc pushes any not-yet-seeded/appended row last
        # portably (the same NULLs-last trick the cooked_on ordering used — SQLite sorts NULLs first, PG last).
        photo_rows = s.execute(
            select(CookPhoto.id, CookPhoto.path, CookPhoto.caption, CookPhoto.cook_log_id, CookLog.cooked_on)
            .join(CookLog, CookLog.id == CookPhoto.cook_log_id, isouter=True)
            .where(CookPhoto.recipe_id == rid)
            .order_by(
                CookPhoto.position.is_(None),     # not-yet-seeded (True=1) sorts after seeded (False=0) — NULLs last
                CookPhoto.position.asc(),         # the stored album order (seeded from cooked_on, then authoritative)
                CookPhoto.id.asc(),               # stable tiebreak
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
        # ⚠️ COMPUTED INSIDE THE SESSION BLOCK, AND IT WAS NOT. The `return jsonify(...)` below
        #    sits OUTSIDE the `with orm_session()`, so a query evaluated in that dict runs on a
        #    CLOSED session: SQLAlchemy opens a new transaction, checks out a connection, and
        #    nothing is left to return it. Measured by hammering one recipe: the commit :8000 runs
        #    served 60 requests cleanly and this one 500'd from the 26th, which is a pool of 5 plus
        #    an overflow of 10 leaking exactly one connection per page view. A real server dies
        #    after fifteen page loads.
        cook_estimate = planahead.cook_estimate(
            r, steps, waits, storage, _baseline_cook_time(s, rid))["label"]
    return jsonify(
        {
            "recipe": dict(r),
            "ingredients": ingredients,
            "steps": serialize_steps(steps),
            "stats": stats,
            "photos": photos,                           # stage 4 (3a): the album — newest cook first, undated last
            # TIER vs OWNERSHIP — two questions, two flags. is_editable answers "does this recipe's
            # SOURCE TIER permit editing at all" (seed is read-only whoever owns it); is_mine answers
            # "is the current user the owner". Editing and deleting need BOTH (see update_recipe), and
            # the client must not conflate them: it previously used is_editable alone as an owner gate,
            # which offered a hero uploader / album add-zone the owner-gated routes then refused with a
            # 403. Named is_mine to match the list payload's existing field (list_recipes).
            "is_editable": r["source"] in EDITABLE_SOURCES,   # TIER only — not ownership
            "is_mine": r["owner"] == current_user.id,         # OWNERSHIP only — not tier
            "is_seed": r["source"] == "seed",           # seed tier stays read-only (edit in seed.py)
            "is_test": r["source"] == "test",           # scratch tier — gets the visible test marker
            "is_queued": is_queued,                     # stage 3a: my want-to-make queue membership
            "annotations": annotations,                 # O-c-1: raw current-vs-original diff entries ([] if unedited)
            # ⚠️ THE TOTAL IS THE NORMAL MINIMUMS ONLY. An extension ("or overnight if time allows")
            # never enters it, and a max exists only when EVERY wait has one. See planahead.total.
            "waits": waits,
            "storage": storage,
            # The note ROWS, and the kind table that groups them. The client stopped splitting
            # recipes.notes into paragraphs the day migration 060 landed.
            "notes": note_rows,
            "note_kinds": note_kind_rows,
            "wait_total": {"min_minutes": wait_min, "max_minutes": wait_max,
                           "label": planahead.total_label(waits)},
            # ⚠️ THE TOTAL IS DECIDED HERE AND COMPUTED AT DISPLAY, NEVER STORED. A stored total goes
            #    stale the first time a step or a wait is edited and nothing tells the cook it has.
            #    A stated total is the author's answer and is shown unchanged; otherwise it is
            #    prep + cook + the counted waits, and missing either part means no total at all.
            #    Measured over the 300: 14 carry a publisher total, 90 can be computed, 196 cannot.
            "total": dict(zip(("label", "note"), planahead.recipe_total(r, waits))),
            # ⚠️ THE SECOND TOTAL, ONE LINE PER CONDITIONAL WAIT, AND THE MAIN TOTAL IS UNCHANGED.
            #    An optional soak is not time a cook has to set aside, so it stays out of the figure
            #    above. A cook who IS going to soak still has to know what it costs, and the page can
            #    do that arithmetic for them. Measured over the 300: 5 recipes carry a conditional
            #    wait and one carries two. Computed here for the same reason the Total is, so the
            #    client prints what it is handed.
            "conditional_totals": planahead.conditional_totals(r, waits),
            # ⚠️ THE AUTHOR'S OWN FIGURE, WHERE THE PAGE HAS OVERRULED IT, AND NULL ON 299 OF 300.
            #    A total cannot contain waits that alone take longer than it, so earl-grey-tea-cake's
            #    stated 1 hr against a 1 hr 30 min rest that always applies is the one arithmetic
            #    impossibility the page may settle on its own. The Total above then says
            #    "(incl. plan ahead)" like any computed one, and this line keeps the author's number
            #    on the page so a cook holding the source card finds it. planahead.author_total_note
            #    is the whole rule. See stated_total_verdict for the two cases it refuses to decide.
            "author_total": planahead.author_total_note(r, waits),
            # ⚠️ THE COOK ESTIMATE, READ OFF THE STEPS AND COMPUTED HERE RATHER THAN STORED. The
            #    same function writes the review file, so a figure Andy read in the CSV is the
            #    figure the page prints. It is "" wherever the page must say nothing: where the
            #    author gave a cook time, where the cook edited one by hand, where the steps
            #    overlap, and for the seven recipes in planahead.NO_COOK_ESTIMATE.
            #    ⚠️ AND IT NEVER REACHES THE TOTAL. recipe_total reads recipe["cook_time"], which
            #    this never writes, so the Total cannot pick it up by accident.
            #    Measured over the 300: 137 recipes print one, 103 state their own cook time.
            "cook_estimate": cook_estimate,
        }
    )


# The 10 header fields a PUT may change, beside `name` (required and validated, so never null and
# never absent). The tuple exists so the write cannot fall out of step with the keep rule.
# ⚠️ `notes` LEFT THIS TUPLE WHEN A NOTE BECAME A ROW (migration 060). The column is a DERIVED copy
#    that write_notes rebuilds from the rows, so writing it here as well would put a payload list
#    into a text column on the new client and fight write_notes on the old one. The keep rule still
#    governs the other nine.
EDITABLE_HEADER_FIELDS = ("author", "source_url", "category", "servings", "prep_time", "cook_time",
                          "total_time", "descr", "image")


def _kept(new, old):
    """The value to write for a header field, keeping what is stored when the payload means the same.

    ⚠️ A SAVE WITH NO EDITS MUST WRITE NOTHING, AND THIS IS WHERE THAT WAS LOST. The client sends every
    header field as a trimmed string, so a column stored as NULL came back as "" and the save wrote the
    "". Measured on live: a no-edit save touched 10 columns on 270 of 300 recipes. Nothing looked wrong,
    since every reader treats "" and NULL as empty and the diff folds them together, and the cost was
    paid somewhere else entirely. The recipe's serialization stopped matching its baseline byte for
    byte, so _recipe_annotations lost its short-circuit for that recipe permanently. That is how
    brioche-bread came to hold "" in descr, image and total_time against a baseline holding NULL.

    ⚠️ THE WEAKEST TEST THAT FIXES IT, ON PURPOSE. Null and empty mean the same thing, so keep what is
    stored. It does NOT fold whitespace, and it must not: a user who re-wrapped a headnote has made a
    real edit, and a keep rule that collapsed whitespace would discard it silently. The diff's own
    comparison DOES fold whitespace (units.compare_text), so no mark appears for one either way. That
    division is deliberate. Compare loosely, write faithfully."""
    return old if (new or "") == (old or "") else new


@app.route("/api/recipes/<rid>", methods=["PUT"])
def update_recipe(rid):
    """Edit an app-owned recipe. The slug (id) stays fixed so references don't break."""
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        # The WHOLE row, because the header write below keeps a field the payload did not really
        # change (see _kept) and needs the stored value to compare against.
        row = s.execute(select(Recipe.__table__)
                        .where(Recipe.__table__.c.id == rid)).mappings().first()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        # TIER first, then OWNERSHIP — the two gates refuse DISJOINT sets and neither subsumes the
        # other (tier refuses seed rows whoever owns them; ownership refuses app rows owned by someone
        # else). Order matters for the MESSAGE, not the outcome: a seed row is owner-NULL, so checking
        # ownership first would answer "not your recipe" about a recipe nobody owns. Tier is a property
        # of the recipe, ownership a property of the relationship — refusing on the intrinsic one first
        # yields the truer message. It also keeps test_seed_recipe_is_read_only / test_gate_parity_*
        # testing the SEED gate rather than passing on an ownership 403 that happens to share a status.
        if row["source"] not in EDITABLE_SOURCES:
            return jsonify({"error": "this recipe is from seed.py and is read-only here, edit it in seed.py"}), 403
        if row["owner"] != current_user.id:                  # default-deny: only the owner may edit
            return jsonify({"error": "not your recipe"}), 403
        # The [[key]]s this recipe's steps already carry. An edit may keep them even if nothing in
        # `ingredients` answers to them any more, and may not introduce a NEW one that names nothing.
        standing = set()
        for (body,) in s.execute(select(RecipeStep.body).where(RecipeStep.recipe_id == rid)):
            standing.update(m.group(1).strip()
                            for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", body or ""))
        clean, err = resolve_recipe_payload(s, payload, standing)
        if err:
            return jsonify({"error": err}), 400
        # ⚠️ ONLY THE FIELDS THE PAYLOAD ACTUALLY NAMES. This wrote all ten unconditionally, so an
        #    absent key reached _kept as None, compared "" against the stored value, found them
        #    different and wrote NULL over it. A PUT that did not mention `notes` erased the
        #    headnote, which is the longest prose this database holds and has no second copy. Same
        #    class as the waits key in write_plan_ahead: absent is not empty. An explicit "" still
        #    clears the field, which is how the editor empties one.
        s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rid).values(
            name=clean["name"],
            **{f: _kept(payload[f], row[f]) for f in EDITABLE_HEADER_FIELDS if f in payload},
        ))
        # The rows as they stand. write_recipe_rows matches each incoming line to one of them by id
        # and updates it in place, falls back to the two-tier _Carry for a line that arrives without
        # one, inserts what is left and deletes what the payload dropped. Read here rather than in
        # there so the id check below and the write agree on exactly one set of rows.
        stored_ing = s.execute(
            select(RecipeIngredient.__table__)
            .where(RecipeIngredient.recipe_id == rid)
            .order_by(RecipeIngredient.position, RecipeIngredient.id)
        ).mappings().all()
        stored_step = s.execute(
            select(RecipeStep.__table__)
            .where(RecipeStep.recipe_id == rid)
            .order_by(RecipeStep.position, RecipeStep.id)
        ).mappings().all()
        # BEFORE the first write, so a bad id costs nothing. The recipe row above is updated in this
        # same transaction and `with orm_session()` closes without committing on this return.
        id_err = _check_row_ids(clean, stored_ing, stored_step)
        if id_err:
            return jsonify({"error": id_err}), 400
        write_recipe_rows(s, rid, clean, stored=(stored_ing, stored_step))
        # ⚠️ IMMEDIATELY AFTER THE WRITE AND BEFORE ANYTHING READS THE ROWS. A surviving row that
        # came out empty means the server read this payload differently from how the client wrote it,
        # which is the shape that nearly emptied every recipe's method when steps gained an object
        # wire form. Raising here rolls the whole save back.
        assert_no_blanked_rows(s, rid, stored_ing, stored_step)
        # ⚠️ BEFORE the baseline capture and the heading sync below, so a snapshot taken in this
        # same transaction sees the waits this save wrote.
        write_plan_ahead(s, rid, payload)
        # ⚠️ AFTER write_recipe_rows, for the reason write_plan_ahead is: a note's step_id has to be
        #    checked against the steps THIS SAVE wrote, not the ones it replaced.
        write_notes(s, rid, payload)
        # U5: an imported recipe is written with NO reason='original' baseline, because it arrives as
        # the publisher wrote it and the user is about to fix the parse errors. THIS save is the first
        # moment the content is something they have approved, so the baseline is captured here, from
        # the rows JUST written — import corrections leave no annotations, later edits all do.
        #
        # NARROWLY GATED, and the gate is the point: it fires only for a recipe carrying an
        # `imported_via` flag, and snapshot_original's WHERE NOT EXISTS makes it a no-op ever after.
        # It must NOT become unconditional — sync_original_heading_layout's docstring spells out why
        # minting a baseline from current content is destructive for a recipe that simply never got
        # one: it would declare that recipe born in its edited state and erase every annotation it
        # should have had. An import has no annotations to erase; a legacy recipe does.
        if s.execute(select(ImportFlag.id).where(
                ImportFlag.recipe_id == rid, ImportFlag.flag == "imported_via")).first():
            snapshot_original(s, rid)
        # AFTER the rows are written (the sync reads the headings that were JUST saved, so it cannot
        # run before this) and BEFORE the commit (so a content-safety failure aborts the whole edit
        # with no partial state). Same session, same transaction — deliberately not a post-commit
        # hook. See sync_original_heading_layout.
        sync_original_heading_layout(s, rid)
        s.commit()
    return jsonify({"id": rid})


# ---- POINT/linked-hero cleanup helpers (Stage 4 build 2c) ---------------------------------------
# ⚠️ ONE QUESTION, TWO SPELLINGS, BECAUSE THE TWO DELETE PATHS ASKED IT DIFFERENTLY. "Does this
# recipe have a hero photo" was `if row.image:` in delete_recipe (Python truthiness, so "" and NULL
# both mean no) and `Recipe.image.isnot(None)` in the test-recipe sweep (SQL, so "" means YES and an
# empty string was gathered as a file to unlink). Live carries 16 recipes whose image is "" against
# 163 that are NULL, so the two spellings disagree about a sixth of the corpus. Nothing was lost,
# because unlink_unreferenced drops falsy paths before it reaches the filesystem, but a rule stated
# twice in two different ways is one edit away from mattering.
def has_image():
    """The SQL half: a recipe row whose hero names a file."""
    return and_(Recipe.image.isnot(None), func.trim(Recipe.image) != "")


def image_file(row):
    """The Python half: the file a row's hero names, or None when it names nothing."""
    value = row if isinstance(row, (str, bytes, type(None))) else getattr(row, "image", None)
    return (value or "").strip() or None


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
    """After a delete/cascade has COMMITTED, unlink each file — but ONLY if no surviving row still points
    at it. Guards the copy-shares-image case: copy_recipe carries the image PATH, so two recipes
    can share one file; deleting one must not unlink a file the other still uses. Opens its own session for
    the reference check (the rows are already gone). Idempotent (delete_image no-ops a missing file).

    ⚠️ BOTH TABLES THAT POINT AT A FILE ARE ASKED, AND ONE OF THEM USED TO BE MISSING. Two columns
    name an image, `recipes.image` and `cook_photos.path`, and this read only the first, so a
    surviving ALBUM row was invisible to the guard and its file was unlinked underneath it. The
    hero-upload route is what makes the two diverge: it inserts a cook_photos row AND sets
    recipes.image to the same path, and uploading a REPLACEMENT hero leaves the old path as a plain
    album photo. So the sequence that loses a file is ordinary use. A owns a recipe and uploads a
    hero P, somebody copies that recipe as a test recipe (copy_recipe carries the path), A uploads a
    new hero so P is now only an album photo, and the copy's bulk delete gathers P, finds no
    recipes.image matching, and unlinks a file A's own album row still points at. Reproduced through
    the HTTP API, with a 200 and no sign anything happened. All three callers share this function,
    so the single-account spelling of it was broken the same way.

    ⚠️ IT IS A UNION, NOT A SECOND LOOP. One question, "does anything still reference this path",
    asked once over both columns."""
    paths = [p for p in dict.fromkeys(paths) if p]   # de-dup, drop falsy
    if not paths:
        return
    with orm_session() as s:
        still = set(s.scalars(select(Recipe.image).where(Recipe.image.in_(paths))))
        still |= set(s.scalars(select(CookPhoto.path).where(CookPhoto.path.in_(paths))))
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
        row = s.execute(select(Recipe.source, Recipe.image, Recipe.owner).where(Recipe.id == rid)).first()
        if row is None:
            return jsonify({"error": "recipe not found"}), 404
        if row.source not in EDITABLE_SOURCES:                # TIER first, then OWNERSHIP — see update_recipe
            return jsonify({"error": "seed recipes can't be deleted here — remove them from seed.py"}), 403
        if row.owner != current_user.id:                      # default-deny: only the owner may delete
            return jsonify({"error": "not your recipe"}), 403
        files = list(s.scalars(select(CookPhoto.path).where(CookPhoto.recipe_id == rid)))   # all album files
        hero = image_file(row)
        if hero:
            files.append(hero)                               # + the hero's own file (the orphan fix)
        s.execute(delete(Recipe.__table__).where(Recipe.__table__.c.id == rid))   # cascades cook_photos ROWS
        s.commit()
    unlink_unreferenced(files)                               # AFTER commit: unlink files no surviving recipe uses
    return jsonify({"deleted": rid})


@app.route("/api/recipes/<rid>/image", methods=["POST"])
def upload_recipe_image(rid):
    """Upload a dish photo for a recipe you OWN (multipart, field 'image'): store it, ADD it to the album,
    and make it the hero — "a photo is a photo" (the album is every photo of this dish). Owner-checked
    (mirrors the shares owner-gate). Stored uuid-unique via images.save_cook_photo (like album photos, NOT
    the slug-flat save_image), inserted as a COOK-LESS cook_photos row (cook_log_id NULL) at the album's
    end, then promoted: recipes.image = its path, so is_hero derives true. REPLACING a hero leaves the
    previous one as a plain album photo (its row stays; it just stops matching recipes.image) — nothing
    deleted. Returns ONLY the new path (least-exposure). Login-gated by before_request (NOT in PUBLIC_ENDPOINTS)."""
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
            path = images.save_cook_photo(f.read())          # uuid-unique (images/cooks/<uuid>.jpg), like album photos
        except images.ImageValidationError as e:
            return jsonify({"error": str(e)}), 400           # bad/blocked/bomb input -> 400, nothing written
        next_pos = s.execute(                                # APPEND at the album's end (mirrors add_cook_photo)
            select(func.coalesce(func.max(CookPhoto.position), -1) + 1).where(CookPhoto.recipe_id == rec.id)
        ).scalar_one()
        s.execute(insert(CookPhoto.__table__).values(        # a COOK-LESS album row (cook_log_id NULL)
            cook_log_id=None, recipe_id=rec.id, user_id=current_user.id,
            path=path, caption=None, added_at=now_utc(), position=next_pos,
        ))
        s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rec.id).values(image=path))  # promote -> hero
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


# ⚠️ WHAT A COPY DELIBERATELY DOES NOT CARRY, stated so that everything else on the table IS
#    carried and a column added tomorrow lands in the copy by default. The route named its columns
#    one by one for years and the list was short every time anyone measured it. See copy_recipe.
COPY_RESET_RECIPE_FIELDS = frozenset({"id", "name", "created_at", "source", "uid", "hash", "owner"})


@app.route("/api/recipes/<rid>/copy", methods=["POST"])
def copy_recipe(rid):
    """Duplicate a recipe's CONTENT into a new recipe, resetting the accruing layer to zero.
    `is_test` picks the tier (test vs app). The copy starts with no cooks and no rating for free,
    and migration 048 made that a single fact rather than two: cook_count, last_cooked AND the rating
    all derive from cook_log, which is not copied. Content (incl. import-harvested grams/secondary_measure) is carried by a direct
    row-copy; uid/hash are import identity and left NULL (uid is UNIQUE-indexed — copying it throws)."""
    is_test = bool((request.get_json(silent=True) or {}).get("is_test"))   # thin, self-contained flag
    with orm_session() as s:
        src = s.execute(select(Recipe.__table__).where(Recipe.id == rid)).mappings().first()
        if src is None:
            return jsonify({"error": "recipe not found"}), 404
        new_name, new_id = _unique_copy_id(s, src["name"])
        # ⚠️ STATED OVER THE TABLE. This named 11 columns and the table has 18, so a copy lost
        #    total_includes_waits (migration 058) and printed a different Total from the recipe it
        #    was made from. 1 of live's 300 carries it.
        s.execute(insert(Recipe.__table__).values(
            id=new_id, name=new_name, created_at=now_utc(),
            source=("test" if is_test else "app"), uid=None, hash=None,
            owner=current_user.id,   # R4 (box model): the copy is owned by whoever made it, even copying your own
            **{k: v for k, v in dict(src).items() if k not in COPY_RESET_RECIPE_FIELDS},
        ))
        # Direct row-copy: carries all content INCL. harvested grams/secondary_measure (write_recipe_rows
        # would NULL those). cook_log / ratings / import_flags / per-person tables are deliberately NOT
        # copied — that's what makes the copy start clean.
        # ⚠️ EVERY COLUMN BUT THE ROW'S OWN id, AND THAT IS THE WHOLE POINT. These were two
        #    INSERT…SELECT statements naming their columns by hand, and both lists were short.
        #    heading_level was missing and a copy FLATTENED every subheading (measured: a level-2
        #    heading came back level 1). The ingredient list was missing five: heading (052) and
        #    catalog_id, link_confidence, link_rule, link_matched (033), so a copy lost its library
        #    linkage on 2,851 of live's 3,572 ingredient rows. Written as a loop over the table's
        #    own rows, like the waits, storage and notes loops below, a column added tomorrow is
        #    carried without anyone remembering this route exists. Position order is preserved
        #    because _copy_row_map pairs an old row to its new one BY POSITION.
        for table in (RecipeIngredient.__table__, RecipeStep.__table__):
            for row in s.execute(select(table).where(table.c.recipe_id == rid)
                                 .order_by(table.c.position, table.c.id)).mappings():
                vals = {k: v for k, v in dict(row).items() if k != "id"}
                vals["recipe_id"] = new_id
                s.execute(insert(table).values(**vals))
        # ⚠️ EVERY POINTER IS REMAPPED, WHICH IS WHY THESE ARE NOT INSERT…SELECT. A wait, a note and a
        #    note's step reference all name a ROW of the recipe they belong to. Copying the id would
        #    leave the copy's rows pointing at the ORIGINAL's steps, so editing the original would
        #    change what the copy's links mean. The two tables above are written in position order, so
        #    position is what ties an old row to the new one that replaced it.
        step_map = _copy_row_map(s, RecipeStep.__table__, rid, new_id)
        ing_map = _copy_row_map(s, RecipeIngredient.__table__, rid, new_id)
        # ⚠️ WAITS AND STORAGE WERE NOT COPIED AT ALL. Measured before this line existed: an original
        #    with one wait and one storage row produced a copy with none of either. Both tables
        #    arrived in migration 049, after this route was written, and nothing tested it.
        for w in s.execute(select(RecipeWait.__table__).where(RecipeWait.__table__.c.recipe_id == rid)
                           .order_by(RecipeWait.position, RecipeWait.id)).mappings():
            vals = {k: v for k, v in dict(w).items() if k != "id"}
            vals["recipe_id"] = new_id
            for key in ("step_id", "alongside_step_id", "ext_step_id"):
                vals[key] = step_map.get(vals.get(key))
            s.execute(insert(RecipeWait.__table__).values(**vals))
        for x in s.execute(select(RecipeStorage.__table__)
                           .where(RecipeStorage.__table__.c.recipe_id == rid)
                           .order_by(RecipeStorage.position, RecipeStorage.id)).mappings():
            vals = {k: v for k, v in dict(x).items() if k != "id"}
            vals["recipe_id"] = new_id
            s.execute(insert(RecipeStorage.__table__).values(**vals))
        # ⚠️ AND NOTES, WHICH SURVIVED A COPY ONLY WHILE THEY WERE A COLUMN. Migration 060 made a note
        #    a row, so without this a copy would silently lose every note it had, which is a worse
        #    failure than the two above because the text has no second home.
        for n in s.execute(select(RecipeNote.__table__).where(RecipeNote.__table__.c.recipe_id == rid)
                           .order_by(RecipeNote.position, RecipeNote.id)).mappings():
            vals = {k: v for k, v in dict(n).items() if k != "id"}
            vals["recipe_id"] = new_id
            vals["step_id"] = step_map.get(vals.get("step_id"))
            vals["ingredient_row_id"] = ing_map.get(vals.get("ingredient_row_id"))
            new_note_id = s.execute(insert(RecipeNote.__table__).values(**vals)).inserted_primary_key[0]
            for ref in s.execute(select(RecipeNoteStepRef.__table__)
                                 .where(RecipeNoteStepRef.__table__.c.note_id == n["id"])
                                 .order_by(RecipeNoteStepRef.ref_index)).mappings():
                rv = {k: v for k, v in dict(ref).items() if k != "id"}
                rv["note_id"] = new_note_id
                rv["step_id"] = step_map.get(rv.get("step_id"))
                s.execute(insert(RecipeNoteStepRef.__table__).values(**rv))
        # ⚠️ AND THE AUTHOR'S ORIGINAL WORDS, WHICH A COPY HAD NO RECORD OF AT ALL. Measured on live
        #    after the notes round went out: a copy of aloo-potato-parathas carried its note and the
        #    note's step reference and wrote 0 rows into recipe_notes_original, so the copy was a
        #    playground with no way back while the recipe it came from had one. recipe_notes_original
        #    is written ONCE per recipe and updated by nothing, so a copy has to be given its own at
        #    birth or never get one.
        # ⚠️ FROM THE SOURCE'S ORIGINALS WHERE IT HAS THEM, AND FROM ITS CURRENT NOTES WHERE IT DOES
        #    NOT. A recipe created in the app has note rows and no originals, because only
        #    notes_to_rows and the importer write that table. Copying its current words is the
        #    truthful answer there: they ARE the words it was born with.
        src_orig = list(s.execute(
            select(RecipeNoteOriginal.__table__)
            .where(RecipeNoteOriginal.__table__.c.recipe_id == rid)
            .order_by(RecipeNoteOriginal.__table__.c.position)).mappings())
        if src_orig:
            for o in src_orig:
                vals = {k: v for k, v in dict(o).items() if k != "id"}
                vals["recipe_id"] = new_id
                s.execute(insert(RecipeNoteOriginal.__table__).values(**vals))
        else:
            record_notes_original(s, new_id)      # the create route's own rule
        snapshot_original(s, new_id)   # O-a: the copy's original = its copied content at birth (before editing)
        s.commit()
    return jsonify({"id": new_id}), 201


# --- the per-note write path ---------------------------------------------------------------------
# ⚠️ WHY THESE EXIST AT ALL, WHEN write_notes ALREADY WRITES NOTES. write_notes replaces a recipe's
#    WHOLE list from a save payload, which is the right shape for a create and for the importer and
#    the wrong shape for editing one note in reading view: it needs the other notes in the payload to
#    leave them alone, so a client that holds a stale copy of the list would write that stale copy
#    back. These name ONE row.
#
# ⚠️ AND THEY ARE THE REASON A NOTE COSTS NOTHING. A note is a playground (Andy's ruling): no
#    annotation entry, no mark, and no recipe leaving the byte-equal set because somebody reworded a
#    tip. That is structural rather than careful — recipe_notes is not in the snapshot blob and
#    neither is the derived column, so there is no path from these routes to recipe_snapshots at all.
#    tests/test_note_api.py states it as a measurement anyway, and proves the measurement can fail.
#
# ⚠️ LAST WRITE WINS, DELIBERATELY AND WITH NOTHING CLEVER. Two tabs editing one note is two PATCHes,
#    and the second overwrites the first. There is no version column and no If-Match, because the
#    alternative is a conflict dialog over a single paragraph of prose in a single-user app, and the
#    losing text is still in the other tab's textarea. The ROWS are matched by id, so a collision
#    costs the earlier wording and never the row, its links or its place in the list.

NOTE_FIELDS = ("text", "kind", "step_id", "position")


def _note_gate(s, rid):
    """(recipe row, None) when this caller may write this recipe's notes, else (None, (body, code)).

    ⚠️ THE SAME TWO GATES AS update_recipe, IN THE SAME ORDER, AND THE ORDER IS ABOUT THE MESSAGE.
    A seed row is owner-NULL, so asking about ownership first would answer "not your recipe" about a
    recipe nobody owns. Tier is a property of the recipe, ownership a property of the relationship.

    ⚠️ IT IS THE SERVER'S ANSWER AND NOT THE BUTTON'S. The client hides "+ note" from a non-owner,
    and a hidden button is not an access rule: every one of these routes asks this first.
    """
    row = s.execute(select(Recipe.__table__.c.id, Recipe.__table__.c.source,
                           Recipe.__table__.c.owner)
                    .where(Recipe.__table__.c.id == rid)).mappings().first()
    if row is None:
        return None, (jsonify({"error": "recipe not found"}), 404)
    if row["source"] not in EDITABLE_SOURCES:
        return None, (jsonify({"error": "this recipe is from seed.py and is read-only here, "
                                        "edit it in seed.py"}), 403)
    if row["owner"] != current_user.id:
        return None, (jsonify({"error": "not your recipe"}), 403)
    return row, None


def _is_row_id(v):
    """A row id a payload may name: a whole number, and NOT a bool.

    ⚠️ bool IS AN int IN PYTHON, so `True in step_ids` is true whenever this recipe owns step id 1.
    _check_row_ids guards this for ingredient and step ids already; the note path did not.
    """
    return isinstance(v, int) and not isinstance(v, bool)


def _note_title(value):
    """A note's title as it is STORED: trimmed, or None.

    ⚠️ NULL AND '' ARE NOT TWO SPELLINGS OF "no title", and the CHECK on the column refuses the
    second one. A cleared Title box therefore has to arrive as NULL rather than as a blank string,
    or an otherwise ordinary save is an IntegrityError. One function, because both doors write this
    column and the per-note PATCH and the recipe PUT disagreeing about it is the shape four reviews
    of the notes round found four times."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _note_payload_error(rows, kinds):
    """The first thing wrong inside a note entry, or None. Types only, no database reads.

    ⚠️ IT IS THE FIELDS, NOT THE CONTAINER. resolve_recipe_payload already refuses a notes value
    that is not a list or a string, and an entry that is not an object. This is the layer under
    that, and it is the layer every 500 on a malformed note came from.
    """
    if not isinstance(rows, list):
        return None                                      # absent, or the bare string shape
    for n in rows:
        if "text" in n and not isinstance(n["text"], str):
            return "a note's text must be text"
        if "id" in n and n["id"] is not None and not _is_row_id(n["id"]):
            return "a note's id must be a whole number"
        for key in ("step_id", "ingredient_row_id", "position"):
            if n.get(key) is not None and not _is_row_id(n[key]):
                return f"a note's {key} must be a whole number"
        # ⚠️ THE TYPE IS REFUSED AND THE VALUE IS NOT, AND THE LINE BETWEEN THEM IS THE RULE. A kind
        #    that is a list or a number is a payload nothing can read, and it was a 500. A kind that
        #    is a STRING the table does not list is a stale client or a script, and write_notes has
        #    always put that note under the default kind on purpose, because recipe_notes.kind is a
        #    foreign key and the alternative is an IntegrityError on an otherwise valid save.
        #    ⚠️ THE PER-NOTE PATCH ANSWERS 400 FOR THE SAME STRING, so the two doors still disagree
        #    about an unknown kind. That is a decision for Andy, not a defect to close here.
        if n.get("kind") is not None and not isinstance(n["kind"], str):
            return f"a note's kind must be text, not {type(n['kind']).__name__}"
        # A title is optional, and a non-string one is a payload nothing can read. Refused for the
        # reason the kind's TYPE is refused above: the alternative is a 500 or a column holding
        # whatever str() made of a list.
        if "title" in n and n["title"] is not None and not isinstance(n["title"], str):
            return f"a note's title must be text, not {type(n['title']).__name__}"
        refs = n.get("refs")
        if refs is not None and not isinstance(refs, list):
            return "a note's refs must be a list"
        for r in (refs or ()):
            if not isinstance(r, dict):
                return "each entry in a note's refs must be an object"
            if not _is_row_id(r.get("ref_index")) or r["ref_index"] < 0:
                return "a note reference needs a whole-number ref_index"
            if not isinstance(r.get("match_text"), str):
                return "a note reference needs the words it belongs to"
            if r.get("step_id") is not None and not _is_row_id(r["step_id"]):
                return "a note reference's step_id must be a whole number"
    return None


def _note_step_target(sid, step_ids, was=None):
    """Which step id a note, or one of its references, may actually point at after a save.

    `step_ids` is {step id: is_heading} for THIS recipe. `was` is the id already stored for this
    exact thing, where there is one.

    ⚠️ ONE RULE, THREE DOORS, AND IT USED TO BE THREE ANSWERS. write_notes (the recipe PUT),
    _rescan_note_refs (the per-note PATCH) and _validated_note_fields each decided this for
    themselves, and all three comments claimed to be following the same rule. Measured, they were
    not: a reference to a step that had become a heading was KEPT by a PUT and DESTROYED by the
    next text edit through the other door, and the id lives nowhere else, so converting the heading
    back could never bring it back. One function now, and every door asks it.

    ⚠️ A STEP THAT IS GONE IS GONE. Nothing can bring its id back, so the pointer is dropped rather
    than stored dangling.

    ⚠️ A HEADING IS KEPT WHERE IT WAS ALREADY STORED, AND REFUSED WHERE IT IS NEW, which is the
    distinction the three copies were really groping at. Converting a step to a heading has to be
    reversible (write_plan_ahead's reason: the id lives nowhere else), so a link that already named
    that row survives the conversion and simply stops printing a number. Creating a link to a
    heading is a pointer nobody can follow and no part of the UI offers it, so it is not stored.
    """
    if sid is None or sid not in step_ids:
        return None
    if step_ids[sid] and sid != was:
        return None
    return sid


def _note_ref_rows(text, step_ids, sent=None, carried=None, auto=None):
    """The reference rows a note's words should have after a save. ONE rule, both write doors.

    ⚠️ A REFERENCE EXISTS ONLY WHILE ITS MENTION DOES, keyed on (ref_index, match_text), so
    inserting a sentence before "step 9" keeps the link and rewording the mention drops it.

    ⚠️ THE TARGET IS THE FIRST OF THREE THAT NAMES ONE, and the order is the rule:
      what the payload sent for those exact words, where it names a step;
      then what the stored row held for them, INCLUDING a stored null, which is an answer and
        stops the search, because that is how an unlink survives a later text edit;
      then what the words themselves resolve to, which is the "step N" auto-link.
    ⚠️ A SENT NULL IS NOT AN ANSWER, and that is why the auto-link reaches the PUT at all. The
    editor round-trips refs verbatim and builds a new mention with a null target, because a client
    cannot know a link the server has never told it about. Reading that null as a decision is what
    made the same words link in reading view and stay plain in Edit mode.
    """
    sent, carried, auto = sent or {}, carried or {}, auto or {}
    rows = []
    for m in notes_rules.scan_step_mentions(text):
        key = (m["ref_index"], m["match_text"])
        if sent.get(key) is not None:
            target = sent[key]
        elif key in carried:
            target = carried[key]
        else:
            target = auto.get(key)
        rows.append({"ref_index": m["ref_index"], "match_text": m["match_text"],
                     "step_id": _note_step_target(target, step_ids, carried.get(key))})
    return rows


def _note_step_ids(s, rid):
    """{step id: is_heading} for this recipe, the set a note's link may name."""
    return {m["id"]: bool(m["is_heading"]) for m in s.execute(
        select(RecipeStep.__table__.c.id, RecipeStep.__table__.c.is_heading)
        .where(RecipeStep.__table__.c.recipe_id == rid)).mappings()}


def _carried_refs(value):
    """The references a restore is handing back -> {(ref_index, match_text): step_id}, or an error.

    ⚠️ A STORED NULL IN HERE IS AN ANSWER, which is the whole point. delete_note hands the client
    the note's references as they stood, Undo posts them straight back, and a mention the cook had
    deliberately unlinked has to come back unlinked. Merged OVER the auto-link exactly as
    update_note merges its carried map, so a mention with no history still links itself.

    ⚠️ AND IT REFUSES WHAT IT CANNOT READ, like every other list on a write path. A dict iterated
    to its keys and a list of numbers filtered to nothing both answer 200 while losing the thing
    they were asked to carry.
    """
    if value is None:
        return {}, None
    if not isinstance(value, list):
        return None, "a note's refs must be a list"
    out = {}
    for r in value:
        if not isinstance(r, dict):
            return None, "each ref must be an object"
        idx, words, sid = r.get("ref_index"), r.get("match_text"), r.get("step_id")
        if not isinstance(idx, int) or not isinstance(words, str):
            return None, "a ref names a mention by ref_index and match_text"
        if sid is not None and not isinstance(sid, int):
            return None, "a ref's step_id must be a step id or null"
        out[(idx, words)] = sid
    return out, None


def _rescan_note_refs(s, note_id, text, step_ids, carried=None, auto=None):
    """Rewrite one note's step references from its words. Returns the rows written.

    ⚠️ THE SAME RULE write_notes USES, AND FOR THE SAME REASON. A reference exists only while its
    mention does: inserting a sentence before "step 9" keeps the link, deleting the words drops it.
    Carried by (ref_index, match_text) so rewording the mention underneath an ordinal does not leave
    the old target attached to the new words.

    ⚠️ AND A MENTION WITH NO TARGET IS STILL A ROW. It stores step_id NULL, which is what lets the
    text render as plain words rather than as a link, and what lets a later link/unlink name it.

    ⚠️ carried AND auto STAY APART, BECAUSE _note_step_target ASKS WHAT WAS STORED. Both per-note
    doors merged them (`auto.update(carried)`) and handed the result in as `carried`, so the
    guard's `sid != was` compared a value against itself and could never fire. write_notes, the
    third door, had it right all along and takes the two as separate arguments.
    ⚠️ MEASURED, THAT MERGE CHANGED NO OUTCOME, and this is recorded rather than dressed up as a
    bug fix. The only keys the merge added to `carried` came from the auto-link, and
    _auto_link_mentions resolves against notes_rules.step_numbers, which counts NON-HEADING rows,
    so an auto-linked target is never a heading and the guard had nothing to catch. They are passed
    apart because a guard that cannot fire is worse than no guard: it reads as protection. Found by
    an independent review of the 2026-10-07 round.
    ⚠️ A heading link handed back by an UNDO still survives, which is the point of the distinction
    and is tested: delete_note returns the note's references and Undo posts them straight back, so
    those ARE links that were stored. Refusing them would make deleting a note the one gesture that
    destroys a link to a converted step for good.
    """
    rnr = RecipeNoteStepRef.__table__
    s.execute(delete(rnr).where(rnr.c.note_id == note_id))
    # ⚠️ THE TARGETS COME FROM _note_ref_rows, NOT FROM A SECOND COPY OF THE RULE HERE. This read
    #    `target not in step_ids or step_ids[target]`, which NULLED a reference whose step had
    #    become a heading while the PUT door kept it. Measured: auto-link a note to step 2, convert
    #    step 2 to a heading through the PUT (the link is held, correctly), then change one word of
    #    the note in reading view, and the link is gone for good.
    written = _note_ref_rows(text, step_ids, carried=carried, auto=auto)
    for row in written:
        s.execute(insert(rnr).values(note_id=note_id, **row))
    return written


def _auto_link_mentions(text, step_ids, numbers):
    """{(ref_index, match_text): step id} for every "step N" naming a step that exists.

    ⚠️ THIS IS THE "step N" AUTO-LINK, AND IT RESOLVES AGAINST THE NUMBERS THE PAGE PRINTS. A cook
    typing "step 3" means the third step they can see, which is the third NON-HEADING row, so the
    answer comes from notes_rules.step_numbers rather than from a position or a row id.

    ⚠️ A NUMBER NAMING NO STEP IS LEFT UNLINKED RATHER THAN GUESSED. "step 40" on a nine-step recipe
    stores the mention with a null target and prints as plain text, which is the rule a reference
    whose step became a heading already follows: a wrong number is worse than no link.
    """
    by_number = {n: sid for sid, n in numbers.items() if n is not None}
    out = {}
    for m in notes_rules.scan_step_mentions(text):
        sid = by_number.get(m["number"])
        if sid is not None and sid in step_ids and not step_ids[sid]:
            out[(m["ref_index"], m["match_text"])] = sid
    return out


def _notes_out(s, rid, note_id):
    """(the one note, the whole list), both in exactly the shape the GET route serves them in.

    One read, because every one of these routes returns both: the row that changed, and the list,
    since a create or a move renumbers the others and the client repaints from the list rather than
    guessing what the server did.
    """
    all_notes = read_notes(s, rid)
    return next((n for n in all_notes if n["id"] == note_id), None), all_notes


def _validated_note_fields(payload, step_ids, kinds, *, creating):
    """The fields a payload may set, validated. Returns (values, error string)."""
    vals = {}
    if "text" in payload or creating:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None, "a note needs some text"
        vals["text"] = text.strip()
    if "kind" in payload:
        kind = payload.get("kind")
        if kind not in kinds:
            return None, f"unknown note kind: {kind!r}"
        vals["kind"] = kind
    if "title" in payload:
        title = payload.get("title")
        if title is not None and not isinstance(title, str):
            return None, "a note's title must be text"
        # ⚠️ A CLEARED BOX IS A CHANGE, SO '' HAS TO REACH vals. It becomes NULL on the way, which
        #    is the only spelling of "no title" the column accepts, and returning early on a blank
        #    string would make clearing a title the one edit the editor could not save.
        vals["title"] = _note_title(title)
    if "step_id" in payload:
        sid = payload.get("step_id")
        if sid is not None:
            if not isinstance(sid, int) or sid not in step_ids:
                return None, "that step is not in this recipe"
            # ⚠️ A HEADING IS REFUSED RATHER THAN STORED INERT. notes_rules.resolve would render a
            #    heading-linked note without a link, so storing it costs nothing on the page and
            #    leaves a pointer that reads as a defect in every sweep over the table. The UI only
            #    offers "+ note" on real steps, so this is the programmatic door.
            if step_ids[sid]:
                return None, "a note attaches to a step, not to a heading"
        vals["step_id"] = sid
    if "position" in payload:
        pos = payload.get("position")
        if not isinstance(pos, int) or pos < 0:
            return None, "position must be a whole number"
        vals["position"] = pos
    return vals, None


@app.route("/api/recipes/<rid>/notes", methods=["POST"])
def create_note(rid):
    """Add one note. Returns the row, in the GET route's shape, and the recipe's whole list.

    The list comes back because a create can renumber positions, and the client repaints from it
    rather than guessing what the server did.
    """
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        _row, err = _note_gate(s, rid)
        if err:
            return err
        step_ids = _note_step_ids(s, rid)
        kinds = {m["kind"] for m in s.execute(select(NoteKind.__table__.c.kind)).mappings()}
        vals, msg = _validated_note_fields(payload, step_ids, kinds, creating=True)
        if msg:
            return jsonify({"error": msg}), 400
        carried, msg = _carried_refs(payload.get("refs"))
        if msg:
            return jsonify({"error": msg}), 400
        stored = _stored_rows(s, RecipeNote.__table__, rid)
        vals.setdefault("kind", notes_rules.DEFAULT_KIND)
        vals.setdefault("step_id", None)
        # ⚠️ THE DEFAULT PLACE IS THE END, and an explicit position is clamped into the list rather
        #    than refused, because an off-by-one from a client that just deleted a row should not
        #    cost the cook the note they typed.
        pos = vals.pop("position", len(stored))
        pos = max(0, min(pos, len(stored)))
        plan = []
        for i, m in enumerate(stored[:pos]):
            plan.append((m, {"position": i}))
        plan.append((None, dict(recipe_id=rid, position=pos, ingredient_row_id=None, **vals)))
        for i, m in enumerate(stored[pos:], start=pos + 1):
            plan.append((m, {"position": i}))
        _apply_rows(s, RecipeNote.__table__, plan, [])
        new_id = s.scalar(select(RecipeNote.__table__.c.id)
                          .where(RecipeNote.__table__.c.recipe_id == rid,
                                 RecipeNote.__table__.c.position == pos))
        numbers = notes_rules.step_numbers(list(s.execute(
            select(RecipeStep.__table__.c.id, RecipeStep.__table__.c.is_heading)
            .where(RecipeStep.__table__.c.recipe_id == rid)
            .order_by(RecipeStep.__table__.c.position, RecipeStep.__table__.c.id)).mappings()))
        # ⚠️ AN UNDO RESTORES THE LINKS IT WAS DELETED WITH, AND IT USED TO RE-LINK THEM. The undo
        #    of a delete is a re-create (delete_note hands back `restore` and the client posts it),
        #    and this ran the auto-link over the words with nothing carried, so every "step N"
        #    mention came back linked. A cook who had unlinked one, deleted the note and pressed
        #    Undo got the link they had removed. Same merge as update_note: carried wins, including
        #    a carried null, and a mention with no history still links itself.
        auto = _auto_link_mentions(vals["text"], step_ids, numbers)
        _rescan_note_refs(s, new_id, vals["text"], step_ids, carried=carried, auto=auto)
        out, all_notes = _notes_out(s, rid, new_id)
        s.commit()
    return jsonify({"note": out, "notes": all_notes}), 201


@app.route("/api/recipes/<rid>/notes/<int:note_id>", methods=["PATCH"])
def update_note(rid, note_id):
    """Change one note's text, kind, step link or place. Only the keys the payload names.

    ⚠️ ONE ENDPOINT FOR ALL FOUR, rather than a route each for "change kind" and "link a step". They
    are the same operation on the same row with the same gate, and a route per field means four
    places to forget the reference rescan. `text` is the only one that rescans, because the
    references come from the words.
    """
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        _row, err = _note_gate(s, rid)
        if err:
            return err
        rn = RecipeNote.__table__
        stored = _stored_rows(s, rn, rid)
        me = next((m for m in stored if m["id"] == note_id), None)
        if me is None:
            return jsonify({"error": "note not found"}), 404
        step_ids = _note_step_ids(s, rid)
        kinds = {m["kind"] for m in s.execute(select(NoteKind.__table__.c.kind)).mappings()}
        vals, msg = _validated_note_fields(payload, step_ids, kinds, creating=False)
        if msg:
            return jsonify({"error": msg}), 400
        if not vals:
            return jsonify({"error": "nothing to change"}), 400
        move_to = vals.pop("position", None)
        if vals:
            s.execute(update(rn).where(rn.c.id == note_id).values(**vals))
        if move_to is not None and move_to != me["position"]:
            others = [m for m in stored if m["id"] != note_id]
            move_to = max(0, min(move_to, len(others)))
            order = others[:move_to] + [me] + others[move_to:]
            _apply_rows(s, rn, [(m, {"position": i}) for i, m in enumerate(order)], [])
        if "text" in vals:
            carried = {(r["ref_index"], r["match_text"]): r["step_id"] for r in s.execute(
                select(RecipeNoteStepRef.__table__)
                .where(RecipeNoteStepRef.__table__.c.note_id == note_id)).mappings()}
            numbers = notes_rules.step_numbers(list(s.execute(
                select(RecipeStep.__table__.c.id, RecipeStep.__table__.c.is_heading)
                .where(RecipeStep.__table__.c.recipe_id == rid)
                .order_by(RecipeStep.__table__.c.position, RecipeStep.__table__.c.id)).mappings()))
            # ⚠️ A MENTION THE COOK HAS JUST TYPED IS AUTO-LINKED, AND ONE THEY ALREADY UNLINKED IS
            #    NOT RE-LINKED. The carried value wins where the same words were there before, so
            #    "remove link" survives the next keystroke; a mention with no history auto-links.
            # The carried value WINS, including a carried None. A mention whose words were there
            # before keeps whatever it pointed at, so "remove link" survives the next keystroke,
            # and a mention with no history takes the auto-link. _note_ref_rows holds that order;
            # merging the two here is what let a NEW link name a heading.
            auto = _auto_link_mentions(vals["text"], step_ids, numbers)
            _rescan_note_refs(s, note_id, vals["text"], step_ids, carried=carried, auto=auto)
        out, all_notes = _notes_out(s, rid, note_id)
        s.commit()
    return jsonify({"note": out, "notes": all_notes}), 200


@app.route("/api/recipes/<rid>/notes/<int:note_id>/refs/<int:ref_index>", methods=["PATCH"])
def update_note_ref(rid, note_id, ref_index):
    """Link or unlink ONE "step N" mention. `step_id` null is "remove link".

    ⚠️ A SEPARATE ROUTE BECAUSE IT NAMES A MENTION, NOT THE NOTE. The note's text is unchanged, so
    sending it through update_note would rescan the references and undo the very thing being asked
    for.

    ⚠️ NO CLIENT CALLS THIS TODAY, AND IT STAYS. Measured 2026-10-07: static/app.js had one caller,
    unlinkNoteRef, which nothing called, and it has been removed. The × beside a note's step link is
    data-note-unlink-step and clears the note's own step_id, which is a different thing. The route
    stays because it is the ONLY way a stored null reference is made, and a stored null is what
    "an unlink survives the next keystroke" rests on (_note_ref_rows, and the restore a delete hands
    back). Removing it would leave that rule with nothing able to exercise it outside the tests.
    Whether the page should offer a per-mention unlink again is a product decision, not a cleanup.
    """
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        _row, err = _note_gate(s, rid)
        if err:
            return err
        rnr = RecipeNoteStepRef.__table__
        me = s.execute(select(RecipeNote.__table__)
                       .where(RecipeNote.__table__.c.id == note_id,
                              RecipeNote.__table__.c.recipe_id == rid)).mappings().first()
        if me is None:
            return jsonify({"error": "note not found"}), 404
        ref = s.execute(select(rnr).where(rnr.c.note_id == note_id,
                                          rnr.c.ref_index == ref_index)).mappings().first()
        if ref is None:
            return jsonify({"error": "that note does not name a step there"}), 404
        sid = payload.get("step_id")
        step_ids = _note_step_ids(s, rid)
        if sid is not None:
            if not isinstance(sid, int) or sid not in step_ids:
                return jsonify({"error": "that step is not in this recipe"}), 400
            if step_ids[sid]:
                return jsonify({"error": "a reference names a step, not a heading"}), 400
        s.execute(update(rnr).where(rnr.c.note_id == note_id, rnr.c.ref_index == ref_index)
                  .values(step_id=sid))
        out, all_notes = _notes_out(s, rid, note_id)
        s.commit()
    return jsonify({"note": out, "notes": all_notes}), 200


@app.route("/api/recipes/<rid>/notes/<int:note_id>", methods=["DELETE"])
def delete_note(rid, note_id):
    """Remove one note. Returns what it took, so the client can offer Undo.

    ⚠️ THE UNDO IS A RE-CREATE AND IT IS HONEST ABOUT THAT. `restore` carries the words, the kind,
    the place and the step link, so pressing Undo puts an equivalent note back at the same position.
    It is a NEW row with a new id, because the old one is gone and pretending otherwise would mean
    keeping deleted rows around. Nothing downstream holds a note id: the snapshot does not record
    notes, so a new id costs the recipe nothing.
    """
    with orm_session() as s:
        _row, err = _note_gate(s, rid)
        if err:
            return err
        rn = RecipeNote.__table__
        stored = _stored_rows(s, rn, rid)
        me = next((m for m in stored if m["id"] == note_id), None)
        if me is None:
            return jsonify({"error": "note not found"}), 404
        # ⚠️ THE TITLE IS IN IT, AND IT WAS NOT. This body is what Undo POSTs back verbatim, so a
        #    field missing here is a field the restore invents as empty. Deleting a titled note and
        #    pressing Undo brought it back untitled, and the title was then gone for good:
        #    recipe_notes_original has no title column, and an app-authored note has no original row
        #    at all. The Edit-mode delete keeps the whole row object and survived, so this was the
        #    reading view only. Same shape as the restore's own four fields and as `heading_level`.
        # ⚠️ THE REFERENCES TRAVEL WITH IT, FOR THE REASON THE TITLE DOES. This body is what Undo
        #    posts back verbatim, and a field missing from it is a field the restore invents. The
        #    references were missing, so the re-create auto-linked every "step N" mention and an
        #    unlink the cook had made was undone by their own Undo.
        refs = [{"ref_index": r["ref_index"], "match_text": r["match_text"], "step_id": r["step_id"]}
                for r in s.execute(
                    select(RecipeNoteStepRef.__table__)
                    .where(RecipeNoteStepRef.__table__.c.note_id == note_id)
                    .order_by(RecipeNoteStepRef.__table__.c.ref_index)).mappings()]
        restore = {"text": me["text"], "title": me["title"], "kind": me["kind"],
                   "position": me["position"], "step_id": me["step_id"], "refs": refs}
        s.execute(delete(rn).where(rn.c.id == note_id))      # refs cascade
        left = [m for m in stored if m["id"] != note_id]
        _apply_rows(s, rn, [(m, {"position": i}) for i, m in enumerate(left)], [])
        all_notes = read_notes(s, rid)
        s.commit()
    return jsonify({"deleted": note_id, "restore": restore, "notes": all_notes}), 200


@app.route("/api/test-recipes", methods=["DELETE"])
def delete_test_recipes():
    """Delete the CALLER'S test-tier recipes at once (their children cascade via ON DELETE CASCADE).
    Matches only source='test', never app/seed, and only rows the requester owns. Sibling namespace to
    /api/recipes/<rid> so it can't be shadowed by a recipe slugged 'test'. Mirrors delete_recipe's 2c
    file cleanup: the cascade removes ROWS but not FILES, so gather every test recipe's cook-photo paths
    + hero files BEFORE the delete and unlink them AFTER commit — otherwise a bulk test-delete orphans
    those files on disk. unlink_unreferenced skips any file a surviving recipe still references as its hero
    (the copy-shares-image guard: a test recipe whose hero is shared with a surviving app copy keeps it).

    ⚠️ OWNER IS PART OF THE DELETE, NOT A CHECK AROUND IT. This used to match source='test' alone,
    with no owner clause, and copy_recipe stamps every copy with owner=current_user.id. So any
    logged-in account could delete any other account's test copies, and the Browse header told them
    how many were there: the button's count came from GET /api/recipes, which is not owner-filtered,
    so B saw "Delete 1 test recipe" because A had made one. Folding the owner into the WHERE means a
    row somebody else owns is never selected, by the same rule get_ingredient follows, rather than
    fetched and then judged.

    ⚠️ AND THE FILE SWEEP IS SCOPED THE SAME WAY, for the same reason the delete is. Gathering every
    test recipe's photos and then deleting only your own would unlink another account's hero while
    its recipe row survived, which is worse than the cross-owner delete: a live row pointing at a
    file that is gone. unlink_unreferenced's copy-share guard would not help, because it asks which
    files a SURVIVING recipe still references and the answer would be "this one", only after the
    sweep had already been built from the wrong set."""
    with orm_session() as s:
        mine = (Recipe.source == "test", Recipe.owner == current_user.id)
        files = list(s.scalars(select(CookPhoto.path)
                               .join(Recipe, CookPhoto.recipe_id == Recipe.id)
                               .where(*mine)))                 # the caller's test recipes' album files
        files += list(s.scalars(select(Recipe.image)
                                .where(*mine, has_image())))                  # + their heroes
        n = s.execute(delete(Recipe).where(*mine)).rowcount     # children cascade (FK ON)
        s.commit()
    unlink_unreferenced(files)   # AFTER commit: unlink files no surviving recipe uses (copy-share guarded)
    return jsonify({"deleted": n})


# ---- ingredient field guide ----

def mine_or_shared():
    """The one answer to "may this reader see this ingredient row".

    ⚠️ ONE CLAUSE, FIVE CALLERS, BECAUSE FOUR OF THEM HAD IT AND ONE DID NOT. Migration 031 gave
    `ingredients` an owner: NULL means a LIBRARY row anyone may read, anything else means the row
    belongs to one person. get_ingredient folded that into its WHERE and so did both halves of
    delete_ingredient, while list_ingredients and in_season selected the table bare, so a personal
    row showed up in every account's picker and in everyone's seasonal list. Written out five times
    it was one omission away from exactly that, which is what happened.

    ⚠️ IT READS THE TABLE COLUMN, NOT THE MAPPED ATTRIBUTE, so one spelling serves both an ORM
    select and a Core delete and no caller has to name `owner` to ask the question. A test pins that
    this function is the only reader of the column (tests/test_ingredient_identity.py)."""
    col = Ingredient.__table__.c.owner
    return or_(col.is_(None),                        # a library row, readable by everyone
               col == current_user.id)               # or this reader's own personal row


@app.route("/api/ingredients")
def list_ingredients():
    """The whole library as {id, name} — used to populate the recipe form and the
    'add ingredient' picker in a person's version."""
    with orm_session() as s:
        rows = s.execute(select(Ingredient.id, Ingredient.name)
                         .where(mine_or_shared())
                         .order_by(Ingredient.name)).all()
    return jsonify([dict(r._mapping) for r in rows])


@app.route("/api/ingredients/<iid>")
def get_ingredient(iid):
    """One ingredient's field-guide panel. Login-gated by the before_request allowlist (NOT in
    PUBLIC_ENDPOINTS), like every route that isn't the SPA shell or auth.

    ⚠️ OWNERSHIP IS PART OF THE LOOKUP, NOT A CHECK AFTER IT. The Panel's stage 1 (migration 031)
    gave this table an `owner`: NULL means a LIBRARY row and anyone may read it, anything else means the row
    belongs to one person. Folding that into the WHERE means a row you may not read is never fetched,
    and it leaves exactly ONE refusal branch, so "no such ingredient" and "not yours" cannot drift
    apart later. The season / region / used-in queries below run only on a row that passed, so a
    hidden row leaks nothing through its children either.

    ⚠️ 404 FOR BOTH, WHICH IS THE APP'S CONVENTION AND NOT A DEPARTURE FROM IT. The six
    recipes.owner gates answer 403 "not your recipe", and every one of them is a WRITE on a recipe the
    requester can already see, since GET /api/recipes returns all recipes to every user
    (docs/SECURITY.md). A 403 conceals nothing there. create_share answers a uniform 404 instead, for
    the case where existence is NOT already public, which docs/SECURITY.md calls the social layer's
    non-leaking uniform 404s. A personal ingredient is that second case. Its existence IS the private
    fact, and ids here are slugified NAMES, the most guessable id space in the app, so 403 on
    /api/ingredients/gochujang would tell a guesser that somebody keeps a private gochujang.

    Inert on today's data. Every row is owner NULL, so this hides nothing from anyone. It lands before
    the Panel's stage 3 creates the first personal row, so there is no window in which one exists and
    this route will still hand it to a stranger."""
    with orm_session() as s:
        ing = s.execute(
            select(Ingredient.__table__).where(
                Ingredient.id == iid,
                mine_or_shared(),
            )
        ).first()
        if ing is None:                                          # not there, or not yours: same answer
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


# Ingredient tiers the app may delete. ONLY 'app', which is what the save gate stamps on a row it
# promoted from the library (migration 030). An ALLOWLIST rather than "anything that is not seed" on
# purpose: a tier added later is then protected by default instead of deletable by default. Mirrors
# EDITABLE_SOURCES, which does the same job for recipes.
DELETABLE_INGREDIENT_SOURCES = ("app",)


@app.route("/api/ingredients/<iid>", methods=["DELETE"])
def delete_ingredient(iid):
    """Remove a promoted ingredient nobody links to. The undo for the save gate's create path.

    THE FIRST AND ONLY WAY TO REMOVE AN INGREDIENT. Until now nothing in the app deleted from this
    table, so a row created by mistake was permanent. It exists so a wrong promote is reversible, and
    it landed before the library lookup file was generated so that has always been true.

    ⚠️ SEED ROWS ARE REFUSED, AND NO SEED ROW EXISTS TODAY. The 36 hand-authored rows this guard
    was written for were an early demo, deleted in migration 046 along with seed.py's INGREDIENTS,
    so ingredients holds 0 rows and the refusal has nothing to fire on. The check stays because the
    tier does, and a future seeded row would need it. TIER IS CHECKED FIRST, before the reference
    count, for the reason delete_recipe gives about ownership. All 36 were both seed AND linked, so
    refusing on the intrinsic property yielded the truer message.

    ⚠️ A LINKED ROW IS REFUSED BY A PRE-CHECK, WITH THE FOREIGN KEY AS THE BACKSTOP. Deleting a row
    some recipe points at would dangle that link, and recipe_ingredients.ingredient_id carries NO
    ondelete, so with foreign_keys=ON (set per connection in orm_session) the database already
    refuses. The pre-check is not what makes it safe, it is what makes it EXPLICABLE: the constraint
    raises "FOREIGN KEY constraint failed", which tells the reader nothing, while a count can say
    which recipes to unlink first. It costs one covering-index lookup on idx_ri_ingredient.

    Child rows go with it. ingredient_seasons and ingredient_regions both cascade, so a row carrying
    either is cleaned up by the database. A promoted row has neither, and the cascade is what keeps
    this correct anyway if one ever does.

    404 / 403 / 409 / 200 {"deleted": id}, matching delete_recipe. Login-gated by the before_request
    allowlist, like every other write route."""
    with orm_session() as s:
        row = s.execute(
            select(Ingredient.source, Ingredient.name).where(
                Ingredient.id == iid,
                # ⚠️ OWNERSHIP IS PART OF THE LOOKUP, THE SAME WAY get_ingredient DOES IT. The read
                # folded it in and this route never mentioned `owner`, so one account could delete
                # another's personal, unlinked row by id and get a 200 for it. A library row is
                # owner NULL and stays deletable by anyone, which is what keeps this the undo for
                # the promote path, since that path leaves owner NULL on purpose. One refusal
                # branch, so "no such ingredient" and "not yours" cannot drift apart later.
                mine_or_shared(),
            )).first()
        if row is None:                                  # not there, or not yours: same answer
            return jsonify({"error": "ingredient not found"}), 404
        if row.source not in DELETABLE_INGREDIENT_SOURCES:   # TIER first — see the docstring
            return jsonify({
                "error": "hand-authored ingredients can't be deleted here, edit seed.py instead"
            }), 403
        used = s.scalar(
            select(func.count(func.distinct(RecipeIngredient.recipe_id)))
            .where(RecipeIngredient.ingredient_id == iid))
        if used:
            return jsonify({
                "error": f"{row.name} is still linked by {used} "
                         f"recipe{'s' if used != 1 else ''}, unlink it there first"
            }), 409
        # ⚠️ THE CLAUSE IS ON THE DELETE TOO, NOT ONLY ON THE LOOKUP THAT AUTHORIZED IT. A check
        # that reads and then writes on the bare id is correct only while nothing changes in
        # between, and the whole point of this round is that a write path states what it may touch.
        done = s.execute(delete(Ingredient.__table__).where(
            Ingredient.__table__.c.id == iid,
            mine_or_shared()))
        # ⚠️ THE WRITE'S OWN ANSWER, NOT THE READ'S. The lookup above authorized the delete and the
        #    clause is repeated on the statement, so a row that changed hands or was removed between
        #    the two matches nothing. Reporting {"deleted": id} on a rowcount of 0 tells the client
        #    the row is gone when it is still there, and the client repaints on that word.
        if not done.rowcount:
            s.rollback()
            return jsonify({"error": "ingredient not found"}), 404
        s.commit()
    return jsonify({"deleted": iid})


@app.route("/api/in-season")
@app.route("/api/in-season/<int:month>")
def in_season(month=None):
    if month is None:
        month = datetime.date.today().month
    with orm_session() as s:
        rows = s.execute(
            select(Ingredient.id, Ingredient.name)
            .join(IngredientSeason, IngredientSeason.ingredient_id == Ingredient.id)
            .where(IngredientSeason.month == month, mine_or_shared())
            .order_by(Ingredient.name)
        ).all()
    return jsonify({"month": month, "ingredients": [dict(r._mapping) for r in rows]})


# ---- the ingredient library lookup ----
# The FIRST route that reads a library table. It reads library_names ONLY, the ~10,500-row lookup
# build_db loads from a server-side file. It never opens join.db (894 MB) or sources.db (5.18 GB),
# which are not present on a server and which app.py has no access to.

LIBRARY_SEARCH_LIMIT = 50


def _like_escape(text_):
    """Make a typed % or _ literal rather than a LIKE wildcard. 36 library canonicals carry a %
    ('3% fat reduced cocoa powder', 'Сливки питьевые с массовой долей жира от 10 % до 19 %'), so an
    unescaped query silently turns into a wildcard search."""
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.route("/api/library/search")
def search_library():
    """Search the ingredient library by name, for the picker a later stage will build.

    MATCHING IS A CASE-INSENSITIVE SUBSTRING ON THE CANONICAL, and that is the whole of it. No
    prefix weighting, no token splitting, no fuzzy distance. The picker does not exist yet, so there
    is nothing to tune against, and a v1 that is easy to describe is easier to replace than one
    carrying invented ranking.
    ⚠️ ILIKE, NOT LIKE, BECAUSE LIKE IS NOT THE SAME OPERATOR ON THE TWO DIALECTS THIS APP RUNS ON.
    SQLite's LIKE folds ASCII case; Postgres's LIKE folds nothing at all, so a plain LIKE would have
    made 'penne' miss 'Penne' the moment the app ran on PG. ilike compiles to ILIKE on Postgres and
    to lower(x) LIKE lower(y) on SQLite, so the claim above is true on both. The two still differ on
    NON-Latin text: SQLite's lower() is ASCII-only, so 'масло' does not match 'МАСЛО' there, while
    Postgres folds by locale and does. Closing that gap needs a folded search column, which is a
    decision for when a picker exists.

    ORDERED BY LENGTH, THEN NAME, WHICH IS WHAT MAKES THE CAP HONEST. An exact match is always the
    shortest string containing the query, so shortest-first puts it top without a ranking rule. A
    bare LIMIT with no ORDER BY would return 50 arbitrary rows and could drop the exact match.

    CAPPED AT 50, with `capped` telling the caller there were more. A one-letter query matches
    thousands of the ~10,500 rows, and no picker wants that payload.

    ⚠️ `ingredient_id` IS THE ANSWER THE PICKER ACTUALLY NEEDS, and null is the interesting value.
    Non-null means an `ingredients` row already holds this concept, so the picker links to that id
    and the save path creates nothing. Null means the row would be created on link. `matched_by`
    says which of two different facts produced it:
      "library_id"  an ingredients row records THIS library row as its origin. Exact, no inference.
      "slug"        no provenance match, but an ingredients row already OCCUPIES the id this
                    canonical would mint. That is the hand-authored case: 32 of the 36 seed ids are
                    reproduced exactly by slugifying some library canonical (garlic, red_onion,
                    soy_sauce), and those rows carry no library_id because nobody promoted them.
                    Linking to them is right, and it is what stops a promotion colliding on the
                    primary key.
    A slug match is an inference from a name, so it is reported as its own kind rather than folded
    into the certain one.

    EMPTY RESULTS ON AN EMPTY TABLE, WHICH IS THE NORMAL STATE. library_names is loaded from a
    gitignored server-side file, so a fresh clone and CI have none. The route answers 200 with an
    empty list rather than erroring, which is the same self-disabling this feature does everywhere.

    Login-gated by the before_request allowlist (NOT in PUBLIC_ENDPOINTS), same as every other
    ingredient route."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"query": "", "capped": False, "results": []})

    pattern = f"%{_like_escape(q)}%"
    with orm_session() as s:
        found = s.execute(
            select(LibraryName.library_id, LibraryName.canonical)
            .where(LibraryName.canonical.ilike(pattern, escape="\\"))
            .order_by(func.length(LibraryName.canonical), LibraryName.canonical)
            .limit(LIBRARY_SEARCH_LIMIT + 1)          # one extra, purely to detect the cap
        ).all()
        capped = len(found) > LIBRARY_SEARCH_LIMIT
        found = found[:LIBRARY_SEARCH_LIMIT]

        slugs = {r.canonical: ingredient_slug(r.canonical) for r in found}
        by_library_id, taken_slugs = {}, set()
        if found:
            # ONE query for both halves of the answer, over at most 50 ids and 50 slugs.
            existing = s.execute(
                select(Ingredient.id, Ingredient.library_id).where(or_(
                    Ingredient.library_id.in_([r.library_id for r in found]),
                    Ingredient.id.in_([sl for sl in slugs.values() if sl]),
                ))
            ).all()
            for row in existing:
                if row.library_id:
                    by_library_id[row.library_id] = row.id
                taken_slugs.add(row.id)

    results = []
    for r in found:
        ident, matched_by = by_library_id.get(r.library_id), "library_id"
        if ident is None:
            slug = slugs[r.canonical]
            ident, matched_by = (slug, "slug") if slug in taken_slugs else (None, None)
        results.append({"library_id": r.library_id, "canonical": r.canonical,
                        "ingredient_id": ident, "matched_by": matched_by})
    return jsonify({"query": q, "capped": capped, "results": results})


# ---- cooking log + ratings ----

@app.route("/api/cooks")
def list_cooks():
    """The signed-in user's OWN cook-log entries (cook_log.user_id == current_user), NEWEST-FIRST, for
    the feed compose modal's cook picker. Joins cook_log -> recipes for the name/image. Scoped STRICTLY
    to my own cooks (default-deny — never another user's; login-gated by the before_request allowlist).
    Exposing MY OWN cook_log_id is what lets the client POST /api/shares {cook_log_id} to share a cook
    I'm proud of.

    ?recipe=<id> narrows it to one recipe, which is what the recipe page's cook log reads. The filter
    is ADDITIVE and the user scope is not negotiable by it — a recipe filter still only ever returns
    my own cooks."""
    only = request.args.get("recipe")
    with orm_session() as s:
        rows = s.execute(
            select(CookLog.id, CookLog.recipe_id, CookLog.cooked_on, CookLog.rating, CookLog.caption,
                   CookLog.source, Recipe.name, Recipe.image)
            .join(Recipe, Recipe.id == CookLog.recipe_id)
            .where(CookLog.user_id == current_user.id,
                   *( [CookLog.recipe_id == only] if only else [] ))
            .order_by(CookLog.cooked_on.desc(), CookLog.id.desc())   # newest cook first (id tiebreak, as recipe_stats)
        ).all()
    return jsonify([
        {
            "cook_log_id": r.id,
            "recipe_id": r.recipe_id,
            "recipe_name": r.name,
            "image": r.image,
            "cooked_on": r.cooked_on,
            "rating": float(r.rating) if r.rating is not None else None,
            "caption": r.caption,
            "source": r.source,                 # non-'app' reads as a provisional date (the ~ treatment)
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
    # Migration 048: the log-cook box rates and captions the cook it is logging, in the same write.
    # Both are optional — logging a cook you have no verdict on is the ordinary case.
    rating, rate_err = clean_rating(payload.get("rating"))
    if rate_err:
        return jsonify({"error": rate_err}), 400
    caption, cap_err = clean_caption(payload.get("caption"))
    if cap_err:
        return jsonify({"error": cap_err}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        cl = CookLog.__table__
        fields = {"recipe_id": rid, "user_id": current_user.id, "rating": rating, "caption": caption,
                  "rated_at": now_utc() if rating is not None else None}
        if cooked_on:
            fields["cooked_on"] = cooked_on          # else omitted -> DB default date('now')
        res = s.execute(insert(cl).values(**fields))
        cook_log_id = res.inserted_primary_key[0]   # returned so the client can attach a photo to THIS cook (2b)
        snapshot_recipe(s, rid, cook_log_id, "cook")   # change-tracking stage 1: capture the recipe-state cooked
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    return jsonify({**stats, "cook_log_id": cook_log_id})


@app.route("/api/recipes/<rid>/uncook", methods=["POST"])
def undo_cook(rid):
    """Remove the most recent cook entry — for fixing an accidental tap.

    ⚠️ MIGRATION 048 MADE THIS SIMPLER, AND THE OLD SPECIAL CASE IS GONE ON PURPOSE. The rating used to
    live on the recipe, so undoing the last cook had to work out whether to delete a separate ratings
    row and hand the value back for a redo. A verdict now lives ON the cook row, so deleting the cook
    takes its rating with it and the remaining cooks keep theirs untouched. `cleared_rating` survives
    in the undo payload for one reason only, which is that the redo needs the value to put back."""
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        # R4: everything here is scoped to current_user — MY last cook, MY remaining count, MY rating.
        # Without the user filter, my undo would drop ANOTHER user's rating on the same recipe (the
        # consideration-#3 cross-bleed). recipes stay visible to all, but the personal layer is per-user.
        last = s.execute(
            select(CookLog.id, CookLog.cooked_on, CookLog.source, CookLog.rating, CookLog.caption)
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
            # The verdict left with the row. Carried back only so redo_cook can restore this exact cook.
            undone = {"cooked_on": last.cooked_on, "source": last.source,
                      "cleared_rating": float(last.rating) if last.rating is not None else None,
                      "caption": last.caption}
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    unlink_unreferenced(photo_paths)   # 2c: AFTER commit, unlink the cascade-orphaned files (copy-share guarded)
    return jsonify({**stats, "undone": undone})


# ⚠️ EVERY SOURCE THE LOG ACTUALLY HOLDS, not just the ones a route writes. redo_cook validates a
# restored cook against this tuple, so a source missing here makes undo-then-redo fail on a cook that
# is sitting in the database. 'demo-seed' (5 rows) and 'demo-2b' (2 rows) were missing and did exactly
# that. Any non-'app' source still reads as provisional (see recipe_stats).
COOK_SOURCES = ("app", "paprika-import", "rating-inferred", "demo-seed", "demo-2b")


@app.route("/api/recipes/<rid>/redo-cook", methods=["POST"])
def redo_cook(rid):
    """Restore a cook that /uncook just removed — the SAME cooked_on and source (not a new
    today's cook), and optionally re-set a rating the undo cleared. Makes the redo arrow a
    faithful one-shot reversal of that specific undo. /cooked and /uncook are unchanged.
    All client-supplied inputs are validated (real non-future date, known source, rating on a
    half step) and nothing is written on bad input."""
    payload = request.get_json(silent=True) or {}
    cooked_on = payload.get("cooked_on")
    source = payload.get("source")
    rating, rate_err = clean_rating(payload.get("rating"))   # optional: only when the undo cleared one
    if rate_err:
        return jsonify({"error": rate_err}), 400
    caption, cap_err = clean_caption(payload.get("caption"))
    if cap_err:
        return jsonify({"error": cap_err}), 400
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
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        # The verdict and the note are restored ON the new row, so the redo brings back the whole cook
        # rather than the date alone.
        res = s.execute(insert(CookLog.__table__).values(
            recipe_id=rid, user_id=current_user.id, cooked_on=cooked_on, source=source,
            rating=rating, caption=caption, rated_at=now_utc() if rating is not None else None))
        # change-tracking stage 1: a redo is a NEW cook row -> its own snapshot of the CURRENT recipe-state
        snapshot_recipe(s, rid, res.inserted_primary_key[0], "cook")
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    return jsonify(stats)


# ⚠️ POST /api/recipes/<rid>/rating IS GONE, DELIBERATELY. It set one rating for a whole recipe and
# was explicitly not cook-gated, which is what left the server able to record a verdict on a dish
# nobody had cooked. A rating is now a property of one cooking, so there is no recipe-level thing to
# set. The two ways in are logging a cook with a rating, and rating a cook already in the log
# (PATCH /api/cooks/<id> below). The recipe's number is read-only everywhere and is an average.


@app.route("/api/cooks/<int:cook_log_id>", methods=["PATCH"])
def edit_cook(cook_log_id):
    """Rate or caption ONE cooking (JSON {rating, caption}), which is how the stars on a cook-log row
    write. Cook-owner gated (cook_log.user_id == current_user), mirroring edit_cook_photo.

    ⚠️ ABSENT AND NULL MEAN DIFFERENT THINGS HERE, and conflating them would make it impossible to
    un-rate a cook. A key that is absent leaves that field alone, so rating a cook does not wipe its
    caption. A key sent explicitly as null CLEARS that field. Returns the recipe's stats, since
    changing one cook's verdict moves the recipe's average."""
    payload = request.get_json(silent=True) or {}
    with orm_session() as s:
        cook = s.get(CookLog, cook_log_id)
        if cook is None:
            return jsonify({"error": "cook not found"}), 404
        if cook.user_id != current_user.id:
            return jsonify({"error": "not your cook"}), 403
        values = {}
        if "rating" in payload:
            rating, err = clean_rating(payload["rating"])
            if err:
                return jsonify({"error": err}), 400
            values["rating"] = rating
            values["rated_at"] = now_utc() if rating is not None else None
        if "caption" in payload:
            caption, err = clean_caption(payload["caption"])
            if err:
                return jsonify({"error": err}), 400
            values["caption"] = caption
        if not values:
            return jsonify({"error": "nothing to change — send a rating or a caption"}), 400
        s.execute(update(CookLog.__table__).where(CookLog.__table__.c.id == cook_log_id).values(**values))
        stats = recipe_stats(s, cook.recipe_id, current_user.id)
        s.commit()
    return jsonify({**stats, "cook_log_id": cook_log_id})


@app.route("/api/recipes/<rid>/cooked-and-rated", methods=["POST"])
def log_cook_and_rate(rid):
    """Atomically log a cook (today; source defaults to 'app' — a real confirmed cook) AND rate it, in
    one transaction. Returns recipe_stats.

    ⚠️ THE RATING LANDS ON THE COOK THIS CREATES, not on the recipe (migration 048). The rating is
    REQUIRED here, which is what separates this route from /cooked — a caller with no verdict to
    record is logging a cook, not rating one."""
    payload = request.get_json(silent=True) or {}
    rating, rate_err = clean_rating(payload.get("rating"), allow_none=False)
    if rate_err:
        return jsonify({"error": rate_err}), 400
    caption, cap_err = clean_caption(payload.get("caption"))
    if cap_err:
        return jsonify({"error": cap_err}), 400
    with orm_session() as s:
        if s.scalar(select(Recipe.id).where(Recipe.id == rid)) is None:
            return jsonify({"error": "recipe not found"}), 404
        res = s.execute(insert(CookLog.__table__).values(   # today's cook, source default 'app'
            recipe_id=rid, user_id=current_user.id,
            rating=rating, caption=caption, rated_at=now_utc()))
        cook_log_id = res.inserted_primary_key[0]   # returned for at-log-time photo attach (2b), like log_cook
        snapshot_recipe(s, rid, cook_log_id, "cook")   # change-tracking stage 1: capture the recipe-state cooked
        stats = recipe_stats(s, rid, current_user.id)
        s.commit()
    return jsonify({**stats, "cook_log_id": cook_log_id})


# ---- cook-photo album (Stage 4 build 2b) --------------------------------------------------------
# CRUD for cook photos over the cook_photos table (schema: migration 025/026). Reuses the 2a image seams
# (images.save_cook_photo for the file, images.delete_image for removal), the CookPhoto model, and the
# hero endpoint's owner-check pattern. Login-gated by default (NOT in PUBLIC_ENDPOINTS). NO promote-to-hero
# and NO POINT/linked-hero deletion logic here — that's 2c (so in 2b no cook photo can be a hero yet,
# which is why the DELETE below needs no hero-clear).

COOK_PHOTO_CAPTION_MAX = 60    # album caption is a SHORT label under the polaroid (fits Kalam at readable size).
                               # The feed/share caption (create_share's CAPTION_MAX=280) is a DIFFERENT field, untouched.


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
        # 3d-i: APPEND — a new photo lands at the END of the recipe's stored album order (max position + 1,
        # -1 for the first photo -> 0). Keeps every row non-NULL after the backfill, so nothing relies on the
        # NULLs-last fallback; the user drags it elsewhere later (3d-ii/iii).
        next_pos = s.execute(
            select(func.coalesce(func.max(CookPhoto.position), -1) + 1).where(CookPhoto.recipe_id == rec.id)
        ).scalar_one()
        res = s.execute(insert(CookPhoto.__table__).values(
            cook_log_id=cook_log_id, recipe_id=rec.id, user_id=current_user.id,
            path=path, caption=caption, added_at=now_utc(), position=next_pos,
        ))
        photo_id = res.inserted_primary_key[0]
        # 2c AUTO-PROMOTE: if the recipe has NO hero yet, this photo becomes it (POINT/linked, same path).
        # No-hijack guard — only when YOU own the recipe: attaching a photo to your cook of someone else's
        # recipe must NOT auto-set their empty hero. (Standalone attach already required recipe-owner.)
        is_hero = False
        if not image_file(rec) and rec.owner == current_user.id:
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


@app.route("/api/recipes/<rid>/photos/order", methods=["PATCH"])
def reorder_cook_photos(rid):
    """Persist a dragged album order (Stage 4 build 3d-ii) — set cook_photos.position from the given order.
    Body: {"order": [id, id, …]} — the FULL ordered list of THIS recipe's cook_photo ids. Recipe-owner gated
    (rec.owner == current_user, mirroring promote — the stored album order is the recipe owner's arrangement).
    Validation is load-bearing: the body must be an EXACT permutation of the recipe's photo ids — a foreign/
    unknown id, a missing id (partial list), or a duplicate is rejected 400 with NOTHING written (a malformed
    reorder must not corrupt positions). On accept, sets position = the id's INDEX in the list, all in ONE
    transaction (atomic — all or nothing). Reads come back in the new order via 3d-i's ORDER BY position."""
    order = (request.get_json(silent=True) or {}).get("order")
    with orm_session() as s:
        rec = s.get(Recipe, str(rid))
        if rec is None:
            return jsonify({"error": "recipe not found"}), 404
        if rec.owner != current_user.id:                      # recipe-owner gate (mirrors promote)
            return jsonify({"error": "not your recipe"}), 403
        # EXACT-PERMUTATION validation — reject before any write (atomic: a rejected reorder leaves positions intact)
        if not isinstance(order, list) or not all(isinstance(x, int) for x in order):
            return jsonify({"error": "order must be a list of photo ids"}), 400
        if len(set(order)) != len(order):                     # a duplicate id
            return jsonify({"error": "order has a duplicate id"}), 400
        existing = set(s.execute(select(CookPhoto.id).where(CookPhoto.recipe_id == rec.id)).scalars().all())
        if set(order) != existing:                            # a foreign/unknown id, or a missing one (partial)
            return jsonify({"error": "order must be exactly this recipe's photo ids"}), 400
        for i, pid in enumerate(order):                       # set position = index in the list, one transaction
            s.execute(update(CookPhoto.__table__).where(CookPhoto.__table__.c.id == pid).values(position=i))
        s.commit()
    return jsonify({"ok": True})


# ---- want-to-make queue (stage 2) ---------------------------------------------------------------
# Per-user planning state promoted out of the old GLOBAL "To Make" tag (recipe_queue, migration 024,
# backfilled stage 1). Login-gated by default (NOT in PUBLIC_ENDPOINTS); current_user is ALWAYS the
# actor. A want-to-make queue is for recipes you MEAN to cook — including OTHERS' — so queueing is NOT
# owner-restricted (unlike sharing): any visible recipe is queueable. Mirrors list_cooks (read) /
# the cook routes (idempotent add / recipe_id-keyed remove) verbatim in idiom.

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


# ------------------------------------------------------------------------------------------------ #
# URL import, stage 4 (U4): PREVIEW — paste a URL, see what WOULD be imported. Writes nothing.
#
# This is the first time the reader half (U0 fetch -> U2 cascade -> U1 json-ld) is reachable from the
# app. It costs nothing but the fetch because plan_recipe is PURE: planning a recipe touches no rows,
# so "show me first" needs no staging table and no transaction to roll back. The write path is U5.
# ------------------------------------------------------------------------------------------------ #

# A fetch refusal is the USER's problem or the SITE's problem, and the status has to say which.
# 502/504 are deliberate: they place the fault upstream, so a client can offer "try again" for those
# and "check the link" for a 400. TOO_LARGE is NOT 413 — that status describes the REQUEST body being
# too large, and would tell a client to retry with less, which is not the situation.
FETCH_STATUS = {
    "BAD_URL": 400,        # not a URL we can import (scheme/host) — the pasted text is wrong
    "NOT_HTML": 400,       # a PDF/video/image link — the pasted text points at the wrong thing
    "HTTP_ERROR": 502,     # the site answered with an error (maangchi's Cloudflare 403 is the real case)
    "NETWORK_ERROR": 502,  # DNS/TLS/connection — the site could not be reached at all
    "TOO_LARGE": 502,      # the site's page exceeds url_fetch.MAX_BYTES
    "TIMEOUT": 504,        # the site did not answer in time
    # U0b's address guard. BLOCKED_ADDRESS is 400 because the PASTED url named a non-public address —
    # the same fault as BLOCKED_HOST below. The other two are 502: the user's link was fine and the
    # SITE misbehaved, by redirecting somewhere it shouldn't or by looping.
    "BLOCKED_ADDRESS": 400,
    "BLOCKED_REDIRECT": 502,
    "TOO_MANY_REDIRECTS": 502,
}

# Query keys that identify a VISITOR or a CAMPAIGN rather than a document. Dropping them is what makes
# the same recipe shared from a newsletter and from Facebook collapse to one dedup key. Any utm_* is
# dropped by prefix. Deliberately aggressive: over-collapsing produces a false WARNING, and a warning
# is non-blocking by design — under-collapsing produces a silent duplicate, which is the worse failure.
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "si", "_ga", "_gl", "amp",
})


def normalize_source_url(url):
    """A URL -> a stable dedup key, or "" if it isn't an importable URL.

    Collapses the variants that are the SAME page: scheme (http/https), a leading www. or amp. host
    label, a default port, a trailing slash, a trailing /amp path segment, tracking params, and the
    fragment. Remaining query params are kept and sorted, because plenty of sites carry the recipe's
    identity in the query (?p=1234) and dropping it would merge unrelated recipes.

    NOT collapsed, on purpose: a different HOST. Two publishers' versions of the same dish are two
    typeset recipes with different words, amounts and photos — they are not duplicates of each other,
    and treating them as such would refuse exactly the comparison this app exists to capture.
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    try:
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:              # a malformed port ("host:notanumber") — not an importable URL
        return ""
    if not host:
        return ""
    for label in ("www.", "amp."):
        if host.startswith(label):
            host = host[len(label):]
    if port and port not in (80, 443):
        host = f"{host}:{port}"

    # Path case is PRESERVED — paths are case-sensitive, and lowercasing them would merge two
    # genuinely different URLs on any server that treats them as distinct.
    segments = [seg for seg in parts.path.split("/") if seg]
    while segments and segments[-1].lower() == "amp":
        segments.pop()
    path = "/" + "/".join(segments) if segments else ""

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    query = urlencode(sorted(kept))
    return f"{host}{path}" + (f"?{query}" if query else "")


def private_host_refusal(url):
    """A message if `url` OBVIOUSLY names a non-public address, else None. A cheap pre-filter only.

    Judged from the URL's text, so it costs no DNS lookup and lets the route answer an obviously-bad
    paste without touching the network. It is NOT the security boundary: a name that RESOLVES to a
    private address, and any REDIRECT hop, are caught inside url_fetch (U0b), which resolves before
    connecting and re-checks every hop. That is the right home for it, because U5's write path
    fetches through the same seam and would otherwise be unguarded.

    The classification itself lives in url_fetch.blocked_literal — one copy, two callers.
    """
    return url_fetch.blocked_literal(urlsplit(url or "").hostname)


def duplicate_source_url(s, url):
    """The already-imported recipe whose source_url normalizes to the same key, or None.

    A WARNING, never a skip: the user decides. Compares NORMALIZED forms on both sides, which
    subsumes the exact match (identical URLs normalize identically). Reads every non-null source_url
    rather than filtering in SQL because the normalization is Python, not something SQLite and
    Postgres would both compute the same way in a WHERE clause.
    """
    key = normalize_source_url(url)
    if not key:
        return None
    rows = s.execute(select(Recipe.id, Recipe.name, Recipe.source_url)
                     .where(Recipe.source_url.is_not(None)))
    for rid, name, existing in rows:
        if normalize_source_url(existing) == key:
            return {"id": rid, "name": name, "source_url": existing}
    return None


def preview_body(plan, provenance, duplicate):
    """A write plan -> the preview response. Carries what a PERSON needs in order to decide.

    plan_recipe returns 7 keys; four of them are dropped here on purpose:
      created_at  minted at plan time, and U5 mints its own — showing it would be a value that never
                  reaches the database.
      uid, hash   Paprika's dedup keys. A URL read has neither (url_jsonld sets both to ""), so they
                  would be two permanently-empty fields.
      source      always 'app'; image always None (images are a later pass). Nothing to decide.
    The minted slug IS carried, as `slug`, because it is the recipe's URL name and the one field a
    person may want to change before writing — but it is PROVISIONAL: mint_slug derives it from the
    slugs taken right now, and U5 re-plans against the state at write time.

    Per-ingredient, `ingredient_id` and `note` are dropped: both are unconditionally None out of the
    importer (library linkage is a separate later pass), so they are structure with no content.
    """
    r = plan["recipe"]
    return {
        "slug": r["id"],
        "recipe": {k: r[k] for k in ("name", "author", "source_url", "category", "servings",
                                     "prep_time", "cook_time", "total_time", "descr")},
        # ⚠️ THE NOTES ARE ROWS, NOT A RECIPE FIELD. They were read from r["notes"] here while
        #    recipes.notes existed as a derived copy. Migration 063 drops that column, and the plan
        #    has carried the rows since migration 060, so the preview shows what will actually be
        #    written: one entry per note, with the kind the importer assigned.
        "notes": [{k: n.get(k) for k in ("position", "kind", "text")}
                  for n in (plan.get("notes") or [])],
        "ingredients": [{k: row[k] for k in ("position", "is_heading", "qty", "quantity", "unit",
                                             "label", "raw_text", "grams", "secondary_measure")}
                        for row in plan["ingredients"]],
        # position / is_heading / heading_level / text — already the shape
        "steps": plan["steps"],
        "recipe_flags": plan["recipe_flags"],
        "review_flags": plan["review_flags"],
        "read_by": provenance["layer"],
        # The row U5 will persist, surfaced so the preview shows HOW this was read using the same
        # value that gets written. The route does NOT write it.
        "provenance_flag": url_cascade.provenance_flag_row(provenance),
        "duplicate": duplicate,                      # None, or {id, name, source_url} — a warning
    }


@app.route("/api/import/preview", methods=["POST"])
def import_preview():
    """Read a pasted URL and return the plan it WOULD write. Writes nothing.

    POST, not GET, and that is a security decision rather than a REST one: this route makes the
    SERVER perform a network fetch to a user-supplied address. A GET would be reachable by
    navigation, an <img> tag or a prefetch, which is the same shape of mistake as a GET that writes.
    Login-gated by the fail-closed default in _require_login (the endpoint is not in PUBLIC_ENDPOINTS).
    """
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "paste a recipe URL to preview", "code": "BAD_URL"}), 400

    blocked = private_host_refusal(url)
    if blocked:
        return jsonify({"error": blocked, "code": "BLOCKED_HOST"}), 400

    got = url_fetch.fetch(url)
    if isinstance(got, url_fetch.Refused):
        # The wording is url_fetch's, unchanged: "the site refused the request (HTTP 403)" says the
        # SITE said no. Rewriting it here as "could not read the recipe" would blame the reader for
        # a page it was never given.
        return jsonify({"error": got.detail, "code": got.code, "url": got.url,
                        "status": got.status}), FETCH_STATUS.get(got.code, 502)

    read = url_cascade.read(got.url, got.html)
    if isinstance(read, url_cascade.Failed):
        # 422, not 400: the request was fine and the page was fetched fine — it just carries no
        # recipe this reader can use. Every layer's refusal is returned, not just a flat failure.
        return jsonify({
            "error": read.message,
            "code": "NO_RECIPE_FOUND",
            "url": got.url,
            "refusals": [{"layer": r.layer, "code": r.code, "detail": r.detail} for r in read.refusals],
        }), 422

    cleaned = clean_recipe(read.normalized)
    with orm_session() as s:                         # the REQUEST's session (W2/W3), never a new connection
        uid_index, taken = import_write.db_state(s)
        plan = import_write.plan_recipe(cleaned, uid_index, taken)
        duplicate = duplicate_source_url(s, got.url)
        # NO s.commit() — and nothing above issues a write. plan_recipe is pure; db_state and the
        # duplicate lookup are SELECTs. The session closes without a transaction to roll back.

    if plan["decision"] != "write":
        # Unreachable via the readers shipping today (a URL read carries no uid, so plan_recipe
        # cannot match a twin), kept so a future reader that DOES supply one gets an explicit answer
        # instead of a KeyError on plan["recipe"].
        return jsonify({"error": f"already imported as \u201c{plan['twin']['name']}\u201d",
                        "code": "ALREADY_IMPORTED", "twin": plan["twin"]}), 409

    return jsonify(preview_body(plan, read.provenance, duplicate)), 200


def read_url_or_refusal(url):
    """Shared front half of preview and commit: guard -> fetch -> cascade.

    Returns (read, None) on success or (None, (body, status)) on any refusal, so both routes answer a
    bad URL, a refusing site and an unreadable page with byte-identical wording and status. U5 exists
    to WRITE what U4 showed; two copies of this would be two chances to drift.
    """
    blocked = private_host_refusal(url)
    if blocked:
        return None, ({"error": blocked, "code": "BLOCKED_HOST"}, 400)
    # NO allow_private — U0b's SSRF guard (resolve-then-check + every redirect hop) stays ON. That
    # flag exists for url_fetch's own loopback transport tests and must never be passed from a route.
    got = url_fetch.fetch(url)
    if isinstance(got, url_fetch.Refused):
        return None, ({"error": got.detail, "code": got.code, "url": got.url, "status": got.status},
                      FETCH_STATUS.get(got.code, 502))
    read = url_cascade.read(got.url, got.html)
    if isinstance(read, url_cascade.Failed):
        return None, ({"error": read.message, "code": "NO_RECIPE_FOUND", "url": got.url,
                       "refusals": [{"layer": r.layer, "code": r.code, "detail": r.detail}
                                    for r in read.refusals]}, 422)
    return (read, got), None


def _attach_imported_hero(rid, owner_id, candidates):
    """Fetch the imported page's photo and make it this recipe's hero. NEVER RAISES.

    ⚠️ CALLED AFTER THE COMMIT, AND THAT IS THE WHOLE DESIGN. import_commit's session ends with
    "nothing above committed - a raise leaves NO row", which is right for the recipe and wrong for
    its picture. The image sits on a third-party host, so it can answer 404, time out or be refused
    long after the recipe itself is perfect. Inside that transaction a dead image url would throw
    away a good import. Outside it, the same failure leaves the recipe hero-less, which is the state
    most recipes are already in and which upload_recipe_image already fixes by hand.

    The write below MIRRORS upload_recipe_image rather than only setting recipes.image, and that is
    measured rather than tidy: all 120 existing heroes also carry a cook_photos row with the same
    path (0 exceptions). is_hero derives from recipes.image == p.path across the album, so a hero
    with no album row would be the first in the database to show on the card and be missing from the
    album. "A photo is a photo" holds for a photo that arrived over the wire too.
    """
    def store(path):
        with orm_session() as s:                             # its OWN short transaction, after the recipe's
            next_pos = s.execute(
                select(func.coalesce(func.max(CookPhoto.position), -1) + 1).where(CookPhoto.recipe_id == rid)
            ).scalar_one()
            s.execute(insert(CookPhoto.__table__).values(    # a COOK-LESS album row, as an upload makes
                cook_log_id=None, recipe_id=rid, user_id=owner_id,
                path=path, caption=None, added_at=now_utc(), position=next_pos,
            ))
            s.execute(update(Recipe.__table__).where(Recipe.__table__.c.id == rid).values(image=path))
            s.commit()                                       # DB updated ONLY after the file is on disk (S6)

    return url_image.attach_hero(store, candidates)


@app.route("/api/import/commit", methods=["POST"])
def import_commit():
    """Import a URL into a REAL recipe and hand back its id, so the client can open it in the editor.

    WRITE-THEN-EDIT, following copy_recipe's precedent: the row is created, then the client navigates
    to it. The user corrects the import with the ordinary editor — rows, row menus, drag, step
    editors — instead of a second, parallel editing surface. Cancel is the existing DELETE.

    The recipe is written WITHOUT its reason='original' baseline (commit_plan(snapshot=False)); the
    first save captures it. Everything a fetch or a reader can refuse in preview, this refuses
    identically and BEFORE any row exists — the write is the last thing that happens.
    """
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "paste a recipe URL to import", "code": "BAD_URL"}), 400

    got, refusal = read_url_or_refusal(url)
    if refusal:
        body, status = refusal
        return jsonify(body), status
    read, fetched = got

    cleaned = clean_recipe(read.normalized)
    with orm_session() as s:                         # ONE session: plan, write and flag share a transaction
        uid_index, taken = import_write.db_state(s)
        plan = import_write.plan_recipe(cleaned, uid_index, taken)
        if plan["decision"] != "write":              # unreachable today (a URL read carries no uid)
            return jsonify({"error": f"already imported as \u201c{plan['twin']['name']}\u201d",
                            "code": "ALREADY_IMPORTED", "twin": plan["twin"]}), 409
        # A duplicate source_url is a WARNING and never blocks: re-importing a recipe you already have
        # is the user's call. Read BEFORE the insert, or the row we are about to write matches itself.
        duplicate = duplicate_source_url(s, fetched.url)
        # plan_recipe carries no owner (the batch importer has no request user), but every other
        # create path sets one — and the photo/album routes gate on rec.owner, so an ownerless import
        # would 403 the importer off their own recipe's photos. NB the Paprika path has the same gap;
        # this fixes it HERE, where there is a request user to attribute it to.
        plan["recipe"]["owner"] = current_user.id
        # Provenance rides in with the review flags — one insert loop, no second write path (U2).
        plan["review_flags"] = plan["review_flags"] + [url_cascade.provenance_flag_row(read.provenance)]
        import_write.commit_plan(s, plan, owner_id=current_user.id, snapshot=False)
        rid = plan["recipe"]["id"]
        s.commit()                                   # nothing above committed — a raise leaves NO row
    # The recipe is now durable. ONLY NOW is the network touched again for its photo, so every way
    # that can fail (no image published, a dead url, a host that refuses, an address the guard
    # blocks, bytes that are not an image) costs the picture and never the recipe.
    hero = _attach_imported_hero(rid, current_user.id, cleaned["images"])
    return jsonify({"id": rid, "slug": rid, "duplicate": duplicate,
                    "read_by": read.provenance["layer"], "hero": hero.path or None}), 201


if __name__ == "__main__":
    # Debug defaults OFF. Werkzeug's debugger offers arbitrary code execution in the browser on any
    # unhandled exception, and this file is no longer only run by a developer at a keyboard: the
    # cold-start CI job runs `python app.py` verbatim, so a stranger following README got a debug
    # server. Opt in explicitly for local work: FLASK_DEBUG=1 python3.13 app.py
    # (that is also what restores the auto-reloader).
    _debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    app.run(port=8000, debug=_debug)
