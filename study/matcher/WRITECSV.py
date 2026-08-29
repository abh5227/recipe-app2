# -*- coding: utf-8 -*-
"""SCRATCH. Write previews/full-ingredient-match.csv from REGEN.pkl, adding the MVJ
   hand verdicts on the rightmost-vs-seg0 axis so every read line shows its verdict."""
import sys, os, re, csv, io, pickle, collections
SP = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SP)
WT = "/private/tmp/claude-501/-Users-andrewhannah-Documents-Local-Documents-Food-recipe-app/838360e4-1af7-4569-904a-48460982006c/scratchpad/head-wt"
REPO = "/Users/andrewhannah/Documents/Local Documents/Food/recipe-app"
sys.path.insert(0, WT)
from MVJ import J as MVJ
recs = pickle.load(open(SP + "/REGEN.pkl", "rb"))
T = pickle.load(open(SP + "/REGEN_TALLY.pkl", "rb"))
cov = pickle.load(open(SP + "/COV2.pkl", "rb"))          # carries the read/unread mapping
readkey = {(r["slug"], r["pos"]): r["read"] for r in cov if r.get("read")}
for r in recs:
    hand = readkey.get((r["slug"], r["pos"]))
    if hand and r["verdict"] in ("(unread)", ""):
        r["verdict"] = f"{hand[1]} - hand-read on the rightmost-vs-seg0 axis"
