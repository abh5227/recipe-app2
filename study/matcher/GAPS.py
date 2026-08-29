"""READ-ONLY COVERAGE MEASUREMENT. Builds the library FRESH from join.db + sources.db,
resolves every stored ingredient line, writes ONE file: previews/ingredient-gaps.csv.
Touches recipes.db read-only. Adds nothing to the importer."""
import sys,os,re,csv,collections,sqlite3
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
sys.path.insert(0,"/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
os.chdir("/Users/andrewhannah/Documents/Local Documents/Food/recipe-app")
import lib, build_library as BL, weights
from build_join import norm_name as n

# ── THIRD: build the library FRESH (recomputed from join.db + sources.db, NOT read from the xlsx)
rows,_ = lib.rowset(BL)
kept   = [r for r in rows if not r["cut_by"]]
print("library rebuilt fresh: %d rows total, %d KEPT, %d cut"%(len(rows),len(kept),len(rows)-len(kept)))

idx=collections.defaultdict(list)
for r in kept:
    key=(r["anchor"],str(r["id"]),r["canonical"])
    for t in r["variations"]: idx[n(t)].append(key)
for k in idx: idx[k]=sorted(set(idx[k]))
print("name index: %d distinct normalized names over the kept rows"%len(idx))

# ── SECOND: the resolver, verbatim from the surviving scratch script
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
    b=weights.base_name(l)
    yield "as stored",               n(l)
    yield "weights.normalize",       n(weights.normalize(l))
    yield "weights.base_name",       n(b)
    yield "strip leading modifiers", n(LEAD.sub("",b).strip())
    yield "strip a container word",  n(CONT.sub("",LEAD.sub("",b)).strip())
    yield "strip a unit word",       n(UNITWORD.sub("",CONT.sub("",LEAD.sub("",b)).strip()))
def resolve(l):
    tried=[]
    for how,k in cands(l):
        tried.append("%s=%r"%(how,k))
        if not k: continue
        for key in (k, BL.depluralize(k)):
            if key and key in idx: return how,key,idx[key],tried
    return None,None,None,tried

# near-miss: index keys sharing the final word (head noun) of the last reduced form
head_idx=collections.defaultdict(list)
for k in idx:
    t=k.split()
    if t: head_idx[t[-1]].append(k)
def near(key):
    if not key: return ""
    t=key.split()
    if not t: return ""
    c=[x for x in head_idx.get(t[-1],[]) if x!=key]
    c.sort(key=len)
    return "; ".join(c[:3])

db=sqlite3.connect("file:recipes.db?mode=ro",uri=True); db.execute("PRAGMA query_only=ON")
print("\nrecipes in db: %d   with >=1 ingredient line: %d"%(
  db.execute("SELECT COUNT(*) FROM recipes").fetchone()[0],
  db.execute("SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredients WHERE is_heading=0").fetchone()[0]))

def run(sql,tag):
    lines=list(db.execute(sql))
    res=[]; c=collections.Counter()
    for rid,rec,label,raw,pos in lines:
        text=(label or "").strip() or (raw or "").strip()
        how,key,hits,tried=resolve(text)
        if hits is None:      cls="MISS"
        elif len(hits)==1:    cls="MATCHED"
        else:                 cls="AMBIGUOUS"
        c[cls]+=1
        res.append((rid,rec,pos,text,label,raw,cls,how,key,hits,tried))
    t=len(lines)
    print("\n── %s: %d lines"%(tag,t))
    for k in ("MATCHED","AMBIGUOUS","MISS"):
        print("     %-10s %5d  %5.1f%%"%(k,c[k],100*c[k]/t if t else 0))
    return res,c,t

# Population A: the scratch population (label present) -> faithfulness check vs 2,159/2,997
A,cA,tA = run("SELECT ri.id, r.id, ri.label, ri.raw_text, ri.position FROM recipe_ingredients ri "
  "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0 AND ri.label IS NOT NULL "
  "AND TRIM(ri.label)<>''","POPULATION A (label present) — the scratch population")
# Population B: EVERY ingredient line, label-or-raw_text -> the real coverage
B,cB,tB = run("SELECT ri.id, r.id, ri.label, ri.raw_text, ri.position FROM recipe_ingredients ri "
  "JOIN recipes r ON r.id=ri.recipe_id WHERE ri.is_heading=0","POPULATION B (every ingredient line)")

# ── FIFTH: the gap list, from population B
miss=[x for x in B if x[6]=="MISS"]
final_key=lambda tried:(tried[-1].split("=",1)[1].strip("'\"") if tried else "")
name_of=lambda x: final_key(x[10]) or x[3].casefold()
counts=collections.Counter(name_of(x) for x in miss)
out=[]
for x in sorted(miss,key=lambda x:(-counts[name_of(x)],name_of(x),x[1],x[2])):
    rid,rec,pos,text,label,raw,cls,how,key,hits,tried=x
    nm=name_of(x)
    out.append({"missed_name":nm,"lines_for_this_name":counts[nm],
      "raw_text":(raw or "").strip(),"parsed_label":(label or "").strip(),
      "resolver_input":text,"recipe_slug":rec,"position":pos,
      "reductions_tried":" | ".join(tried),"closest_near_miss":near(nm)})
os.makedirs("previews",exist_ok=True)
p="previews/ingredient-gaps.csv"
with open(p,"w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh,fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    fh.write("\n")
    w2=csv.writer(fh)
    w2.writerow(["=== SECTION 2: THE GAP SET — distinct missed names, highest line count first ==="])
    w2.writerow(["missed_name","lines","example_raw_text","closest_near_miss"])
    for nm,ct in counts.most_common():
        ex=next(( (x[5] or "").strip() for x in miss if name_of(x)==nm),"")
        w2.writerow([nm,ct,ex,near(nm)])
print("\nwrote %s  (%d miss rows, %d distinct missed names)"%(p,len(out),len(counts)))
print("\n=== TOP 40 DISTINCT MISSED NAMES ===")
for nm,ct in counts.most_common(40):
    ex=next(((x[5] or "").strip() for x in miss if name_of(x)==nm),"")
    print("  %3d  %-28s  e.g. %s"%(ct,nm[:28],ex[:60]))
import pickle; pickle.dump({"miss":[(name_of(x),x[1],x[2],x[3],x[5]) for x in miss],
                            "counts":counts},open(SP+"/GAPS.pkl","wb"))
