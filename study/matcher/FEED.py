"""READ-ONLY. Does feeding the importer's parsed NAME help? Scratch only, writes nothing."""
import sys,os,re,collections,sqlite3
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
sys.path.insert(0,"/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
os.chdir("/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
import lib, build_library as BL, weights, import_cleanup as C
from build_join import norm_name as n
rows,_=lib.rowset(BL); kept=[r for r in rows if not r["cut_by"]]
idx=collections.defaultdict(list)
for r in kept:
    for t in r["variations"]: idx[n(t)].append((r["anchor"],str(r["id"]),r["canonical"]))
for k in idx: idx[k]=sorted(set(idx[k]))
print("library: %d kept, index %d keys\n"%(len(kept),len(idx)))

LEAD=re.compile(r"^(?:\d+[\d\s/.¼½¾⅓⅔⅛-]*\s*)?(?:of\s+|the\s+|a\s+|an\s+)?"
    r"(?:(?:whole|peeled|canned|tinned|frozen|fresh|freshly|ripe|large|small|medium|good|"
    r"quality|best|spooned|leveled|packed|firmly|finely|roughly|thinly|coarsely|cooked|raw|"
    r"dried|extra|plain|toasted|warm|lukewarm|hot|cold|room|natural|pure|unsweetened|"
    r"ground|squeezed|light|dark|fine|coarse|granulated|caster|superfine|boneless|skinless|"
    r"unsalted|salted|low|reduced|full|semi|non)\s+)+", re.I)
CONT=re.compile(r"^(?:\d+\s*)?(?:cans?|jars?|tins?|packets?|boxes?|bags?|bunch(?:es)?|"
    r"heads?|cloves?|sticks?|sprigs?|stalks?|slices?|pieces?|strips?)\s+(?:of\s+)?", re.I)
UNITWORD=re.compile(r"^(cloves?|sticks?|sprigs?|stalks?|heads?|bunch(?:es)?|slices?)\s+", re.I)
PREPTAIL=re.compile(r"\b(?:minced|chopped|sliced|diced|crushed|peeled|grated|halved|quartered|"
    r"divided|crumbled|melted|softened|beaten|cubed|julienned|trimmed|drained|rinsed|shredded|"
    r"seeded|deboned|sifted|packed|room temperature|finely|roughly|thinly|cut into.*|for .*|"
    r"plus more.*|to serve.*|optional.*)\b.*$", re.I)

def base_cands(l):
    b=weights.base_name(l)
    yield n(l); yield n(weights.normalize(l)); yield n(b)
    yield n(LEAD.sub("",b).strip())
    yield n(CONT.sub("",LEAD.sub("",b)).strip())
    yield n(UNITWORD.sub("",CONT.sub("",LEAD.sub("",b)).strip()))
def comma_cands(l):
    """EVERY comma segment, not just the first. weights.normalize takes split(',')[0],
       which is right for 'olive oil, divided' and wrong for 'boneless, skinless chicken'."""
    for seg in [s.strip() for s in re.split(r"[,/]", l) if s.strip()]:
        for k in base_cands(seg): yield k
def prep_cands(l):
    """Drop a TRAILING prep clause rather than everything after the first comma."""
    for seg in [s.strip() for s in re.split(r"[,/]", l) if s.strip()]:
        c=PREPTAIL.sub("",seg).strip()
        if c and c!=seg:
            for k in base_cands(c): yield k
def hit(gen):
    for k in gen:
        if not k: continue
        for key in (k,BL.depluralize(k)):
            if key and key in idx: return idx[key]
    return None
def cls(h): return "MISS" if h is None else ("MATCHED" if len(h)==1 else "AMBIGUOUS")

db=sqlite3.connect("file:recipes.db?mode=ro",uri=True); db.execute("PRAGMA query_only=ON")
raw_rows=list(db.execute("SELECT r.id, ri.position, ri.label, ri.raw_text FROM recipe_ingredients ri "
  "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0"))
print("ingredient lines: %d   of which label IS NULL/blank: %d"
      %(len(raw_rows),sum(1 for _,_,l,_ in raw_rows if not (l or '').strip())))

def reparse(raw):
    try: return (C.classify_line(raw or "") or {}).get("name") or ""
    except Exception: return ""
agree=sum(1 for _,_,l,rw in raw_rows if (l or "").strip() and reparse(rw)==(l or "").strip())
have=sum(1 for _,_,l,_ in raw_rows if (l or "").strip())
print("re-parsing raw_text reproduces the stored label on %d of %d rows that have one\n"%(agree,have))

VARIANTS=[
 ("1 CURRENT       label, else raw_text",      lambda l,rw: (l or "").strip() or (rw or "").strip(), base_cands),
 ("2 RE-PARSED     classify_line(raw)['name']",lambda l,rw: reparse(rw) or (l or "").strip() or (rw or "").strip(), base_cands),
 ("3 CURRENT + every comma segment",           lambda l,rw: (l or "").strip() or (rw or "").strip(), lambda l:(list(base_cands(l))+list(comma_cands(l)))),
 ("4 CURRENT + segments + trailing-prep strip",lambda l,rw: (l or "").strip() or (rw or "").strip(), lambda l:(list(base_cands(l))+list(comma_cands(l))+list(prep_cands(l)))),
]
out={}
for tag,pick,gen in VARIANTS:
    c=collections.Counter(); per={}
    for rec,pos,l,rw in raw_rows:
        t=pick(l,rw); h=hit(gen(t)); c[cls(h)]+=1; per[(rec,pos)]=(cls(h),t,h)
    out[tag]=(c,per)
    print("%-46s MATCHED %4d  AMBIGUOUS %4d  MISS %4d"%(tag,c["MATCHED"],c["AMBIGUOUS"],c["MISS"]))

base=out[VARIANTS[0][0]][1]
for tag,_,_ in VARIANTS[1:]:
    per=out[tag][1]
    flips=[(k,base[k],per[k]) for k in base if base[k][0]!=per[k][0]]
    up=[f for f in flips if f[1][0]=="MISS" and f[2][0]!="MISS"]
    down=[f for f in flips if f[1][0]!="MISS" and f[2][0]=="MISS"]
    print("\n── %s"%tag)
    print("   MISS -> resolved: %d      resolved -> MISS: %d"%(len(up),len(down)))
    seen=set()
    for k,a,b in up:
        if b[1][:40] in seen: continue
        seen.add(b[1][:40])
        print("      %-52s %s -> %s  %s"%(b[1][:52],a[0],b[0],[x[2] for x in b[2]][:2]))
        if len(seen)>=14: break
    for k,a,b in down[:6]: print("      ⚠ REGRESSION %-40s %s -> %s"%(b[1][:40],a[0],b[0]))
import pickle; pickle.dump({t:(dict(c),p) for t,(c,p) in out.items()},open(SP+"/FEED.pkl","wb"))
