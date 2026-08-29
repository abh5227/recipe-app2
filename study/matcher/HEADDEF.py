# -*- coding: utf-8 -*-
"""THE HEAD-NOUN DEFINITION, and its stress cases. Reads nothing, writes nothing."""
import sys,os,re
SP=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,SP)
ROOT="/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0,ROOT); os.chdir(ROOT)
from build_join import norm_name as n
from STOP2 import STOP
SEG=re.compile(r"[,;()/–—]|\bor\b|\band/or\b",re.I)
LEADNUM=re.compile(r"^(?:[\d¼-¾⅐-⅞./\s]+)"); MARK="*†‡#•~+°±%&!?;:.,\"'“”​⁄/"
NUMTOK=re.compile(r"^[\d¼-¾⅐-⅞./%°]+$")
def toks(s): return [w for w in (t.strip(MARK) for t in n(LEADNUM.sub("",(s or "").strip())).split()) if w]
def is_content(w): return w not in STOP and not NUMTOK.match(w) and any(c.isalnum() for c in w)

def head_noun(seg_words):
    """THE DEFINITION: the LAST content word of the segment. Content means not in the
    stoplist, not a bare number, has a letter or digit.

    Why the last word and not a part-of-speech guess: English is head-final in a noun
    phrase, so the thing being named is the last word and everything before it modifies
    it. 'chile powder' is a powder. 'chicken breast' is a breast. No tagger is needed and
    none is available offline.

    ⚠️ FORM WORDS COUNT AS HEADS AND THAT IS THE POINT. 'flakes' in 'chile flakes' IS the
    head noun. Skipping form words to reach 'chile' would reintroduce the exact bug this
    rule exists to fix, because 'red chile powder' would then head on 'chile' and 'red
    chile' would win again."""
    c=[w for w in seg_words if is_content(w)]
    return c[-1] if c else None

CASES=[
 ("red chile powder","powder","'chile powder' must beat 'red chile'"),
 ("boneless skinless chicken breast","breast","-> longest containing 'breast' = chicken breast"),
 ("extra virgin olive oil","oil","-> longest containing 'oil'"),
 ("chile flakes","flakes","⚠ THE AMBIGUOUS ONE"),
 ("chicken thighs, bone-in","thighs","seg 0 only"),
 ("2 tablespoons ghee or olive oil","ghee","seg 0 is 'ghee', unchanged by head-noun"),
 ("1 cup mashed ripe banana","banana","'mashed' and 'ripe' are stoplisted"),
 ("garlic, crushed to a paste with a pinch of salt","garlic","seg 0 is 'garlic'"),
 ("bone-in, skin-on chicken thighs","bone","⚠ FAILS: seg 0 is 'bone in', head is 'bone'"),
 ("1 pound skirt steak or flank steak","steak","seg 0 head"),
 ("small skin-on boneless snapper fillets","fillets","form word is the head, correctly"),
 ("sea salt and freshly ground black pepper","pepper","'and' is stoplisted, so one segment"),
 ("1 2-3 lb. sugar pumpkin","pumpkin","fixes seg0's 'sugar'"),
 ("1 teaspoon vanilla paste or extract","paste","seg 0 = 'vanilla paste'"),
 ("Tahini Brioche Dough, cold","dough","fixes seg0's 'tahini'"),
]
print("=== head_noun = LAST CONTENT WORD of the segment ===\n")
print("%-46s %-12s %-10s %s"%("line (segment 0 shown)","predicted","actual","note"))
print("-"*116)
bad=0
for line,want,note in CASES:
    seg0=SEG.split(line)[0]
    w=toks(seg0); h=head_noun(w)
    ok = (h==want)
    if not ok: bad+=1
    print("%-46s %-12s %-10s %s%s"%(line[:46],want,h or "(none)",note," " if ok else "   <-- MISMATCH"))
print("\n%d of %d as predicted"%(len(CASES)-bad,len(CASES)))
print("\n=== WHERE THE DEFINITION IS SHAKY, named up front ===")
for line in ["bone-in, skin-on chicken thighs","3 pc skin-on, bone-in chicken thigh",
             "1 cup daikon radish (julienned)","2 cups masa harina teaspoon kosher salt",
             "Breakfast potatoes, toast, and/or fruit","banana shallots (about 2 oz/70g total prepared weight)",
             "1 teaspoon Kashmiri chili","Different additions so far","AP Flour"]:
    seg0=SEG.split(line)[0]; w=toks(seg0)
    print("   %-52s seg0=%-26s head=%r"%(line[:52]," ".join(w)[:26],head_noun(w)))
