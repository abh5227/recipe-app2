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

WHY THE TABLES ARE SEPARATE, AND WHY THAT IS A LICENSE DECISION
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

Hence source_catalogue below: license and attribution get a column, and they are written
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
#    License and attribution are recorded VERBATIM. Anything marked ⚠ is load-bearing.
DATASETS = [
    {
        "source": "wikidata",
        "dataset": "food_items_q2095",
        "url": "https://query.wikidata.org/sparql",
        # ⚠ ORDER BY IS MANDATORY. LIMIT/OFFSET paging without a total order is
        #   non-deterministic and silently lost 29% of the labels on a previous attempt.
        # ⚠ ALL LANGUAGES, not English. gochugaru is reachable ONLY via its Korean label.
        #
        # ⚠⚠ THE LABEL-PAGED FORM OF THIS QUERY DOES NOT RUN, measured 23 Aug 2026:
        #      LIMIT 5000 OFFSET      0  ->  HTTP 502 after 15.3s
        #      LIMIT 5000 OFFSET 320000  ->  HTTP 504 after 65.1s
        #    WDQS must sort all 332,018 label rows before every OFFSET. The ORDER BY that
        #    prevents the 29% loss is what makes it unrunnable, and dropping it would
        #    reintroduce the exact bug it guards. So the stored query is the ITEM query
        #    below, which returns the whole ordered key set in one 5.8s request, and the
        #    labels come from wbgetentities batches keyed on that stored list. Determinism
        #    moves from "the server repeats a sort" to "we hold the ordered key set",
        #    which is the stronger guarantee. See fetch_sources.cmd_wikidata.
        "query_text": "SELECT ?item WHERE { ?item wdt:P279* wd:Q2095 . } ORDER BY ?item",
        "license": "CC0-1.0",
        "attribution": "Wikidata contributors. Available under CC0 1.0 Universal Public Domain Dedication.",
        "notes": "Food items are subclasses of Q2095 (food), transitively via P279*. Measured "
                 "23 Aug 2026: 28,632 entities and 332,018 label+alias rows. An earlier count of "
                 "~34,900 counted LABELS, not distinct items, and was wrong. ⚠ 1 of the 28,632 is "
                 "a LEXEME SENSE (L1369402-S1), not an item. ⚠ COVERAGE HOLE, not fixable from "
                 "inside a subclass crawl: xawaash exists as two duplicate items, Q123924322 "
                 "(P279 -> Q1521067, reachable) and Q139964282 (no P279, no P31, unreachable).",
    },
    {
        # ⚠ THE .txt IS THE CANONICAL SOURCE AND THE .json EXPORT IS LOSSY. Measured
        #   23 Aug 2026: the .txt carries 61,565 language lines of which 11,015 (17.9%)
        #   list more than one name. The .json keeps only the first and drops the rest.
        #       en: salt, table salt, common salt, cooking salt, dry salt, edible salt,
        #           edible common salt, food salt        -> .json keeps "salt" alone
        #   That is the King Arthur failure inside the source, so the .txt is fetched too.
        "source": "open_food_facts",
        "dataset": "ingredients_taxonomy_txt",
        "url": "https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/"
               "main/taxonomies/food/ingredients.txt",
        "query_text": None,
        "license": "ODbL-1.0",
        "attribution": "Open Food Facts contributors. Database licensed under the Open Database "
                       "License (ODbL). Individual contents under Database Contents License.",
        "notes": "The canonical taxonomy source, ~2.66 MB. Carries FULL synonym lists per language, "
                 "which the JSON export drops. ⚠ NOT the product database at ~9 GB.",
    },
    {
        "source": "open_food_facts",
        "dataset": "ingredients_taxonomy_json",
        "url": "https://static.openfoodfacts.org/data/taxonomies/ingredients.json",
        "query_text": None,
        "license": "ODbL-1.0",
        "attribution": "Open Food Facts contributors. Database licensed under the Open Database "
                       "License (ODbL). Individual contents under Database Contents License.",
        "notes": "The derived JSON export, ~3.16 MB, 6,446 entries, names in 193 languages, 5,515 "
                 "with an English name. Fetched for the STRUCTURED XREFS the .txt lacks (wikidata, "
                 "ciqual_food_code, usda_ndb_code, ifct_food_code, e_number). ⚠ Lossy on synonyms, "
                 "see the txt dataset. Both land in off_taxonomy_entry, told apart by "
                 "source_fetch.dataset, exactly like the two USDA datasets.",
    },
    {
        "source": "agrovoc",
        "dataset": "sparql_licensed_six",
        "url": "https://agrovoc.fao.org/sparql",
        # ⚠ PAGES BY CONCEPT, not by label. Label paging would split a concept across a
        #   page boundary and write it twice with partial labels. The inner subquery
        #   fixes the key set per page, so pages tile with zero overlap (verified).
        # ⚠ Unlike WDQS this endpoint pages correctly: OFFSET 40000 returns in 9.5s, an
        #   ordered page repeats identically, and page1+page2 equals one double page.
        "query_text": (
            "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
            "SELECT ?c ?t ?kind ?lang WHERE {\n"
            "  { SELECT DISTINCT ?c WHERE { ?c skos:inScheme "
            "<http://aims.fao.org/aos/agrovoc> . } ORDER BY ?c LIMIT {limit} OFFSET {offset} }\n"
            "  { ?c skos:prefLabel ?t . BIND(\"prefLabel\" AS ?kind) }\n"
            "  UNION\n"
            "  { ?c skos:altLabel ?t .  BIND(\"altLabel\" AS ?kind) }\n"
            "  BIND(LANG(?t) AS ?lang)\n"
            "  FILTER(?lang IN (\"en\", \"fr\", \"es\", \"ar\", \"ru\", \"zh\"))\n"
            "}\n"
            "ORDER BY ?c ?kind ?lang ?t"
        ),
        "license": "CC-BY-4.0, and ONLY for en, fr, es, ar, ru, zh",
        "attribution": "AGROVOC Multilingual Thesaurus, Food and Agriculture Organization of the "
                       "United Nations (FAO). Licensed CC BY 4.0.",
        "notes": "⚠ THE LICENSED SUBSET IS SIX LANGUAGES, NOT ONE. FAO holds copyright on the six "
                 "FAO official languages (English, French, Spanish, Arabic, Russian, Chinese) and "
                 "those are CC BY 4.0. Content in the other 36 languages rests with the "
                 "institutions that authored it and is NOT covered, so it must not be fetched. "
                 "⚠ ALL SIX ARE FETCHED. An earlier run took ENGLISH ONLY, which was a NARROWER CHOICE "
                 "than the license requires rather than an obligation, and it dropped exactly the "
                 "non-Western alias material this source search existed to find. Measured 23 Aug "
                 "2026: en 54,443, fr 50,150, es 53,744, ar 44,002, ru 51,331, zh 50,240, total "
                 "303,910 rows. English alone was 17.9% of what the license permits. "
                 "⚠ No working bulk dump. FAO stopped dated releases in July 2025. "
                 "⚠ THIN ON THIS PROJECT'S HARD TERMS: 2 of the 10 collapse terms match an "
                 "English label (pekmez c_809befad, asafoetida c_a7a129af). gochugaru, Shaoxing "
                 "wine, doubanjiang, xawaash, za'atar, guanciale, lu bao and speculoos all miss. "
                 "41,825 concepts total, most of them agriculture rather than food.",
    },
    {
        "source": "usda_fdc",
        "dataset": "foundation_foods",
        "url": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2025-04-24.zip",
        "query_text": None,
        "license": "public-domain (17 USC 105)",
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
        "license": "public-domain (17 USC 105)",
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
        "license": "CC-BY-SA-4.0 AND GFDL-1.3",
        "share_alike": 1,
        "attribution": "Extracted from English Wiktionary by wiktextract (Tatu Ylonen). "
                       "Wiktionary content is available under CC BY-SA and GFDL. "
                       "Cite: Tatu Ylonen, Wiktextract: Wiktionary as Machine-Readable Structured "
                       "Data, LREC 2022, pp. 1317-1325.",
        "notes": "⚠ 2,826.7 MB COMPRESSED, expanding to 22.9 GB. Verified 23 Aug 2026. ⚠ NO topical "
                 "subset exists: kaikki publishes per-language-EDITION dumps and 721 browsable "
                 "topics, but topics are not downloadable slices, so no smaller artifact covers "
                 "the same ground. The English-only file is DEPRECATED and is the wrong axis "
                 "anyway, since this dump carries hundreds of languages with English glosses. "
                 "⚠ SHARE-ALIKE. This is the one source whose license bites on a merged artefact, "
                 "which is the strongest reason the tables stay separate. Added because it MEASURED "
                 "better than the other five on the terms they collapse on: 8 of 10 present in "
                 "en.wiktionary (pekmez, gochugaru, Shaoxing wine, doubanjiang, asafoetida, za'atar, "
                 "guanciale, speculoos) against 5 of 10 correct top hits in Wikidata. Misses xawaash "
                 "and lu bao.",
    },
    {
        "source": "wikipedia_redirect",
        "dataset": "enwiki_food_redirects",
        "url": "https://en.wikipedia.org/w/api.php?action=query&prop=redirects&rdlimit=max",
        "query_text": None,
        "license": "CC-BY-SA-4.0",
        "share_alike": 1,
        "attribution": "Wikipedia contributors. Text available under the Creative Commons "
                       "Attribution-ShareAlike 4.0 License.",
        "probe_score": "9/10",
        "decision_reason": "Highest score of anything measured, and the only source that beats "
                           "Wikidata on Wikidata's own weakness. Redirects ARE an alias list, "
                           "written by the people who hit the naming problem: Shaoxing jiu / "
                           "Shaohsing wine, 豆瓣酱 / Broad bean paste, Heeng, Speculaas / Windmill "
                           "cookie. gochugaru resolves to a dedicated 'Korean chili pepper' "
                           "article, which is exactly the merge Wikidata gets wrong.",
        "notes": "Scoped to the enwiki sitelinks of the food items already in wikidata_entry, so "
                 "the key set is one this store already holds. Measured 23 Aug 2026 on a sample "
                 "of 60: 32% of items carry an enwiki article, mean 4.7 redirects each, "
                 "projecting ~9,066 articles and ~42,467 aliases from ~182 API calls. No bulk "
                 "download. ⚠ SHARE-ALIKE, like wiktextract.",
    },
    {
        "source": "wiktextract",
        "dataset": "zhwiktionary_senses",
        "url": "https://kaikki.org/zhwiktionary/raw-wiktextract-data.jsonl.gz",
        "query_text": None,
        "license": "CC-BY-SA-4.0 AND GFDL-1.3",
        "share_alike": 1,
        "attribution": "Extracted from Chinese Wiktionary by wiktextract (Tatu Ylonen). "
                       "Wiktionary content is available under CC BY-SA and GFDL.",
        "probe_score": "5/10",
        "decision_reason": "The best of the non-English editions by a distance, and its hits are "
                           "the COMPLEMENT rather than more of the same: gochugaru, Shaoxing wine, "
                           "doubanjiang, asafoetida and guanciale, which are the CJK terms the "
                           "English edition handles worst. Every other edition measured 2 or "
                           "below (ko 2, it 2, fr 2, ru 2, tr 1, ar 1, nl 1, so 1, de 1, ja 0, hi 0).",
        "notes": "Same extractor as the English dump, different Wiktionary edition. Lands in "
                 "wiktextract_entry, told apart by source_fetch.dataset.",
    },
]

