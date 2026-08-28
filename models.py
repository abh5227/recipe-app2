"""models.py — SQLAlchemy model layer (Stage 1a of the SQLite -> Postgres migration).

PURELY ADDITIVE. These models MIRROR the live schema (built by migrations/ + build_db.py) exactly;
NOTHING is wired to them yet. The raw sqlite3 db() path in app.py is untouched and remains the sole
query path until Stage 1b. The engine/session default to the SAME recipes.db the raw path uses, so
when queries do move to the ORM they hit the identical database.

Stage 1 stays on SQLite (this file); Stage 2 swaps the engine to Postgres. Types/defaults mirror the
current SQLite schema so create_all reproduces it: TEXT stays Text; text-date defaults stay literal
datetime('now')/date('now') (NOT converted to real datetime columns) to preserve behavior; the six
INTEGER-PK tables keep AUTOINCREMENT; recipes.uid keeps its PARTIAL UNIQUE index.
"""
import os
from pathlib import Path

from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Index, Integer, Table, Text,
    UniqueConstraint, create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent


class Base(DeclarativeBase):
    pass


# Single-column PKs are NOT NULL (SQLAlchemy's default for primary_key columns). NOTE (Stage 2a): these
# originally carried nullable=True to mirror SQLite's implicit-nullable PK DDL (PRAGMA notnull=0), but a
# Postgres PK is ALWAYS NOT NULL — so the Alembic baseline's re-autogenerate saw a perpetual nullable
# diff. Dropping nullable=True aligns the models with Postgres (and is semantically honest — a PK is never
# null); the live SQLite schema is still built by migrations/*.sql, so this metadata change doesn't touch
# the running SQLite app. Composite PKs were already NOT NULL.
class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    author = Column(Text)
    source_url = Column(Text)
    category = Column(Text)
    servings = Column(Text)
    prep_time = Column(Text)
    cook_time = Column(Text)
    total_time = Column(Text)
    descr = Column(Text)
    notes = Column(Text)
    image = Column(Text)
    created_at = Column(Text)
    source = Column(Text, nullable=False, server_default=text("'seed'"))
    uid = Column(Text)
    hash = Column(Text)
    # Rescoping R1: whose recipe-box this recipe is in (docs/product-vision.md). NULLABLE for now —
    # a fresh build_db has no user to own seed recipes; R2 backfills existing rows to me, and
    # create/copy set it to current_user. Reference FK (no cascade), matching auth-1's created_by/used_by.
    owner = Column(Integer, ForeignKey("users.id"))
    __table_args__ = (
        # partial unique index: uid is unique only when set (imports carry it; app recipes don't).
        # Both dialect kwargs so the partial index renders on SQLite AND Postgres (Stage 2a) — each
        # dialect ignores the other's kwarg; without postgresql_where PG would build a plain unique index.
        Index("idx_recipes_uid", "uid", unique=True,
              sqlite_where=text("uid IS NOT NULL"), postgresql_where=text("uid IS NOT NULL")),
    )


class Ingredient(Base):
    """The ingredient field guide. Hand-authored rows come from seed.py's INGREDIENTS, 36 of them.
    Add-on-save stage 5 will also create rows PROMOTED from the ingredient library, so migration 030
    added the two columns that tell them apart. source mirrors recipes.source exactly, same vocabulary
    and same TEXT NOT NULL DEFAULT 'seed'. It defaults to 'seed' because that is the fail-safe
    direction. Stage 6's delete path refuses a seed row, so a writer that forgets to set 'app' leaves a
    row undeletable rather than leaving the 36 curated rows deletable. library_id is AUDIT PROVENANCE
    and is deliberately NOT a foreign key to library_names, since library ids are not durable across a
    rebuild (7 died in commit 460cae5) and it is expected to dangle. Nothing on a page reads it. Both
    columns are inert until stage 5."""
    __tablename__ = "ingredients"
    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    descr = Column(Text)
    pairs = Column(Text)
    created_at = Column(Text)
    source = Column(Text, nullable=False, server_default=text("'seed'"))   # 'seed' | 'app', as recipes.source
    library_id = Column(Text)                                              # provenance, may dangle, no FK


