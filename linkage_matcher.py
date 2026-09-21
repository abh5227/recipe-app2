#!/usr/bin/env python3
"""linkage_matcher.py - propose a catalog link for every recipe ingredient line.

IT NEVER WRITES A LINK. It reads recipes.db and emits a proposal file. A separate step writes only
what a human has approved in that file. The reason is asymmetry: an UNLINKED line renders exactly as
it does today, while a WRONGLY linked line shows another ingredient's prose, safety flags and
allergen warnings under the wrong name. The pipeline fails toward the first.

⚠️ IT MATCHES THE BUILT CATALOG, NOT join.db. An earlier analysis pass matched raw join_member and
every number it produced was void, because build_library MOVES roughly 4,000 names between rows
before writing the catalog (2,906 for a seeded authored row alone). A name's row in the raw join is
an INPUT to the build, not its output. `library_names` in recipes.db is the shipped catalog and the
only correct thing to match.

THE THREE TIERS, and the middle one is the whole review:
    EXACT       the canonical, or its depluralized form, is what the line says. No inference.
    FORM_STRIP  a modifier was removed to reach a match. This IS an inference and is reviewable.
    AMBIGUOUS   the name is held by more than one catalog row. REFUSED, never picked.

DECIDED CASES ARE NOT RE-ASKED. Judgements already made about food (green onion is scallion,
coriander alone means cilantro) are artifact-independent, so they are reused rather than re-reviewed.
Only their TARGET is re-confirmed against the built catalog, since a row's id can move. A line
resolved by a prior decision is marked DECIDED and needs a spot-check, not a decision.
"""
import collections, csv, re, sqlite3, sys, unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from build_join import norm_name
from build_library import depluralize

DB = BASE_DIR / "recipes.db"
ALIAS_DECISIONS = BASE_DIR / "previews" / "alias-collisions.csv"

# Judgements settled by reading the corpus rather than by a rule. Each maps a normalized recipe name
# to the canonical a cook means. The TARGET is resolved against the built catalog at load time, so a
# moved id is caught rather than silently mislinking.
#   coriander: 31 lines say coriander. 22 say 'coriander seed' or 'ground coriander' and reach those
#              rows directly. Only 4 reach a bare 'coriander' and 3 of them read 'coriander/cilantro'.
#   the rest:  every occurrence in the corpus carries the qualifier, so the corpus settles them.
DECIDED_BY_CORPUS = {
    "coriander":     "cilantro",
    "kernel":        "corn kernel",
    "coffee powder": "instant coffee",
    "makrut lime":   "makrut lime leaves",
    "thai lime":     "makrut lime leaves",
    # 'half-and-half cream' is half-and-half with a redundant suffix. No strip rule separates it
    # (adding 'cream' as trailing noise would break 'sour cream'), so it is named here.
    "half and half cream": "half-and-half",
}
# Names with no safe target. Mapping them would MANUFACTURE a wrong match, which is worse than a miss.
# ⚠️ sprout ADDED 2026-09-15, and it was nearly given a row instead. 3,230 corpus recipes lose a base
#    facet on it and the catalog holds 23 sprout specifics, so a general row looked obvious. Wikibooks
#    settles it the other way: Cookbook:Sprout is a DISAMBIGUATION page reading "the term sprout is an
#    ambiguous term that may refer to: Brussels sprouts, Bean sprouts, Sprouted (germinated) seeds."
#    Three different foods, so a bare 'sprout' has no safe target, exactly like 'meal' above. Refusing
#    it costs 3,230 misses and a row would have cost 3,230 wrong matches.
# ⚠️ FOUR ADDED 2026-09-16 from the class A review, and only four of eleven refusals. The other
#    seven ('raw', 'dairy', 'cut', 'buffer', 'varietal', 'celebrity', 'salt, pepper') are not food
#    words at all and will never be proposed again, so they live in docs/open-library-queues.md
#    rather than bloating a set whose job is FOOD-WORD ambiguity. These four are words a cook
#    really writes, with a target that is wrong rather than missing, so a later pass could
#    re-propose them:
#      amaretto  an almond liqueur. The only near row is 'Amaretto macaron', a cookie.
#      pastry    broader than 'pastry dough', and 'pastry cream' and 'pastry flour' also exist.
#      soy       'soy sauce' or 'soy bean', and US recipes mean the first. Genuinely two targets.
#      tartar    ⚠️ 'tartar sauce' against 'cream of tartar'. A baking line saying tartar means
#                the raising agent and would land on mayonnaise. The worst of the four.
DROPPED = {"rose", "meal", "blood pudding", "custard apple", "red tea", "sprout",
           "amaretto", "pastry", "soy", "tartar"}


