#!/usr/bin/env python3
"""paprika_format_study.py — READ-ONLY study of the Paprika HTML export format.

Aggregates across every paprika_samples/*.html to understand the format's STRUCTURE and
VARIATION before we design the import core. Reports field presence/format, image layout,
source shapes, section-header classification reliability (the key risk), amount/unit
patterns, and other quirks. WRITES NOTHING — no DB, no files, no image copies. It studies
and reports only; it does not clean text or link the library.

Needs BeautifulSoup:  pip install beautifulsoup4
Run:                  python3 paprika_format_study.py
"""
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("BeautifulSoup not installed — run:  pip install beautifulsoup4")

SAMPLES = Path(__file__).resolve().parent.parent / "paprika_samples"  # study/ -> repo root
UNICODE_FRAC = "¼½¾⅓⅔⅛⅜⅝⅞⅙⅚⅕⅖⅗⅘⅐⅑⅒"
UNIT_WORDS = {
    "tsp", "teaspoon", "teaspoons", "tbsp", "tablespoon", "tablespoons", "cup", "cups",
    "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", "g", "gram", "grams", "kg",
    "ml", "l", "liter", "litre", "litres", "pinch", "clove", "cloves", "cm", "mm",
    "stick", "sticks", "can", "cans", "slice", "slices", "sprig", "sprigs", "handful",
    "pint", "quart", "gallon", "dash", "knob", "bunch", "head",
}
_PREP = re.compile(
    r"\b(minced|chopped|sliced|diced|crushed|peeled|grated|halved|quartered|removed|divided|"
    r"crumbled|melted|softened|beaten|cubed|julienned|trimmed|drained|rinsed|shredded|seeded|"
    r"deboned|finely|roughly|thinly|packed|sifted|room temperature|skin on|bones?)\b", re.I)
_MISSED_HEADER = re.compile(r"^(for the\b|to (make|serve|assemble|finish)\b|the .* (sauce|dressing|topping)\b)", re.I)


def is_section_header(text):
    t = text.strip()
    if not t:
        return False
    if t.endswith(":"):
        return "colon"
    if any(c.isalpha() for c in t) and t.upper() == t:
        return "allcaps"
    return False


def split_amount_text(p):
    strong = p.find("strong")
    amount = strong.get_text(strip=True) if strong else ""
    full = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
    text = full[len(amount):].strip() if amount and full.startswith(amount) else full
    return amount, text


def yield_shape(v):
    if v is None:
        return "absent"
    if re.fullmatch(r"\s*Servings\s+\d+\s*", v):
        return '"Servings N"'
    if re.fullmatch(r"\s*\d+\s*", v):
        return '"N"'
    if re.search(r"\d", v):
        return "other-with-number"
    return "text-no-number"


