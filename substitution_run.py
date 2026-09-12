#!/usr/bin/env python3
"""substitution_run.py - phase 3d part 1. Substitution CANDIDATES, not facts.

⚠️ IT PROPOSES, IT DOES NOT ASSERT. The 3d diagnostic measured substitutions as thin and
error-prone: 27.6% clean, direction reversing on a preposition, 9% of survivors silently
truncated. Errors wash out in a statistic over millions and do not wash out in a small set of
specific claims, where one wrong row tells a cook to replace the wrong thing. So the output is a
review queue and a person decides. See previews/substitution-curation-scoping.md.

⚠️ NO SENTENCE SURVIVES THE MATCH. docs/mining-decision.md (b) and (f). The extractor emits
(from_id, to_id, pattern_label, n). The pattern label is provenance, the name of the rule that
fired. The clause it read is never returned, never stored, never kept for debugging, because
that is the documented way this boundary erodes.
"""
import argparse, ast, collections, csv, json, re, sqlite3, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import brand_guard as BG
import linkage_matcher as LM
import mining_probe as MP
import nonfood_filter as NF
from recipe_line_parser import parse

csv.field_size_limit(10_000_000)
SOURCE_SLUG = "recipenlg-2020"

# ⚠️ DIRECTION IS SET BY THE PREPOSITION, NOT THE VERB. "substitute X for Y" replaces Y with X.
#    "X substituted with Y" replaces X with Y. Same verb, opposite reading, and a rule written on
#    the verb alone gets half of them backwards. A backwards substitution is worse than a missing
#    one: it tells a cook to replace the thing they have with the thing they do not.
RULES = [
    ("instead of",   r"\b(?:use|used|using|add|adding|try)\s+(?P<to>.{2,40}?)\s+instead of\s+(?P<frm>.{2,40}?)(?=[.,;:)]|\s+(?:and|or|in|to|for|if|when|which|that)\b|$)"),
    ("in place of",  r"\b(?P<to>.{2,40}?)\s+(?:can be |may be |)(?:used\s+)?in place of\s+(?P<frm>.{2,40}?)(?=[.,;:)]|\s+(?:and|or|in|to|for|if|when|which|that)\b|$)"),
    ("sub X for Y",  r"\bsubstitut(?:e|ed|ing)\s+(?P<to>.{2,40}?)\s+for\s+(?P<frm>.{2,40}?)(?=[.,;:)]|\s+(?:and|or|in|to|if|when|which|that)\b|$)"),
    ("sub'd for",    r"\b(?P<to>.{2,40}?)\s+(?:can|may|could)\s+be\s+substituted\s+for\s+(?P<frm>.{2,40}?)(?=[.,;:)]|\s+(?:and|or|in|to|if|when|which|that)\b|$)"),
    ("sub'd with",   r"\b(?P<frm>.{2,40}?)\s+(?:can|may|could)\s+be\s+substituted\s+with\s+(?P<to>.{2,40}?)(?=[.,;:)]|\s+(?:and|or|in|to|if|when|which|that)\b|$)"),
]
COMPILED = [(n, re.compile(r, re.I)) for n, r in RULES]
PREFILTER = re.compile(r"substitut|instead of|in place of", re.I)

# ⚠️ `egg substitute` IS A PRODUCT NAME, NOT A CLAIM. Any rule keying on `substitut` reads
#    "egg substitute and vanilla" as a substitution statement unless this is cut first.
NOUN_USE = re.compile(r"\b(?:egg|sugar|salt|meat|milk|butter)\s+substitutes?\b", re.I)

# equipment and serving, which `instead of` and `in place of` reach and which are not food swaps
NOT_FOOD_SWAP = re.compile(
    r"\b(bowl|pan|dish|sheet|spoon|straw|skillet|pot|plate|platter|mold|mould|tin|rack|"
    r"foil|wrap|paper|towel|oven|microwave|blender|mixer|processor|grill|"
    r"serve|serving|garnish|throwing|wish|like|desired)\b", re.I)


_SPAN_CACHE = {}


