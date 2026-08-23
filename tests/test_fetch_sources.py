"""Parser and storage tests for fetch_sources.py. No network: every test uses a fixture.

Guards the two rules the module exists to keep:
  - the payload is stored whole and re-readable offline;
  - whatever the parse drops is counted, with the criterion recorded verbatim.
"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import build_sources_db as bsd
import fetch_sources as fs

ENTRY_PREFIXES_FETCH = [p for p, _ in bsd.ENTRY_SOURCES]

# A cut-down taxonomy exercising every shape the real file has: a heading block, a
# stopwords directive, parents, multi-name lines, and a wholly non-Latin entry.
TXT_FIXTURE = """### Properties for ingredients

stopwords:en: and, or

# a comment block only

< en: mineral
en: salt, table salt, common salt, cooking salt
bg: сол, готварска сол
ko: 소금
ja: 塩

< en: millet
en: little millet
ta: சாமை

bg: захар
ru: сахар
"""

JSON_FIXTURE = {
    "en:salt": {
        "name": {"en": "salt", "bg": "сол", "ko": "소금"},
        "parents": ["en:mineral"],
        "wikidata": {"en": "Q11254"},
        "usda_ndb_code": {"en": "2047"},
        "ifct_food_code": {"en": "X001"},
    },
    "fr:sel-de-mer": {"name": {"fr": "sel de mer"}},
}


@pytest.fixture
def conn(tmp_path):
    path = bsd.build(tmp_path / "sources.db")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


# ── the .txt parser, which is why the .txt is fetched at all ────────────────────────────

def test_txt_keeps_the_synonyms_the_json_drops():
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    salt = [e for e in entries if e["name"] == "salt"][0]
    en = [l["text"] for l in salt["labels"] if l["lang"] == "en"]
    assert en == ["salt", "table salt", "common salt", "cooking salt"]
    kinds = [l["kind"] for l in salt["labels"] if l["lang"] == "en"]
    assert kinds == ["canonical_name", "synonym", "synonym", "synonym"]


def test_txt_preserves_non_latin_names():
    """The first parser slugged ids with [^a-z0-9] and erased Cyrillic entirely."""
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    texts = {l["text"] for e in entries for l in e["labels"]}
    for native in ("сол", "готварска сол", "소금", "塩", "சாமை", "захар", "сахар"):
        assert native in texts, f"{native} was lost"


def test_txt_entry_id_is_the_block_position_not_a_derived_slug():
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    assert all(e["entry_id"].isdigit() for e in entries)
    assert len({e["entry_id"] for e in entries}) == len(entries)


def test_a_wholly_non_latin_block_still_becomes_an_entry():
    """The block with only bg: and ru: lines is what collided as the id "bg:"."""
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    assert any(e["name"] == "захар" and e["lang"] == "bg" for e in entries)


def test_txt_excludes_directives_and_counts_them(conn):
    entries, n_rec, n_exc = fs.parse_off_txt(TXT_FIXTURE)
    assert n_rec == len(entries) + n_exc, "records must equal written plus excluded"
    assert n_exc == 3, "heading, stopwords and comment-only blocks"


def test_txt_captures_parents_as_xrefs():
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    salt = [e for e in entries if e["name"] == "salt"][0]
    assert json.loads(salt["xrefs"])["parents"] == ["en:mineral"]


def test_txt_raw_block_is_verbatim():
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    salt = [e for e in entries if e["name"] == "salt"][0]
    assert "en: salt, table salt, common salt, cooking salt" in salt["raw"]
    assert "ja: 塩" in salt["raw"]


# ── the .json parser, fetched for the xrefs ─────────────────────────────────────────────

def test_json_uses_the_sources_own_id():
    entries, n_rec, n_exc = fs.parse_off_json(JSON_FIXTURE)
    assert {e["entry_id"] for e in entries} == {"en:salt", "fr:sel-de-mer"}
    assert (n_rec, n_exc) == (2, 0)


def test_json_captures_xrefs():
    entries, _, _ = fs.parse_off_json(JSON_FIXTURE)
    xr = json.loads([e for e in entries if e["entry_id"] == "en:salt"][0]["xrefs"])
    assert xr["wikidata"] == {"en": "Q11254"}
    assert xr["ifct_food_code"] == {"en": "X001"}
    assert xr["parents"] == ["en:mineral"]


def test_json_makes_one_label_per_language():
    entries, _, _ = fs.parse_off_json(JSON_FIXTURE)
    salt = [e for e in entries if e["entry_id"] == "en:salt"][0]
    assert {l["lang"] for l in salt["labels"]} == {"en", "bg", "ko"}
    assert sum(l["is_preferred"] for l in salt["labels"]) == 1


def test_json_entry_without_english_still_lands():
    entries, _, _ = fs.parse_off_json(JSON_FIXTURE)
    fr = [e for e in entries if e["entry_id"] == "fr:sel-de-mer"][0]
    assert fr["lang"] == "fr" and fr["name"] == "sel de mer"


# ── storage ─────────────────────────────────────────────────────────────────────────────

def test_payload_round_trips_offline(conn):
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    blob = TXT_FIXTURE.encode("utf-8")
    fid = fs.record_page(conn, cat, blob, crawl_id="c1")
    assert fs.read_payload(conn, fid) == blob, "a parser bug must be re-runnable without refetching"


def test_payload_is_compressed_and_hashed_separately(conn):
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    blob = (TXT_FIXTURE * 40).encode("utf-8")
    fid = fs.record_page(conn, cat, blob, crawl_id="c1")
    r = conn.execute("SELECT * FROM source_payload WHERE fetch_id=?", (fid,)).fetchone()
    f = conn.execute("SELECT bytes, sha256 FROM source_fetch WHERE id=?", (fid,)).fetchone()
    assert r["compression"] == "gzip"
    assert r["bytes_stored"] < f["bytes"]
    assert r["sha256_stored"] != f["sha256"], "the wire hash and the stored hash are different things"
    assert gzip.decompress(r["blob"]) == blob


def test_license_and_attribution_are_copied_at_fetch_time(conn):
    """Copied, not referenced: licenses change. IFCT went AGPL in April 2025."""
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    fid = fs.record_page(conn, cat, b"x", crawl_id="c1")
    r = conn.execute("SELECT license, attribution FROM source_fetch WHERE id=?", (fid,)).fetchone()
    assert r["license"] == "ODbL-1.0"
    assert "Open Food Facts" in r["attribution"]


def test_unpaged_source_writes_one_final_page(conn):
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    fid = fs.record_page(conn, cat, b"x", crawl_id="c1")
    r = conn.execute("SELECT page_index, is_final_page FROM source_fetch WHERE id=?", (fid,)).fetchone()
    assert (r["page_index"], r["is_final_page"]) == (0, 1)


def test_a_partial_crawl_looks_partial(conn):
    """The point of one row per page: the last crawl lost 29% while reporting success."""
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    fs.record_page(conn, cat, b"a", crawl_id="c9", page_index=0, is_final=False)
    fs.record_page(conn, cat, b"b", crawl_id="c9", page_index=1, is_final=False)
    final = conn.execute(
        "SELECT COUNT(*) FROM source_fetch WHERE crawl_id='c9' AND is_final_page=1").fetchone()[0]
    assert final == 0, "no terminal page means the crawl did not finish"


def test_parse_accounting_is_written(conn):
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    blob = TXT_FIXTURE.encode("utf-8")
    fid = fs.record_page(conn, cat, blob, crawl_id="c1", parse_filter=fs.OFF_TXT_FILTER)
    entries, n_rec, n_exc = fs.parse_off_txt(fs.read_payload(conn, fid).decode())
    written = fs.write_entries(conn, "off_taxonomy", fid, entries)
    conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
                 "entries_excluded=? WHERE id=?", (n_rec, written, n_exc, fid))
    r = conn.execute("SELECT * FROM source_fetch WHERE id=?", (fid,)).fetchone()
    assert r["records_in_payload"] == r["entries_written"] + r["entries_excluded"]
    assert r["parse_filter"] and "block index" in r["parse_filter"]


def test_labels_land_as_rows(conn):
    cat = fs.catalogue_row(conn, "open_food_facts", "ingredients_taxonomy_txt")
    fid = fs.record_page(conn, cat, TXT_FIXTURE.encode(), crawl_id="c1")
    entries, _, _ = fs.parse_off_txt(TXT_FIXTURE)
    fs.write_entries(conn, "off_taxonomy", fid, entries)
    n = conn.execute("SELECT COUNT(*) FROM off_taxonomy_label").fetchone()[0]
    assert n >= 10
    rows = conn.execute("""
        SELECT e.name FROM off_taxonomy_entry e
        WHERE     EXISTS (SELECT 1 FROM off_taxonomy_label l WHERE l.entry_pk=e.pk AND l.lang<>'en')
          AND NOT EXISTS (SELECT 1 FROM off_taxonomy_label l WHERE l.entry_pk=e.pk AND l.lang='en')
    """).fetchall()
    assert "захар" in {r["name"] for r in rows}


# ── guards ──────────────────────────────────────────────────────────────────────────────

def test_no_ascii_slug_is_reintroduced():
    """An ASCII slug inside ingestion built to fix an anglocentric gap IS the gap.

    Checked against the AST, so the comment explaining WHY the slug was removed is
    allowed to quote the offending pattern. A raw-text scan fails on its own docs,
    which is the mistake the sibling guard in test_sources_schema.py already made.
    """
    import ast
    tree = ast.parse((REPO / "fetch_sources.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert node.name != "slug", "the derived-id slug came back"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "[^a-z0-9]" not in node.value, "an ASCII-only slug pattern is live code again"


def test_fetch_module_never_names_recipes_db():
    import ast
    tree = ast.parse((REPO / "fetch_sources.py").read_text())
    banned = {"app", "seed", "migrate", "models", "build_db"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned
    body = tree.body[1:] if ast.get_docstring(tree) else tree.body
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                assert "recipes.db" not in sub.value


def test_offline_path_needs_no_network(conn):
    """cmd_off accepts pre-fetched bytes, which is how these tests avoid the network."""
    res = fs.cmd_off(conn, offline={
        "ingredients_taxonomy_txt": TXT_FIXTURE.encode("utf-8"),
        "ingredients_taxonomy_json": json.dumps(JSON_FIXTURE).encode("utf-8"),
    })
    assert len(res) == 2
    by = {r[0]: r for r in res}
    assert by["ingredients_taxonomy_json"][3] == 2
    assert by["ingredients_taxonomy_txt"][3] == 3   # salt, little millet, захар


# ── Wikidata ────────────────────────────────────────────────────────────────────────────

# Q1072946 as Wikidata actually holds it, measured 23 Aug 2026. The English label is the
# generic "chili powder" while the Korean label is the specific 고춧가루. That merge is a
# FINDING ABOUT THE SOURCE and these tests exist to prove it survives ingestion intact.
WD_FIXTURE = {"entities": {
    "Q1072946": {
        "type": "item", "id": "Q1072946",
        "labels": {
            "en": {"language": "en", "value": "chili powder"},
            "ko": {"language": "ko", "value": "고춧가루"},
            "ja": {"language": "ja", "value": "唐辛子粉"},
        },
        "aliases": {"en": [{"language": "en", "value": "powdered chili"},
                           {"language": "en", "value": "chile powder"},
                           {"language": "en", "value": "chilli powder"},
                           {"language": "en", "value": "chili powder blend"}]},
        "descriptions": {"en": {"language": "en", "value": "spice"}},
        "claims": {
            "P279": [{"mainsnak": {"datatype": "wikibase-item",
                                   "datavalue": {"value": {"id": "Q42527"}}}}],
            "P2734": [{"mainsnak": {"datatype": "external-id",
                                    "datavalue": {"value": "gochugaru-id"}}}],
        },
    },
    "Q123924322": {
        "type": "item", "id": "Q123924322",
        "labels": {"en": {"language": "en", "value": "xawaash"}},
        "aliases": {}, "descriptions": {},
        "claims": {"P279": [{"mainsnak": {"datatype": "wikibase-item",
                                          "datavalue": {"value": {"id": "Q1521067"}}}}]},
    },
    "Q999999999": {"id": "Q999999999", "missing": ""},
}}


def test_wd_keeps_every_language_label():
    entries, _, _ = fs.parse_wd_entities(WD_FIXTURE)
    g = [e for e in entries if e["entry_id"] == "Q1072946"][0]
    langs = {l["lang"] for l in g["labels"] if l["kind"] == "label"}
    assert langs == {"en", "ko", "ja"}
    assert "고춧가루" in {l["text"] for l in g["labels"]}


def test_wd_keeps_aliases_as_well_as_labels():
    entries, _, _ = fs.parse_wd_entities(WD_FIXTURE)
    g = [e for e in entries if e["entry_id"] == "Q1072946"][0]
    aliases = {l["text"] for l in g["labels"] if l["kind"] == "alias"}
    assert aliases == {"powdered chili", "chile powder", "chilli powder", "chili powder blend"}


def test_the_gochugaru_merge_survives_ingestion_intact():
    """The defect is the finding. Nothing may correct it on the way in."""
    entries, _, _ = fs.parse_wd_entities(WD_FIXTURE)
    g = [e for e in entries if e["entry_id"] == "Q1072946"][0]
    assert g["name"] == "chili powder", "the merged English label must not be repaired"
    assert g["lang"] == "en"
    en = {l["text"] for l in g["labels"] if l["lang"] == "en"}
    assert "chili powder" in en and "chile powder" in en
    ko = [l for l in g["labels"] if l["lang"] == "ko"]
    assert [l["text"] for l in ko] == ["고춧가루"]
    # and the raw record is byte-faithful to what the source returned
    assert json.loads(g["raw"])["labels"]["ko"]["value"] == "고춧가루"


def test_wd_extracts_external_ids_and_subclass_as_xrefs():
    entries, _, _ = fs.parse_wd_entities(WD_FIXTURE)
    g = [e for e in entries if e["entry_id"] == "Q1072946"][0]
    xr = json.loads(g["xrefs"])
    assert xr["P279"] == ["Q42527"]
    assert xr["P2734"] == ["gochugaru-id"]


def test_wd_skips_missing_entities():
    entries, n_rec, _ = fs.parse_wd_entities(WD_FIXTURE)
    assert {e["entry_id"] for e in entries} == {"Q1072946", "Q123924322"}
    assert n_rec == 3, "the missing entity is still counted as a record in the payload"


def test_wd_index_page_excludes_non_items_and_counts_them(conn):
    """The query returns a lexeme sense alongside items. It is excluded and COUNTED."""
    index = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1072946"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q123924322"}},
        {"item": {"value": "http://www.wikidata.org/entity/L1369402-S1"}},
    ]}}
    fs.cmd_wikidata(conn, offline={"index": json.dumps(index).encode(),
                                   "page1": json.dumps(WD_FIXTURE).encode()})
    r = conn.execute("SELECT * FROM source_fetch WHERE page_index=0").fetchone()
    assert r["records_in_payload"] == 3
    assert r["entries_excluded"] == 1, "the lexeme sense must be counted, not silently dropped"
    assert r["entries_written"] == 0, "page 0 is an index and writes no entries"


def test_wd_crawl_has_exactly_one_final_page(conn):
    index = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1072946"}}]}}
    fs.cmd_wikidata(conn, offline={"index": json.dumps(index).encode(),
                                   "page1": json.dumps(WD_FIXTURE).encode()})
    crawl = conn.execute("SELECT crawl_id FROM source_fetch LIMIT 1").fetchone()["crawl_id"]
    finals = conn.execute(
        "SELECT COUNT(*) FROM source_fetch WHERE crawl_id=? AND is_final_page=1",
        (crawl,)).fetchone()[0]
    assert finals == 1
    pages = [r[0] for r in conn.execute(
        "SELECT page_index FROM source_fetch WHERE crawl_id=? ORDER BY page_index", (crawl,))]
    assert pages == list(range(len(pages))), "page indices must be contiguous from 0"


def test_wd_stored_query_is_the_item_query_not_the_broken_label_query(conn):
    """The label-paged form 502s and 504s. The catalogue must hold what actually runs."""
    q = conn.execute("SELECT query_text FROM source_catalogue WHERE source='wikidata'"
                     ).fetchone()["query_text"]
    assert "ORDER BY" in q
    assert "skos:altLabel" not in q, "the stored query must be the runnable item query"
    assert "wdt:P279* wd:Q2095" in q


# ── AGROVOC ─────────────────────────────────────────────────────────────────────────────

# Shaped like the real response: rows grouped by concept, prefLabel plus altLabels.
# asafoetida is the real one, c_a7a129af, and it is one of only two of the ten collapse
# terms AGROVOC carries at all.
AG_FIXTURE = {"results": {"bindings": [
    {"c": {"value": "http://aims.fao.org/aos/agrovoc/c_a7a129af"},
     "kind": {"value": "prefLabel"}, "t": {"value": "asafoetida", "xml:lang": "en"}},
    {"c": {"value": "http://aims.fao.org/aos/agrovoc/c_a7a129af"},
     "kind": {"value": "altLabel"}, "t": {"value": "hing", "xml:lang": "en"}},
    {"c": {"value": "http://aims.fao.org/aos/agrovoc/c_a7a129af"},
     "kind": {"value": "altLabel"}, "t": {"value": "devil's dung", "xml:lang": "en"}},
    {"c": {"value": "http://aims.fao.org/aos/agrovoc/c_809befad"},
     "kind": {"value": "prefLabel"}, "t": {"value": "pekmez", "xml:lang": "en"}},
]}}


def test_agrovoc_groups_rows_into_concepts():
    entries, present, _ = fs.parse_agrovoc(AG_FIXTURE)
    assert present == 2
    assert {e["entry_id"] for e in entries} == {"c_a7a129af", "c_809befad"}


def test_agrovoc_keeps_the_sources_own_label_words():
    """prefLabel and altLabel are SKOS's words. Normalising them would be merging."""
    entries, _, _ = fs.parse_agrovoc(AG_FIXTURE)
    a = [e for e in entries if e["entry_id"] == "c_a7a129af"][0]
    kinds = {l["kind"] for l in a["labels"]}
    assert kinds == {"prefLabel", "altLabel"}
    assert {l["text"] for l in a["labels"] if l["kind"] == "altLabel"} == {"hing", "devil's dung"}
    assert a["name"] == "asafoetida"
    assert sum(l["is_preferred"] for l in a["labels"]) == 1


