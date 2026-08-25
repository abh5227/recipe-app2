#!/usr/bin/env python3
"""build_library.py: build the first-pass ingredient library from join.db and vocab/.

    python3.13 build_library.py            -> previews/ingredient-list-pass1.xlsx

WHAT THIS PRODUCES. One row per ingredient: a canonical name, every variation that
resolves to it with the language and source and field each came from, what kind of thing
it is, and a confidence with the reason spelled out. NAMES AND VARIATIONS ONLY. No
descriptions, no facts, no densities, no substitutions. Those come later and writing them
before the list is right would be writing them twice.

⚠️ NO NAME IS INVENTED HERE. Every canonical name and every variation is copied verbatim
from a source. The only things this file decides are WHICH entries exist and WHICH name
leads. Both decisions are stated below and both are judgements.

WHAT IT READS
    join.db            the name buckets, built by build_join.py, git-ignored
    sources.db         read-only, REQUIRED. Entry names and English glosses. git-ignored.
                       ⚠️ The build STOPS without it rather than returning a shorter list.
                       Measured: an earlier draft treated it as optional and silently
                       returned 11,769 entries instead of 11,153, because the E-number
                       filter reads OFF's stored names and matched nothing.
    vocab/*.json       the classification model. ⚠️ CANNOT BE REGENERATED, see vocab/README.md
    ingredient_cuts.py the cut rules and the override list
    reviewed.py        the 265 hand-read verdicts
    hand_removals.csv  ⚠️ Andy's removals. THE DECISION LIVES THERE, NOT IN THE SHEET,
                       because the sheet is regenerated. Marked in the spreadsheet and
                       pulled back by harvest_marks.py.

WHAT IS REPRODUCIBLE AND WHAT IS NOT. Given the same join.db and the same vocab/ this
script is deterministic and rebuilds the sheet exactly. What it CANNOT rebuild is the
judgement in ingredient_cuts.py and reviewed.py, which is why both are committed as data
rather than recomputed here.

THE THREE ADMISSION RULES, strongest first. Only Wikidata and Open Food Facts may create
an entry, because only they carry anything resembling a food classification.

  1  Wikidata classifies the item "Ingredient or foodstuff".                6,605
  2  Wikidata carries NO classification, but an OFF ingredients-taxonomy       487
     entry shares its name.
     ⚠️ THE WEAKEST RULE, and it exists for one measured reason: the Wikidata item that
     gets gochugaru right carries no food category at all. It also admitted dish, diet,
     seed, legume, flavoring and biscuit, which is why the sheet marks all 487.
  3  An OFF ingredients-taxonomy entry reaching no Wikidata item, after the    4,269
     json and txt copies of one concept are merged.

⚠️ AGROVOC, WIKTIONARY AND WIKIPEDIA NEVER CREATE AN ENTRY. They supply variations only.
None carries a food classification: AGROVOC has no type field in the store and its entries
begin 2,4-D and A horizons, and the two Wikimedia sources are a dictionary and an
article-redirect list. Measured on 60 hand-read Wiktionary candidates, its topics-and-
categories signal is 57 to 75% wrong AND misses Shaoxing wine, so there is nothing better
to use than the five-entry override list.

OWNERSHIP, AND WHY IT IS NOT "EVERY NAME IN MY BUCKETS". Every source entry belongs to at
most ONE library entry. Seeds own themselves, and every other source entry goes to the
anchor it shares the most buckets with.

    Without this the ginger anchor swallowed all six rows of the 'hing' bucket. That
    bucket holds two different things: Wikidata, OFF and its canonical_name all label
    ginger "hing" in ZHUANG, while AGROVOC's altLabel and OFF 4698's synonym are ENGLISH
    and mean asafoetida. Ownership gives each entry the rows its own sources wrote, and
    the language column on every variation is what makes the split readable.
"""
import collections, json, os, pickle, re, sqlite3, sys, unicodedata

import csv

import ingredient_cuts as CUTS
# ⚠️ THE SAME KEY THE JOIN USES, AND THE SAME KEY A RECIPE LABEL WILL BE MATCHED ON.
#    Two rows answering to one name is only a defect under the key the lookup will use,
#    so the name rules below key on norm_name rather than on casefold(). Measured:
#    casefold finds 1,260 pairs where norm_name finds 1,301, a difference of 41 that is
#    entirely hyphens, brackets and apostrophes.
from build_join import norm_name
try:
    import reviewed
except ImportError:                                   # the verdicts are optional to run
    reviewed = None

HAND_REMOVALS = os.environ.get("HAND_REMOVALS", "hand_removals.csv")
AUTHORED_ROWS = os.environ.get("AUTHORED_ROWS", "authored_rows.csv")
JOIN_DB = os.environ.get("JOIN_DB", "join.db")
SOURCES_DB = os.environ.get("SOURCES_DB", "sources.db")
VOCAB = os.environ.get("VOCAB_DIR", "vocab")
OUT = os.environ.get("LIBRARY_XLSX", "previews/ingredient-list-pass1.xlsx")

SOURCE_NAME = {"wikidata": "Wikidata", "off_taxonomy": "OFF", "agrovoc": "AGROVOC",
               "wiktextract": "Wiktionary", "wikipedia_redirect": "Wikipedia"}
# The source's own display name for an entry, per source's own vocabulary.
PRIMARY_KINDS = {"word", "label", "prefLabel", "canonical_name", "name", "article_title"}
# ⚠️ The fields the measured errors came from. 20.8% wrong on the 200-bucket sample.
ALIAS_KINDS = {"synonym", "alt_of", "form", "altLabel"}
FIELD_NAME = {"synonym": "synonym", "alt_of": "alternative form", "form": "word form",
              "altLabel": "alias", "alias": "alias", "redirect": "redirect",
              # ⚠️ NO SOURCE WROTE THIS ONE. See build_library.strip_as_food.
              "derived": "DERIVED HERE, no source wrote it",
              **{k: "primary name" for k in PRIMARY_KINDS}}

INGREDIENT = "Ingredient or foodstuff"
# ⚠️ Excluded even when Wikidata ALSO calls the item an ingredient. 179 brands and 34
#    fictional items were admitted by kind and removed anyway. Dish, Taxon, Chemical and
#    Drink are NOT here, because ingredient-plus-those is the dual nature and is kept.
FATAL_KINDS = {"Fictional food": "fictional",
               "Brand or trademark": "a brand or trademark"}
# ⚠️ MARKED, NEVER MOVED, AND THE MEASUREMENT IS IN ingredient_cuts.DECLINED.
#    653 rows carry one of these kinds AND "Ingredient or foodstuff". Reading 40 found
#    16 dishes and 24 ingredients, so a batch move would take chocolate, shrimp, honey,
#    ham, soy sauce and 387 others out of the library. The flag makes the 653 sortable
#    so the separation happens by reading, one row at a time.
DISH_KINDS = {"Dish or prepared food", "Cuisine, recipe or meal"}
E_NUMBER = re.compile(r"^e\s?\d{3}", re.I)
PROCESS_NAMES = {"frying", "cooking", "baking", "smoking", "drying", "fermentation",
                 "roasting", "preparation"}
BINOMIAL = re.compile(r"^[A-Z][a-z]+ [a-z]+(?: (?:subsp|var|f)\.? [a-z]+)?$")


def is_binomial(canonical, variations):
    """⚠️ SHAPE IS NOT EVIDENCE, AND ON ITS OWN IT WAS WRONG ABOUT 9 NAMES IN 10.

    BINOMIAL alone is a capital word followed by a lowercase one, which is the shape of
    every English name carrying a proper noun in front of it. It fired on 705 rows.
    Reading 60 of them found 5 genuine binomials, 8.3%, 95% CI [3.6%, 18.1%], so roughly
    646 of the 705 were wrong. Kaiser roll, Swiss roll, Welsh onion, Atlantic salmon,
    Shaoxing wine, Napa cabbage, Cheddar cheese, Serrano ham and Manuka honey all fired.

    ⚠️ THE FLAG IS NOT DECORATION. It tells the reader to pick a cook's name out of the
    variations by hand, so a wrong flag is work that should never have been started.

    The evidence the shape lacked is a source calling the string Latin. 56 of the 705
    carry a Latin language tag on the canonical itself, and the hand-read 5 were all 5 of
    them. Known cost, both directions:

      one false positive   'American cheese'. la.wikipedia did not translate the name, so
                           Wikidata carries it as a Latin label. Real tag, real name,
                           not a binomial.
      about fifteen misses mostly bacterial culture names that no source tags as Latin.
                           Lactobacillus acidophilus, Bifidobacterium longum,
                           Streptococcus thermophilus, Tuber magnatum, Tamarindus indica.
                           ⚠️ A MISS COSTS LESS THAN A FALSE POSITIVE HERE. Nobody writes
                           Lactobacillus acidophilus in a recipe, so an unflagged one
                           creates no work. A wrong flag does.

    ⚠️ A GENUS VOCABULARY WAS TRIED AND MADE IT WORSE, recorded so it is not retried.
    Deriving genus names from the corpus's own Latin-tagged strings yielded 339 genera and
    added 14 rows, only 5 of them real. 'American cheese' put 'American' in the genus list
    and pulled in American lobster, American mustard, American beef and three more. One
    bad tag propagated. Requiring the genus twice and the epithet absent from an English
    wordlist cut it to 4 correct additions, at the price of a system wordlist this repo
    does not otherwise need."""
    if not BINOMIAL.match(canonical):
        return False
    return any(lang.startswith("la") for _, _, lang in variations.get(canonical, ()))