def longest_catalog_match(text, cat, decided, max_words=5):
    """⚠️ LONGEST MATCH, NOT THE NEXT SPACE. The diagnostic found 9% of captures truncated:
    `peanut` where the text said peanut butter, `whipped` for whipped cream, `pineapple` for
    pineapple juice. Those are WRONG facts rather than missing ones, which is the expensive kind.
    Try the longest leading span first and fall back, the same idea strip_forms already uses."""
    # ⚠️ MEMOIZED, AND THE REASON IS MEASURED. Each captured span costs up to ten matcher calls,
    #    which put the first full-corpus projection at 240 minutes. Spans repeat heavily across
    #    2.2 million recipes: `water`, `milk`, `flour`, `butter`. cat and decided are fixed for
    #    the life of a run, so the span text alone is a sound key.
    key = (text or "").lower().strip()
    if key in _SPAN_CACHE:
        return _SPAN_CACHE[key]
    words = re.sub(r"[^\w\s'-]", " ", text or "").split()
    for k in range(min(max_words, len(words)), 0, -1):
        core, _, _ = parse(" ".join(words[:k]))
        if not core:
            continue
        tier, _, rows, _ = LM.match(core, cat, decided)
        if tier in MP.MATCHED and len(rows) == 1:
            _SPAN_CACHE[key] = (rows[0][0], k)
            return _SPAN_CACHE[key]
    # and from the TAIL, since "chopped fresh spinach" names spinach at the end
    for k in range(min(max_words, len(words)), 0, -1):
        core, _, _ = parse(" ".join(words[-k:]))
        if not core:
            continue
        tier, _, rows, _ = LM.match(core, cat, decided)
        if tier in MP.MATCHED and len(rows) == 1:
            _SPAN_CACHE[key] = (rows[0][0], k)
            return _SPAN_CACHE[key]
    _SPAN_CACHE[key] = (None, 0)
    return _SPAN_CACHE[key]


def run(csv_path, limit):
    conn = sqlite3.connect(f"file:{BASE/'recipes.db'}?mode=ro", uri=True)
    cat = LM.load_catalog(conn)
    decided, _ = LM.load_decisions(cat)
    canon = {r[0]: r[1] for r in conn.execute("SELECT library_id, canonical FROM library_names")}
    is_cat_name = BG.catalog_name_check(conn)
    conn.close()

    pairs = collections.Counter()          # (from_id, to_id, pattern) -> n
    unrep = collections.Counter()          # (from_id, pattern) -> n, one-to-many, cannot store
    drop = collections.Counter()
    n_recipes = fired = 0
    t0 = time.time()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            n_recipes += 1
            if n_recipes > limit:
                break
            raw = row.get("directions") or ""
            if not PREFILTER.search(raw):
                continue
            try:
                names = ast.literal_eval(row.get("NER") or "[]")
            except (ValueError, SyntaxError):
                names = []
            if NF.classify(row.get("title") or "", names)[0] == "nonfood":
                drop["cosmetic recipe"] += 1
                continue
            try:
                text = " ".join(ast.literal_eval(raw))
            except (ValueError, SyntaxError):
                text = raw
            text = NOUN_USE.sub(" ", text)
            for label, rx in COMPILED:
                for m in rx.finditer(text):
                    fired += 1
                    fs, ts = m.group("frm"), m.group("to")
                    if NOT_FOOD_SWAP.search(fs) or NOT_FOOD_SWAP.search(ts):
                        drop["equipment or serving"] += 1
                        continue
                    a, _ = longest_catalog_match(fs, cat, decided)
                    b, _ = longest_catalog_match(ts, cat, decided)
                    if a and not b and re.search(r"\b(?:and|plus|\+)\b", ts, re.I):
                        # one ingredient replaced by two, which (from_id,to_id) cannot express
                        unrep[(a, label)] += 1
                        continue
                    if not a:
                        drop["from side unresolved"] += 1; continue
                    if not b:
                        drop["to side unresolved"] += 1; continue
                    if a == b:
                        drop["both sides the same row"] += 1; continue
                    # ⚠️ boundary (g), on BOTH sides. Cool Whip, Jell-O and Crisco all appear in
                    #    substitution text, so a mark can arrive as either half of the tuple.
                    if BG.is_brand(canon[a], is_catalog_name=is_cat_name) or \
                       BG.is_brand(canon[b], is_catalog_name=is_cat_name):
                        drop["a side is a brand"] += 1; continue
                    pairs[(a, b, label)] += 1
                    # fs, ts, m and text go out of scope here. Nothing retains the clause.
    return pairs, unrep, drop, fired, n_recipes, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("-n", type=int, default=10**9)
    ap.add_argument("--out", default="previews/substitution-candidates.json")
    a = ap.parse_args()
    pairs, unrep, drop, fired, N, el = run(a.corpus, a.n)
    merged = collections.Counter()
    patt = {}
    for (f, t, lab), v in pairs.items():
        merged[(f, t)] += v
        patt.setdefault((f, t), set()).add(lab)
    out = {
        "source_slug": SOURCE_SLUG, "recipes_read": N, "seconds": round(el, 1),
        "matches_fired": fired, "clean_tuples": len(merged),
        "dropped": dict(drop),
        "candidates": [{"from_id": f, "to_id": t, "n": v,
                        "patterns": sorted(patt[(f, t)])}
                       for (f, t), v in merged.most_common()],
        "unrepresentable": [{"from_id": f, "pattern": lab, "n": v}
                            for (f, lab), v in unrep.most_common()],
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"\n  {N:,} recipes, {el:.0f}s   matches fired {fired:,}")
    print(f"  clean candidate pairs {len(merged):,}   unrepresentable {len(unrep):,}")
    print(f"  dropped: {dict(drop)}")
    print(f"  wrote {a.out}")


if __name__ == "__main__":
    main()
