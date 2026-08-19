"""URL import, stage 1 (U1): read schema.org/Recipe JSON-LD into the pipeline's normalized shape.

PURE — no network, no DB, no I/O. Input is HTML text (from url_fetch) plus the final URL; output is
either the 17-key normalized dict that import_cleanup.clean_recipe already consumes, or a Refused
saying why not. Refusals are VALUES so the cascade (U2) can compose them into one honest message.

⚠️ NEVER html.unescape() THE <script> BODY. Script content is RAW TEXT per the HTML spec, so entities
are NOT decoded before the JSON is parsed — they are decoded on the extracted string VALUES. Getting
this backwards is not theoretical: unescaping first turns a legitimate `10&quot;` (an inch mark, in a
real recipetineats step) into a bare quote, which breaks the enclosing JSON string and makes
json.loads fail. recipetineats.com — the single most-used site in this corpus, 28 recipes — then
reports as having no JSON-LD at all. There is a test pinned on that exact fixture.

Every shape handled below was MEASURED across the nine committed JSON-LD fixtures, not guessed:
  - the Recipe sits at the top level (2) or inside @graph at index 0, 6, 7, 7 or 10 (5) — so the
    search is recursive and never indexes.
  - pages carry up to 4 ld+json blocks; all are scanned.
  - author is an object with a name (4), a one-element list (3), or a bare {"@id"} REFERENCE (2)
    resolved against the graph. Unresolved, recipetineats loses "Nagi" and thewoksoflife "Kaitlin".
  - recipeInstructions is a list of HowToStep (7), a list of plain strings (1), or a list MIXING
    bare HowToSteps with HowToSections (hot-thai-kitchen: 3 loose steps, then 2 sections).
  - recipeYield is an int, a string, or a list whose element [0] is the number.
  - recipeCategory/recipeCuisine are lists OR comma-separated strings.
  - times are ISO-8601 strings, absent (recipetineats totalTime), or a Duration OBJECT carrying a
    minValue/maxValue range (seriouseats cookTime PT45M-PT70M).
  - values contain HTML entities ('thigh &amp; drumstick', "Bob&#39;s") and non-breaking spaces.
"""
import html as html_mod
import json
import re
from typing import NamedTuple