# ── MEASURED AND REJECTED. Kept in the catalogue with status='declined' so the decision
#    is legible and the probe is not repeated. Each carries its score and its reason.
DECLINED = [
    {
        "source": "foodon", "dataset": "owl_release",
        "url": "http://purl.obolibrary.org/obo/foodon.owl",
        "license": "CC-BY-3.0",
        "attribution": "FoodOn: A farm to fork ontology. Licensed CC BY 3.0.",
        "probe_score": "1-2/10",
        "decision_reason": "⚠ THE REASON IS STRUCTURAL, NOT COVERAGE. FoodOn knows DISHES, not "
                           "INGREDIENTS. Probing the ten collapse terms via EBI OLS4, gochugaru "
                           "returns 'kimchi' and guanciale returns 'carbonara sauce'. It "
                           "classifies what a food IS in a taxonomy of prepared items, which is a "
                           "different question from what a thing is CALLED on a packet. A larger "
                           "download would not change that, so this is not a 'revisit when it "
                           "grows' decline. Of the two apparent hits, za'atar resolves to "
                           "GENEPIO:0002240, a DIFFERENT ontology OLS serves alongside FoodOn, so "
                           "FoodOn proper carries one of the ten (asafoetida, FOODON:00002936).",
        "notes": "38.6 MB OWL release. Would also have needed a stdlib OWL parser. Declined "
                 "before fetching, on a measurement that cost one API sweep.",
    },
    {
        "source": "wikimedia_commons", "dataset": "categories",
        "url": "https://commons.wikimedia.org/w/api.php",
        "license": "mixed, per file",
        "attribution": "Wikimedia Commons contributors.",
        "probe_score": "0/10",
        "decision_reason": "No exact category matched any of the ten. Nearest results were "
                           "'Category:Gochujang' for gochugaru and 'Category:Guanciale dishes' "
                           "for guanciale. Consistent with the earlier finding that a Commons "
                           "search for guanciale returned a racehorse, and that xawaash returned "
                           "34,826 irrelevant results.",
        "probe_caveat": "⚠ WEAKER MEASUREMENT THAN THE OTHERS, and a future pass should know it. "
                        "The probe used a compound 'incategory:\"x\" OR x' search restricted to "
                        "namespace 14, which may understate real coverage. The 0/10 agrees with "
                        "independent prior evidence, but it rests on one query shape rather than "
                        "on a clean exact-match lookup like the FoodOn and AGROVOC probes. If "
                        "Commons is reconsidered, re-probe properly before trusting this row. "
                        "License is also mixed per file rather than uniform.",
        "notes": "Category NAMES were the target, not the media.",
    },
    {
        "source": "recipenlg", "dataset": "corpus",
        "url": "https://recipenlg.cs.put.poznan.pl/",
        "license": "NOT ESTABLISHED",
        "attribution": "unavailable",
        "probe_score": "not measured",
        "decision_reason": "⚠ DECLINED ON LICENSE, BEFORE COVERAGE, per the license-first rule. No "
                           "license statement was reachable on the project site. It is built on "
                           "Recipe1M+, which is scraped from copyrighted recipe websites, so the "
                           "underlying rights are not the authors' to grant. A source that cannot "
                           "ship is not worth measuring.",
        "notes": "~2.2 million recipes with named food entities. Coverage never tested.",
    },
    {
        "source": "recipe1m", "dataset": "corpus",
        "url": "http://pic2recipe.csail.mit.edu/",
        "license": "NOT REDISTRIBUTABLE",
        "attribution": "unavailable",
        "probe_score": "not measured",
        "decision_reason": "⚠ DECLINED ON LICENSE, BEFORE COVERAGE. The dataset is not provided "
                           "publicly; the authors publish image URLs to be scraped, which puts "
                           "the rights with the original recipe sites rather than the dataset.",
        "notes": "Coverage never tested.",
    },
    {
        "source": "gs1", "dataset": "gpc",
        "url": "https://gpc-browser.gs1.org/",
        "license": "GS1 member license only",
        "attribution": "GS1 Global Product Classification.",
        "probe_score": "not measured",
        "decision_reason": "⚠ DECLINED ON LICENSE, BEFORE COVERAGE. GS1 grants 'a royalty-free "
                           "licence or a RAND licence to Necessary Claims' TO GS1 MEMBERS. That "
                           "is a membership term, not a redistribution grant, and no open license "
                           "covering reuse in a product was found.",
        "notes": "Retail product classification. Coverage never tested.",
    },
    {
        "source": "wikidata", "dataset": "lexemes",
        "url": "https://www.wikidata.org/w/api.php?action=wbsearchentities&type=lexeme",
        "license": "CC0-1.0",
        "attribution": "Wikidata contributors. CC0 1.0.",
        "probe_score": "3/10",
        "decision_reason": "License is ideal and coverage is not. Only pekmez (L1359153, Albanian), "
                           "za'atar (L1420702, English) and speculoos (L1553996, Dutch) matched. "
                           "Lexemes record words as words, and food vocabulary is sparsely "
                           "covered. Worth revisiting if lexeme coverage grows.",
        "notes": "Distinct from Wikidata ITEMS, which are already ingested.",
    },
    {
        "source": "wiktextract", "dataset": "other_editions",
        "url": "https://kaikki.org/",
        "license": "CC-BY-SA-4.0 AND GFDL-1.3",
        "attribution": "Wiktionary contributors, extracted by wiktextract.",
        "probe_score": "2/10 or below",
        "decision_reason": "Measured every edition on the ten: ko 2, it 2, fr 2, ru 2, tr 1, ar 1, "
                           "nl 1, so 1, de 1, ja 0, hi 0. Only zh reached 5 and is ingested "
                           "separately. The rest do not justify a dump each.",
        "notes": "Recorded so the sweep is not repeated edition by edition.",
    },
]

