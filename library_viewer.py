#!/usr/bin/env python3
"""library_viewer.py - a read-only instrument for the ingredient library.

    python3.13 library_viewer.py        then open http://localhost:8100

⚠️ READ-ONLY ON THE DATABASE, BY CONSTRUCTION. Every connection is opened
`file:recipes.db?mode=ro`, so the process CANNOT write to it even if a query tried. A verification
tool that can corrupt what it verifies is worse than none.

⚠️ IT WRITES ONE FILE, AND ONLY ONE: hand_substitutions.csv. The substitutions tab is a review
queue, and a confirm or a reject there appends a line to that file. This is not an exception to
the rule above, it is the project's own pattern applied here. load_relations.py states it plainly:
the hand file is the only writer, and a decision stored in recipes.db would be orphaned by the
next load with nothing in the build to notice it. So the decision goes where a rebuild will find
it, and library_substitutions is a projection of the file rather than a place anything is typed
into. Everything else on this instrument still reads and nothing more.

⚠️ SEPARATE FROM app.py. Different port, own process, own connections, no imports from it.

DESIGN. One instrument. Every page shares the rail, the readout strip, the ruled treatment and the
ledger row (label left, dotted leader, figure right). Teal carries meaning only: bound segments,
leading values, links. Amber carries only the unbound and the drifted. Mono appears on machine
values, never on a label.

⚠️ THE SIX DATA GOTCHAS, each capable of showing WRONG data silently rather than erroring. Every
   one is marked GOTCHA n at its handler.

 1. library_relations.parent_id is TWO NAMESPACES. kind='in_category' means a
    library_categories.category_id; kind in (kind_of, made_from) means a library_names.library_id.
    'bread' and 'pasta' exist in BOTH tables under the same string, so an unconstrained join
    silently mixes them. This already produced a wrong count once.
 2. library_siblings.sibling_id is stored LOWERCASE ('q78295261'). A plain join returns NOTHING,
    so the panel renders empty rather than erroring. Joined COLLATE NOCASE.
 3. library_entries.link_state IS COMPUTED AT LOAD AND GOES STALE. The viewer recomputes it and
    NEVER prints the stored value as fact. Live is 51 linked / 2 drift / 3 no-row; the stored
    field still says 52 / 1 / 3 because strained-yogurt was renamed after the load.
 4. 'legume' has a SPLIT PARENT REPRESENTATION: some children reach it as kind_of on the catalog
    row, others as in_category on the slug. Membership is gathered along BOTH paths.
 5. THREE ENTRIES HAVE NO library_id (salt, sugar, water). A normal state, not an error.
 6. A CHILD CAN CARRY TWO EDGES TO ONE PARENT under different kinds. The graph dedupes by parent.

⚠️ THE EMPTY STATE IS THE DEFAULT. Two catalog rows in five carry no relation at all and only
53 have a written entry. A bare row is the ordinary thing this viewer shows.
"""
import csv, datetime, hashlib, math, os, re, sqlite3, time
from flask import Flask, request, jsonify, redirect
from markupsafe import escape
from urllib.parse import quote

DB = os.environ.get("VIEWER_DB", "recipes.db")
# ⚠️ THE ONE FILE THIS PROCESS CAN WRITE. Named here beside the database so the pair is read
#    together, and printed in the readout strip on every page so the claim is visible rather
#    than buried in a docstring.
HAND = os.environ.get("VIEWER_HAND", "hand_substitutions.csv")
PORT = int(os.environ.get("VIEWER_PORT", "8100"))
PER = 60
app = Flask(__name__)


def db():
    """⚠️ mode=ro. The process cannot write to the library it is inspecting."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


# ── the matcher, memoized on the database's own fingerprint ──────────────────
# The reason a line failed to bind is not stored anywhere: link_rule is only written for lines
# that DID bind. Recovering it means running the matcher. That is a few seconds, so the result is
# held against the database's size and mtime and recomputed the moment either changes. The page is
# still live in the sense that matters: it can never show a result from a different database.
_MATCH = {"key": None, "rows": None}


def proposals():
    st = os.stat(DB)
    key = (st.st_size, st.st_mtime_ns)
    if _MATCH["key"] != key:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import importlib, linkage_matcher
        importlib.reload(linkage_matcher)
        rows, _ = linkage_matcher.propose(db=DB)
        _MATCH["key"], _MATCH["rows"] = key, rows
    return _MATCH["rows"]


# ════════════════════════════════════════════════════════════════════════════
#  THE SHELL. Lifted verbatim from the locked bench mockup so every page is
#  the same instrument.
# ════════════════════════════════════════════════════════════════════════════

CSS = """
:root{
  --surface:#fff; --ground:#EEF1F2; --ink:#1B2A33; --steel:#526B7A; --steel-dim:#6B8492;
  --teal:#0E6E6E; --teal-mid:#4E9695; --teal-pale:#B9D4D3; --teal-wash:#F0F6F6;
  --amber:#A45B0B; --amber-wash:#FBF4EC; --rule:#C3D0D5; --hair:#E1E8EA; --wash:#F6F9F9;
  --rail:#1B2A33; --rail-2:#263A45; --rail-text:#A9BFC9;
  --s0:11px; --s1:12.5px; --s2:13.5px; --s3:15px; --s4:20px; --s5:30px; --s6:56px;
  --pad:clamp(18px,3.2vw,34px);
  /* ⚠️ THE GUTTER between a divider and the text after it. Every columned block was written as
     padding-right plus a border-right, which leaves padding-left at 0, so the first column sat
     correctly against the page edge and every column after it sat flush against the divider of
     the one before. The container is pulled left by the same amount, so the first column keeps
     its alignment with the prose above while every column gains the gutter. */
  --gut:20px;
  /* ⚠️ THE MEASURE FOR ANYTHING THAT IS NOT A TABLE. Charts and the header count sat in an
     unbounded column, so a bar drawn at 1800px stretched to 1,508px and the count landed
     1,299px from its own title. A table stops at its content width. A bar has no content
     width, so it needs one stated. The count shares it, which puts it on the right edge of
     the bar it summarises instead of the right edge of the monitor. */
  --chart:920px;
}
*{box-sizing:border-box;min-width:0}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ground);color:var(--ink);
  font:var(--s2)/1.55 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
a{color:inherit;text-decoration:none}
a:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
h1{margin:0 0 3px;font-size:var(--s4);font-weight:600;letter-spacing:-.004em}
h2{margin:0 0 2px;font-size:var(--s3);font-weight:600}
h3{margin:0 0 3px;font-size:var(--s2);font-weight:600}
.hint{margin:0 0 var(--pad);font-size:var(--s1);color:var(--steel);max-width:74ch;line-height:1.55}
.sub{margin:0 0 var(--pad);font-size:var(--s1);color:var(--steel);max-width:74ch;line-height:1.55}

.shell{display:grid;grid-template-columns:224px 1fr;min-height:100vh}
@media(max-width:900px){.shell{grid-template-columns:1fr}}

.rail{background:var(--rail);color:var(--rail-text);position:sticky;top:0;height:100vh;
  display:flex;flex-direction:column;padding:20px 0 16px;overflow-y:auto}
