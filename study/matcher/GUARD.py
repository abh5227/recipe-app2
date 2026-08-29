# -*- coding: utf-8 -*-
"""THE INDEX-KEY GUARD, and the full three-config measurement. Reads only."""
import sys,os,re,collections,sqlite3,pickle
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
ROOT="/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0,ROOT); os.chdir(ROOT)
import lib, build_library as BL, weights
from build_join import norm_name as n
from STOP2 import STOP
from STRIP import TAIL
from VERD import D as VD
from VERDN import WRONG as NW

rows,_=lib.rowset(BL); kept=[r for r in rows if not r["cut_by"]]
idx=collections.defaultdict(list)
for r in kept:
    for t in r["variations"]: idx[n(t)].append((str(r["id"]),r["canonical"]))
for k in idx: idx[k]=sorted(set(idx[k]))
print("library fresh: %d rows, %d KEPT, %d index keys"%(len(rows),len(kept),len(idx)))

LEADNUM=re.compile(r"^(?:[\d¼-¾⅐-⅞./\s]+)"); MARK="*†‡#•~+°±%&!?;:.,\"'“”​⁄/"
NUMTOK=re.compile(r"^[\d¼-¾⅐-⅞./%°]+$")
def toks(s): return [w for w in (t.strip(MARK) for t in n(LEADNUM.sub("",(s or "").strip())).split()) if w]
def is_content(w): return w not in STOP and not NUMTOK.match(w) and any(c.isalnum() for c in w)

# ── 1. THE GUARD ─────────────────────────────────────────────────────────────
def guard_blocks(cut_text):
    """Return the index key that vetoes this strip, or None.

    Tokenize the text about to be REMOVED, keep only content words, and test each one
    (and its depluralized form) against the 183,651-key library index. One hit vetoes
    the whole strip: if the 'clause' contains a real ingredient name, it is not a clause.

    'to taste'                -> content ['taste']  -> 'taste' not a key   -> strip proceeds
    'plus more for dusting'   -> content ['dusting'] -> not a key          -> strip proceeds
    ', to taste) torn curly kale leaves'
                              -> content ['taste','torn','curly','kale','leaves']
                              -> 'kale' IS a key                          -> REFUSED
    """
    for w in toks(cut_text):
        if not is_content(w): continue
        for k in (w, BL.depluralize(w)):
            if k and k in idx: return k
    return None

def strip_tail(text, guard=False):
    m=TAIL.search(text or "")
    if not m: return text,"",None
    if m.start("cut")<3: return text,"",None
    cut=text[m.start("cut"):].strip()
    if guard:
        v=guard_blocks(cut)
        if v: return text,"",v                       # refused, line kept whole
    return text[:m.start("cut")].rstrip(" ,;("), cut, None

# ── the matcher: seg0 + head-noun, the config where the strip helped ─────────
SEG=re.compile(r"[,;()/–—]|\bor\b|\band/or\b",re.I)
def all_stop(g): return all(w in STOP for w in g.split())
def head_noun(w):
    c=[x for x in w if is_content(x)]; return c[-1] if c else None
def cands(text):
    out=[];off=0
    for si,seg in enumerate(SEG.split(text or "")):
        w=toks(seg); h=head_noun(w)
        for L in range(len(w),0,-1):
            for i in range(0,len(w)-L+1): out.append((L,off+i,si,i,w,h))
        off+=len(w)
    return out
RANKS={"rightmost":lambda c:(-c[0],-c[1]),
       "headnoun":lambda c:(c[2],0 if (c[5] is not None and c[5] in c[4][c[3]:c[3]+c[0]]) else 1,-c[0],c[3])}
def pick(text,mode="headnoun",strip=0):
    if strip: text=strip_tail(text,guard=(strip==2))[0]
    for L,ab,si,i,w,h in sorted(cands(text),key=RANKS[mode]):
        g=" ".join(w[i:i+L])
        for key in (g,BL.depluralize(g)):
            if not key or key not in idx: continue
            if L==1 and all_stop(g): break
            return dict(hit=idx[key],ngram=g,L=L)
    return None
LEAD=re.compile(r"^(?:\d+[\d\s/.¼½¾⅓⅔⅛-]*\s*)?(?:of\s+|the\s+|a\s+|an\s+)?"
    r"(?:(?:whole|peeled|canned|tinned|frozen|fresh|freshly|ripe|large|small|medium|good|"
    r"quality|best|spooned|leveled|packed|firmly|finely|roughly|thinly|coarsely|cooked|raw|"
    r"dried|extra|plain|toasted|warm|lukewarm|hot|cold|room|natural|pure|unsweetened|"
    r"ground|squeezed|light|dark|fine|coarse|granulated|caster|superfine|boneless|skinless|"
    r"unsalted|salted|low|reduced|full|semi|non)\s+)+", re.I)
CONT=re.compile(r"^(?:\d+\s*)?(?:cans?|jars?|tins?|packets?|boxes?|bags?|bunch(?:es)?|"
    r"heads?|cloves?|sticks?|sprigs?|stalks?|slices?|pieces?|strips?)\s+(?:of\s+)?", re.I)
UNITWORD=re.compile(r"^(cloves?|sticks?|sprigs?|stalks?|heads?|bunch(?:es)?|slices?)\s+", re.I)
def ladder(l):
    b=weights.base_name(l)
    for how,k in [("as-stored",n(l)),("normalize",n(weights.normalize(l))),("base_name",n(b)),
        ("strip-leading",n(LEAD.sub("",b).strip())),
        ("strip-container",n(CONT.sub("",LEAD.sub("",b)).strip())),
        ("strip-unit",n(UNITWORD.sub("",CONT.sub("",LEAD.sub("",b)).strip())))]:
        if not k: continue
        for key in (k,BL.depluralize(k)):
            if key and key in idx: return how,key,idx[key]
    return "MISS",None,None
db=sqlite3.connect("file:recipes.db?mode=ro",uri=True)
recs=[]
for rid,rn,pos,lab,raw in db.execute("SELECT r.id,r.name,ri.position,ri.label,ri.raw_text "
   "FROM recipe_ingredients ri JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 "
   "ORDER BY r.id,ri.position"):
    t=(lab or "").strip() or (raw or "").strip()
    rung,ok,oh=ladder(t)
    k0,c0,_=strip_tail(t,guard=False)
    k1,c1,veto=strip_tail(t,guard=True)
    recs.append(dict(slug=rn,pos=pos,raw=(raw or "").strip(),text=t,ohit=oh,
        cut_noguard=c0,cut_guard=c1,veto=veto,
        rm=pick(t,"rightmost",0),hn=pick(t,"headnoun",0),
        hns=pick(t,"headnoun",1),hng=pick(t,"headnoun",2)))
pickle.dump(recs,open(SP+"/GUARD.pkl","wb"))
mod0=[r for r in recs if r["cut_noguard"]]
mod1=[r for r in recs if r["cut_guard"]]
ref =[r for r in recs if r["veto"]]
print("\nstrips WITHOUT the guard : %d"%len(mod0))
print("strips WITH the guard    : %d"%len(mod1))
print("strips REFUSED by the guard: %d  (%.0f%% of all strips)"%(len(ref),100*len(ref)/len(mod0)))
