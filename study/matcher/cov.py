# -*- coding: utf-8 -*-
"""SCRATCH. Link coverage at HEAD bc38181, matcher = seg0-core.
   seg0-core = segment-first ranking, NO language rule, NO clause strip."""
import sys, os, re, pickle, collections, sqlite3
SP = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SP)
WT = "/private/tmp/claude-501/-Users-andrewhannah-Documents-Local-Documents-Food-recipe-app/838360e4-1af7-4569-904a-48460982006c/scratchpad/head-wt"
sys.path.insert(0, WT); os.chdir(WT)
import build_library as BL, weights, lib
from build_join import norm_name as n
from STOP2 import STOP
assert not hasattr(BL, "pasta_rule"), "this is not HEAD"

rows, _ = lib.rowset(BL)
kept = [r for r in rows if not r["cut_by"]]
idx = collections.defaultdict(list)
for r in kept:
    for t in r["variations"]: idx[n(t)].append((str(r["id"]), r["canonical"]))
idx = {k: sorted(set(v)) for k, v in idx.items()}
print(f"library at HEAD: {len(rows):,} rows, {len(kept):,} KEPT, {len(idx):,} index keys")

SEG = re.compile(r"[,;()/–—]|\bor\b|\band/or\b", re.I)
LEADNUM = re.compile(r"^(?:[\d¼-¾⅐-⅞./\s]+)"); MARK = "*†‡#•~+°±%&!?;:.,\"'“”​⁄/"
NUMTOK = re.compile(r"^[\d¼-¾⅐-⅞./%°]+$")
def toks(s): return [w for w in (t.strip(MARK) for t in n(LEADNUM.sub("", (s or "").strip())).split()) if w]
def isc(w): return w not in STOP and not NUMTOK.match(w) and any(c.isalnum() for c in w)
def allstop(g): return all(w in STOP for w in g.split())
def cands(text):
    out = []; off = 0
    for si, seg in enumerate(SEG.split(text or "")):
        w = toks(seg)
        for L in range(len(w), 0, -1):
            for i in range(0, len(w) - L + 1): out.append((L, off + i, si, i, w))
        off += len(w)
    return out
SEG0 = lambda c: (c[2], -c[0], c[3])            # ⚠ the banked predicate
def pick(text):
    for L, ab, si, i, w in sorted(cands(text), key=SEG0):
        g = " ".join(w[i:i+L])
        for key in (g, BL.depluralize(g)):
            if not key or key not in idx: continue
            if L == 1 and allstop(g): break
            left = [t for j, t in enumerate(w) if not (i <= j < i+L) and isc(t)]
            return dict(hit=idx[key], ngram=g, key=key, L=L, seg=si,
                        cov=L / (L + len(left)))
    return None
# the OLD ladder, kept only to reproduce the AGREE / DIFFERENT split
LEAD = re.compile(r"^(?:\d+[\d\s/.¼½¾⅓⅔⅛-]*\s*)?(?:of\s+|the\s+|a\s+|an\s+)?"
    r"(?:(?:whole|peeled|canned|tinned|frozen|fresh|freshly|ripe|large|small|medium|good|"
    r"quality|best|spooned|leveled|packed|firmly|finely|roughly|thinly|coarsely|cooked|raw|"
    r"dried|extra|plain|toasted|warm|lukewarm|hot|cold|room|natural|pure|unsweetened|"
    r"ground|squeezed|light|dark|fine|coarse|granulated|caster|superfine|boneless|skinless|"
    r"unsalted|salted|low|reduced|full|semi|non)\s+)+", re.I)
CONT = re.compile(r"^(?:\d+\s*)?(?:cans?|jars?|tins?|packets?|boxes?|bags?|bunch(?:es)?|"
    r"heads?|cloves?|sticks?|sprigs?|stalks?|slices?|pieces?|strips?)\s+(?:of\s+)?", re.I)
UNITWORD = re.compile(r"^(cloves?|sticks?|sprigs?|stalks?|heads?|bunch(?:es)?|slices?)\s+", re.I)
def ladder(l):
    b = weights.base_name(l)
    for how, k in [("as-stored", n(l)), ("normalize", n(weights.normalize(l))), ("base_name", n(b)),
        ("strip-leading", n(LEAD.sub("", b).strip())),
        ("strip-container", n(CONT.sub("", LEAD.sub("", b)).strip())),
        ("strip-unit", n(UNITWORD.sub("", CONT.sub("", LEAD.sub("", b)).strip())))]:
        if not k: continue
        for key in (k, BL.depluralize(k)):
            if key and key in idx: return how, key, idx[key]
    return "MISS", None, None

db = sqlite3.connect("file:recipes.db?mode=ro", uri=True)
def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]
recs = []
for rid, rn, pos, lab, raw, ing in db.execute(
    "SELECT r.id, r.name, ri.position, ri.label, ri.raw_text, ri.ingredient_id "
    "FROM recipe_ingredients ri JOIN recipes r ON r.id=ri.recipe_id "
    "WHERE ri.is_heading=0 ORDER BY r.id, ri.position"):
    t = (lab or "").strip() or (raw or "").strip()
    rung, ok, oh = ladder(t)
    recs.append(dict(slug=slug(rn), pos=pos, raw=(raw or "").strip(),
                     parsed=(lab or "").strip(), text=t, stored=ing,
                     rung=rung, ohit=oh, m=pick(t)))
def K(h): return tuple(sorted(i for i, _ in h)) if h else None
for r in recs:
    o, w = K(r["ohit"]), K(r["m"]["hit"] if r["m"] else None)
    r["agree"] = ("AGREE" if o == w else "DIFFERENT") if (o and w) else \
                 ("OLD-ONLY" if o else ("NEW-ONLY" if w else "BOTH-MISS"))
pickle.dump(recs, open(SP + "/COV.pkl", "wb"))
def cls(h): return "MISS" if not h else ("MATCHED" if len(h) == 1 else "AMBIG")
c = collections.Counter(cls(r["m"]["hit"] if r["m"] else None) for r in recs)
N = len(recs)
print(f"\ncorpus lines {N:,}")
for k in ("MATCHED", "AMBIG", "MISS"):
    print(f"   {k:8} {c[k]:5}   {100*c[k]/N:5.1f}%")
print("\nagreement with the OLD ladder (this is what the hand reading covered):")
for k, v in collections.Counter(r["agree"] for r in recs).most_common():
    print(f"   {k:10} {v:5}   {100*v/N:5.1f}%")
