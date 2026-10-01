"""SQLite and Postgres must describe the SAME schema, and a divergence has to be written down.

⚠️ WHY THIS EXISTS. `migrations/*.sql` is the SQLite history and `alembic/` owns the Postgres
schema. The two are written by hand from the same intention with nothing comparing them. The
dual-dialect suite runs the APP against both, so it catches a column that is missing outright and
nothing else. Measured during the pre-push review: five constraints were deleted from the Postgres
side one at a time and the suite stayed green all five times, an index, a CHECK and a column default
among them. A missing CHECK on Postgres means production accepts a row SQLite refuses, and the first
sign is bad data rather than an error.

So this reflects both schemas and diffs them: tables, columns, type affinity, nullability, defaults,
primary keys, indexes, unique constraints, CHECKs, and foreign keys WITH their ON DELETE. Anything
that legitimately differs between the dialects is normalized by a named rule below, with the reason.
The diff is empty by default, so a new divergence has to be written down to pass.

⚠️ SQLITE'S `ON DELETE` DOES NOT COME FROM SQLALCHEMY REFLECTION, AND THAT IS NOT A STYLE CHOICE.
`Inspector.get_foreign_keys` returns `options: {}` for SQLite even when the DDL says
`ON DELETE CASCADE`, which `PRAGMA foreign_key_list` reports correctly. Measured: 21 of 54 tables
"differed" on ON DELETE purely from that gap, against 32 real CASCADEs in the SQLite schema. Reading
the pragma is the difference between this test checking cascade behavior and this test having 21
false positives that someone would eventually silence by dropping the check.
"""
import os
import pathlib
import re
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
# ⚠️ GATED PER TEST, NOT PER MODULE, because the last test in this file compares SQLite against
# SQLite and must run on an ordinary `pytest` with no Postgres anywhere.
needs_pg = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="schema parity needs both dialects — set DATABASE_URL=postgresql+psycopg://… to run",
)

from sqlalchemy import create_engine, inspect, text as sa_text                 # noqa: E402

import migrate as migrate_mod                                                  # noqa: E402

# tables that exist on one side on purpose
TABLE_ALLOWANCES = {
    "schema_migrations": "SQLite's own migration ledger. Alembic owns Postgres and uses "
                         "alembic_version, so neither table is part of the shared schema.",
    "alembic_version":   "Alembic's revision stamp. The SQLite side is tracked by "
                         "schema_migrations instead.",
}

# a column type is compared by AFFINITY, not by the dialect's name for it
TYPE_BUCKETS = {
    "text": {"TEXT", "VARCHAR", "CHAR", "CLOB", "CHARACTER VARYING", "CHARACTER"},
    "int":  {"INTEGER", "INT", "BIGINT", "SMALLINT", "SERIAL", "BIGSERIAL"},
    "real": {"REAL", "DOUBLE PRECISION", "FLOAT", "NUMERIC", "DECIMAL"},
    "blob": {"BLOB", "BYTEA"},
    "bool": {"BOOLEAN"},
}
# measured: the only type pairs that differ at all are REAL <-> DOUBLE PRECISION (4 columns) and
# REAL <-> NUMERIC(n,m) (3 columns). Both are the same affinity. An UNKNOWN type name is compared
# literally on purpose, so introducing one has to be done deliberately.

# the same clock, spelled per dialect
# ⚠️ THE CAST PATTERN MUST NOT MATCH A SPACE. It was `::[a-z_ ]+`, and the space let
# `::text OR flag_kind IS NOT NULL` be eaten whole, which silently truncated three CHECK predicates
# to their first clause and reported them as divergences. Multi-word types are listed instead.
CAST = re.compile(r"::(?:double precision|character varying|timestamp with(?:out)? time zone"
                  r"|[a-z_]+)(?:\(\d+(?:,\s*\d+)?\))?")

DEFAULT_FORMS = {
    "date('now')": "<date-now>",
    "to_char((now() at time zone 'utc'), 'yyyy-mm-dd')": "<date-now>",
    "datetime('now')": "<datetime-now>",
    "to_char((now() at time zone 'utc'), 'yyyy-mm-dd hh24:mi:ss')": "<datetime-now>",
}