def load_vocab():
    """The classification model. ⚠️ These files cannot be regenerated, see vocab/README.md."""
    def read(name, key):
        with open(os.path.join(VOCAB, name), encoding="utf-8") as fh:
            return json.load(fh)[key]
    return (read("wikidata-kinds.json", "kinds"),
            read("wikidata-superclasses.json", "superclasses"),
            read("off-taxonomy-tree.json", "parents"))


def off_tree(src):
    """Rebuild the OFF parent tree from sources.db when it is present. Falls back to the
    committed copy, which exists because sources.db is 5.18 GB and git-ignored."""
    if src is None:
        return None
    parents = collections.defaultdict(set)
    rows = src.execute("SELECT e.entry_id, e.raw, f.dataset FROM off_taxonomy_entry e "
                       "JOIN source_fetch f ON f.id = e.fetch_id")
    for entry_id, raw, dataset in rows:
        if dataset.endswith("_json"):
            try:
                got = json.loads(raw).get("parents") or []
            except ValueError:
                got = []
        else:
            got = re.findall(r"<\s*(en:[\w\-']+)", raw or "")
        for parent in got:
            parents[entry_id].add(str(parent))
    return {k: sorted(v) for k, v in parents.items()}


def read_members(join):
    """Every member row, grouped by source entry and by bucket."""
    by_entry = collections.defaultdict(list)
    by_bucket = collections.defaultdict(list)
    for norm, source, dataset, entry_id, kind, lang, text, _ in join.execute(
            "SELECT norm, source, dataset, entry_id, kind, lang, text, via_override "
            "FROM join_member"):
        by_entry[(source, dataset, entry_id)].append((norm, kind, lang, text))
        by_bucket[norm].append((source, dataset, entry_id, kind, lang, text))
    return by_entry, by_bucket


def pick_anchors(by_entry, by_bucket, kinds):
    """The three admission rules. Returns (wikidata_anchors, off_only_groups)."""
    wd_in_join = {e for (s, d, e) in by_entry if s == "wikidata"}
    off_in_join = {(d, e) for (s, d, e) in by_entry if s == "off_taxonomy"}

    wd_with_off = set()
    for rows in by_bucket.values():
        if any(r[0] == "off_taxonomy" for r in rows):
            wd_with_off |= {r[2] for r in rows if r[0] == "wikidata"}

    rule1 = {q for q in wd_in_join if INGREDIENT in kinds.get(q, {}).get("kinds", {})}
    rule2 = {q for q in wd_in_join if not kinds.get(q, {}).get("kinds")} & wd_with_off

    covered = set()
    for q in rule1 | rule2:
        for norm, *_ in by_entry[("wikidata", "food_items_q2095", q)]:
            covered |= {(d, e) for (s, d, e, *_) in by_bucket[norm] if s == "off_taxonomy"}

    # ⚠️ OFF IS LOADED TWICE, as a json taxonomy and a txt taxonomy, so most concepts
    #    appear as TWO entries. Two OFF entries sharing a bucket are one concept.
    rest, groups, seen = off_in_join - covered, [], set()
    for key in sorted(rest):
        if key in seen:
            continue
        group, stack = {key}, [key]
        while stack:
            dataset, entry_id = stack.pop()
            for norm, *_ in by_entry[("off_taxonomy", dataset, entry_id)]:
                for s2, d2, e2, *_ in by_bucket[norm]:
                    if s2 == "off_taxonomy" and (d2, e2) in rest and (d2, e2) not in group:
                        group.add((d2, e2))
                        stack.append((d2, e2))
        seen |= group
        groups.append(sorted(group))
    return rule1, rule2, groups


# ⚠️ ONE PRIMARY NAME PER CONCEPT PER LANGUAGE, AND THE SOURCES KEEP THAT PROMISE EXACTLY.
#    Measured in sources.db, not assumed: 0 of 250,765 AGROVOC (entry, language) pairs hold
#    two prefLabels, 0 of 238,997 Wikidata pairs hold two labels, 0 of 61,565 Open Food
#    Facts pairs hold two canonical_names. Zero exceptions in 551,327 pairs.
#
#    So two DIFFERENT primary names from one source in one language on one library row is
#    two source concepts merged, and no name-shape test is involved in saying so.
PRIMARY_CLAIM = {("agrovoc", "prefLabel"), ("wikidata", "label"),
                 ("off_taxonomy", "canonical_name")}


def primary_claims(rows, source):
    """The (source, language) slot -> the primary name an entry states in it.

    ⚠️ THE NAME, NOT JUST THE SLOT, AND THE FIRST DRAFT KEPT ONLY THE SLOT. It marked any
    second primary name in an occupied language, so two entries that AGREE got flagged as a
    merge: 'rosemary' was marked an intruder on the rosemary row. The premise is two
    DIFFERENT primary names. Measured, the correction removes 914 of 15,850 marks, 5.8%,
    which is smaller than it looks worth: the marks it removes are the ones that would have
    read as nonsense to anyone checking the column."""
    return {(source, (lang or "").lower()): text
            for _, kind, lang, text in rows if (source, kind) in PRIMARY_CLAIM}


def assign_ownership(entries, by_entry, by_bucket):
    """Every source entry belongs to at most ONE library entry. See the module docstring
    for the hing bucket, which is why this exists.

    ⚠️ AND AN ENTRY CARRYING A PRIMARY NAME DOES NOT JOIN AN ANCHOR THAT ALREADY HOLDS ONE
    FROM THE SAME SOURCE IN THE SAME LANGUAGE. Without this, 954 rows carried two or more
    concepts of one source over 698 recipe lines. egg yolk held sugar AND Amanita caesarea,
    milk held nickel, cabbage held water, cream held Panax, honey held common sole.

    The cause is that the "most shared buckets" tie-break has no floor and one homograph
    is enough to win. milk absorbed AGROVOC's nickel on the single bucket 'ni', the chemical
    symbol, out of 263 buckets. egg yolk absorbed Open Food Facts' sugar on the single
    bucket 'gula', which is sugar in Malay, out of 147.

    ⚠️ A SHARED-BUCKET FLOOR WAS MEASURED AND REJECTED. 17,933 of 23,814 absorbed entries,
    75.3%, share exactly ONE bucket with their owner, so a floor of two would un-own three
    quarters of the library's variation coverage to fix 954 rows. The precision is in the
    field rather than the count: of entries that carry a primary name, only 32.1% won on a
    single bucket. This rule has no threshold in it.

    ⚠️ NOTHING IS UN-OWNED AND NOTHING IS RESHUFFLED. An unowned entry is a name nothing can
    reach, which is worse than a name on the wrong row. What the rule marks is the intruding
    PRIMARY NAME, and resolve_borrowed then takes it off the row only where another row
    carries it, so no name can be lost. The entry's other names stay: Open Food Facts' sugar
    entry keeps contributing its 90 translations to whatever row it landed on, and only the
    word 'sugar' stops answering for egg yolk.

    ⚠️ RESHUFFLING WAS BUILT FIRST AND MEASURED AND IT DOES NOT WORK. Sending the entry to
    its next-best free anchor moved 954 merged rows to 931 and put recipe lines UP from 698
    to 721, because 1,727 of 1,914 displaced entries had no free anchor at all. A Wikidata
    anchor's own seed already holds a label in every language it is labeled in, so a second
    Wikidata item is blocked from every candidate and lands back where it started. The 187
    that did move took their clash with them to a new row.

    Entries are placed strongest-claim-first, so the ordering is deterministic rather than
    dictionary order, in which an entry sharing one bucket could take the slot from one
    sharing forty."""
    # ⚠️ THE ARTICLE A REDIRECT ENTRY IS. A wikipedia_redirect entry is ONE en.wikipedia
    #    article plus every name that redirects to it, and build_join already stores the
    #    article under its own kind on the same entry_id. 12,055 entries, all 12,055 carrying
    #    an article_title, against 42,762 redirect names. Nothing here is fetched or joined
    #    again: the signal has been sitting in join.db unread.
    article = {}
    for key, rows in by_entry.items():
        if key[0] != "wikipedia_redirect":
            continue
        for _, kind, _, text in rows:
            if kind == "article_title":
                article[key] = text
                break

    owner, seeds, held = {}, {}, collections.defaultdict(dict)
    for i, entry in enumerate(entries):
        for key in entry["seed"]:
            owner[key] = seeds[key] = i
            held[i].update(primary_claims(by_entry[key], key[0]))
    shared = collections.defaultdict(collections.Counter)
    for i, entry in enumerate(entries):
        for bucket in entry["buckets"]:
            for source, dataset, entry_id, *_ in by_bucket[bucket]:
                if (source, dataset, entry_id) not in seeds:
                    shared[(source, dataset, entry_id)][i] += 1

    # ⚠️ STRONGEST CLAIM FIRST, AND THE SORT IS THE RULE'S DETERMINISM. Placing entries in
    #    dict order would let an entry sharing one bucket take the slot from one sharing forty.
    order = sorted(shared, key=lambda k: (-max(shared[k].values()), k))
    intruders = collections.defaultdict(set)
    for key in order:
        best = max(shared[key].items(), key=lambda kv: (kv[1], -kv[0]))[0]
        owner[key] = best
        wants = primary_claims(by_entry[key], key[0])
        if not wants:
            continue                                  # variations only, nothing to clash
        for slot, text in wants.items():
            sitting = held[best].get(slot)
            if sitting is not None and norm_name(sitting) != norm_name(text):
                intruders[best].add(text)             # a SECOND, DIFFERENT primary name
            held[best].setdefault(slot, text)

    names = collections.defaultdict(lambda: collections.defaultdict(set))
    articles = collections.defaultdict(set)
    for key, rows in by_entry.items():
        i = owner.get(key)
        if i is None:
            continue
        if key in article:
            articles[i].add(article[key])
        for _, kind, lang, text in rows:
            names[i][text].add((key[0], kind, (lang or "").lower()))
    return names, intruders, articles