class Rating(Base):
    __tablename__ = "ratings"
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True)
    rating = Column(Integer, nullable=False)
    rated_on = Column(Text, nullable=False, server_default=text("datetime('now')"))
    # Rescoping R3: whose rating this is. Now part of the COMPOSITE PK (recipe_id, user_id) — one rating
    # per (recipe, user) — so it's NOT NULL. Reference FK to users (no cascade). Existing rows were
    # backfilled to the owner account by scripts/backfill_rescoping.py before this constraint applied.
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True, nullable=False)
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5"),)


class CookLog(Base):
    __tablename__ = "cook_log"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    cooked_on = Column(Text, nullable=False, server_default=text("date('now')"))
    source = Column(Text, nullable=False, server_default=text("'app'"))
    # Rescoping R1: who logged this cook. NULLABLE add only (R2 backfills existing → me; new cooks set
    # current_user). Reference FK (no cascade). No PK change here (cook_log keeps its own id PK).
    user_id = Column(Integer, ForeignKey("users.id"))
    __table_args__ = (
        Index("idx_cook_log_recipe", "recipe_id"),
        {"sqlite_autoincrement": True},
    )


class ImportFlag(Base):
    __tablename__ = "import_flags"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer)
    flag = Column(Text, nullable=False)
    reason = Column(Text)
    created_at = Column(Text, nullable=False, server_default=text("datetime('now')"))
    __table_args__ = (
        Index("idx_import_flags_recipe", "recipe_id"),
        {"sqlite_autoincrement": True},
    )


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    __table_args__ = ({"sqlite_autoincrement": True},)


class IngredientSeason(Base):
    __tablename__ = "ingredient_seasons"
    ingredient_id = Column(Text, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True)
    month = Column(Integer, primary_key=True)
    __table_args__ = (
        CheckConstraint("month BETWEEN 1 AND 12"),
        Index("idx_seasons_month", "month"),
    )


class IngredientRegion(Base):
    __tablename__ = "ingredient_regions"
    ingredient_id = Column(Text, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True)
    region_id = Column(Integer, ForeignKey("regions.id"), primary_key=True)
    position = Column(Integer, nullable=False)
    __table_args__ = (Index("idx_iregions_region", "region_id"),)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    is_heading = Column(Integer, nullable=False, server_default=text("0"))
    qty = Column(Text)
    ingredient_id = Column(Text, ForeignKey("ingredients.id"))
    label = Column(Text)
    note = Column(Text)
    raw_text = Column(Text)
    grams = Column(Float)   # Float = float8/DOUBLE PRECISION on PG (sa.REAL = float4 would truncate)
    secondary_measure = Column(Text)
    quantity = Column(Text)
    unit = Column(Text)
    __table_args__ = (
        Index("idx_ri_ingredient", "ingredient_id"),
        Index("idx_ri_recipe", "recipe_id"),
        {"sqlite_autoincrement": True},
    )


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    is_heading = Column(Integer, nullable=False, server_default=text("0"))
    # DB column is "text"; the attribute is renamed to avoid shadowing sqlalchemy.text.
    body = Column("text", Text, nullable=False)
    __table_args__ = (
        Index("idx_rs_recipe", "recipe_id"),
        {"sqlite_autoincrement": True},
    )


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    filename = Column(Text, primary_key=True)
    applied_at = Column(Text, nullable=False, server_default=text("datetime('now')"))


# ---- auth (auth-1: data layer only; Flask-Login + the JSON endpoints land in auth-2) -------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(Text, nullable=False, unique=True)                    # stored lowercased
    password_hash = Column(Text, nullable=False)
    display_name = Column(Text)
    # int-boolean (0/1), matching is_heading/convert_to_grams — NOT a Boolean column. Gates invite
    # GENERATION only (a later stage), not a general superpower.
    is_admin = Column(Integer, nullable=False, server_default=text("0"))
    # created_at is set in code (now_utc()) — NO DB default, so there's no SQLite datetime('now') vs
    # Postgres to_char default expression to reconcile (the divergence the 2a baseline had to hand-fix).
    created_at = Column(Text, nullable=False)
    __table_args__ = ({"sqlite_autoincrement": True},)

    # Flask-Login interface (auth-2). Provided directly rather than via flask_login.UserMixin so
    # models.py stays free of the web-framework import — this data layer is shared by build_db/alembic/
    # import, none of which use Flask-Login. A loaded User is always an authenticated, active, non-anon
    # account (there is no disabled/soft-delete flag yet); get_id returns the PK as the str Flask-Login
    # stores in the signed session cookie.
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def get_id(self):
        return str(self.id)


