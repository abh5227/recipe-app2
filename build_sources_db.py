#!/usr/bin/env python3
"""build_sources_db.py — create sources.db, the raw vocabulary store.

WHAT THIS IS
------------
Six public food vocabularies, each ingested WHOLE and UNMODIFIED into its own tables,
labelled with where it came from, its version and its fetch date. No reconciliation, no
merging, no normalisation. Raw storage is what makes a later mistake recoverable and
re-runnable without re-fetching.

The catalogue is the library. The 298 recipes and their 892 head terms are a test set,
not a scope. A stranger importing a Peruvian or Ethiopian recipe has to find their
ingredients already known, and that coverage comes from the ingested vocabulary rather
than from hand-authored entries. A term resolving to an entry with aliases is a working
link with a thin panel, and that is the baseline for everyone.

This script owns sources.db and nothing else. It does not touch recipes.db, migrations/
or Alembic, and migrate.py never sees this file.

WHY THE TABLES ARE SEPARATE, AND WHY THAT IS A LICENCE DECISION
---------------------------------------------------------------
⚠️ DO NOT CONSOLIDATE THESE TABLES WITHOUT READING THIS.

Whole, unmodified, source-labelled tables sitting side by side are a COLLECTIVE DATABASE
under ODbL, explicitly NOT a Derivative Database. The share-alike obligation attaches to a
merged artefact, and only on distribution. Merge the tables and the resulting artefact is
a Derivative, at which point ODbL share-alike attaches to it, and the CC BY-SA sources
(Wiktionary via wiktextract) bring their own share-alike alongside it.

So the separation is not tidiness. It is the thing keeping the obligation off the product.

A shared table with a `source` column would be equally a Collective Database in law, and
it is rejected anyway: its columns would immediately be reconciled to fit all six, and
that reconciliation IS the merge. Separate tables make the independence structural rather
than a comment somebody can ignore.

THE CAUTIONARY PRECEDENT, WHICH THIS SCHEMA EXISTS TO AVOID REPEATING
---------------------------------------------------------------------
build_db.py::seed_weights loads the King Arthur chart with:

    reader = csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#"))

That filter discards this line, verbatim, at read time:

    # Source: King Arthur Baking Ingredient Weight Chart
    # (kingarthurbaking.com/learn/ingredient-weight-chart). Values are factual weights;
    # this is a curated subset for the recipe-app volume-to-weight converter.

Attribution, URL and the curated-subset caveat, all three, reaching nothing. And the
destination table (migrations/008_ingredient_weights.sql) has four columns, none of which
could have held any of it even if the filter were removed. The loss is structural.

Hence source_catalogue below: licence and attribution get a column, and they are written
BEFORE any data lands, not alongside it and not after.

THE PER-LABEL CHILD TABLE
-------------------------
One Wikidata item carries labels in 40 languages. Storing them as a blob puts 40 labels
somewhere you cannot filter. They get a child table so this is a query:

    -- every item the source knows in some language but not in English
    SELECT e.entry_id, e.name
    FROM wikidata_entry e
    WHERE     EXISTS (SELECT 1 FROM wikidata_label l
                       WHERE l.entry_pk = e.pk AND l.lang <> 'en')
      AND NOT EXISTS (SELECT 1 FROM wikidata_label l
                       WHERE l.entry_pk = e.pk AND l.lang = 'en');

That query is the shape of the gochugaru finding: Q1072946 is reachable through the
Korean label and its English label is the merged generic "chili powder".

Run it with:  python3 build_sources_db.py
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "sources.db"

# ── The six sources, and the SPECIFIC dataset in each. Naming the source is not enough.
#    Licence and attribution are recorded VERBATIM. Anything marked ⚠ is load-bearing.
DATASETS = [
    {
        "source": "wikidata",
        "dataset": "food_items_q2095",
        "url": "https://query.wikidata.org/sparql",
        # ⚠ ORDER BY IS MANDATORY. LIMIT/OFFSET paging without a total order is
        #   non-deterministic and silently lost 29% of the labels on a previous attempt.
        # ⚠ ALL LANGUAGES, not English. Returns one row per label, which is exactly the
        #   shape of wikidata_label. gochugaru is reachable ONLY via its Korean label.
        "query_text": (
            "SELECT ?item ?text ?lang ?kind WHERE {\n"
            "  ?item wdt:P279* wd:Q2095 .\n"
            "  { ?item rdfs:label ?text .   BIND(\"label\" AS ?kind) }\n"
            "  UNION\n"
            "  { ?item skos:altLabel ?text . BIND(\"alias\" AS ?kind) }\n"
            "  BIND(LANG(?text) AS ?lang)\n"
            "}\n"
            "ORDER BY ?item ?kind ?lang ?text\n"
            "LIMIT {limit} OFFSET {offset}"
        ),
        "licence": "CC0-1.0",
        "attribution": "Wikidata contributors. Available under CC0 1.0 Universal Public Domain Dedication.",
        "notes": "Food items are subclasses of Q2095 (food), transitively via P279*. "
                 "Measured 28,632 distinct items on 23 Aug 2026. An earlier count of ~34,900 "
                 "counted LABELS, not distinct items, and was wrong.",
    },
    {
        "source": "open_food_facts",
        "dataset": "ingredients_taxonomy",
        "url": "https://static.openfoodfacts.org/data/taxonomies/ingredients.json",
        "query_text": None,
        "licence": "ODbL-1.0",
        "attribution": "Open Food Facts contributors. Database licensed under the Open Database "
                       "License (ODbL). Individual contents under Database Contents Licence.",
        "notes": "⚠ THE TAXONOMY ONLY, ~2.5 MB, ~4,700 English entries. NOT the product database "
                 "at ~9 GB, which is a different dataset and is not wanted here.",
    },
    {
        "source": "foodon",
        "dataset": "owl_release",
        "url": "http://purl.obolibrary.org/obo/foodon.owl",
        "query_text": None,
        "licence": "CC-BY-3.0",
        "attribution": "FoodOn: A farm to fork ontology. Licensed CC BY 3.0.",
        "notes": "⚠ THE OWL RELEASE, ~38.6 MB. foodon.obo is an 8 KB stub and is NOT a substitute.",
    },
    {
        "source": "agrovoc",
        "dataset": "sparql_en",
        "url": "https://agrovoc.fao.org/sparql",
        "query_text": (
            "SELECT ?c ?text ?kind WHERE {\n"
            "  ?c skos:inScheme <http://aims.fao.org/aos/agrovoc> .\n"
            "  { ?c skos:prefLabel ?text . BIND(\"prefLabel\" AS ?kind) }\n"
            "  UNION\n"
            "  { ?c skos:altLabel ?text .  BIND(\"altLabel\"  AS ?kind) }\n"
            "  FILTER(LANG(?text) = \"en\")\n"
            "}\n"
            "ORDER BY ?c ?kind ?text\n"
            "LIMIT {limit} OFFSET {offset}"
        ),
        "licence": "CC-BY-4.0 (6 of 42 languages only)",
        "attribution": "AGROVOC Multilingual Thesaurus, Food and Agriculture Organization of the "
                       "United Nations (FAO). Licensed CC BY 4.0.",
        "notes": "⚠ ENGLISH ONLY, and that is a LICENCE constraint rather than a shortcut: the CC BY "
                 "4.0 grant covers 6 of AGROVOC's 42 languages. The other 36 are not freely licensed, "
                 "so they must not be fetched. ⚠ No working bulk dump. FAO stopped dated releases in "
                 "July 2025, so SPARQL paging is the only route.",
    },
    {
        "source": "usda_fdc",
        "dataset": "foundation_foods",
        "url": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2025-04-24.zip",
        "query_text": None,
        "licence": "public-domain (17 USC 105)",
        "attribution": "U.S. Department of Agriculture, Agricultural Research Service. "
                       "FoodData Central, fdc.nal.usda.gov.",
        "notes": "⚠ Stored AS FETCHED as a zipped blob in source_payload and decompressed per read. "
                 "Shares the FDC schema with sr_legacy, so both land in usda_fdc_entry and are told "
                 "apart by source_fetch.dataset. ⚠ NOT Branded, NOT FNDDS.",
    },
    {
        "source": "usda_fdc",
        "dataset": "sr_legacy",
        "url": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip",
        "query_text": None,
        "licence": "public-domain (17 USC 105)",
        "attribution": "U.S. Department of Agriculture, Agricultural Research Service. "
                       "FoodData Central, fdc.nal.usda.gov.",
        "notes": "⚠ Stored AS FETCHED as a zipped blob. Same FDC schema as foundation_foods. "
                 "⚠ NOT Branded, NOT FNDDS.",
    },
    {
        "source": "wiktextract",
        "dataset": "enwiktionary_senses",
        "url": "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz",
        "query_text": None,
        "licence": "CC-BY-SA-4.0 AND GFDL-1.3",
        "attribution": "Extracted from English Wiktionary by wiktextract (Tatu Ylonen). "
                       "Wiktionary content is available under CC BY-SA and GFDL. "
                       "Cite: Tatu Ylonen, Wiktextract: Wiktionary as Machine-Readable Structured "
                       "Data, LREC 2022, pp. 1317-1325.",
        "notes": "⚠ SHARE-ALIKE. This is the one source whose licence bites on a merged artefact, "
                 "which is the strongest reason the tables stay separate. Added because it MEASURED "
                 "better than the other five on the terms they collapse on: 8 of 10 present in "
                 "en.wiktionary (pekmez, gochugaru, Shaoxing wine, doubanjiang, asafoetida, za'atar, "
                 "guanciale, speculoos) against 5 of 10 correct top hits in Wikidata. Misses xawaash "
                 "and lu bao.",
    },
]

# ── Infrastructure: the manifest, the constants, and the raw bytes.
INFRA_SQL = """
-- Per-dataset constants. Written BEFORE any data lands, so licence and attribution can
-- never be the thing that got filtered out at read time. See the King Arthur note above.
CREATE TABLE source_catalogue (
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    url          TEXT NOT NULL,
    query_text   TEXT,                    -- SPARQL verbatim; NULL for file downloads
    licence      TEXT NOT NULL,
    attribution  TEXT NOT NULL,           -- verbatim, as the source requires it
    notes        TEXT,
    PRIMARY KEY (source, dataset)
);