read = sum(1 for r in recs if r["verdict"] not in ("(unread)", ""))
def nm(h): return " | ".join(c for _, c in h) if h else ""
def ids(h): return " | ".join(i for i, _ in h) if h else ""
def cls(r): return "MISS" if not r["m"] else ("MATCHED" if len(r["m"]["hit"]) == 1 else "AMBIG")
K2 = collections.Counter(cls(r) for r in recs); C = T["C"]; A = T["A"]; N = T["N"]
LR, LK, LI = T["LIB"]
amb_read = sum(1 for r in recs if cls(r) == "AMBIG" and r["verdict"] not in ("(unread)", ""))
one_read = sum(1 for r in recs if cls(r) == "MATCHED" and r["verdict"] not in ("(unread)", ""))
HEAD = f"""\
# full-ingredient-match  -  EVERY ingredient line in the corpus, matched or not
#
# ⚠ REGENERATED at HEAD bc38181 with the BANKED matcher. The previous render used the
# rightmost tie-break, which is the config that sent 'boneless ribeye' to butter through
# the word 'cubes' and 'asparagus' to 'sharp'. Those 62 regressions are gone here.
#
# SCOPE.  recipe_ingredients holds 3,555 rows across 298 recipes. 223 are is_heading=1
# section headings and are excluded. All {N:,} ingredient lines are below, none sampled,
# none truncated. Library built fresh from join.db + sources.db at HEAD bc38181:
# {LR:,} rows, {LK:,} KEPT, {LI:,} index keys.
#
# THE TWO MATCHERS
#   OLD  the committed reduction ladder. Six reductions, first hit wins: as-stored,
#        normalize, base_name, strip-leading, strip-container, strip-unit. Each tries the
#        key and its depluralized form. It only ever strips from the FRONT of the line.
#   NEW  seg0-core, the banked config. Segment the line on , ; ( ) / - and on 'or'; inside
#        each segment take every consecutive word run; normalize with build_join.norm_name,
#        the SAME function the index is built with. Rank by SEGMENT FIRST, then longest,
#        then leftmost, so the main clause wins over a later parenthetical.
#        ⚠ NO language rule and NO clause strip. Both were measured and are not banked.
#        Stopword guard: a 1-word run that is a stopword is SKIPPED and the search
#        continues. DECLINED-STOPWORD means the only index key on the line was such a word.
#
# WHAT IS LINKED, and the two numbers are not the same thing
#   STORED IN recipes.db RIGHT NOW      50 rows over 6 recipes, 36 distinct ingredient_ids.
#                                       The ingredients table has 36 rows and
#                                       recipe_ingredients.ingredient_id points at it. The
#                                       {LK:,}-row library lives in join.db and reaches no
#                                       recipe row yet.
#   WHAT THIS MATCHER WOULD LINK        {K2['MATCHED']:,} single-row + {K2['AMBIG']:,} ambiguous
#                                       = {K2['MATCHED']+K2['AMBIG']:,} of {N:,} lines.
#
# ⚠ CONFIDENCE. {read:,} of the {N:,} lines carry a HAND verdict. The other
# {N-read:,} were never individually read, and {A['AGREE']:,} of those are the AGREE block
# where the ladder and seg0-core landed on the same row. Agreement is not verification:
# both matchers share the same index and the same normalizer, so they fail together on a
# wrong library row. Every precision figure quoted anywhere rests on that block being
# right, and it has never been checked.
#
# COVERAGE, and it is the fixed definition, not the earlier broken one
#   coverage = words in the matched phrase / (words in the matched phrase + leftover
#   content words in that segment). A matched multi-word index key counts as matched
#   content IN FULL, so 'half-and-half' scores 0.75 rather than 0.00.
#
# CONFIDENCE BANDS, applied in this order, first hit wins:
#   NONE    no match, or the only key on the line was a stopword
#   LOW     coverage below 0.34, OR a 1-word match on a form word (pan, cubes, chips)
#   HIGH    the matched phrase is 2 or more words, OR a 1-word match that is a row's own
#           canonical name and is the whole content of its clause
#   MEDIUM  everything else
#   Counts: HIGH {C['HIGH']:,}   MEDIUM {C['MEDIUM']:,}   LOW {C['LOW']:,}   NONE {C['NONE']:,}
#
# AGREEMENT: AGREE {A['AGREE']:,}   NEW-ONLY {A['NEW-ONLY']:,}   DIFFERENT {A['DIFFERENT']:,}
#            OLD-ONLY {A['OLD-ONLY']:,}   BOTH-MISS {A['BOTH-MISS']:,}
#
# THE 38 MISSES, categorised by reading each one
#   REAL-GAP           17   the library has no row for the thing the line names
#   NOT-INGREDIENT     16   a fragment, a note or a heading, 4 of them wrapped lines
#   DECLINED-STOPWORD   3   'ice', blocked by the stoplist
#   HEAD-NOT-IN-INDEX   2   the row exists under another spelling
#
# REAL-GAP  -  the names the library genuinely lacks, and the line count each carries.
# ⚠ 8 of the 17 are the PASTA SHAPES. The anchor rule that closes rigatoni and ditalini
# is written but NOT COMMITTED, so they are still open here. tubetti and rigati stay open
# even after it, because Wikidata has no item under either name.
# MSG  3
# rigatoni  3
# ditalini  2
# bagel  1
# bourbon  1
# eschalot  1
# kasuri methi  1
# lu bao herb packet  1
# nonstick spray  1
# paratha  1
# rigati  1
# tubetti  1
# TOTAL 12 names over 17 lines
#
# verdict_when_differ says '(unread)' where no hand verdict exists. It is not a claim that
# the row is right. It is the absence of a claim.
"""
COLS = ["recipe_slug","position","raw_text","parsed_name","old_match","old_row_id","old_rung",
        "new_match","new_row_id","new_matched_phrase","new_confidence","new_reason",
        "agreement","verdict_when_differ"]
dst = os.path.join(REPO, "previews/full-ingredient-match.csv")
with io.open(dst, "w", encoding="utf-8-sig", newline="") as fh:
    fh.write(HEAD)
    w = csv.writer(fh, quoting=csv.QUOTE_ALL)
    w.writerow(COLS)
    for r in recs:
        m = r["m"]
        w.writerow([r["slug"], r["pos"], r["raw"], r["parsed"],
                    nm(r["ohit"]), ids(r["ohit"]), r["rung"],
                    nm(m["hit"]) if m else "", ids(m["hit"]) if m else "",
                    m["ngram"] if m else "", r["conf"], r["why"],
                    r["agree"], r["verdict"]])
print(f"wrote {dst}  {len(recs):,} rows, hand-read {read:,}")
pickle.dump(dict(read=read, one_read=one_read, amb_read=amb_read), open(SP+"/READ.pkl","wb"))
