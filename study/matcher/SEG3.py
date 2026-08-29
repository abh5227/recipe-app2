# -*- coding: utf-8 -*-
"""Correct four-variant split, then extract the MOVED rows for reading."""
import sys,os,re,collections,sqlite3,pickle
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
ROOT="/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0,ROOT); os.chdir(ROOT)
import lib, build_library as BL, weights
from build_join import norm_name as n
from STOP2 import STOP
from VERD import D as VD
from VERDN import WRONG as NW
rows,_=lib.rowset(BL); kept=[r for r in rows if not r["cut_by"]]
idx=collections.defaultdict(list); langs=collections.defaultdict(set)
for r in kept:
    for name,meta in r["variations"].items():
        k=n(name); idx[k].append((str(r["id"]),r["canonical"]))
        for s,kd,lg in meta: langs[k].add(lg or "")
for k in idx: idx[k]=sorted(set(idx[k]))
SEG=re.compile(r"[,;()/–—]|\bor\b|\band/or\b",re.I)
LEADNUM=re.compile(r"^(?:[\d¼-¾⅐-⅞./\s]+)"); MARK="*†‡#•~+°±%&!?;:.,\"'“”​⁄/"
NUMTOK=re.compile(r"^[\d¼-¾⅐-⅞./%°]+$")
def toks(s): return [w for w in (t.strip(MARK) for t in n(LEADNUM.sub("",(s or "").strip())).split()) if w]
def is_content(w): return w not in STOP and not NUMTOK.match(w) and any(c.isalnum() for c in w)
def all_stop(g): return all(w in STOP for w in g.split())
def english(key):
    L=langs[key]; return ("en" in L) or ("" in L) or (not L)
RANK={"rightmost": lambda L,ab,si,i:(-L,-ab), "seg0": lambda L,ab,si,i:(si,-L,i)}
def cands(text):
    out=[];off=0
    for si,seg in enumerate(SEG.split(text or "")):
        w=toks(seg)
        for L in range(len(w),0,-1):
            for i in range(0,len(w)-L+1): out.append((L,off+i,si,i,w))
        off+=len(w)
    return out
def pick(text,mode="rightmost",lang=0):
    """lang: 0 = off, 1 = length-1 matches only, 2 = every length"""
    for L,ab,si,i,w in sorted(cands(text),key=lambda c:RANK[mode](c[0],c[1],c[2],c[3])):
        g=" ".join(w[i:i+L])
        for key in (g,BL.depluralize(g)):
            if not key or key not in idx: continue
            if L==1 and all_stop(g): break
            if lang and (lang==2 or L==1) and not english(key): break
            left=[t for j,t in enumerate(w) if not (i<=j<i+L) and is_content(t)]
            return dict(hit=idx[key],ngram=g,key=key,L=L,seg=si,cov=L/(L+len(left)))
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
def slug(s): return re.sub(r"[^a-z0-9]+","-",(s or "").lower()).strip("-")[:60]
recs=[]
for rid,rn,pos,lab,raw in db.execute("SELECT r.id,r.name,ri.position,ri.label,ri.raw_text "
   "FROM recipe_ingredients ri JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 "
   "ORDER BY r.id,ri.position"):
    t=(lab or "").strip() or (raw or "").strip()
    rung,ok,oh=ladder(t)
    recs.append(dict(slug=slug(rn),pos=pos,raw=(raw or "").strip(),parsed=(lab or "").strip(),
        text=t,rung=rung,ohit=oh,rm=pick(t,"rightmost",0),s0=pick(t,"seg0",0),
        s0l2=pick(t,"seg0",2),s0l1=pick(t,"seg0",1)))
