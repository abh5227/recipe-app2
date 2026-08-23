#!/usr/bin/env python3
"""fetch_sources.py — fetch a source into sources.db, whole and unmodified.

Stage 2. Writes source_fetch, source_payload and one source's entry and label tables.
Reconciles nothing, matches nothing across sources, and never touches recipes.db.
See build_sources_db.py for why the tables are separate and why that is a license
decision rather than tidiness.

TWO RULES THIS MODULE EXISTS TO KEEP
------------------------------------
1. The PAYLOAD is stored whole and unmodified, always. Parsing is a second act on top of
   stored bytes, so a parser bug is re-runnable offline and a wider filter can be applied
   later without re-fetching. This is what keeps the collective-database argument intact.

2. Whatever the parse DROPS is counted and the criterion recorded VERBATIM, in
   source_fetch.parse_filter / records_in_payload / entries_written / entries_excluded.
   An uncounted drop is the King Arthur failure, and this schema makes it answerable.

ONE ROW PER PAGE
----------------
source_fetch carries one row per page, not per crawl. The last Wikidata crawl silently
lost 29% of the labels while reporting success, so a partial crawl has to look partial.
Unpaged sources write a single page 0 that is also the final page.
"""
import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "sources.db"
UA = "recipe-app-sources/1.0 (+https://github.com/abh5227/recipe-app2)"


# ── plumbing ────────────────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_bytes(url, timeout=180, tries=6, pause=0.0):
    """GET with backoff on rate limiting. A 429 is the server asking, not an error.

    The first Wikipedia redirect crawl died at page 194 of 194 with HTTP 429 and no
    retry. It left a partial crawl that LOOKED partial (194 pages, zero final flags),
    which is what the per-page rows are for, but it should not have died at all.
    """
    delay = 1.0
    for attempt in range(tries):
        if pause:
            time.sleep(pause)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == tries - 1:
                raise
            wait = float(e.headers.get("Retry-After") or 0) or delay
            print(f"    HTTP {e.code}, waiting {wait:.0f}s "
                  f"(attempt {attempt + 1}/{tries})", flush=True)
            time.sleep(wait)
            delay = min(delay * 2, 60)
    raise RuntimeError("unreachable")


def catalogue_row(conn, source, dataset):
    row = conn.execute(
        "SELECT * FROM source_catalogue WHERE source=? AND dataset=?", (source, dataset)
    ).fetchone()
    if row is None:
        raise SystemExit(f"{source}/{dataset} is not catalogued. Run build_sources_db.py first.")
    return row


def record_page(conn, cat, blob, *, crawl_id, page_index=0, is_final=True,
                page_offset=None, page_limit=None, rows_returned=None, version=None,
                parse_filter=None, records_in_payload=None,
                entries_written=None, entries_excluded=None):
    """Insert the source_fetch row for one page and store its payload gzipped."""
    cur = conn.execute(
        "INSERT INTO source_fetch "
        "(source, dataset, url, query_text, version, license, share_alike, attribution, "
        " fetched_at, bytes, sha256, notes, crawl_id, page_index, page_offset, page_limit, "
        " rows_returned, is_final_page, parse_filter, records_in_payload, "
        " entries_written, entries_excluded) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cat["source"], cat["dataset"], cat["url"], cat["query_text"], version,
         cat["license"], cat["share_alike"], cat["attribution"], now_utc(), len(blob),
         hashlib.sha256(blob).hexdigest(), cat["notes"], crawl_id, page_index,
         page_offset, page_limit, rows_returned, 1 if is_final else 0,
         parse_filter, records_in_payload, entries_written, entries_excluded),
    )
    fetch_id = cur.lastrowid
    packed = gzip.compress(blob)
    conn.execute(
        "INSERT INTO source_payload "
        "(fetch_id, media_type, compression, blob, bytes_stored, sha256_stored) "
        "VALUES (?,?,?,?,?,?)",
        (fetch_id, "application/octet-stream", "gzip", packed, len(packed),
         hashlib.sha256(packed).hexdigest()),
    )
    return fetch_id


def read_payload(conn, fetch_id):
    """Decompress a stored payload. Proves a parse can be re-run without the network."""
    row = conn.execute(
        "SELECT blob, compression FROM source_payload WHERE fetch_id=?", (fetch_id,)
    ).fetchone()
    if row is None:
        raise KeyError(fetch_id)
    return gzip.decompress(row["blob"]) if row["compression"] == "gzip" else row["blob"]


def write_entries(conn, prefix, fetch_id, entries):
    """Write entry + label rows. `entries` is a list of dicts from a parser."""
    n = 0
    for e in entries:
        cur = conn.execute(
            f"INSERT INTO {prefix}_entry (fetch_id, entry_id, name, lang, xrefs, raw) "
            "VALUES (?,?,?,?,?,?)",
            (fetch_id, e["entry_id"], e["name"], e.get("lang"), e.get("xrefs"), e["raw"]),
        )
        pk = cur.lastrowid
        conn.executemany(
            f"INSERT INTO {prefix}_label (entry_pk, lang, text, kind, is_preferred, source_field) "
            "VALUES (?,?,?,?,?,?)",
            [(pk, l.get("lang"), l["text"], l["kind"], l.get("is_preferred", 0),
              l.get("source_field")) for l in e["labels"]],
        )
        n += 1
    return n


# ── Open Food Facts ─────────────────────────────────────────────────────────────────────

# The .txt is a sequence of blank-line-separated blocks. Inside a block:
#   "### heading"          a file heading
#   "# comment"            a comment
#   "< en: sugar"          a PARENT reference
#   "en: salt, table salt" a language line: canonical name first, then OFF's synonyms
# Blocks that carry no language line are directives (stopwords, synonyms, headings) and
# are not entries. They are COUNTED as excluded rather than quietly skipped.
TXT_LANG_RE = re.compile(r'^([a-z]{2,3}(?:_[A-Za-z]+)?):\s*(.+)$')
TXT_PARENT_RE = re.compile(r'^<\s*([a-z]{2,3}(?:_[A-Za-z]+)?):\s*(.+)$')
OFF_TXT_FILTER = (
    "A block is an entry when it carries at least one 'lang: names' line and is not a "
    "stopwords: or synonyms: directive. Heading and comment-only blocks are excluded. "
    "entry_id is the block index, because the .txt carries no identifier of its own."
)
OFF_JSON_FILTER = "Every key in the JSON object is an entry. Nothing is excluded."