def test_agrovoc_counts_concepts_with_no_english_label(conn):
    """A page requests 5,000 concepts; those with no English label yield no rows."""
    entries, present, excluded = fs.parse_agrovoc(AG_FIXTURE, requested=10)
    assert (present, excluded) == (2, 8), "the 8 silent ones must be counted, not ignored"


def test_agrovoc_pages_by_concept_not_by_label():
    """Label paging splits a concept across a boundary and writes it twice."""
    assert "SELECT DISTINCT ?c" in fs.AGROVOC_QUERY
    inner = fs.AGROVOC_QUERY.index("SELECT DISTINCT ?c")
    assert fs.AGROVOC_QUERY.index("LIMIT", inner) > inner, "LIMIT must sit in the concept subquery"
    assert "ORDER BY ?c" in fs.AGROVOC_QUERY


def test_agrovoc_fetches_exactly_the_licensed_six(conn):
    """The license IS the filter. Six FAO languages in, the other 36 never fetched."""
    assert fs.AGROVOC_LICENSED_LANGS == ("en", "fr", "es", "ar", "ru", "zh")
    for lg in fs.AGROVOC_LICENSED_LANGS:
        assert f'"{lg}"' in fs.AGROVOC_QUERY, f"{lg} is licensed and must be fetched"
    for lg in ("de", "it", "ja", "hi", "pt", "tr"):
        assert f'"{lg}"' not in fs.AGROVOC_QUERY, f"{lg} is NOT covered and must not be fetched"
    r = conn.execute("SELECT license, notes FROM source_catalogue WHERE source='agrovoc'").fetchone()
    assert "en, fr, es, ar, ru, zh" in r["license"]
    for lang in ("English", "French", "Spanish", "Arabic", "Russian", "Chinese"):
        assert lang in r["notes"], f"{lang} must be named as part of the licensed subset"
    assert "36" in r["notes"], "the uncovered remainder must be stated"