# ⚠️ SPELLING FOLDS, each one measured against the unmatched set rather than guessed.
#   chile/chilli/chillies  the corpus uses all three spellings and the catalog holds one.
#                          ⚠️ These fold to a bare 'chili', which reaches Q165199 through the
#                          ALIAS since 2026-09-16. The hardcode that used to do it is retired,
#                          and these three stay because they work inside a phrase: 'chilli
#                          powder' folds to 'chili powder', which no alias can do.
#   Parmigiano             Parmigiano, Parmigiano Reggiano and Parmigiana all name the catalog's
#                          'Parmesan'. 6 lines.
#   the typos              tumeric, brussel, crimini, jalepeno, semi-sweet, yoghourt. Each was
#                          read in the corpus, not invented.
#   ⚠️ THE YOGHURT ENTRY IS NOT WHAT IT LOOKS LIKE, and this comment used to say 'yoghurt'.
#                          The pattern is \byoghou?rt\b, which matches yoghourt and yoghort and
#                          NOT the commoner yoghurt, since that has no 'o' after the 'h'. The
#                          bare word 'yoghurt' reaches Q13317 through an alias instead. The two
#                          cover different spellings and neither is redundant. A phrase like
#                          'greek yoghurt' is reached by neither and is still unmatched.
_FOLDS = [
    (r"\bchill?ies\b", "chili"), (r"\bchill?i\b", "chili"), (r"\bchiles?\b", "chili"),
    (r"\bparmigian[oa]( reggiano)?\b", "parmesan"), (r"\bparm\b", "parmesan"),
    (r"\byoghou?rt\b", "yogurt"), (r"\btumeric\b", "turmeric"),
    (r"\bbrussel\b", "brussels"), (r"\bcrimini\b", "cremini"),
    (r"\bjalepeno\b", "jalapeno"), (r"\bsemi sweet\b", "semisweet"),
]