@media(max-width:900px){.rail{position:static;height:auto;padding-bottom:6px;overflow:visible}}
.rail .mark{padding:0 20px 16px;border-bottom:1px solid var(--rail-2);margin-bottom:12px}
.rail .mark b{display:block;color:#fff;font-size:var(--s3);font-weight:600}
.rail .mark span{display:block;font-size:var(--s0);color:#7E97A4;margin-top:2px}
.rail nav{display:flex;flex-direction:column}
@media(max-width:900px){.rail nav{flex-direction:row;flex-wrap:wrap;padding:0 12px 8px}}
.rail a{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:7px 20px;
  font-size:var(--s2);color:var(--rail-text);border-left:2px solid transparent;line-height:1.4}
@media(max-width:900px){.rail a{border-left:none;border-bottom:2px solid transparent;padding:6px 10px}}
.rail a:hover{background:var(--rail-2);color:#fff}
.rail a[aria-current]{background:var(--rail-2);color:#fff;border-left-color:var(--teal)}
@media(max-width:900px){.rail a[aria-current]{border-left-color:transparent;border-bottom-color:var(--teal)}}
.rail a var{font-style:normal;font-size:var(--s1);color:#7E97A4;
  font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.rail a:hover var,.rail a[aria-current] var{color:var(--teal-pale)}
.rail .tail{margin-top:auto;padding:14px 20px 0;border-top:1px solid var(--rail-2);
  font-size:var(--s0);color:#7E97A4;line-height:1.6}
@media(max-width:900px){.rail .tail{display:none}}

main{background:var(--surface);min-height:100vh}
.readout{display:flex;flex-wrap:wrap;padding:0 var(--pad);border-bottom:1px solid var(--rule)}
.readout .f{padding:11px 22px 11px 0;margin-right:22px;border-right:1px solid var(--hair)}
.readout .f:last-child{border-right:none;margin-right:0;padding-right:0}
.readout label{display:block;font-size:var(--s0);color:var(--steel);margin-bottom:1px;font-weight:450}
.readout .v{font-size:var(--s2);font-weight:500;line-height:1.35}
.readout .live{color:var(--teal);display:inline-flex;align-items:center;gap:6px}
.readout .live::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--teal);flex:none}
.crumb{padding:9px var(--pad) 0;font-size:var(--s1);color:var(--steel)}
.crumb a{color:var(--steel)} .crumb a:hover{color:var(--teal);text-decoration:underline}
.crumb i{font-style:normal;color:#9DB0B9;padding:0 7px}

section{padding:clamp(22px,3.4vw,34px) var(--pad)}
section + section{border-top:1px solid var(--rule)}

/* ── the ledger row: label left, leader, figure right ─────────────────── */
.led{display:flex;align-items:baseline;gap:0}
.led .lab{font-size:var(--s2);font-weight:500;white-space:nowrap;min-width:0}
@media(max-width:1000px){.led .lab{white-space:normal;overflow-wrap:anywhere}
  .led .lead{min-width:10px;margin:0 8px}}
.led .lead{flex:1 1 auto;min-width:16px;margin:0 12px;border-bottom:1px dotted var(--rule);
  transform:translateY(-.3em)}
.led .fig{font-family:"IBM Plex Mono",monospace;font-weight:500;font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap}

/* ── gauge ────────────────────────────────────────────────────────────── */
.head{display:flex;align-items:flex-end;gap:clamp(16px,3vw,30px);flex-wrap:wrap;
  margin-bottom:clamp(22px,3.4vw,30px)}
.head a.big{font-family:"IBM Plex Mono",monospace;font-size:var(--s6);font-weight:500;
  line-height:.84;letter-spacing:-.035em;color:var(--teal);font-variant-numeric:tabular-nums;
  display:inline-block;border-bottom:2px solid transparent}
.head a.big:hover{border-bottom-color:var(--teal)}
.head .of{font-size:var(--s3);color:var(--steel);line-height:1.4;padding-bottom:4px;max-width:18ch}
.head .of b{color:var(--ink);font-weight:500;font-family:"IBM Plex Mono",monospace}
.head .pct{margin-left:auto;padding-left:clamp(16px,2.6vw,26px);border-left:1px solid var(--hair);
  line-height:1.1;padding-bottom:2px}
.head .pct .v{font-family:"IBM Plex Mono",monospace;font-size:var(--s5);font-weight:500;
  color:var(--teal);letter-spacing:-.028em;border-bottom:2px solid transparent}
.head a.pct:hover .v{border-bottom-color:var(--teal)}
.head .pct .l{display:block;font-size:var(--s1);color:var(--steel);margin-top:3px}
@media(max-width:620px){.head .pct{margin-left:0;border-left:none;padding-left:0;width:100%;
  border-top:1px solid var(--hair);padding-top:12px;margin-top:4px}}
.track{display:flex;height:30px;border:1px solid var(--rule)}
.track i{display:block;height:100%}
.track i + i{border-left:1px solid rgba(255,255,255,.55)}
/* ⚠️ EVERY SEGMENT IS A DOOR. The bar showed the shape and the legend underneath held the only
   links, so the thing you were looking at was not the thing you could click. */
.track a{display:block;height:100%;min-width:0}
.track a + a{border-left:1px solid rgba(255,255,255,.55)}
.track a:hover{filter:brightness(1.12)}
.track a:focus-visible{outline:2px solid var(--ink);outline-offset:1px}

/* the same gauge, sized for the top of an inner page */
.pgauge{margin:0 0 clamp(18px,2.6vw,24px);max-width:var(--chart)}
.pgauge .gcap{margin:0 0 7px;font-family:"IBM Plex Mono",monospace;font-size:var(--s0);
  color:var(--steel-dim)}
/* the dashboard coverage chart is four siblings, not one wrapper, so they share the cap */
.chart{max-width:var(--chart)}
.pgauge .track{height:26px}
/* ⚠️ NOTHING HERE IS PLACED BY SEGMENT WIDTH. Drawing a percentage on its own segment, or
   centred above it, fails on the small ones, and the failure was measured rather than guessed:
   1.2% needs 18px of type and its block is 11.5px, 0.7% needs 16px and has 7.3px, and the
   made-from 0.0% needs 13px and has 1.4px. Above the bar the same two labels overlap, their
   centres 8.5px apart. One key per line with the figure in a fixed column makes 0.0% exactly as
   legible as 77.0%. Tabular mono, right-aligned, stacks the decimal points so the column reads
   as one scale. No rule between rows. The leader already carries the eye across. */
.pgauge .keys{margin-top:11px}
.pgauge .keys a{display:flex;align-items:baseline;padding:6px 0;font-size:var(--s1);
  color:var(--steel)}
.pgauge .keys a:hover{color:var(--teal)}
.pgauge .keys em{width:10px;height:10px;flex:none;display:block;border:1px solid rgba(0,0,0,.06);
  transform:translateY(1px);margin-right:9px}
.pgauge .keys .lab{white-space:nowrap;min-width:0}
.pgauge .keys b{font-family:"IBM Plex Mono",monospace;font-weight:500;color:var(--ink);
  font-variant-numeric:tabular-nums;margin-left:15px}
.pgauge .keys a:hover b{color:var(--teal)}
.pgauge .keys .lead{flex:1 1 auto;min-width:24px;margin:0 14px;
  border-bottom:1px dotted var(--rule);transform:translateY(-.3em)}
/* named off `sub`: that class is the page standfirst paragraph and carried a bottom margin of
   up to 34px into every key row. */
.pgauge .keys .pc{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;
  color:var(--steel);width:7ch;text-align:right;flex:none}
.pgauge .keys a:hover .pc{color:var(--teal)}
@media(max-width:640px){.pgauge .keys .lab{white-space:normal;overflow-wrap:anywhere}
  .pgauge .keys .lead{min-width:12px;margin:0 9px}}
.ruler{position:relative;height:26px}
.ruler .t{position:absolute;top:0;width:1px;height:6px;background:var(--rule)}
.ruler .t.maj{height:9px;background:var(--steel-dim)}
.ruler .lab{position:absolute;top:11px;font-family:"IBM Plex Mono",monospace;font-size:var(--s0);
  color:var(--steel);transform:translateX(-50%);white-space:nowrap}
.ruler .lab.first{transform:none} .ruler .lab.last{transform:translateX(-100%)}
/* the same one-key-per-line reading as the gauge legends, plus the gloss each key carries.
   Three columns split by rules put the figure of one key beside the label of the next. */
.legend{margin-top:clamp(14px,2.2vw,20px)}
.legend a{display:block;padding:10px 10px 11px 8px;margin-left:-8px}
.legend a:hover{background:var(--teal-wash)}
.legend .led em{width:11px;height:11px;flex:none;display:block;border:1px solid rgba(0,0,0,.06);
  margin-right:9px;transform:translateY(-1px)}
.legend .led .fig{font-size:var(--s4);line-height:1.1}
.legend .led .pc{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;
  color:var(--steel);width:8ch;text-align:right;flex:none;margin-left:20px;font-size:var(--s2)}
.legend a:hover .lab{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
.legend a:hover .pc{color:var(--teal)}
.legend .g{display:block;font-size:var(--s1);color:var(--steel);margin-top:2px;line-height:1.5;
  max-width:62ch;padding-left:20px}
.legend .bound .fig{color:var(--teal)} .legend .un .fig{color:var(--amber)}

/* a source you can follow. The slug reads as the citation, the href goes to the source. */
a.src{color:var(--teal);border-bottom:1px solid var(--teal-pale);font-size:var(--s1)}
a.src:hover{border-bottom-color:var(--teal);background:var(--teal-wash)}
a.src + a.src{margin-left:8px}
span.src{font-size:var(--s1)}
.meta a.src{margin-left:2px}

/* ── registers ────────────────────────────────────────────────────────── */
.reg{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--hair)}
@media(max-width:860px){.reg{grid-template-columns:repeat(2,1fr)}}
@media(max-width:520px){.reg{grid-template-columns:1fr}}
.reg a:not(:nth-child(3n+1)){padding-left:var(--gut)}
.reg a{display:block;padding:15px 20px 16px 0;border-right:1px solid var(--hair);
  border-bottom:1px solid var(--hair)}
.reg a:nth-child(3n){border-right:none;padding-right:0}
.reg a:nth-last-child(-n+3){border-bottom:none}
@media(max-width:860px){
  .reg a{padding-right:20px}
  .reg a:nth-child(3n){border-right:1px solid var(--hair);padding-right:20px}
  .reg a:nth-child(2n){border-right:none;padding-right:0}
  .reg a:not(:nth-child(2n+1)){padding-left:var(--gut)}
  .reg a:nth-child(2n+1){padding-left:0}
  .reg a:nth-last-child(-n+3){border-bottom:1px solid var(--hair)}
  .reg a:nth-last-child(-n+2){border-bottom:none}}
@media(max-width:520px){
  .reg a{padding-left:0}
  .reg a,.reg a:nth-child(3n),.reg a:nth-child(2n){border-right:none;padding-right:0;
    border-bottom:1px solid var(--hair)}
  .reg a:last-child{border-bottom:none}}
.reg a:hover{background:var(--teal-wash)}
.reg .led .fig{font-size:var(--s5);letter-spacing:-.03em;line-height:1.05}
.reg a:hover .fig{color:var(--teal)}
.reg a:hover .lab{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
.reg .fig .unit{display:block;font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:var(--s0);font-weight:400;color:var(--steel-dim);letter-spacing:0;margin-top:2px;text-align:right}
.reg .d{display:block;font-size:var(--s1);color:var(--steel);margin-top:5px;line-height:1.45;
  max-width:34ch}

/* ── condition ────────────────────────────────────────────────────────── */
.cond{display:grid;grid-template-columns:1fr 1fr;gap:0 clamp(28px,5vw,64px);
  border-top:1px solid var(--hair);padding-top:12px}
@media(max-width:700px){.cond{grid-template-columns:1fr}}
.cond a{display:block;padding:8px 0;border-bottom:1px dotted var(--hair)}
.cond a:hover{background:var(--teal-wash)}
.cond a:hover .lab{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
.cond a:hover .fig{color:var(--teal)}
.cond .led .lab{font-weight:400;color:var(--ink)}
.cond .led .fig{font-size:var(--s4);line-height:1.2}
.cond .flag .fig{color:var(--amber)}
.cond .sums{grid-column:1/-1;margin:14px 0 0;padding:12px 0 0;border-top:1px solid var(--hair);
  color:var(--steel);font-size:var(--s1);max-width:74ch;line-height:1.55}
.cond .sums b{color:var(--ink);font-weight:600}

/* ── distributions ────────────────────────────────────────────────────── */
.dist{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--hair)}
@media(max-width:900px){.dist{grid-template-columns:1fr}}
.dist > div{padding:16px 22px 4px 0;border-right:1px solid var(--hair);display:flex;flex-direction:column}
.dist > div:not(:nth-child(3n+1)){padding-left:var(--gut)}
.dist > div:last-child{border-right:none;padding-right:0}
@media(max-width:900px){.dist > div{border-right:none;border-bottom:1px solid var(--hair);
  padding:16px 0 8px} .dist > div:last-child{border-bottom:none}}
.dist .cap{margin:0 0 14px;font-size:var(--s1);color:var(--steel);line-height:1.5;
  max-width:38ch;min-height:4.4em}
@media(max-width:900px){.dist .cap{min-height:0}}
a.bar{display:block;margin-bottom:2px;padding:5px 6px 6px;margin-left:-6px}
a.bar:hover{background:var(--teal-wash)}
a.bar .r{display:flex;align-items:baseline;gap:0;font-size:var(--s2);margin-bottom:4px}
a.bar .r .lead{flex:1 1 auto;min-width:14px;margin:0 10px;border-bottom:1px dotted var(--rule);
  transform:translateY(-.3em)}
a.bar .r span.k{color:var(--ink)}
a.bar:hover .r span.k{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
a.bar .r b{font-family:"IBM Plex Mono",monospace;font-weight:500;font-variant-numeric:tabular-nums;
  color:var(--steel);text-align:right;min-width:5.4ch}
a.bar:hover .r b{color:var(--teal)}
/* the bar answers the pointer too, so the row reads as a single door */
a.bar:hover .t i{background:var(--teal)}
a.bar:hover .t{background:var(--teal-pale)}
a.bar .t{display:block;height:4px;background:var(--hair)}
a.bar .t i{display:block;height:100%;background:var(--steel-dim)}
a.bar.lead .r span.k{font-weight:500}
a.bar.lead .r b{color:var(--teal)}
a.bar.lead .t i{background:var(--teal)}

/* ── tables, the list pages ───────────────────────────────────────────── */
/* ⚠️ THE SCROLL CONTAINER IS OFF ABOVE THE BREAKPOINT, and that is what lets the header stick.
   An element with overflow-x:auto becomes a scroll container on BOTH axes, because CSS turns a
   visible overflow-y into auto the moment the other axis is not visible. A sticky header inside
   it then pins to that box rather than to the viewport, and the box is exactly as tall as the
   table, so it never appears to stick at all. Above 760px the table already fits, so the
   container is not needed and the header sticks to the page. Below it the horizontal scroll
   comes back and sticky is given up, which is the honest trade. */
.scroll{overflow:visible}
table{border-collapse:collapse;width:auto;max-width:100%;font-size:var(--s2)}
@media(max-width:760px){
  .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;
    margin-right:calc(var(--pad) * -1);padding-right:var(--pad)}
  .scroll > table{width:max-content;min-width:100%}
  thead th{position:static !important}}
thead th{text-align:left;padding:7px 12px 7px 0;color:var(--steel);font-weight:600;font-size:var(--s0);
  border-bottom:1px solid var(--rule);white-space:nowrap;font-variant:normal}
tbody td{padding:9px 12px 9px 0;border-bottom:1px solid var(--hair);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--teal-wash)}
/* ══ THE COLUMN VOCABULARY. Four classes, used identically on every page. ═══
   nm    the row's own name. The widest thing in the table and the primary door.
   num   a figure. Right-aligned and tabular so a column of them lines up on the
         last digit, and shrunk to its content so it never leaves a gap.
   wrap  prose. Capped so a long note cannot stretch the whole table.
   (bare) a secondary value, left-aligned. */
/* ⚠️ no percentage width here. width:1% is the usual shrink-a-column trick, and it only works
   on a table that is already width:100%. On an auto-width table any percentage makes the table
   resolve against its container instead of its content, which is what was stretching it to the
   full viewport with the last column absorbing the slack. nowrap does the shrinking on its own. */
th.num,td.num{text-align:right;font-family:"IBM Plex Mono",monospace;
  font-variant-numeric:tabular-nums;white-space:nowrap}
td.nm{min-width:13ch}
th.nm,td.nm{padding-right:22px}
/* ⚠️ ONLY THE LAST COLUMN loses its right padding. Every cell already has padding-left:0, so a
   .num sitting mid-table with padding-right:0 had no gutter on either side and ran straight into
   its neighbour. 'lines' + 'library_id' rendered as one column reading 86Q4116639, and 'parents'
   + 'children' turned 1 and 2 into 12. Five tables were affected, not just the catalog. */
/* ⚠️ the last numeric column keeps its trailing space too. This used to be zeroed so a figure sat
   flush with the right edge of a full-width table. The table is content-width now, so there is no
   edge to sit against and the zero only made the last column read tighter than every other. */

/* ══ THE EXPLAINED PAGE ════════════════════════════════════════════════════
   Every page says what it is, how many, and what table it reads. Every column
   says what it holds in plain words and which stored column that is. The labels
   stay accurate and the explanation does the work. */
.phead{margin-bottom:clamp(16px,2.4vw,22px);padding-top:clamp(6px,1vw,12px)}
.phead .row{display:flex;align-items:flex-end;gap:26px;flex-wrap:wrap;max-width:var(--chart)}
.phead h1{margin:0;flex:none}
.phead .tally{margin-left:auto;display:flex;align-items:baseline;gap:9px;padding-bottom:2px}
.phead .tally .v{font-family:"IBM Plex Mono",monospace;font-size:var(--s5);font-weight:500;
  color:var(--teal);letter-spacing:-.028em;line-height:1;font-variant-numeric:tabular-nums}
.phead .tally .l{font-size:var(--s1);color:var(--steel)}
.phead .tally .l b{font-family:"IBM Plex Mono",monospace;font-weight:500;color:var(--ink)}
.phead .ident,.ident{margin:5px 0 0;font-size:var(--s1);color:var(--steel-dim)}
.phead .about{margin:13px 0 0;font-size:var(--s2);color:var(--steel);line-height:1.65;max-width:80ch}
.phead .about + .about{margin-top:9px}
.phead .about b{color:var(--ink);font-weight:500}
.phead .about .ex{color:var(--ink)}

/* the glossed column head. Three lines, each quieter than the one above it. */
/* ⚠️ the whole header reads left to right, numeric columns included. A right-aligned gloss
   wraps into a ragged block and the column names stop sharing a baseline. Only the DATA in a
   numeric column stays right-aligned. */
/* ⚠️ sticky, and still the containing block for the hover gloss. position:sticky establishes one
   the same way relative does, so the tooltip keeps positioning against its own header cell. */
thead th{vertical-align:top;padding-bottom:10px;text-align:left;position:sticky;top:0;z-index:5;
  background:var(--surface)}
thead th::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;
  background:var(--rule)}
/* a numeric header sits over its figures. This was left-aligned while the plain-English gloss
   printed under it and wrapped into a ragged block. The gloss moved to hover, so the header is
   two short lines again and can align with the column it labels. */
thead th.num{text-align:right;font-family:"IBM Plex Sans",system-ui,sans-serif}
thead th.num .db{text-align:right;max-width:none}
thead th.num .gl{left:auto;right:0;text-align:left}
/* the column NAME and the stored column stay on the page. The sentence explaining the column is
   one hover or one tab away, so the header stays two quiet lines instead of four. */
thead th .hd{border-bottom:1px dotted var(--rule);cursor:help}
thead th .hd:hover,thead th .hd:focus-visible{color:var(--teal);border-bottom-color:var(--teal);
  outline:none}
/* ⚠️ wraps at spaces, never inside a word. With overflow-wrap:anywhere a shrink-to-content
   numeric column broke 'kind_of, made_from' into 'kind_o f, made_f rom'. A stored column name
   split mid-token is worse than a wide column, since the point of the line is to be copyable. */
thead th .db{display:block;font-family:"IBM Plex Mono",monospace;font-size:10px;line-height:1.4;
  color:var(--steel-dim);font-weight:400;margin-top:4px;letter-spacing:0;white-space:normal;
  max-width:24ch;text-align:left;overflow-wrap:normal;word-break:normal}
/* ⚠️ IT SITS OVER THE FIRST ROW AND HAS TO LOOK LIKE IT. The header is sticky at the top of the
   viewport, so there is no room to place the sentence above it, and a tooltip that drops into the
   data with no edge reads as text printed onto the row rather than a layer over it. The shadow
   and the hairline are what separate the two. Narrower than before so it stays near the column it
   belongs to instead of spanning three of them. */
thead th .gl{position:absolute;left:0;top:calc(100% + 2px);z-index:30;width:max-content;
  font-family:"IBM Plex Sans",system-ui,sans-serif;
  max-width:230px;font-size:11px;line-height:1.5;font-weight:400;color:var(--surface);
  background:var(--ink);padding:8px 11px;text-align:left;white-space:normal;letter-spacing:0;
  border:1px solid rgba(255,255,255,.14);box-shadow:0 6px 20px rgba(11,20,26,.30);
  opacity:0;pointer-events:none;transition:opacity .1s ease}
/* the last two columns open leftward so the sentence cannot run off the edge of the page */
thead th:nth-last-child(-n+2) .gl{left:auto;right:0}
thead th .hd:hover ~ .gl,thead th .hd:focus-visible ~ .gl{opacity:1}
@media(prefers-reduced-motion:reduce){thead th .gl{transition:none}}

td.nm a{font-weight:500}
tbody tr:hover td.nm a{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
/* ⚠️ every link in a cell announces itself under the pointer, not just the row's own name. The
   category cell was a real door that looked exactly like plain text. */
tbody td a:hover{color:var(--teal);text-decoration:underline;text-underline-offset:2px}
td.wrap{max-width:52ch}
.dimc{color:var(--steel)}
.tag{display:inline-block;font-size:var(--s0);padding:1px 7px;border:1px solid var(--hair);
  color:var(--steel);white-space:nowrap}
.tag.teal{border-color:var(--teal-pale);color:var(--teal);background:var(--teal-wash)}
.tag.amber{border-color:#E7CFAE;color:var(--amber);background:var(--amber-wash)}
/* A door keeps the weight of the value it sits on and picks up teal only under the pointer.
   Counts link to the SET they count, names to the RECORD they name. Zero is never a door. */
a.tag:hover{border-color:var(--teal);color:var(--teal);background:var(--teal-wash)}
td.num a{color:inherit;border-bottom:1px solid transparent}
td.num a:hover{color:var(--teal);border-bottom-color:var(--teal-pale)}
.dimc a{color:inherit}
.dimc a:hover{color:var(--teal)}
.zero{color:#AFBAC1}
/* ⚠️ ONE BAR PER ROW, AND IT IS NOT A gauge(). A gauge partitions a total, and these shares do
   not: a recipe carries many ingredients, so a dish's shares sum well past 100%. This reads as a
   rule against its own row rather than a slice of a whole, which is the honest shape for it.
   Drawn at the same teal the rest of the bench uses for meaning, and it carries no text of its
   own because the share is already in the column beside it. */
td.bar{width:120px;padding-right:14px}
.minibar{display:block;height:5px;background:var(--hair);position:relative}
.minibar>span{position:absolute;left:0;top:0;bottom:0;background:var(--teal-mid);min-width:1px}
tr:hover .minibar>span{background:var(--teal)}
.ctx{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin:0 0 14px;font-size:var(--s1);
  color:var(--steel);border-left:3px solid var(--teal);padding:7px 12px;background:var(--teal-wash)}
.ctx b{color:var(--ink);font-weight:600}
.ctx a.clear{margin-left:auto;color:var(--steel);border-bottom:1px solid var(--hair)}
.ctx a.clear:hover{color:var(--teal);border-bottom-color:var(--teal)}

.filters{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:0 0 16px}
.filters a{padding:3px 11px;border:1px solid var(--hair);font-size:var(--s1);color:var(--steel)}
.filters a:hover{border-color:var(--teal);color:var(--teal)}
.filters a.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.filters form{margin:0;display:flex;gap:6px}
.filters input{padding:3px 10px;border:1px solid var(--hair);font-size:var(--s1);width:210px;
  font-family:inherit;color:var(--ink)}
.filters input:focus{outline:2px solid var(--teal);outline-offset:1px}
.filters .lbl{font-size:var(--s1);color:var(--steel);margin-right:2px}

/* ── per-column refine, and the bar saying what is on ─────────────────────
   The controls sit above the table rather than inside the header row. A control in a sticky
   header would fight the gloss tooltip for the same few pixels, and a select inside a th
   cannot be reached at all once the header sticks. */
.refine{margin:0 0 14px;max-width:var(--chart)}
.rf{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:flex-end;margin-bottom:8px}
.rf:last-child{margin-bottom:0}
.rf label{display:flex;flex-direction:column;gap:3px}
.rf label > span{font-size:var(--s0);color:var(--steel)}
.rf input,.rf select{padding:4px 9px;border:1px solid var(--hair);font-size:var(--s1);
  font-family:inherit;color:var(--ink);background:var(--surface)}
.rf input{width:200px}
.rf input:focus,.rf select:focus{outline:2px solid var(--teal);outline-offset:1px}
.rf button{padding:5px 15px;border:1px solid var(--ink);background:var(--ink);color:#fff;
  font-family:inherit;font-size:var(--s1);cursor:pointer}
.rf button:hover{background:var(--teal);border-color:var(--teal)}

.active{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:0 0 14px;
  padding:9px 0;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
.active .lbl{font-size:var(--s1);color:var(--steel)}
.active .chip{display:inline-flex;align-items:baseline;gap:6px;padding:3px 9px;
  border:1px solid var(--teal);color:var(--teal);font-size:var(--s1);background:var(--teal-wash)}
.active .chip b{font-weight:400;color:var(--steel)}
.active .chip i{font-style:normal;color:var(--steel-dim);font-size:var(--s2)}
.active .chip:hover{background:var(--teal);color:#fff;border-color:var(--teal)}
.active .chip:hover b,.active .chip:hover i{color:#fff}
.active .clr{font-size:var(--s1);color:var(--steel);text-decoration:underline;
  text-underline-offset:2px}
.active .clr:hover{color:var(--amber)}
.active .res{margin-left:auto;font-family:"IBM Plex Mono",monospace;font-size:var(--s1);
  color:var(--steel);font-variant-numeric:tabular-nums}

/* the sort affordance on a column header */
thead th a.hd{color:inherit;display:inline-flex;align-items:baseline;gap:5px}
thead th a.hd:hover{color:var(--teal);text-decoration:underline;text-underline-offset:3px}
thead th a.hd .ar{font-style:normal;font-size:var(--s0);color:var(--steel-dim);
  width:7px;display:inline-block}
thead th a.hd.sorted{color:var(--teal)}
thead th a.hd.sorted .ar{color:var(--teal)}
thead th.num a.hd{flex-direction:row-reverse}

.pager{display:flex;gap:6px;align-items:center;margin:18px 0 0;font-size:var(--s1);flex-wrap:wrap}
.pager a,.pager span{padding:4px 10px;border:1px solid var(--hair)}
.pager span.cur{background:var(--ink);color:#fff;border-color:var(--ink)}
.pager span.gap{border:none;color:var(--steel)}
.pager a:hover{border-color:var(--teal);color:var(--teal)}

/* ── the decision controls, the only place this instrument writes ──────────
   Two buttons, sized to the row rather than to themselves. Teal for the confirm because teal
   carries meaning here as everywhere else, amber for the reject because amber is what this
   instrument already uses for the unbound and the set-aside. Neither is a colour of alarm. */
.act{display:flex;gap:6px;justify-content:flex-end;align-items:baseline}
.act form{margin:0;display:inline}
.act button{padding:2px 9px;border:1px solid var(--hair);background:var(--surface);
  color:var(--steel);font-family:inherit;font-size:var(--s0);cursor:pointer;line-height:1.6}
.act button:hover{border-color:var(--teal);color:var(--teal);background:var(--teal-wash)}
.act button.no:hover{border-color:#E7CFAE;color:var(--amber);background:var(--amber-wash)}
.act .held{font-size:var(--s0);color:#AFBAC1}

/* the authored-row form. Wider than a refine control because an id is longer than a filter. */
.authored{border:1px solid var(--hair);padding:14px 16px;margin:0 0 18px;max-width:var(--chart)}
.authored h3{margin:0 0 4px}
.authored p{margin:0 0 11px;font-size:var(--s1);color:var(--steel);line-height:1.55;max-width:74ch}

.empty{padding:16px 0;color:var(--steel);font-size:var(--s2);border-top:1px solid var(--hair)}
.note{font-size:var(--s1);color:var(--steel);margin-top:6px;line-height:1.5}
.banner{border-left:3px solid var(--amber);background:var(--amber-wash);padding:11px 14px;
  margin:0 0 16px;font-size:var(--s2);line-height:1.55;max-width:82ch}
.banner b{font-weight:600}
.banner.ok{border-left-color:var(--teal);background:var(--teal-wash)}
.prose p{margin:0 0 12px;max-width:70ch;line-height:1.65}
.prose .meta{font-size:var(--s0);color:var(--steel);margin:-8px 0 14px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 18px;font-size:var(--s2);margin:0}
.kv dt{color:var(--steel);font-size:var(--s1);padding-top:1px} .kv dd{margin:0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:0 clamp(28px,5vw,56px)}
@media(max-width:820px){.two{grid-template-columns:1fr;gap:var(--pad) 0}}
#net{height:620px;border:1px solid var(--rule);background:var(--surface)}
footer{padding:clamp(20px,3vw,28px) var(--pad);border-top:1px solid var(--rule)}
footer p{margin:0;font-size:var(--s1);color:var(--steel);max-width:74ch;line-height:1.6}
@media(prefers-reduced-motion:no-preference){a,tbody tr{transition:background .12s ease,color .12s ease}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600'
         '&family=IBM+Plex+Sans:wght@400;450;500;600&display=swap" rel="stylesheet">')


def counts(c):
    q = lambda s: c.execute(s).fetchone()[0]
    return {
        "catalog": q("SELECT COUNT(*) FROM library_names"),
        "entries": q("SELECT COUNT(*) FROM library_entries"),
        "categories": q("SELECT COUNT(*) FROM library_categories"),
        "relations": q("SELECT COUNT(*) FROM library_relations"),
        "links": q("SELECT COUNT(*) FROM recipe_ingredients WHERE catalog_id IS NOT NULL"),
        "recipes": q("SELECT COUNT(*) FROM recipes"),
        "subs": q("SELECT COUNT(*) FROM mined_substitution_candidates"),
        # ⚠️ GUARDED, unlike the rest. The dish tables arrive in migration 038 and 039, they are
        #    derived from a corpus that is not in the repo, and empty is their normal state in a
        #    clone. A bare COUNT here would take the whole viewer down on a database that simply
        #    has not been migrated yet.
        "dishes": q("SELECT COUNT(*) FROM mined_dish") if has_dishes(c) else 0,
    }


def has_table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (name,)).fetchone())


# ⚠️ EVERY TABLE THE DISH PAGES TOUCH, NOT JUST THE FIRST ONE. The guard used to ask for
#    mined_dish alone, and migrations 038 and 039 arrive separately. A database with 038 applied
#    and 039 not, which is exactly what the live catalog is right now, passed the guard and then
#    500'd on mined_dish_ingredient. Caught by running the viewer against the live database
#    rather than only against the loaded copy.
DISH_TABLES = ("mined_dish", "mined_dish_form", "mined_dish_method", "mined_dish_diet",
               "mined_dish_structural", "mined_dish_appliance", "mined_dish_base",
               "mined_dish_accompaniment", "mined_dish_ingredient")


def has_dishes(c):
    return all(has_table(c, t) for t in DISH_TABLES)


NAV = [("/", "Condition", None), ("/catalog", "Catalog", "catalog"),
       ("/entries", "Entries", "entries"), ("/categories", "Categories", "categories"),
       ("/relations", "Relations", "relations"), ("/links", "Recipe links", "links"),
       ("/recipes", "Recipes", "recipes"), ("/dishes", "Dishes", "dishes"),
       ("/substitutions", "Substitutions", "subs"),
       ("/uncovered", "Not covered", None), ("/search", "Search", None)]


def page(title, body, active="/", crumbs=(), head="", n=None):
    c = db()
    n = n or counts(c)
    st = os.stat(DB)
    h = hashlib.sha256(open(DB, "rb").read()).hexdigest()[:16]
    c.close()
    unbound = n.get("_unbound")
    items = ""
    for href, label, key in NAV:
        cur = ' aria-current="page"' if href == active else ""
        val = ""
        if key == "links":
            val = f"<var>{fmt(n['links'])}</var>"
        elif key:
            val = f"<var>{fmt(n[key])}</var>"
        elif label == "Not covered" and unbound is not None:
            val = f"<var>{fmt(unbound)}</var>"
        items += f'<a href="{href}"{cur}>{escape(label)} {val}</a>'
    cr = ""
    if crumbs:
        parts = ['<a href="%s">%s</a>' % (href, escape(lab)) if href else
                 '<span>%s</span>' % escape(lab) for lab, href in crumbs]
        cr = '<div class=crumb>' + '<i>/</i>'.join(parts) + '</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{escape(title)} · library bench</title>
<meta name="viewport" content="width=device-width,initial-scale=1">{FONTS}
<style>{CSS}</style>{head}</head><body><div class=shell>
<div class=rail>
  <div class=mark><b>Library bench</b><span>read-only instrument</span></div>
  <nav aria-label="Registers">{items}</nav>
  <div class=tail>Queries run per request.<br>Nothing is cached.<br>
    The database is never written.</div>
</div>
<main>
  <div class=readout>
    <div class=f><label>mounted</label><div class="v mono">{escape(DB)}</div></div>
    <div class=f><label>sha256</label><div class="v mono">{h}</div></div>
    <div class=f><label>size</label><div class="v mono">{st.st_size/1e6:.1f} MB</div></div>
    <div class=f><label>revised</label><div class=v>{time.strftime('%-d %b %Y, %H:%M', time.localtime(st.st_mtime))}</div></div>
    <div class=f><label>mode</label><div class=v><span class=live>read-only</span></div></div>
    <div class=f><label>writes</label><div class="v mono">{escape(HAND)}</div></div>
  </div>{cr}{body}
  <footer><p>Every figure on this panel is counted at the moment it is read. The database is
    opened read-only, so nothing here can alter what it measures.</p></footer>
</main></div></body></html>"""


# ── components ──────────────────────────────────────────────────────────────

def led(label, figure, href=None, cls="", gloss="", unit=""):
    """⚠️ THE UNIT RIDES WITH THE FIGURE. Six registers rendered identically put 10,474 next to
    10,192 and invited a comparison that means nothing: one counts names, the other counts edges
    between names. A catalog could double its names without gaining a single edge. The unit is
    the fix, not a chart, because there is no relationship to chart."""
    u = f'<span class=unit>{escape(unit)}</span>' if unit else ""
    inner = (f'<span class=led><span class=lab>{label}</span><span class=lead></span>'
             f'<span class=fig>{figure}{u}</span></span>')
    if gloss:
        inner += f'<span class=d>{gloss}</span>'
    return f'<a class="{cls}" href="{href}">{inner}</a>' if href else f'<div class="{cls}">{inner}</div>'


def uq(v):
    """Percent-encode a value for a URL.

    ⚠️ escape() is for TEXT and does not touch URL syntax. Four library_ids carry a '#'
    (en:Guinness:noun#0 and three others) and three carry a space, so an id dropped raw into an
    href truncated at the fragment and the link died silently. Nothing in the catalog carries a
    '/', which is why encoding the whole value is safe for the path as well as the query.
    """
    return quote(str(v or ""), safe="")


def ilink(lid, label=None):
    return f'<a href="/i/{uq(lid)}">{escape(label or lid)}</a>'


def dlink(did, label=None):
    return f'<a href="/dish/{uq(did)}">{escape(label or did)}</a>'


def clink(cid, label=None):
    return f'<a href="/c/{uq(cid)}">{escape(label or cid)}</a>'


def elink(eid, label=None):
    return f'<a href="/e/{uq(eid)}">{escape(label or eid)}</a>'


def rlink(rid, label=None):
    return f'<a href="/r/{uq(rid)}">{escape(label or rid)}</a>'


def plink(kind, pid, label=None):
    """⚠️ GOTCHA 1. A parent is a category on an in-category edge and a catalog row on any other.

    'bread' and 'pasta' are the same string in both tables, so the destination has to be chosen
    by the edge's kind rather than by the id.
    """
    return clink(pid, label) if kind == "in_category" else ilink(pid, label)


# ⚠️ Keyed by (column, value), never by value alone. 'read' is 169 rows as a confidence and 22
#    as a source, and it does not mean the same thing in the two places.
NAMES = {
    ("kind", "kind_of"):     "is a kind of",
    ("kind", "in_category"): "is in category",
    ("kind", "made_from"):   "is made from",
    ("kind", "hierarchy"):   "is a kind of, or made from",
    ("confidence", "high"):     "the source stated it",
    ("confidence", "picked"):   "picked by hand",
    ("confidence", "read"):     "read off a page",
    ("confidence", "authored"): "written by hand",
    ("source", "wikidata"):        "Wikidata",
    ("source", "off"):             "Open Food Facts",
    ("source", "read"):            "a page that was read",
    ("source", "prose"):           "the written entry",
    ("source", "possible_parent"): "a proposed parent",
    ("link_state", "linked"):          "linked",
    ("link_state", "no_library_id"):   "no catalog row",
    ("link_state", "canonical_drift"): "the name has drifted",
    ("link_confidence", "exact"):      "the name matched exactly",
    ("link_confidence", "form_strip"): "matched after a form word was dropped",
    ("link_confidence", "repoint"):    "re-pointed by hand",
    ("link_confidence", "decided"):    "settled by an earlier decision",
    ("assertion_kind", "claim"):       "claim",
    ("assertion_kind", "safety_flag"): "safety flag",
}


def human(col, val):
    """The readable name for a stored value. Falls back to the value with its underscores out."""
    return NAMES.get((col, val), (val or "").replace("_", " "))


def tag(text, cls=""):
    return f'<span class="tag {cls}">{escape(text)}</span>' if text else ""


def taglink(text, href, cls=""):
    """A tag that is also a door back to the filtered set it names."""
    return f'<a class="tag {cls}" href="{href}">{escape(text)}</a>' if text else ""


def cnt(n, href=None):
    """A count links to the set it counts. Zero names an empty set, so it is not a door."""
    if not n:
        return '<span class=zero>0</span>'
    return f'<a href="{href}">{fmt(n)}</a>' if href else fmt(n)


SEG = ["var(--teal)", "var(--teal-mid)", "var(--steel-dim)", "var(--rule)", "#C8D6DA", "#E1E8EA"]


def gauge(parts, total, whole_label=""):
    """A segmented bar where every segment is a door. parts: [(label, value, href)].

    ⚠️ THE PARTS MUST SUM TO THE TOTAL. A gauge whose segments do not partition is a false claim
    about the data, and the map that produced these found two candidates that failed exactly that
    test: catalog bare/used/written double-counts because a row can be both, and rows-by-hierarchy
    misses `bread`, the one row that is only ever an in-category parent. This refuses to draw
    rather than manufacture a relationship, so a later breakdown cannot quietly slip through.
    """
    got = sum(v for _, v, _ in parts)
    if got != total:
        raise AssertionError(f"gauge parts sum to {got}, not {total}. It does not partition, "
                             f"so it must not be charted.")
    bars, keys = "", ""
    for i, (label, value, href) in enumerate(parts):
        bg = SEG[i % len(SEG)]
        # ⚠️ flex is the raw count. A segment of 4 against 10,192 renders as a hairline, and that
        #    sliver is the honest picture. It is not padded to be visible.
        bars += (f'<a href="{href}" style="background:{bg};flex:{value}" '
                 f'aria-label="{escape(label)}, {fmt(value)}"></a>')
        pct = (value / total * 100) if total else 0
        keys += (f'<a href="{href}"><em style="background:{bg}"></em>'
                 f'<span class=lab>{escape(label)}</span><b>{fmt(value)}</b>'
                 f'<span class=lead></span><span class=pc>{pct:.1f}%</span></a>')
    aria = ", ".join(f"{escape(l)} {fmt(v)}" for l, v, _ in parts)
    # the set the bar is drawn over, stated on the bar. A chart sitting above a filtered table
    # has to say which of the two it describes.
    cap = f'<p class=gcap>{escape(whole_label)}</p>' if whole_label else ""
    return (f'<div class=pgauge>{cap}<div class=track role="img" aria-label="{aria}">{bars}</div>'
            f'<div class=keys>{keys}</div></div>')


def entry_sources(c, entry_id):
    """key -> [(slug, url)] for one entry, in one query.

    ⚠️ A CITATION THAT CANNOT BE FOLLOWED IS NOT A CITATION. 337 of the 402 claims and prose
    pieces in the library reach a real URL through library_chains, and the page was printing the
    slug as flat text, so checking one meant querying the database by hand. Sources without a URL
    stay flat text rather than becoming a dead link: one slug, `repo: weights.py`, is a pointer
    into this repo and is not a place on the web."""
    out = {}
    for r in c.execute(
            "SELECT ch.key, ch.source_slug, s.url FROM library_chains ch "
            "LEFT JOIN library_sources s ON s.source_slug=ch.source_slug "
            "WHERE ch.entry_id=? ORDER BY ch.position", (entry_id,)):
        out.setdefault(r["key"], []).append((r["source_slug"], r["url"]))
    return out


def srclink(slug, url):
    """One source. A link when there is somewhere to go, plain text when there is not."""
    if not url or not str(url).startswith("http"):
        return f'<span class="src dimc">{escape(slug)}</span>'
    return (f'<a class=src href="{escape(url)}" target="_blank" rel="noopener noreferrer" '
            f'title="{escape(url)}">{escape(slug)}</a>')


def srcbits(pairs):
    return " ".join(srclink(sl, u) for sl, u in pairs) if pairs else ""


def phead(title, n, unit, table_name, about, said=None, of=None):
    """The head every list page shares. Title, a count scoped to the filters, the table it
    reads, and a paragraph saying what the page is. `about` may hold several <p class=about>."""
    tally = (f'<span class=tally><span class=v>{fmt(n)}</span>'
             f'<span class=l>{"of <b>" + fmt(of) + "</b> " if of is not None else ""}{escape(unit)}'
             f'</span></span>')
    body = said if said else f'<p class=about>{about}</p>'
    return (f'<div class=phead><div class=row><h1>{escape(title)}</h1>{tally}</div>'
            f'<p class=ident>read from <span class=mono>{escape(table_name)}</span></p>'
            f'{body}</div>')


def ctx(bits, clear=None):
    """The strip naming what a filtered view is showing, with the way back out."""
    if not bits:
        return ""
    inner = " ".join(bits)
    out = f'<div class=ctx><span>{inner}</span>'
    if clear:
        out += f'<a class=clear href="{clear}">show all</a>'
    return out + "</div>"


def table(headers, rows, aligns=None, empty="Nothing here."):
    if not rows:
        return f'<div class=empty>{escape(empty)}</div>'
    aligns = aligns or [""] * len(headers)
    # a header is either a bare string or (name, plain gloss, stored column).
    def head_cell(x, a):
        if isinstance(x, (tuple, list)):
            nm, gl, db, sk = (list(x) + ["", "", None])[:4]
            # ⚠️ A SORTABLE HEADER IS A LINK, NOT A BUTTON. The whole tool works with the URL as
            #    the state, so a sort has to survive a copy-paste and a page change like every
            #    other control here. Clicking the active column flips the direction.
            cur, cdir = request.args.get("sort") or "", request.args.get("dir") or ""
            if sk:
                nxt = "asc" if (cur == sk and cdir == "desc") else ("desc" if cur == sk else "asc")
                arrow = (f'<i class=ar aria-hidden="true">{"↑" if cdir != "desc" else "↓"}</i>'
                         if cur == sk else '<i class=ar aria-hidden="true"></i>')
                on = " sorted" if cur == sk else ""
                label = (f'<a class="hd{on}" href="{qs(sort=sk, dir=nxt, page=None)}"'
                         + (f' aria-describedby="g{abs(hash((nm, db, gl))) % 10**8}"' if gl else "")
                         + f' aria-sort="{"descending" if cdir == "desc" else "ascending"}"'
                           f'>{escape(nm)}{arrow}</a>')
            else:
                label = (f'<span class=hd tabindex="0" '
                         f'aria-describedby="g{abs(hash((nm, db, gl))) % 10**8}">{escape(nm)}</span>'
                         if gl else escape(nm))
            gid = f"g{abs(hash((nm, db, gl))) % 10**8}"
            return (f'<th class="{a}">{label}'
                    + (f'<span class=db>{escape(db)}</span>' if db else "")
                    + (f'<span class=gl id="{gid}" role="tooltip">{escape(gl)}</span>' if gl else "")
                    + '</th>')
        return f'<th class="{a}">{escape(x)}</th>'
    h = "".join(head_cell(x, a) for x, a in zip(headers, aligns))
    b = "".join("<tr>" + "".join(f'<td class="{a}">{cell}</td>' for cell, a in zip(r, aligns))
                + "</tr>" for r in rows)
    # ⚠️ the scroller is the table's own, not the page's. A seven-column table cannot fit 375px,
    #    and without this the last columns are simply unreachable rather than scrollable.
    return (f'<div class=scroll><table><thead><tr>{h}</tr></thead>'
            f'<tbody>{b}</tbody></table></div>')


def qs(**over):
    args = {k: v for k, v in request.args.items()}
    args.update(over)
    args = {k: v for k, v in args.items() if v not in (None, "")}
    return ("?" + "&".join(f"{k}={uq(v)}" for k, v in args.items())) if args else ""


def pager(page_no, total, base):
    n = max(1, math.ceil(total / PER))
    if n <= 1:
        return f'<div class=pager><span class=gap>{fmt(total)} rows</span></div>'
    out = []
    if page_no > 1:
        out.append(f'<a href="{base}{qs(page=page_no-1)}">prev</a>')
    show = sorted({1, n} | set(range(max(1, page_no - 2), min(n, page_no + 2) + 1)))
    last = 0
    for p in show:
        if p - last > 1:
            out.append('<span class=gap>…</span>')
        out.append(f'<span class=cur>{p}</span>' if p == page_no
                   else f'<a href="{base}{qs(page=p)}">{p}</a>')
        last = p
    if page_no < n:
        out.append(f'<a href="{base}{qs(page=page_no+1)}">next</a>')
    out.append(f'<span class=gap>{fmt(total)} rows</span>')
    return f'<div class=pager>{"".join(out)}</div>'


def filters(base, key, options, current, label=""):
    out = [f'<span class=lbl>{escape(label)}</span>'] if label else []
    for val, lab in options:
        args = {k: v for k, v in request.args.items() if k not in (key, "page")}
        if val:
            args[key] = val
        q = ("?" + "&".join(f"{k}={uq(v)}" for k, v in args.items())) if args else ""
        on = " on" if (current or "") == (val or "") else ""
        out.append(f'<a class="{on.strip()}" href="{base}{q}">{escape(lab)}</a>')
    return "".join(out)


def searchbox(placeholder="filter by name", keep=()):
    hidden = "".join(f'<input type=hidden name={k} value="{escape(request.args.get(k,""))}">'
                     for k in keep if request.args.get(k))
    return (f'<form><input type=search name=q placeholder="{escape(placeholder)}" '
            f'value="{escape(request.args.get("q",""))}">{hidden}</form>')


# ════════════════════════════════════════════════════════════════════════════
#  SHARED QUERIES. The six gotcha handlers live here.
# ════════════════════════════════════════════════════════════════════════════

def entry_state(conn, e):
    """⚠️ GOTCHA 3. Compute the link state NOW. Never trust the stored field.

    link_state is written when the entry is loaded and no rename since re-runs the reconcile, so a
    renamed row leaves a stale value. Live is 51 linked / 2 drift / 3 no-row against a stored
    52 / 1 / 3: strained-yogurt was renamed to Greek yogurt after the load and the field has not
    caught up. The two disagreeing is exactly what a verification tool exists to surface.
    """
    if not e["library_id"]:
        return "no_library_id", None, "the entry carries no library_id"
    row = conn.execute("SELECT canonical FROM library_names WHERE library_id=?",
                       (e["library_id"],)).fetchone()
    if not row:
        return "DANGLING", None, "library_id does not resolve in library_names"
    live = row["canonical"]
    if e["library_canonical"] and norm(live) != norm(e["library_canonical"]):
        return "canonical_drift", live, f"snapshot {e['library_canonical']!r}, live {live!r}"
    return "linked", live, None


def entry_states(conn):
    """Every entry's computed state, plus the disagreements with the stored field."""
    computed, stored, dis = {}, {}, []
    for e in conn.execute("SELECT * FROM library_entries"):
        s, live, why = entry_state(conn, e)
        computed[s] = computed.get(s, 0) + 1
        stored[e["link_state"]] = stored.get(e["link_state"], 0) + 1
        if s != e["link_state"]:
            dis.append((e["entry_id"], e["link_state"], s, why))
    return computed, stored, dis


def neighbourhood(conn, lid):
    """⚠️ GOTCHA 1 and 6. kind is constrained on every branch; parents deduped by row.

    parent_id holds either a library_id or a category slug. 'bread' and 'pasta' exist in BOTH
    tables under the same string, so a join without a kind constraint mixes them silently. And a
    child can carry both a kind_of and a made_from edge to one parent, which would draw twice.
    """
    out = {"category": [], "parent": [], "child": [], "sibling": []}
    for r in conn.execute(
            "SELECT lc.category_id id, lc.name label, r.confidence, r.source "
            "FROM library_relations r JOIN library_categories lc ON lc.category_id=r.parent_id "
            "WHERE r.child_id=? AND r.kind='in_category'", (lid,)):
        out["category"].append(dict(r))
    seen = {}
    for r in conn.execute(
            "SELECT ln.library_id id, ln.canonical label, r.kind, r.confidence, r.source "
            "FROM library_relations r JOIN library_names ln ON ln.library_id=r.parent_id "
            "WHERE r.child_id=? AND r.kind IN ('kind_of','made_from')", (lid,)):
        d = seen.setdefault(r["id"], {"id": r["id"], "label": r["label"], "kinds": [],
                                      "confidence": r["confidence"], "source": r["source"]})
        d["kinds"].append(r["kind"])
    out["parent"] = list(seen.values())
    kids = {}
    for r in conn.execute(
            "SELECT ln.library_id id, ln.canonical label, r.kind, r.confidence "
            "FROM library_relations r JOIN library_names ln ON ln.library_id=r.child_id "
            "WHERE r.parent_id=? AND r.kind IN ('kind_of','made_from') ORDER BY ln.canonical", (lid,)):
        d = kids.setdefault(r["id"], {"id": r["id"], "label": r["label"], "kinds": [],
                                      "confidence": r["confidence"]})
        d["kinds"].append(r["kind"])
    out["child"] = list(kids.values())
    # the shared parent is named, not just identified. ⚠️ GOTCHA 1 decides which table holds the
    # name: an in-category edge is a category slug, anything else is a catalog row.
    for r in conn.execute(
            "SELECT DISTINCT ln.library_id id, ln.canonical label, m.kind, m.parent_id via, "
            " COALESCE(CASE WHEN m.kind='in_category' THEN lc.name ELSE pn.canonical END, m.parent_id) via_label "
            "FROM library_relations m "
            "JOIN library_relations s ON s.parent_id=m.parent_id AND s.kind=m.kind "
            "  AND s.child_id<>m.child_id "
            "JOIN library_names ln ON ln.library_id=s.child_id "
            "LEFT JOIN library_names pn ON pn.library_id=m.parent_id "
            "LEFT JOIN library_categories lc ON lc.category_id=m.parent_id "
            "WHERE m.child_id=? ORDER BY ln.canonical", (lid,)):
        out["sibling"].append(dict(r))
    return out


def category_members(conn, cid):
    """⚠️ GOTCHA 4. A category can be reached two ways and both must be gathered.

    'legume' has children on the slug AND on the catalog row Q145909 that shares its name.
    Asking only about the slug understates the membership by about two fifths.
    """
    rows, seen = [], set()
    for r in conn.execute(
            "SELECT ln.library_id id, ln.canonical label, r.confidence, r.source "
            "FROM library_relations r JOIN library_names ln ON ln.library_id=r.child_id "
            "WHERE r.parent_id=? AND r.kind='in_category'", (cid,)):
        seen.add(r["id"]); rows.append(dict(r, via="in_category"))
    cat = conn.execute("SELECT name FROM library_categories WHERE category_id=?", (cid,)).fetchone()
    twin = None
    if cat:
        for t in conn.execute("SELECT library_id FROM library_names WHERE canonical=? COLLATE NOCASE",
                              (cat["name"],)):
            twin = t["library_id"]
            for r in conn.execute(
                    "SELECT ln.library_id id, ln.canonical label, r.confidence, r.source "
                    "FROM library_relations r JOIN library_names ln ON ln.library_id=r.child_id "
                    "WHERE r.parent_id=? AND r.kind='kind_of'", (twin,)):
                if r["id"] not in seen:
                    seen.add(r["id"]); rows.append(dict(r, via="kind_of on the catalog row"))
    rows.sort(key=lambda x: x["label"].lower())
    return rows, twin


def coverage(conn):
    """The gauge. Scope is every non-heading recipe line."""
    q = lambda s: conn.execute(s).fetchone()[0]
    scope = q("SELECT COUNT(*) FROM recipe_ingredients WHERE is_heading=0")
    bound = q("SELECT COUNT(*) FROM recipe_ingredients WHERE catalog_id IS NOT NULL")
    entry = q("SELECT COUNT(*) FROM recipe_ingredients ri "
              "JOIN library_entries le ON le.library_id = ri.catalog_id")
    return {"scope": scope, "bound": bound, "entry": entry,
            "row": bound - entry, "unbound": scope - bound,
            "pct": (bound / scope * 100) if scope else 0}


REASONS = {
    "UNMATCHED": ("no catalog row", "The parsed name reached nothing the catalog holds."),
    "AMBIGUOUS": ("refused, several rows", "The name is held by more than one row, so binding it "
                                           "would have been a guess. Phase C merges release these."),
    "NOT_AN_INGREDIENT": ("not an ingredient", "The line parses to nothing nameable: a quantity, "
                                               "a heading fragment or an instruction."),
    # ⚠️ NOT A FAILURE. These lines DID match, and the match was held back on purpose because the
    #    row it reached carries someone else's prose. self-rising flour and white miso both land on
    #    a row with a written entry (flour, miso), so binding them would show a cook the wrong
    #    description under the right name. The cilantro compound names three ingredients and was
    #    matched on the first. Counting them as unmatched would misread a decision as a gap.
    "FORM_STRIP": ("held back on purpose", "The line matched, and the match was suppressed because "
                                           "the row it reached carries another ingredient's prose."),
    "DECIDED": ("held back on purpose", "The line matched and the match was suppressed."),
    "EXACT": ("held back on purpose", "The line matched and the match was suppressed."),
}


def unbound_rows(conn):
    """Why each unlinked line failed. Reasons come from the matcher, not from the database, since
    link_rule is only written for lines that DID bind."""
    bound = {r[0] for r in conn.execute(
        "SELECT id FROM recipe_ingredients WHERE catalog_id IS NOT NULL")}
    out = []
    for r in proposals():
        if r["id"] in bound:
            continue
        out.append({"id": r["id"], "recipe": r["recipe"], "raw": r["raw"], "core": r["core"],
                    "reason": r["tier"], "matched": r.get("matched") or ""})
    return out


# ════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    c = db()
    q = lambda s: c.execute(s).fetchone()[0]
    n = counts(c)
    cov = coverage(c)
    n["_unbound"] = cov["unbound"]
    computed, stored, dis = entry_states(c)
    total = n["catalog"]
    linked_rows = q("SELECT COUNT(DISTINCT child_id) FROM library_relations")
    bare = total - linked_rows
    with_id = q("SELECT COUNT(*) FROM library_entries WHERE library_id IS NOT NULL")

    # ⚠️ ONE REGISTER, NOT SIX. The dish model is eight tables and putting eight counters here
    #    would drown the five registers that describe the library itself. The gloss carries the
    #    shape and the tab carries the detail.
    dish_led = ""
    if n.get("dishes"):
        prof = q("SELECT COUNT(DISTINCT dish_id) FROM mined_dish_ingredient")
        forms = q("SELECT COUNT(DISTINCT dish_type) FROM mined_dish_form")
        bases = q("SELECT COUNT(DISTINCT library_id) FROM mined_dish_base")
        dish_led = led("Dishes", fmt(n["dishes"]), "/dishes",
                       gloss=f"{fmt(prof)} with an ingredient profile, {fmt(forms)} forms, "
                             f"{fmt(bases)} distinct bases, all catalog rows",
                       unit="dish types")

    banner = ""
    if dis:
        rows = "".join(
            f'<li><a href="/e/{uq(a)}">{escape(a)}</a>: stored says <b>{escape(b)}</b>, '
            f'computed says <b>{escape(cc)}</b>. {escape(d or "")}</li>' for a, b, cc, d in dis)
        banner = (f'<div class=banner>⚠️ <b>{len(dis)} of {n["entries"]} entries: the stored '
                  f'<code>link_state</code> disagrees with the state computed on this reading.</b> '
                  f'It is written at load, and no rename since re-runs the reconcile, so the stored '
                  f'value goes stale. The computed figures below are the ones to trust.'
                  f'<ul style="margin:8px 0 0;padding-left:18px">{rows}</ul></div>')

    def dist(sql, base, key, lead_first=True):
        rows = list(c.execute(sql))
        top = max((r[1] for r in rows), default=1) or 1
        out = ""
        for i, r in enumerate(rows):
            cls = "bar lead" if (i == 0 and lead_first) else "bar"
            # the bar already sits inside the anchor, so the whole row is one door. It only
            # LOOKED unclickable because nothing under the pointer answered.
            out += (f'<a class="{cls}" href="{base}?{key}={uq(r[0])}">'
                    f'<span class=r><span class=k>{escape(human(key, str(r[0])))}</span>'
                    f'<span class=lead></span><b>{fmt(r[1])}</b></span>'
                    f'<span class=t><i style="width:{r[1]/top*100:.1f}%"></i></span></a>')
        return out

    seg = lambda v: (v / cov["scope"] * 100) if cov["scope"] else 0
    body = f"""
<section aria-labelledby=cov><h2 id=cov>Linkage coverage</h2>
<p class=hint>Recipe lines bound to a catalog row, measured against the {fmt(cov['scope'])}
 non-heading lines in scope. The leading segment is the part that reaches written prose, which is
 the figure that decides what a cook is actually shown.</p>
<div class=chart>
<div class=head>
  <a class=big href="/links">{fmt(cov['bound'])}</a>
  <span class=of>of <b>{fmt(cov['scope'])}</b> lines in scope</span>
  <a class=pct href="/links"><span class=v>{cov['pct']:.1f}%</span><span class=l>bound</span></a>
</div>
<div class=track role="img" aria-label="{cov['entry']} lines reach a written entry, {cov['row']} reach a plain catalog row, {cov['unbound']} remain unbound">
  <a href="/links?reach=entry" style="background:var(--teal);flex:{cov['entry']}" aria-label="reach a written entry"></a>
  <a href="/links?reach=row" style="background:var(--teal-mid);flex:{cov['row']}" aria-label="reach a plain catalog row"></a>
  <a href="/uncovered" style="flex:{cov['unbound']};background:repeating-linear-gradient(45deg,#DCE6E8 0 4px,#F6F9F9 4px 8px)" aria-label="reach nothing"></a>
</div>
<div class=ruler aria-hidden="true">
  {"".join(f'<span class="t{" maj" if i%2==0 else ""}" style="left:{i*12.5}%"></span>' for i in range(8))}
  <span class="t maj" style="left:calc(100% - 1px)"></span>
  <span class="lab first" style="left:0">0</span>
  <span class=lab style="left:25%">{fmt(round(cov['scope']*.25))}</span>
  <span class=lab style="left:50%">{fmt(round(cov['scope']*.5))}</span>
  <span class=lab style="left:75%">{fmt(round(cov['scope']*.75))}</span>
  <span class="lab last" style="left:100%">{fmt(cov['scope'])}</span>
</div>
<div class=legend>
  <a class=bound href="/links?reach=entry"><span class=led><em style="background:var(--teal)"></em>
    <span class=lab>reach a written entry</span><span class=lead></span>
    <span class=fig>{fmt(cov['entry'])}</span><span class=pc>{seg(cov['entry']):.1f}%</span></span>
    <span class=g>The line can be shown sourced prose, its claims and its safety flags.</span></a>
  <a href="/links?reach=row"><span class=led><em style="background:var(--teal-mid)"></em>
    <span class=lab>reach a plain catalog row</span><span class=lead></span>
    <span class=fig>{fmt(cov['row'])}</span><span class=pc>{seg(cov['row']):.1f}%</span></span>
    <span class=g>Identified and resolvable, with nothing written about it yet.</span></a>
  <a class=un href="/uncovered"><span class=led>
    <em style="background:repeating-linear-gradient(45deg,#DCE6E8 0 3px,#F6F9F9 3px 6px)"></em>
    <span class=lab>remain unbound</span><span class=lead></span>
    <span class=fig>{fmt(cov['unbound'])}</span><span class=pc>{seg(cov['unbound']):.1f}%</span></span>
    <span class=g>Compounds, constructions and specialist ingredients the catalog does not hold.</span></a>
</div></div></section>

<section aria-labelledby=regs><h2 id=regs>Registers</h2>
<p class=hint>Counted at this reading. Each opens its own list.</p>
<div class=reg>
  {led("Catalog rows", fmt(n['catalog']), "/catalog", gloss="Every name the library can resolve", unit="names")}
  {led("Written entries", fmt(n['entries']), "/entries",
       gloss=f"{with_id} bound to a row, {n['entries']-with_id} without one", unit="records")}
  {led("Categories", fmt(n['categories']), "/categories", gloss="The browsable vocabulary", unit="records")}
  {led("Relations", fmt(n['relations']), "/relations",
       gloss=", ".join(f"{fmt(r[1])} {human('kind', r[0])}" for r in c.execute(
           "SELECT kind, COUNT(*) FROM library_relations GROUP BY 1 ORDER BY 2 DESC")),
       unit="edges between names")}
  {led("Recipe links", fmt(n['links']), "/links",
       gloss=f"Across {fmt(q('SELECT COUNT(DISTINCT catalog_id) FROM recipe_ingredients WHERE catalog_id IS NOT NULL'))} distinct catalog rows",
       unit="line-to-row bindings")}
  {led("Recipes", fmt(n['recipes']), "/recipes", gloss="The corpus those links are drawn from", unit="recipes")}
  {dish_led}
</div></section>

<section aria-labelledby=cnd><h2 id=cnd>Condition</h2>
<p class=hint>Recomputed on this reading rather than taken from the stored field, which goes stale
 the moment a name is changed.</p>
{banner}
<div class=cond>
  {led("linked", fmt(computed.get('linked',0)), "/entries?state=linked")}
  {led("canonical drifted", fmt(computed.get('canonical_drift',0)), "/entries?state=canonical_drift", cls="flag")}
  {led("no catalog row", fmt(computed.get('no_library_id',0)), "/entries?state=no_library_id")}
  {led("rows with no relation", fmt(bare), "/catalog?filter=bare")}
  {led("share of catalog", f"{bare/total*100:.0f}%", "/catalog?filter=bare")}
  {led("written entries in all", fmt(n['entries']), "/entries")}
  <div class=sums>The three states account for all <b>{n['entries']}</b> written entries, and the
    <b>{with_id}</b> carrying a catalog row are the linked and the drifted together. Two rows in
    five of the catalog hold nothing but a name, which is the ordinary state of a catalog this
    size rather than a fault in it.</div>
</div></section>

<section aria-labelledby=ver><h2 id=ver>Verification detail</h2>
<p class=hint>Where each relation came from and how firmly it stands. Every row opens the slice it
 names.</p>
<div class=dist>
  <div><h3>Confidence</h3><p class=cap>How firmly the edge was established.</p>
    {dist("SELECT confidence, COUNT(*) FROM library_relations GROUP BY 1 ORDER BY 2 DESC", "/relations", "confidence")}</div>
  <div><h3>Determined from</h3><p class=cap>A cook's judgment outranks a graph. Where both had an
    opinion on the same ingredient, they agreed four times in fifteen.</p>
    {dist("SELECT source, COUNT(*) FROM library_relations GROUP BY 1 ORDER BY 2 DESC", "/relations", "source")}</div>
  <div><h3>Standing of the prose</h3><p class=cap>Each sentence carries the tier of the weakest
    claim beneath it.</p>
    {dist("SELECT derived_tier, COUNT(*) FROM library_prose_pieces GROUP BY 1 ORDER BY 2 DESC", "/prose", "tier")}</div>
</div></section>"""
    c.close()
    return page("Condition", body, "/", n=n)


# ════════════════════════════════════════════════════════════════════════════
#  LIST PAGES
# ════════════════════════════════════════════════════════════════════════════

CAT_FILTERS = [("", "all"), ("has-entry", "written up"), ("has-category", "in a category"),
               ("has-parent", "has a parent"), ("has-lines", "used in a recipe"), ("bare", "bare")]
# `attached` is reachable from the chart but is not a chip. It is the exact complement of bare,
# which the six chips have no single value for.
CAT_FILTER_LABELS = dict(CAT_FILTERS)

# ⚠️ ONE DEFINITION PER COLUMN, used by SELECT, WHERE and ORDER BY alike. The number you read,
#    the number you sort on and the number you filter on are then provably the same expression
#    rather than three that happen to agree today.
CAT_EXPR = {
    "lines": "(SELECT COUNT(*) FROM recipe_ingredients ri WHERE ri.catalog_id=ln.library_id)",
    "par":   "(SELECT COUNT(*) FROM library_relations r WHERE r.child_id=ln.library_id"
             " AND r.kind<>'in_category')",
    "kids":  "(SELECT COUNT(*) FROM library_relations r WHERE r.parent_id=ln.library_id"
             " AND r.kind<>'in_category')",
    "cat":   "(SELECT lc.category_id FROM library_relations r JOIN library_categories lc"
             " ON lc.category_id=r.parent_id WHERE r.child_id=ln.library_id"
             " AND r.kind='in_category' LIMIT 1)",
    "ent":   "(SELECT e.entry_id FROM library_entries e WHERE e.library_id=ln.library_id)",
}

# the sort whitelist. A key that is not in here never reaches SQL.
CAT_SORT = {"ingredient": "ln.canonical COLLATE NOCASE", "category": CAT_EXPR["cat"],
            "entry": CAT_EXPR["ent"], "parents": CAT_EXPR["par"], "children": CAT_EXPR["kids"],
            "lines": CAT_EXPR["lines"], "library_id": "ln.library_id COLLATE NOCASE"}


def cat_order(key, direction):
    """⚠️ EVERY SORT ENDS WITH THE SAME TIEBREAK. 10,065 of the 10,474 rows have lines=0, so an
    ORDER BY with no deterministic tail lets SQLite return them in any order it likes, and a row
    can then appear on two pages or on none. canonical is unique, so it settles every tie.

    NULLs go last in both directions. Sorting by category ascending otherwise opens on 4,089
    rows that have no category, which is the one thing that column is never being asked."""
    d = "DESC" if direction == "desc" else "ASC"
    e = CAT_SORT.get(key)
    if not e:
        return f"{CAT_EXPR['lines']} DESC, ln.canonical COLLATE NOCASE"
    nulls = (f"CASE WHEN {e} IS NULL THEN 1 ELSE 0 END, " if key in ("category", "entry") else "")
    coll = " COLLATE NOCASE" if key in ("category", "entry") else ""
    return f"{nulls}{e}{coll} {d}, ln.canonical COLLATE NOCASE"


# ⚠️ THE OPTIONS COME FROM THE MEASURED SPREAD, NOT FROM A TEMPLATE. parents runs 0 to 2 across
#    the whole catalog, so a range box would offer bounds that do not exist. lines is zero for
#    96.1% of rows and children for 98.3%, so presence is the cut that does the work, and a
#    threshold handles the tail. Value "0" means exactly none, any other N means N or more.
CAT_NUM = {
    "nlines": ("lines", "lines", [("0", "none"), ("1", "1 or more"), ("5", "5 or more"),
                                  ("10", "10 or more"), ("25", "25 or more")]),
    "npar":   ("par", "parents", [("0", "none"), ("1", "1 or more"), ("2", "2")]),
    "nkids":  ("kids", "children", [("0", "none"), ("1", "1 or more"), ("5", "5 or more"),
                                    ("25", "25 or more"), ("100", "100 or more")]),
}
CAT_TEXT = {"q": ("ingredient", "name contains"), "cat": ("category", "category contains"),
            "ent": ("entry", "entry contains")}


def cat_where():
    """Read the request into (where, args, active). Every control lands in one WHERE, so the
    head count and the rows can never disagree about what is being shown."""
    where, args, active = [], [], []
    g = lambda k: (request.args.get(k) or "").strip()

    if g("q"):
        where.append("ln.canonical LIKE ? COLLATE NOCASE"); args.append(f"%{g('q')}%")
        active.append(("q", "name contains", g("q")))
    # ⚠️ 14 rows sit in two categories and the cat column shows only the first of them, so
    #    matching the DISPLAYED value would quietly drop the second category of those rows.
    #    EXISTS asks the relation table instead, which is where the truth is.
    if g("cat"):
        where.append("EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id"
                     " AND r.kind='in_category' AND r.parent_id LIKE ? COLLATE NOCASE)")
        args.append(f"%{g('cat')}%")
        active.append(("cat", "category contains", g("cat")))
    if g("ent"):
        where.append("EXISTS(SELECT 1 FROM library_entries e WHERE e.library_id=ln.library_id"
                     " AND e.entry_id LIKE ? COLLATE NOCASE)")
        args.append(f"%{g('ent')}%")
        active.append(("ent", "entry contains", g("ent")))

    for param, (col, label, opts) in CAT_NUM.items():
        v = g(param)
        if not v.isdigit():
            continue
        n = int(v)
        where.append(f"{CAT_EXPR[col]} {'=' if n == 0 else '>='} ?"); args.append(n)
        active.append((param, label, dict(opts).get(v, v)))

    # ⚠️ THE CHART GETS ITS OWN PARAMETER, NOT THE CHIP'S. Both segments once wrote `filter`,
    #    which the six chips also own, so clicking a segment while a chip was on replaced the
    #    chip instead of narrowing it: the chart read 5 bare of the 53 written up, and the door
    #    opened on all 4,061 bare rows in the catalog. A separate key ANDs with everything else.
    #    `attached` is the exact complement of `bare`, which no single chip expresses.
    ANY_REL = ("EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id"
               " OR r.parent_id=ln.library_id)")
    at = g("attach")
    if at in ("bare", "attached"):
        where.append(ANY_REL if at == "attached" else f"NOT {ANY_REL}")
        active.append(("attach", "attachment",
                       "attached to something" if at == "attached" else "nothing attached"))

    # ⚠️ GOTCHA 1: kind is constrained inside every EXISTS.
    F = {"has-entry": "EXISTS(SELECT 1 FROM library_entries e WHERE e.library_id=ln.library_id)",
         "has-category": "EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id AND r.kind='in_category')",
         "has-parent": "EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id AND r.kind<>'in_category')",
         "has-lines": "EXISTS(SELECT 1 FROM recipe_ingredients ri WHERE ri.catalog_id=ln.library_id)",
         "bare": "NOT EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id OR r.parent_id=ln.library_id)"}
    f = g("filter")
    if f in F:
        where.append(F[f])
        active.append(("filter", "show", CAT_FILTER_LABELS.get(f, f)))
    return where, args, active


def cat_gauge(c, w, args, total, n_all, filtered):
    """⚠️ THE CHART AND THE TABLE DESCRIBE THE SAME SET. Drawn over the whole catalog while the
    table showed 14 rows, the bar was answering a question nobody asked, and the 38.8% under a
    filtered table read as a fact about those 14. The split is recomputed inside the same WHERE
    the rows come from, so the two cannot drift.

    The segments carry the active filter forward rather than replacing it, so clicking `nothing
    attached` on a filtered chart narrows what is shown instead of resetting to the whole
    catalog."""
    if not total:
        return ""                      # an empty bar states nothing and draws as a broken rule
    bare = ("NOT EXISTS(SELECT 1 FROM library_relations r WHERE r.child_id=ln.library_id"
            " OR r.parent_id=ln.library_id)")
    joiner = " AND " if w else " WHERE "
    n_bare = c.execute(f"SELECT COUNT(*) FROM library_names ln {w}{joiner}{bare}",
                       args).fetchone()[0]
    cap = (f"the {fmt(total)} rows shown" if filtered else f"all {fmt(n_all)} rows")
    return gauge([("nothing attached", n_bare, f"/catalog{qs(attach='bare', page=None)}"),
                  ("in a category, under a parent, or both", total - n_bare,
                   f"/catalog{qs(attach='attached', page=None)}")],
                 total, whole_label=cap)


def refine(cats):
    """The per-column controls. One row of text boxes, one row of counted-column selects."""
    keep = "".join(f'<input type=hidden name={k} value="{escape(request.args.get(k, ""))}">'
                   for k in ("filter", "attach", "sort", "dir") if request.args.get(k))
    tx = "".join(
        f'<label><span>{escape(lab)}</span>'
        f'<input type=search name={k} value="{escape(request.args.get(k, ""))}" '
        f'placeholder="{escape(ph)}"{" list=cats" if k == "cat" else ""}></label>'
        for k, (lab, ph) in CAT_TEXT.items())
    nm = ""
    for param, (col, label, opts) in CAT_NUM.items():
        cur = request.args.get(param) or ""
        o = '<option value="">any</option>' + "".join(
            f'<option value="{v}"{" selected" if cur == v else ""}>{escape(l)}</option>'
            for v, l in opts)
        nm += f'<label><span>{escape(label)}</span><select name={param} ' \
              f'onchange="this.form.submit()">{o}</select></label>'
    dl = ('<datalist id=cats>'
          + "".join(f'<option value="{escape(x)}">' for x in cats) + '</datalist>')
    return (f'<form class=refine>{keep}{dl}<div class=rf>{tx}</div><div class=rf>{nm}'
            f'<button type=submit>apply</button></div></form>')


def activebar(active, total, n_all):
    """What is on right now, each one removable, and the count it produced."""
    if not active:
        return ""
    # ⚠️ THE PATH HAS TO BE WRITTEN OUT. qs() returns an empty string once the last parameter is
    #    dropped, and href="" reloads the URL you are already on, so removing the only active
    #    filter would silently do nothing.
    chips = "".join(
        f'<a class=chip href="/catalog{qs(**{k: None, "page": None})}" '
        f'title="remove this filter"><b>{escape(lab)}</b> {escape(str(val))}<i>×</i></a>'
        for k, lab, val in active)
    return (f'<div class=active><span class=lbl>filtering</span>{chips}'
            f'<a class=clr href="/catalog">clear all</a>'
            f'<span class=res>{fmt(total)} of {fmt(n_all)}</span></div>')


@app.route("/catalog")
def catalog():
    c = db()
    p = max(1, int(request.args.get("page") or 1))
    sort = request.args.get("sort") if request.args.get("sort") in CAT_SORT else ""
    direc = "desc" if (request.args.get("dir") or "") == "desc" else "asc"
    where, args, active = cat_where()
    w = ("WHERE " + " AND ".join(where)) if where else ""
    # ⚠️ THE COUNT AND THE ROWS SHARE ONE WHERE. The head figure is the same query as the body.
    total = c.execute(f"SELECT COUNT(*) FROM library_names ln {w}", args).fetchone()[0]
    order = cat_order(sort, direc) if sort else \
        f"{CAT_EXPR['lines']} DESC, ln.canonical COLLATE NOCASE"
    rows = []
    for r in c.execute(
            f"SELECT ln.library_id, ln.canonical, {CAT_EXPR['lines']} lines,"
            f" {CAT_EXPR['par']} par, {CAT_EXPR['kids']} kids, {CAT_EXPR['cat']} cat,"
            f" {CAT_EXPR['ent']} ent"
            f" FROM library_names ln {w} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [PER, (p - 1) * PER]):
        lid = uq(r["library_id"])
        rows.append((
            f'<span class=nm>{ilink(r["library_id"], r["canonical"])}</span>',
            clink(r["cat"], r["cat"].replace("-", " ")) if r["cat"] else '<span class=dimc>none</span>',
            elink(r["ent"]) if r["ent"] else '<span class=dimc>none</span>',
            # counts land on exactly the set they count: hierarchy edges above, below, and the
            # recipe lines that bound to this row.
            cnt(r["par"], f'/relations?child={lid}&kind=hierarchy'),
            cnt(r["kids"], f'/relations?parent={lid}&kind=hierarchy'),
            cnt(r["lines"], f'/links?catalog={lid}'),
            f'<span class="mono dimc">{ilink(r["library_id"])}</span>'))
    q1 = lambda sql: c.execute(sql).fetchone()[0]
    n_bare = q1("SELECT COUNT(*) FROM library_names ln WHERE NOT EXISTS(SELECT 1 FROM "
                "library_relations r WHERE r.child_id=ln.library_id OR r.parent_id=ln.library_id)")
    n_all = q1("SELECT COUNT(*) FROM library_names")
    n_used = q1("SELECT COUNT(DISTINCT catalog_id) FROM recipe_ingredients WHERE catalog_id IS NOT NULL")
    n_ent = q1("SELECT COUNT(*) FROM library_entries")
    n_par = q1("SELECT COUNT(DISTINCT parent_id) FROM library_relations WHERE kind<>'in_category'")
    cats = [x[0] for x in c.execute("SELECT category_id FROM library_categories ORDER BY 1")]
    about = (f'Every name the library can resolve, and mostly that is all it holds. '
             f'<b>{fmt(n_bare)}</b> of the {fmt(n_all)} carry nothing but a name, which is the '
             f'ordinary state of a catalog this size. <b>{fmt(n_used)}</b> have ever been reached '
             f'by a recipe line, and <b>{fmt(n_ent)}</b> have prose written about them. A row '
             f'earns its detail by being cooked with, not by being listed.')
    HEADS = [
      ("ingredient", "the name as the library spells it", "canonical", "ingredient"),
      ("category", "the browsable family it was filed under", "in_category parent", "category"),
      ("written entry", f"whether prose has been written about it. {fmt(n_ent)} of {fmt(n_all)} have",
       "library_entries", "entry"),
      ("parents", "broader rows above it", "kind_of, made_from", "parents"),
      ("children", f"narrower rows below it. Only {fmt(n_par)} rows parent anything",
       "kind_of, made_from", "children"),
      ("lines", "recipe lines that resolved here", "catalog_id", "lines"),
      ("library_id", "the stored id. Everything else points at this", "library_id", "library_id"),
    ]
    body = f"""<section>
{phead("Catalog", total, "rows" if not active else "rows shown", "library_names", about,
       of=None if not active else n_all)}
{cat_gauge(c, w, args, total, n_all, bool(active))}
<div class=filters>{filters("/catalog","filter",CAT_FILTERS,request.args.get("filter") or "","show")}</div>
{refine(cats)}
{activebar(active, total, n_all)}
{table(HEADS, rows, ["nm","","","num","num","num",""], "No catalog row matches.")}
{pager(p,total,"/catalog")}</section>"""
    c.close()
    return page("Catalog", body, "/catalog", [("Condition", "/"), ("Catalog", None)])


@app.route("/entries")
def entries():
    c = db()
    want = request.args.get("state") or ""
    rows, shown = [], 0
    for e in c.execute("SELECT * FROM library_entries ORDER BY entry_id"):
        s, live, why = entry_state(c, e)          # ⚠️ GOTCHA 3
        if want and s != want:
            continue
        shown += 1
        stale = "" if s == e["link_state"] else f' {tag("stored says "+e["link_state"],"amber")}'
        q1 = lambda sql: c.execute(sql, (e["entry_id"],)).fetchone()[0]
        eid = uq(e["entry_id"])
        # the possible parent is a free-text name. It becomes a door only when it resolves to a
        # real catalog row, and stays plain text when it does not.
        pp, pp_html = e["possible_parent"], ""
        if pp:
            hit = c.execute("SELECT library_id FROM library_names WHERE canonical=? COLLATE NOCASE",
                            (pp,)).fetchone()
            pp_html = (f'<span class=dimc>{ilink(hit["library_id"], pp)}</span>' if hit
                       else f'<span class=dimc>{escape(pp)}</span>')
        rows.append((
            f'<span class=nm>{elink(e["entry_id"])}</span>',
            ilink(e["library_id"], live or e["library_id"]) if e["library_id"]
              else '<span class=dimc>no catalog row</span>',
            taglink(s, f'/entries?state={uq(s)}', "teal" if s == "linked" else "amber") + stale,
            cnt(q1("SELECT COUNT(*) FROM library_prose_pieces WHERE entry_id=?"), f'/prose?entry={eid}'),
            cnt(q1("SELECT COUNT(*) FROM library_assertions WHERE entry_id=? AND assertion_kind='claim'"), f'/e/{eid}'),
            cnt(q1("SELECT COUNT(*) FROM library_assertions WHERE entry_id=? AND assertion_kind='safety_flag'"), f'/e/{eid}'),
            pp_html))
    computed, stored, dis = entry_states(c)
    opts = [("", "all")] + [(k, k.replace("_", " ")) for k in
                            ("linked", "canonical_drift", "no_library_id")]
    n_all = c.execute("SELECT COUNT(*) FROM library_names").fetchone()[0]
    about = (
      f'<p class=about>An entry is an ingredient someone has actually sat down and written about. '
      f'<b>{sum(computed.values())}</b> of the {fmt(n_all)} catalog rows have one. The rest are '
      f'names with nothing written behind them, which is not a fault, only how far the writing '
      f'has got.</p>'
      '<p class=about>The state is recomputed on this reading rather than read from the stored '
      '<code>link_state</code>, which goes stale the moment a name changes. Where the two '
      'disagree the stored value is shown beside it and the computed one is right.</p>')
    HEADS = [
      ("entry", "the written record, named by its slug", "entry_id"),
      ("catalog row", "the catalog name it was linked to", "library_id"),
      ("state", "linked, the name has drifted, or no catalog row. Computed now, not stored",
       "link_state"),
      ("prose", "sentences written for it", "library_prose_pieces"),
      ("claims", "statements it makes that a sentence can rest on", "assertion_kind = claim"),
      ("flags", "allergen and hazard warnings", "assertion_kind = safety_flag"),
      ("possible parent", "a broader row someone proposed, not yet an edge", "possible_parent"),
    ]
    STATE_HREF = {"linked": "linked", "canonical_drift": "canonical_drift",
                  "no_library_id": "no_library_id"}
    st_parts = [(human("link_state", k) if k in STATE_HREF else k, v,
                 f"/entries?state={uq(k)}") for k, v in sorted(computed.items(), key=lambda x: -x[1])]
    body = f"""<section>
{phead("Written entries", shown, "entries", "library_entries", "", said=about)}
{gauge(st_parts, sum(computed.values()))}
<div class=filters>{filters("/entries","state",opts,want,"state")}</div>
{table(HEADS, rows, ["nm","","","num","num","num",""], "No entry in that state.")}
<p class=note>{shown} shown. Computed across all: {", ".join(f"{k.replace('_',' ')} {v}" for k,v in sorted(computed.items()))}.</p>
</section>"""
    c.close()
    return page("Entries", body, "/entries", [("Condition", "/"), ("Entries", None)])


@app.route("/categories")
def categories():
    c = db()
    rows, nested = [], 0
    for r in c.execute("SELECT * FROM library_categories ORDER BY category_id"):
        m, twin = category_members(c, r["category_id"])      # ⚠️ GOTCHA 4
        if r["parent_slug"]:
            nested += 1
        cid = uq(r["category_id"])
        rows.append((
            f'<span class=nm>{clink(r["category_id"], r["name"])}</span>',
            cnt(len(m), f'/c/{cid}'),
            (f'<span class=dimc>{clink(r["parent_slug"])}</span>' if r["parent_slug"]
             else '<span class=dimc>none</span>'),
            taglink("split parent", f'/c/{cid}', "amber") if twin else "",
            f'<span class="dimc wrap">{escape((r["note"] or "")[:130])}</span>'))
    n_twin = c.execute("SELECT COUNT(*) FROM library_categories lc WHERE EXISTS(SELECT 1 FROM "
                       "library_names ln WHERE ln.canonical=lc.name COLLATE NOCASE)").fetchone()[0]
    about = (
      f'<p class=about>A category is a family you browse. A kind-of parent is a claim about what a '
      f'thing <b>is</b>. They look alike on the page and do different work, and telling them apart '
      f'matters because <b>{n_twin} of these {len(rows)}</b> names are also a catalog row.</p>'
      f'<p class=about>It is a flat list rather than a tree. <b>{nested}</b> of the {len(rows)} '
      f'carries a parent category, so nesting barely exists yet and it is rendered honestly as a '
      f'list.</p>')
    HEADS = [
      ("category", "the family, as it is browsed", "name"),
      ("members", "rows filed under it, by either path", "in_category, kind_of"),
      ("nested under", "a broader category, on the one that has it", "parent_slug"),
      ("", "flagged where a catalog row shares this name", "library_names.canonical"),
      ("note", "why the category is drawn where it is", "note"),
    ]
    body = f"""<section>
{phead("Categories", len(rows), "categories", "library_categories", "", said=about)}
{table(HEADS, rows, ["nm","num","","",""])}</section>"""
    c.close()
    return page("Categories", body, "/categories", [("Condition", "/"), ("Categories", None)])


@app.route("/relations")
def relations():
    c = db()
    kind = request.args.get("kind") or ""
    conf = request.args.get("confidence") or ""
    src = request.args.get("source") or ""
    qy = (request.args.get("q") or "").strip()
    p = max(1, int(request.args.get("page") or 1))
    child = request.args.get("child") or ""
    parent = request.args.get("parent") or ""
    where, args = [], []
    # ⚠️ 'hierarchy' is a pseudo-kind meaning kind-of plus made-from. The catalog's parent and
    #    child counts exclude in-category edges, so the door has to exclude them too or the
    #    destination would show more rows than the number that led to it.
    if kind == "hierarchy":
        where.append("r.kind<>'in_category'")
    elif kind:
        where.append("r.kind=?"); args.append(kind)
    for col, val in (("confidence", conf), ("source", src)):
        if val:
            where.append(f"r.{col}=?"); args.append(val)
    if child:
        where.append("r.child_id=?"); args.append(child)
    if parent:
        where.append("r.parent_id=?"); args.append(parent)
    if qy:
        where.append("(r.child_canonical LIKE ? COLLATE NOCASE OR r.parent_canonical LIKE ? COLLATE NOCASE)")
        args += [f"%{qy}%", f"%{qy}%"]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM library_relations r {w}", args).fetchone()[0]
    rows = []
    for r in c.execute(f"SELECT * FROM library_relations r {w} "
                       "ORDER BY r.child_canonical LIMIT ? OFFSET ?", args + [PER, (p - 1) * PER]):
        # ⚠️ GOTCHA 1: the parent link target depends on kind. in_category goes to a category page,
        #    kind_of and made_from go to a catalog page. 'bread' and 'pasta' are both.
        plnk = plink(r["kind"], r["parent_id"], r["parent_canonical"] or r["parent_id"])
        rows.append((f'<span class=nm>{ilink(r["child_id"], r["child_canonical"] or r["child_id"])}</span>',
                     taglink(human("kind", r["kind"]), f'/relations?kind={uq(r["kind"])}'),
                     plnk, taglink(human("confidence", r["confidence"]), f'/relations?confidence={uq(r["confidence"])}'),
                     f'<span class=dimc><a href="/relations?source={uq(r["source"])}">'
                     f'{escape(human("source", r["source"]))}</a></span>',
                     f'<span class="dimc wrap">{escape((r["note"] or "")[:90])}</span>'))
    def opts(col):
        base = [("", "all")] + [(x[0], f"{human(col, x[0])} {fmt(x[1])}") for x in c.execute(
            f"SELECT {col}, COUNT(*) FROM library_relations GROUP BY 1 ORDER BY 2 DESC")]
        if col == "kind":
            n = c.execute("SELECT COUNT(*) FROM library_relations WHERE kind<>'in_category'").fetchone()[0]
            base.append(("hierarchy", f'{human("kind", "hierarchy")} {fmt(n)}'))
        return base

    # the strip naming a child- or parent-filtered view, so an arrival from a count knows where it is
    bits, nm = [], lambda i: (c.execute("SELECT canonical FROM library_names WHERE library_id=?",
                                        (i,)).fetchone() or [i])[0]
    if child:
        bits.append(f'Edges above <b>{escape(nm(child))}</b>, so the parents it was given.')
    if parent:
        bits.append(f'Edges below <b>{escape(nm(parent))}</b>, so the children it was given.')
    if kind == "hierarchy":
        bits.append('Kind-of and made-from only, matching the counts on the catalog.')
    strip = ctx(bits, "/relations") if bits else ""
    q1 = lambda sql: c.execute(sql).fetchone()[0]
    n_par = q1("SELECT COUNT(DISTINCT parent_id) FROM library_relations WHERE kind<>'in_category'")
    n_kid = q1("SELECT COUNT(DISTINCT child_id) FROM library_relations WHERE kind<>'in_category'")
    n_cat = q1("SELECT COUNT(*) FROM library_categories")
    n_twin = q1("SELECT COUNT(*) FROM library_categories lc WHERE EXISTS(SELECT 1 FROM "
                "library_names ln WHERE ln.canonical=lc.name COLLATE NOCASE)")
    n_note = q1("SELECT COUNT(*) FROM library_relations WHERE note IS NOT NULL AND note<>''")
    n_edges = q1("SELECT COUNT(*) FROM library_relations")
    filtered = bool(kind or conf or src or qy or child or parent)
    about = (
      '<p class=about>A relation is one line saying how an ingredient sits under something broader. '
      'There are three of them and they are not the same claim.</p>'
      '<p class=about><span class=ex>All-purpose flour <b>is a kind of</b> flour</span>, the same '
      'stuff named more narrowly. <span class=ex>Cilantro <b>is in the</b> herb <b>category</b></span>, '
      'filed with a family you can browse. <span class=ex>Garlic powder <b>is made from</b> '
      'garlic</span>, one ingredient turned into another.</p>'
      f'<p class=about>The hierarchy is wide and shallow. <b>{fmt(n_par)}</b> rows do all the '
      f'parenting for <b>{fmt(n_kid)}</b> children. A parent is not always a catalog row either. '
      f'On an in-category line it is a category, and <b>{n_twin} of the {n_cat}</b> categories '
      f'share their name with one, so every query here has to say which of the two it means.</p>')
    HEADS = [
      ("child", "the row the line is about, the narrower of the two", "child_canonical"),
      ("kind", "which of the three claims this line makes", "kind"),
      ("parent", "the broader thing it sits under", "parent_canonical"),
      ("confidence", "how firmly it stands. high is the source's own claim, the rest are hand calls",
       "confidence"),
      ("source", "where it came from. wikidata and off are bulk imports", "source"),
      ("note", f"a reason, on the {fmt(n_note)} lines that carry one", "note"),
    ]
    kind_parts = [(human("kind", k), v, f"/relations?kind={uq(k)}") for k, v in c.execute(
        "SELECT kind, COUNT(*) FROM library_relations GROUP BY 1 ORDER BY 2 DESC")]
    body = f"""<section>
{phead("Relations", total, "edges", "library_relations", "", said=about,
       of=None if not filtered else n_edges)}
{gauge(kind_parts, n_edges)}
<div class=filters>{filters("/relations","kind",opts("kind"),kind,"kind")}</div>
<div class=filters>{filters("/relations","confidence",opts("confidence"),conf,"confidence")}</div>
<div class=filters>{filters("/relations","source",opts("source"),src,"source")}{searchbox("filter by name",("kind","confidence","source","child","parent"))}</div>
{strip}
{table(HEADS, rows, ["nm","","","","",""], "No relation matches those filters.")}
{pager(p,total,"/relations")}</section>"""
    c.close()
    return page("Relations", body, "/relations", [("Condition", "/"), ("Relations", None)])


@app.route("/prose")
def prose_list():
    c = db()
    tier = request.args.get("tier") or ""
    p = max(1, int(request.args.get("page") or 1))
    ent_id = request.args.get("entry") or ""
    key = request.args.get("key") or ""
    where, args = [], []
    if tier:
        where.append("p.derived_tier=?"); args.append(tier)
    if ent_id:
        where.append("p.entry_id=?"); args.append(ent_id)
    if key:
        # ⚠️ the join is on the composite (entry_id, slot, position), not on entry_id alone.
        where.append("EXISTS(SELECT 1 FROM library_prose_derived_from d WHERE d.entry_id=p.entry_id"
                     " AND d.slot=p.slot AND d.position=p.position AND d.key=?)"); args.append(key)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM library_prose_pieces p {w}", args).fetchone()[0]
    rows = []
    for r in c.execute(
            "SELECT p.*, (SELECT group_concat(d.key,' + ') FROM library_prose_derived_from d "
            " WHERE d.entry_id=p.entry_id AND d.slot=p.slot AND d.position=p.position) df "
            f"FROM library_prose_pieces p {w} ORDER BY p.entry_id, p.position LIMIT ? OFFSET ?",
            args + [PER, (p - 1) * PER]):
        rests = ""
        if r["df"]:
            rests = " + ".join(
                f'<a href="/prose?key={uq(k.strip())}">{escape(k.strip())}</a>'
                for k in r["df"].split(" + "))
            rests = f'<code class=dimc>{rests}</code>'
        rows.append((f'<span class=nm>{elink(r["entry_id"])}</span>',
                     taglink(r["derived_tier"], f'/prose?tier={uq(r["derived_tier"])}',
                             "teal" if r["derived_tier"] == "curated" else ""),
                     f'<span class=wrap>{escape(r["text"])}</span>',
                     rests or '<span class=dimc>no claim behind it</span>'))
    opts = [("", "all")] + [(x[0], f"{x[0]} {fmt(x[1])}") for x in c.execute(
        "SELECT derived_tier, COUNT(*) FROM library_prose_pieces GROUP BY 1 ORDER BY 2 DESC")]
    bits = []
    if ent_id:
        bits.append(f'Sentences written for <b>{escape(ent_id)}</b>.')
    if key:
        bits.append(f'Sentences resting on the claim <b>{escape(key)}</b>.')
    pstrip = ctx(bits, "/prose") if bits else ""
    tiers = dict(c.execute("SELECT derived_tier, COUNT(*) FROM library_prose_pieces GROUP BY 1"))
    about = (
      f'<p class=about>Every written sentence in the library, <b>{fmt(sum(tiers.values()))}</b> of '
      f'them across {c.execute("SELECT COUNT(DISTINCT entry_id) FROM library_prose_pieces").fetchone()[0]} '
      f'entries. Each carries the tier of the weakest claim beneath it, so a sentence resting on '
      f'nothing reads as generated however careful its wording. <b>{tiers.get("curated",0)}</b> are '
      f'curated, <b>{tiers.get("cited",0)}</b> cited and <b>{tiers.get("generated",0)}</b> '
      f'generated.</p>')
    HEADS = [
      ("entry", "the entry the sentence was written for", "entry_id"),
      ("tier", "how well grounded, taken from the weakest claim beneath it", "derived_tier"),
      ("sentence", "the sentence as written", "text"),
      ("rests on", "the claim it draws from, where there is one", "library_prose_derived_from.key"),
    ]
    tier_parts = [(k, v, f"/prose?tier={uq(k)}") for k, v in c.execute(
        "SELECT derived_tier, COUNT(*) FROM library_prose_pieces GROUP BY 1 ORDER BY 2 DESC")]
    body = f"""<section>
{phead("Prose", total, "sentences", "library_prose_pieces", "", said=about)}
{gauge(tier_parts, sum(v for _, v, _ in tier_parts))}
<div class=filters>{filters("/prose","tier",opts,tier,"tier")}</div>
{pstrip}
{table(HEADS, rows, ["nm","","wrap",""])}
{pager(p,total,"/prose")}</section>"""
    c.close()
    return page("Prose", body, "/entries", [("Condition", "/"), ("Prose", None)])


# ════════════════════════════════════════════════════════════════════════════
#  THE TWO COVERAGE VIEWS
# ════════════════════════════════════════════════════════════════════════════

@app.route("/links")
def links():
    """Bound lines, filterable by how far they reach."""
    c = db()
    reach = request.args.get("reach") or ""
    qy = (request.args.get("q") or "").strip()
    p = max(1, int(request.args.get("page") or 1))
    cat_id = request.args.get("catalog") or ""
    rec_id = request.args.get("recipe") or ""
    confv = request.args.get("confidence") or ""
    where = ["ri.catalog_id IS NOT NULL"]
    args = []
    if cat_id:
        where.append("ri.catalog_id=?"); args.append(cat_id)
    if rec_id:
        where.append("ri.recipe_id=?"); args.append(rec_id)
    if confv:
        where.append("ri.link_confidence=?"); args.append(confv)
    if reach == "entry":
        where.append("EXISTS(SELECT 1 FROM library_entries le WHERE le.library_id=ri.catalog_id)")
    elif reach == "row":
        where.append("NOT EXISTS(SELECT 1 FROM library_entries le WHERE le.library_id=ri.catalog_id)")
    if qy:
        where.append("(COALESCE(ri.label,ri.raw_text) LIKE ? COLLATE NOCASE OR ri.link_matched LIKE ? COLLATE NOCASE)")
        args += [f"%{qy}%", f"%{qy}%"]
    w = "WHERE " + " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM recipe_ingredients ri {w}", args).fetchone()[0]
    rows = []
    for r in c.execute(
            "SELECT ri.*, rc.name rname, "
            " (SELECT le.entry_id FROM library_entries le WHERE le.library_id=ri.catalog_id) ent "
            f"FROM recipe_ingredients ri JOIN recipes rc ON rc.id=ri.recipe_id {w} "
            "ORDER BY rc.name, ri.position LIMIT ? OFFSET ?", args + [PER, (p - 1) * PER]):
        rows.append((f'<span class=wrap>{escape(r["label"] or r["raw_text"] or "")}</span>',
                     f'<span class=nm>{ilink(r["catalog_id"], r["link_matched"] or r["catalog_id"])}</span>',
                     (f'<a href="/e/{uq(r["ent"])}">{escape(r["ent"])}</a>' if r["ent"]
                      else '<span class=dimc>no entry</span>'),
                     taglink(r["link_confidence"] or "", f'/links?confidence={uq(r["link_confidence"] or "")}',
                             "teal" if r["link_confidence"] == "exact" else ""),
                     rlink(r["recipe_id"], r["rname"])))
    cov = coverage(c)
    opts = [("", f"all bound {fmt(cov['bound'])}"), ("entry", f"reach an entry {fmt(cov['entry'])}"),
            ("row", f"reach a plain row {fmt(cov['row'])}")]
    bits = []
    if cat_id:
        nm = c.execute("SELECT canonical FROM library_names WHERE library_id=?", (cat_id,)).fetchone()
        bits.append(f'Recipe lines that bound to <b>{escape(nm["canonical"] if nm else cat_id)}</b>.')
    if rec_id:
        rn = c.execute("SELECT name FROM recipes WHERE id=?", (rec_id,)).fetchone()
        bits.append(f'Bound lines in <b>{escape(rn["name"] if rn else rec_id)}</b>.')
    if confv:
        bits.append(f'Matched at confidence <b>{escape(confv)}</b>.')
    strip = ctx(bits, "/links") if bits else ""
    about = (
      f'<p class=about>A link is one recipe line that found a catalog row. <b>{fmt(cov["bound"])}</b> '
      f'of the {fmt(cov["scope"])} lines in the corpus did. The ones that reach a written entry, '
      f'<b>{fmt(cov["entry"])}</b> of them, are the only ones a cook could be shown prose for. '
      f'<a href="/uncovered">The {fmt(cov["unbound"])} that found nothing are listed '
      f'separately.</a></p>')
    HEADS = [
      ("line as written", "the ingredient line as the recipe has it", "label, else raw_text"),
      ("catalog row", "the name it resolved to", "catalog_id"),
      ("written entry", "prose behind that row, where there is any", "library_entries"),
      ("confidence", "how the match was made. exact is the name itself", "link_confidence"),
      ("recipe", "the recipe the line came from", "recipes.name"),
    ]
    mq = [(human("link_confidence", k), v, f"/links?confidence={uq(k)}") for k, v in c.execute(
        "SELECT link_confidence, COUNT(*) FROM recipe_ingredients WHERE catalog_id IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC")]
    body = f"""<section>
{phead("Recipe links", total, "lines", "recipe_ingredients", "", said=about)}
{gauge(mq, sum(v for _, v, _ in mq))}
<div class=filters>{filters("/links","reach",opts,reach,"reach")}{searchbox("filter by line or match",("reach","catalog","recipe","confidence"))}</div>
{strip}
{table(HEADS, rows, ["wrap","nm","","",""])}
{pager(p,total,"/links")}</section>"""
    n = counts(c); n["_unbound"] = cov["unbound"]
    c.close()
    return page("Recipe links", body, "/links", [("Condition", "/"), ("Recipe links", None)], n=n)


@app.route("/uncovered")
def uncovered():
    """⚠️ THE GLOBAL COVERAGE-GAP VIEW. Every unbound line corpus-wide, grouped by why.

    The reason is not in the database: link_rule is only written for lines that bound. It comes
    from the matcher, so this page is the live gap list to watch shrink.
    """
    c = db()
    reason = request.args.get("reason") or ""
    qy = (request.args.get("q") or "").strip()
    p = max(1, int(request.args.get("page") or 1))
    rec_id = request.args.get("recipe") or ""
    allrows = unbound_rows(c)
    if rec_id:
        allrows = [r for r in allrows if r["recipe"] == rec_id]
    by = {}
    for r in allrows:
        by[r["reason"]] = by.get(r["reason"], 0) + 1
    rows = [r for r in allrows
            if (not reason or r["reason"] == reason)
            and (not qy or qy.lower() in (r["raw"] or "").lower()
                 or qy.lower() in (r["core"] or "").lower())]
    total = len(rows)
    rec = {x["id"]: x["name"] for x in c.execute("SELECT id,name FROM recipes")}
    page_rows = rows[(p - 1) * PER: p * PER]
    tbl = []
    for r in page_rows:
        label, why = REASONS.get(r["reason"], (r["reason"], ""))
        tbl.append((f'<span class=wrap>{escape(r["raw"])}</span>',
                    f'<span class=dimc>{escape(r["core"] or "")}</span>',
                    taglink(label, f'/uncovered?reason={uq(r["reason"])}', "amber"),
                    rlink(r["recipe"], rec.get(r["recipe"], r["recipe"]))))
    opts = [("", f"all {fmt(len(allrows))}")] + [
        (k, f"{REASONS.get(k,(k,''))[0]} {fmt(v)}") for k, v in sorted(by.items(), key=lambda x: -x[1])]
    keep = f'&recipe={escape(rec_id)}' if rec_id else ''
    groups = "".join(
        f'<div><h3><a href="/uncovered?reason={uq(k)}{keep}">{escape(REASONS.get(k,(k,""))[0])}'
        f' <span class=dimc>{fmt(v)}</span></a></h3>'
        f'<p class=cap>{escape(REASONS.get(k,("",""))[1])}</p></div>'
        for k, v in sorted(by.items(), key=lambda x: -x[1]))
    bits = []
    if rec_id:
        rn = c.execute("SELECT name FROM recipes WHERE id=?", (rec_id,)).fetchone()
        bits.append(f'Uncovered lines in <b>{escape(rn["name"] if rn else rec_id)}</b>.')
    strip = ctx(bits, "/uncovered") if bits else ""
    about = (
      f'<p class=about>Every recipe line that found no catalog row, and why. This is the gap list, '
      f'the thing to watch shrink as the catalog grows. The reason is not stored anywhere. '
      f'<code>link_rule</code> is written only for lines that succeeded, so the reason here comes '
      f'from running the matcher over the corpus at this reading.</p>')
    HEADS = [
      ("line as written", "the ingredient line as the recipe has it", "label, else raw_text"),
      ("parsed to", "what the parser reduced it to before looking", "computed on this reading"),
      ("reason", "why nothing was bound", "computed on this reading"),
      ("recipe", "the recipe the line came from", "recipes.name"),
    ]
    body = f"""<section>
{phead("Not covered", total, "lines", "recipe_ingredients", "", said=about)}
<div class=dist style="border-top:1px solid var(--hair);margin-bottom:18px">{groups}</div>
<div class=filters>{filters("/uncovered","reason",opts,reason,"reason")}{searchbox("filter by line",("reason","recipe"))}</div>
{strip}
{table(HEADS, tbl, ["wrap","","",""], "Nothing uncovered matches.")}
{pager(p,total,"/uncovered")}</section>"""
    n = counts(c); n["_unbound"] = len(allrows)
    c.close()
    return page("Not covered", body, "/uncovered", [("Condition", "/"), ("Not covered", None)], n=n)


@app.route("/recipes")
def recipes():
    c = db()
    qy = (request.args.get("q") or "").strip()
    f = request.args.get("filter") or ""
    p = max(1, int(request.args.get("page") or 1))
    where, args = [], []
    if qy:
        where.append("r.name LIKE ? COLLATE NOCASE"); args.append(f"%{qy}%")
    rcat = request.args.get("category") or ""
    if rcat:
        where.append("r.category=?"); args.append(rcat)
    if f == "gaps":
        where.append("EXISTS(SELECT 1 FROM recipe_ingredients ri WHERE ri.recipe_id=r.id "
                     "AND ri.is_heading=0 AND ri.catalog_id IS NULL)")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM recipes r {w}", args).fetchone()[0]
    dm = recipe_dishes(c)
    rows = []
    for r in c.execute(
            "SELECT r.id, r.name, r.category,"
            " (SELECT COUNT(*) FROM recipe_ingredients ri WHERE ri.recipe_id=r.id AND ri.is_heading=0) n,"
            " (SELECT COUNT(*) FROM recipe_ingredients ri WHERE ri.recipe_id=r.id AND ri.catalog_id IS NOT NULL) k"
            f" FROM recipes r {w} ORDER BY r.name LIMIT ? OFFSET ?", args + [PER, (p - 1) * PER]):
        gap = r["n"] - r["k"]
        pct = (r["k"] / r["n"] * 100) if r["n"] else 0
        rid = uq(r["id"])
        rows.append((f'<span class=nm>{rlink(r["id"], r["name"])}</span>',
                     (f'<span class=dimc><a href="/recipes?category={uq(r["category"])}">'
                      f'{escape(r["category"])}</a></span>') if r["category"]
                       else '<span class=dimc>none</span>',
                     cnt(r["k"], f'/links?recipe={rid}'),
                     cnt(r["n"], f'/r/{rid}'),
                     f'<a href="/r/{rid}" style="color:{"var(--teal)" if pct>=90 else "var(--steel)"}">{pct:.0f}%</a>',
                     (lambda h: dlink(h[0], h[1]) if h else '<span class=zero>none</span>')(dm.get(r["id"])),
                     taglink(f"{gap} uncovered", f'/uncovered?recipe={rid}', "amber") if gap else ""))
    opts = [("", "all"), ("gaps", "with uncovered lines")]
    bits = [f'Recipes filed under <b>{escape(rcat)}</b>.'] if rcat else []
    strip = ctx(bits, "/recipes") if bits else ""
    cov0 = coverage(c)
    about = (
      f'<p class=about>The corpus every link is drawn from. <b>{fmt(cov0["bound"])}</b> of its '
      f'<b>{fmt(cov0["scope"])}</b> ingredient lines found a catalog row, and coverage is that '
      f'share taken one recipe at a time. A low figure is a gap in the catalog rather than a fault '
      f'in the recipe.</p>')
    HEADS = [
      ("recipe", "the recipe, as the corpus names it", "recipes.name"),
      ("category", "the tags it arrived with, filed as one string", "recipes.category"),
      ("bound", "lines that found a catalog row", "catalog_id is set"),
      ("lines", "ingredient lines, headings excluded", "is_heading = 0"),
      ("coverage", "bound as a share of lines", "computed on this reading"),
      ("dish", f"the mined dish this name reduces to, where the corpus has one. {len(dm)} of "
               f"{total} do", "mined_dish"),
      ("", "lines nothing reached, where there are any", "catalog_id is null"),
    ]
    body = f"""<section>
{phead("Recipes", total, "recipes", "recipes", "", said=about)}
<div class=filters>{filters("/recipes","filter",opts,f,"show")}{searchbox("filter by name",("filter","category"))}</div>
{strip}
{table(HEADS, rows, ["nm","","num","num","num","nm",""])}
{pager(p,total,"/recipes")}</section>"""
    c.close()
    return page("Recipes", body, "/recipes", [("Condition", "/"), ("Recipes", None)])


@app.route("/r/<path:rid>")
def recipe(rid):
    """⚠️ THE PER-RECIPE COVERAGE VIEW. What bound, and what did not, with the reason."""
    c = db()
    r = c.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not r:
        c.close()
        return page("Not found", f"<section><h1>No recipe</h1><p class=sub><code>{escape(rid)}</code>"
                    " is not in the corpus.</p></section>", "/recipes",
                    [("Condition", "/"), ("Recipes", "/recipes")]), 404
    why = {x["id"]: x for x in proposals() if x["recipe"] == rid}
    bound, gaps = [], []
    for x in c.execute("SELECT * FROM recipe_ingredients WHERE recipe_id=? AND is_heading=0 "
                       "ORDER BY position", (rid,)):
        if x["catalog_id"]:
            ent = c.execute("SELECT entry_id FROM library_entries WHERE library_id=?",
                            (x["catalog_id"],)).fetchone()
            bound.append((f'<span class=wrap>{escape(x["label"] or x["raw_text"] or "")}</span>',
                          f'<span class=nm>{ilink(x["catalog_id"], x["link_matched"] or x["catalog_id"])}</span>',
                          elink(ent["entry_id"]) if ent else '<span class=dimc>no entry</span>',
                          taglink(x["link_confidence"] or "",
                                  f'/links?confidence={uq(x["link_confidence"] or "")}'),
                          f'<code class=dimc>{escape(x["link_rule"] or "")}</code>'))
        else:
            w = why.get(x["id"])
            reason = w["tier"] if w else "UNMATCHED"
            label, expl = REASONS.get(reason, (reason, ""))
            gaps.append((f'<span class=wrap>{escape(x["label"] or x["raw_text"] or "")}</span>',
                         f'<span class=dimc>{escape((w or {}).get("core") or "")}</span>',
                         taglink(label, f'/uncovered?reason={uq(reason)}', "amber"),
                         f'<span class="dimc wrap">{escape(expl)}</span>'))
    n_all = len(bound) + len(gaps)
    pct = (len(bound) / n_all * 100) if n_all else 0
    gapsec = ""
    if gaps:
        gapsec = f"""<section><h2>Not covered <a class=dimc href="/uncovered?recipe={uq(rid)}">{len(gaps)}</a></h2>
<p class=hint>These lines found no catalog row. The reason comes from running the matcher, since
 the database records a rule only for lines that succeeded.</p>
{table([("line as written","the line as this recipe has it","label, else raw_text"),
        ("parsed to","what the parser reduced it to","computed on this reading"),
        ("reason","why nothing was bound","computed on this reading"),
        ("what that means","the reason in full","computed on this reading")],
       gaps, ["wrap","","","wrap"])}
</section>"""
    else:
        gapsec = ('<section><div class="banner ok">Every ingredient line in this recipe found a '
                  'catalog row.</div></section>')
    # ⚠️ THE ONE PLACE THE TWO CORPORA MEET. Everything else on this page is Andy's own data.
    #    This block is the corpus's opinion of the same dish, and the page keeps them visually
    #    separate rather than blending them into one claim.
    dm = recipe_dishes(c)
    hit = dm.get(rid)
    if hit:
        did, dname, dn = hit
        fbits, fbase = dish_facet_bits(c, did, dn)
        top = list(c.execute(
            "SELECT l.canonical, i.n, i.n_dish FROM mined_dish_ingredient i "
            "JOIN library_names l ON l.library_id=i.library_id "
            "WHERE i.dish_id=? ORDER BY i.n DESC LIMIT 8", (did,)))
        mine = {x["catalog_id"] for x in c.execute(
            "SELECT catalog_id FROM recipe_ingredients WHERE recipe_id=? AND catalog_id IS NOT NULL",
            (rid,))}
        common = list(c.execute(
            f"SELECT l.library_id, l.canonical, i.n, i.n_dish FROM mined_dish_ingredient i "
            f"JOIN library_names l ON l.library_id=i.library_id WHERE i.dish_id=? "
            f"ORDER BY i.n DESC", (did,)))
        have = [x for x in common if x["library_id"] in mine]
        dishsec = f"""<section><h2>As the corpus cooks it</h2>
<p class=cap>This recipe's name reduces to the dish <b>{dlink(did, dname)}</b>, which
 {fmt(dn)} recipes in RecipeNLG also resolve to. Everything in this section is the corpus
 speaking, not this library. It is here to compare against, never to correct with.</p>
<div class=two><dl class=kv>
  <dt>dish</dt><dd>{dlink(did, dname)} <span class=dimc>{fmt(dn)} recipes</span></dd>
  <dt>base</dt><dd>{", ".join(fbase) or '<span class=dimc>not recorded</span>'}</dd>
  <dt>facets</dt><dd>{" ".join(fbits) or '<span class=dimc>none</span>'}</dd></dl>
<dl class=kv>
  <dt>its commonest</dt><dd>{", ".join(f'{escape(x["canonical"])} <span class=dimc>{x["n"]/x["n_dish"]*100:.0f}%</span>' for x in top[:6]) or '<span class=dimc>no profile</span>'}</dd>
  <dt>shared with this recipe</dt><dd>{fmt(len(have))} of {fmt(len(common))}</dd></dl></div>
{table([("ingredient","a catalog row in the corpus profile for this dish","mined_dish_ingredient"),
        ("in","recipes of the dish carrying it","n of n_dish"),
        ("share","that count as a share","n / n_dish"),
        ("this recipe","whether this recipe's lines reached it","recipe_ingredients.catalog_id")],
       [(f'<span class=nm>{ilink(x["library_id"], x["canonical"])}</span>',
         f'{fmt(x["n"])} <span class=dimc>of {fmt(x["n_dish"])}</span>',
         f'{x["n"]/x["n_dish"]*100:.0f}%',
         tag("in this recipe","teal") if x["library_id"] in mine else '<span class=zero>no</span>')
        for x in common[:40]],
       ["nm","num","num",""], "No profile stored for this dish.")}
{f'<p class=note>Showing 40 of {fmt(len(common))}.</p>' if len(common) > 40 else ''}</section>"""
    elif has_dishes(c) and dm:
        dishsec = f"""<section><h2>As the corpus cooks it</h2>
<div class=empty>This recipe's name does not reduce to any of the {fmt(counts(c)["dishes"])} dishes
 the corpus names at least ten times. That is the ordinary answer for {fmt(len(list(c.execute("SELECT 1 FROM recipes"))) - len(dm))} of
 the {fmt(len(list(c.execute("SELECT 1 FROM recipes"))))} recipes here, and it is usually a fact about the
 corpus rather than about the dish. An English-language web corpus under-represents exactly the
 cuisines this library exists to serve.</div></section>"""
    else:
        dishsec = ""

    body = f"""<section><h1>{escape(r["name"])}</h1>
<p class=ident>read from <span class=mono>recipes</span>, with its lines from
 <span class=mono>recipe_ingredients</span></p>
<p class=sub>{f'<a href="/recipes?category={uq(r["category"])}">{escape(r["category"])}</a>' if r["category"] else "uncategorised"}.
 {len(bound)} of {n_all} ingredient lines bound to the catalog, {pct:.0f}%.</p>
<h2>Bound lines <a class=dimc href="/links?recipe={uq(rid)}">{len(bound)}</a></h2>
<p class=cap>Lines that found a catalog row. The ones reaching a written entry are the only ones a
 cook could be shown prose for.</p>
{table([("line as written","the line as this recipe has it","label, else raw_text"),
        ("catalog row","the name it resolved to","catalog_id"),
        ("written entry","prose behind that row, where there is any","library_entries"),
        ("confidence","how the match was made","link_confidence"),
        ("rule","the matcher rule that fired","link_rule")],
       bound, ["wrap","nm","","",""])}</section>
{dishsec}
{gapsec}"""
    c.close()
    return page(r["name"], body, "/recipes",
                [("Condition", "/"), ("Recipes", "/recipes"), (r["name"], None)])


# ════════════════════════════════════════════════════════════════════════════
#  DETAIL PAGES
# ════════════════════════════════════════════════════════════════════════════

@app.route("/i/<path:lid>")
def ingredient(lid):
    c = db()
    row = c.execute("SELECT * FROM library_names WHERE library_id=?", (lid,)).fetchone()
    if not row:
        # ⚠️ ids are not stored in a consistent case across tables (library_siblings holds
        #    q78295261 where library_names holds Q78295261), so an exact miss is retried
        #    case-insensitively before the row is called absent.
        row = c.execute("SELECT * FROM library_names WHERE library_id=? COLLATE NOCASE",
                        (lid,)).fetchone()
        if row:
            lid = row["library_id"]
    if not row:
        c.close()
        return page("Not found", f"<section><h1>No catalog row</h1><p class=sub>"
                    f"<code>{escape(lid)}</code> is not in library_names.</p></section>",
                    "/catalog", [("Condition", "/"), ("Catalog", "/catalog")]), 404
    nb = neighbourhood(c, lid)                    # ⚠️ GOTCHA 1 and 6
    ent = c.execute("SELECT * FROM library_entries WHERE library_id=?", (lid,)).fetchone()
    lines = list(c.execute(
        "SELECT rc.id, rc.name, ri.label, ri.raw_text, ri.link_confidence, ri.link_rule "
        "FROM recipe_ingredients ri JOIN recipes rc ON rc.id=ri.recipe_id "
        "WHERE ri.catalog_id=? ORDER BY rc.name", (lid,)))

    if ent:
        s, live, why = entry_state(c, ent)        # ⚠️ GOTCHA 3
        pp = ent["possible_parent"]
        pp_html = "not recorded"
        if pp:
            hit = c.execute("SELECT library_id FROM library_names WHERE canonical=? COLLATE NOCASE",
                            (pp,)).fetchone()
            pp_html = ilink(hit["library_id"], pp) if hit else escape(pp)
        stale = "" if s == ent["link_state"] else f' {tag("stored says "+ent["link_state"],"amber")}'
        idsec = f"""<div class=two><dl class=kv>
  <dt>written entry</dt><dd><a href="/e/{uq(ent["entry_id"])}">{escape(ent["entry_id"])}</a></dd>
  <dt>state</dt><dd>{tag(s,"teal" if s=="linked" else "amber")}{stale}
    {f'<div class=note>{escape(why)}</div>' if why else ''}</dd>
  <dt>form</dt><dd>{escape(ent["form"] or "not recorded")}</dd></dl>
<dl class=kv>
  <dt>cuisine</dt><dd>{escape(ent["cuisine"] or "not recorded")}</dd>
  <dt>possible parent</dt><dd>{pp_html}</dd>
  <dt>review state</dt><dd>{escape(ent["review_state"])}</dd></dl></div>"""
    else:
        n_ent = c.execute("SELECT COUNT(*) FROM library_entries").fetchone()[0]
        n_all = c.execute("SELECT COUNT(*) FROM library_names").fetchone()[0]
        idsec = (f'<p class=sub>No written entry. This is a plain catalog row, which is the common '
                 f'case: only {fmt(n_ent)} of the {fmt(n_all)} rows have prose behind them.</p>')

    kp = lambda ks: " ".join(taglink(human("kind", k), f'/relations?kind={uq(k)}') for k in ks)
    conf_t = lambda v: taglink(human("confidence", v), f'/relations?confidence={uq(v)}') if v else ""
    src_t = lambda v: (f'<span class=dimc><a href="/relations?source={uq(v)}">{escape(v)}</a></span>'
                       if v else "")
    cat_rows = [(f'<span class=nm>{clink(x["id"], x["label"])}</span>',
                 taglink(human("kind","in_category"), "/relations?kind=in_category"), conf_t(x["confidence"]),
                 src_t(x["source"])) for x in nb["category"]]
    par_rows = [(f'<span class=nm>{ilink(x["id"], x["label"])}</span>', kp(x["kinds"]),
                 conf_t(x["confidence"]), src_t(x["source"]))
                for x in nb["parent"]]
    kid_rows = [(f'<span class=nm>{ilink(x["id"], x["label"])}</span>', kp(x["kinds"]),
                 conf_t(x["confidence"]), "") for x in nb["child"][:200]]
    # ⚠️ GOTCHA 1 again: a sibling is reached through a shared parent, and that parent is a
    #    category on an in-category edge and a catalog row on any other.
    sib_rows = [(f'<span class=nm>{ilink(x["id"], x["label"])}</span>',
                 taglink(human("kind", x["kind"]), f'/relations?kind={uq(x["kind"])}'),
                 f'<span class=dimc>through {plink(x["kind"], x["via"], x["via_label"])}</span>', "")
                for x in nb["sibling"][:100]]
    line_rows = [(f'<span class=wrap>{escape(r["label"] or r["raw_text"] or "")}</span>',
                  rlink(r["id"], r["name"]),
                  taglink(r["link_confidence"] or "", f'/links?confidence={uq(r["link_confidence"] or "")}'),
                  f'<code class=dimc>{escape(r["link_rule"] or "")}</code>') for r in lines]
    # ⚠️ counted at this reading. Both figures used to be written into the string, and the first
    #    had already drifted from 53 to 56 without anything noticing.
    # ⚠️ THE REVERSE OF /dish/<id>. Without this the dish pages link INTO the catalog and nothing
    #    links back out, which makes the tie-in one-directional and effectively invisible from
    #    the side Andy starts on. Guarded the same way the nav count is: the dish tables are
    #    derived from a corpus that is not in the repository.
    dish_base, dish_use, n_base, n_use = [], [], 0, 0
    if has_dishes(c):
        n_base = c.execute("SELECT COUNT(*) FROM mined_dish_base WHERE library_id=?",
                           (lid,)).fetchone()[0]
        n_use = c.execute("SELECT COUNT(*) FROM mined_dish_ingredient WHERE library_id=?",
                          (lid,)).fetchone()[0]
        dish_base = list(c.execute(
            "SELECT d.dish_id, d.dish, d.n FROM mined_dish_base b JOIN mined_dish d "
            "ON d.dish_id=b.dish_id WHERE b.library_id=? ORDER BY d.n DESC LIMIT 60", (lid,)))
        # ⚠️ ORDERED BY SHARE, NOT BY COUNT. By raw count this list is just the biggest dishes in
        #    the corpus over and over. `chicken 10,262` outranks `guacamole 899` for avocado on
        #    count and says nothing, where share says avocado is 92% of a guacamole.
        dish_use = list(c.execute(
            "SELECT d.dish_id, d.dish, i.n, i.n_dish, (i.n * 1.0 / i.n_dish) share "
            "FROM mined_dish_ingredient i JOIN mined_dish d ON d.dish_id=i.dish_id "
            "WHERE i.library_id=? ORDER BY share DESC, i.n DESC LIMIT 60", (lid,)))
    base_rows = [(f'<span class=nm>{dlink(x["dish_id"], x["dish"])}</span>', fmt(x["n"]))
                 for x in dish_base]
    use_rows = [(f'<span class=nm>{dlink(x["dish_id"], x["dish"])}</span>',
                 f'{fmt(x["n"])} <span class=dimc>of {fmt(x["n_dish"])}</span>',
                 f'{x["share"]*100:.0f}%') for x in dish_use]

    n_used = c.execute("SELECT COUNT(DISTINCT catalog_id) FROM recipe_ingredients "
                       "WHERE catalog_id IS NOT NULL").fetchone()[0]
    n_rows = c.execute("SELECT COUNT(*) FROM library_names").fetchone()[0]
    dup = ('<p class=note>Two kinds to one parent are shown together on a single row rather than '
           'duplicated.</p>' if any(len(x["kinds"]) > 1 for x in nb["parent"]) else "")

    body = f"""<section><h1>{escape(row["canonical"])}</h1>
<p class=sub><span class=mono>{escape(lid)}</span> · <a href="/g/{uq(lid)}">open the graph</a></p>
<p class=ident>read from <span class=mono>library_names</span>, with its edges from
 <span class=mono>library_relations</span></p>
{idsec}</section>
<section><h2>Category and hierarchy</h2>
<div class=two>
  <div><h3>Category <a class=dimc href="/relations?child={uq(lid)}&amp;kind=in_category">{fmt(len(nb["category"]))}</a></h3>
  <p class=cap>The browsable family this row is filed under.</p>
  {table([("category","the family it is filed under","library_categories.name"),
          ("kind","always in-category here","kind"),
          ("confidence","how firmly the filing stands","confidence"),
          ("source","where the filing came from","source")],
         cat_rows, ["nm","","",""], "In no category.")}</div>
  <div><h3>Parents <a class=dimc href="/relations?child={uq(lid)}&amp;kind=hierarchy">{fmt(len(nb["parent"]))}</a></h3>
  <p class=cap>Broader rows above this one. <b>Is a kind of</b> means the same stuff named more
   narrowly. <b>Is made from</b> means one ingredient turned into another.</p>
  {table([("parent","the broader row above this one","parent_id"),
          ("kind","is a kind of, or is made from","kind"),
          ("confidence","how firmly it stands","confidence"),
          ("source","where it came from","source")],
         par_rows, ["nm","","",""], "No parent.")}{dup}</div>
</div>
<h3 style="margin-top:26px">Children <a class=dimc href="/relations?parent={uq(lid)}&amp;kind=hierarchy">{fmt(len(nb["child"]))}</a></h3>
<p class=cap>Narrower rows that sit below this one. Most rows have none.</p>
{table([("child","the narrower row below this one","child_id"),
        ("kind","is a kind of, or is made from","kind"),
        ("confidence","how firmly it stands","confidence"),("",""," ")],
       kid_rows, ["nm","","",""], "No children.")}
{f'<p class=note>Showing 200 of {fmt(len(nb["child"]))}.</p>' if len(nb["child"])>200 else ''}
<h3 style="margin-top:26px">Siblings <span class=dimc>{fmt(len(nb["sibling"]))}</span></h3>
<p class=cap>Rows that share a parent with this one. Not stored anywhere, worked out on this
 reading by looking at what else hangs off the same parent.</p>
{table([("sibling","another row under the same parent","child_id"),
        ("kind","the relation both of them carry","kind"),
        ("reached through","the parent they share","parent_id"),("",""," ")],
       sib_rows, ["nm","","",""], "No siblings.")}
</section>
<section><h2>Dishes <span class=dimc>{fmt(n_use)}</span></h2>
<p class=cap>What the corpus cooks with this, counted over 2,231,142 recipes. {
 "Nothing in this library's own recipes uses it yet, so the section below is empty and this one "
 "is not. That gap is the point of reading a corpus at all."
 if not lines else
 f"The {fmt(len(lines))} ingredient lines below are a different question and the two are worth "
 f"not reading as one. The corpus says what people cook. The lines say what has been cooked here."
}</p>
<div class=two>
  <div><h3>Dishes this is the base of <a class=dimc href="/dishes">{fmt(n_base)}</a></h3>
  <p class=cap>Dishes whose name says they are made of this.</p>
  {table([("dish", "the dish this row is the base of", "mined_dish_base"),
          ("recipes", "how many recipes resolved to that dish", "mined_dish.n")],
         base_rows, ["nm", "num"], "No dish is built on this row.")}
  {f'<p class=note>Showing 60 of {fmt(n_base)}.</p>' if n_base > 60 else ''}</div>
  <div><h3>Dishes that use it <span class=dimc>{fmt(n_use)}</span></h3>
  <p class=cap>Ordered by share rather than by count, so a dish this is characteristic OF ranks
   above a dish that is merely large.</p>
  {table([("dish", "a dish whose profile carries this row", "mined_dish_ingredient"),
          ("in", "recipes of that dish carrying it", "n of n_dish"),
          ("share", "that count as a share of the dish", "n / n_dish")],
         use_rows, ["nm", "num", "num"], "No dish profile carries this row.")}
  {f'<p class=note>Showing the 60 highest shares of {fmt(n_use)}.</p>' if n_use > 60 else ''}</div>
</div></section>
<section><h2>Recipe uses <a class=dimc href="/links?catalog={uq(lid)}">{fmt(len(lines))}</a></h2>
<p class=cap>Every ingredient line in the corpus that resolved to this row. Zero means nothing has
 been cooked with it yet, which is true of all but {fmt(n_used)} of the {fmt(n_rows)} rows.</p>
{table([("line as written","the line as the recipe has it","label, else raw_text"),
        ("recipe","the recipe it came from","recipes.name"),
        ("confidence","how the match was made","link_confidence"),
        ("rule","the matcher rule that fired","link_rule")],
       line_rows, ["wrap","","",""], "This row is not used in any recipe.")}</section>"""
    c.close()
    return page(row["canonical"], body, "/catalog",
                [("Condition", "/"), ("Catalog", "/catalog"), (row["canonical"], None)])


@app.route("/e/<entry_id>")
def entry(entry_id):
    c = db()
    e = c.execute("SELECT * FROM library_entries WHERE entry_id=?", (entry_id,)).fetchone()
    if not e:
        c.close()
        return page("Not found", f"<section><h1>No entry</h1><p class=sub>"
                    f"<code>{escape(entry_id)}</code> is not a written entry.</p></section>",
                    "/entries", [("Condition", "/"), ("Entries", "/entries")]), 404
    s, live, why = entry_state(c, e)              # ⚠️ GOTCHA 3

    # ⚠️ GOTCHA 5: an entry can legitimately carry no library_id.
    if not e["library_id"]:
        head = ('<div class=banner>This entry has <b>no catalog row</b>, so it has no relations '
                'and no recipe links. That is a normal state rather than an error, and its written '
                'detail below is complete.</div>')
    else:
        stale = "" if s == e["link_state"] else f' {tag("stored says "+e["link_state"],"amber")}'
        head = (f'<dl class=kv><dt>catalog row</dt><dd>{ilink(e["library_id"], live or e["library_id"])} '
                f'<span class="mono dimc">{ilink(e["library_id"])}</span></dd>'
                f'<dt>state</dt><dd>{tag(s,"teal" if s=="linked" else "amber")}{stale}'
                + (f'<div class=note>{escape(why)}</div>' if why else "") + '</dd></dl>')

    prose = list(c.execute(
        "SELECT p.*, (SELECT group_concat(d.key,' + ') FROM library_prose_derived_from d "
        " WHERE d.entry_id=p.entry_id AND d.slot=p.slot AND d.position=p.position) df "
        "FROM library_prose_pieces p WHERE p.entry_id=? ORDER BY p.slot,p.position", (entry_id,)))
    def _rests(df):
        if not df:
            return "no claim behind it"
        inner = " + ".join(f'<a href="/prose?key={uq(k.strip())}">{escape(k.strip())}</a>'
                           for k in df.split(" + "))
        return f'rests on <code>{inner}</code>'
    SRC = entry_sources(c, entry_id)

    def _read_from(df):
        """the sources behind every claim this piece rests on, de-duplicated, order kept"""
        seen, pairs = set(), []
        for k in (df or "").split(" + "):
            for sl, u in SRC.get(k.strip(), []):
                if sl not in seen:
                    seen.add(sl); pairs.append((sl, u))
        return f' read from {srcbits(pairs)}' if pairs else ""

    prose_html = "".join(
        f'<p>{escape(r["text"])}</p><div class=meta>'
        + taglink(r["derived_tier"], f'/prose?tier={uq(r["derived_tier"])}',
                  "teal" if r["derived_tier"] == "curated" else "") + ' '
        + _rests(r["df"]) + _read_from(r["df"]) + '</div>'
        for r in prose) or '<div class=empty>No prose.</div>'

    claims = [(f'<code><a href="/prose?key={uq(r["key"])}">{escape(r["key"])}</a></code>',
               taglink(r["tier"], f'/prose?tier={uq(r["tier"])}', "teal" if r["tier"]=="curated" else ""),
               srcbits(SRC.get(r["key"], [])) or '<span class=dimc>none</span>',
               f'<span class=dimc>{escape(r["state"])}</span>',
               f'<span class=wrap>{escape(r["text"])}</span>')
              for r in c.execute("SELECT * FROM library_assertions WHERE entry_id=? "
                                 "AND assertion_kind='claim' ORDER BY position", (entry_id,))]
    flags = [(f'<code>{escape(r["key"])}</code>', tag(r["flag_kind"] or "", "amber"),
              escape(r["allergen"] or r["hazard"] or ""),
              tag("surfaces", "teal") if r["surfaces"] else '<span class=dimc>hidden</span>',
              f'<span class=wrap>{escape(r["text"])}</span>')
             for r in c.execute("SELECT * FROM library_assertions WHERE entry_id=? "
                                "AND assertion_kind='safety_flag' ORDER BY position", (entry_id,))]
    canon_j, def_j = [], []
    for r in c.execute("SELECT * FROM library_judgements WHERE entry_id=? ORDER BY position", (entry_id,)):
        if r["shape"] == "canonical":
            canon_j.append((f'<code>{escape(r["judgement_id"] or "")}</code>', escape(r["kind"] or ""),
                            f'<span class=wrap>{escape(r["decided"] or "")}</span>',
                            f'<span class=dimc>{escape(r["alternatives"] or "")}</span>',
                            f'<span class=dimc>{escape(r["falsifier"] or "")}</span>'))
        else:
            def_j.append((f'<code>{escape(r["judgement_key"] or "")}</code>', escape(r["about"] or ""),
                          f'<span class=dimc>{escape(r["author"] or "")}</span>',
                          f'<span class=wrap>{escape(r["body"] or "")}</span>'))
    chains = [(f'<code>{escape(r["key"])}</code>', srclink(r["source_slug"], r["url"]), tag(r["mode"]),
               escape(r["read_depth"]), f'<span class=wrap>{escape((r["taken"] or "")[:340])}</span>')
              for r in c.execute("SELECT ch.*, s.url FROM library_chains ch LEFT JOIN "
                                 "library_sources s ON s.source_slug=ch.source_slug "
                                 "WHERE ch.entry_id=? ORDER BY ch.position", (entry_id,))]
    disc = [(f'<code>{escape(r["key"])}</code>', f'<span class=dimc>{escape(r["author"])}</span>',
             f'<span class=wrap>{escape(r["body"])}</span>')
            for r in c.execute("SELECT * FROM library_discussions WHERE entry_id=? ORDER BY position", (entry_id,))]
    forms = [(escape(r["form"]), tag(r["kind"]), f'<span class="dimc wrap">{escape(r["note"] or "")}</span>')
             for r in c.execute("SELECT * FROM library_forms WHERE entry_id=? ORDER BY position", (entry_id,))]
    # ⚠️ GOTCHA 2: sibling_id is stored LOWERCASE. Without COLLATE NOCASE this joins to nothing and
    #    the panel renders empty rather than erroring.
    # ⚠️ GOTCHA 2, one layer further than the join. Fixing the JOIN with COLLATE NOCASE still left
    #    the LINK built from the sibling row's own lowercase spelling, and /i/q78295261 is a 404
    #    while /i/Q78295261 is the record. The real id is selected alongside the name and the door
    #    is built from that, so the panel resolves and the link lands.
    sibs = [(f'<span class=nm>{ilink(r["real_id"] or r["sibling_id"], r["canonical"] or r["sibling_id"])}</span>',
             f'<span class=wrap>{escape(r["why_separate"] or "")}</span>',
             f'<span class=dimc>stored as <code>{escape(r["sibling_id"])}</code>, '
             f'resolved case-insensitively to <code>{escape(r["real_id"] or "nothing")}</code></span>')
            for r in c.execute(
                "SELECT s.sibling_id, s.why_separate, ln.canonical, ln.library_id real_id "
                "FROM library_siblings s "
                "LEFT JOIN library_names ln ON ln.library_id = s.sibling_id COLLATE NOCASE "
                "WHERE s.entry_id=? ORDER BY s.position", (entry_id,))]

    sec = lambda t, n, h: f'<h2 style="margin-top:26px">{escape(t)} <span class=dimc>{n}</span></h2>{h}'
    body = f"""<section><h1>{escape(e["name"])}</h1>
<p class=ident>read from <span class=mono>library_entries</span>, with its writing from
 <span class=mono>library_prose_pieces</span> and <span class=mono>library_assertions</span></p>
<p class=sub>Entry <span class=mono>{escape(entry_id)}</span> · review state {escape(e["review_state"])}
 · <a href="/prose?entry={uq(entry_id)}">its {fmt(len(prose))} sentences</a>
 · <span class=dimc>{escape(e["source_file"])}</span></p>
{head}</section>
<section><h2>Description</h2><div class=prose>{prose_html}</div></section>
<section>
{sec("Claims", len(claims),
     '<p class=cap>A claim is one statement about the ingredient that a written sentence can rest '
     'on. Stored beside the safety flags, told apart by <span class=mono>assertion_kind</span>.</p>'
     + table([("key","the handle a sentence cites","key"),
              ("tier","how well grounded. curated, cited or generated","tier"),
              ("source","where it was read from. Opens the source itself","library_sources.url"),
              ("state","settled, or still open","state"),
              ("text","the claim itself","text")],
             claims, ["","","","","wrap"], "No claims."))}
{sec("Safety flags", len(flags),
     '<p class=cap>An allergen or a hazard. The same table as the claims above, with '
     '<span class=mono>assertion_kind</span> set to safety_flag instead of claim.</p>'
     + table([("key","the handle it is stored under","key"),
              ("kind","what sort of warning","flag_kind"),
              ("allergen or hazard","the thing being warned about","allergen, hazard"),
              ("shown","whether a cook is shown it","surfaces"),
              ("text","the warning itself","text")],
             flags, ["","","","","wrap"], "No safety flags."))}
{sec("Judgments, decisions taken", len(canon_j),
     '<p class=cap>A call that was made, with what it rules out and what would overturn it. Shares '
     'a table with the deferred ones, told apart by <span class=mono>shape</span>.</p>'
     + table([("id","the handle the decision is stored under","judgement_id"),
              ("kind","what sort of decision","kind"),
              ("decided","what was settled","decided"),
              ("alternatives","what it rules out","alternatives"),
              ("falsifier","what would overturn it","falsifier")],
             canon_j, ["","","wrap","",""], "None."))}
{sec("Judgments, decisions deferred", len(def_j),
     '<p class=cap>A question raised and left open on purpose.</p>'
     + table([("key","the handle it is stored under","judgement_key"),
              ("about","what it concerns","about"),
              ("author","who raised it","author"),
              ("body","the question","body")],
             def_j, ["","","","wrap"], "None."))}
{sec("Source chains", len(chains),
     '<p class=cap>Where a claim was read from, and how far into the source the reader went.</p>'
     + table([("claim","the claim this chain backs","key"),
              ("source","the source it was read from","source_slug"),
              ("mode","how it was read","mode"),
              ("depth","how far in","read_depth"),
              ("what was taken","the passage relied on","taken")],
             chains, ["","","","","wrap"], "No chains."))}
{sec("Discussion", len(disc),
     '<p class=cap>Notes left against a claim while it was being written.</p>'
     + table([("claim","the claim being discussed","key"),
              ("author","who left it","author"),("body","the note","body")],
             disc, ["","","wrap"], "No discussion."))}
{sec("Forms", len(forms),
     '<p class=cap>The shapes this ingredient is bought or used in.</p>'
     + table([("name","the form","form"),("kind","what sort of form","kind"),
              ("note","anything worth saying about it","note")],
             forms, ["","","wrap"], "No forms recorded."))}
{sec("Siblings", len(sibs),
     '<p class=cap>Rows kept deliberately apart from this one, with the reason. Recorded by hand so '
     'a later merge does not quietly undo the decision.</p>'
     + table([("separate row","the row held apart","sibling_id"),
              ("why separate","the reason it was kept apart","why_separate"),("",""," ")],
             sibs, ["nm","wrap",""], "No siblings recorded."))}
</section>"""
    c.close()
    return page(e["name"], body, "/entries",
                [("Condition", "/"), ("Entries", "/entries"), (e["name"], None)])


@app.route("/c/<path:cid>")
def category(cid):
    c = db()
    cat = c.execute("SELECT * FROM library_categories WHERE category_id=?", (cid,)).fetchone()
    if not cat:
        c.close()
        return page("Not found", f"<section><h1>No category</h1><p class=sub>"
                    f"<code>{escape(cid)}</code> is not in the vocabulary.</p></section>",
                    "/categories", [("Condition", "/"), ("Categories", "/categories")]), 404
    members, twin = category_members(c, cid)      # ⚠️ GOTCHA 4
    split = ""
    if twin:
        a = sum(1 for m in members if m["via"] == "in_category")
        split = (f'<div class=banner>⚠️ <b>Split parent representation.</b> {a} members reach this '
                 f'category through the slug <code>{escape(cid)}</code>, and {len(members)-a} more '
                 f'through the catalog row {ilink(twin)} that shares its name. Asking about only '
                 f'the slug understates the membership, so both paths are gathered below.</div>')
    rows = []
    for m in members:
        mid = uq(m["id"])
        # 'reached through' names how the edge was found. The in-category path is the slug itself,
        # the other is the catalog row sharing the name, so each points at its own record.
        via = (clink(cid, "in-category") if m["via"] == "in_category"
               else ilink(twin, "kind-of on the catalog row") if twin
               else escape(m["via"]))
        rows.append((
            f'<span class=nm>{ilink(m["id"], m["label"])}</span>',
            taglink(m["confidence"], f'/relations?confidence={uq(m["confidence"])}'),
            f'<span class=dimc><a href="/relations?source={uq(m["source"])}">{escape(m["source"])}</a></span>',
            f'<span class=dimc>{via}</span>',
            cnt(c.execute("SELECT COUNT(*) FROM recipe_ingredients WHERE catalog_id=?",
                          (m["id"],)).fetchone()[0] or 0, f'/links?catalog={mid}')))
    kids = list(c.execute("SELECT category_id, name FROM library_categories WHERE parent_slug=? "
                          "ORDER BY name", (cid,)))
    kidsec = ""
    if kids:
        kidsec = ('<h2 style="margin-top:26px">Categories nested under this one '
                  f'<span class=dimc>{len(kids)}</span></h2>'
                  '<p class=cap>Narrower families filed beneath this one. Only one category in the '
                  'whole vocabulary carries a parent, so this is nearly always empty.</p>'
                  + table([("category", "the narrower family", "category_id"),
                           ("members", "rows filed under it", "in_category, kind_of")],
                          [(f'<span class=nm>{clink(k["category_id"], k["name"])}</span>',
                            cnt(len(category_members(c, k["category_id"])[0]), f'/c/{uq(k["category_id"])}'))
                           for k in kids], ["nm", "num"]))
    # ⚠️ A CATEGORY REACHES DISHES ONLY THROUGH ITS MEMBERS' BASES, never directly. There is no
    #    dish-to-category edge and inventing one would be a claim the data does not make. This
    #    asks a narrower and true question: which dishes are built on a row filed under this
    #    family. Measured: 45 of the 256 categories reach at least one dish, and the rest reach
    #    none because their members are seasonings and compounds rather than what a dish is
    #    made OF. An empty section here is the ordinary answer.
    dishsec = ""
    if has_dishes(c) and members:
        ids = [m["id"] for m in members]
        qm = ",".join("?" * len(ids))
        drows = list(c.execute(
            f"SELECT d.dish_id, d.dish, d.n, l.canonical, b.library_id "
            f"FROM mined_dish_base b JOIN mined_dish d ON d.dish_id=b.dish_id "
            f"JOIN library_names l ON l.library_id=b.library_id "
            f"WHERE b.library_id IN ({qm}) ORDER BY d.n DESC LIMIT 60", ids))
        ndish = c.execute(f"SELECT COUNT(DISTINCT dish_id) FROM mined_dish_base "
                          f"WHERE library_id IN ({qm})", ids).fetchone()[0]
        dishsec = f"""<h2 style="margin-top:26px">Dishes built on this family
 <span class=dimc>{fmt(ndish)}</span></h2>
<p class=cap>Dishes whose base is one of the rows above. Reached through the member, not stored
 as an edge, so a dish appears here only when the corpus says it is made OF something in this
 family.</p>
{table([("dish","a dish whose base sits in this family","mined_dish_base"),
        ("base","the member row it is built on","library_id"),
        ("recipes","how many recipes resolved to that dish","mined_dish.n")],
       [(f'<span class=nm>{dlink(x["dish_id"], x["dish"])}</span>',
         ilink(x["library_id"], x["canonical"]), fmt(x["n"])) for x in drows],
       ["nm","nm","num"], "No dish in the corpus is built on a row from this family.")}
{f'<p class=note>Showing the 60 commonest of {fmt(ndish)}.</p>' if ndish > 60 else ''}"""

    body = f"""<section><h1>{escape(cat["name"])}</h1>
<p class=ident>read from <span class=mono>library_categories</span>, with its members from
 <span class=mono>library_relations</span></p>
<p class=sub>Category <span class=mono>{escape(cid)}</span>
 {"· nested under " + clink(cat["parent_slug"]) if cat["parent_slug"] else ""}
 · <a href="/relations?parent={uq(cid)}&amp;kind=in_category">its in-category edges</a></p>
{f'<p class=sub>{escape(cat["note"])}</p>' if cat["note"] else ''}
{split}
<h2>Members <span class=dimc>{fmt(len(members))}</span></h2>
<p class=cap>Every row filed under this family. A category is something you browse, which is not
 the same as a kind-of parent, and a row can sit in one without having the other.</p>
{table([("ingredient","the row filed under this family","child_id"),
        ("confidence","how firmly the filing stands","confidence"),
        ("source","where the filing came from","source"),
        ("reached through","which of the two paths found it","kind"),
        ("lines","recipe lines that resolved to it","catalog_id")],
       rows, ["nm","","","","num"], "No members.")}
{dishsec}
{kidsec}</section>"""
    c.close()
    return page(cat["name"], body, "/categories",
                [("Condition", "/"), ("Categories", "/categories"), (cat["name"], None)])


@app.route("/search")
def search():
    qy = (request.args.get("q") or "").strip()
    if not qy:
        return page("Search", '<section><h1>Search</h1><p class=sub>Look for a catalog row, a '
                    'written entry, a category or a recipe.</p><div class=filters>'
                    + searchbox("what are you looking for") + '</div></section>', "/search",
                    [("Condition", "/"), ("Search", None)])
    c = db()
    other = [(f'<span class=nm><a href="/c/{uq(r["category_id"])}">{escape(r["name"])}</a></span>',
              tag("category"), "", "") for r in c.execute(
              "SELECT * FROM library_categories WHERE name LIKE ? COLLATE NOCASE", (f"%{qy}%",))]
    other += [(f'<span class=nm><a href="/e/{uq(r["entry_id"])}">{escape(r["entry_id"])}</a></span>',
               tag("written entry", "teal"), "", "") for r in c.execute(
               "SELECT * FROM library_entries WHERE entry_id LIKE ? OR name LIKE ? COLLATE NOCASE",
               (f"%{qy}%", f"%{qy}%"))]
    other += [(f'<span class=nm><a href="/r/{uq(r["id"])}">{escape(r["name"])}</a></span>',
               tag("recipe"), "", "") for r in c.execute(
               "SELECT * FROM recipes WHERE name LIKE ? COLLATE NOCASE LIMIT 25", (f"%{qy}%",))]
    rows = [(f'<span class=nm>{ilink(r["library_id"], r["canonical"])}</span>',
             f'<span class="mono dimc">{ilink(r["library_id"])}</span>',
             cnt(r["lines"], f'/links?catalog={uq(r["library_id"])}'),
             cnt(r["edges"], f'/relations?child={uq(r["library_id"])}'))
            for r in c.execute(
        "SELECT ln.library_id, ln.canonical, "
        " (SELECT COUNT(*) FROM recipe_ingredients ri WHERE ri.catalog_id=ln.library_id) lines, "
        " (SELECT COUNT(*) FROM library_relations lr WHERE lr.child_id=ln.library_id "
        "   OR (lr.parent_id=ln.library_id AND lr.kind<>'in_category')) edges "
        "FROM library_names ln WHERE ln.canonical LIKE ? COLLATE NOCASE "
        "ORDER BY lines DESC, LENGTH(ln.canonical) LIMIT 200", (f"%{qy}%",))]
    about = (f'<p class=about>Anything whose name contains <b>{escape(qy)}</b>. Catalog rows are '
             f'ordered by how often a recipe reached them, so the ones you have actually cooked '
             f'with come first.</p>')
    body = f"""<section>
{phead(qy, len(other) + len(rows), "matches", "library_names, library_entries, library_categories, recipes", "", said=about)}
<div class=filters>{searchbox("search again")}</div>
<h2>Categories, entries and recipes <span class=dimc>{len(other)}</span></h2>
{table([("name","the record that matched","name, entry_id or recipes.name"),
        ("what","which of the three it is","the table it came from"),("",""," "),("",""," ")],
       other, ["nm","","",""], "Nothing of that kind.")}
<h2 style="margin-top:26px">Catalog rows <span class=dimc>{len(rows)}</span></h2>
{table([("ingredient","the name as the library spells it","canonical"),
        ("library_id","the stored id","library_id"),
        ("lines","recipe lines that resolved here","catalog_id"),
        ("edges","relations touching this row, either direction","library_relations")],
       rows, ["nm","","num","num"], "No catalog row matches.")}
</section>"""
    c.close()
    return page(f"search {qy}", body, "/search", [("Condition", "/"), (f'search “{qy}”', None)])


# ════════════════════════════════════════════════════════════════════════════
#  GRAPH
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
#  SUBSTITUTIONS. The corpus proposes, a person disposes, the hand file records it.
#
#  ⚠️ THE ONLY WRITE SURFACE ON THIS INSTRUMENT, and it writes a CSV, never the database. See
#     the second warning in the module docstring. mined_substitution_candidates is a queue that
#     the next mining run rebuilds whole, so a decision kept in recipes.db would be re-proposed
#     the next morning and lost the morning after. hand_substitutions.csv is in git and is
#     replayed by load_substitutions.py, so a decision written there survives both.
# ════════════════════════════════════════════════════════════════════════════

SUB_SORT = {"n": "s.n", "reverse": "s.n_reverse", "from": "f.canonical COLLATE NOCASE",
            "to": "t.canonical COLLATE NOCASE"}
STATE_TAG = {"confirmed": "teal", "rejected": "amber", "pending": ""}


def hand_rows():
    """Every line of the hand file, in the order it was written. Read fresh on every request,
    like everything else here. The file is small and a cached decision is a wrong decision."""
    if not os.path.exists(HAND):
        return []
    import importlib, sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import load_substitutions
    importlib.reload(load_substitutions)
    return load_substitutions.read(HAND)


def hand_state():
    """(from, to) -> the winning decision. ⚠️ THE LAST LINE FOR A PAIR WINS, because the file is
    appended to and never edited. Changing your mind about butter to margarine writes a second
    line, and the first stays as a record that you once thought otherwise."""
    return {(r["from"], r["to"]): r for r in hand_rows()}


def append_decision(frm, to, decision, ratio="", note="", n=""):
    """⚠️ THE ONE WRITER. Every path that records a decision comes through here.

    It resolves both ids against the catalog and refuses rather than skipping, the same rule
    load_relations.py states: a skipped row is a silent no-op, and Phase C measured what those
    cost. The canonical names are snapshotted into the line, the way library_relations keeps
    child_canonical, so a later rename is diagnosable by reading the line.
    """
    if decision not in ("confirmed", "rejected", "authored"):
        return f"decision {decision!r} is not one of confirmed, rejected, authored"
    if not frm or not to:
        return "a substitution needs both sides"
    c = db()
    names = {}
    for side in (frm, to):
        r = c.execute("SELECT library_id, canonical FROM library_names WHERE library_id=? "
                      "OR canonical=? COLLATE NOCASE", (side, side)).fetchone()
        if not r:
            c.close()
            return (f"{side} is not a catalog row. use the library_id, or the name as the "
                    f"catalog spells it")
        names[side] = (r["library_id"], r["canonical"])
    if names[frm][0] == names[to][0]:
        c.close()
        return "both sides are the same row"
    if not n:
        row = c.execute("SELECT n FROM mined_substitution_candidates WHERE from_id=? AND to_id=?",
                        (names[frm][0], names[to][0])).fetchone()
        n = str(row["n"]) if row else ""
    c.close()
    if decision == "authored" and not note.strip():
        return "an authored substitution needs a note. nothing proposed it, so say why it is there"
    if ratio:
        try:
            float(ratio)
        except ValueError:
            return f"ratio {ratio!r} is not a number. leave it blank when it is not a fixed one"
    # ⚠️ APPEND, in one line, with the csv writer rather than a format string. A note carrying a
    #    comma would otherwise shift every column after it and the loader would refuse the file.
    with open(HAND, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([names[frm][0], names[frm][1], names[to][0], names[to][1],
                                 decision, ratio.strip(), n, note.strip(),
                                 datetime.date.today().isoformat()])
    return None


# ── dishes ─────────────────────────────────────────────────────────────────────────────────────
# ⚠️ THE UNIT HERE IS THE DISH, NOT THE RECIPE. Every figure on these two pages is a count over
#    the corpus, and no row refers to a recipe or can be traced back to one. That is boundary (c)
#    in docs/mining-decision.md, and it is why the column is `recipes` rather than a list of them.
#
# ⚠️ EVERY INGREDIENT ON THESE PAGES IS A DOOR. base, accompaniment and the profile all store a
#    library_id rather than a word, so each one links to /i/<lid> and lands on the same catalog
#    row the rest of the bench already knows about. That link is the whole reason the facets store
#    ids, and an earlier draft that stored the vocabulary word instead could not have drawn it.

DISH_FACETS = [("form", "mined_dish_form", "dish_type"),
               ("method", "mined_dish_method", "method"),
               ("diet", "mined_dish_diet", "diet"),
               ("structural", "mined_dish_structural", "structural"),
               ("appliance", "mined_dish_appliance", "appliance")]


def dish_missing():
    """The page every dish route returns when the corpus has never been read here."""
    return page("Dishes", '<section><h1>Dishes</h1>'
                '<p class=ident>read from <span class=mono>mined_dish</span></p>'
                '<div class=empty>No dish facets here. They are derived from RecipeNLG, which is '
                'not in the repository, so empty is the correct state for a fresh clone. '
                'Regenerate with dish_facet_run.py and load_dish_facets.py.</div></section>',
                "/dishes", [("Condition", "/"), ("Dishes", None)])


# ── a recipe's dish, resolved on the fly ───────────────────────────────────────────────────────
# ⚠️ THE 298 RECIPES ARE NOT IN THE MINED DATA AND CANNOT BE. mined_dish is derived from the
#    corpus's titles, and these recipes are Andy's own. The bridge is that both sides run the same
#    reducer, so `Banana Bread` and a corpus `Banana Bread!!` land on the same dish_id.
#
#    ⚠️ MEASURED, AND THE NUMBER IS THE POINT: 106 of 298 resolve, 36%. Of those, 80 reach a
#    specific dish and 26 reach a one-word generic. The 192 that miss are mostly real dishes the
#    corpus never names ten times, `agedashi tofu`, `acqua pazza`, `arabic flatbread`, `za'atar`.
#    That is this collection leaning toward the cuisines an English web corpus under-represents,
#    which is the same limit docs/what-the-library-is-for.md already records. The page says so
#    rather than showing a blank.
#
#    ⚠️ THE IMPORT IS GUARDED. dish_facets reads its vocabularies from previews/, which is
#    gitignored, so on a clone without them the import fails. The viewer must still run.
_DISHMAP = {"key": None, "val": None}


def recipe_dishes(c):
    """recipe_id -> (dish_id, dish, n). Empty when the dish tables or the vocabularies are absent."""
    st = os.stat(DB)
    key = (st.st_size, st.st_mtime_ns)
    if _DISHMAP["key"] == key:
        return _DISHMAP["val"]
    out = {}
    if has_dishes(c):
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import dish_facets as _F, brand_guard as _BG
            chk, brands = _BG.catalog_name_check(c), _BG.load_brands()
            known = {r["dish_id"]: (r["dish"], r["n"]) for r in
                     c.execute("SELECT dish_id, dish, n FROM mined_dish")}
            for r in c.execute("SELECT id, name FROM recipes"):
                d = _F.specific_dish(r["name"], brands, chk)
                did = _F.dish_id(d) if d else None
                if did in known:
                    out[r["id"]] = (did,) + known[did]
        except Exception:
            out = {}                      # no vocabularies here, which is a clone, not a fault
    _DISHMAP["key"], _DISHMAP["val"] = key, out
    return out


def dish_facet_bits(c, did, n_dish=None):
    """The vocabulary facets of one dish as tag markup, EACH CARRYING ITS SHARE.

    ⚠️ THE SHARE IS NOT DECORATION. Without it `bread` and `vegan` render identically on banana
    bread, and they are 99.1% and 1.0% of it. A bare tag reads as a property of the dish when it
    is a property of some recipes for the dish. The number is what makes the tag true.
    """
    if n_dish is None:
        r = c.execute("SELECT n FROM mined_dish WHERE dish_id=?", (did,)).fetchone()
        n_dish = r[0] if r else 0
    bits = []
    for label, tbl, col in DISH_FACETS:
        vals = list(c.execute(
            f"SELECT {col} v, n FROM {tbl} WHERE dish_id=? ORDER BY n DESC LIMIT 3", (did,)))
        bits += [tag(f'{x["v"]} {x["n"]/n_dish*100:.0f}%' if n_dish else x["v"], "teal")
                 for x in vals]
    base = [ilink(x["library_id"], x["canonical"]) for x in c.execute(
        "SELECT b.library_id, l.canonical FROM mined_dish_base b "
        "JOIN library_names l ON l.library_id=b.library_id WHERE b.dish_id=? ORDER BY b.n DESC",
        (did,))]
    return bits, base


@app.route("/dishes")
def dishes():
    c = db()
    if not has_dishes(c):
        c.close()
        return dish_missing()
    q = (request.args.get("q") or "").strip()
    form = request.args.get("form") or ""
    show = request.args.get("show") or ""
    sort = request.args.get("sort") or "n"
    sdir = "ASC" if (request.args.get("dir") or "desc") == "asc" else "DESC"
    where, args = [], []
    if q:
        where.append("d.dish LIKE ?"); args.append(f"%{q}%")
    if form:
        where.append("EXISTS (SELECT 1 FROM mined_dish_form f WHERE f.dish_id=d.dish_id "
                     "AND f.dish_type=?)"); args.append(form)
    if show == "noprofile":
        where.append("NOT EXISTS (SELECT 1 FROM mined_dish_ingredient i WHERE i.dish_id=d.dish_id)")
    elif show == "nobase":
        where.append("NOT EXISTS (SELECT 1 FROM mined_dish_base b WHERE b.dish_id=d.dish_id)")
    elif show == "profiled":
        where.append("EXISTS (SELECT 1 FROM mined_dish_ingredient i WHERE i.dish_id=d.dish_id)")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM mined_dish d {w}", args).fetchone()[0]
    n_all = c.execute("SELECT COUNT(*) FROM mined_dish").fetchone()[0]
    page_no = max(1, int(request.args.get("page") or 1))
    order = {"dish": "d.dish", "n": "d.n", "cells": "cells"}.get(sort, "d.n")
    rows = list(c.execute(
        f"""SELECT d.dish_id, d.dish, d.n,
                   (SELECT COUNT(*) FROM mined_dish_ingredient i WHERE i.dish_id=d.dish_id) cells
            FROM mined_dish d {w} ORDER BY {order} {sdir}, d.dish
            LIMIT ? OFFSET ?""", args + [PER, (page_no - 1) * PER]))
    ids = [r["dish_id"] for r in rows]
    qmark = ",".join("?" * len(ids)) or "''"
    forms, bases = {}, {}
    if ids:
        for r in c.execute(f"SELECT dish_id, dish_type FROM mined_dish_form "
                           f"WHERE dish_id IN ({qmark}) ORDER BY n DESC", ids):
            forms.setdefault(r["dish_id"], []).append(r["dish_type"])
        for r in c.execute(f"SELECT b.dish_id, b.library_id, l.canonical FROM mined_dish_base b "
                           f"JOIN library_names l ON l.library_id=b.library_id "
                           f"WHERE b.dish_id IN ({qmark}) ORDER BY b.n DESC", ids):
            bases.setdefault(r["dish_id"], []).append(ilink(r["library_id"], r["canonical"]))
    body_rows = [(f'<span class=nm>{dlink(r["dish_id"], r["dish"])}</span>',
                  fmt(r["n"]),
                  " ".join(taglink(x, f'/dishes?form={uq(x)}') for x in forms.get(r["dish_id"], [])),
                  ", ".join(bases.get(r["dish_id"], [])) or '<span class=dimc>none</span>',
                  cnt(r["cells"], f'/dish/{uq(r["dish_id"])}')) for r in rows]
    bits = []
    if q: bits.append(f'matching <b>{escape(q)}</b>')
    if form: bits.append(f'form <b>{escape(form)}</b>')
    if show: bits.append(f'<b>{escape(show)}</b>')
    top_forms = [x[0] for x in c.execute(
        "SELECT dish_type, COUNT(*) k FROM mined_dish_form GROUP BY 1 ORDER BY k DESC LIMIT 14")]
    about = ("Every dish the corpus names at least 10 times, reduced to a normalized form. The "
             "specific dish is the one place a mined table holds the corpus's own words, and it "
             "is cleaned of brands and personal names before it is stored. Everything beside it "
             "is a vocabulary word or a catalog id.")
    body = f"""<section>
{phead("Dishes", total, "dishes" if not bits else "dishes shown", "mined_dish", about,
       of=None if not bits else n_all)}
<div class=filters>{searchbox("filter by dish", keep=("form", "show"))}</div>
<div class=filters>{filters("/dishes", "show", [("", "all"), ("profiled", "has a profile"),
  ("noprofile", "no profile"), ("nobase", "no base")], show, "show")}</div>
<div class=filters>{filters("/dishes", "form", [("", "any form")] + [(f, f) for f in top_forms],
  form, "form")}</div>
{ctx(bits, "/dishes" if bits else None)}
{table([("dish", "the normalized specific dish", "mined_dish.dish", "dish"),
        ("recipes", "how many recipes in the corpus resolved to it", "mined_dish.n", "n"),
        ("form", "the functional category", "mined_dish_form.dish_type"),
        ("base", "what it is made of, as catalog rows", "base.library_id"),
        ("profile", "how many ingredients are stored for it", "ingredient cells", "cells")],
       body_rows, ["nm", "num", "", "", "num"], "No dish matches.")}
{pager(page_no, total, "/dishes")}</section>"""
    c.close()
    return page("Dishes", body, "/dishes", [("Condition", "/"), ("Dishes", None)])


@app.route("/dish/<path:did>")
def dish(did):
    c = db()
    if not has_dishes(c):
        c.close()
        return dish_missing()
    row = c.execute("SELECT * FROM mined_dish WHERE dish_id=?", (did,)).fetchone()
    if not row:
        c.close()
        return page("Not found", f'<section><h1>No dish</h1><p class=sub>'
                    f'<code>{escape(did)}</code> is not in mined_dish.</p></section>',
                    "/dishes", [("Condition", "/"), ("Dishes", "/dishes")]), 404
    nd = row["n"]
    vocab = {}
    for label, tbl, col in DISH_FACETS:
        vocab[label] = list(c.execute(
            f"SELECT {col} v, n FROM {tbl} WHERE dish_id=? ORDER BY n DESC", (did,)))
    base = list(c.execute(
        "SELECT b.library_id, b.n, l.canonical FROM mined_dish_base b "
        "JOIN library_names l ON l.library_id=b.library_id WHERE b.dish_id=? ORDER BY b.n DESC",
        (did,)))
    acc = list(c.execute(
        "SELECT a.library_id, a.n, l.canonical FROM mined_dish_accompaniment a "
        "JOIN library_names l ON l.library_id=a.library_id WHERE a.dish_id=? ORDER BY a.n DESC",
        (did,)))
    prof = list(c.execute(
        "SELECT i.library_id, i.n, i.n_dish, l.canonical FROM mined_dish_ingredient i "
        "JOIN library_names l ON l.library_id=i.library_id WHERE i.dish_id=? ORDER BY i.n DESC",
        (did,)))

    def vrow(label):
        """⚠️ EVERY FACET CARRIES ITS SHARE, for the reason in dish_facet_bits. `vegan` on banana
        bread is 31 of 3,245 recipes, and a bare tag beside `bread` at 99% claims they are the
        same kind of true."""
        v = vocab[label]
        if not v:
            return '<span class=dimc>not recorded</span>'
        return " ".join(tag(f'{x["v"]} {x["n"]/nd*100:.0f}%' if nd else x["v"], "teal") for x in v)

    # ⚠️ A BAR PER ROW, NOT A gauge(). gauge() refuses to draw parts that do not partition a
    #    total, and these do not: a recipe carries many ingredients, so the shares sum well past
    #    100%. Drawing them as one segmented bar would be a false claim about the data, which is
    #    exactly what that helper exists to prevent.
    def bar(n):
        pc = n / nd * 100 if nd else 0
        return (f'<span class=minibar aria-hidden="true">'
                f'<span style="width:{min(pc,100):.1f}%"></span></span>')

    prof_rows = [(f'<span class=nm>{ilink(r["library_id"], r["canonical"])}</span>',
                  f'{fmt(r["n"])} <span class=dimc>of {fmt(nd)}</span>',
                  f'{r["n"]/nd*100:.0f}%', bar(r["n"])) for r in prof]
    acc_rows = [(f'<span class=nm>{ilink(r["library_id"], r["canonical"])}</span>',
                 fmt(r["n"])) for r in acc]
    base_html = ", ".join(ilink(r["library_id"], r["canonical"]) for r in base) or \
        '<span class=dimc>not recorded</span>'

    body = f"""<section><h1>{escape(row["dish"])}</h1>
<p class=sub><span class=mono>{escape(did)}</span> ·
 <b>{fmt(nd)}</b> recipes in the corpus resolved to this dish</p>
<p class=ident>read from <span class=mono>mined_dish</span>, with its facets from
 <span class=mono>mined_dish_*</span> and its profile from
 <span class=mono>mined_dish_ingredient</span></p>
<div class=two><dl class=kv>
  <dt>base</dt><dd>{base_html}</dd>
  <dt>form</dt><dd>{vrow("form")}</dd>
  <dt>method</dt><dd>{vrow("method")}</dd></dl>
<dl class=kv>
  <dt>diet</dt><dd>{vrow("diet")}</dd>
  <dt>structural</dt><dd>{vrow("structural")}</dd>
  <dt>appliance</dt><dd>{vrow("appliance")}</dd></dl></div>
<p class=note>base is a catalog row and links to it. The other five are words from a vocabulary
 this repository authored, so they name a quality rather than a thing and have no row to open.</p>
</section>
<section><h2>Ingredient profile <span class=dimc>{fmt(len(prof))}</span></h2>
<p class=cap>What this dish is made of, counted across all {fmt(nd)} recipes. An ingredient is
 stored when it appears in at least 3 of them, or in at least 2 and at least a tenth of them.
 The share arm is what keeps a dish the corpus rarely sees from storing nothing at all.</p>
{table([("ingredient", "the catalog row the line resolved to", "ingredient.library_id"),
        ("in", "recipes of this dish carrying it", "n of n_dish"),
        ("share", "that count as a share of the dish", "n / n_dish"),
        ("", "", " ")],
       prof_rows, ["nm", "num", "num", "bar"], "No ingredient clears the floor for this dish.")}
</section>
<section><h2>Served with <span class=dimc>{fmt(len(acc))}</span></h2>
<p class=cap>Read from the phrase after `with` or `over` in the title, resolved to catalog rows.
 Most dishes carry none, which is the ordinary answer rather than a failure.</p>
{table([("accompaniment", "what the title said it is served with", "mined_dish_accompaniment"),
        ("recipes", "how many said so", "n")],
       acc_rows, ["nm", "num"], "Nothing recorded.")}</section>"""
    c.close()
    return page(row["dish"], body, "/dishes",
                [("Condition", "/"), ("Dishes", "/dishes"), (row["dish"], None)])


@app.route("/substitutions/decide", methods=["POST"])
def decide():
    f = request.form
    err = append_decision(f.get("from", "").strip(), f.get("to", "").strip(),
                          f.get("decision", ""), f.get("ratio", ""), f.get("note", ""),
                          f.get("n", ""))
    back = f.get("back") or "/substitutions"
    # a return path from a form is still a path. Anything that could leave this host is refused.
    if not back.startswith("/") or back.startswith("//"):
        back = "/substitutions"
    sep = "&" if "?" in back else "?"
    return redirect(f"{back}{sep}err={uq(err)}" if err else back, code=303)


@app.route("/substitutions")
def substitutions():
    c = db()
    state = request.args.get("state") or ""
    shape = request.args.get("shape") or ""
    floor = request.args.get("floor") or ""
    qy = (request.args.get("q") or "").strip()
    sort = request.args.get("sort") or "n"
    sdir = request.args.get("dir") or "desc"
    p = max(1, int(request.args.get("page") or 1))
    n_all = c.execute("SELECT COUNT(*) FROM mined_substitution_candidates").fetchone()[0]

    where, args = [], []
    if shape == "gap":
        where.append("s.one_to_many=1")
    elif shape == "pair":
        where.append("s.one_to_many=0")
    if floor:
        where.append("s.n>=?"); args.append(int(floor))
    if qy:
        where.append("(f.canonical LIKE ? COLLATE NOCASE OR t.canonical LIKE ? COLLATE NOCASE)")
        args += [f"%{qy}%", f"%{qy}%"]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    e = SUB_SORT.get(sort, "s.n")
    d = "DESC" if sdir == "desc" else "ASC"
    # ⚠️ EVERY SORT ENDS WITH THE SAME TIEBREAK, the rule the catalog page already runs on. 3,299
    #    of the 4,600 rows sit at n=1, so a sort on n alone reorders them on every page load and
    #    a row can be read twice while another is never seen at all.
    order = f"{e} {d}, f.canonical COLLATE NOCASE, t.canonical COLLATE NOCASE"
    rows_sql = c.execute(
        f"SELECT s.from_id, s.to_id, s.n, s.n_reverse, s.one_to_many, s.pattern, "
        f"       f.canonical fn, t.canonical tn "
        f"FROM mined_substitution_candidates s "
        f"JOIN library_names f ON f.library_id=s.from_id "
        f"LEFT JOIN library_names t ON t.library_id=s.to_id {w} ORDER BY {order}", args).fetchall()

    # ⚠️ STATE IS NOT IN THE DATABASE, so it cannot be a WHERE clause. A decision lives in
    #    hand_substitutions.csv, and library_substitutions holds only the confirmed half of it
    #    with no trace of a rejection at all. SQL does what SQL can see, and the state filter runs
    #    here over at most 4,600 rows already in memory.
    decided = hand_state()

    def st(r):
        got = decided.get((r["from_id"], r["to_id"]))
        return got["decision"] if got else "pending"

    tally = {"pending": 0, "confirmed": 0, "rejected": 0, "authored": 0}
    for r in rows_sql:
        tally[st(r)] += 1
    rows_f = [r for r in rows_sql if not state or st(r) == state]
    total = len(rows_f)
    page_rows = rows_f[(p - 1) * PER: p * PER]

    back = "/substitutions" + qs()
    out = []
    for r in page_rows:
        s_now = st(r)
        if r["one_to_many"]:
            # ⚠️ NO CONTROLS ON A GAP, because there is nothing to confirm. The row is here so the
            #    shape this schema cannot hold stays visible instead of being quietly dropped.
            to_cell = '<span class=dimc>two ingredients, which this table cannot hold</span>'
            act = '<span class=held>flagged</span>'
        else:
            to_cell = f'<span class=nm>{ilink(r["to_id"], r["tn"] or r["to_id"])}</span>'

            def btn(dec, label, cls="", _r=r):
                return (f'<form method=post action="/substitutions/decide">'
                        f'<input type=hidden name=from value="{escape(_r["from_id"])}">'
                        f'<input type=hidden name=to value="{escape(_r["to_id"])}">'
                        f'<input type=hidden name=n value="{_r["n"]}">'
                        f'<input type=hidden name=decision value="{dec}">'
                        f'<input type=hidden name=back value="{escape(back)}">'
                        f'<button class="{cls}" type=submit>{label}</button></form>')

            act = ('<div class=act>'
                   + (btn("confirmed", "confirm") if s_now != "confirmed" else "")
                   + (btn("rejected", "reject", "no") if s_now != "rejected" else "")
                   + '</div>')
        out.append((
            f'<span class=nm>{ilink(r["from_id"], r["fn"] or r["from_id"])}</span>',
            to_cell,
            f'<span class=mono>{fmt(r["n"])}</span>',
            f'<span class=mono>{fmt(r["n_reverse"])}</span>' if r["n_reverse"]
            else '<span class=zero>0</span>',
            f'<span class="dimc wrap">{escape(r["pattern"])}</span>',
            tag(s_now, STATE_TAG.get(s_now, "")) if s_now != "pending"
            else '<span class=dimc>pending</span>',
            act))

    # ⚠️ THE GAUGE IS SCOPED TO THE FILTERS BUT NOT TO THE STATE, and each segment is the door to
    #    that state. Scoping it to the state as well would draw one full bar every time, which is
    #    a picture of the filter rather than of the data. Same split the catalog chart runs on.
    parts = [(k, tally[k], f"/substitutions{qs(state=k, page=None)}")
             for k in ("pending", "confirmed", "rejected") if tally[k] or k == "pending"]
    chart = gauge(parts, sum(tally[k] for k in ("pending", "confirmed", "rejected")),
                  "the queue, by what has been decided") if rows_sql else ""

    n_conf = c.execute("SELECT COUNT(*) FROM library_substitutions").fetchone()[0]
    said_yes = sum(1 for r in decided.values() if r["decision"] in ("confirmed", "authored"))
    # ⚠️ THE STORED TABLE IS NEVER PRINTED AS FACT, the same rule GOTCHA 3 states for link_state.
    #    A confirm appends to the file and nothing else. library_substitutions catches up when
    #    load_substitutions.py runs, and until it does the two disagree. Saying so is the job.
    drift = ""
    if said_yes != n_conf:
        drift = (f'<div class=banner><b>{fmt(said_yes)}</b> confirmed in the hand file, '
                 f'<b>{fmt(n_conf)}</b> in <span class=mono>library_substitutions</span>. '
                 f'A decision is written to the file, and the table catches up when '
                 f'<span class=mono>python3.13 load_substitutions.py</span> replays it.</div>')
    err = request.args.get("err")
    if err:
        drift = f'<div class=banner>{escape(err)}</div>' + drift

    n_gap = c.execute("SELECT COUNT(*) FROM mined_substitution_candidates "
                      "WHERE one_to_many=1").fetchone()[0]
    # ⚠️ THESE COUNT PAIRS, WHICH IS NOT THE SAME AS COUNTING ROWS, and the first draft of this
    #    page got both wrong in the same direction. A one-to-many gap is a row and not a pair, so
    #    n>=3 over the whole table reads 608 against the 593 pairs that can actually be confirmed.
    #    A pair seen both ways is stored as two rows, so n_reverse>0 reads 1,262 for 631 pairs.
    n_both = c.execute("SELECT COUNT(*) FROM mined_substitution_candidates "
                       "WHERE n_reverse>0").fetchone()[0] // 2
    n3 = c.execute("SELECT COUNT(*) FROM mined_substitution_candidates "
                   "WHERE n>=3 AND one_to_many=0").fetchone()[0]
    about = (
      "<p class=about>A substitution here is a proposal, not a fact. RecipeNLG's directions text "
      'says things like <span class=ex>use margarine instead of butter</span>, and an extractor '
      f'pulled <b>{fmt(n_all - n_gap)}</b> ordered pairs out of 2,231,142 recipes. Slightly over '
      'half of what it matched survived cleaning, so the rest of the work is reading.</p>'
      '<p class=about>Direction is the fact, so the pair is ordered and the reverse count sits '
      f'beside it. <b>{fmt(n_both)}</b> pairs were seen both ways round. Water to chicken broth '
      'was seen 137 times and 5 times the other way, and that asymmetry is what says the rule '
      'read the preposition rather than the verb.</p>'
      f'<p class=about><b>{fmt(n3)}</b> pairs were seen three times or more. <b>{fmt(n_gap)}</b> '
      'more read as one ingredient replaced by two, which a from-and-to row cannot say, so they '
      'are held here flagged rather than dropped. Confirming or rejecting writes a line to '
      f'<span class=mono>{escape(HAND)}</span>. Nothing on this page writes the database.</p>')

    HEADS = [
      ("from", "the ingredient being replaced", "from_id", "from"),
      ("to", "what stands in for it", "to_id", "to"),
      ("n", "times the corpus said so", "n", "n"),
      ("reverse", "times it said the opposite", "n_reverse", "reverse"),
      ("pattern", "which rule fired. provenance, never the sentence it read", "pattern"),
      # ⚠️ THE COLUMN LABEL NAMES A FILE, NOT A COLUMN, and that is the honest label. Every other
      #    header here says which stored field it shows. This one is not stored in the database at
      #    all, and writing a column name under it would be the one place this page lied.
      ("state", "what you decided. not a database column", HAND),
      ("", "", ""),
    ]
    # ⚠️ AN AUTHORED ROW IS NOT IN THE QUEUE, so it would otherwise be written and never seen
    #    again. Nothing proposed it, so no candidate row carries it and every count on this page
    #    is blind to it. They are read back out of the hand file and shown under the form that
    #    writes them. A write surface where the write disappears is worse than no write surface.
    in_queue = {(r["from_id"], r["to_id"]) for r in rows_sql}
    own = [r for k, r in decided.items() if r["decision"] == "authored" and k not in in_queue]
    own_rows = [(f'<span class=nm>{ilink(r["from"], r["from_name"] or r["from"])}</span>',
                 f'<span class=nm>{ilink(r["to"], r["to_name"] or r["to"])}</span>',
                 f'<span class=mono>{escape(r["ratio"])}</span>' if r["ratio"]
                 else '<span class=dimc>not fixed</span>',
                 f'<span class="dimc wrap">{escape(r["note"])}</span>',
                 f'<span class=dimc>{escape(r["decided"])}</span>') for r in own]
    own_block = ""
    if own_rows:
        own_block = ('<h3 style="margin:22px 0 6px">Written in by hand '
                     f'<span class=dimc>{len(own_rows)}</span></h3>'
                     + table([("from", "the ingredient being replaced"),
                              ("to", "what stands in for it"),
                              ("ratio", "how much of it stands in for one of the other"),
                              ("why", "your words. they stay in the file and never reach a table"),
                              ("decided", "the day you wrote it")],
                             own_rows, ["nm", "nm", "num", "", ""]))
    bits = []
    if state:
        bits.append(f"Showing the <b>{escape(state)}</b> rows only.")
    if shape == "gap":
        bits.append("One ingredient replaced by two, which this table cannot store.")
    if shape == "pair":
        bits.append("Ordered pairs only, so the rows that can be confirmed.")
    if floor:
        # ⚠️ THE HEADER COUNTS ROWS AND THE PARAGRAPH ABOVE COUNTS PAIRS, so at a floor of 3 one
        #    says 608 and the other says 593 within three inches of each other. Both are true and
        #    together they read as a contradiction. The 15 between them are one-to-many gaps,
        #    which are rows and are not pairs, and naming them here is cheaper than making either
        #    number wrong.
        n_gap_here = sum(1 for r in rows_f if r["one_to_many"])
        bits.append(f"Seen <b>{escape(floor)}</b> times or more."
                    + (f" <b>{fmt(total - n_gap_here)}</b> of them are pairs and "
                       f"<b>{fmt(n_gap_here)}</b> are one-to-many gaps." if n_gap_here else ""))
    strip = ctx(bits, "/substitutions") if bits else ""
    authored = (
      '<div class=authored><h3>Write one in by hand</h3>'
      '<p>For a substitution you know and the corpus never proposed. It goes into the same file '
      'marked authored, and it has to carry a note, since nothing but you stands behind it.</p>'
      '<form method=post action="/substitutions/decide">'
      '<input type=hidden name=decision value="authored">'
      f'<input type=hidden name=back value="{escape(back)}">'
      '<div class=rf>'
      '<label><span>replace this</span><input name=from placeholder="library_id or the exact name" required></label>'
      '<label><span>with this</span><input name=to placeholder="library_id or the exact name" required></label>'
      '<label><span>ratio</span><input name=ratio placeholder="1" style="width:70px"></label>'
      '</div><div class=rf>'
      '<label><span>why</span><input name=note style="width:420px" required></label>'
      '<button type=submit>add</button></div></form>' + own_block + '</div>')
    body = f"""<section>
{phead("Substitutions", total, "candidates", "mined_substitution_candidates", "", said=about,
       of=n_all if (state or shape or floor or qy) else None)}
{drift}
{chart}
<div class=filters>{filters("/substitutions","state",[("","all"),("pending",f"pending {fmt(tally['pending'])}"),("confirmed",f"confirmed {fmt(tally['confirmed'])}"),("rejected",f"rejected {fmt(tally['rejected'])}")],state,"state")}</div>
<div class=filters>{filters("/substitutions","shape",[("","all"),("pair",f"ordered pairs {fmt(n_all-n_gap)}"),("gap",f"one-to-many {fmt(n_gap)}")],shape,"shape")}</div>
<div class=filters>{filters("/substitutions","floor",[("","any"),("2","seen 2+"),("3","seen 3+"),("5","seen 5+"),("10","seen 10+")],floor,"support")}{searchbox("filter by ingredient",("state","shape","floor","sort","dir"))}</div>
{strip}
{authored}
{table(HEADS, out, ["nm","nm","num","num","","","act"], "No candidate matches those filters.")}
{pager(p,total,"/substitutions")}</section>"""
    c.close()
    return page("Substitutions", body, "/substitutions",
                [("Condition", "/"), ("Substitutions", None)])


@app.route("/g/<path:lid>")
def graph(lid):
    c = db()
    row = c.execute("SELECT canonical FROM library_names WHERE library_id=?", (lid,)).fetchone()
    if not row:
        c.close()
        return page("Not found", f"<section><h1>No catalog row</h1><p class=sub>"
                    f"<code>{escape(lid)}</code></p></section>", "/catalog",
                    [("Condition", "/"), ("Catalog", "/catalog")]), 404
    nb = neighbourhood(c, lid)
    c.close()
    head = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/'
            'vis-network.min.js"></script>')
    body = f"""<section><h1>{escape(row["canonical"])}</h1>
<p class=sub><span class=mono>{escape(lid)}</span> · {len(nb["category"])} category,
 {len(nb["parent"])} parent, {fmt(len(nb["child"]))} children, {fmt(len(nb["sibling"]))} siblings ·
 <a href="/i/{uq(lid)}">full detail</a></p>
<p class=hint>Single-click a node to re-centre on it, double-click to open its page. Parents are
 deduped by row: a child can carry both a kind-of and a made-from edge to the same parent, which
 would otherwise draw two lines between one pair. Children are capped at 40 and siblings at 20.</p>
<div id=net></div></section>
<script>
let net, nodes;
async function load(id){{
  const d = await (await fetch('/api/n/' + encodeURIComponent(id))).json();
  nodes = new vis.DataSet(d.nodes);
  if(net) net.destroy();
  net = new vis.Network(document.getElementById('net'),
    {{nodes, edges:new vis.DataSet(d.edges)}}, {{
    physics:{{stabilization:true, barnesHut:{{springLength:160, gravitationalConstant:-4200}}}},
    nodes:{{shape:'box', font:{{size:13, face:'IBM Plex Sans,sans-serif'}}, margin:8,
            borderWidth:1, shapeProperties:{{borderRadius:2}}}},
    edges:{{arrows:'to', font:{{size:10, align:'middle', color:'#526B7A',
            strokeWidth:3, strokeColor:'#fff'}}, smooth:{{type:'dynamic'}}, width:1.2}}
  }});
  net.on('click', p => {{ if(p.nodes.length){{ const x=nodes.get(p.nodes[0]);
     if(x && x.lid){{ load(x.lid); history.replaceState(null,'','/g/'+encodeURIComponent(x.lid)); }} }} }});
  net.on('doubleClick', p => {{ if(p.nodes.length){{ const x=nodes.get(p.nodes[0]);
     if(x && x.lid) location='/i/'+encodeURIComponent(x.lid);
     else if(x && x.cid) location='/c/'+encodeURIComponent(x.cid); }} }});
}}
load({lid!r});
</script>"""
    return page("graph " + row["canonical"], body, "/catalog",
                [("Condition", "/"), ("Catalog", "/catalog"),
                 (row["canonical"], f"/i/{lid}"), ("graph", None)], head)


@app.route("/api/n/<path:lid>")
def api_n(lid):
    """⚠️ GOTCHA 1 and 6. kind constrained on every branch, parents deduped by row."""
    c = db()
    row = c.execute("SELECT canonical FROM library_names WHERE library_id=?", (lid,)).fetchone()
    if not row:
        c.close()
        return jsonify({"nodes": [], "edges": []})
    nb = neighbourhood(c, lid)
    c.close()
    nodes = [{"id": lid, "lid": lid, "label": row["canonical"],
              "color": {"background": "#1B2A33", "border": "#1B2A33"},
              "font": {"color": "#fff", "size": 15}}]
    edges, seen = [], {lid}

    def add(nid, label, bg, border, **kw):
        if nid in seen:
            return False
        seen.add(nid)
        nodes.append(dict(id=nid, label=label, color={"background": bg, "border": border}, **kw))
        return True

    for x in nb["category"]:
        add("cat:" + x["id"], x["label"], "#F0F6F6", "#0E6E6E", cid=x["id"], shape="ellipse")
        edges.append({"from": lid, "to": "cat:" + x["id"], "label": "in-category", "color": "#0E6E6E"})
    for x in nb["parent"]:
        add(x["id"], x["label"], "#E6EEF7", "#1a5490", lid=x["id"])
        edges.append({"from": lid, "to": x["id"],
                      "label": " + ".join(k.replace("_", "-") for k in x["kinds"]), "color": "#1a5490"})
    for x in nb["child"][:40]:
        add(x["id"], x["label"], "#F6F9F9", "#C3D0D5", lid=x["id"])
        edges.append({"from": x["id"], "to": lid,
                      "label": " + ".join(k.replace("_", "-") for k in x["kinds"]), "color": "#B3BFC4"})
    for x in nb["sibling"][:20]:
        if add(x["id"], x["label"], "#FBF4EC", "#E7CFAE", lid=x["id"]):
            edges.append({"from": lid, "to": x["id"], "label": "sibling", "dashes": True,
                          "color": "#E7CFAE", "arrows": ""})
    return jsonify({"nodes": nodes, "edges": edges,
                    "truncated": {"children": max(0, len(nb["child"]) - 40),
                                  "siblings": max(0, len(nb["sibling"]) - 20)}})


if __name__ == "__main__":
    print(f"library bench  http://localhost:{PORT}   reading {DB} read-only")
    app.run(port=PORT, debug=False)