def choose_canonical(entry, by_entry, stored_names):
    """⚠️ THE ANCHOR'S OWN ENGLISH LABEL WINS. No promotion off a binomial and no tiebreak
    on string length. An earlier build did both and picked 'ail' for garlic, because the
    French name is shorter, and 'wild garlic' for Allium sativum, which is a different
    plant. A binomial canonical is FLAGGED instead and the cook's name is picked by hand."""
    for key in sorted(entry["seed"]):
        for _, kind, lang, text in by_entry[key]:
            if kind in PRIMARY_KINDS and (lang or "").lower().startswith("en"):
                return text, "the anchor's own English name"
    for key in sorted(entry["seed"]):
        name = stored_names.get((key[0], key[2]))
        if name:
            return name, "the anchor's own stored name, which is not in English"
    return None, "the anchor carries no name of its own"


def english_names(variations):
    """A name is English when a source states lang en*, or when it comes from
    wikipedia_redirect, which is enwiki and states no language at all."""
    return {text for text, tags in variations.items()
            if any(lang.startswith("en") or source == "wikipedia_redirect"
                   for source, _, lang in tags)}


def load_removals(path=HAND_REMOVALS):
    """Andy's hand removals, keyed on (anchor, id).

    ⚠️ (anchor, id) IS THE KEY BECAUSE THE CANONICAL NAME IS NOT UNIQUE. Measured over
    11,153 entries: zero (anchor, id) collisions, and 69 canonical names used by more
    than one entry. The id is the SOURCE'S OWN identifier, a Q-number or an OFF slug,
    not something this file invents.

    ⚠️ A ROW WITH NO REASON IS REJECTED, the same rule as ingredient_cuts.OVERRIDES."""
    if not os.path.exists(path):
        return {}, []
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    removals, rejected = collections.defaultdict(list), []
    for row in rows:
        if not (row.get("reason") or "").strip():
            rejected.append(row)
            continue
        removals[(row["anchor"], str(row["id"]))].append(row)
    return dict(removals), rejected


def load_authored(path=AUTHORED_ROWS):
    """Rows Andy authored, the mirror of load_removals.

    ⚠️ AN AUTHORED ROW HAS NO ANCHOR AND THAT IS THE POINT. Every other row traces to a
    fetch. These exist because the thing exists and no source we hold has it: 'salt' is
    52 recipe lines and 32 dependents and had no row, so a line saying salt reached
    'table salt' or 'sea salt', which is the wrong specific rather than the general
    thing. anchor is left EMPTY rather than set to "authored", because a fourth source
    name would read as data and there is no fetch, no entry_id and nothing to
    re-derive behind it.

    ⚠️ A ROW WITH NO REASON IS REJECTED, the same rule as OVERRIDES and hand_removals."""
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as fh:
        raw = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    good, rejected = [], []
    for row in raw:
        (good if (row.get("reason") or "").strip() else rejected).append(row)
    return good, rejected


def add_authored(rows, authored, subclass_count):
    """Build the row dicts. ⚠️ sources stays EMPTY, so the 'only one source' flag cannot
    fire on a row that has none, and the authored flag says the true thing instead."""
    for row in authored:
        name = row["name"].strip()
        sources = [s.strip() for s in (row.get("sources") or "").split(";") if s.strip()]
        rows.append({
            "canonical": name, "how": "authored by hand, no source",
            # The tag makes the name English to english_names() without inventing a
            # source: the language is a fact about the string, not a claim by anyone.
            "variations": {name: {("authored", "label", "en")}}, "n_variations": 0,
            "anchor": "", "id": row["id"].strip(), "kinds": [],
            "why": f"AUTHORED. {row['reason'].strip()}",
            "sources": sources, "languages": ["en"],
            "subclasses": subclass_count.get(row["id"].strip(), 0),
            "binomial": False, "rule2": False, "override": False, "dish": False,
            "authored": True, "added": (row.get("added") or "").strip(),
            "intruders": set(),      # nothing was absorbed, so nothing can intrude
            "articles": [],
        })
    return rows


def apply_removals(rows, removals):
    """Mark entries 'hand' and trim variations. Nothing is deleted: a dropped entry moves
    to the cut sheet with the reason, and a trimmed name is recorded on the row it left."""
    seen = set()
    for row in rows:
        key = (row["anchor"], str(row["id"]))
        row["hand_reasons"], row["trimmed"] = [], []
        for rule in removals.get(key, ()):
            seen.add(key)
            action, reason = rule["action"], rule["reason"].strip()
            if action == "drop":
                row["hand_reasons"].append(reason)
            elif action == "drop_variation":
                name = (rule.get("variation") or "").strip()
                if name in row["variations"] and name != row["canonical"]:
                    del row["variations"][name]
                    row["trimmed"].append(f"{name} ({reason})")
            elif action == "trim_alias_only":
                gone = [t for t, tags in row["variations"].items()
                        if t != row["canonical"]
                        and all(k in ALIAS_KINDS for _, k, _ in tags)]
                for name in gone:
                    del row["variations"][name]
                if gone:
                    row["trimmed"].append(
                        f"{len(gone)} alias-only variation(s) ({reason}): "
                        + ", ".join(gone[:8]) + (" ..." if len(gone) > 8 else ""))
        row["n_variations"] = len(row["variations"]) - 1
    dangling = [r for key, rules in removals.items() if key not in seen for r in rules]
    return rows, dangling


# ─────────────────────────────────────────────────────────────────────────────────────
# Name resolution: which row answers to a name that two rows carry.
#
# Measured over the 11,153 rows before any of this ran: 1,301 (holder, name) pairs where
# a name on one row is ANOTHER row's canonical, and 490 of 2,997 recipe ingredient lines,
# 16.3%, hit a name that more than one row carries. That is the only group where the app
# gives a WRONG answer rather than no answer, so it is worth a rule where the rest is not.
#
# ⚠️ NOTHING IS DELETED HERE. A name that leaves a row is recorded ON the row it left with
#    the rule that moved it, the same way a cut row keeps its mark, so it reads back and
#    reverses by name.
#
# ⚠️ AND NO NAME STOPS RESOLVING, BY CONSTRUCTION. A pair only exists when another row
#    already claims that name as its CANONICAL, so every name taken off a holder still
#    answers, to the row that owns it. Measured across the whole pipeline: 1,262 of 2,997
#    recipe lines match a library name before and after, and 963 of them land on a
#    canonical before and after. Both figures are unchanged to the line.
# ─────────────────────────────────────────────────────────────────────────────────────
AS_FOOD = " as food"
DERIVED = "derived"          # ⚠️ NOT A SOURCE FIELD. See strip_as_food.


def strip_as_food(rows):
    """Wikidata's "X as food" items name the food rather than the animal, and the suffix
    is Wikidata's disambiguator rather than a word a cook writes.

    ⚠️ THE SUFFIX COMES OFF ONLY WHERE THE STEM IS FREE. 106 rows carry it. On 19 the bare
    stem is ALREADY another row's canonical, and those 19 are exactly the rows where the
    distinction is doing work: 'lobster as food' against 'lobster', 'oyster as food'
    against 'oyster', 'goose as food' against 'goose', 'clam as food' against 'clam'.
    Wikidata holds the animal and the food as separate items and the library holds both,
    so a strip there would collide two real rows rather than rename one. Those 19 are a
    MERGE decision and they are left alone. 'egg as food' is one of them, and it carries
    46 of the 48 recipe lines the whole group reaches.

    The other 87 collide with nothing: blue marlin, crabgrass, geoduck, razor shell,
    blood vessel, lily bulb, shipworm, hagfish.

    ⚠️ THE STRIPPED NAME IS MARKED 'derived' RATHER THAN GIVEN A SOURCE FIELD, because no
    source wrote it. It is this file removing four characters, which is CURATED under
    docs/sourcing-tiers.md, and the variations cell has to say so or the row would read as
    though Wikidata had labelled it that."""
    owned = {norm_name(row["canonical"]) for row in rows}
    stems = collections.Counter(norm_name(row["canonical"][:-len(AS_FOOD)])
                                for row in rows
                                if row["canonical"].casefold().endswith(AS_FOOD))
    renamed = []
    for row in rows:
        if not row["canonical"].casefold().endswith(AS_FOOD):
            continue
        stem = row["canonical"][:-len(AS_FOOD)]
        if norm_name(stem) in owned or stems[norm_name(stem)] > 1:
            continue                                  # the 19. A merge, not a rename.
        row["variations"].setdefault(stem, set()).add((row["anchor"], DERIVED, "en"))
        row["renamed_from"] = row["canonical"]
        row["canonical"] = stem
        row["n_variations"] = len(row["variations"]) - 1
        renamed.append(row)
    return renamed