class Invite(Base):
    __tablename__ = "invites"
    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False, unique=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)   # reference FK, no cascade
    created_at = Column(Text, nullable=False)                              # set in code via now_utc()
    used_by = Column(Integer, ForeignKey("users.id"))                      # NULL until consumed (single-use)
    used_at = Column(Text)
    expires_at = Column(Text)                                              # present now, unused until later
    __table_args__ = ({"sqlite_autoincrement": True},)


# ---- social (sub-stage 1: the friend graph; docs/product-vision.md build plan) ------------------
class Friendship(Base):
    """A mutual friendship stored as ONE row (requester -> addressee); "are A and B friends" queries BOTH
    directions. Composite PK (requester_id, addressee_id) blocks a same-direction duplicate; the
    reverse-duplicate (B->A while A->B pending) is resolved by auto-accept in the request endpoint. status
    is a text-IN CHECK (the ratings CHECK idiom); reference FKs -> users(id) with no ondelete (matching
    owner/user_id/created_by). created_at/accepted_at set in code via now_utc() (no DB default). Queried
    with explicit select() — no relationship() (house style). Additive: nothing reads it yet."""
    __tablename__ = "friendships"
    requester_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    addressee_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    status = Column(Text, nullable=False)                                  # 'pending' | 'accepted'
    created_at = Column(Text, nullable=False)                              # set in code via now_utc()
    accepted_at = Column(Text)                                             # NULL until accepted
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted')"),
        CheckConstraint("requester_id <> addressee_id"),                   # no self-friend
    )


class SharedPost(Base):
    """A deliberate share (sub-stage 2a) — a first-class feed post. References WHAT was shared via
    SEPARATE nullable FK columns (cook_log_id / recipe_id) with ON DELETE CASCADE, so a deleted
    cook/recipe cascades the post (no orphans) — the integrity need that ruled out a polymorphic column
    (which can't cascade). The XOR CheckConstraint enforces exactly one target, so post_type is DERIVED
    (cook_log_id -> 'cook', recipe_id -> 'recipe'), never stored. Surrogate id PK (repeat shares allowed,
    no dedup); created_at = now_utc() is share-time = feed-time. Queried with explicit select() — no
    relationship() (house style). Additive: nothing reads it until the feed endpoint."""
    __tablename__ = "shared_posts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)             # the sharer
    cook_log_id = Column(Integer, ForeignKey("cook_log.id", ondelete="CASCADE"))  # set for a 'cook' post
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"))        # set for a 'recipe' post
    caption = Column(Text)                                                        # optional (<=280 chars)
    created_at = Column(Text, nullable=False)                                     # now_utc(): share-time
    __table_args__ = (
        CheckConstraint("(cook_log_id IS NOT NULL) <> (recipe_id IS NOT NULL)"),  # exactly one target
        {"sqlite_autoincrement": True},
    )


