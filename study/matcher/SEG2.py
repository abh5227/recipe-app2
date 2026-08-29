# -*- coding: utf-8 -*-
"""Re-derive the hand verdicts at the new HEAD, then the four-variant table."""
import sys,os,collections,pickle
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
ROOT="/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0,ROOT); os.chdir(ROOT)
from VERD import D as VD
from VERDN import WRONG as NW, LOW as NL
recs=pickle.load(open(SP+"/SEG.pkl","rb"))
def K(h): return tuple(sorted(i for i,_ in h)) if h else None
def nm(h): return " | ".join(c for _,c in h) if h else ""
def agree(r,v="rm"):
    o,w=K(r["ohit"]),K(r[v]["hit"] if r[v] else None)
    return ("AGREE" if o==w else "DIFFERENT") if (o and w) else ("OLD-ONLY" if o else ("NEW-ONLY" if w else "BOTH-MISS"))
unmatched=[]
for r in recs:
    a=agree(r); r["agree"]=a; r["verdict"]=""
    if a=="NEW-ONLY":
        k=(r["rm"]["ngram"],nm(r["rm"]["hit"]))
        r["verdict"]="BOTH-WRONG" if k in NW else "NEW-RIGHT"
        r["low"]= k in NL
    elif a in ("DIFFERENT","OLD-ONLY"):
        k=(nm(r["ohit"]),nm(r["rm"]["hit"]) if r["rm"] else "-",(r["rm"]["ngram"] if r["rm"] else "-"))
        if k in VD: r["verdict"],why,conf=VD[k][0],VD[k][1],VD[k][2]; r["low"]=(conf=="LOW")
        else: r["verdict"]="UNJUDGED"; unmatched.append(r); r["low"]=False
    else: r["low"]=False
print("=== hand verdicts re-keyed at HEAD bc38181 ===")
C=collections.Counter(r["verdict"] for r in recs if r["verdict"])
for k,v in C.most_common(): print("   %-32s %5d"%(k,v))
print("   UNJUDGED patterns needing a look: %d"%len(unmatched))
for r in unmatched[:6]:
    print("      OLD %-26s NEW %-26s '%s'  | %s"%(nm(r["ohit"]),nm(r["rm"]["hit"]) if r["rm"] else "-",
          r["rm"]["ngram"] if r["rm"] else "-",r["raw"][:56]))
OLDRIGHT=[r for r in recs if r["verdict"]=="OLD-RIGHT"]
NEWRIGHT=[r for r in recs if r["agree"]=="NEW-ONLY" and r["verdict"]=="NEW-RIGHT"]
NEWWRONG=[r for r in recs if r["agree"]=="NEW-ONLY" and r["verdict"]=="BOTH-WRONG"]
print("\n   OLD-RIGHT regressions %d   NEW-RIGHT recoveries %d   NEW-ONLY wrong %d"
      %(len(OLDRIGHT),len(NEWRIGHT),len(NEWWRONG)))
pickle.dump(dict(recs=recs,OLDRIGHT=[id(x) for x in OLDRIGHT]),open(SP+"/SEG2.pkl","wb"))

# ── 2. THE FOUR-VARIANT TABLE ────────────────────────────────────────────────
def cls(h): return "MISS" if not h else ("MATCHED" if len(h)==1 else "AMBIG")
VAR=[("(a) rightmost  [today]","rm"),("(b) seg0","s0"),
     ("(c) seg0 + language","s0l"),("(d) seg0 + language, 1-word only","s0l1")]
print("\n=== 2. FOUR VARIANTS over all %d lines ==="%len(recs))
hdr="%-34s %8s %9s %6s | %11s %11s %10s %11s"%("variant","matched","ambiguous","miss",
    "REGRESSIONS","regr FIXED","recov KEPT","still WRONG")
print(hdr); print("-"*len(hdr))
TAB=[]
for label,v in VAR:
    c=collections.Counter(cls(r[v]["hit"] if r[v] else None) for r in recs)
    # a REGRESSION under this variant: a line the ladder matched to one row, where the
    # variant lands on a different row set
    regr=sum(1 for r in recs if r["ohit"] and len(r["ohit"])==1 and r[v] and K(r[v]["hit"])!=K(r["ohit"]))
    fixed=sum(1 for r in OLDRIGHT if not r[v] or K(r[v]["hit"])==K(r["ohit"]))
    kept =sum(1 for r in NEWRIGHT if r[v] and K(r[v]["hit"])==K(r["rm"]["hit"]))
    wrong=sum(1 for r in NEWWRONG if r[v] and K(r[v]["hit"])==K(r["rm"]["hit"]))
    print("%-34s %8d %9d %6d | %11d %11d %10d %11d"
          %(label,c["MATCHED"],c["AMBIG"],c["MISS"],regr,fixed,kept,wrong))
    TAB.append(dict(variant=label.strip(),matched=c["MATCHED"],ambiguous=c["AMBIG"],miss=c["MISS"],
        regressions_vs_OLD=regr,known_regressions_fixed="%d of %d"%(fixed,len(OLDRIGHT)),
        recoveries_kept="%d of %d"%(kept,len(NEWRIGHT)),
        new_only_still_wrong="%d of %d"%(wrong,len(NEWWRONG))))
pickle.dump(TAB,open(SP+"/TAB.pkl","wb"))