def test_the_earlier_english_only_run_is_recorded_as_the_narrower_choice():
    """It was a choice, not an obligation, and the record has to say which."""
    assert "17.9%" in fs.AGROVOC_FILTER
    assert "NOT covered" in fs.AGROVOC_FILTER
    assert "narrower choice" in fs.AGROVOC_FILTER.lower()


def test_agrovoc_lang_is_bound_not_assumed(conn):
    """?lang is projected by the query, and a concept may have no English label at all."""
    assert "BIND(LANG(?t) AS ?lang)" in fs.AGROVOC_QUERY
    assert "ORDER BY ?c ?kind ?lang ?t" in fs.AGROVOC_QUERY
    fixture = {"results": {"bindings": [
        {"c": {"value": "http://aims.fao.org/aos/agrovoc/c_x"},
         "kind": {"value": "prefLabel"}, "lang": {"value": "ar"},
         "t": {"value": "\u0627\u0644\u062d\u0644\u062a\u064a\u062a", "xml:lang": "ar"}}]}}
    entries, _, _ = fs.parse_agrovoc(fixture)
    assert entries[0]["lang"] == "ar", "lang must come from the row, not be hardcoded to en"


def test_agrovoc_crawl_pages_and_final_flag(conn):
    pages = {f"page{i}": json.dumps(AG_FIXTURE).encode() for i in range(3)}
    fs.cmd_agrovoc(conn, offline=pages, limit_pages=3)
    rows = conn.execute("SELECT page_index, is_final_page FROM source_fetch "
                        "WHERE source='agrovoc' ORDER BY page_index").fetchall()
    assert [r["page_index"] for r in rows] == [0, 1, 2]
    assert sum(r["is_final_page"] for r in rows) == 1
    assert rows[-1]["is_final_page"] == 1


