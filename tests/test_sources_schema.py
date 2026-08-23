"""Schema tests for sources.db.

Guards the decisions that are expensive to reverse later:
  - per-source tables, never a shared one with a source column;
  - a per-label child table, never a blob;
  - license and attribution have a column and are filled BEFORE data lands;
  - the Wikidata query is ordered and is not English-only;
  - recipes.db is not touched by any of it.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import build_sources_db as bsd

ENTRY_PREFIXES = [p for p, _ in bsd.ENTRY_SOURCES]
CONTRACT = {"pk", "fetch_id", "entry_id", "name", "lang", "xrefs", "raw"}
LABEL_CONTRACT = {"pk", "entry_pk", "lang", "text", "kind", "is_preferred", "source_field"}


@pytest.fixture
def db(tmp_path):
    """A freshly built sources.db in a temp dir. Never the real file."""
    path = bsd.build(tmp_path / "sources.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ── the store exists and is shaped as decided ───────────────────────────────────────────

def test_infrastructure_tables_exist(db):
    assert {"source_catalogue", "source_fetch", "source_payload"} <= tables(db)


def test_one_entry_table_per_source(db):
    have = tables(db)
    for p in ENTRY_PREFIXES:
        assert f"{p}_entry" in have, f"missing {p}_entry"
        assert f"{p}_label" in have, f"missing {p}_label"


def test_ingest_datasets_and_their_sources(db):
    """Datasets that share a schema share a table, told apart by source_fetch.dataset."""
    rows = db.execute(
        "SELECT source, dataset FROM source_catalogue WHERE status='ingest'").fetchall()
    assert len(rows) == 9
    assert len({r["source"] for r in rows}) == 6
    assert sorted(r["dataset"] for r in rows if r["source"] == "usda_fdc") == [
        "foundation_foods", "sr_legacy"]
    assert sorted(r["dataset"] for r in rows if r["source"] == "open_food_facts") == [
        "ingredients_taxonomy_json", "ingredients_taxonomy_txt"]
    assert sorted(r["dataset"] for r in rows if r["source"] == "wiktextract") == [
        "enwiktionary_senses", "zhwiktionary_senses"]
    for shared in ("usda_fdc", "off_taxonomy", "wiktextract"):
        assert f"{shared}_entry" in tables(db)
    for never in ("sr_legacy_entry", "foundation_foods_entry", "zhwiktionary_senses_entry"):
        assert never not in tables(db)


def test_every_ingest_source_has_tables_and_no_declined_one_does(db):
    have = tables(db)
    for r in db.execute("SELECT DISTINCT source, status FROM source_catalogue"):
        pass
    ingest = {r[0] for r in db.execute(
        "SELECT DISTINCT source FROM source_catalogue WHERE status='ingest'")}
    declined_only = {r[0] for r in db.execute(
        "SELECT DISTINCT source FROM source_catalogue WHERE status='declined'")} - ingest
    for src in declined_only:
        assert f"{src}_entry" not in have, f"{src} is declined but still has tables"


def test_no_shared_entry_table_with_a_source_column(db):
    """The structural rule: a shared table is a merge waiting to happen."""
    for t in tables(db):
        if t.endswith("_entry") or t.endswith("_label"):
            assert "source" not in cols(db, t), (
                f"{t} carries a source column, which makes it a shared table in disguise"
            )


# ── the column contract ─────────────────────────────────────────────────────────────────

def test_entry_tables_share_the_contract(db):
    for p in ENTRY_PREFIXES:
        assert cols(db, f"{p}_entry") == CONTRACT, f"{p}_entry breaks the contract"


def test_label_tables_share_the_contract(db):
    for p in ENTRY_PREFIXES:
        assert cols(db, f"{p}_label") == LABEL_CONTRACT, f"{p}_label breaks the contract"


def test_labels_are_rows_not_a_blob(db):
    """A blob puts 40 labels somewhere you cannot filter."""
    for p in ENTRY_PREFIXES:
        c = cols(db, f"{p}_label")
        assert "lang" in c and "text" in c
        info = {r["name"]: r["type"] for r in db.execute(f"PRAGMA table_info({p}_label)")}
        assert info["text"].upper() == "TEXT"
        assert "BLOB" not in {v.upper() for v in info.values()}


def test_raw_record_is_kept_on_every_entry_table(db):
    for p in ENTRY_PREFIXES:
        assert "raw" in cols(db, f"{p}_entry")


# ── the King Arthur guard ───────────────────────────────────────────────────────────────

def test_license_and_attribution_have_a_column_and_are_filled(db):
    """The precedent this schema exists to avoid: attribution with nowhere to go."""
    for t in ("source_catalogue", "source_fetch"):
        assert {"license", "attribution"} <= cols(db, t)
    rows = db.execute("SELECT source, dataset, license, attribution FROM source_catalogue").fetchall()
    assert rows, "catalogue is empty, so attribution landed nowhere"
    for r in rows:
        assert r["license"].strip(), f"{r['source']}/{r['dataset']} has no license"
        assert r["attribution"].strip(), f"{r['source']}/{r['dataset']} has no attribution"


def test_every_catalogued_dataset_names_a_specific_dataset(db):
    """Naming the source is not enough."""
    for r in db.execute("SELECT source, dataset, url FROM source_catalogue"):
        assert r["dataset"] and r["dataset"] != r["source"]
        assert r["url"].startswith("http")


# ── the queries ─────────────────────────────────────────────────────────────────────────

def test_wikidata_query_is_ordered(db):
    """LIMIT/OFFSET without ORDER BY is non-deterministic and lost 29% of labels once."""
    q = db.execute(
        "SELECT query_text FROM source_catalogue WHERE source='wikidata'"
    ).fetchone()["query_text"]
    assert "ORDER BY" in q, "an unordered key set is the 29% bug"
    if "LIMIT" in q:
        assert q.index("ORDER BY") < q.index("LIMIT")


def test_wikidata_query_is_not_english_only(db):
    q = db.execute(
        "SELECT query_text FROM source_catalogue WHERE source='wikidata'"
    ).fetchone()["query_text"]
    assert "LANG(" not in q, "the item query must not filter by language at all"

    # The all-languages requirement moved WITH the design: labels now come from
    # wbgetentities rather than from the SPARQL, so the guard follows them there.
    # wbgetentities returns every language unless a `languages` parameter narrows it.
    src = (REPO / "fetch_sources.py").read_text()
    assert "labels|aliases|descriptions|claims" in src, "labels AND aliases, both"
    assert '"languages"' not in src, "a languages parameter would narrow the fetch to a subset"


def test_agrovoc_query_is_limited_to_the_licensed_languages(db):
    r = db.execute(
        "SELECT query_text, notes, license FROM source_catalogue WHERE source='agrovoc'"
    ).fetchone()
    for lg in ("en", "fr", "es", "ar", "ru", "zh"):
        assert f'"{lg}"' in r["query_text"], f"{lg} is licensed and must be fetched"
    for lg in ("de", "it", "ja", "hi"):
        assert f'"{lg}"' not in r["query_text"], f"{lg} is NOT licensed and must not be fetched"
    # The license covers SIX languages, so the record must name them AND say plainly
    # that English-only is a narrower choice rather than the obligation.
    assert "en, fr, es, ar, ru, zh" in r["license"]
    for lang in ("English", "French", "Spanish", "Arabic", "Russian", "Chinese"):
        assert lang in r["notes"], f"{lang} is licensed and must be named"
    assert "36" in r["notes"], "the uncovered remainder must be stated"
    assert "NARROWER CHOICE" in r["notes"].upper(), (
        "the earlier English-only run was a choice rather than the license obligation, "
        "and the record has to keep saying which is which"
    )


def test_paged_queries_are_ordered(db):
    for r in db.execute("SELECT source, query_text FROM source_catalogue WHERE query_text IS NOT NULL"):
        if "LIMIT" in r["query_text"]:
            assert "ORDER BY" in r["query_text"], f"{r['source']} pages without an order"


# ── referential integrity ───────────────────────────────────────────────────────────────

def test_entry_requires_a_real_fetch(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO wikidata_entry (fetch_id, entry_id, name, raw) VALUES (?,?,?,?)",
            (999, "Q1", "x", "{}"),
        )


def test_payload_requires_a_real_fetch(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO source_payload "
            "(fetch_id, media_type, compression, blob, bytes_stored, sha256_stored) "
            "VALUES (?,?,?,?,?,?)",
            (999, "application/zip", "zip", b"x", 1, "abc"),
        )


def test_fetch_requires_a_catalogued_dataset(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO source_fetch "
            "(source, dataset, url, license, attribution, fetched_at, bytes, sha256, crawl_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("nope", "nope", "https://x", "CC0", "x", "2026-08-23T00:00:00Z", 1, "abc", "c1"),
        )


# ── the query the child table exists for ────────────────────────────────────────────────

def test_native_label_without_english_is_queryable(db):
    """The gochugaru shape, which a blob could not answer."""
    db.execute(
        "INSERT INTO source_fetch "
        "(source, dataset, url, license, attribution, fetched_at, bytes, sha256"
        ", crawl_id) VALUES ('wikidata','food_items_q2095','https://query.wikidata.org/sparql',"
        "'CC0-1.0','Wikidata contributors','2026-08-23T00:00:00Z',1,'abc','c1')"
    )
    fid = db.execute("SELECT id FROM source_fetch").fetchone()[0]
    for eid, name in (("Q1072946", "고춧가루"), ("Q194632", "guanciale")):
        db.execute(
            "INSERT INTO wikidata_entry (fetch_id, entry_id, name, lang, raw) VALUES (?,?,?,?,?)",
            (fid, eid, name, "ko" if eid == "Q1072946" else "en", "{}"),
        )
    ko = db.execute("SELECT pk FROM wikidata_entry WHERE entry_id='Q1072946'").fetchone()[0]
    en = db.execute("SELECT pk FROM wikidata_entry WHERE entry_id='Q194632'").fetchone()[0]
    db.execute("INSERT INTO wikidata_label (entry_pk, lang, text, kind) VALUES (?,?,?,?)",
               (ko, "ko", "고춧가루", "label"))
    db.execute("INSERT INTO wikidata_label (entry_pk, lang, text, kind) VALUES (?,?,?,?)",
               (en, "en", "guanciale", "label"))
    db.execute("INSERT INTO wikidata_label (entry_pk, lang, text, kind) VALUES (?,?,?,?)",
               (en, "it", "guanciale", "label"))

    rows = db.execute("""
        SELECT e.entry_id FROM wikidata_entry e
        WHERE     EXISTS (SELECT 1 FROM wikidata_label l WHERE l.entry_pk=e.pk AND l.lang <> 'en')
          AND NOT EXISTS (SELECT 1 FROM wikidata_label l WHERE l.entry_pk=e.pk AND l.lang =  'en')
    """).fetchall()
    assert [r["entry_id"] for r in rows] == ["Q1072946"]


def test_label_kind_is_not_normalised(db):
    """Normalising the source's own word for a label IS merging."""
    kinds = ("label", "alias", "prefLabel", "altLabel", "hasExactSynonym", "translation")
    db.execute(
        "INSERT INTO source_fetch "
        "(source, dataset, url, license, attribution, fetched_at, bytes, sha256"
        ", crawl_id) VALUES ('agrovoc','sparql_licensed_six','https://agrovoc.fao.org/sparql',"
        "'CC-BY-4.0','FAO','2026-08-23T00:00:00Z',1,'abc','c1')"
    )
    fid = db.execute("SELECT id FROM source_fetch").fetchone()[0]
    db.execute("INSERT INTO agrovoc_entry (fetch_id, entry_id, name, raw) VALUES (?,?,?,?)",
               (fid, "c_1", "x", "[]"))
    pk = db.execute("SELECT pk FROM agrovoc_entry").fetchone()[0]
    for k in kinds:
        db.execute("INSERT INTO agrovoc_label (entry_pk, text, kind) VALUES (?,?,?)", (pk, "t", k))
    got = {r[0] for r in db.execute("SELECT DISTINCT kind FROM agrovoc_label")}
    assert got == set(kinds), "a CHECK constraint would force normalisation here"