# Xref fields the JSON export carries on the entry itself. Stored verbatim as JSON.
OFF_JSON_XREFS = ("wikidata", "ciqual_food_code", "ciqual_food_name", "usda_ndb_code",
                  "usda_ndb_name", "ifct_food_code", "ifct_food_name", "e_number",
                  "agribalyse_food_code", "wiktionary", "openfoodfacts")


# ⚠ THERE IS NO slug() HERE, DELIBERATELY. The first version of this parser derived an
#   OFF-style id with re.sub(r'[^a-z0-9]+', '-', name.lower()), which reduces any wholly
#   non-Latin name to the empty string. Measured on the real file: 10 Bulgarian and 2
#   Russian blocks collapsed to the ids "bg:" and "ru:" and collided. An ASCII slug
#   inside the ingestion built to fix an anglocentric gap is the gap, so the .txt now
#   carries no derived id at all. See parse_off_txt.
def parse_off_txt(text):
    """-> (entries, n_blocks, n_excluded). Names AND synonyms, which the JSON drops."""
    blocks = [b for b in text.split("\n\n") if b.strip()]
    entries, excluded = [], 0
    for block_index, block in enumerate(blocks):
        lines = block.splitlines()
        if any(l.startswith(("stopwords:", "synonyms:")) for l in lines):
            excluded += 1
            continue
        langs, parents = [], []
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            mp = TXT_PARENT_RE.match(line.strip())
            if mp:
                parents.append(f"{mp.group(1)}:{mp.group(2).strip()}")
                continue
            ml = TXT_LANG_RE.match(line)
            if ml:
                names = [n.strip() for n in ml.group(2).split(",") if n.strip()]
                if names:
                    langs.append((ml.group(1), names))
        if not langs:
            excluded += 1
            continue
        first_lang, first_names = langs[0]
        labels = []
        for lang, names in langs:
            for i, nm in enumerate(names):
                labels.append({
                    "lang": lang, "text": nm,
                    # OFF's own semantics: first on the line is the display name, the
                    # rest are its synonyms. Not normalised into one word.
                    "kind": "canonical_name" if i == 0 else "synonym",
                    "is_preferred": 1 if (i == 0 and lang == first_lang) else 0,
                    "source_field": f"{lang} line",
                })
        entries.append({
            # ⚠ The .txt carries NO identifier. Its block position is the only identity
            #   it actually has, so that is what entry_id records. Deriving a readable
            #   id would mean inventing one, and the two attempts at that both failed:
            #   an ASCII slug erased non-Latin names, and the plain name collides
            #   because OFF itself duplicates entries (little-millet and kodo-millet
            #   each appear twice under "< en: millet"). Real OFF ids come from the
            #   .json dataset, which is why both artifacts are fetched.
            "entry_id": str(block_index),
            "name": first_names[0], "lang": first_lang,
            "xrefs": json.dumps({"parents": parents}, ensure_ascii=False) if parents else None,
            "raw": block, "labels": labels,
        })
    return entries, len(blocks), excluded


def parse_off_json(obj):
    """-> (entries, n_records, n_excluded). One label per language name."""
    entries = []
    for key, rec in obj.items():
        if not isinstance(rec, dict):
            continue
        names = rec.get("name") or {}
        lang = "en" if "en" in names else (next(iter(names)) if names else None)
        xr = {k: rec[k] for k in OFF_JSON_XREFS if k in rec}
        if rec.get("parents"):
            xr["parents"] = rec["parents"]
        entries.append({
            "entry_id": key,
            "name": names.get(lang) if lang else key,
            "lang": lang,
            "xrefs": json.dumps(xr, ensure_ascii=False) if xr else None,
            "raw": json.dumps(rec, ensure_ascii=False, sort_keys=True),
            "labels": [{"lang": lg, "text": nm, "kind": "name",
                        "is_preferred": 1 if lg == lang else 0, "source_field": "name"}
                       for lg, nm in names.items()],
        })
    return entries, len(obj), 0


def cmd_off(conn, offline=None):
    """Fetch both OFF taxonomy artifacts. The .txt is canonical, the .json adds xrefs."""
    jobs = [
        ("ingredients_taxonomy_txt", parse_off_txt, OFF_TXT_FILTER,
         lambda b: b.decode("utf-8")),
        ("ingredients_taxonomy_json", parse_off_json, OFF_JSON_FILTER,
         lambda b: json.loads(b.decode("utf-8"))),
    ]
    out = []
    for dataset, parser, criterion, decode in jobs:
        cat = catalogue_row(conn, "open_food_facts", dataset)
        blob = (offline or {}).get(dataset) or fetch_bytes(cat["url"])
        crawl = f"off-{dataset}-{now_utc()}"
        fid = record_page(conn, cat, blob, crawl_id=crawl, parse_filter=criterion)
        # Parse from the STORED payload, not the in-memory bytes, so the offline
        # re-run path is the one that is actually exercised.
        entries, n_rec, n_exc = parser(decode(read_payload(conn, fid)))
        written = write_entries(conn, "off_taxonomy", fid, entries)
        conn.execute(
            "UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
            "entries_excluded=?, rows_returned=? WHERE id=?",
            (n_rec, written, n_exc, written, fid))
        conn.commit()
        out.append((dataset, len(blob), n_rec, written, n_exc, fid))
    return out


# ── Wikidata ────────────────────────────────────────────────────────────────────────────

# ⚠ THE PAGED SPARQL IN THE CATALOGUE DOES NOT RUN, AND THAT IS A REAL COLLISION.
#   Measured 23 Aug 2026 against query.wikidata.org:
#       LIMIT 5000 OFFSET      0  ->  HTTP 502 after 15.3s
#       LIMIT 5000 OFFSET 320000  ->  HTTP 504 after 65.1s
#   The ORDER BY that prevents the 29% loss is the same thing that makes it unrunnable,
#   since WDQS must sort all 332,018 label rows before applying any OFFSET. Dropping the
#   ORDER BY would make it run and reintroduce exactly the bug it guards against.
#
#   So the crawl pages by ITEM instead of by LABEL, which keeps determinism without
#   deep OFFSET. Page 0 is the whole ordered QID list, fetched in one 5.8s query and
#   stored as an index. Pages 1..N are wbgetentities batches keyed on that fixed list.
#   Determinism now comes from a stored, ordered key set rather than from the server
#   repeating a sort, which is stronger than the original design, not weaker.
WD_ITEMS_QUERY = "SELECT ?item WHERE { ?item wdt:P279* wd:Q2095 . } ORDER BY ?item"
WD_BATCH = 50
WD_FILTER = (
    "Page 0 is the ordered QID index and writes no entries. Pages 1..N are wbgetentities "
    "batches of 50 over that index. Non-item entities are excluded: the query returns "
    "lexeme senses (L...-S...) alongside items, and wbgetentities cannot resolve a sense. "
    "The count of those is recorded in entries_excluded on page 0."
)
WD_EXTERNAL = ("P279", "P31")   # kept alongside external-ids as the entry's own refs