-- One row per fetch. This is the manifest you scan to see what is in the store and when
-- it arrived, so it stays cheap to read and the bytes live in source_payload.
CREATE TABLE source_fetch (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    url          TEXT NOT NULL,
    query_text   TEXT,
    version      TEXT,                    -- the source's own release identifier
    licence      TEXT NOT NULL,           -- copied from catalogue AT FETCH TIME: licences change
    attribution  TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,           -- ISO-8601 UTC
    bytes        INTEGER NOT NULL,        -- as fetched, on the wire
    sha256       TEXT NOT NULL,           -- of the fetched bytes
    notes        TEXT,
    FOREIGN KEY (source, dataset) REFERENCES source_catalogue(source, dataset),
    UNIQUE (source, dataset, fetched_at)
);

-- The bytes AS FETCHED, so a parse bug is re-runnable offline. Wikidata and AGROVOC
-- change underneath you, so a re-fetch is not the same bytes and cannot stand in.
CREATE TABLE source_payload (
    fetch_id      INTEGER PRIMARY KEY REFERENCES source_fetch(id) ON DELETE CASCADE,
    media_type    TEXT NOT NULL,
    compression   TEXT NOT NULL CHECK (compression IN ('none','gzip','zip')),
    blob          BLOB NOT NULL,
    bytes_stored  INTEGER NOT NULL,       -- differs from source_fetch.bytes if we compressed
    sha256_stored TEXT NOT NULL
);