# ── Wikipedia redirects ─────────────────────────────────────────────────────────────────

# Real shape, including the case that matters: gochugaru's article is "Korean chili
# pepper", which is the merge Wikidata gets wrong.
WP_FIXTURE = {"query": {"pages": [
    {"pageid": 111, "title": "Korean chili pepper", "redirects": [
        {"title": "Gochugaru"}, {"title": "Gochu-garu"}, {"title": "Kochugaru"},
        {"title": "Korean hot pepper"}]},
    {"pageid": 222, "title": "Doubanjiang", "redirects": [
        {"title": "豆瓣酱"}, {"title": "Broad bean paste"}]},
    {"pageid": 333, "title": "Xawaash"},
    {"title": "Lu bao", "missing": True},
]}}


def test_wp_redirects_become_labels():
    entries, _, _ = fs.parse_wp_redirects(WP_FIXTURE)
    k = [e for e in entries if e["name"] == "Korean chili pepper"][0]
    kinds = {l["kind"] for l in k["labels"]}
    assert kinds == {"article_title", "redirect"}
    assert {l["text"] for l in k["labels"] if l["kind"] == "redirect"} == {
        "Gochugaru", "Gochu-garu", "Kochugaru", "Korean hot pepper"}
    assert sum(l["is_preferred"] for l in k["labels"]) == 1


