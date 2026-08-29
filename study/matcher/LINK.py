"""READ-ONLY SCRATCH RUN. Resolve every recipe label to a library row. WRITES NOTHING.

⚠ NO MIGRATION, NO SCHEMA, NO WRITE. This computes what a linkage pass WOULD produce and
  reports it, so the write-side work is justified by a measurement rather than an assumption."""
import sys,os,re,sqlite3,collections,pickle
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
sys.path.insert(0,"/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
os.chdir("/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
import lib, build_library as BL, weights
from build_join import norm_name as n
db=sqlite3.connect("file:recipes.db?mode=ro",uri=True)
rows,_=lib.rowset(BL); kept=[r for r in rows if not r["cut_by"]]
# name -> [(anchor,id,canonical)] ; a name on several rows is AMBIGUOUS and reported as such
idx=collections.defaultdict(list)
for r in kept:
    key=(r["anchor"],str(r["id"]),r["canonical"])
    for t in r["variations"]: idx[n(t)].append(key)
for k in idx: idx[k]=sorted(set(idx[k]))

LEAD=re.compile(r"^(?:\d+[\d\s/.¼½¾⅓⅔⅛-]*\s*)?(?:of\s+|the\s+|a\s+|an\s+)?"
    r"(?:(?:whole|peeled|canned|tinned|frozen|fresh|freshly|ripe|large|small|medium|good|"
    r"quality|best|spooned|leveled|packed|firmly|finely|roughly|thinly|coarsely|cooked|raw|"
    r"dried|extra|plain|toasted|warm|lukewarm|hot|cold|room|natural|pure|unsweetened|"
    r"ground|squeezed|light|dark|fine|coarse|granulated|caster|superfine|boneless|skinless|"
    r"unsalted|salted|low|reduced|full|semi|non)\s+)+", re.I)
CONT=re.compile(r"^(?:\d+\s*)?(?:cans?|jars?|tins?|packets?|boxes?|bags?|bunch(?:es)?|"
    r"heads?|cloves?|sticks?|sprigs?|stalks?|slices?|pieces?|strips?)\s+(?:of\s+)?", re.I)
UNITWORD=re.compile(r"^(cloves?|sticks?|sprigs?|stalks?|heads?|bunch(?:es)?|slices?)\s+", re.I)
def cands(l):
    """Every reduction, cheapest first. The FIRST that resolves wins, and which one it was
    is reported, so a costly rule can be dropped if it earns nothing."""
    b=weights.base_name(l)
    yield "as stored",               n(l)
    yield "weights.normalize",       n(weights.normalize(l))
    yield "weights.base_name",       n(b)
    yield "strip leading modifiers", n(LEAD.sub("",b).strip())
    yield "strip a container word",  n(CONT.sub("",LEAD.sub("",b)).strip())
    yield "strip a unit word",       n(UNITWORD.sub("",CONT.sub("",LEAD.sub("",b)).strip()))
def resolve(l):
    for how,k in cands(l):
        if not k: continue
        for key in (k, BL.depluralize(k)):
            if key and key in idx: return how,key,idx[key]
    return None,None,None

lines=list(db.execute("SELECT ri.id, r.id, ri.label, ri.ingredient_id FROM recipe_ingredients ri "
                      "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 "
                      "AND ri.label IS NOT NULL AND TRIM(ri.label)<>''"))
res={}; byhow=collections.Counter(); amb=0
for rid,rec,label,existing in lines:
    how,key,hits=resolve(label)
    res[rid]=(rec,label,existing,how,key,hits)
    byhow[how or "⚠ UNRESOLVED"]+=1
    if hits and len(hits)>1: amb+=1
print("recipe ingredient lines: %d\n"%len(lines))
print("%-26s %6s"%("resolved by","lines"))
for k in ["as stored","weights.normalize","weights.base_name","strip leading modifiers",
          "strip a container word","strip a unit word","⚠ UNRESOLVED"]:
    if byhow.get(k): print("%-26s %6d"%(k,byhow[k]))
got=len(lines)-byhow["⚠ UNRESOLVED"]
print("\nLINKED  %d of %d  (%.1f%%)     was 50 (1.5%%)"%(got,len(lines),100*got/len(lines)))
print("⚠ AMBIGUOUS, the name is on 2+ rows: %d lines (%.1f%% of linked)"%(amb,100*amb/got))
pickle.dump(res,open(SP+"/LINK.pkl","wb"))