CREATE INDEX idx_fetch_source  ON source_fetch(source, dataset);
CREATE INDEX idx_fetch_when    ON source_fetch(fetched_at);
"""

# ── The six entry tables share a COLUMN CONTRACT but never a table.
#    Per-source, so the independence is structural. See the licence note in the docstring.
ENTRY_SOURCES = [
    ("wikidata",        "Wikidata items, subclasses of Q2095."),
    ("off_taxonomy",    "Open Food Facts ingredients taxonomy entries."),
    ("foodon",          "FoodOn OWL classes."),
    ("agrovoc",         "AGROVOC concepts, English only for licence reasons."),
    ("usda_fdc",        "USDA FDC foods. Foundation and SR Legacy share this table and are told "
                        "apart by source_fetch.dataset."),
    ("wiktextract",     "English Wiktionary senses extracted by wiktextract."),
]

ENTRY_TMPL = """
-- {comment}
CREATE TABLE {p}_entry (
    pk        INTEGER PRIMARY KEY,
    fetch_id  INTEGER NOT NULL REFERENCES source_fetch(id) ON DELETE CASCADE,
    entry_id  TEXT NOT NULL,          -- the source's OWN identifier, verbatim
    name      TEXT NOT NULL,          -- verbatim and untransformed; the source's display name
    lang      TEXT,                   -- language of `name`, as the source states it
    xrefs     TEXT,                   -- cross-references the ENTRY ITSELF carries, verbatim
    raw       TEXT NOT NULL,          -- the unmodified record, so a later pass can extract
                                      -- something nobody thought to extract
    UNIQUE (fetch_id, entry_id)
);