# ── Infrastructure: the manifest, the constants, and the raw bytes.
INFRA_SQL = """
-- Per-dataset constants. Written BEFORE any data lands, so license and attribution can
-- never be the thing that got filtered out at read time. See the King Arthur note above.
CREATE TABLE source_catalogue (
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    url          TEXT NOT NULL,
    query_text   TEXT,                    -- SPARQL verbatim; NULL for file downloads
    license      TEXT NOT NULL,
    attribution  TEXT NOT NULL,           -- verbatim, as the source requires it
    share_alike  INTEGER NOT NULL DEFAULT 0 CHECK (share_alike IN (0,1)),
    notes        TEXT,

    -- ⚠ DECLINES ARE CATALOGUED TOO. A source that was measured and rejected is a
    --   decision worth keeping. Without this, the next pass re-derives the same probe
    --   and may reach a different answer for no reason.
    status          TEXT NOT NULL DEFAULT 'ingest'
                    CHECK (status IN ('ingest','declined')),
    probe_score     TEXT,                 -- score on the ten collapse terms
    decision_reason TEXT,                 -- why it is in or out, in one place
    probe_caveat    TEXT,                 -- how much the measurement can bear

    PRIMARY KEY (source, dataset)
);

-- ONE ROW PER PAGE, not per crawl. Uglier and more honest: the last Wikidata crawl
-- silently lost 29% while reporting success, so a partial crawl has to LOOK partial.
-- A crawl is complete only when its pages run 0..N contiguously and exactly one row
-- carries is_final_page = 1. Unpaged sources are a single page 0 that is also final.
CREATE TABLE source_fetch (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    dataset       TEXT NOT NULL,
    url           TEXT NOT NULL,
    query_text    TEXT,
    version       TEXT,                   -- the source's own release identifier
    license       TEXT NOT NULL,          -- copied from catalogue AT FETCH TIME: licenses change
    share_alike   INTEGER NOT NULL DEFAULT 0 CHECK (share_alike IN (0,1)),
                                          -- ⚠ 1 = this source's license attaches share-alike
                                          --   to any MERGED artefact. Two sources carry it now
                                          --   (wiktextract, wikipedia_redirect), which is the
                                          --   strongest reason the tables stay separate.
    attribution   TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,          -- ISO-8601 UTC
    bytes         INTEGER NOT NULL,       -- as fetched, on the wire
    sha256        TEXT NOT NULL,          -- of the fetched bytes
    notes         TEXT,

    -- paging
    crawl_id      TEXT NOT NULL,          -- groups the pages of one crawl
    page_index    INTEGER NOT NULL DEFAULT 0,
    page_offset   INTEGER,
    page_limit    INTEGER,
    rows_returned INTEGER,
    is_final_page INTEGER NOT NULL DEFAULT 1 CHECK (is_final_page IN (0,1)),

    -- parse accounting. What the parse DROPPED, recorded next to what it kept, so the
    -- King Arthur question ("what did the reader filter out?") has an answer per fetch.
    parse_filter      TEXT,               -- the criterion, VERBATIM, or NULL if nothing filtered
    records_in_payload INTEGER,           -- records the payload contained
    entries_written   INTEGER,            -- rows written to the entry table
    entries_excluded  INTEGER,            -- records the filter rejected

    FOREIGN KEY (source, dataset) REFERENCES source_catalogue(source, dataset),
    UNIQUE (crawl_id, page_index)
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
CREATE INDEX idx_fetch_crawl   ON source_fetch(crawl_id, page_index);
"""