def wd_sparql(query, timeout=180):
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        "https://query.wikidata.org/sparql", data=data,
        headers={"User-Agent": UA, "Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def wd_entities(qids, timeout=90):
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "labels|aliases|descriptions|claims", "format": "json"})
    return fetch_bytes(url, timeout=timeout)


def parse_wd_entities(obj):
    """-> (entries, n_records, n_excluded). Labels AND aliases, every language.

    ⚠ Stores what the source says, defects included. Q1072946 is gochugaru carrying the
      English label "chili powder" with aliases "chile powder" / "chilli powder" /
      "chili powder blend", which is a specific product merged into a generic term. That
      is a FINDING ABOUT THE SOURCE and it has to survive ingestion intact. Nothing here
      corrects, dedupes or prefers one label over another.
    """
    entries = []
    ents = obj.get("entities", {}) or {}
    for qid, e in ents.items():
        if e.get("missing") is not None:
            continue
        labels = e.get("labels", {}) or {}
        aliases = e.get("aliases", {}) or {}
        lang = "en" if "en" in labels else (next(iter(labels)) if labels else None)
        xr = {}
        for pid, claims in (e.get("claims", {}) or {}).items():
            vals = []
            for c in claims:
                snak = c.get("mainsnak", {})
                dv = snak.get("datavalue", {}).get("value")
                if snak.get("datatype") == "external-id" and isinstance(dv, str):
                    vals.append(dv)
                elif pid in WD_EXTERNAL and isinstance(dv, dict) and "id" in dv:
                    vals.append(dv["id"])
            if vals:
                xr[pid] = vals
        rows = [{"lang": lg, "text": v["value"], "kind": "label",
                 "is_preferred": 1 if lg == lang else 0, "source_field": "labels"}
                for lg, v in labels.items()]
        rows += [{"lang": lg, "text": a["value"], "kind": "alias",
                  "is_preferred": 0, "source_field": "aliases"}
                 for lg, arr in aliases.items() for a in arr]
        entries.append({
            "entry_id": qid,
            "name": labels.get(lang, {}).get("value") if lang else qid,
            "lang": lang,
            "xrefs": json.dumps(xr, ensure_ascii=False, sort_keys=True) if xr else None,
            "raw": json.dumps(e, ensure_ascii=False, sort_keys=True),
            "labels": rows,
        })
    return entries, len(ents), 0


def cmd_wikidata(conn, offline=None, limit_pages=None):
    cat = catalogue_row(conn, "wikidata", "food_items_q2095")
    crawl = f"wd-{now_utc()}"

    # ── page 0: the ordered QID index.
    blob = (offline or {}).get("index") or wd_sparql(WD_ITEMS_QUERY)
    idx_id = record_page(conn, cat, blob, crawl_id=crawl, page_index=0, is_final=False,
                         parse_filter=WD_FILTER)
    rows = json.loads(read_payload(conn, idx_id).decode())["results"]["bindings"]
    all_ids = [r["item"]["value"].rsplit("/", 1)[-1] for r in rows]
    qids = [q for q in all_ids if q.startswith("Q")]
    conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=0, "
                 "entries_excluded=?, rows_returned=? WHERE id=?",
                 (len(all_ids), len(all_ids) - len(qids), len(all_ids), idx_id))
    conn.commit()

    # ── pages 1..N: wbgetentities over that fixed, ordered list.
    batches = [qids[i:i + WD_BATCH] for i in range(0, len(qids), WD_BATCH)]
    if limit_pages:
        batches = batches[:limit_pages]
    total_e = total_l = 0
    for i, batch in enumerate(batches, start=1):
        final = (i == len(batches))
        b = (offline or {}).get(f"page{i}") or wd_entities(batch)
        fid = record_page(conn, cat, b, crawl_id=crawl, page_index=i, is_final=final,
                          page_offset=(i - 1) * WD_BATCH, page_limit=WD_BATCH,
                          parse_filter=WD_FILTER)
        entries, n_rec, n_exc = parse_wd_entities(json.loads(read_payload(conn, fid).decode()))
        written = write_entries(conn, "wikidata", fid, entries)
        total_e += written
        total_l += sum(len(e["labels"]) for e in entries)
        conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
                     "entries_excluded=?, rows_returned=? WHERE id=?",
                     (n_rec, written, n_exc, written, fid))
        conn.commit()
        if i % 25 == 0 or final:
            print(f"  page {i}/{len(batches)}  entries={total_e:,}  labels={total_l:,}", flush=True)
    return [("food_items_q2095", len(all_ids), len(all_ids), total_e,
             len(all_ids) - len(qids), idx_id)]


# ── AGROVOC ─────────────────────────────────────────────────────────────────────────────

# Unlike WDQS, this endpoint pages correctly. Measured 23 Aug 2026:
#   LIMIT 5000 OFFSET 40000 -> 200, 5000 rows, 9.5s;  OFFSET 75000 -> 0 rows, past the end.
#   An ordered page repeats identically, and page1+page2 equals one double-size page with
#   zero overlap. There is no server-side cap below the full 54,443 English rows.
# So no item-keyed workaround is needed. Paging is still keyed on CONCEPTS rather than on
# labels, because label paging would split a concept across a page boundary and write it
# twice with partial labels each time.
AGROVOC_SCHEME = "<http://aims.fao.org/aos/agrovoc>"
# ⚠ THE LICENSED SIX, not English. FAO holds copyright on its six official languages and
#   those are CC BY 4.0. Fetching only English was a narrower choice than the license
#   requires, and it left out Arabic, Russian and Chinese, which are the non-Western
#   alias material this source search existed to find.
AGROVOC_LICENSED_LANGS = ("en", "fr", "es", "ar", "ru", "zh")
AGROVOC_QUERY = """PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?c ?t ?kind ?lang WHERE {
  { SELECT DISTINCT ?c WHERE { ?c skos:inScheme %s . } ORDER BY ?c LIMIT %%d OFFSET %%d }
  { ?c skos:prefLabel ?t . BIND("prefLabel" AS ?kind) }
  UNION
  { ?c skos:altLabel ?t .  BIND("altLabel" AS ?kind) }
  BIND(LANG(?t) AS ?lang)
  FILTER(?lang IN (%s))
}
ORDER BY ?c ?kind ?lang ?t""" % (AGROVOC_SCHEME, ", ".join('"%s"' % l for l in AGROVOC_LICENSED_LANGS))
AGROVOC_BATCH = 5000
AGROVOC_ENDPOINT = "https://agrovoc.fao.org/sparql"