BLOCK_RE = re.compile(
    r'<script[^>]*\btype=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
ISO_RE = re.compile(
    r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?\Z", re.I)


class Refused(NamedTuple):
    """Why no recipe came out. `code` is stable; `detail` is a sentence; `context` is for the cascade."""
    code: str                    # NO_STRUCTURED_DATA | NOT_A_RECIPE | INCOMPLETE
    detail: str
    context: tuple = ()


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def text(value):
    """A JSON-LD string value -> clean display text.

    Tags are stripped BEFORE entities are decoded, so a literal `&lt;b&gt;` written by the publisher
    survives as visible text instead of becoming a tag and then being deleted. \xa0 is folded because
    a real HowToSection name ends with one.
    """
    if value is None:
        return ""
    out = TAG_RE.sub(" ", str(value))
    out = html_mod.unescape(out)                 # on the VALUE — never on the <script> body
    return re.sub(r"\s+", " ", out.replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------- #
# Finding the Recipe
# --------------------------------------------------------------------------- #
def blocks(page_html):
    """Every parseable ld+json block. A block that doesn't parse is skipped, not fatal — a page may
    carry several and only one need be good."""
    found = []
    for match in BLOCK_RE.finditer(page_html):
        body = match.group(1).strip()
        try:
            # strict=False tolerates raw control characters inside strings, which some CMSes emit.
            found.append(json.loads(body, strict=False))
        except ValueError:
            continue
    return found


def walk(node):
    """Every dict anywhere in the parsed JSON, at any depth. The Recipe's location is not fixed."""
    if isinstance(node, list):
        for item in node:
            yield from walk(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)


def types_of(node):
    raw = node.get("@type")
    return [t for t in (raw if isinstance(raw, list) else [raw]) if isinstance(t, str)]


def index_by_id(parsed):
    """@id -> the node that actually SAYS something, for resolving references.

    A NAMED node wins over a bare one, and that is the whole point rather than a nicety: the same
    @id appears FOUR times on the recipetineats page — once as the real Person carrying "Nagi", and
    three times as a bare {"@id": ...} back-reference. A plain last-wins dict keeps one of the
    stubs, the author resolves to nothing, and the recipe imports with no source. Measured.
    """
    index = {}
    for node in walk(parsed):
        key = node.get("@id")
        if not isinstance(key, str):
            continue
        known = index.get(key)
        if known is None or (node.get("name") and not known.get("name")):
            index[key] = node
    return index


# --------------------------------------------------------------------------- #
# Field mapping
# --------------------------------------------------------------------------- #
def iso_minutes(value):
    """ISO-8601 duration -> whole minutes, or None. Seconds are dropped: recipe times are not
    second-precision, and 'PT45M30S' rendering as '45 min' is right."""
    match = ISO_RE.fullmatch(str(value).strip())
    if not match:
        return None
    weeks, days, hours, minutes, _seconds = match.groups()
    total = (int(weeks or 0) * 7 * 24 * 60 + int(days or 0) * 24 * 60
             + int(hours or 0) * 60 + int(minutes or 0))
    return total or None


def duration_text(value):
    """ISO-8601 -> the human form this database already stores ('20 min', '1 hr 15 min')."""
    if isinstance(value, dict):
        # A Duration RANGE (seriouseats cookTime is PT45M-PT70M). These are single-value columns and
        # the stored format family has no range form, so ONE end of the range has to be chosen: the
        # UPPER bound. A cook time is a planning input, which makes underestimating the costlier
        # error — being told 45 min for something that takes 70 makes dinner late, while
        # overestimating only leaves slack. maxValue is also the outer bound the publisher actually
        # claims, so it is their statement rather than our guess.
        value = value.get("maxValue") or value.get("value") or ""
    if not isinstance(value, str):
        return ""
    minutes = iso_minutes(value)
    if not minutes:
        return ""
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} hr {rest} min"
    return f"{hours} hr" if hours else f"{rest} min"


def terms(value):
    """recipeCategory / recipeCuisine -> a flat list. Either may be a list or one comma-joined string."""
    out = []
    for item in (value if isinstance(value, list) else [value]):
        if isinstance(item, dict):
            item = item.get("name")
        for part in str(item or "").split(","):
            cleaned = text(part)
            if cleaned:
                out.append(cleaned)
    return out


def yield_text(value):
    """recipeYield -> the servings string. In every sampled list form, element [0] is the number
    ('4' from ['4', '4 servings']), which is what the servings parser wants."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("value") or ""
    return text(value) if value not in (None, "") else ""


def author_name(recipe, by_id):
    """The author's name, resolving an {"@id": ...} reference against the graph.

    Two of nine fixtures use a bare reference. Left unresolved this silently yields nothing —
    recipetineats loses "Nagi", thewoksoflife loses "Kaitlin" — which is the quiet kind of wrong.
    """
    author = recipe.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    if isinstance(author, str):
        return text(author)
    if isinstance(author, dict):
        if author.get("name"):
            return text(author["name"])
        target = by_id.get(author.get("@id"))
        if target and target.get("name"):
            return text(target["name"])
    return ""


def directions(instructions):
    """recipeInstructions -> the flat list of lines the seam accepts, sections included.

    A HowToSection's `name` becomes a HEADING line and its itemListElement entries follow beneath it;
    bare steps before the first section are an unsectioned preamble, which the pipeline already
    models. A COLON IS APPENDED when the name lacks one — deliberately. The JSON-LD told us
    explicitly that this is a section, but `directions` is a flat list of strings, so that fact would
    be lost at the seam; the colon is how it survives, letting classify_step mark the heading
    deterministically instead of depending on the publisher's punctuation.
    """
    lines = []

    def add(node):
        if isinstance(node, str):
            line = text(node)
            if line:
                lines.append(line)
        elif isinstance(node, dict):
            if "HowToSection" in types_of(node):
                name = text(node.get("name"))
                if name:
                    lines.append(name if name.endswith(":") else name + ":")
                for child in node.get("itemListElement") or []:
                    add(child)
            else:
                line = text(node.get("text") or node.get("name"))
                if line:
                    lines.append(line)

    if isinstance(instructions, str):
        for piece in instructions.split("\n"):
            line = text(piece)
            if line:
                lines.append(line)
    else:
        for node in instructions or []:
            add(node)
    return lines


# --------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------- #
def read(page_html, url=""):
    """HTML -> the 17-key normalized dict, or Refused. `url` is the FINAL url from the fetcher."""
    parsed = blocks(page_html)
    if not parsed:
        return Refused("NO_STRUCTURED_DATA", "the page carries no JSON-LD")

    by_id = index_by_id(parsed)
    recipes = [node for node in walk(parsed) if "Recipe" in types_of(node)]
    if not recipes:
        seen = tuple(sorted({t for node in walk(parsed) for t in types_of(node)}))
        described = ", ".join(seen[:4]) if seen else "nothing recognisable"
        return Refused("NOT_A_RECIPE", f"the page's JSON-LD describes {described}, not a Recipe", seen)

    recipe = recipes[0]
    name = text(recipe.get("name"))
    ingredient_lines = [line for line in (text(i) for i in recipe.get("recipeIngredient") or []) if line]
    steps = directions(recipe.get("recipeInstructions"))

    # "Usable" is name + at least one ingredient + at least one step. Everything else is optional:
    # those three are what it takes to produce a recipe row with children, and a weaker bar accepts
    # pages that yield an ingredient list and nothing to do with it.
    missing = ([] if name else ["a name"]) + ([] if ingredient_lines else ["ingredients"]) \
        + ([] if steps else ["steps"])
    if missing:
        return Refused("INCOMPLETE", f"the JSON-LD Recipe has no {', '.join(missing)}", tuple(missing))

    return {
        "name": name,
        "ingredient_lines": ingredient_lines,
        "directions": steps,
        "servings_raw": yield_text(recipe.get("recipeYield")),
        "source": author_name(recipe, by_id),
        "source_url": url,                       # the FINAL url after redirects — also the dedup key
        "categories": list(dict.fromkeys(terms(recipe.get("recipeCategory"))
                                         + terms(recipe.get("recipeCuisine")))),
        "description": text(recipe.get("description")),
        "prep_time": duration_text(recipe.get("prepTime")),
        "cook_time": duration_text(recipe.get("cookTime")),
        "total_time": duration_text(recipe.get("totalTime")),
        "notes": "",
        # RATING IS DELIBERATELY 0, NOT aggregateRating. That number is strangers' opinion of the
        # recipe; this app's ratings are cook-gated on purpose, because the outcome data — what THIS
        # cook made and thought — is the entire point of the app. Importing a publisher's average
        # would poison exactly the signal being collected. Do not "fix" this.
        "rating": 0,
        "uid": "",                               # Paprika's dedup key; a URL import has none
        "hash": "",
        "images": [],                            # image handling is a later pass, as with Paprika
        "primary_photo": None,
    }
