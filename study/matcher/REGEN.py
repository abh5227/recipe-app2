# -*- coding: utf-8 -*-
"""SCRATCH. Regenerate previews/full-ingredient-match.csv at HEAD bc38181 with the
   BANKED matcher (seg0-core), then HTM.py re-renders the HTML from it.
   Reads join.db / sources.db / recipes.db READ-ONLY. Writes only into previews/."""
import sys, os, re, csv, io, pickle, collections, sqlite3
SP = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SP)
WT = "/private/tmp/claude-501/-Users-andrewhannah-Documents-Local-Documents-Food-recipe-app/838360e4-1af7-4569-904a-48460982006c/scratchpad/head-wt"
REPO = "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0, WT); os.chdir(WT)
import build_library as BL, weights, lib
from build_join import norm_name as n
from STOP2 import STOP, FORM
from VERD import D as VD
from VERDN import WRONG as NW
assert not hasattr(BL, "pasta_rule"), "not HEAD"

rows, _ = lib.rowset(BL)
kept = [r for r in rows if not r["cut_by"]]
idx = collections.defaultdict(list)
for r in kept:
    for t in r["variations"]: idx[n(t)].append((str(r["id"]), r["canonical"]))
idx = {k: sorted(set(v)) for k, v in idx.items()}
CANON = {n(r["canonical"]) for r in kept}
LIB = (len(rows), len(kept), len(idx))

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
    saw = False
    for L, ab, si, i, w in sorted(cands(text), key=SEG0):
        g = " ".join(w[i:i+L])
        for key in (g, BL.depluralize(g)):
            if not key or key not in idx: continue
            if L == 1 and allstop(g): saw = True; break
            left = [t for j, t in enumerate(w) if not (i <= j < i+L) and isc(t)]
            return dict(hit=idx[key], ngram=g, key=key, L=L, left=left,
                        cov=L/(L+len(left))), saw
    return None, saw
def band(m):
    if not m: return "NONE"
    if m["cov"] < 0.34: return "LOW"
    if m["L"] == 1 and (m["ngram"] in FORM or BL.depluralize(m["ngram"]) in FORM): return "LOW"
    if m["L"] >= 2: return "HIGH"
    if m["cov"] >= 1.0 and (m["ngram"] in CANON or BL.depluralize(m["ngram"]) in CANON): return "HIGH"
    return "MEDIUM"
def reason(m):
    if not m: return ""
    g, L, left = m["ngram"], m["L"], m["left"]
    lead = (f"longest phrase '{g}' ({L} words) is an index key" if L >= 2
            else f"'{g}' is an index key")
    if L == 1 and (g in FORM or BL.depluralize(g) in FORM):
        lead = (f"the longest phrase that is an index key is '{g}', which names a shape "
                "or a preparation rather than a food")
    if not left: return lead + ", and it is the whole content of its clause"
    return (lead + f", but {len(left)} other content word(s) in the clause are "
            f"unaccounted for: " + " ".join(left))

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

# the hand-written miss annotations from the previous render, carried forward by line
OLDCSV = os.path.join(REPO, "previews/full-ingredient-match.csv")
prev = {}
if os.path.exists(OLDCSV):
    raw = io.open(OLDCSV, encoding="utf-8-sig").read().splitlines()
    for r in csv.DictReader([l for l in raw if not l.startswith("#")]):
        if r["new_confidence"] == "NONE" and r["new_reason"]:
            prev[(r["recipe_slug"], r["position"])] = r["new_reason"]
print(f"carried forward {len(prev)} hand-written miss annotations")

db = sqlite3.connect("file:recipes.db?mode=ro", uri=True); db.execute("PRAGMA query_only=ON")
def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]
recs = []
for rid, rn, pos, lab, raw_t in db.execute(
    "SELECT r.id,r.name,ri.position,ri.label,ri.raw_text FROM recipe_ingredients ri "
    "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 ORDER BY r.id,ri.position"):
    text = (lab or "").strip() or (raw_t or "").strip()
    rung, okey, ohit = ladder(text)
    m, saw = pick(text)
    recs.append(dict(slug=slug(rn), pos=pos, raw=(raw_t or "").strip(),
        parsed=(lab or "").strip(), text=text, rung=rung, ohit=ohit, m=m, saw=saw,
        conf=band(m), why=reason(m)))
def K(h): return tuple(sorted(i for i, _ in h)) if h else None
def nm(h): return " | ".join(c for _, c in h) if h else ""
def ids(h): return " | ".join(i for i, _ in h) if h else ""
for r in recs:
    o, w = K(r["ohit"]), K(r["m"]["hit"] if r["m"] else None)
    r["agree"] = ("AGREE" if o == w else "DIFFERENT") if (o and w) else \
                 ("OLD-ONLY" if o else ("NEW-ONLY" if w else "BOTH-MISS"))
    if not r["m"]:
        r["why"] = prev.get((r["slug"], str(r["pos"])), "") or (
            "DECLINED-STOPWORD - the only index key on the line was a stopword"
            if r["saw"] else "NO index key anywhere on the line")
    if r["agree"] in ("DIFFERENT", "OLD-ONLY"):
        k = (nm(r["ohit"]), nm(r["m"]["hit"]) if r["m"] else "-",
             r["m"]["ngram"] if r["m"] else "-")
        v = VD.get(k)
        r["verdict"] = f"{v[0]} - {v[1]}" if v else "(unread)"
    elif r["agree"] == "NEW-ONLY":
        k = (r["m"]["ngram"], nm(r["m"]["hit"]))
        r["verdict"] = f"BOTH-WRONG - {NW[k]}" if k in NW else "(unread)"
    else:
        r["verdict"] = "(unread)" if r["agree"] == "AGREE" else ""
pickle.dump(recs, open(SP + "/REGEN.pkl", "wb"))
C = collections.Counter(r["conf"] for r in recs)
A = collections.Counter(r["agree"] for r in recs)
def cls(r): return "MISS" if not r["m"] else ("MATCHED" if len(r["m"]["hit"]) == 1 else "AMBIG")
K2 = collections.Counter(cls(r) for r in recs)
N = len(recs)
read = sum(1 for r in recs if r["verdict"] not in ("(unread)", ""))
print(f"lines {N}  {dict(K2)}  bands {dict(C)}  agreement {dict(A)}  hand-read {read}")
pickle.dump(dict(LIB=LIB, C=C, A=A, K2=K2, N=N, read=read), open(SP + "/REGEN_TALLY.pkl", "wb"))