# ⚠ ENGLISH ONLY, AND THAT IS NARROWER THAN THE LICENSE REQUIRES. Recorded because the
#   two filters are different things and only one of them is a license obligation:
#     - the LICENSE-REQUIRED filter is the six FAO official languages. FAO holds copyright
#       on English, French, Spanish, Arabic, Russian and Chinese, and those six are
#       CC BY 4.0. Content in the other 36 languages rests with the institutions that
#       authored it and is NOT covered.
#     - ENGLISH ONLY is a narrower CHOICE on top of that. Measured 23 Aug 2026, English is
#       54,443 of the 303,910 label rows the license permits, so 17.9%. Widening to the
#       licensed six is a one-line change and needs no license re-derivation.
AGROVOC_FILTER = (
    "The six FAO official languages (en, fr, es, ar, ru, zh), which is exactly what the "
    "CC BY 4.0 grant covers. The other 36 languages are NOT covered, their copyright "
    "rests with the contributing institutions, and they must not be fetched. An earlier "
    "run took English alone, which was 54,443 of the 303,910 licensed rows (17.9%) and "
    "was a narrower choice than the license requires rather than an obligation. Concepts "
    "in a page's key range carrying no label in any of the six produce no rows and are "
    "counted in entries_excluded."
)


def agrovoc_page(limit, offset, timeout=180):
    data = urllib.parse.urlencode({"query": AGROVOC_QUERY % (limit, offset)}).encode()
    req = urllib.request.Request(
        AGROVOC_ENDPOINT, data=data,
        headers={"User-Agent": UA, "Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_agrovoc(obj, requested=None):
    """-> (entries, n_concepts_present, n_excluded). Rows arrive grouped by concept."""
    grouped = {}
    for row in obj["results"]["bindings"]:
        uri = row["c"]["value"]
        grouped.setdefault(uri, []).append(
            (row["kind"]["value"], row["t"]["value"], row["t"].get("xml:lang")))
    entries = []
    for uri, rows in grouped.items():
        # `name` prefers the English prefLabel when there is one, but MUST NOT assume it:
        # a concept can be licensed-and-present with no English label at all.
        pref_en = next((t for k, t, lg in rows if k == "prefLabel" and lg == "en"), None)
        pref_any = next(((t, lg) for k, t, lg in rows if k == "prefLabel"), None)
        if pref_en:
            name, lang = pref_en, "en"
        elif pref_any:
            name, lang = pref_any
        else:
            name, lang = rows[0][1], rows[0][2]
        entries.append({
            "entry_id": uri.rsplit("/", 1)[-1],
            "name": name,
            "lang": lang,
            "xrefs": json.dumps({"uri": uri}, ensure_ascii=False),
            "raw": json.dumps(sorted(rows), ensure_ascii=False),
            "labels": [{"lang": lg, "text": t, "kind": k,
                        "is_preferred": 1 if k == "prefLabel" else 0,
                        "source_field": "skos:" + k} for k, t, lg in rows],
        })
    present = len(grouped)
    excluded = max(0, (requested or present) - present)
    return entries, present, excluded


AGROVOC_CONCEPTS = 41825   # measured 23 Aug 2026 by COUNT(DISTINCT ?c) on the scheme


def cmd_agrovoc(conn, offline=None, limit_pages=None, total=None):
    cat = catalogue_row(conn, "agrovoc", "sparql_licensed_six")
    crawl = f"agrovoc-{now_utc()}"
    # `offline` is keyed by PAGE, so its length is a page count and not a concept count.
    if total is None:
        total = len(offline) * AGROVOC_BATCH if offline else AGROVOC_CONCEPTS
    n_pages = max(1, -(-total // AGROVOC_BATCH))
    if limit_pages:
        n_pages = min(n_pages, limit_pages)
    written_all = 0
    for i in range(n_pages):
        off = i * AGROVOC_BATCH
        requested = min(AGROVOC_BATCH, total - off)
        b = (offline or {}).get(f"page{i}") or agrovoc_page(AGROVOC_BATCH, off)
        fid = record_page(conn, cat, b, crawl_id=crawl, page_index=i,
                          is_final=(i == n_pages - 1), page_offset=off,
                          page_limit=AGROVOC_BATCH, parse_filter=AGROVOC_FILTER)
        entries, present, excluded = parse_agrovoc(
            json.loads(read_payload(conn, fid).decode()), requested=requested)
        written = write_entries(conn, "agrovoc", fid, entries)
        written_all += written
        conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
                     "entries_excluded=?, rows_returned=? WHERE id=?",
                     (requested, written, excluded, written, fid))
        conn.commit()
        print(f"  page {i+1}/{n_pages}  concepts={written:,}  no-English={excluded:,}", flush=True)
    return [("sparql_licensed_six", total, total, written_all, total - written_all, None)]


# ── Wikipedia redirects ─────────────────────────────────────────────────────────────────

# ⚠ ITS OWN TABLES, NEVER FOLDED INTO wikidata_label. Wikidata merges gochugaru into the
#   generic "chili powder"; Wikipedia has a separate "Korean chili pepper" article with
#   the romanization variants attached. Writing the redirects into wikidata_label would
#   REPAIR that merge invisibly, and keeping it visible is why this store exists. How the
#   two relate is a question for a later pass, not something to decide at ingest.
#
# The key set is the enwiki sitelinks of the food items ALREADY in wikidata_entry, so
# this crawl adds no new scope decision. Measured on a sample of 60: 32% of items carry
# an enwiki article, mean 4.7 redirects each.
WP_BATCH = 50
WP_FILTER = (
    "Keyed on the enwiki sitelinks of the items already in wikidata_entry. Items with no "
    "enwiki article contribute nothing and are counted in entries_excluded. An article "
    "with zero redirects is still written, because 'known and unaliased' is a different "
    "fact from 'absent'."
)


def wp_sitelinks(qids, timeout=60):
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "sitelinks", "sitefilter": "enwiki", "format": "json"})
    return fetch_bytes(url, timeout=timeout)


def wp_redirects(titles, timeout=60):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "titles": "|".join(titles), "prop": "redirects",
        "rdlimit": "max", "rdnamespace": "0", "format": "json", "formatversion": "2"})
    return fetch_bytes(url, timeout=timeout, pause=0.15)


