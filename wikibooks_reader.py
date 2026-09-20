#!/usr/bin/env python3
"""wikibooks_reader.py - read en.wikibooks Cookbook recipe pages into structured records.

⚠️ A READER, NOT A MINER. Same three-stage discipline as the Paprika path: this file turns
wikitext into tuples and knows nothing about the catalog, the matcher or any database. What the
tuples then MEAN is decided downstream, so adding a source never touches core logic. It writes
nothing.

⚠️ INGREDIENTS ARE READ FROM THE LINE TEXT, NOT FROM THE WIKILINKS, AND THAT WAS MEASURED RATHER
   THAN ASSUMED. Every ingredient line carries [[Cookbook:...]] links and following them is the
   obvious move. Counted across all 3,792 pages, the commonest link targets are:

       Cup 2,408 · Tablespoon 1,940 · Salt 1,894 · Teaspoon 1,863 · Gram 1,080 ·
       Chopping 953 · Onion 908 · Pepper 829 · Ounce 791 · Butter 771

   Six of the top ten are units or knife techniques. Wikibooks links its units and its verbs the
   same way it links its foods, so a link-following reader mines `cup` as the second commonest
   ingredient in the corpus and `chopping` ahead of onion. The links are stripped to their display
   text and the resulting plain line goes through recipe_line_parser.parse, which is the same
   pipeline RecipeNLG's names went through. Using a different one would make the two sources
   incomparable, which would defeat the point of adding this one.

⚠️ THE INGREDIENTS SECTION RUNS TO THE NEXT HEADING AT ITS OWN LEVEL OR SHALLOWER, not to the next
   heading. 428 pages put their sub-lists inside it as level-3 headings, `Filling`, `Dough`,
   `Marinade`, `Garnish`. Stopping at the first sub-heading drops all of them: `marinade` is
   nested 16 times out of 16, `garnish` 19 out of 21. `Equipment` is never nested, 0 times out of
   469, so the same rule that keeps the sub-lists also keeps 2,111 equipment bullets out.

⚠️ 89 PAGES KEEP THEIR INGREDIENTS IN A TABLE AND NOT IN A LIST, so both are read. See
   _table_rows for why skipping them would have cut the bread recipes specifically.

⚠️ NO RECIPE TEXT LEAVES THIS MODULE FOR A DATABASE. It returns the procedure step count and not
   the steps, because a count is a fact and a step is expression. docs/mining-decision.md
   boundary (d). The caller gets ingredient line text so the matcher can read it, exactly as
   pairing_run.py gets RecipeNLG's NER names, and neither is stored.
"""
import json
import re

__all__ = ["Recipe", "read", "parse_page", "strip_markup", "CATEGORY_KINDS"]

HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)
LINK = re.compile(r"\[\[(?:[^\]|#]*?:)?([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
CATEGORY = re.compile(r"\[\[Category:\s*([^\]|]+?)\s*(?:\|[^\]]*)?\]\]", re.I)
REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.S | re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
HTML = re.compile(r"<[^>]+>")
REDIRECT = re.compile(r"^\s*#\s*REDIRECT", re.I)
BULLET = re.compile(r"^[*:]+\s*")
NUMBERED = re.compile(r"^#+\s*")

# The five shapes a Wikibooks category comes in. The prefix is the source's own wording and is
# what makes the routing decidable without a hand list per value.
CATEGORY_KINDS = [
    ("ingredient", re.compile(r"^recipes?\s+using\s+(.+)$", re.I)),
    ("form",       re.compile(r"^recipes?\s+for\s+(.+)$", re.I)),
    ("method",     re.compile(r"^(.+?)\s+recipes$", re.I)),      # `Steamed recipes`, and much else
]


def strip_markup(s):
    """Wikitext to the plain sentence a human reads. Links become their display text."""
    s = COMMENT.sub(" ", s)
    s = REF.sub(" ", s)
    s = LINK.sub(lambda m: (m.group(2) or m.group(1)), s)
    for _ in range(3):                       # nested templates, innermost first
        s2 = TEMPLATE.sub(" ", s)
        if s2 == s:
            break
        s = s2
    s = HTML.sub(" ", s)
    s = re.sub(r"'{2,}", "", s)              # bold and italic
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def _heading_text(raw):
    t = strip_markup(raw)
    return t.strip().lower().rstrip(":").strip()


def sections(txt):
    """[(level, heading, body)] in document order, plus the lead as (0, '', body)."""
    ms = list(HEADING.finditer(txt))
    out = [(0, "", txt[:ms[0].start()] if ms else txt)]
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        out.append((len(m.group(1)), _heading_text(m.group(2)), txt[m.end():end]))
    return out


def _span(txt, match):
    """Body of the first section whose heading matches, running to the next heading at its own
    level or shallower, so nested sub-lists are included and siblings are not."""
    ms = list(HEADING.finditer(txt))
    for i, m in enumerate(ms):
        level, head = len(m.group(1)), _heading_text(m.group(2))
        if not match(head):
            continue
        end = len(txt)
        for j in range(i + 1, len(ms)):
            if len(ms[j].group(1)) <= level:
                end = ms[j].start()
                break
        return txt[m.end():end]
    return ""


def _bullets(body):
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("*"):
            continue
        s = strip_markup(BULLET.sub("", s))
        if s and not s.startswith("="):
            out.append(s)
    return out


# ⚠️ 89 REAL RECIPES HAVE NO BULLET LIST AT ALL, and a bullet-only reader returned them as pages
#    with zero ingredients. They are not junk and they are not evenly spread: Baguette at 29
#    steps, Challah at 16, Schwarzwalder Kirschtorte at 30, White Bread, Focaccia, Bagels,
#    English Muffins. Breads and baked goods, because those are the recipes where a baker's
#    percentage column makes a table the natural layout. Dropping them would have cut the bread
#    category specifically while reporting a clean-looking total.
#
#    ⚠️ THE INGREDIENT IS ALWAYS THE FIRST COLUMN, checked rather than assumed. Every header
#    signature across the 89 starts with `Ingredient` or `Name`, the commonest being
#    (ingredient, count, volume, weight, baker's %) at 39 pages. No table puts the amount first.
TOTAL_ROW = re.compile(r"^(total|sum)\b", re.I)


def _table_rows(body):
    """First cell of every data row of every wikitable in the body."""
    out = []
    for table in re.findall(r"\{\|.*?\|\}", body, re.S):
        cells, row_open = [], False
        for line in table.splitlines()[1:]:
            s = line.strip()
            if s.startswith("|-"):
                row_open = True
                cells.append([])
                continue
            if s.startswith("!") or s.startswith("|}") or s.startswith("{|"):
                continue
            if s.startswith("|") and row_open:
                # `| a || b` puts several cells on one line. Only the first is wanted.
                first = s[1:].split("||")[0]
                cells[-1].append(first)
        for row in cells:
            if not row:
                continue
            v = strip_markup(row[0]).strip(" |")
            if v and not TOTAL_ROW.match(v) and not v.startswith("="):
                out.append(v)
    return out


class Recipe:
    """One page, read. Nothing here is a judgement about food."""

    __slots__ = ("title", "name", "ingredients", "equipment", "steps", "categories",
                 "summary_category", "is_redirect")

    def __init__(self, title, name, ingredients, equipment, steps, categories,
                 summary_category, is_redirect):
        self.title = title
        self.name = name
        self.ingredients = ingredients
        self.equipment = equipment
        self.steps = steps
        self.categories = categories
        self.summary_category = summary_category
        self.is_redirect = is_redirect

    @property
    def usable(self):
        """⚠️ THE ONLY DEFINITION OF `A RECIPE` THIS MODULE OFFERS, and it is deliberately thin: a
        page that names at least one ingredient. Page count is not recipe count and neither is
        the count that survives dish reduction. Anything stricter is a decision for the caller."""
        return not self.is_redirect and bool(self.ingredients)

    def __repr__(self):
        return (f"<Recipe {self.name!r} {len(self.ingredients)} ingredients "
                f"{self.steps} steps {len(self.categories)} categories>")


def page_name(title):
    """`Cookbook:Awug` to `Awug`. The namespace goes, the parenthetical stays for the caller."""
    return re.sub(r"^Cookbook:\s*", "", title).strip()


def summary_category(txt):
    """The Category field of the {{Recipe summary}} template, when the page carries one.

    ⚠️ PARSED BY HAND RATHER THAN BY A TEMPLATE LIBRARY. The name is written four ways in the
    corpus, `Recipesummary`, `Recipe summary`, `recipesummary` and `RecipeSummary`, and the field
    separator is a newline as often as a pipe.
    """
    m = re.search(r"\{\{\s*recipe\s*summary\s*(.*?)\}\}", txt, re.I | re.S)
    if not m:
        return ""
    f = re.search(r"\|\s*category\s*=\s*([^|\n}]+)", m.group(1), re.I)
    return strip_markup(f.group(1)).strip() if f else ""


def parse_page(title, txt):
    ing_body = _span(txt, lambda h: "ingredient" in h)
    eq_body = _span(txt, lambda h: h in ("equipment", "special equipment", "equipment needed"))
    proc_body = _span(txt, lambda h: h.startswith("procedure") or h in ("method", "directions",
                                                                        "preparation", "steps"))
    steps = len([l for l in proc_body.splitlines() if NUMBERED.match(l.strip())])
    return Recipe(
        title=title,
        name=page_name(title),
        ingredients=_bullets(ing_body) + _table_rows(ing_body),
        equipment=_bullets(eq_body),
        steps=steps,
        categories=[c.strip() for c in CATEGORY.findall(txt)],
        summary_category=summary_category(txt),
        is_redirect=bool(REDIRECT.match(txt)),
    )


def read(path):
    """Yield a Recipe per page from a fetched {title: wikitext} JSON file."""
    blob = json.load(open(path))
    pages = blob.get("wikitext", blob)
    for title, txt in pages.items():
        yield parse_page(title, txt)


def classify_category(cat):
    """(kind, value) for a Wikibooks category, or ('other', cat). Routing is the caller's call."""
    for kind, rx in CATEGORY_KINDS:
        m = rx.match(cat.strip())
        if m:
            return kind, m.group(1).strip().lower()
    return "other", cat.strip().lower()