def resolve_borrowed(rows, superclasses, off_parents):
    """Take a name off a row when another row owns it as that row's canonical.

    RULE 1, A REDIRECT LOSES TO A CANONICAL AND WINS AGAINST NOTHING. A name supplied only
    by wikipedia_redirect leaves a row that another row claims as canonical. A redirect is
    a pointer to an article, not a claim that the target IS the thing, and en.wikipedia
    redirects 'Salmon' at 'Atlantic salmon' without saying they are the same fish.

    ⚠️ THE SECOND HALF OF THE RULE IS WHAT KEEPS THE SOURCE WORTH HAVING. Nothing is taken
    from a redirect that is the only source for a name. wikipedia_redirect supplies 15,309
    unique names over 947 recipe lines, and 14,773 of them over 608 lines are uncontested,
    so the rule keeps 96.5% of what the source uniquely gives and takes 3.5%. Every
    collapse term survives: Heeng, Windmill cookie, gochugaru, doubanjiang, guanciale,
    pekmez, za'atar, speculaas are all redirect-only and all uncontested.

    RULE 2, THE GENERAL TERM LEAVES THE SPECIFIC HOLDER. A name whose words are a strict
    subset of the holder's own canonical leaves it: 'salt' off 'sea salt', 'olive oil' off
    'extra virgin olive oil', 'milk' off "cow's milk". The specific row is not the general
    thing and it should not answer for it.

    Measured over the kept rows. Rule 1 alone takes 509 names, rule 2 alone takes 112,
    and 37 pairs are in BOTH, so the two together take 584 rather than 621. In the build,
    which resolves the cut rows as well and runs the rename first, rule 1 takes 500 and
    rule 2 takes the remaining 76.

    ⚠️ THE OVERLAP IS WHY RULE 2's HEADLINE NUMBER SHRINKS. Measured alone, rule 2 returns
    436 recipe lines and its largest single gain is 'olive oil' +117 off 'extra virgin
    olive oil'. Every one of those 117 is already returned by rule 1, which sees the same
    pair first because en.wikipedia is the only source that put 'olive oil' on that row.
    Behind rule 1, rule 2's gains are salt +156, sugar +44, egg +39, milk +22, oil +11,
    pepper +10, paprika +8, rice +4. ⚠️ SIX OF THE EIGHT ARE AUTHORED ROWS THAT DID NOT
    EXIST BEFORE STAGE 1. Rule 2 is worth almost nothing without authored_rows.csv,
    because there was no general row for the general term to go to.

    RULE 3, A SECOND PRIMARY NAME FROM ONE SOURCE IN ONE LANGUAGE LEAVES. A source gives a
    concept at most ONE primary name per language and all three keep that promise exactly,
    measured in sources.db rather than assumed: 0 of 250,765 AGROVOC (entry, language) pairs
    hold two prefLabels, 0 of 238,997 Wikidata pairs hold two labels, 0 of 61,565 OFF pairs
    hold two canonical_names. Zero exceptions in 551,327 pairs. So a row holding two is a
    row holding two concepts, and assign_ownership marks the later one.

    ⚠️ AND IT STILL ONLY LEAVES IF ANOTHER ROW CARRIES THE NAME, the same guard as rules 1
    and 2. Without that guard this rule could take a name out of the library, which the
    other two cannot do by construction.

    ⚠️ WHAT THIS DOES NOT REACH, AND IT IS 668 PAIRS. No rule touches a pair whose two
    names share no word, where no source is a redirect, and where both are the first primary
    name their source states in their language. 'peppercorn' holding 'pepper'
    has AGROVOC, Open Food Facts, Wikidata and Wiktionary behind it and they are not
    wrong. 'cabbage' holding 'water' has Open Food Facts behind it and is. Source count
    does not separate the two, so they are read by hand rather than ruled on.

    ⚠️ RULE 3 MARKS FAR MORE THAN IT MOVES, AND THE GUARD IS WHY. 14,936 second primary
    names are marked across 939 entries and 64 leave. 14,791 stay because nothing else in
    the library carries them, so removing one would take the name out altogether. They are
    named on the row in 'What I was unsure about' instead. The marks are a reading list, and
    deciding which of two entries keeps the row is a merge question, not a rule."""
    moved = collections.Counter()
    # ⚠️ A CUT ROW NEVER WINS A NAME, AND WITHOUT THIS GUARD TWO DID. 'Red Rome' moved off
    #    'Rome' and 'Bohnapfel' off 'Rheinischer Bohnapfel', both to rows the cultivar
    #    register then cut, which would have taken the two names out of the library
    #    altogether. Neither reaches a recipe line, so the cost was zero and the claim
    #    above was still false. The marks are computed here on the PRE-resolution row,
    #    which is safe in one direction: resolving only removes names, so it can push a
    #    row INTO a cut and never out of one.
    cut = [bool(apply_cuts(row, superclasses, off_parents)) for row in rows]
    canonical = collections.defaultdict(list)
    for i, row in enumerate(rows):
        if not cut[i]:
            canonical[norm_name(row["canonical"])].append(i)

    for i, row in enumerate(rows):
        row.setdefault("resolved", [])
        head = set(norm_name(row["canonical"]).split())
        for text in list(row["variations"]):
            key = norm_name(text)
            if key == norm_name(row["canonical"]):
                continue
            owners = [j for j in canonical.get(key, ()) if j != i]
            if not owners:
                continue                              # a redirect wins against nothing
            tags = row["variations"][text]
            if all(source == "wikipedia_redirect" for source, _, _ in tags):
                rule = "redirect loses to a canonical"
            elif set(key.split()) < head:
                rule = "the general term leaves the specific holder"
            elif text in row.get("intruders", ()):
                rule = "a second primary name from one source in one language"
            else:
                continue
            del row["variations"][text]
            row["resolved"].append((text, rows[owners[0]]["canonical"], rule))
            moved[rule] += 1

    for row in rows:
        # ⚠️ RECOMPUTED, NOT LEFT STALE. A name that belongs to another row was never
        #    evidence for this one, so the source that supplied only that name stops
        #    counting here. Measured: 14 rows change source count and 4 fall to a single
        #    source (camembert de Normandie, wild carrot, pesto variants, Dutch Mimolette),
        #    which correctly moves all four into the one-source flag.
        row["n_variations"] = len(row["variations"]) - 1
        if row["authored"]:
            # ⚠️ AN AUTHORED ROW KEEPS ITS EMPTY sources, WHICH IS THE POINT OF add_authored.
            #    Recomputing from the tags would put the placeholder word 'authored' into
            #    the source list, where it would read as a source name and would fire the
            #    "only one source says this exists" flag on a row that has none.
            continue
        row["sources"] = sorted({s for tags in row["variations"].values() for s, _, _ in tags})
        row["languages"] = sorted({l for tags in row["variations"].values()
                                   for _, _, l in tags if l})
    return moved


def apply_cuts(row, superclasses, off_parents):
    """⚠️ EVERY CUT NAMES AN ANCHOR. Read the anchor clause in ingredient_cuts.py before
    adding one: a cut phrased only as "single source and no variations" removes every
    override at once, because an override exists precisely because nothing corroborates
    the term."""
    marks = []
    if row.get("hand_reasons"):
        marks.append("hand")                          # ⚠️ Andy's call outranks every rule
    if (row["anchor"] == "wikidata"
            and set(superclasses.get(row["id"], [])) & set(CUTS.CULTIVAR_CLASSES)
            and len(row["sources"]) == 1 and row["n_variations"] == 0):
        marks.append("cultivar_register")
    # ⚠️ off_only USED TO FIRE HERE, on anchor == off_taxonomy and one source, and it
    #    took 3,549 rows. REVERSED, and the measurement that killed it is recorded in
    #    ingredient_cuts.DECLINED. It read "Open Food Facts is the only source" as
    #    "therefore this is label vocabulary", which is a claim about source coverage
    #    rather than about what a thing is. 56.7% of a read 60 were ordinary ingredients.
    #    ⚠️ NOTHING REPLACES IT YET, and that is deliberate. Read the label rows and put
    #    the verdicts in hand_removals.csv. A rule read back from evidence can come later.
    if (row["anchor"] == "off_taxonomy"
            and set(off_parents.get(row["id"], [])) & CUTS.OFF_FLAVOURING_PARENTS):
        marks.append("off_flavouring")
    return marks