-- One row per label. NOT a blob: 40 labels in a blob cannot be filtered, and
-- "native-language label but no English one" is a query worth running.
CREATE TABLE {p}_label (
    pk           INTEGER PRIMARY KEY,
    entry_pk     INTEGER NOT NULL REFERENCES {p}_entry(pk) ON DELETE CASCADE,
    lang         TEXT,                -- the source's own code, verbatim; NULL if it states none
    text         TEXT NOT NULL,       -- verbatim
    kind         TEXT NOT NULL,       -- the source's OWN word: label, alias, prefLabel,
                                      -- altLabel, synonym, hasExactSynonym, translation.
                                      -- NOT normalised: normalising is merging.
    is_preferred INTEGER NOT NULL DEFAULT 0 CHECK (is_preferred IN (0,1)),
    source_field TEXT                 -- which field of `raw` this came from
);

CREATE INDEX idx_{p}_entry_fetch ON {p}_entry(fetch_id);
CREATE INDEX idx_{p}_entry_name  ON {p}_entry(name);
CREATE INDEX idx_{p}_label_entry ON {p}_label(entry_pk);
CREATE INDEX idx_{p}_label_lang  ON {p}_label(lang);
CREATE INDEX idx_{p}_label_text  ON {p}_label(text);
"""


def schema_sql():
    """The full DDL, assembled. Kept as a function so tests can read it without a DB."""
    parts = [INFRA_SQL]
    for prefix, comment in ENTRY_SOURCES:
        parts.append(ENTRY_TMPL.format(p=prefix, comment=comment))
    return "\n".join(parts)


def build(db_path=None):
    """Create sources.db and populate source_catalogue. No network, no entry rows.

    db_path is read at CALL TIME rather than frozen at import, so a test can point this at
    a temp file and be sure it is not writing to the real one. (Same lesson as
    app.py::orm_session.)
    """
    path = Path(db_path) if db_path else DB
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(schema_sql())
        for d in DATASETS:
            conn.execute(
                "INSERT INTO source_catalogue "
                "(source, dataset, url, query_text, licence, attribution, notes) "
                "VALUES (?,?,?,?,?,?,?)",
                (d["source"], d["dataset"], d["url"], d["query_text"],
                 d["licence"], d["attribution"], d["notes"]),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def print_manifest(db_path=None):
    """Print what the store is set up to hold. Stage 1 has no rows, so this is the catalogue."""
    path = Path(db_path) if db_path else DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source, dataset, licence, url FROM source_catalogue ORDER BY source, dataset"
    ).fetchall()
    n_tab = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    conn.close()
    print(f"{path.name}: {n_tab} tables, {len(rows)} datasets catalogued, 0 entries (Stage 1 is offline)\n")
    for r in rows:
        print(f"  {r['source']:16} {r['dataset']:22} {r['licence']:34} {r['url'][:52]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create sources.db (schema + catalogue). No network.")
    ap.add_argument("--db", default=None, help="path to write (default: ./sources.db)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = ap.parse_args(argv)

    path = Path(args.db) if args.db else DB
    if path.exists():
        if not args.force:
            print(f"{path} already exists. Re-run with --force to replace it.", file=sys.stderr)
            return 1
        path.unlink()
    build(path)
    print_manifest(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