def main():
    files = sorted(SAMPLES.glob("*.html"))
    if not files:
        sys.exit(f"No .html in {SAMPLES}")

    FIELDS = ["name", "recipeIngredient", "recipeInstructions", "recipeYield",
              "recipeCategory", "prepTime", "cookTime", "totalTime",
              "aggregateRating", "author", "url", "nutrition"]
    present = Counter()
    n_files = len(files)
    recipes_per_file = Counter()
    yield_shapes = Counter()
    yield_examples = set()
    time_examples = {"prepTime": set(), "cookTime": set(), "totalTime": set()}
    source_shapes = Counter()
    author_only_examples = set()
    notes_present = 0

    # images
    img_counts = Counter()           # number of itemprop=image per recipe
    img_path_ok = 0
    img_path_missing = 0
    img_path_pattern = Counter()
    img_has_dims = 0

    # sections
    section_lines = []               # (file, text, rule)
    suspected_missed = []            # (file, text)  no-amount lines that look like headers
    false_positive = []             # SECTION-classified lines that look like real ingredients

    # amount/unit patterns
    pat = Counter()
    total_ing = 0
    unit_case = {}                   # lowercased unit-ish first token -> set of raw casings
    quirks = Counter()

    for f in files:
        soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
        recipes = soup.find_all(attrs={"itemtype": "http://schema.org/Recipe"})
        recipes_per_file[len(recipes)] += 1
        for div in recipes:
            def prop(name):
                el = div.find(attrs={"itemprop": name})
                return el.get_text(" ", strip=True) if el else None

            for fld in FIELDS:
                if div.find(attrs={"itemprop": fld}) is not None:
                    present[fld] += 1

            yv = prop("recipeYield")
            yield_shapes[yield_shape(yv)] += 1
            if yv:
                yield_examples.add(yv.strip())
            for t in ("prepTime", "cookTime", "totalTime"):
                tv = prop(t)
                if tv:
                    time_examples[t].add(tv.strip())

            # notes (Paprika 'notesbox' / itemprop comment)
            if div.find(attrs={"itemprop": "comment"}) or div.select_one(".notesbox"):
                notes_present += 1

            # source shape
            has_url = div.find("a", attrs={"itemprop": "url"}) is not None
            au = prop("author")
            has_author = bool(au)
            if has_url and has_author:
                source_shapes["url+author"] += 1
            elif has_url:
                source_shapes["url only"] += 1
            elif has_author:
                source_shapes["author only"] += 1
                author_only_examples.add(au.strip())
            else:
                source_shapes["none"] += 1

            # images
            imgs = div.find_all("img", attrs={"itemprop": "image"})
            img_counts[len(imgs)] += 1
            for im in imgs:
                src = im.get("src", "")
                if re.match(r"Images/[0-9A-Fa-f-]+/[^/]+\.(jpg|jpeg|png)$", src):
                    img_path_pattern["Images/<UUID>/<file>.<ext>"] += 1
                elif src:
                    img_path_pattern[f"other: {src[:40]}"] += 1
                if im.get("width") or im.get("height"):
                    img_has_dims += 1
                if src and (SAMPLES / src).exists():
                    img_path_ok += 1
                elif src:
                    img_path_missing += 1

            # ingredients: sections + amount/unit patterns
            for p in div.find_all("p", attrs={"itemprop": "recipeIngredient"}):
                amount, text = split_amount_text(p)
                full = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
                rule = is_section_header(full)
                if rule:
                    section_lines.append((f.name, full, rule))
                    # false positive? a "section" that still has a numeric amount + unit-ish text
                    if re.search(r"\d", amount) and any(t.strip(",.").lower() in UNIT_WORDS for t in text.split()):
                        false_positive.append((f.name, full))
                    continue
                total_ing += 1
                # suspected missed header: no amount, short, header-ish phrasing
                if not amount and (_MISSED_HEADER.match(text) or
                                   (len(text.split()) <= 4 and text and text[0].isupper()
                                    and not re.search(r"\d", text)
                                    and not (set(t.lower() for t in text.split()) & UNIT_WORDS)
                                    and text.lower() not in {"salt", "sea salt", "pepper",
                                       "kosher salt", "black pepper", "olive oil", "water"})):
                    suspected_missed.append((f.name, text))

                blob = amount + " " + text
                low = text.lower()
                if any(c in UNICODE_FRAC for c in amount):
                    pat["unicode-fraction in amount"] += 1
                if re.search(r"\d+\s+\d+/\d+", amount) or re.search(r"\d[" + UNICODE_FRAC + r"]", amount) or re.search(r"\d\s+[" + UNICODE_FRAC + r"]", amount):
                    pat["mixed number"] += 1
                if re.search(r"\d\s*[–—-]\s*\d", blob) or re.search(r"\b\d+\s+to\s+\d+\b", low):
                    pat["range"] += 1
                if re.search(r"\b\d*\s*x\s*\d", low) or re.search(r"\b\d+\s*x\b", low):
                    pat['"x" amount'] += 1
                if amount == "":
                    pat["empty amount"] += 1
                if re.search(r"\bplus\b.*\b(tbsp|tsp|cup|cups|teaspoon|tablespoon|gram|grams|oz|lb)\b", low):
                    pat["secondary amount in text"] += 1
                if re.search(r"\bof\b", " ".join(text.split()[:3]).lower()):
                    pat['"of" filler'] += 1
                if re.search(r"\(\s*(?:about\s*)?\d[\d.]*\s*(?:grams?|g)\b", low):
                    pat["parenthetical grams"] += 1
                if "(" in text:
                    pat["parenthetical (any)"] += 1
                if re.search(r"\bor\b", low):
                    pat["alternative (or ...)"] += 1
                if _PREP.search(text):
                    pat["prep-note"] += 1
                if re.fullmatch(r"\d+", amount):
                    toks = {t.strip(",.").lower() for t in text.split()}
                    if not (toks & UNIT_WORDS):
                        pat["count, no unit"] += 1
                # unit-case tracking (first token, if it's a unit word ignoring case)
                if text.split():
                    first = text.split()[0].strip(",.")
                    if first.lower() in UNIT_WORDS:
                        unit_case.setdefault(first.lower(), set()).add(first)
                # encoding quirks
                if "″" in blob or '"' in blob:
                    quirks['inch-mark / quote (″ or ")'] += 1

            # malformed: recipe with no ingredients or no instructions
            if not div.find_all("p", attrs={"itemprop": "recipeIngredient"}):
                quirks["recipe with NO ingredients"] += 1
            if div.find(attrs={"itemprop": "recipeInstructions"}) is None:
                quirks["recipe with NO instructions block"] += 1

    # ---------------- report ----------------
    def bar(n):
        return f"{n:>4}/{n_files}  ({100*n//n_files:>3}%)"

    print("=" * 80)
    print(f"PAPRIKA FORMAT STUDY — {n_files} HTML files")
    print("=" * 80)

    print("\n[1] FIELD PRESENCE")
    for fld in FIELDS:
        print(f"  {fld:<20} {bar(present[fld])}")
    print(f"  {'notes/comment':<20} {bar(notes_present)}")

    print("\n[1b] FORMAT VARIATION")
    print("  recipeYield shapes:", dict(yield_shapes))
    print("  recipeYield examples:", sorted(yield_examples)[:8], "..." if len(yield_examples) > 8 else "")
    for t in ("prepTime", "cookTime", "totalTime"):
        ex = sorted(time_examples[t])
        print(f"  {t} examples ({len(ex)} distinct):", ex[:8], "..." if len(ex) > 8 else "")
    print("  recipes per file:", dict(recipes_per_file))

    print("\n[2] IMAGES")
    print("  images (itemprop=image) per recipe:", dict(sorted(img_counts.items())))
    print("  src path pattern:", dict(img_path_pattern))
    print(f"  src resolves to a file on disk: {img_path_ok} yes, {img_path_missing} missing")
    print(f"  <img> carries width/height attrs: {img_has_dims}")
    print(f"  Images/ tree on disk: {sum(1 for _ in (SAMPLES/'Images').glob('*'))} recipe folders, "
          f"{sum(1 for _ in (SAMPLES/'Images').rglob('*') if _.is_file())} files")

    print("\n[3] SOURCE SHAPES")
    for shape, n in source_shapes.most_common():
        print(f"  {shape:<14} {n}")
    print("  author-only examples:", sorted(author_only_examples)[:12])

    print("\n[4] SECTION HEADERS  (key risk: classification reliability)")
    print(f"  total SECTION-classified lines: {len(section_lines)} "
          f"(colon={sum(1 for _,_,r in section_lines if r=='colon')}, "
          f"allcaps={sum(1 for _,_,r in section_lines if r=='allcaps')})")
    for fn, txt, rule in section_lines:
        print(f"    [{rule:<7}] {txt}   ({fn})")
    print(f"  FALSE POSITIVES (looks like a real ingredient but caught as section): {len(false_positive)}")
    for fn, txt in false_positive:
        print(f"    ! {txt}   ({fn})")
    print(f"  SUSPECTED MISSED headers (no amount, header-ish, NOT caught — review): {len(suspected_missed)}")
    for fn, txt in suspected_missed[:25]:
        print(f"    ? {txt}   ({fn})")
    if len(suspected_missed) > 25:
        print(f"    ... +{len(suspected_missed)-25} more")

    print("\n[5] AMOUNT / UNIT PATTERNS  (across", total_ing, "INGREDIENT lines)")
    for name, n in pat.most_common():
        print(f"  {name:<26} {n:>4}  ({100*n//max(total_ing,1):>3}%)")
    mixedcase = {u: sorted(c) for u, c in unit_case.items() if len(c) > 1}
    print("  unit case inconsistency:", mixedcase if mixedcase else "(none)")

    print("\n[6] OTHER QUIRKS")
    for name, n in quirks.most_common():
        print(f"  {name:<34} {n}")
    if not quirks:
        print("  (none)")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  files: {n_files} | ingredient lines: {total_ing} + {len(section_lines)} section headers")
    print(f"  section-classification risk: {len(false_positive)} false-positive, "
          f"{len(suspected_missed)} suspected-missed (of {total_ing+len(section_lines)} lines)")
    print(f"  image path pattern: {dict(img_path_pattern)} | on-disk resolve: {img_path_ok} ok / {img_path_missing} missing")
    print("  per-field presence: " + ", ".join(f"{fld} {100*present[fld]//n_files}%" for fld in
          ["name", "recipeIngredient", "recipeInstructions", "recipeYield", "prepTime",
           "cookTime", "aggregateRating", "url", "author"]))


if __name__ == "__main__":
    main()