def build_rows(join, src, kinds, superclasses, off_parents):
    by_entry, by_bucket = read_members(join)
    rule1, rule2, off_groups = pick_anchors(by_entry, by_bucket, kinds)

    stored_names = {}
    if src is not None:
        for table, source in (("wikidata_entry", "wikidata"),
                              ("off_taxonomy_entry", "off_taxonomy")):
            for entry_id, name in src.execute(f"SELECT entry_id, name FROM {table}"):
                stored_names[(source, entry_id)] = name

    entries = []
    for q in sorted(rule1 | rule2):
        key = ("wikidata", "food_items_q2095", q)
        entries.append({"anchor": "wikidata", "id": q, "seed": {key},
                        "buckets": {n for n, *_ in by_entry[key]},
                        "why": ("Wikidata kind is Ingredient or foodstuff" if q in rule1
                                else "Wikidata carries no kind, an OFF ingredient entry "
                                     "shares its name")})
    for group in off_groups:
        name = stored_names.get(("off_taxonomy", group[0][1]), "")
        if E_NUMBER.match(name.strip()) or name.strip().lower() in PROCESS_NAMES:
            continue                                  # additives and process words
        seed = {("off_taxonomy", d, e) for d, e in group}
        entries.append({"anchor": "off_taxonomy", "id": group[0][1], "seed": seed,
                        "buckets": {n for k in seed for n, *_ in by_entry[k]},
                        "why": "an Open Food Facts ingredients-taxonomy entry that "
                               "reaches no Wikidata item"})

    owned, intruders, articles = assign_ownership(entries, by_entry, by_bucket)
    subclass_count = collections.Counter()
    for parents in superclasses.values():
        for parent in parents:
            subclass_count[parent] += 1

    rows, dropped = [], collections.Counter()
    for i, entry in enumerate(entries):
        variations = owned.get(i)
        if not variations:
            continue
        item_kinds = sorted(kinds.get(entry["id"], {}).get("kinds", {}))
        fatal = [FATAL_KINDS[k] for k in item_kinds if k in FATAL_KINDS]
        if fatal:
            dropped[fatal[0] + ", even though Wikidata also calls it an ingredient"] += 1
            continue
        canonical, how = choose_canonical(entry, by_entry, stored_names)
        if canonical is None:
            best = [(len({s for s, _, _ in tags}), t) for t, tags in variations.items()
                    if any(k in PRIMARY_KINDS for _, k, _ in tags)]
            canonical = max(best)[1] if best else sorted(variations)[0]
        rows.append({
            "canonical": canonical, "how": how, "variations": variations,
            "n_variations": len(variations) - 1, "anchor": entry["anchor"],
            "id": entry["id"], "kinds": item_kinds, "why": entry["why"],
            "sources": sorted({s for tags in variations.values() for s, _, _ in tags}),
            "languages": sorted({l for tags in variations.values()
                                 for _, _, l in tags if l}),
            "subclasses": subclass_count.get(entry["id"], 0),
            "binomial": is_binomial(canonical, variations),
            "rule2": entry["why"].startswith("Wikidata carries no kind"),
            "dish": bool(DISH_KINDS & set(item_kinds)) and INGREDIENT in item_kinds,
            "override": False, "authored": False,
            # ⚠️ Names this row holds that are a SECOND primary name from one source in one
            #    language. See assign_ownership. resolve_borrowed decides what happens.
            "intruders": {t for t in intruders.get(i, ()) if t in variations},
            # ⚠️ THE en.wikipedia ARTICLES THIS ROW'S REDIRECT NAMES CAME FROM. Two or more
            #    means the row answers for two things en.wikipedia keeps apart. See
            #    the MEMBERS note in NOTES.
            "articles": sorted(articles.get(i, ())),
        })
    return rows, dropped, by_entry, by_bucket


def add_overrides(rows, by_entry, by_bucket, kinds, subclass_count):
    """The five hand-added terms. ⚠️ Report the list's size after every change: if it
    passes a few dozen the anchor rule is drawn in the wrong place."""
    for term, (failure, ident, reason) in CUTS.OVERRIDES.items():
        seed = {(s, d, e) for s, d, e, *_ in by_bucket.get(term, [])}
        if ident.startswith("Q"):
            seed.add(("wikidata", "food_items_q2095", ident))
        seed = {k for k in seed if k in by_entry}
        if not seed:
            continue
        variations, buckets = collections.defaultdict(set), set()
        for key in seed:
            for norm, kind, lang, text in by_entry[key]:
                variations[text].add((key[0], kind, (lang or "").lower()))
                buckets.add(norm)
        for bucket in buckets:
            for s, d, e, kind, lang, text in by_bucket[bucket]:
                if (s, d, e) in seed:
                    variations[text].add((s, kind, (lang or "").lower()))
        canonical = next((t for key in sorted(seed) for _, k, l, t in by_entry[key]
                          if k in PRIMARY_KINDS and (l or "").lower().startswith("en")),
                         term)
        anchor = "wikidata" if ident.startswith("Q") else "wiktextract"
        rows.append({
            "canonical": canonical, "how": "the anchor's own English name",
            "variations": dict(variations), "n_variations": len(variations) - 1,
            "anchor": anchor, "id": ident, "kinds": sorted(kinds.get(ident, {}).get("kinds", {})),
            "why": f"OVERRIDE ({failure}). {reason}",
            "sources": sorted({s for tags in variations.values() for s, _, _ in tags}),
            "languages": sorted({l for tags in variations.values() for _, _, l in tags if l}),
            "subclasses": subclass_count.get(ident, 0),
            "binomial": is_binomial(canonical, variations), "rule2": False, "override": True,
            "intruders": set(),      # hand-seeded from one bucket, so nothing can intrude
            "articles": [],
            "dish": bool(DISH_KINDS & set(kinds.get(ident, {}).get("kinds", {})))
                    and INGREDIENT in kinds.get(ident, {}).get("kinds", {}),
            "authored": False,
        })
    return rows


def annotate(rows, superclasses, off_parents):
    """Borrowed names, the five checks, confidence, and the cut marks.

    ⚠️ CONFIDENCE IS NOT A QUALITY AXIS AND NO CUT USES IT. 614 low entries carry three or
    more sources and Allium sativum is one of them. It sorts reading order, nothing else."""
    fold = lambda s: s.casefold().strip()
    by_canonical = collections.defaultdict(list)
    for i, row in enumerate(rows):
        by_canonical[fold(row["canonical"])].append(i)

    for i, row in enumerate(rows):
        row["borrowed"] = [
            (text, [rows[j]["canonical"] for j in by_canonical[fold(text)] if j != i])
            for text in row["variations"]
            if fold(text) != fold(row["canonical"])
            and any(j != i for j in by_canonical.get(fold(text), []))]
        row["english"] = english_names(row["variations"])
        row["alias_only"] = [t for t, tags in row["variations"].items()
                             if t != row["canonical"]
                             and all(k in ALIAS_KINDS for _, k, _ in tags)]
        row["cut_by"] = apply_cuts(row, superclasses, off_parents)

        flags = []
        for reason in row.get("hand_reasons", ()):
            flags.append(f"REMOVED BY HAND: {reason}")
        for note in row.get("trimmed", ()):
            flags.append(f"VARIATIONS TRIMMED BY HAND: {note}")
        if row["override"]:
            flags.append("ADMITTED BY HAND. See 'Why it is in the list' for the reason.")
        if row["authored"]:
            flags.append("AUTHORED BY HAND AND UNSOURCED. No source in the store has this "
                         "term. GENERATED under docs/sourcing-tiers.md until traced.")
        if row.get("renamed_from"):
            flags.append(f"RENAMED from '{row['renamed_from']}'. Wikidata's 'as food' "
                         "suffix is its own disambiguator, and no row claims the stem.")
        if len(row["articles"]) > 1:
            flags.append(
                f"answers for {len(row['articles'])} things en.wikipedia keeps apart, and "
                "each is a separate article whose redirects this row absorbed whole: "
                + ", ".join(row["articles"][:5])
                + (" ..." if len(row["articles"]) > 5 else ""))
        staying = sorted(row["intruders"] - {t for t, _, _ in row.get("resolved", ())}
                         - {row["canonical"]})
        if staying:
            flags.append(
                f"{len(staying)} name(s) here are a SECOND primary name from one source in "
                "one language, which means a second concept, and NOTHING ELSE IN THE LIBRARY "
                "CARRIES THEM so they stay rather than be lost: " + ", ".join(
                    repr(t) for t in staying[:4]))
        if row.get("resolved"):
            flags.append(f"{len(row['resolved'])} name(s) moved to the row that owns "
                         "them: " + "; ".join(f"'{t}' -> {o} ({why})"
                                              for t, o, why in row["resolved"][:3]))
        if row["borrowed"]:
            flags.append(f"holds {len(row['borrowed'])} name(s) another entry claims as "
                         "its own: " + "; ".join(
                             f"'{t}' belongs to {', '.join(o)}"
                             for t, o in row["borrowed"][:3]))
        if len(row["sources"]) == 1:
            # ⚠️ THIS IS A COVERAGE FACT, NOT A QUALITY ONE, and off_only was reversed for
            #    reading it as the latter. Open Food Facts alone carries cumin seeds.
            flags.append("only one source says this exists "
                         f"({SOURCE_NAME[row['sources'][0]]})")
        if row["binomial"]:
            flags.append("the canonical name is a scientific binomial, so a cook's name "
                         "has to be picked from the variations by hand")
        if row["rule2"]:
            flags.append("ADMITTED BY RULE 2, the weakest rule" + (
                f", and {row['subclasses']} items subclass it, which is what a CATEGORY "
                "looks like" if row["subclasses"] else ""))
        if row["n_variations"] >= 5:
            flags.append(f"{row['n_variations']} variations, and a third of buckets this "
                         "large measured wrong")
        if row["alias_only"]:
            flags.append(f"{len(row['alias_only'])} variation(s) rest only on a synonym, "
                         "alt_of or form field, which measured 20.8% wrong")
        if reviewed is not None:
            verdict = reviewed.lookup(row["canonical"])
            if verdict:
                flags.append(f"HAND-READ: {verdict}")
        row["flags"] = flags
        row["n_flags"] = len(flags)

        # ⚠️ An authored row is floored at low on purpose. Nothing corroborates it, and
        #    low sorts it to the top of the reading order where it stays visible.
        if (row["borrowed"] or len(row["sources"]) == 1 or row["authored"]
                or (row["rule2"] and row["subclasses"])):
            row["confidence"] = "low"
        elif len(flags) >= 2:
            row["confidence"] = "medium"
        elif len(flags) == 1:
            row["confidence"] = "medium" if row["n_variations"] >= 5 else "high"
        else:
            row["confidence"] = "high"
    return rows