# ── The six entry tables share a COLUMN CONTRACT but never a table.
#    Per-source, so the independence is structural. See the license note in the docstring.
ENTRY_SOURCES = [
    ("wikidata",        "Wikidata items, subclasses of Q2095."),
    ("off_taxonomy",    "Open Food Facts ingredients taxonomy entries."),

    ("agrovoc",         "AGROVOC concepts, English only for license reasons."),
    ("usda_fdc",        "USDA FDC foods. Foundation and SR Legacy share this table and are told "
                        "apart by source_fetch.dataset."),
    ("wiktextract",     "Wiktionary senses extracted by wiktextract. Editions share this "
                        "table and are told apart by source_fetch.dataset."),
    ("wikipedia_redirect", "Wikipedia articles and the redirects pointing at them. A redirect "
                        "IS an alias, recorded by the people who hit the naming problem. "
                        "⚠ ITS OWN TABLES ON PURPOSE, never folded into wikidata_label: "
                        "Wikidata merges gochugaru into 'chili powder' and Wikipedia has a "
                        "separate 'Korean chili pepper' article. Merging the two would repair "
                        "that defect invisibly, and keeping it visible is the point of the "
                        "store. How the two relate is a later question, not an ingest-time one."),
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
        ins = ("INSERT INTO source_catalogue "
               "(source, dataset, url, query_text, license, attribution, share_alike, notes, "
               " status, probe_score, decision_reason, probe_caveat) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        for d in DATASETS:
            conn.execute(ins, (d["source"], d["dataset"], d["url"], d.get("query_text"),
                               d["license"], d["attribution"], d.get("share_alike", 0),
                               d.get("notes"), "ingest",
                               d.get("probe_score"), d.get("decision_reason"),
                               d.get("probe_caveat")))
        for d in DECLINED:
            conn.execute(ins, (d["source"], d["dataset"], d["url"], d.get("query_text"),
                               d["license"], d["attribution"], d.get("share_alike", 0),
                               d.get("notes"), "declined",
                               d.get("probe_score"), d.get("decision_reason"),
                               d.get("probe_caveat")))
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
        "SELECT source, dataset, license, url, status, probe_score FROM source_catalogue "
        "ORDER BY status, source, dataset"
    ).fetchall()
    n_tab = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    conn.close()
    n_in = sum(1 for r in rows if r["status"] == "ingest")
    n_out = len(rows) - n_in
    print(f"{path.name}: {n_tab} tables, {n_in} datasets to ingest, {n_out} declined and recorded\n")
    for st in ("ingest", "declined"):
        sel = [r for r in rows if r["status"] == st]
        print(f"  -- {st} ({len(sel)})")
        for r in sel:
            score = r["probe_score"] or ""
            print(f"     {r['source']:18} {r['dataset']:24} {score:>14}  {r['license'][:36]}")


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