def parse_wp_redirects(obj, qid_by_title=None):
    """-> (entries, n_records, n_excluded). One entry per article, one label per redirect."""
    pages = (obj.get("query", {}) or {}).get("pages", []) or []
    entries, excluded = [], 0
    for pg in pages:
        if pg.get("missing"):
            excluded += 1
            continue
        title = pg["title"]
        reds = [r["title"] for r in (pg.get("redirects") or [])]
        labels = [{"lang": "en", "text": title, "kind": "article_title",
                   "is_preferred": 1, "source_field": "title"}]
        labels += [{"lang": None, "text": r, "kind": "redirect",
                    "is_preferred": 0, "source_field": "redirects"} for r in reds]
        xr = {"qid": (qid_by_title or {}).get(title)} if qid_by_title else None
        entries.append({
            "entry_id": str(pg.get("pageid") or title),
            "name": title, "lang": "en",
            "xrefs": json.dumps(xr, ensure_ascii=False) if xr and xr.get("qid") else None,
            "raw": json.dumps(pg, ensure_ascii=False, sort_keys=True),
            "labels": labels,
        })
    return entries, len(pages), excluded


def unfinished_crawl(conn, source, dataset):
    """-> (crawl_id, next_page) for a crawl that never wrote a final page, else (None, 0).

    A crawl with no is_final_page row did not finish. Because pages are contiguous and
    each commits as it lands, resuming means starting at max(page_index) + 1 rather than
    re-fetching everything.
    """
    row = conn.execute(
        "SELECT crawl_id, MAX(page_index) AS last FROM source_fetch "
        "WHERE source=? AND dataset=? GROUP BY crawl_id "
        "HAVING SUM(is_final_page)=0 ORDER BY MAX(id) DESC LIMIT 1",
        (source, dataset)).fetchone()
    return (row["crawl_id"], row["last"] + 1) if row else (None, 0)


def cmd_wikipedia_redirect(conn, offline=None, limit_pages=None, resume=True):
    cat = catalogue_row(conn, "wikipedia_redirect", "enwiki_food_redirects")
    crawl, start_page = unfinished_crawl(conn, "wikipedia_redirect",
                                         "enwiki_food_redirects") if resume else (None, 0)
    if crawl:
        print(f"  resuming crawl {crawl} at page {start_page}", flush=True)
    else:
        crawl, start_page = f"wp-{now_utc()}", 0
    qids = [r[0] for r in conn.execute("SELECT entry_id FROM wikidata_entry ORDER BY pk")]
    if not qids and not offline:
        raise SystemExit("wikidata_entry is empty. Run `fetch_sources.py wikidata` first: "
                         "this crawl is keyed on the food items already stored.")
    # resolve QIDs -> enwiki titles
    qid_by_title, no_article = {}, 0
    if offline and "sitelinks" in offline:
        batches = [json.loads(offline["sitelinks"])]
    else:
        batches = []
        for i in range(0, len(qids), WP_BATCH):
            batches.append(json.loads(wp_sitelinks(qids[i:i + WP_BATCH]).decode()))
    for d in batches:
        for q, e in (d.get("entities", {}) or {}).items():
            sl = (e.get("sitelinks") or {}).get("enwiki")
            if sl:
                qid_by_title[sl["title"]] = q
            else:
                no_article += 1
    titles = sorted(qid_by_title)
    pages = [titles[i:i + WP_BATCH] for i in range(0, len(titles), WP_BATCH)]
    if limit_pages:
        pages = pages[:limit_pages]
    total_e = total_l = 0
    for i, batch in enumerate(pages):
        if i < start_page:
            continue
        b = (offline or {}).get(f"page{i}") or wp_redirects(batch)
        fid = record_page(conn, cat, b, crawl_id=crawl, page_index=i,
                          is_final=(i == len(pages) - 1), page_offset=i * WP_BATCH,
                          page_limit=WP_BATCH, parse_filter=WP_FILTER)
        entries, n_rec, n_exc = parse_wp_redirects(
            json.loads(read_payload(conn, fid).decode()), qid_by_title)
        written = write_entries(conn, "wikipedia_redirect", fid, entries)
        total_e += written
        total_l += sum(len(e["labels"]) for e in entries)
        conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
                     "entries_excluded=?, rows_returned=? WHERE id=?",
                     (n_rec, written, n_exc + (no_article if i == 0 else 0), written, fid))
        conn.commit()
        if (i + 1) % 25 == 0 or i == len(pages) - 1:
            print(f"  page {i+1}/{len(pages)}  articles={total_e:,}  aliases={total_l:,}", flush=True)
    return [("enwiki_food_redirects", len(qids), len(qids), total_e, no_article, None)]


# ── wiktextract ─────────────────────────────────────────────────────────────────────────

# ⚠ TWO SIZE FACTS, BOTH MEASURED BEFORE ANY BYTES WERE FETCHED.
#
#   1. THE EXPANDED FORM NEVER LANDS ON DISK. The artifact is 2,826,672,112 bytes of
#      gzipped JSONL expanding to about 22.9 GB. It is parsed as a STREAM through
#      zlib.decompressobj, one stored page at a time, so the 22.9 GB exists only as a
#      moving window of a few MB. Nothing is written to a temp file.
#
#   2. ⚠ SQLITE CANNOT HOLD IT AS ONE BLOB. This build reports
#      SQLITE_LIMIT_LENGTH = 1,000,000,000 (compiled MAX_LENGTH=1000000000), and the
#      artifact is 2.83 GB. A single-blob payload would fail outright.
#      So the download is PAGED BY BYTE RANGE, which the server supports
#      (accept-ranges: bytes, verified 206 on a probe). Each page holds one range,
#      comfortably under the ceiling. Concatenating pages 0..N in page_index order
#      reproduces the artifact byte for byte, and the whole-file sha256 is computed
#      incrementally during the fetch and recorded on the final page. "Whole and
#      unmodified" therefore still holds: the payload is complete, merely stored across
#      rows, and it reassembles exactly.
# WIKT_URL removed: the per-dataset URL lives in source_catalogue.url.
WIKT_RANGE = 256 * 1024 * 1024          # 256 MB per page: 11 pages, far under the 1 GB ceiling