def test_wp_keeps_native_script_redirects():
    entries, _, _ = fs.parse_wp_redirects(WP_FIXTURE)
    d = [e for e in entries if e["name"] == "Doubanjiang"][0]
    assert "豆瓣酱" in {l["text"] for l in d["labels"]}


def test_wp_article_with_no_redirects_is_still_written():
    """'Known and unaliased' is a different fact from 'absent'."""
    entries, _, _ = fs.parse_wp_redirects(WP_FIXTURE)
    x = [e for e in entries if e["name"] == "Xawaash"][0]
    assert [l["kind"] for l in x["labels"]] == ["article_title"]


def test_wp_missing_pages_are_counted_not_dropped():
    entries, n_rec, n_exc = fs.parse_wp_redirects(WP_FIXTURE)
    assert n_rec == 4 and n_exc == 1 and len(entries) == 3


def test_wp_carries_the_qid_as_an_xref_not_as_a_merge():
    entries, _, _ = fs.parse_wp_redirects(WP_FIXTURE, {"Korean chili pepper": "Q1072946"})
    k = [e for e in entries if e["name"] == "Korean chili pepper"][0]
    assert json.loads(k["xrefs"])["qid"] == "Q1072946"


def test_redirects_never_write_into_wikidata_tables(conn):
    """The gochugaru merge must stay visible. Folding these in would repair it silently."""
    conn.execute(
        "INSERT INTO source_fetch (source,dataset,url,license,attribution,fetched_at,"
        "bytes,sha256,crawl_id) VALUES ('wikidata','food_items_q2095','u','CC0','a',"
        "'2026-08-23T00:00:00Z',1,'h','c0')")
    fid = conn.execute("SELECT id FROM source_fetch").fetchone()[0]
    conn.execute("INSERT INTO wikidata_entry (fetch_id,entry_id,name,lang,raw) "
                 "VALUES (?,?,?,?,?)", (fid, "Q1072946", "chili powder", "en", "{}"))
    before = conn.execute("SELECT COUNT(*) FROM wikidata_label").fetchone()[0]
    fs.cmd_wikipedia_redirect(conn, offline={
        "sitelinks": json.dumps({"entities": {"Q1072946": {
            "sitelinks": {"enwiki": {"title": "Korean chili pepper"}}}}}),
        "page0": json.dumps(WP_FIXTURE).encode()})
    after = conn.execute("SELECT COUNT(*) FROM wikidata_label").fetchone()[0]
    assert before == after, "redirects leaked into wikidata_label"
    assert conn.execute("SELECT COUNT(*) FROM wikipedia_redirect_label").fetchone()[0] > 0
    # and the Wikidata merge is untouched
    assert conn.execute("SELECT name FROM wikidata_entry WHERE entry_id='Q1072946'"
                        ).fetchone()[0] == "chili powder"