def fold(s):
    """Diacritic-strip, then apply the measured spelling folds. WARNING: this is for MATCHING only.
    It never changes what is stored or displayed."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = norm_name(s)
    for pat, rep in _FOLDS:
        s = re.sub(pat, rep, s)
    # ⚠️ THE BARE-'chili' HARDCODE WAS RETIRED 2026-09-16 when library_aliases was wired into
    #    load_catalog. It read `if s == "chili": s = "chili pepper"`, and its twin in
    #    load_catalog copied the chili pepper rows under the bare word. Both existed for one
    #    reason: the catalog had no row a bare 'chili' could reach. 'chili' is now an alias on
    #    Q165199, so the table states what the hardcode used to assume. The three spelling
    #    folds above still do their own job, turning chilli, chillies, chile and chiles into
    #    'chili' ANYWHERE IN A PHRASE, which an alias on one row cannot do.
    return s


def load_catalog(conn, source_slug=None):
    """Every name the catalog answers to, normalized, mapping to the rows that own it.

    ⚠️ source_slug SELECTS WHICH ALIASES ARE LIVE, and None is not "all of them", it is
    "the unscoped ones". A scoped alias exists because two sources disagree about what a name
    means, so applying india's 'corn flour' -> cornstarch to a RecipeNLG line would be the
    resolved-but-wrong failure the scope was added to prevent. Passing no slug is what a local
    recipe and every existing caller get, and it is the conservative half. See migrations/047.

    ⚠️ ALIASES ARE READ HERE, AND UNTIL 2026-09-16 THEY WERE NOT. library_aliases held 164 rows
    that no code path consulted, so every alias applied by the class A, class B and tier 0
    passes was recorded and inert. Measured before wiring, in previews/alias-wiring-scoping.md:
    163 keys gained, 0 keys made ambiguous, 0 existing targets changed, and 160 of the 164
    aliases change a word's outcome.

    ⚠️ AN ALIAS INDEXES TO ITS ROW'S CANONICAL, NOT TO ITSELF. The matcher's output names the
    row, and putting the alias string there would report a name the catalog does not display.

    ⚠️ BOTH norm_name AND fold ARE INDEXED. They differ for some aliases, and indexing one
    leaves the other spelling unreachable."""
    cat = collections.defaultdict(list)
    canon_of = {}
    for lid, canon in conn.execute("select library_id, canonical from library_names"):
        canon_of[lid] = canon
        cat[norm_name(canon)].append((lid, canon))
        f = fold(canon)
        if f != norm_name(canon) and (lid, canon) not in cat[f]:
            cat[f].append((lid, canon))
    # ⚠️ A DATABASE WITHOUT MIGRATION 047 HAS NO source_slug AND MUST STILL MATCH. The four
    #    mining run scripts read recipes.db by name, and a live database one migration behind
    #    would otherwise crash the matcher on a column it has never heard of. Every alias in
    #    such a database is unscoped by definition, so the unscoped query is the correct
    #    reading of it, not a degraded one. Same reasoning as the cut-row skip below.
    scoped = any(r[1] == "source_slug"
                 for r in conn.execute("PRAGMA table_info(library_aliases)"))
    if not scoped:
        q, params = "select library_id, alias from library_aliases", ()
    elif source_slug is None:
        q, params = "select library_id, alias from library_aliases where source_slug is null", ()
    else:
        q = ("select library_id, alias from library_aliases "
             "where source_slug is null or source_slug = ?")
        params = (source_slug,)
    for lid, alias in conn.execute(q, params):
        canon = canon_of.get(lid)
        if canon is None:          # an alias whose row was cut. load_aliases refuses these,
            continue               # and a stale database is not worth crashing the matcher for
        for key in {norm_name(alias), fold(alias)}:
            if (lid, canon) not in cat[key]:
                cat[key].append((lid, canon))
    return cat


def load_decisions(cat, path=ALIAS_DECISIONS):
    """Prior food judgements, re-pointed at the built catalog. Returns (decisions, problems)."""
    decided, problems = {}, []
    by_id = {lid: canon for rows in cat.values() for lid, canon in rows}
    if path.exists():
        for r in csv.DictReader(open(path, encoding="utf-8")):
            if r["proposal"] != "RESOLVE" or not r["resolve_to"]:
                continue
            lid = r["resolve_to"].split("=")[0]
            if lid not in by_id:
                problems.append(f"{r['alias']!r}: target {lid} is not in the built catalog")
                continue
            decided[norm_name(r["alias"])] = (lid, by_id[lid], "prior decision")
    for alias, canon in DECIDED_BY_CORPUS.items():
        rows = cat.get(norm_name(canon), [])
        if len(rows) != 1:
            problems.append(f"{alias!r}: {canon!r} resolves to {len(rows)} catalog rows")
            continue
        decided[norm_name(alias)] = (rows[0][0], rows[0][1], "settled by the corpus")
    return decided, problems


def match(core, cat, decided):
    """Returns (tier, matched_name, rows, rule)."""
    n = fold(core)
    if n in DROPPED:
        return "DROPPED", n, [], "no safe target"
    if n in decided:
        lid, canon, why = decided[n]
        return "DECIDED", canon, [(lid, canon)], why
    if n in cat:
        return ("AMBIGUOUS" if len(cat[n]) > 1 else "EXACT"), n, cat[n], "exact"
    d = depluralize(n)
    if d and d in cat:
        return ("AMBIGUOUS" if len(cat[d]) > 1 else "EXACT"), d, cat[d], "plural"
    from recipe_line_parser import strip_forms, FORM as FORM_WORDS          # the validated stripper, imported where it is used
    m, dropped = strip_forms(n, lambda k: k in cat or k in decided, depluralize)
    if m:
        # ⚠️ A DECISION APPLIES AFTER STRIPPING, NOT ONLY ON AN EXACT CORE. 'fresh coriander' has to
        #    strip to 'coriander' before the coriander-means-cilantro judgement can fire. Checking
        #    only the unstripped core left 5 coriander lines unmatched.
        if m in decided and not any(w in FORM_WORDS for w in dropped):
            # ⚠️ ONLY AFTER PREP. 'fresh coriander' is still coriander-the-bare-word and the
            #    cilantro judgement applies. 'ground coriander' is NOT: 'ground' is an identity
            #    word and ground coriander is the SEED. Letting a decision fire after a FORM word
            #    was dropped sent 'ground coriander' to cilantro, which is simply wrong.
            lid, canon, why = decided[m]
            return "DECIDED", canon, [(lid, canon)], f"{why} after prep strip:" + " ".join(dropped)
        rows = cat.get(m, [])
        if not rows:
            # m was reachable only because it is a DECIDED name, and the decision was blocked
            # (a FORM word was dropped). There is no catalog row here, so this is a miss, not a
            # match with an empty target.
            return "UNMATCHED", n, [], "decision blocked: a form word was dropped"
        return ("AMBIGUOUS" if len(rows) > 1 else "FORM_STRIP"), m, rows, \
               "form_strip:" + " ".join(dropped)
    return "UNMATCHED", n, [], "none"


def propose(db=DB, only_recipe=None):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cat = load_catalog(conn)
    decided, problems = load_decisions(cat)
    sourced = {l: e for e, l in conn.execute(
        "select entry_id, library_id from library_entries where library_id is not null")}
    q = """select ri.id, ri.recipe_id, ri.label, ri.raw_text
           from recipe_ingredients ri where ri.is_heading = 0"""
    args = ()
    if only_recipe:
        q += " and ri.recipe_id = ?"; args = (only_recipe,)
    lines = conn.execute(q, args).fetchall()
    conn.close()

    from recipe_line_parser import parse
    out = []
    for rid, recipe, label, raw in lines:
        txt = (label or raw or "").strip()
        core, rules, flags = parse(txt)
        if not core:
            out.append(dict(id=rid, recipe=recipe, raw=txt, core="", tier="NOT_AN_INGREDIENT",
                            matched="", catalog_id="", canonical="", rule="", sourced="",
                            words_dropped=0))
            continue
        tier, m, rows, rule = match(core, cat, decided)
        one = rows[0] if len(rows) == 1 else ("", "")
        out.append(dict(id=rid, recipe=recipe, raw=txt, core=core, tier=tier, matched=m,
                        catalog_id=one[0], canonical=one[1], rule=rule,
                        sourced=sourced.get(one[0], ""),
                        words_dropped=max(0, len(norm_name(core).split()) - len(str(m).split()))))
    return out, problems
