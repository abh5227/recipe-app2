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
import argparse, collections, csv, re, sqlite3, sys, unicodedata
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
DROPPED = {"rose", "meal", "blood pudding", "custard apple", "red tea"}


# ⚠️ SPELLING FOLDS, each one measured against the unmatched set rather than guessed.
#   chile/chilli/chillies  the corpus uses all three spellings and the catalog holds one.
#   bare 'chili'           the catalog has no 'chili' row, it has 'chili pepper', so a bare chili
#                          would otherwise reach nothing at all. 24 lines.
#   Parmigiano             Parmigiano, Parmigiano Reggiano and Parmigiana all name the catalog's
#                          'Parmesan'. 6 lines.
#   the typos              tumeric, brussel, crimini, jalepeno, semi-sweet, yoghurt. Each was read
#                          in the corpus, not invented.
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
    # the catalog has no bare 'chili' row, only 'chili pepper'
    if s == "chili":
        s = "chili pepper"
    return s


def load_catalog(conn):
    cat = collections.defaultdict(list)
    for lid, canon in conn.execute("select library_id, canonical from library_names"):
        cat[norm_name(canon)].append((lid, canon))
        f = fold(canon)
        if f != norm_name(canon) and (lid, canon) not in cat[f]:
            cat[f].append((lid, canon))
    # ⚠️ strip_forms generates a bare 'chili' and the catalog only has 'chili pepper', so the
    #    stripped form would reach nothing. Index the row under the bare word too.
    if "chili pepper" in cat and "chili" not in cat:
        cat["chili"] = list(cat["chili pepper"])
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
