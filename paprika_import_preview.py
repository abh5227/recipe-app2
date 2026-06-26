#!/usr/bin/env python3
"""paprika_import_preview.py — READ-ONLY preview of Paprika HTML recipe exports.

Parses every .html in paprika_samples/ and PRINTS a structured preview per recipe:
title, metadata, ingredients (amount/text split + SECTION_HEADER vs INGREDIENT), steps,
and per-file PARSE NOTES flagging messy ingredient-text patterns — then a cross-file
summary. It WRITES NOTHING: no database, no files. This is a judgment tool to evaluate
parse quality before we design the importer. It does NOT clean text or link the library.

Needs BeautifulSoup:  pip install beautifulsoup4
Run:                  python3 paprika_import_preview.py
"""
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("BeautifulSoup not installed — run:  pip install beautifulsoup4")

SAMPLES = Path(__file__).resolve().parent / "paprika_samples"

# Unit words — used ONLY for the "count with no unit" flag, not for any cleaning/linking.
UNIT_WORDS = {
    "tsp", "teaspoon", "teaspoons", "tbsp", "tablespoon", "tablespoons", "cup", "cups",
    "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", "g", "gram", "grams", "kg",
    "ml", "l", "liter", "litre", "litres", "pinch", "clove", "cloves", "cm", "mm",
    "stick", "sticks", "can", "cans", "slice", "slices", "sprig", "sprigs", "handful",
}
_PREP = re.compile(
    r"\b(minced|chopped|sliced|diced|crushed|peeled|grated|halved|quartered|removed|divided|"
    r"crumbled|melted|softened|beaten|cubed|julienned|trimmed|drained|rinsed|shredded|seeded|"
    r"deboned|finely|roughly|thinly|packed|sifted|room temperature|skin on|bones?)\b", re.I)


def is_section_header(text):
    """A grouping label, not an ingredient/step: colon-terminated or ALL-CAPS."""
    t = text.strip()
    if not t:
        return False
    if t.endswith(":"):
        return True
    return any(c.isalpha() for c in t) and t.upper() == t


def split_amount_text(p):
    """(amount, text): amount = the <strong> contents (quantity), text = the rest of the line."""
    strong = p.find("strong")
    amount = strong.get_text(strip=True) if strong else ""
    full = p.get_text(" ", strip=True)
    full = re.sub(r"\s+", " ", full)
    text = full[len(amount):].strip() if amount and full.startswith(amount) else full
    return amount, text


def messy_flags(amount, text):
    """Observations (not errors) about messy patterns in the amount/text."""
    flags = []
    blob = (amount + " " + text)
    low = text.lower()
    if re.search(r"\bor\b", low):
        flags.append("alternative")
    if "(" in text or ")" in text:
        flags.append("parenthetical")
    if _PREP.search(text):
        flags.append("prep-note")
    if re.search(r"\d\s*[–—-]\s*\d", blob) or re.search(r"\b\d+\s+to\s+\d+\b", low):
        flags.append("range")
    if re.search(r"\b\d*\s*x\s*\d", low) or re.search(r"\b\d+(oz|g|kg|ml|lb|lbs)\b", low):
        flags.append("unusual-amount")
    if any(ord(c) > 127 for c in blob) or '"' in blob:
        flags.append("unicode")
    if re.fullmatch(r"\d+", amount):                          # bare integer count
        tokens = {t.strip(",.").lower() for t in text.split()}
        if not (tokens & UNIT_WORDS):
            flags.append("count-no-unit")
    return flags


def parse_recipe(div, stats):
    def prop(name):
        el = div.find(attrs={"itemprop": name})
        return el.get_text(" ", strip=True) if el else None

    # 1. Title
    print(f"  TITLE: {prop('name') or '(none)'}")

    # 2. Metadata
    yield_raw = prop("recipeYield")
    servings = None
    if yield_raw:
        m = re.search(r"\d+", yield_raw)
        servings = int(m.group()) if m else None
    url_el = div.find("a", attrs={"itemprop": "url"})
    rating_el = div.find(attrs={"itemprop": "aggregateRating"})
    rating = (rating_el.get("value") if rating_el and rating_el.get("value")
              else (rating_el.get_text(strip=True) if rating_el else None))
    cats = prop("recipeCategory")
    print("  META:")
    print(f"    prep={prop('prepTime') or '—'}  cook={prop('cookTime') or '—'}  "
          f"total={prop('totalTime') or '—'}  "
          f"servings={servings if servings is not None else '—'} (raw {yield_raw!r})")
    print(f"    source={url_el.get('href') if url_el else '—'}")
    print(f"    author={prop('author') or '—'}  rating={rating or '—'}")
    print(f"    categories={[c.strip() for c in cats.split(',')] if cats else []}")

    # 3. Ingredients
    print("  INGREDIENTS:")
    ing_ps = div.find_all("p", attrs={"itemprop": "recipeIngredient"})
    for p in ing_ps:
        amount, text = split_amount_text(p)
        full = p.get_text(" ", strip=True)
        stats["ingredient_lines"] += 1
        if is_section_header(full):
            stats["section_header"] += 1
            print(f"    [SECTION]    {full}")
            continue
        stats["ingredient"] += 1
        flags = messy_flags(amount, text)
        for f in flags:
            stats["flags"][f] += 1
        flagstr = f"   flags: {', '.join(flags)}" if flags else ""
        print(f"    [INGREDIENT] amt={amount!r:>8} | {text}{flagstr}")

    # 4. Steps
    print("  STEPS:")
    instr = div.find(attrs={"itemprop": "recipeInstructions"})
    step_ps = instr.find_all("p") if instr else []
    for i, p in enumerate(step_ps, 1):
        txt = p.get_text(" ", strip=True)
        if is_section_header(txt):
            print(f"    {i:>2}. [STEP-SECTION] {txt}")
        else:
            preview = txt if len(txt) <= 100 else txt[:97] + "..."
            print(f"    {i:>2}. {preview}")

    # 5. Parse notes (per-recipe roll-up of flags)
    file_flags = Counter()
    for p in ing_ps:
        amount, text = split_amount_text(p)
        if not is_section_header(p.get_text(" ", strip=True)):
            file_flags.update(messy_flags(amount, text))
    print("  PARSE NOTES (messy ingredient-text patterns):")
    if file_flags:
        for name, n in file_flags.most_common():
            print(f"    {name}: {n}")
    else:
        print("    (none)")


def main():
    if not SAMPLES.is_dir():
        sys.exit(f"No samples dir: {SAMPLES}")
    files = sorted(SAMPLES.glob("*.html"))
    if not files:
        sys.exit(f"No .html files in {SAMPLES}")

    stats = {"ingredient_lines": 0, "section_header": 0, "ingredient": 0, "flags": Counter()}
    for f in files:
        print("\n" + "=" * 78)
        print(f"FILE: {f.name}")
        print("=" * 78)
        soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
        recipes = soup.find_all(attrs={"itemtype": "http://schema.org/Recipe"})
        if not recipes:
            print("  (no schema.org Recipe found)")
            continue
        for div in recipes:
            parse_recipe(div, stats)

    print("\n" + "=" * 78)
    print(f"SUMMARY across {len(files)} file(s)")
    print("=" * 78)
    print(f"  ingredient lines total : {stats['ingredient_lines']}")
    print(f"    classified INGREDIENT: {stats['ingredient']}")
    print(f"    classified SECTION   : {stats['section_header']}")
    print("  messy-pattern tally (across INGREDIENT lines):")
    for name, n in stats["flags"].most_common():
        print(f"    {name}: {n}")


if __name__ == "__main__":
    main()