class Comment(Base):
    """A comment on a feed post — the CONVERSATION (docs/product-vision.md: comments YES, likes/reactions
    NEVER, no count-as-metric, no notifications). post_id -> shared_posts(id) ON DELETE CASCADE is the
    integrity chain: a shared_post already cascades when its cook/recipe is deleted, so recipe/cook ->
    post -> comments cleans up the whole thread (and unshare deletes a post's comments). author_id ->
    users(id) is a reference FK (no ondelete), matching shared_posts.user_id. Surrogate id PK; created_at
    = now_utc(); idx_comments_post backs the feed's batched WHERE post_id IN (...) load. Queried with
    explicit select() — no relationship() (house style). Additive: nothing reads it until the feed
    serializer embeds comments."""
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("shared_posts.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)           # reference FK, no cascade
    body = Column(Text, nullable=False)                                           # <=300 chars, app-enforced
    created_at = Column(Text, nullable=False)                                     # now_utc()
    __table_args__ = (
        Index("idx_comments_post", "post_id"),
        {"sqlite_autoincrement": True},
    )


class RecipeQueue(Base):
    """A per-user want-to-make queue (want-to-make stage 1 schema, migration 024; the API is stage 2).
    One row = "user_id wants to make recipe_id" — the per-user planning state promoted out of the old
    GLOBAL "To Make" category tag (backfilled by scripts/backfill_recipe_queue.py). user_id -> users(id)
    is a reference FK (no ondelete, matching shared_posts.user_id); recipe_id -> recipes(id) ON DELETE
    CASCADE so a deleted recipe leaves no orphan queue row (the shared_posts.recipe_id idiom). recipe_id
    is Text to match recipes.id (Text). UNIQUE(user_id, recipe_id): a recipe is in your queue once or not
    at all — an add is an idempotent on_conflict_do_nothing, never a duplicate. Surrogate id PK (the
    UNIQUE carries the dedup; queue_id is exposed for a future per-entry reorder/notes consumer). added_at
    = now_utc(). Queried with explicit select() — no relationship() (house style)."""
    __tablename__ = "recipe_queue"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)             # whose queue this is in
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)  # the wanted recipe
    added_at = Column(Text, nullable=False)                                       # now_utc(): when queued
    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id"),   # in your queue once, or not at all
        {"sqlite_autoincrement": True},
    )


class CookPhoto(Base):
    """A photo in a recipe's per-cook album (Stage 4, build 1 schema, migration 025; the save_cook_photo
    helper + attach/promote/caption endpoints are build 2). One row = "this photo belongs to cook_log C
    (recipe R), added by user U" — several photos per cook, accumulating into a per-recipe album BESIDE the
    single hero (recipes.image is untouched). cook_log_id -> cook_log(id) ON DELETE CASCADE so undoing a
    cook / deleting a recipe (which cascades cook_log) leaves no orphan photo (the shared_posts.cook_log_id
    idiom). recipe_id -> recipes(id) ON DELETE CASCADE is DENORMALIZED (the cook already carries the recipe),
    carried so the "all photos for this recipe" album query is a single indexed WHERE recipe_id = ? instead
    of a join through cook_log; its own cascade keeps it consistent. recipe_id is Text to match recipes.id
    (Text). user_id -> users(id) is a reference FK (no ondelete, matching recipe_queue.user_id) — the interim
    multi-user-shaped rule: present from day one though single-user now, set to current_user at insert. path
    is the stored image path (build 2 fills it via save_cook_photo); caption is optional (<=100 chars,
    app-enforced later). Surrogate id PK (a photo is a first-class row; no natural key). added_at = now_utc().
    Queried with explicit select() — no relationship() (house style)."""
    __tablename__ = "cook_photos"
    id = Column(Integer, primary_key=True)
    cook_log_id = Column(Integer, ForeignKey("cook_log.id", ondelete="CASCADE"))  # nullable: standalone album photo (2a)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)        # denormalized
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)             # who added it (no cascade)
    path = Column(Text, nullable=False)                                           # stored image path (build 2)
    caption = Column(Text)                                                        # optional (<=100 chars)
    added_at = Column(Text, nullable=False)                                       # now_utc(): when added
    position = Column(Integer)          # stored album order (3d-i, migration 027); nullable until seeded/set on insert
    __table_args__ = (
        Index("idx_cook_photos_recipe", "recipe_id"),      # per-recipe album query
        Index("idx_cook_photos_cook_log", "cook_log_id"),  # per-cook lookup
        Index("idx_cook_photos_recipe_position", "recipe_id", "position"),  # per-recipe album ORDER BY position (3d-i)
        {"sqlite_autoincrement": True},
    )