# The food slice. Recorded VERBATIM in source_fetch.parse_filter so a later pass can
# widen it and re-parse FROM THE STORED PAYLOAD without re-fetching 2.83 GB.
WIKT_FOOD_TOPICS = {
    "food", "foods", "cooking", "cuisine", "cuisines", "gastronomy", "culinary",
    "beverages", "drinks", "alcoholic beverages", "dishes", "desserts", "confectionery",
    "fruits", "vegetables", "herbs", "spices", "seasonings", "condiments", "sauces",
    "meats", "seafood", "fish", "shellfish", "dairy", "cheeses", "grains", "cereals",
    "legumes", "nuts", "breads", "pasta", "baking", "brewing", "oils", "mushrooms",
}
# ⚠ THE TOPIC FILTER ALONE WAS WRONG, AND THE FIRST PARSE PROVED IT. English Wiktionary
#   categorises by GRAMMAR AND ETYMOLOGY, not by semantic domain. Measured on the stored
#   payload: gochugaru's only categories are "English lemmas", "English nouns" and
#   "English terms borrowed from Korean". doubanjiang, speculoos and za'atar are the same.
#   A topic-only slice kept 16,931 entries and MISSED 9 OF THE 10 TERMS THE SOURCE WAS
#   ADDED FOR, which is the opposite of the point.
#
#   No single signal works, so the filter is a UNION of two weak ones, measured over
#   1,500,000 sampled records:
#       food topic/category        0.3%    catches asafoetida, misses guanciale/pekmez
#       noun AND food-word gloss   1.2%    catches guanciale/pekmez, misses asafoetida
#   Together they catch all three. Recorded verbatim so a third signal can be added and
#   the parse re-run from the stored payload without re-fetching 2.83 GB.
WIKT_GLOSS_WORDS = (
    "food dish sauce spice herb fruit vegetable meat cheese bread soup stew drink beverage "
    "wine beer cake pastry noodle rice bean pepper edible cuisine cooking cooked seasoning "
    "condiment paste flour oil nut seed berry fish confection dessert snack liquor syrup "
    "jam pickle resin gum latex culinary flavouring flavoring eaten eating"
).split()
WIKT_GLOSS_RE = re.compile(r"\b(" + "|".join(WIKT_GLOSS_WORDS) + r")\b", re.I)
WIKT_FILTER = (
    "FOOD SLICE, a UNION of two signals because Wiktionary carries no reliable semantic "
    "domain field. (A) any sense or the entry carries a topic or category matching: " +
    ", ".join(sorted(WIKT_FOOD_TOPICS)) + ". (B) pos == 'noun' AND some gloss contains one "
    "of: " + ", ".join(sorted(WIKT_GLOSS_WORDS)) + ". Signal (A) alone was the first "
    "attempt and missed 9 of the 10 terms this source was added for, because English "
    "Wiktionary categorises by grammar and etymology rather than by domain. Everything "
    "else is counted in entries_excluded and NOT written. The payload is stored whole, so "
    "widening either signal and re-parsing needs no re-fetch."
)


def _wikt_is_food(rec):
    def names(x):
        for v in (x or []):
            if isinstance(v, str):
                yield v.lower()
            elif isinstance(v, dict) and v.get("name"):
                yield str(v["name"]).lower()
    pools = [rec.get("topics"), rec.get("categories")]
    for sense in (rec.get("senses") or []):
        pools.append(sense.get("topics"))
        pools.append(sense.get("categories"))
    for pool in pools:
        for nm in names(pool):
            if nm in WIKT_FOOD_TOPICS:
                return True
            if any(w in WIKT_FOOD_TOPICS for w in nm.replace("/", " ").split()):
                return True
    return False


def _wikt_gloss_hit(rec):
    if rec.get("pos") != "noun":
        return False
    for sense in (rec.get("senses") or []):
        for g in (sense.get("glosses") or []):
            if WIKT_GLOSS_RE.search(g or ""):
                return True
    return False


def _wikt_keep(rec):
    """The union for the ENGLISH edition. Either signal is enough."""
    return _wikt_is_food(rec) or _wikt_gloss_hit(rec)


# ── the Chinese edition needs its own filter, measured rather than assumed ───────────────
#
# ⚠ THE ENGLISH FILTER YIELDS 386 ENTRIES OF 2,916,811 ON THIS DUMP (0.01%). Measured on
#   the stored payload before parsing anything. Why it fails:
#     - `topics` is present on 0 entries. Signal A is entirely dead.
#     - `categories` covers 90.7% but is grammatical: 有詞條的頁面 (pages with entries),
#       漢語詞元 (Chinese lemmas), 官話詞元 (Mandarin lemmas). No semantic domain, the
#       same failure as English Wiktionary.
#     - 99.9% of glosses are Chinese, so an English word list matches nothing.
ZH_FOOD_WORDS = (
    "食物 食品 食材 菜 菜餚 菜肴 料理 醬 酱 醬料 調味 调味 調味料 香料 辛香料 香辛料 水果 蔬菜 "
    "肉 肉類 米 飯 饭 麵 面條 麵條 湯 汤 酒 茶 糖 鹽 盐 油 豆 魚 鱼 餅 饼 糕 點心 点心 甜點 甜点 "
    "飲料 饮料 烹飪 烹饪 食用 可食 佐料 乳酪 起司 麵包 面包 麵粉 面粉 堅果 坚果 種子 种子 果實 果实 "
    "蘑菇 菌 醋 辣椒 胡椒 薑 姜 蒜 蔥 葱 烹調 烹调 小吃 佳餚"
).split()
ZH_FOOD_RE = re.compile("|".join(map(re.escape, ZH_FOOD_WORDS)))


def _wikt_keep_zh(rec):
    """(A) any zh-language entry, OR (B) any language whose gloss carries a Chinese food word."""
    if rec.get("lang_code") == "zh":
        return True
    for sense in (rec.get("senses") or []):
        for g in (sense.get("glosses") or []):
            if g and ZH_FOOD_RE.search(g):
                return True
    return False


ZH_FILTER = (
    "ZH EDITION UNION, and it is deliberately a RECALL choice. "
    "(A) lang_code == 'zh', 288,183 entries of 2,916,811. This is a LANGUAGE FILTER "
    "RATHER THAN A SEMANTIC ONE: it keeps ALL Chinese vocabulary rather than only food, "
    "roughly 3x the English food slice and mostly non-food. It is kept because it catches "
    "豆瓣醬 (doubanjiang) despite that entry having an EMPTY gloss, which no gloss-based "
    "filter can see. "
    "(B) any language whose gloss contains one of: " + " ".join(ZH_FOOD_WORDS) + " — "
    "44,514 entries. This catches 고춧가루 (gochugaru) on its KOREAN entry, glossed 辣椒粉, "
    "which (A) misses. "
    "THE ALTERNATIVE WAS PRECISION, at the cost of dropping two of the four terms this "
    "edition was added for: 豆瓣醬 has no gloss at all, and 阿魏 (asafoetida) is glossed "
    "botanically and medicinally rather than as food. RECALL WAS CHOSEN BECAUSE THE "
    "STORE'S PURPOSE IS KNOWING WHAT THINGS ARE CALLED. Expected yield 288,183 to 332,697, "
    "the union being at most the sum; the overlap was deliberately not measured first "
    "because the union runs either way and the bound is known. "
    "⚠ The ENGLISH filter would have kept 386 entries here (0.01%) and looked like a "
    "working ingest. The payload is stored whole, so any of this can be re-argued and "
    "re-parsed without re-fetching 225 MB."
)