# ── blast radius ────────────────────────────────────────────────────────────────────────

def test_build_does_not_touch_recipes_db(tmp_path):
    real = REPO / "recipes.db"
    before = real.stat().st_mtime_ns if real.exists() else None
    bsd.build(tmp_path / "isolated.db")
    after = real.stat().st_mtime_ns if real.exists() else None
    assert before == after, "building sources.db modified recipes.db"


def test_module_imports_nothing_that_opens_recipes_db():
    """sources.db is its own world: no seed, no migrate, no app.

    Checked against the AST rather than the raw text, so the docstring is free to NAME
    recipes.db in order to say it never touches it. A substring scan cannot tell prose
    from code, and the first version of this test failed on its own documentation.
    """
    import ast
    tree = ast.parse((REPO / "build_sources_db.py").read_text())
    banned = {"app", "seed", "migrate", "models", "build_db"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, f"imports {a.name}"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned, f"imports from {node.module}"

    # No string CONSTANT names recipes.db. The module docstring is exempt by construction,
    # since ast.get_docstring pulls it out of the body before we walk the rest.
    body = tree.body[1:] if ast.get_docstring(tree) else tree.body
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                assert "recipes.db" not in sub.value, "a string constant names recipes.db"


def test_default_db_path_is_read_at_call_time(tmp_path, monkeypatch):
    """A frozen-at-import path is how the ORM silently hit the real recipes.db in CI."""
    target = tmp_path / "redirected.db"
    monkeypatch.setattr(bsd, "DB", target)
    bsd.build()
    assert target.exists()
