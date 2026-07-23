"""Alembic environment (Stage 2a).

target_metadata is models.py's metadata — the same 15-table mirror the app queries through
(empty-diff-verified against the live SQLite schema in Stage 1a). The URL comes from the
DATABASE_URL env var, defaulting to the app's SQLite path so nothing else breaks; Stage 2 runs
Alembic against the Postgres container via DATABASE_URL=postgresql+psycopg://...
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the project root importable so `import models` works when alembic runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import models  # noqa: E402  (path set up above)

config = context.config

# The DB Alembic operates on. Default to the app's SQLite file (harmless); Stage 2 overrides with
# DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/recipe.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{models.BASE_DIR / 'recipes.db'}")
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # Structural gate only. models.py keeps SQLite-literal date defaults (datetime('now')/date('now'))
        # — it's still the live SQLite app's mirror — while the PG baseline renders them PG-native
        # (to_char(now() AT TIME ZONE 'UTC', …)). That is an INTENDED cross-dialect divergence (a 2b-style
        # dialect residual), not a structural miss, so server-default text isn't compared here.
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=False,   # structural gate — see run_migrations_offline for why
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