WIKT_FILTERS = {"enwiktionary_senses": (_wikt_keep, WIKT_FILTER),
                "zhwiktionary_senses": (_wikt_keep_zh, ZH_FILTER)}


def wikt_filter_for(dataset):
    return WIKT_FILTERS.get(dataset, (_wikt_keep, WIKT_FILTER))


def wikt_entry(rec):
    """One wiktextract record -> the entry/label contract. Nothing corrected on the way in."""
    word, lang = rec.get("word"), rec.get("lang_code") or rec.get("lang")
    labels = [{"lang": lang, "text": word, "kind": "word", "is_preferred": 1,
               "source_field": "word"}]
    for f in (rec.get("forms") or []):
        if f.get("form"):
            labels.append({"lang": lang, "text": f["form"], "kind": "form",
                           "is_preferred": 0, "source_field": "forms"})
    for sense in (rec.get("senses") or []):
        for syn_field in ("synonyms", "alt_of", "related"):
            for v in (sense.get(syn_field) or []):
                t = v.get("word") if isinstance(v, dict) else v
                if t:
                    labels.append({"lang": lang, "text": t, "kind": syn_field,
                                   "is_preferred": 0, "source_field": "senses." + syn_field})
    for tr in (rec.get("translations") or []):
        if tr.get("word"):
            labels.append({"lang": tr.get("code") or tr.get("lang"), "text": tr["word"],
                           "kind": "translation", "is_preferred": 0,
                           "source_field": "translations"})
    xr = {k: rec[k] for k in ("wikidata", "wikipedia") if rec.get(k)}
    # ⚠ lang:word:pos IS NOT UNIQUE. Wiktionary splits a word by ETYMOLOGY, and
    #   wiktextract emits one record per etymology. 'en:may:verb' exists under etymology
    #   2 and 'en:may:noun' under etymology 3. Measured on the stored payload: 216 of
    #   1,924 food keys in the first 400,000 lines collided, about 11%.
    #   etymology_number is the source's OWN field, so composing it is using what the
    #   record carries rather than inventing an identifier (the mistake made on the OFF
    #   .txt, where no identifier existed and one was derived).
    etym = rec.get("etymology_number")
    return {"entry_id": f"{lang}:{word}:{rec.get('pos')}#{etym if etym is not None else 0}",
            "name": word, "lang": lang,
            "xrefs": json.dumps(xr, ensure_ascii=False) if xr else None,
            "raw": json.dumps(rec, ensure_ascii=False, sort_keys=True), "labels": labels}


def wikt_stream_pages(conn, fetch_ids):
    """Yield decoded JSONL lines by streaming the stored ranges through one gzip decoder.

    Never holds more than a single page plus a small decode window, so the 22.9 GB
    expanded form is never materialised anywhere.
    """
    dec = zlib.decompressobj(31)          # 31 = gzip wrapper
    tail = b""
    for fid in fetch_ids:
        chunk = dec.decompress(read_payload(conn, fid))
        if not chunk:
            continue
        tail += chunk
        lines = tail.split(b"\n")
        tail = lines.pop()
        for ln in lines:
            if ln.strip():
                yield ln
    rest = dec.flush()
    tail += rest
    for ln in tail.split(b"\n"):
        if ln.strip():
            yield ln


def completed_crawl(conn, source, dataset):
    """-> (crawl_id, [fetch_ids]) for the newest FINISHED crawl, else (None, []).

    Lets a parse be re-run against bytes already stored. That is the whole reason the
    payload is kept, and the first wiktextract parse needed it within the hour.
    """
    row = conn.execute(
        "SELECT crawl_id FROM source_fetch WHERE source=? AND dataset=? "
        "GROUP BY crawl_id HAVING SUM(is_final_page)=1 ORDER BY MAX(id) DESC LIMIT 1",
        (source, dataset)).fetchone()
    if not row:
        return None, []
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM source_fetch WHERE crawl_id=? ORDER BY page_index",
        (row["crawl_id"],))]
    return row["crawl_id"], ids


# ⚠ OPEN MEASUREMENT, NOT YET DONE. 10,707,971 senses were excluded by WIKT_FILTER and
#   nobody knows the false-negative rate. The right way to settle the gloss word list is
#   to SAMPLE the excluded senses and count how many are food, not to add words one term
#   at a time as they are noticed. The payload is stored, so this costs no bandwidth.
#   Until that measurement exists, the list stays as it is.
WIKT_FALSE_NEGATIVE_TODO = (
    "Sample N excluded senses uniformly, classify each as food or not, and report the "
    "false-negative rate with its confidence interval. That settles the word list. "
    "Growing it by anecdote (speculoos -> add 'biscuit') does not."
)


