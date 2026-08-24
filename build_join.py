#!/usr/bin/env python3
"""build_join.py: build join.db, the name buckets over sources.db.

WHAT THIS IS
------------
One bucket per normalized NAME. Every source row that calls something by that name is a
member of the bucket. Nothing is reconciled to a winner and nothing is deleted. A name
carrying rows from four sources is four opinions filed under one string, and "pepper"
meaning both peppercorn and chili is two buckets that happen to share a spelling, not a
conflict to resolve.

This script owns join.db and nothing else. sources.db is opened read-only and stays
byte-identical, so the Collective Database argument in build_sources_db.py's docstring is
untouched and the 5.18 GB artifact never needs re-verifying. The cost is that
join_member.source, .dataset and .entry_id are a LOGICAL foreign key across files rather
than an enforced one. That was the explicit trade.

recipes.db is never opened.

THE SCOPE RULE, AND WHY EACH STEP IS THERE
-------------------------------------------
Applied to every label row. First match wins. An excluded row is RECORDED in
join_exclusion with the rule that excluded it, never dropped, so "what did we leave out
and why" is a query rather than an archaeology exercise.

  1  degenerate_name            no letter or digit anywhere in the string
  2  inflection_scaffolding     a wiktextract inflection-table marker
  3  translation                a name for the concept in another language, not a name
                                the source claims this entry has
  4  wiktextract_form_or_synonym
  5  no_latin_route             a non-Latin name on an entry with no in-scope Latin name

⚠️ RULE 4 IS NARROW ON PURPOSE AND AN EARLIER DRAFT WAS NOT.

Measured over 200 multi-source buckets read by hand: 13.0% wrong with every alias-shaped
field counted as a name, and 21 of the 26 errors involved a wiktextract synonym or form.
The obvious fix was to count only each source's own display name. That version measured
better on errors and was WRONG ANYWAY, for two reasons the error rate could not see.

  The hing bucket flipped to majority-wrong. Before: 4 asafoetida rows, 3 ginger. Under
  primary-names-only: 1 asafoetida, 3 ginger. The asafoetida evidence lived in an OFF
  synonym, an AGROVOC altLabel and a wiktextract synonyms list, all removed, while the
  ginger rows are primary labels and all survived. A rule that removes the exculpatory
  evidence and keeps the accusation has not reduced error, it has hidden it.

  wikipedia_redirect was reduced to 21.9% of its rows. The REDIRECTS are the thing that
  source was fetched for. It scored 9 of 10 on the collapse terms precisely because
  redirects are an alias list written by people who hit the naming problem. Shaoxing jiu,
  Heeng, Windmill cookie are all redirects.

So rule 4 names the two wiktextract fields the errors actually came from and leaves every
other source's alias field alone. Measured on the same 200: 4.5% wrong against 3.5% for
the blunt version, 6.5% against 6.3% per bucket where a merge exists, and 24% more
mergeable buckets. Same error rate, much more coverage, and hing back in balance at 3
against 3.

⚠️ TRANSLATIONS STAY OUT AND THIS IS NOT A CLOSE CALL. Including them adds 613,691
buckets and puts a pillow in the guanciale bucket, because zh.wiktionary lists guanciale
as a translation of 枕頭. Italian guanciale is both a cured jowl and a pillow.

⚠️ SCAFFOLDING MUST BE FILTERED BEFORE ANYTHING ELSE. wiktextract's forms array carries
inflection-table markers alongside real word forms: 142,756 rows, 8.2% of the field.
Before filtering, the largest bucket in the store held 22,690 entries and was named
`no-table-tags`. After, the largest holds 271.

THE LATIN ROUTE, AND WHAT IT COSTS
-----------------------------------
Rule 5 keeps a name if it is Latin script, or if its entry is reachable from an in-scope
Latin name. Measured reachability by script: Arabic 98.2%, Devanagari 97.8%, Cyrillic
92.1%, Hangul 62.7%, CJK 18.2%. So Arabic, Cyrillic and Devanagari come through nearly
whole and CJK mostly does not.

That is a confidence rule, not a quality judgement. The store holds 361,619 CJK
(bucket, entry) pairs no other source can see, and nobody here can read them well enough
to catch a collision like 不忍, where Wikidata's Min Nan transliteration of PUDDING lands
on the ordinary verb meaning "cannot bear to". The rule draws the line where the store can
be checked.

THE OVERRIDE LIST
-----------------
A hand-written list of specific strings pulled back past RULE 5 ONLY. It does not
resurrect translations, scaffolding or wiktextract forms and synonyms, because those are
where the errors were.

⚠️ IF IT GROWS PAST A FEW DOZEN ENTRIES, THE RULE IS DRAWN IN THE WRONG PLACE AND THE FIX
IS REDRAWING THE RULE. Its size is printed on every run for that reason.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sqlite3
import unicodedata

SOURCES_DB = os.environ.get("SOURCES_DB", "sources.db")
JOIN_DB = os.environ.get("JOIN_DB", "join.db")

RULE_VERSION = "narrow-2"

# The source's own display name for an entry, per source's own vocabulary.
PRIMARY_KINDS = {"word", "label", "prefLabel", "canonical_name", "name", "article_title"}

# ⚠️ The two fields the measured errors came from. NOT "every alias-shaped field".
WIKT_EXCLUDED_KINDS = {"form", "synonyms"}

RULES = [
    ("degenerate_name", "the string carries no letter or digit at all"),
    ("inflection_scaffolding", "a wiktextract inflection-table marker, not a word form"),
    ("translation", "a name for the concept in another language, not a name for this entry"),
    ("wiktextract_form_or_synonym",
     "wiktextract form or synonyms, the two fields 21 of 26 measured errors came from"),
    ("no_latin_route", "non-Latin name on an entry with no in-scope Latin name"),
]

# ⚠️ OVERRIDE LIST. Each entry needs a reason. Rule 5 only. Report the size on every run.
OVERRIDES = {
    "紹興酒": "Shaoxing wine. wiktextract is the only source that has it and its zh rows "
             "carry no Latin primary name, so rule 5 takes the bucket to zero entries.",
    "豆瓣醬": "doubanjiang. The zh.wiktionary rows are the reason that edition was "
             "ingested and rule 5 drops both of them.",
    "豆瓣酱": "Simplified form of the above, same reason.",
    # ⚠️ 绍兴酒 was tried here and REMOVED. Its only label row is a wiktextract `form`,
    #    which rule 4 rejects, and the override reaches rule 5 only. It rescued nothing.
    #    Recorded rather than deleted quietly: an override that changes no row is a
    #    false claim about what this list is doing.
    "阿魏": "asafoetida. The Chinese name, and the two wiktextract rows that carry the "
           "medicinal reading rather than the culinary one.",
    "고춧가루": "gochugaru. Rule 5 drops the wiktextract Korean row and leaves only "
              "Wikidata's chili powder item, which is the merge this store exists to "
              "make visible.",
    "زعتر": "za'atar. Rule 5 drops both wiktextract Arabic rows.",
}

SCHEMA = """
CREATE TABLE join_run (
    run_id        INTEGER PRIMARY KEY,
    built_at      TEXT NOT NULL,          -- ISO-8601 UTC
    rule_version  TEXT NOT NULL,
    sources_db    TEXT NOT NULL,
    sources_bytes INTEGER NOT NULL,       -- so a rebuilt store is visible as a change
    label_rows    INTEGER NOT NULL,
    members       INTEGER NOT NULL,
    exclusions    INTEGER NOT NULL,
    buckets       INTEGER NOT NULL,
    entries_in    INTEGER NOT NULL,
    override_size INTEGER NOT NULL
);