# ─────────────────────────────────────────────────────────────────────────────────────
# The sheet. Facts left of judgements, a visible divider, two blank columns for the
# owner's call, and every header carrying its own caveat as a cell comment.
# ─────────────────────────────────────────────────────────────────────────────────────
CUT_RULE_TEXT = {
    "hand": "hand: removed by Andy, reason in 'What I was unsure about'",
    "cultivar_register": "cultivar register name: subclasses a Wikidata cultivar class, "
                         "one source, no variations",
    "off_flavouring": "OFF flavouring: parent is en:natural-flavouring or en:flavouring",
}
NOTES = {
 "canonical": "The name a cook would say, VERBATIM from the anchor's own English label.\n\n"
   "⚠ NO PROMOTION AND NO TIEBREAK BY LENGTH. An earlier build picked 'ail' for garlic and "
   "'wild garlic' for Allium sativum. A binomial canonical is FLAGGED instead.",
 "status": "kept or CUT.\n\n⚠ NOTHING IS DELETED. A cut row is MARKED with the rule that "
   "removed it, the same way join_exclusion records an excluded label row, so a cut can be "
   "read back and reversed by name.",
 "cut_txt": "WHICH RULE removed it. Blank on a kept row.\n\nThe rules, their thresholds and "
   "their known false positives live in ingredient_cuts.py.",
 "n_variations": "How many other names resolve to this entry. Five or more is a flag, not a "
   "verdict: garlic genuinely has hundreds across the languages the store holds.",
 "vars": "Every variation as  name  [language | sources | field]. ENGLISH FIRST, then "
   "by how many sources carry the name.\n\n⚠ THE CELL IS CAPPED AT 60 AND 832 ROWS "
   "OVERFLOW IT. Alphabetical order hid 32.9% of every variation in the store and 35.9% "
   "of the English names on the rows that overflow. What is hidden now is the least "
   "corroborated tail, and the last line says how many and how many were English.\n\n"
   "⚠ LANGUAGE IS SHOWN, and it is what makes the hing case readable. 'hing' on ginger is Zhuang. 'hing' on asafoetida "
   "is English.\n\nTRANSLATIONS ARE NOT HERE. join.db excludes them by rule, because including "
   "them puts a pillow in the guanciale bucket.",
 "sources": "Which of the five sources contribute anything.",
 "languages": "Every language code appearing on a variation, ENGLISH FIRST.\n\n"
   "⚠ SORTED ALPHABETICALLY THIS COLUMN COULD NOT ANSWER THE ONE QUESTION IT GETS ASKED. "
   "milk holds 312 codes and its 'en' sat at position 67, so the first twenty read "
   "'aa, ab, aeb-arab, af, am' and stopped. 176 rows had an English name the column hid.",
 "kinds": "The Wikidata grouping. SEVERAL KINDS IS THE DUAL NATURE, NOT AN ERROR.\n\n"
   "⚠ 'Cultivar or plant variety' matched zero of the 28,630 items, so the cultivar "
   "exclusion never fired. See vocab/README.md.",
 "anchor": "Which source made this an entry. Only Wikidata and OFF can anchor, plus the "
   "hand-added overrides.",
 "rule2": "TRUE for the 487 entries admitted by rule 2, the weakest rule.",
 "authored": "TRUE for rows Andy wrote, which no source in the store has.\n\n"
   "⚠ THESE ARE THE ONLY ROWS WITH NO ANCHOR. Every other row traces to a fetch. These "
   "exist because the thing exists and nothing we hold names it: 'salt' is 52 recipe "
   "lines and 32 dependents and had no row, so a line saying salt reached 'table salt' "
   "or 'sea salt', the wrong specific rather than the general thing.\n\n"
   "⚠ GENERATED under docs/sourcing-tiers.md until traced. Floored at low confidence "
   "because nothing corroborates them. The reason and the measurement behind each one "
   "are in authored_rows.csv.",
 "dish": "TRUE for the 653 rows Wikidata calls BOTH a dish or a cuisine AND an "
   "ingredient. Sort on it to read them.\n\n"
   "⚠ A MARK, NOT A VERDICT, AND NOT A REMOVAL QUEUE. Reading 40 at random found 16 "
   "dishes and 24 ingredients, 40% dishes, 95% CI [26%, 55%]. Moving all 653 would take "
   "chocolate, shrimp, honey, ham, soy sauce, oyster, carrot and rolled oats out of the "
   "library, and would cost 46 recipe lines.\n\n"
   "⚠ THE 'X as food' ROWS ARE NOT DISHES. pike as food, squid as food, razor shell as "
   "food, gar as food and dog cockle as food are Wikidata separating the ANIMAL from the "
   "FOOD, which is the distinction an ingredient library wants. 52 rows. Do not read them "
   "as removal candidates.\n\n"
   "⚠ Six discriminators were measured and none is usable, so nobody should propose one "
   "from memory. The best is a coin flip. The numbers are in ingredient_cuts.DECLINED "
   "under 'dish_separation'.",
 "confidence": "low / medium / high.\n\n⚠ CONFIDENCE IS NOT A QUALITY AXIS AND NO CUT USES IT. "
   "614 low entries carry three or more sources and Allium sativum is one of them.",
 "flags": "What I was unsure about, one per line. A line beginning HAND-READ is a verdict "
   "from reviewed.py, which is evidence rather than inference.",
 "n_flags": "How many checks fired. Sortable.",
 "subclasses": "How many Wikidata items name this one as a superclass.\n\n⚠ RANKS CATEGORIES, "
   "CANNOT DECIDE THEM. cheese has 86 children in OFF's tree, fruit 78, honey 44, rice 34.",
 "why": "Which admission rule let it in, or the recorded reason for a hand-added override.",
 "how": "How the canonical name was chosen.",
 "resolved": "Names this row USED TO carry that another row owns as its canonical, with "
   "the rule that moved each one.\n\n⚠ NOTHING IS LOST. A name only appears here when "
   "another row already claims it as its OWN canonical, so it still resolves, to that row "
   "instead of this one. Measured: 1,262 of 2,997 recipe lines match a library name before "
   "and after, unchanged to the line, while lines hitting a name TWO rows carry fall from "
   "490 to 266.\n\nThe two rules are in build_library.resolve_borrowed.",
 "articles": "The en.wikipedia ARTICLES whose redirects this row absorbed, shown only where "
   "there is more than one.\n\n⚠ A wikipedia_redirect entry is one article plus every name "
   "redirecting to it, so two articles on one row means the row answers for two things "
   "en.wikipedia keeps apart. fortified wine holds Fortified wine, Port wine and Sherry. "
   "dumpling holds ten, Gnocchi and Knedle and Knodel among them.\n\n⚠ THIS COSTS NOTHING "
   "AND WAS ALREADY IN join.db. 12,055 redirect entries, every one carrying its article "
   "title, and build_library read the field and ignored what it meant.\n\n217 rows are "
   "flagged over 281 recipe lines, 57% of them subclassed by something against a sheet "
   "baseline of 11.3%. 59 of the 217 carry NO second primary name, so the two signals are "
   "not the same check: peppercorn merging Pebre at 32 recipe lines is one of them.\n\n"
   "⚠ BOTH COUNTS ARE COMPUTED FROM OWNERSHIP. A first pass mapped variation TEXT back "
   "to redirect entries instead and reported 340 rows over 168 lines. It double-counted "
   "a name several articles redirect, and missed rows whose article title is not itself "
   "a variation. Ownership is the truth: 217 and 281.",
 "__blank": "Yours. Nothing is written here.", "__blank2": "Yours. Nothing is written here.",
 "__div1": "LEFT is copied verbatim from a source. RIGHT is my judgement.",
 "__div2": "RIGHT is yours.",
}
COLUMNS = [
 ("Ingredient", "canonical", 26), ("Kept or cut", "status", 10),
 ("Removed by which rule", "cut_txt", 44), ("Variations", "n_variations", 9),
 ("Every variation, with language, source and field", "vars", 70),
 ("Sources", "sources", 22), ("Languages", "languages", 20),
 ("What kind of thing it is", "kinds", 26), ("Anchored on", "anchor", 22),
 ("Admitted by rule 2", "rule2", 11), ("Dish as well as ingredient", "dish", 12),
 ("Authored, not sourced", "authored", 12),
 ("Names moved to their owner", "resolved", 46),
 ("Wikipedia articles it answers for", "articles", 34),
 (">>> JUDGEMENTS BELOW >>>", "__div1", 4),
 ("Confidence", "confidence", 11), ("What I was unsure about", "flags", 60),
 ("Checks that fired", "n_flags", 9), ("Things that subclass it", "subclasses", 11),
 ("Why it is in the list", "why", 42), ("How the name was chosen", "how", 30),
 (">>> YOUR CALL BELOW >>>", "__div2", 4), ("My call", "__blank", 16),
 ("My note", "__blank2", 36),
]