def _bucket(t):
    base = re.sub(r"\(.*?\)", "", str(t)).strip().upper()
    for name, members in TYPE_BUCKETS.items():
        if base in members:
            return name
    return base


def _norm_default(raw, is_pk):
    """A column default, reduced to what it MEANS."""
    if raw is None:
        return None
    s = " ".join(str(raw).split()).lower()
    s = CAST.sub("", s)                                      # drop ::text, ::regclass, ::numeric
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    s = " ".join(s.split())
    if is_pk and s.startswith("nextval"):
        # Postgres SERIAL versus SQLite INTEGER PRIMARY KEY AUTOINCREMENT. Same generated key, and
        # SQLite reports no default at all for it.
        return None
    return DEFAULT_FORMS.get(s, s)


def _norm_check(sqltext):
    """A CHECK predicate, reduced so the two dialects' renderings of one rule compare equal.

    Measured differences, all rendering: Postgres writes `x IN (a,b)` as `x = ANY (ARRAY[a,b])`,
    writes `BETWEEN a AND b` as `>= a AND <= b`, lowercases function names, appends `::text` to
    string literals, spells integers in a numeric array as `1::numeric`, and drops parentheses it
    considers redundant.
    """
    s = " ".join((sqltext or "").split()).lower()
    s = CAST.sub("", s)
    # = any (array[a, b]) -> in (a, b)
    s = re.sub(r"=\s*any\s*\(\s*array\[(.*?)\]\s*\)", lambda m: f"in ({m.group(1)})", s)
    # between a and b -> >= a and <= b, keeping the subject
    s = re.sub(r"(\b[\w.]+)\s+between\s+(\S+)\s+and\s+(\S+)",
               lambda m: f"{m.group(1)} >= {m.group(2)} and {m.group(1)} <= {m.group(3)}", s)
    s = re.sub(r"\b(\d+)\.0+\b", r"\1", s)              # 1.0 -> 1
    s = s.replace("(", " ").replace(")", " ")           # parens carry no meaning in these predicates
    s = re.sub(r"\s*,\s*", ",", s)
    return " ".join(s.split())


