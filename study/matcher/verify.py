# -*- coding: utf-8 -*-
"""SCRATCH. The REAL rule, built from the edited build_library.py, against the preview."""
import sys, os, re, pickle, collections, sqlite3
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
ROOT="/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0,ROOT); os.chdir(ROOT)
import build_library as BL, lib, ingredient_cuts as CUTS
from build_join import norm_name as n
from STOP2 import STOP

rows,_ = lib.rowset(BL)
kept   = [r for r in rows if not r["cut_by"]]
base   = pickle.load(open(SP+'/ANCH1_rows.pkl','rb'))
basek  = [r for r in base if not r["cut_by"]]
print(f"KEPT   before {len(basek):,}   after {len(kept):,}   delta +{len(kept)-len(basek):,}")
print(f"ROWS   before {len(base):,}   after {len(rows):,}")
print(f"OVERRIDES {len(CUTS.OVERRIDES)}: {', '.join(CUTS.OVERRIDES)}")

PAS = "Wikidata names pasta as a direct superclass"
pr  = [r for r in rows if r.get("why")==PAS]
prk = [r for r in pr if not r["cut_by"]]
print(f"\nRULE 5 admitted {len(pr):,} entries, {len(prk):,} survive the cuts")
bag = [r for r in rows if r["id"]=="Q272502"]
print(f"bagel override -> {len(bag)} row(s): "
      + "; ".join(f"{r['canonical']!r} cut={bool(r['cut_by'])} why={r['why'][:34]}" for r in bag))

# hop-1 predicate cross-check against the raw vocab
import json
SUP=json.load(open('vocab/wikidata-superclasses.json'))['superclasses']
direct={q for q,ps in SUP.items() if "Q178" in ps}
print(f"\nitems with a DIRECT P279 to Q178 in the vocab: {len(direct):,}")
print(f"  of those, admitted by rule 5: {len({r['id'] for r in pr} & direct):,}  "
      f"(rest were already admitted by rules 1-4 or are not in join.db)")

def index(rs):
    ix=collections.defaultdict(list)
    for r in rs:
        if r["cut_by"]: continue
        for t in r["variations"]: ix[n(t)].append((str(r["id"]),r["canonical"]))
    return {k:sorted(set(v)) for k,v in ix.items()}
ib, ia = index(base), index(rows)
print(f"index keys  before {len(ib):,}  after {len(ia):,}  (+{len(ia)-len(ib):,})")

SEG=re.compile(r"[,;()/–—]|\bor\b|\band/or\b",re.I)
LEADNUM=re.compile(r"^(?:[\d¼-¾⅐-⅞./\s]+)"); MARK="*†‡#•~+°±%&!?;:.,\"'“”​⁄/"
NUMTOK=re.compile(r"^[\d¼-¾⅐-⅞./%°]+$")
def toks(s): return [w for w in (t.strip(MARK) for t in n(LEADNUM.sub("",(s or "").strip())).split()) if w]
def isc(w): return w not in STOP and not NUMTOK.match(w) and any(c.isalnum() for c in w)
def allstop(g): return all(w in STOP for w in g.split())
def hn(w):
    c=[x for x in w if isc(x)]; return c[-1] if c else None
def cands(text):
    out=[];off=0
    for si,seg in enumerate(SEG.split(text or "")):
        w=toks(seg); h=hn(w)
        for L in range(len(w),0,-1):
            for i in range(0,len(w)-L+1): out.append((L,off+i,si,i,w,h))
        off+=len(w)
    return out
RANK=lambda c:(c[2],0 if (c[5] is not None and c[5] in c[4][c[3]:c[3]+c[0]]) else 1,-c[0],c[3])
def pick(text,idx):
    for L,ab,si,i,w,h in sorted(cands(text),key=RANK):
        g=" ".join(w[i:i+L])
        for k in (g,BL.depluralize(g)):
            if not k or k not in idx: continue
            if L==1 and allstop(g): break
            return idx[k]
    return None
db=sqlite3.connect("file:recipes.db?mode=ro",uri=True)
LINES=[((l or "").strip() or (r or "").strip()) for l,r in db.execute(
   "SELECT ri.label, ri.raw_text FROM recipe_ingredients ri WHERE ri.is_heading=0")]
B=[pick(t,ib) for t in LINES]; A=[pick(t,ia) for t in LINES]
def cls(h): return "MISS" if not h else ("MATCHED" if len(h)==1 else "AMBIG")
cb=collections.Counter(cls(x) for x in B); ca=collections.Counter(cls(x) for x in A)
print(f"\ncorpus {len(LINES):,} lines")
print(f"  before  MATCHED {cb['MATCHED']}  AMBIG {cb['AMBIG']}  MISS {cb['MISS']}")
print(f"  after   MATCHED {ca['MATCHED']}  AMBIG {ca['AMBIG']}  MISS {ca['MISS']}")
fix=[(t,a) for t,b,a in zip(LINES,B,A) if not b and a]
amb=[(t,b,a) for t,b,a in zip(LINES,B,A) if b and len(b)==1 and a and len(a)>1]
mov=[(t,b,a) for t,b,a in zip(LINES,B,A) if b and a and len(b)==1==len(a) and b[0][0]!=a[0][0]]
reg=[(t,b,a) for t,b,a in zip(LINES,B,A) if b and len(b)==1 and not a]
print(f"\nFIXED {len(fix)}")
for t,a in fix: print(f"   {t[:46]:46} -> {' | '.join(c for _,c in a)}")
print(f"\nNEW AMBIGUITY {len(amb)}")
for t,b,a in amb: print(f"   {t[:46]:46} {b[0][1]:12} -> {' | '.join(c for _,c in a)}")
print(f"\nMOVED ROW (still one match) {len(mov)}")
for t,b,a in mov: print(f"   {t[:46]:46} {b[0][1]:12} -> {a[0][1]}")
print(f"\n⚠ REGRESSED to MISS {len(reg)}")
for t,b,a in reg: print(f"   {t[:46]:46} was {b[0][1]}")
basecanon=collections.defaultdict(list)
for r in basek: basecanon[n(r["canonical"])].append(r["canonical"])
dup=sorted({r["canonical"] for r in prk+[x for x in bag if not x["cut_by"]]
            if n(r["canonical"]) in basecanon})
print(f"\nDUPLICATE CANONICALS created: {len(dup)}")
for c in dup: print(f"   {c:20} already held by {basecanon[n(c)][0]!r}")