class RecipeSnapshot(Base):
    """A versioned JSON-blob snapshot of a recipe's editable CONTENT (change-tracking stage 1, migration
    028). Captured when a cook is logged (reason='cook'; a manual 'save a version' with reason='manual' is
    stage 2). The Cooking Journal's foundation (HYBRID): snapshots are the STORED TRUTH; diffs are DERIVED
    from consecutive snapshots later (stage 3) and materialized for note-linkage later (stage 4). Stage 1
    only WRITES snapshots — nothing reads them yet. cook_log_id -> cook_log ON DELETE CASCADE (undo a cook
    -> its snapshot goes; NULL for a manual snapshot); recipe_id -> recipes ON DELETE CASCADE. user_id is
    the actor (reference FK, no cascade). content = serialize_recipe_content()'s JSON. created_at = now_utc()
    (a real UTC timestamp; cook_log carries only a date). Queried with explicit select() — no relationship()."""
    __tablename__ = "recipe_snapshots"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Text, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)   # TEXT = recipes.id
    cook_log_id = Column(Integer, ForeignKey("cook_log.id", ondelete="CASCADE"))              # the cook (NULL for manual, stage 2)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)                         # who triggered it (no cascade)
    reason = Column(Text, nullable=False)                                                     # 'cook' | 'manual'
    content = Column(Text, nullable=False)                                                    # the JSON-blob recipe content
    created_at = Column(Text, nullable=False)                                                 # now_utc(): a real UTC timestamp
    __table_args__ = (
        Index("idx_recipe_snapshots_recipe", "recipe_id", "created_at"),   # per-recipe history (stage-3 diff)
        Index("idx_recipe_snapshots_cook_log", "cook_log_id"),             # the cook <-> snapshot link
        {"sqlite_autoincrement": True},
    )


class LibraryName(Base):
    """The ingredient library's id -> canonical-name lookup (add-on-save stage 1, migration 029).

    It exists so the save path can later create an `ingredients` row from a library link without
    opening join.db (894 MB) or sources.db (5.18 GB), neither of which is ever present on a server.
    TWO COLUMNS: an earlier draft carried a `slug` column and an index for the reverse
    slug -> library_id lookup that step-link promotion needed, step-link promotion is dropped, and the
    column went with it (624 KB rather than 1,044 KB on the current 10,527-row library).
    library_id is the library row's own id, which is a Wikidata Q-id 61.1% of the time, an Open Food
    Facts id like 'en:egg-pasta' 38.4% of the time, and an authored slug or wiktextract key for the
    rest, so one Text PK covers every shape. INERT: nothing reads this table, the loader is stage 3,
    and it stays EMPTY on a fresh clone, in CI, and on Postgres, which is what keeps the later save
    gate dormant. Queried with explicit select(), no relationship() (house style)."""
    __tablename__ = "library_names"
    library_id = Column(Text, primary_key=True)   # 'Q1063736', 'en:egg-pasta', 'salt'
    canonical = Column(Text, nullable=False)      # its display name, the later source of ingredients.name


# ingredient_weights has NO primary key in the live schema. ORM-mapped classes require a PK, so this
# table is defined as a Core Table (part of the same metadata) — faithful in create_all (no synthetic
# PK added, no structure change). It can be given an imperative ORM mapping in Stage 1b if it's queried.
ingredient_weights = Table(
    "ingredient_weights", Base.metadata,
    Column("lookup_key", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("grams_per_ml", Float, nullable=False),   # float8 on PG for full density precision
    Column("convert_to_grams", Integer, nullable=False, server_default=text("1")),
    Index("idx_iw_lookup", "lookup_key"),
)


# ---- engine / session ---------------------------------------------------------------------------
# Default to the SAME recipes.db the raw sqlite3 path uses, so the ORM (once wired in Stage 1b) reads
# and writes the identical database. Stage 2 sets DATABASE_URL to a postgresql+psycopg:// URL.
# NOTE: creating the engine/sessionmaker does NOT open a connection; importing this module is
# side-effect-free (nothing here touches the DB), so it cannot change app behavior in Stage 1a.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'recipes.db'}")
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)
