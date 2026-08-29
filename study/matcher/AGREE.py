# -*- coding: utf-8 -*-
"""SCRATCH. The AGREE block at HEAD 460cae5, and a uniform random 60 out of it."""
import sys, os, re, random, pickle, collections, sqlite3
SP = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SP)
ROOT = "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0, ROOT); os.chdir(ROOT)
import build_library as BL, weights, lib
from build_join import norm_name as n
from STOP2 import STOP, FORM
assert hasattr(BL, "pasta_rule"), "expected the committed anchor rule"

rows, _ = lib.rowset(BL)
kept = [r for r in rows if not r["cut_by"]]
idx = collections.defaultdict(list)
for r in kept:
    for t in r["variations"]: idx[n(t)].append((str(r["id"]), r["canonical"]))
idx = {k: sorted(set(v)) for k, v in idx.items()}
CANON = {n(r["canonical"]) for r in kept}
print(f"library at HEAD 460cae5: {len(rows):,} rows, {len(kept):,} KEPT, {len(idx):,} index keys")

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
            for i in range(0, len(w)-L+1): out.append((L, off+i, si, i, w))
        off += len(w)
    return out
SEG0 = lambda c: (c[2], -c[0], c[3])
def pick(text):
    for L, ab, si, i, w in sorted(cands(text), key=SEG0):
        g = " ".join(w[i:i+L])
        for key in (g, BL.depluralize(g)):
            if not key or key not in idx: continue
            if L == 1 and allstop(g): break
            left = [t for j, t in enumerate(w) if not (i <= j < i+L) and isc(t)]
            return dict(hit=idx[key], ngram=g, key=key, L=L, left=left, cov=L/(L+len(left)))
    return None
def band(m):
    if not m: return "NONE"
    if m["cov"] < 0.34: return "LOW"
    if m["L"] == 1 and (m["ngram"] in FORM or BL.depluralize(m["ngram"]) in FORM): return "LOW"
    if m["L"] >= 2: return "HIGH"
    if m["cov"] >= 1.0 and (m["ngram"] in CANON or BL.depluralize(m["ngram"]) in CANON): return "HIGH"
    return "MEDIUM"
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

db = sqlite3.connect("file:recipes.db?mode=ro", uri=True); db.execute("PRAGMA query_only=ON")
def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]
recs = []
for rid, rn, pos, lab, raw in db.execute(
    "SELECT r.id,r.name,ri.position,ri.label,ri.raw_text FROM recipe_ingredients ri "
    "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 ORDER BY r.id,ri.position"):
    text = (lab or "").strip() or (raw or "").strip()
    rung, okey, ohit = ladder(text)
    m = pick(text)
    recs.append(dict(slug=slug(rn), recipe=rn, pos=pos, raw=(raw or "").strip(),
        parsed=(lab or "").strip(), text=text, rung=rung, okey=okey, ohit=ohit,
        m=m, conf=band(m)))
def K(h): return tuple(sorted(i for i, _ in h)) if h else None
for r in recs:
    o, w = K(r["ohit"]), K(r["m"]["hit"] if r["m"] else None)
    r["agree"] = ("AGREE" if o == w else "DIFFERENT") if (o and w) else \
                 ("OLD-ONLY" if o else ("NEW-ONLY" if w else "BOTH-MISS"))
N = len(recs)
A = [r for r in recs if r["agree"] == "AGREE"]
c = collections.Counter(r["agree"] for r in recs)
print(f"corpus {N:,} lines. agreement: " + "  ".join(f"{k}={v}" for k, v in c.most_common()))
print(f"AGREE block = {len(A):,} lines, {100*len(A)/N:.1f}% of the corpus")
ab = collections.Counter(r["conf"] for r in A)
print("AGREE by confidence band: " + "  ".join(f"{k}={ab[k]}" for k in ("HIGH","MEDIUM","LOW")))
single = sum(1 for r in A if len(r["m"]["hit"]) == 1)
print(f"AGREE single-row {single:,}   AGREE ambiguous {len(A)-single:,}")

SEED = 20260827
rnd = random.Random(SEED)
sample = rnd.sample(sorted(range(len(A)), key=lambda i: (A[i]["slug"], A[i]["pos"])), 60)
S60 = [A[i] for i in sorted(sample)]
sb = collections.Counter(r["conf"] for r in S60)
print(f"\nSAMPLE seed={SEED}, uniform over all {len(A):,} AGREE lines, n=60")
print("  band spread: " + "  ".join(f"{k}={sb[k]}" for k in ("HIGH","MEDIUM","LOW")))
print(f"  expected at the block's rate: " +
      "  ".join(f"{k}={60*ab[k]/len(A):.1f}" for k in ("HIGH","MEDIUM","LOW")))
print(f"  distinct recipes in the 60: {len({r['slug'] for r in S60})}")
print(f"  single-row {sum(1 for r in S60 if len(r['m']['hit'])==1)}   "
      f"ambiguous {sum(1 for r in S60 if len(r['m']['hit'])>1)}")
pickle.dump(dict(recs=recs, A=A, S60=S60, seed=SEED, lib=(len(rows),len(kept),len(idx))),
            open(SP + "/AGREE.pkl", "wb"))