def _sqlite_ondelete(db):
    """{(table, (cols)): ON DELETE} straight from the pragma, because reflection drops it."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name NOT LIKE 'sqlite_%'"):
        groups = {}
        for r in c.execute(f'PRAGMA foreign_key_list("{t}")'):
            groups.setdefault(r["id"], []).append(r)
        for rows in groups.values():
            rows.sort(key=lambda r: r["seq"])
            cols = tuple(r["from"] for r in rows)
            od = (rows[0]["on_delete"] or "NO ACTION").upper()
            out[(t, cols)] = "NO ACTION" if od == "NO ACTION" else od
    c.close()
    return out


def _sqlite_expression_indexes(db):
    """{table: {index names}} for indexes over an EXPRESSION, read from sqlite_master.

    ⚠️ THE SAME REFLECTION GAP AS `ON DELETE`. SQLAlchemy emits "Skipped unsupported reflection of
    expression-based index" for SQLite and returns nothing, while Postgres reflects the index
    normally. `idx_msc_key` is real in both schemas (`UNIQUE (from_id, IFNULL(to_id,''), source_slug)`
    on SQLite), so comparing reflection against reflection reports a divergence that is not there.
    """
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for name, tbl, sql in c.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        text = sql or ""
        try:
            body = text[text.index("("):text.rindex(")") + 1]
        except ValueError:
            continue
        # a nested "(" anywhere inside the column list means a function call, so an expression index
        if "(" in body[1:]:
            out.setdefault(tbl, set()).add(name)
    c.close()
    return out


def _shape(insp, table, ondelete_from_pragma=None, expr_from_master=None):
    """One canonical description of a table, in whichever dialect `insp` speaks."""
    pk = tuple(insp.get_pk_constraint(table).get("constrained_columns") or ())
    cols = {}
    for c in insp.get_columns(table):
        is_pk = c["name"] in pk
        cols[c["name"]] = {
            "type": _bucket(c["type"]),
            # ⚠️ nullability is not compared on a PRIMARY KEY column. SQLite reflects
            # `INTEGER PRIMARY KEY AUTOINCREMENT` as nullable and Postgres reflects SERIAL as NOT
            # NULL. Neither can hold a NULL. Measured: this one rule accounts for all 26 tables
            # that appeared to disagree on nullability, every one of them on the id column.
            "nullable": None if is_pk else bool(c["nullable"]),
            "default": _norm_default(c.get("default"), is_pk),
        }

    uniques = {tuple(sorted(u["column_names"])) for u in insp.get_unique_constraints(table)}
    plain, expression = set(), set()
    for ix in insp.get_indexes(table):
        names = ix.get("column_names") or []
        if any(n is None for n in names):
            # an expression index. SQLAlchemy reflects it on Postgres and skips it on SQLite, so it
            # is compared by NAME only rather than silently ignored.
            expression.add(ix["name"])
            continue
        key = tuple(sorted(names))
        if ix.get("unique"):
            # ⚠️ Postgres implements a UNIQUE CONSTRAINT as a unique index and reflects it BOTH
            # ways, where SQLite reports only the constraint. Folding them into one set is what
            # makes the two comparable without dropping real unique indexes.
            uniques.add(key)
        else:
            plain.add(key)

    fks = set()
    for f in insp.get_foreign_keys(table):
        cols_t = tuple(f["constrained_columns"])
        od = (f.get("options") or {}).get("ondelete")
        if ondelete_from_pragma is not None:
            od = ondelete_from_pragma.get((table, cols_t), "NO ACTION")
        od = (od or "NO ACTION").upper()
        fks.add((cols_t, f["referred_table"], tuple(f["referred_columns"]), od))

    if expr_from_master is not None:
        expression |= expr_from_master.get(table, set())

    checks = {_norm_check(c.get("sqltext")) for c in insp.get_check_constraints(table)}
    checks.discard("")

    return {"columns": cols, "pk": pk, "indexes": plain, "uniques": uniques,
            "foreign_keys": fks, "checks": checks, "expression_indexes": expression}


@pytest.fixture(scope="module")
def schemas(tmp_path_factory):
    """A fresh SQLite build from migrations/, and the Postgres schema when there is one.

    The Postgres half is built only when DATABASE_URL names one, so the SQLite-only test below runs
    on an ordinary `pytest` instead of erroring on an empty URL."""
    db = tmp_path_factory.mktemp("parity") / "fresh.db"
    migrate_mod.migrate(verbose=False, db=db)
    lite = create_engine(f"sqlite:///{db}", future=True)
    pg = create_engine(DATABASE_URL, future=True) if DATABASE_URL.startswith("postgresql") else None
    try:
        yield db, inspect(lite), (inspect(pg) if pg is not None else None)
    finally:
        lite.dispose()
        if pg is not None:
            pg.dispose()


def _shared(li, pi):
    lt, pt = set(li.get_table_names()), set(pi.get_table_names())
    return sorted((lt & pt) - set(TABLE_ALLOWANCES)), lt, pt


@needs_pg
def test_both_dialects_hold_the_same_tables(schemas):
    _db, li, pi = schemas
    shared, lt, pt = _shared(li, pi)
    only_lite = sorted(lt - pt - set(TABLE_ALLOWANCES))
    only_pg = sorted(pt - lt - set(TABLE_ALLOWANCES))
    assert not only_lite, f"tables only in SQLite: {only_lite}"
    assert not only_pg, f"tables only in Postgres: {only_pg}"
    assert len(shared) >= 50, f"only {len(shared)} shared tables, the comparison is not covering"


FACETS = ["columns", "pk", "indexes", "uniques", "foreign_keys", "checks", "expression_indexes"]


def divergences(facet, db, li, pi):
    """Every disagreement between the two dialects on one facet. Empty means they agree."""
    pragma = _sqlite_ondelete(db)
    exprs = _sqlite_expression_indexes(db)
    shared, _lt, _pt = _shared(li, pi)
    problems = []
    for t in shared:
        a = _shape(li, t, pragma, exprs)[facet]
        b = _shape(pi, t)[facet]
        if a != b:
            if isinstance(a, dict):
                for col in sorted(set(a) | set(b)):
                    if a.get(col) != b.get(col):
                        problems.append(f"{t}.{col}: sqlite={a.get(col)} postgres={b.get(col)}")
            else:
                problems.append(f"{t}: only-sqlite={sorted(set(a) - set(b))} "
                                f"only-postgres={sorted(set(b) - set(a))}")
    return problems


@needs_pg
@pytest.mark.parametrize("facet", FACETS)
def test_the_two_dialects_agree(schemas, facet):
    """One facet at a time, so a failure says WHICH kind of divergence it is."""
    db, li, pi = schemas
    problems = divergences(facet, db, li, pi)
    assert not problems, (
        f"{len(problems)} {facet} divergence(s) between SQLite and Postgres:\n  "
        + "\n  ".join(problems[:40]))


# ---- the self-proving half ----------------------------------------------------------------------
# ⚠️ A PARITY TEST NOBODY HAS BROKEN ON PURPOSE IS A PARITY TEST THAT MIGHT BE COMPARING NOTHING.
# The review that caused this file deleted five constraints from the Postgres side one at a time and
# the whole suite stayed green all five times. So each class of drift is reintroduced here, the
# comparison is asserted to CATCH it, and it is put back. Restoration runs in a finally and is
# verified, because a drift proof that leaks a broken schema would poison every test after it.
DRIFTS = [
    ("a dropped index", "indexes",
     "DROP INDEX idx_recipe_waits_when",
     "CREATE INDEX idx_recipe_waits_when ON recipe_waits(when_kind)"),
    ("a dropped unique constraint", "uniques",
     "ALTER TABLE recipe_waits DROP CONSTRAINT uq_recipe_waits_position",
     "ALTER TABLE recipe_waits ADD CONSTRAINT uq_recipe_waits_position "
     "UNIQUE (recipe_id, position)"),
    ("a dropped CHECK", "checks",
     "ALTER TABLE recipe_waits DROP CONSTRAINT ck_recipe_waits_when_label",
     "ALTER TABLE recipe_waits ADD CONSTRAINT ck_recipe_waits_when_label "
     "CHECK (when_kind <> 'only_if' OR when_label IS NOT NULL)"),
    ("a dropped column default", "columns",
     "ALTER TABLE ingredients ALTER COLUMN source DROP DEFAULT",
     "ALTER TABLE ingredients ALTER COLUMN source SET DEFAULT 'seed'"),
    ("a dropped ON DELETE CASCADE", "foreign_keys",
     "ALTER TABLE import_flags DROP CONSTRAINT import_flags_recipe_id_fkey; "
     "ALTER TABLE import_flags ADD CONSTRAINT import_flags_recipe_id_fkey "
     "FOREIGN KEY (recipe_id) REFERENCES recipes(id)",
     "ALTER TABLE import_flags DROP CONSTRAINT import_flags_recipe_id_fkey; "
     "ALTER TABLE import_flags ADD CONSTRAINT import_flags_recipe_id_fkey "
     "FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE"),
    ("a loosened NOT NULL", "columns",
     "ALTER TABLE recipe_steps ALTER COLUMN heading_level DROP NOT NULL",
     "ALTER TABLE recipe_steps ALTER COLUMN heading_level SET NOT NULL"),
]


@needs_pg
@pytest.mark.parametrize("label,facet,break_sql,restore_sql", DRIFTS,
                         ids=[d[0].replace(" ", "-") for d in DRIFTS])
def test_the_comparison_catches_a_drift_introduced_on_purpose(
        schemas, label, facet, break_sql, restore_sql):
    db, li, _pi = schemas
    engine = create_engine(DATABASE_URL, future=True)
    try:
        assert not divergences(facet, db, li, inspect(engine)), (
            f"{facet} already diverges, so this proof cannot tell its drift from the existing one")
        with engine.begin() as c:
            for stmt in break_sql.split(";"):
                if stmt.strip():
                    c.execute(sa_text(stmt))
        caught = divergences(facet, db, li, inspect(engine))
        assert caught, f"{label} was NOT caught by the {facet} comparison"
    finally:
        with engine.begin() as c:
            for stmt in restore_sql.split(";"):
                if stmt.strip():
                    c.execute(sa_text(stmt))
        left = divergences(facet, db, li, inspect(engine))
        engine.dispose()
    assert not left, f"the {facet} schema was not restored after proving {label}: {left}"


# ---- and the same question asked of the real database -------------------------------------------

@pytest.mark.live_schema
def test_live_s_schema_is_what_the_migrations_build(schemas, tmp_path):
    """A fresh build from migrations/ must describe the same schema as the live database.

    ⚠️ READ-ONLY, through a mode=ro URI, which is the only way the suite may touch live at all. The
    live path comes from the shared guard rather than from this file's own idea of the repo root.

    ⚠️ AND IT IS COMPARED STRUCTURALLY, NOT AS SQL TEXT. Measured: live and a fresh build agree on
    all 114 schema objects, and `ratings` differs in WHITESPACE ONLY, because live's copy of that
    table was rebuilt by scripts/backfill_rescoping.py from a single-line CREATE rather than by
    migration 019's formatted one. Same columns, same types, same NOT NULLs, same CHECK, same
    composite primary key, same ON DELETE CASCADE. A text comparison would fail on that forever and
    teach everyone to ignore this test.
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import corpus_guard

    live = pathlib.Path(corpus_guard.live_db())
    if not live.exists():
        pytest.skip("no live database here, which is the fresh-clone and CI case")

    fresh_db, fresh_insp, _pi = schemas
    # a creator rather than a URL: the repo path contains spaces, and this makes mode=ro explicit
    live_engine = create_engine(
        "sqlite://", future=True,
        creator=lambda: sqlite3.connect(f"file:{live}?mode=ro", uri=True))
    try:
        live_insp = inspect(live_engine)
        live_pragma = _sqlite_ondelete(live)
        live_exprs = _sqlite_expression_indexes(live)
        fresh_pragma = _sqlite_ondelete(fresh_db)
        fresh_exprs = _sqlite_expression_indexes(fresh_db)

        fresh_tables = set(fresh_insp.get_table_names()) - set(TABLE_ALLOWANCES)
        live_tables = set(live_insp.get_table_names()) - set(TABLE_ALLOWANCES)
        assert not fresh_tables - live_tables, \
            f"migrations build tables live does not have: {sorted(fresh_tables - live_tables)}"
        assert not live_tables - fresh_tables, \
            f"live has tables no migration builds: {sorted(live_tables - fresh_tables)}"

        problems = []
        for t in sorted(fresh_tables):
            a = _shape(fresh_insp, t, fresh_pragma, fresh_exprs)
            b = _shape(live_insp, t, live_pragma, live_exprs)
            for facet in FACETS:
                if a[facet] == b[facet]:
                    continue
                if isinstance(a[facet], dict):
                    for col in sorted(set(a[facet]) | set(b[facet])):
                        if a[facet].get(col) != b[facet].get(col):
                            problems.append(f"{t}.{col} ({facet}): migrations={a[facet].get(col)} "
                                            f"live={b[facet].get(col)}")
                else:
                    problems.append(f"{t} ({facet}): only-migrations="
                                    f"{sorted(set(a[facet]) - set(b[facet]))} "
                                    f"only-live={sorted(set(b[facet]) - set(a[facet]))}")
        assert not problems, (
            f"live's schema has drifted from what migrations build, {len(problems)} place(s):\n  "
            + "\n  ".join(problems[:40]))
    finally:
        live_engine.dispose()