CREATE TABLE join_rule (
    rule        TEXT PRIMARY KEY,
    ordinal     INTEGER NOT NULL,         -- first match wins, in this order
    description TEXT NOT NULL
);

CREATE TABLE join_override (
    norm     TEXT PRIMARY KEY,
    reason   TEXT NOT NULL,               -- ⚠️ no reason, no override
    added_in INTEGER NOT NULL REFERENCES join_run(run_id)
);

-- One row per normalized name that has at least one in-scope member.
CREATE TABLE join_bucket (
    norm       TEXT PRIMARY KEY,
    script     TEXT NOT NULL,
    n_entries  INTEGER NOT NULL,
    n_sources  INTEGER NOT NULL,
    n_datasets INTEGER NOT NULL
);

-- ⚠️ source / dataset / entry_id is a LOGICAL foreign key into sources.db. It is not
--    enforced, because sources.db is a separate file and stays untouched.
CREATE TABLE join_member (
    norm      TEXT NOT NULL REFERENCES join_bucket(norm),
    source    TEXT NOT NULL,
    dataset   TEXT NOT NULL,
    entry_id  TEXT NOT NULL,
    kind      TEXT NOT NULL,              -- the source's OWN word for this label kind
    lang      TEXT,
    text      TEXT NOT NULL,              -- verbatim, pre-normalization
    via_override INTEGER NOT NULL DEFAULT 0 CHECK (via_override IN (0,1))
                                        -- 1 = rule 5 WOULD have dropped this row
);