# ── the catalogue as a decision record ──────────────────────────────────────────────────

def test_declines_are_catalogued_with_reason_and_score(conn):
    rows = conn.execute("SELECT * FROM source_catalogue WHERE status='declined'").fetchall()
    assert len(rows) == 7
    for r in rows:
        assert r["decision_reason"], f"{r['source']}/{r['dataset']} declined without a reason"
        assert r["probe_score"], f"{r['source']}/{r['dataset']} declined without a score"


def test_foodons_decline_is_recorded_as_structural(conn):
    r = conn.execute("SELECT * FROM source_catalogue WHERE source='foodon'").fetchone()
    assert r["status"] == "declined"
    assert "DISHES" in r["decision_reason"] and "INGREDIENTS" in r["decision_reason"]
    assert "GENEPIO" in r["decision_reason"], "the za'atar hit was a different ontology"


def test_commons_decline_carries_its_caveat(conn):
    r = conn.execute("SELECT * FROM source_catalogue WHERE source='wikimedia_commons'").fetchone()
    assert r["status"] == "declined" and r["probe_score"] == "0/10"
    assert r["probe_caveat"], "the weaker measurement must be flagged for a future pass"
    assert "re-probe" in r["probe_caveat"].lower()


def test_license_declines_were_not_measured(conn):
    for src in ("recipenlg", "recipe1m", "gs1"):
        r = conn.execute("SELECT * FROM source_catalogue WHERE source=?", (src,)).fetchone()
        assert r["probe_score"] == "not measured", "license comes before coverage"
        assert "LICENSE" in r["decision_reason"].upper()