def write_sheet(rows, path):
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    fills = {k: PatternFill("solid", fgColor=v) for k, v in {
        "header": "1F3864", "divider": "595959", "fact": "DDEBF7", "judge": "FCE4D6",
        "yours": "E2EFDA", "low": "FFC7CE", "medium": "FFF2CC", "high": "E2EFDA",
        "cut": "D9D9D9", "override": "D9D2E9"}.items()}
    edge = Side(style="thin", color="BFBFBF")
    border = Border(left=edge, right=edge, top=edge, bottom=edge)
    order = {"low": 0, "medium": 1, "high": 2}

    def variation_text(row, cap=60):
        """⚠️ ORDER BEFORE TRUNCATING. THE OLD CAP DROPPED THE END OF THE ALPHABET.

        Measured over 11,153 rows: 832 hold more than 60 variations and the alphabetical
        cap hid 65,766 of 199,728 variation rows, 32.9% of everything the store knows.
        Worse than the volume is which rows it fell on. All 832 are flagged "5 or more
        variations, and a third of buckets this large measured wrong", so the truncation
        landed exactly on the rows most worth reading, and it hid 5,816 of their 16,197
        ENGLISH names, 35.9%, on 454 of the 832.

        milk is the worked case. 523 variations, 40 of them English, and the visible cell
        opened with Abe', abe', akeffay, akʷfay, amata.

        English first, then by how many sources carry the name, then alphabetical. What
        falls off the end is now the least corroborated tail rather than the letters after
        the sixtieth."""
        items = []
        for text, tags in row["variations"].items():
            if text == row["canonical"]:
                continue
            langs = sorted({l for _, _, l in tags if l})
            sources = sorted({SOURCE_NAME[s] for s, _, _ in tags})
            items.append(((text not in row["english"], -len(sources), text.casefold()),
                          "{}   [{} | {} | {}]".format(
                              text, ", ".join(langs) if langs else "no language stated",
                              ", ".join(sources),
                              ", ".join(sorted({FIELD_NAME.get(k, k) for _, k, _ in tags})))))
        items.sort(key=lambda kv: kv[0])
        if len(items) <= cap:
            return "\n".join(text for _, text in items)
        hidden = items[cap:]
        n_en = sum(1 for key, _ in hidden if not key[0])
        return "\n".join([text for _, text in items[:cap]] + [
            f"... and {len(hidden)} more, {n_en} of them English. English names and the "
            "best-corroborated come first, so what is hidden is the least corroborated "
            "tail."])

    def language_text(row, cap=20):
        """⚠️ ENGLISH FIRST, BECAUSE THE QUESTION THIS COLUMN GETS ASKED IS WHETHER THE ROW
        HAS AN ENGLISH NAME AT ALL, and sorted alphabetically it could not answer.

        1,783 rows carry more than 20 language codes and the first-20 cut hid 57,589 of
        them. milk holds 312 and its 'en' sat at alphabetical position 67, so the column
        read aa, ab, aeb-arab, af, am and stopped. On 176 rows the code was present and
        invisible.

        ⚠️ Every row with an English name carries an 'en*' code, all 9,668 of them, so the
        column can answer the question once 'en' is put where it can be seen. The
        wikipedia_redirect rows that state no language of their own are all covered by an
        en-tagged name from another source."""
        first = [l for l in row["languages"] if l.startswith("en")]
        rest = [l for l in row["languages"] if not l.startswith("en")]
        shown = (first + rest)[:cap]
        extra = len(row["languages"]) - len(shown)
        return ", ".join(shown) + (f", ... and {extra} more" if extra else "")

    def sheet(ws, data, banner):
        divider = next(i for i, (_, k, _) in enumerate(COLUMNS, 1) if k == "__div1")
        for i, (head, key, width) in enumerate(COLUMNS, 1):
            cell = ws.cell(1, i)
            cell.value = (banner if i == 1 else "DERIVED, my judgement"
                          if key == "confidence" else "YOURS" if head == "My call" else "")
            cell.fill = fills["fact"] if i < divider else (
                fills["yours"] if key in ("__blank", "__blank2", "__div2") else fills["judge"])
            cell.font = Font(bold=True, size=9, color="333333")
            cell.border = border
        for i, (head, key, width) in enumerate(COLUMNS, 1):
            cell = ws.cell(2, i)
            cell.value = head
            cell.fill = fills["divider"] if key.startswith("__div") else fills["header"]
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = border
            if key in NOTES:
                note = NOTES[key]
                comment = Comment(head.upper() + "\n\n" + note, "build_library.py")
                comment.width = 350
                comment.height = max(140, 32 + 13 * (len(note) // 50 + note.count("\n") * 2))
                cell.comment = comment
            ws.column_dimensions[get_column_letter(i)].width = width
        for r, row in enumerate(data, 3):
            values = {
                "canonical": row["canonical"], "status": "CUT" if row["cut_by"] else "kept",
                "cut_txt": "\n".join(CUT_RULE_TEXT[c] for c in row["cut_by"]),
                "n_variations": row["n_variations"], "vars": variation_text(row),
                "sources": ", ".join(SOURCE_NAME[s] for s in row["sources"]),
                "languages": language_text(row),
                "kinds": ", ".join(row["kinds"]) or (
                    "(authored, so no source classified it)" if row["authored"] else
                    "(OFF entry, Wikidata never classified it)"
                    if row["anchor"] == "off_taxonomy" else "(Wikidata carries no kind)"),
                "anchor": (f"authored by hand, no source  {row['id']}" if row["authored"]
                           else f"{SOURCE_NAME[row['anchor']]}  {row['id']}"),
                "rule2": "yes" if row["rule2"] else "",
                "dish": "yes" if row["dish"] else "",
                "authored": "yes" if row["authored"] else "",
                "resolved": "\n".join(f"{t}  ->  {o}   [{why}]"
                                      for t, o, why in row.get("resolved", ())),
                "articles": "\n".join(row["articles"]) if len(row["articles"]) > 1 else "",
                "confidence": row["confidence"],
                "flags": "\n".join(row["flags"]), "n_flags": row["n_flags"],
                "subclasses": row["subclasses"] or "", "why": row["why"], "how": row["how"]}
            for i, (head, key, width) in enumerate(COLUMNS, 1):
                cell = ws.cell(r, i)
                if key.startswith("__div"):
                    cell.fill, cell.border = fills["divider"], border
                    continue
                if key.startswith("__blank"):
                    cell.fill, cell.border = fills["yours"], border
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
                    continue
                cell.value = values.get(key, "")
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                cell.border, cell.font = border, Font(size=10)
                if key == "status":
                    cell.fill = fills["cut"] if row["cut_by"] else fills["high"]
                    cell.font = Font(size=10, bold=True)
                elif key == "confidence":
                    cell.fill = fills[row["confidence"]]
                    cell.font = Font(size=10, bold=True)
                elif row["override"]:
                    cell.fill = fills["override"]
        ws.freeze_panes = "B3"
        ws.auto_filter.ref = f"A2:{get_column_letter(len(COLUMNS))}{len(data) + 2}"
        ws.row_dimensions[1].height = 13
        ws.row_dimensions[2].height = 56

    kept = sorted((r for r in rows if not r["cut_by"]),
                  key=lambda r: (order[r["confidence"]], -r["n_flags"], -r["n_variations"],
                                 r["canonical"].casefold()))
    cut = sorted((r for r in rows if r["cut_by"]),
                 key=lambda r: (order[r["confidence"]], -r["n_flags"], -r["n_variations"],
                                r["canonical"].casefold()))
    rule2 = sorted((r for r in rows if r["rule2"]),
                   key=lambda r: (-r["subclasses"], -r["n_variations"],
                                  r["canonical"].casefold()))
    book = openpyxl.Workbook()
    sheet(book.active, kept, f"THE LIST, {len(kept):,} kept rows")
    book.active.title = "ingredients (kept)"
    sheet(book.create_sheet("cut, with the rule"), cut,
          f"CUT, {len(cut):,} rows. NOTHING DELETED. Filter 'Removed by which rule'.")
    sheet(book.create_sheet("rule 2, decide by hand"), rule2,
          f"THE {len(rule2)} RULE-2 ENTRIES, sorted by subclass count. Nothing removed.")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    book.save(path)
    return len(kept), len(cut), len(rule2)


def guard_unharvested(path, removals):
    """⚠️ REFUSE TO OVERWRITE A SHEET CARRYING MARKS THE CSV HAS NOT SEEN.

    This is the whole reason marking in the spreadsheet is safe to recommend. Mark forty
    rows, forget to harvest, rebuild, and the reading would be gone. That is the exact
    failure that moved the overrides out of a scratchpad, so the build stops instead."""
    if not os.path.exists(path):
        return
    try:
        import openpyxl
        import harvest_marks
    except ImportError:
        return
    book = openpyxl.load_workbook(path, read_only=True)
    unseen, heads = [], None
    for ws in book:
        for i, values in enumerate(ws.iter_rows(values_only=True), 1):
            if i == 2:
                heads = {str(v): j for j, v in enumerate(values) if v}
                continue
            if i < 3 or heads is None:
                continue
            def cell(name):
                j = heads.get(name)
                return values[j] if j is not None and j < len(values) else None
            call = cell("My call")
            if not (call and str(call).strip()):
                continue
            action, extra = harvest_marks.parse_call(str(call))
            if action in (None, "keep"):
                continue
            parts = str(cell("Anchored on") or "").split()
            anchor = harvest_marks.SOURCE_KEY.get(parts[0]) if parts else None
            if anchor is None:
                continue
            key = (anchor, " ".join(parts[1:]))
            if not any(r["action"] == action and (r.get("variation") or "") == extra
                       for r in removals.get(key, ())):
                unseen.append((cell("Ingredient"), call))
    if unseen:
        listed = "\n".join(f"      {n!r} marked {c!r}" for n, c in unseen[:12])
        more = f"\n      ... and {len(unseen) - 12} more" if len(unseen) > 12 else ""
        raise SystemExit(
            f"⚠️  REFUSING TO OVERWRITE {path}.\n"
            f"  It carries {len(unseen)} mark(s) that hand_removals.csv has not recorded, "
            "and rebuilding would discard them:\n"
            f"{listed}{more}\n\n"
            "  Run this first, then rebuild:\n"
            "      python3.13 harvest_marks.py")


def build(join_db=JOIN_DB, sources_db=SOURCES_DB, out=OUT, verbose=True):
    def say(*a):
        if verbose:
            print(*a, flush=True)

    if not os.path.exists(join_db):
        raise SystemExit(f"{join_db} not found. Run build_join.py first.")
    join = sqlite3.connect(f"file:{join_db}?mode=ro", uri=True)
    # ⚠️ sources.db IS REQUIRED, AND AN EARLIER DRAFT MADE IT OPTIONAL. That draft ran
    #    happily without it and produced 11,769 entries instead of 11,153, because the
    #    E-number and process-word filters read OFF's stored entry names and silently
    #    matched nothing, letting 614 additives and 2 process words through. Canonical
    #    names diverged too. A build that runs and quietly returns a different list is
    #    worse than one that stops, so it stops.
    if not os.path.exists(sources_db):
        raise SystemExit(
            f"{sources_db} not found, and it is REQUIRED.\n"
            "  It supplies OFF's stored entry names, which the E-number and process-word\n"
            "  filters need, and the English glosses. Without it this script would return\n"
            "  11,769 entries instead of 11,153 and would not say so.\n"
            "  Rebuild it with fetch_sources.py then build_sources_db.py, or restore it\n"
            "  from a backup. vocab/off-taxonomy-tree.json is a committed copy of the OFF\n"
            "  tree for reading, NOT a substitute for the corpus.")
    src = sqlite3.connect(f"file:{sources_db}?mode=ro", uri=True)
    src.execute("PRAGMA query_only = ON")

    kinds, superclasses, committed_tree = load_vocab()
    say(f"vocab loaded: {len(kinds):,} kinds, {len(superclasses):,} superclass rows")
    off_parents = off_tree(src) or committed_tree
    say(f"OFF tree: {len(off_parents):,} entries with a parent, rebuilt from sources.db")

    rows, dropped, by_entry, by_bucket = build_rows(join, src, kinds, superclasses,
                                                    off_parents)
    subclass_count = collections.Counter()
    for parents in superclasses.values():
        for parent in parents:
            subclass_count[parent] += 1
    rows = add_overrides(rows, by_entry, by_bucket, kinds, subclass_count)
    # ⚠️ AFTER the overrides and BEFORE the removals, so a hand removal can target an
    #    authored row the same way it targets any other. Its key is ("", <id>).
    authored, authored_rejected = load_authored()
    rows = add_authored(rows, authored, subclass_count)

    removals, rejected = load_removals()
    rows, dangling = apply_removals(rows, removals)

    # ⚠️ THE RENAME RUNS FIRST AND THE PRECEDENCE RULES SECOND, because a rename changes
    #    the canonical set the precedence rules read. Measured both orders: renaming first
    #    costs 5 of rule 1's 509 names and 0 of rule 2's, and stripping 'as food' ADDS 7
    #    borrowed pairs, because a stem that was hidden behind a suffix now collides with
    #    names other rows hold. Precedence has to run after that or it misses those 7.
    renamed = strip_as_food(rows)
    moved = resolve_borrowed(rows, superclasses, off_parents)
    rows = annotate(rows, superclasses, off_parents)

    say(f"\nentries: {len(rows):,}")
    for reason, n in dropped.most_common():
        say(f"  removed by kind: {n:5,d}  {reason}")
    marks = collections.Counter(m for r in rows for m in r["cut_by"])
    for name, n in sorted(marks.items()):
        # ⚠️ 'hand' is Andy's call, not a rule in ingredient_cuts.py, so there is no
        #    recorded count to reconcile against and asking for one is a KeyError.
        recorded = CUTS.CUTS.get(name, {}).get("takes")
        note = f"   (ingredient_cuts.py records {recorded:,})" if recorded else \
               "   (hand removals, reasons in hand_removals.csv)"
        say(f"  marked {name:20s} {n:5,d}{note}")
    n_removals = sum(len(v) for v in removals.values())
    say(f"  authored rows read: {len(authored):,}   "
        + (", ".join(r["name"] for r in authored) if authored else "none"))
    for row in authored_rejected:
        say(f"  ⚠️  REJECTED, no reason given: authored row {row.get('id')}. "
            "A row without a reason is not created.")
    say(f"  hand removals read: {n_removals:,} over {len(removals):,} entries")
    for row in rejected:
        say(f"  ⚠️  REJECTED, no reason given: {row.get('anchor')} {row.get('id')} "
            f"{row.get('action')}. A removal without a reason is not applied.")
    if dangling:
        # ⚠️ REPORTED, NEVER FATAL. The commonest cause is a rule already dropping the
        #    entry, which is good news. Silence is what rots, so it prints every build.
        say(f"  ⚠️  {len(dangling)} DANGLING removal(s): the entry is no longer generated, "
            "so the removal did nothing. A rule may have done the job first, or a key "
            "may have shifted.")
        for row in dangling[:15]:
            say(f"        {row['anchor']} {row['id']} {row['action']}  ({row['reason'][:60]})")
    multi = [r for r in rows if len(r["articles"]) > 1]
    say(f"  rows answering for 2+ en.wikipedia articles: {len(multi):5,d}   "
        f"{sum(len(r['articles']) for r in multi):,} articles between them")
    marked = sum(len(r["intruders"]) for r in rows)
    say(f"  second primary names marked: {marked:5,d} over "
        f"{sum(1 for r in rows if r['intruders']):,} entries")
    say(f"  renamed off 'as food':   {len(renamed):5,d}   "
        "(19 more are left alone: the bare stem is another row's canonical)")
    for rule, n in sorted(moved.items()):
        say(f"  names moved to their owner: {n:5,d}  {rule}")
    say(f"  override list size: {len(CUTS.OVERRIDES)}   "
        "⚠️ if this passes a few dozen the anchor rule is drawn in the wrong place")

    # ⚠️ THE ANCHOR-CLAUSE CHECK. Never ship a cut without re-running the overrides.
    index = collections.defaultdict(set)
    for i, row in enumerate(rows):
        index[row["canonical"].casefold()].add(i)
        for text in row["variations"]:
            index[text.casefold()].add(i)
    killed = [t for t in CUTS.OVERRIDES
              if index.get(t.casefold()) and all(rows[i]["cut_by"] for i in index[t.casefold()])]
    if killed:
        raise SystemExit(f"⚠️  A CUT REMOVED AN OVERRIDE: {killed}. Read the anchor clause "
                         "in ingredient_cuts.py.")
    say("  anchor-clause check: every override survives every cut")

    guard_unharvested(out, removals)
    kept, cut, rule2 = write_sheet(rows, out)
    say(f"\nwrote {out}")
    say(f"  ingredients (kept)       {kept:6,d}")
    say(f"  cut, with the rule       {cut:6,d}")
    say(f"  rule 2, decide by hand   {rule2:6,d}")
    return rows


if __name__ == "__main__":
    build()