-- ⚠️ NOTHING IS DELETED. Every label row the ladder rejected is here with its rule.
CREATE TABLE join_exclusion (
    norm     TEXT NOT NULL,
    source   TEXT NOT NULL,
    dataset  TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    kind     TEXT NOT NULL,
    lang     TEXT,
    text     TEXT NOT NULL,
    rule     TEXT NOT NULL REFERENCES join_rule(rule)
);

CREATE INDEX ix_member_norm ON join_member(norm);
CREATE INDEX ix_member_entry ON join_member(source, dataset, entry_id);
CREATE INDEX ix_excl_norm ON join_exclusion(norm);
CREATE INDEX ix_excl_rule ON join_exclusion(rule);
CREATE INDEX ix_bucket_sources ON join_bucket(n_sources, n_entries);
"""

LABEL_TABLES = [
    ("off_taxonomy", "off_taxonomy_entry", "off_taxonomy_label"),
    ("wikidata", "wikidata_entry", "wikidata_label"),
    ("agrovoc", "agrovoc_entry", "agrovoc_label"),
    ("wikipedia_redirect", "wikipedia_redirect_entry", "wikipedia_redirect_label"),
    ("wiktextract", "wiktextract_entry", "wiktextract_label"),
    ("usda_fdc", "usda_fdc_entry", "usda_fdc_label"),
]

_WS = re.compile(r"\s+")

# Curly and typographic apostrophes are the SAME character for naming purposes. Nobody
# means a different spice by za’atar than by za'atar.
_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "′": "'", "´": "'", "`": "'"})
_SEPARATORS = "-‐‑‒–—()[]{}'"


def norm_name(s):
    """NFKC, casefold, then fold the punctuation that only ever separates words:
    typographic apostrophes to a plain one, then hyphens, dashes, brackets and
    apostrophes all to a space, then collapse whitespace.

    ⚠️ DIACRITICS ARE STILL KEPT. crème and créme stay two buckets, because an accent
    changes the word rather than spacing it.

    ⚠️ THE APOSTROPHE GOES TO A SPACE, NOT TO NOTHING, AND THAT IS THE WHOLE CARE OF
    THIS FUNCTION. Dropping it entirely merges za'atar with zaatar, which is arguably
    right, and it also merges rose's with roses (Rose's lime juice onto the genus Rosa),
    m'ari with mari (honey onto berry), and bull's-eye with bulls-eye (a boiled sweet
    onto a Kraft barbecue sauce). Measured over all 564,991 buckets, dropping the
    apostrophe produces 35 merges of distinct Wikidata items and spacing it produces 33,
    and the two it removes are exactly those collisions.

    What this DOES merge, measured: 3,996 groups absorbing 4,214 buckets, 0.75% of the
    store. 82.0% of those groups already shared a source entry, so they are one thing
    under two spellings and nothing is learned by keeping them apart: olive oil and
    olive-oil, bay leaf and bay-leaf, brown sugar and brown (sugar), confectioners'
    sugar and confectioners sugar. Of the 18.0% that bring together entries which never
    met, 33 join distinct Wikidata items and 3 of those are wrong: sweet tart with a
    Sweet-Tart apple cultivar, tuba with tuba', and a Hebrew pair separated only by a
    geresh. 3 bad merges in 3,996 is the price of collapsing 4,214 duplicate buckets.
    """
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    s = s.translate(_QUOTES)
    for ch in _SEPARATORS:
        s = s.replace(ch, " ")
    return _WS.sub(" ", s).strip()


def script_of(s):
    """The writing system of the first letter or digit. Used only by rule 5."""
    for ch in s:
        if ch.isspace() or not ch.isalnum():
            continue
        if ch.isdigit():
            return "Latin"
        n = unicodedata.name(ch, "")
        for prefix, name in (("CJK", "CJK"), ("HIRAGANA", "CJK"), ("KATAKANA", "CJK"),
                             ("HANGUL", "Hangul"), ("CYRILLIC", "Cyrillic"),
                             ("ARABIC", "Arabic"), ("DEVANAGARI", "Devanagari"),
                             ("LATIN", "Latin")):
            if n.startswith(prefix):
                return name
        return "other"
    return "none"


def scaffolding_strings(src):
    """The wiktextract forms whose tags mark them as inflection-table furniture rather
    than word forms. Read from the stored raw so the list is derived, never hand-kept."""
    junk_tags = {"table-tags", "inflection-template", "class", "dummy"}
    out = set()
    for (raw,) in src.execute("SELECT raw FROM wiktextract_entry"):
        for f in (json.loads(raw).get("forms") or []):
            if set(f.get("tags") or []) & junk_tags and f.get("form"):
                out.add(norm_name(f["form"]))
    return out


def read_labels(src):
    """Every label row in sources.db, as (norm, source, dataset, entry_id, kind, lang, text)."""
    for source, ent, lab in LABEL_TABLES:
        rows = src.execute(
            f"SELECT f.dataset, e.entry_id, l.text, l.kind, l.lang "
            f"FROM {lab} l JOIN {ent} e ON e.pk = l.entry_pk "
            f"JOIN source_fetch f ON f.id = e.fetch_id")
        for dataset, entry_id, text, kind, lang in rows:
            # ⚠️ An EMPTY norm is yielded, not skipped. Once hyphens, brackets and
            # apostrophes fold to spaces, a punctuation-only label normalizes to "" where
            # under narrow-1 it normalized to "-" or "'". Skipping here would drop 66,570
            # rows out of join_exclusion silently, and "nothing is deleted, every excluded
            # row records the rule that excluded it" is the point of this file. pre_rule
            # already calls these degenerate_name, because script_of("") is "none".
            yield norm_name(text), source, dataset, entry_id, kind, lang, text


def pre_rule(n, source, kind, scaffolding, scripts):
    """Rules 1 to 4. Rule 5 needs the Latin-route pass and is applied separately."""
    if scripts[n] == "none":
        return "degenerate_name"
    if n in scaffolding:
        return "inflection_scaffolding"
    if kind == "translation":
        return "translation"
    if source == "wiktextract" and kind in WIKT_EXCLUDED_KINDS:
        return "wiktextract_form_or_synonym"
    return None


def build(sources_db=SOURCES_DB, join_db=JOIN_DB, verbose=True):
    if not os.path.exists(sources_db):
        raise SystemExit(f"{sources_db} not found")
    src = sqlite3.connect(f"file:{sources_db}?mode=ro", uri=True)
    src.execute("PRAGMA query_only = ON")

    def say(*a):
        if verbose:
            print(*a, flush=True)

    say(f"reading {sources_db} (read-only)")
    scaffolding = scaffolding_strings(src)
    say(f"  scaffolding strings derived from the raw forms: {len(scaffolding):,}")

    # Pass 1. Classify rules 1 to 4 and collect the Latin route.
    scripts = {}
    labels = []
    latin_entries = set()
    for row in read_labels(src):
        n, source, dataset, entry_id, kind, lang, text = row
        if n not in scripts:
            scripts[n] = script_of(n)
        r = pre_rule(n, source, kind, scaffolding, scripts)
        labels.append((n, source, dataset, entry_id, kind, lang, text, r))
        if r is None and scripts[n] == "Latin":
            latin_entries.add((source, dataset, entry_id))
    say(f"  label rows read: {len(labels):,}")
    say(f"  entries reachable from an in-scope Latin name: {len(latin_entries):,}")

    # Pass 2. Rule 5 plus the override, then split into members and exclusions.
    members, exclusions = [], []
    overridden = 0
    for n, source, dataset, entry_id, kind, lang, text, r in labels:
        rescued = 0
        if r is None and scripts[n] != "Latin" and (source, dataset, entry_id) not in latin_entries:
            if n in OVERRIDES:
                rescued = 1
                overridden += 1
            else:
                r = "no_latin_route"
        if r is None:
            members.append((n, source, dataset, entry_id, kind, lang, text, rescued))
        else:
            exclusions.append((n, source, dataset, entry_id, kind, lang, text, r))
    say(f"  members: {len(members):,}   exclusions: {len(exclusions):,}   "
        f"rescued by override: {overridden:,}")

    if os.path.exists(join_db):
        os.remove(join_db)
    out = sqlite3.connect(join_db)
    out.executescript(SCHEMA)
    out.executemany("INSERT INTO join_rule VALUES (?,?,?)",
                    [(r, i + 1, d) for i, (r, d) in enumerate(RULES)])

    buckets = collections.defaultdict(lambda: [set(), set(), set()])
    for n, source, dataset, entry_id, _k, _l, _t, _o in members:
        b = buckets[n]
        b[0].add((source, dataset, entry_id))
        b[1].add(source)
        b[2].add(dataset)
    out.executemany(
        "INSERT INTO join_bucket VALUES (?,?,?,?,?)",
        [(n, scripts[n], len(v[0]), len(v[1]), len(v[2])) for n, v in buckets.items()])
    out.executemany("INSERT INTO join_member VALUES (?,?,?,?,?,?,?,?)", members)
    out.executemany("INSERT INTO join_exclusion VALUES (?,?,?,?,?,?,?,?)", exclusions)

    built_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out.execute(
        "INSERT INTO join_run (built_at, rule_version, sources_db, sources_bytes, "
        "label_rows, members, exclusions, buckets, entries_in, override_size) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (built_at, RULE_VERSION, os.path.abspath(sources_db), os.path.getsize(sources_db),
         len(labels), len(members), len(exclusions), len(buckets),
         len({(m[1], m[2], m[3]) for m in members}), len(OVERRIDES)))
    run_id = out.execute("SELECT MAX(run_id) FROM join_run").fetchone()[0]
    out.executemany("INSERT INTO join_override VALUES (?,?,?)",
                    [(k, v, run_id) for k, v in OVERRIDES.items()])
    out.commit()

    say("")
    say(f"wrote {join_db}  ({os.path.getsize(join_db) / 1e6:.1f} MB)")
    say(f"  buckets                {len(buckets):>9,}")
    say(f"  members                {len(members):>9,}")
    say(f"  exclusions             {len(exclusions):>9,}")
    say(f"  entries with a name    {len({(m[1], m[2], m[3]) for m in members}):>9,}")
    say(f"  ⚠️ override list size   {len(OVERRIDES):>9,}   (redraw the rule if this grows)")
    say("")
    say("  exclusions by rule:")
    for r, n in collections.Counter(e[7] for e in exclusions).most_common():
        say(f"    {r:<30} {n:>9,}")
    out.close()
    src.close()
    return join_db


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build join.db (name buckets over sources.db). Read-only on sources.db.")
    ap.add_argument("--sources", default=SOURCES_DB)
    ap.add_argument("--out", default=JOIN_DB)
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    build(a.sources, a.out, verbose=not a.quiet)


if __name__ == "__main__":
    main()