def test_share_alike_sources_are_flagged(conn):
    rows = conn.execute("SELECT source, dataset FROM source_catalogue WHERE share_alike=1").fetchall()
    got = {(r["source"], r["dataset"]) for r in rows}
    assert got == {("wiktextract", "enwiktionary_senses"),
                   ("wiktextract", "zhwiktionary_senses"),
                   ("wikipedia_redirect", "enwiki_food_redirects")}


def test_foodon_has_no_tables_now_that_it_is_declined(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "foodon_entry" not in names and "foodon_label" not in names


# ── resume ──────────────────────────────────────────────────────────────────────────────

def test_unfinished_crawl_is_detected_and_resumed_from(conn):
    """A crawl with no final page did not finish. That is what the page rows are for."""
    cat = fs.catalogue_row(conn, "wikipedia_redirect", "enwiki_food_redirects")
    for i in range(3):
        fs.record_page(conn, cat, b"x", crawl_id="wp-partial", page_index=i, is_final=False)
    crawl, nxt = fs.unfinished_crawl(conn, "wikipedia_redirect", "enwiki_food_redirects")
    assert (crawl, nxt) == ("wp-partial", 3), "resume must continue, not restart"


def test_a_finished_crawl_is_not_resumed(conn):
    cat = fs.catalogue_row(conn, "wikipedia_redirect", "enwiki_food_redirects")
    fs.record_page(conn, cat, b"x", crawl_id="wp-done", page_index=0, is_final=True)
    assert fs.unfinished_crawl(conn, "wikipedia_redirect", "enwiki_food_redirects") == (None, 0)


def test_resume_does_not_refetch_completed_pages(conn):
    cat = fs.catalogue_row(conn, "wikipedia_redirect", "enwiki_food_redirects")
    fs.record_page(conn, cat, b"already", crawl_id="wp-partial", page_index=0, is_final=False)
    conn.execute("INSERT INTO source_fetch (source,dataset,url,license,attribution,"
                 "fetched_at,bytes,sha256,crawl_id) VALUES ('wikidata','food_items_q2095',"
                 "'u','CC0','a','2026-08-23T00:00:00Z',1,'h','c0')")
    fid = conn.execute("SELECT id FROM source_fetch WHERE source='wikidata'").fetchone()[0]
    conn.execute("INSERT INTO wikidata_entry (fetch_id,entry_id,name,lang,raw) "
                 "VALUES (?,?,?,?,?)", (fid, "Q1", "x", "en", "{}"))
    before = conn.execute("SELECT COUNT(*) FROM source_fetch WHERE crawl_id='wp-partial'"
                          ).fetchone()[0]
    fs.cmd_wikipedia_redirect(conn, offline={
        "sitelinks": json.dumps({"entities": {"Q1": {
            "sitelinks": {"enwiki": {"title": "Korean chili pepper"}}}}}),
        "page0": json.dumps(WP_FIXTURE).encode()})
    rows = conn.execute("SELECT page_index FROM source_fetch WHERE crawl_id='wp-partial' "
                        "ORDER BY page_index").fetchall()
    assert before == 1 and len(rows) == 1, "page 0 was already done and must not be refetched"


def test_rate_limiting_is_retried_not_fatal():
    """A 429 is the server asking to slow down, not an error to die on."""
    import inspect
    src = inspect.getsource(fs.fetch_bytes)
    assert "429" in src and "Retry-After" in src
    assert "tries" in inspect.signature(fs.fetch_bytes).parameters


# ── per-edition filters, and the pragma guard ───────────────────────────────────────────

def test_each_wiktextract_edition_gets_its_own_filter():
    """An English gloss word list against a Chinese dump keeps 386 of 2,916,811."""
    assert fs.wikt_filter_for("enwiktionary_senses")[0] is fs._wikt_keep
    assert fs.wikt_filter_for("zhwiktionary_senses")[0] is fs._wikt_keep_zh


def test_zh_filter_keeps_an_entry_with_no_gloss():
    """豆瓣醬 has an empty gloss. Only the language arm of the union can see it."""
    assert fs._wikt_keep_zh({"word": "豆瓣醬", "lang_code": "zh", "senses": [{"glosses": []}]})


def test_zh_filter_keeps_a_chinese_gloss_on_a_non_chinese_entry():
    """고춧가루 is a KOREAN entry glossed 辣椒粉. The language arm misses it."""
    rec = {"word": "고춧가루", "lang_code": "ko", "senses": [{"glosses": ["辣椒粉"]}]}
    assert fs._wikt_keep_zh(rec)
    assert not fs._wikt_keep(rec), "the English filter would have dropped it"


def test_zh_criterion_records_the_recall_tradeoff():
    f = fs.ZH_FILTER
    assert "LANGUAGE FILTER RATHER THAN A SEMANTIC ONE" in f
    assert "mostly non-food" in f and "3x the English food slice" in f
    assert "RECALL WAS CHOSEN" in f
    assert "豆瓣醬" in f and "阿魏" in f, "the two terms precision would have dropped"


def test_every_entry_point_turns_foreign_keys_on():
    """PRAGMA foreign_keys defaults to OFF, so every ON DELETE CASCADE is opt-in.

    An ad-hoc cleanup script that forgot it left 11 orphaned payload rows holding
    2.83 GB, and the store looked clean while carrying them.
    """
    for mod in ("build_sources_db.py", "fetch_sources.py"):
        src = (REPO / mod).read_text()
        assert "PRAGMA foreign_keys = ON" in src, f"{mod} does not enable cascades"


def test_no_orphans_in_a_freshly_built_store(conn):
    pairs = [("source_payload", "fetch_id", "source_fetch", "id")]
    for t in ENTRY_PREFIXES_FETCH:
        pairs.append((f"{t}_entry", "fetch_id", "source_fetch", "id"))
        pairs.append((f"{t}_label", "entry_pk", f"{t}_entry", "pk"))
    for child, ck, parent, pk in pairs:
        n = conn.execute(
            f"SELECT COUNT(*) FROM {child} WHERE {ck} NOT IN (SELECT {pk} FROM {parent})"
        ).fetchone()[0]
        assert n == 0, f"{child} has {n} orphans"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