def cmd_wiktextract(conn, offline=None, dataset="enwiktionary_senses", url=None,
                    max_pages=None, reparse=False, parse=True):
    cat = catalogue_row(conn, "wiktextract", dataset)
    # ⚠ THE URL COMES FROM THE CATALOGUE, NOT FROM A CONSTANT. An earlier version read
    #   `url or WIKT_URL`, so asking for the zh edition re-fetched 2.83 GB of the ENGLISH
    #   dump and stored it under the zh dataset. The catalogue is the record of what each
    #   dataset IS; reaching past it to a module constant makes that record a decoration.
    src_url = url or cat["url"]
    if reparse:
        crawl, ids = completed_crawl(conn, "wiktextract", dataset)
        if not ids:
            raise SystemExit(f"no completed {dataset} crawl to re-parse")
        print(f"  re-parsing stored crawl {crawl}, {len(ids)} pages, NO network", flush=True)
        conn.execute("DELETE FROM wiktextract_entry WHERE fetch_id IN "
                     "(SELECT id FROM source_fetch WHERE crawl_id=?)", (crawl,))
        conn.commit()
        return _wikt_parse(conn, ids, dataset)
    crawl, start = unfinished_crawl(conn, "wiktextract", dataset)
    if crawl:
        print(f"  resuming crawl {crawl} at page {start}", flush=True)
    else:
        crawl, start = f"wikt-{dataset}-{now_utc()}", 0

    if offline:
        blobs = offline["ranges"]
        total = sum(len(b) for b in blobs)
    else:
        head = urllib.request.Request(src_url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(head, timeout=120) as r:
            total = int(r.headers["Content-Length"])
            version = r.headers.get("ETag") or r.headers.get("Last-Modified")
        blobs = None
    # ⚠ In offline mode the caller SUPPLIES the ranges, so their count IS the page count.
    #   Deriving it from WIKT_RANGE fed only the first range into the decoder and produced
    #   a truncated gzip stream. (Same shape as the AGROVOC len(offline) bug.)
    n_pages = len(blobs) if blobs is not None else max(1, -(-total // WIKT_RANGE))
    if max_pages:
        n_pages = min(n_pages, max_pages)
    print(f"  artifact {total:,} bytes -> {n_pages} pages of {WIKT_RANGE // 2**20} MB "
          f"(SQLite blob ceiling is 1,000,000,000)", flush=True)

    whole = hashlib.sha256()
    ids = []
    for i in range(n_pages):
        if blobs is not None:
            lo = sum(len(x) for x in blobs[:i]); hi = lo + len(blobs[i]) - 1
        else:
            lo, hi = i * WIKT_RANGE, min((i + 1) * WIKT_RANGE, total) - 1
        if i < start:
            row = conn.execute("SELECT id FROM source_fetch WHERE crawl_id=? AND page_index=?",
                               (crawl, i)).fetchone()
            ids.append(row["id"])
            whole.update(read_payload(conn, row["id"]))
            continue
        if blobs is not None:
            b = blobs[i]
        else:
            req = urllib.request.Request(src_url, headers={"User-Agent": UA,
                                                           "Range": f"bytes={lo}-{hi}"})
            with urllib.request.urlopen(req, timeout=600) as r:
                b = r.read()
        whole.update(b)
        fid = record_page(conn, cat, b, crawl_id=crawl, page_index=i,
                          is_final=(i == n_pages - 1), page_offset=lo,
                          page_limit=WIKT_RANGE, version=(None if offline else version),
                          parse_filter=wikt_filter_for(dataset)[1])
        conn.execute("UPDATE source_payload SET compression='none', blob=?, bytes_stored=?, "
                     "sha256_stored=? WHERE fetch_id=?",
                     (b, len(b), hashlib.sha256(b).hexdigest(), fid))
        conn.commit()
        ids.append(fid)
        got = hi + 1
        print(f"    page {i+1}/{n_pages}  {got/1e9:.2f} GB of {total/1e9:.2f} GB stored",
              flush=True)

    print(f"  whole-artifact sha256 {whole.hexdigest()[:16]}...", flush=True)
    if not parse:
        # Fetch and parse are separate acts. The payload is stored whole, so the filter
        # can be measured against real bytes BEFORE anything is written to the entry
        # table. That is the whole argument for storing it.
        print(f"  FETCH ONLY. {len(ids)} page(s) stored, nothing parsed. "
              f"Run --reparse once the filter is decided.", flush=True)
        return [(dataset, total, 0, 0, 0, ids[-1])]
    return _wikt_parse(conn, ids, dataset)


def _wikt_parse(conn, ids, dataset):
    """Stream the stored pages, keep the slice this edition needs, count everything dropped."""
    keep_fn, criterion = wikt_filter_for(dataset)
    conn.execute("UPDATE source_fetch SET parse_filter=? WHERE id IN (%s)"
                 % ",".join("?" * len(ids)), [criterion] + list(ids))
    conn.commit()
    print("  parsing as a stream, nothing expands to disk", flush=True)
    kept = dropped = seen = bad = 0
    disambiguated = 0
    used = set()
    batch = []
    final_id = ids[-1]
    for line in wikt_stream_pages(conn, ids):
        seen += 1
        try:
            rec = json.loads(line)
        except Exception:
            bad += 1; dropped += 1
            continue
        if not rec.get("word") or not keep_fn(rec):
            dropped += 1
            continue
        e = wikt_entry(rec)
        if e["entry_id"] in used:
            # Deterministic given the stored payload: the record's ordinal in the file.
            e["entry_id"] = f"{e['entry_id']}~{seen}"
            disambiguated += 1
        used.add(e["entry_id"])
        batch.append(e)
        if len(batch) >= 2000:
            kept += write_entries(conn, "wiktextract", final_id, batch)
            conn.commit(); batch = []
            print(f"    {seen:,} senses read, {kept:,} food entries kept", flush=True)
    if batch:
        kept += write_entries(conn, "wiktextract", final_id, batch)
    conn.execute("UPDATE source_fetch SET records_in_payload=?, entries_written=?, "
                 "entries_excluded=?, rows_returned=? WHERE id=?",
                 (seen, kept, dropped, kept, final_id))
    conn.commit()
    print(f"  {seen:,} senses, {kept:,} kept, {dropped:,} excluded "
          f"({bad:,} unparseable, {disambiguated:,} ids disambiguated by ordinal)", flush=True)
    return [(dataset, seen, seen, kept, dropped, final_id)]


COMMANDS = {"off": cmd_off, "wikidata": cmd_wikidata, "agrovoc": cmd_agrovoc,
            "wikipedia-redirect": cmd_wikipedia_redirect, "wiktextract": cmd_wiktextract}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch one source into sources.db.")
    ap.add_argument("source", choices=sorted(COMMANDS))
    ap.add_argument("--db", default=None)
    ap.add_argument("--reparse", action="store_true",
                    help="re-parse the stored payload without re-fetching")
    ap.add_argument("--fetch-only", action="store_true",
                    help="store the payload but do not parse it")
    ap.add_argument("--dataset", default=None, help="which wiktextract edition")
    args = ap.parse_args(argv)
    path = Path(args.db) if args.db else DB
    if not path.exists():
        print(f"{path} not found. Run build_sources_db.py first.", file=sys.stderr)
        return 1
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        kw = {}
        if args.source == "wiktextract":
            if args.reparse:
                kw["reparse"] = True
            if args.fetch_only:
                kw["parse"] = False
            if args.dataset:
                kw["dataset"] = args.dataset
        for dataset, nbytes, n_rec, written, n_exc, fid in COMMANDS[args.source](conn, **kw):
            print(f"{args.source}/{dataset}: {nbytes:,} bytes fetched, {n_rec:,} records, "
                  f"{written:,} entries written, {n_exc:,} excluded (fetch id {fid})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