def K(h): return tuple(sorted(i for i,_ in h)) if h else None
def nm(h): return " | ".join(c for _,c in h) if h else ""
for r in recs:
    o,w=K(r["ohit"]),K(r["rm"]["hit"] if r["rm"] else None)
    r["agree"]=("AGREE" if o==w else "DIFFERENT") if (o and w) else ("OLD-ONLY" if o else ("NEW-ONLY" if w else "BOTH-MISS"))
    if r["agree"]=="NEW-ONLY":
        r["verdict"]="BOTH-WRONG" if (r["rm"]["ngram"],nm(r["rm"]["hit"])) in NW else "NEW-RIGHT"
    elif r["agree"] in ("DIFFERENT","OLD-ONLY"):
        k=(nm(r["ohit"]),nm(r["rm"]["hit"]) if r["rm"] else "-",r["rm"]["ngram"] if r["rm"] else "-")
        r["verdict"]=VD.get(k,("UNJUDGED",))[0]
    else: r["verdict"]=""
pickle.dump(recs,open(SP+"/SEG3.pkl","wb"))
OLDRIGHT=[r for r in recs if r["verdict"]=="OLD-RIGHT"]
NEWRIGHT=[r for r in recs if r["agree"]=="NEW-ONLY" and r["verdict"]=="NEW-RIGHT"]
NEWWRONG=[r for r in recs if r["agree"]=="NEW-ONLY" and r["verdict"]=="BOTH-WRONG"]
def cls(h): return "MISS" if not h else ("MATCHED" if len(h)==1 else "AMBIG")
VAR=[("(a) rightmost  [today]","rm"),("(b) seg0","s0"),
     ("(c) seg0 + language, EVERY length","s0l2"),("(d) seg0 + language, 1-WORD only","s0l1")]
print("known sets at this HEAD: OLD-RIGHT %d   NEW-RIGHT %d   NEW-ONLY wrong %d"%(len(OLDRIGHT),len(NEWRIGHT),len(NEWWRONG)))
h="%-36s %7s %6s %5s | %11s %10s %10s %10s"%("variant","matched","ambig","miss",
  "REGRESSION","recov KEPT","recov MOVED","still WRONG")
print("\n"+h); print("-"*len(h))
TAB=[]
for lab,v in VAR:
    c=collections.Counter(cls(r[v]["hit"] if r[v] else None) for r in recs)
    fixed=sum(1 for r in OLDRIGHT if not r[v] or K(r[v]["hit"])==K(r["ohit"]))
    regr=len(OLDRIGHT)-fixed
    keptn=sum(1 for r in NEWRIGHT if r[v] and K(r[v]["hit"])==K(r["rm"]["hit"]))
    movd=len(NEWRIGHT)-keptn
    wrong=sum(1 for r in NEWWRONG if r[v] and K(r[v]["hit"])==K(r["rm"]["hit"]))
    print("%-36s %7d %6d %5d | %11d %10d %10d %10d"%(lab,c["MATCHED"],c["AMBIG"],c["MISS"],regr,keptn,movd,wrong))
    TAB.append(dict(variant=lab.strip(),matched=c["MATCHED"],ambiguous=c["AMBIG"],miss=c["MISS"],
      regressions_still_open="%d of %d"%(regr,len(OLDRIGHT)),
      known_regressions_fixed=fixed,
      recoveries_kept="%d of %d"%(keptn,len(NEWRIGHT)),recoveries_moved=movd,
      new_only_still_wrong="%d of %d"%(wrong,len(NEWWRONG))))
pickle.dump(TAB,open(SP+"/TAB.pkl","wb"))
# the MOVED rows: a NEW-RIGHT recovery that seg0+lang(1-word) lands on a DIFFERENT row
MOVED=[r for r in NEWRIGHT if not (r["s0l1"] and K(r["s0l1"]["hit"])==K(r["rm"]["hit"]))]
print("\nMOVED rows to read (variant d): %d"%len(MOVED))
pat=collections.Counter((r["rm"]["ngram"],nm(r["rm"]["hit"]),
     r["s0l1"]["ngram"] if r["s0l1"] else "-", nm(r["s0l1"]["hit"]) if r["s0l1"] else "-") for r in MOVED)
print("distinct (old phrase, old row, new phrase, new row) patterns: %d"%len(pat))
pickle.dump(MOVED,open(SP+"/MOVED.pkl","wb"))
for (a,b,c2,d),k in pat.most_common(60):
    print("  x%-3d '%s' -> %-26s   ==>  '%s' -> %s"%(k,a,b[:26],c2,d))
