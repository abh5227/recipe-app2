"""U1: reading schema.org/Recipe JSON-LD into the pipeline's normalized shape.

Every test runs against U0's committed fixtures — real pages, no network, no DB. The shapes being
handled were measured from those nine pages, so the tests assert against what publishers actually
emit rather than against the spec's happy path.
"""
import json
import pathlib
import socket

import pytest

import import_cleanup as cleanup
import import_write as iw
import url_jsonld as reader

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"
MANIFEST = {r["domain"]: r for r in json.loads((FIXTURES / "manifest.json").read_text())}

# the seam's contract — import_cleanup.clean_recipe consumes exactly these
KEYS = {"name", "ingredient_lines", "directions", "servings_raw", "source", "source_url",
        "categories", "description", "prep_time", "cook_time", "total_time", "notes",
        "rating", "uid", "hash", "images", "primary_photo"}

JSON_LD = sorted(d for d, r in MANIFEST.items() if r["case"] == "json-ld")
NO_RECIPE = sorted(d for d, r in MANIFEST.items() if r["case"] != "json-ld")


def read(domain):
    row = MANIFEST[domain]
    return reader.read((FIXTURES / row["file"]).read_text(errors="replace"), row["url"])


# ----------------------------------------------------------------- THE TRAP (pinned first)
def test_script_body_entities_do_not_break_the_json():
    """THE REGRESSION THIS MODULE EXISTS TO NOT REPEAT.

    A <script> body is RAW TEXT per the HTML spec, so entities must NOT be decoded before json.loads.
    recipetineats writes a real inch mark as `10&quot;` inside a step; unescaping the body first
    turns that into a bare quote, breaks the enclosing JSON string, and makes the page — the single
    most-used site in this corpus — read as having no JSON-LD at all.
    """
    got = read("recipetineats.com")
    assert not isinstance(got, reader.Refused), f"the &quot; trap is back: {got}"
    step = next(s for s in got["directions"] if "dutch oven" in s.lower())
    assert '10"' in step                      # decoded on the VALUE...
    assert "&quot;" not in step               # ...exactly once, not left raw


def test_the_trap_fixture_really_contains_the_entity():
    """Guards the guard: if recipetineats ever re-publishes without `&quot;`, the test above would
    keep passing while testing nothing."""
    raw = (FIXTURES / "recipetineats.com.html").read_text(errors="replace")
    assert "&quot;" in raw


# ----------------------------------------------------------------- the corpus
@pytest.mark.parametrize("domain", JSON_LD)
def test_every_jsonld_fixture_reads(domain):
    got = read(domain)
    assert not isinstance(got, reader.Refused), f"{domain}: {got}"
    assert set(got) == KEYS                                   # exactly the 17, no more, no fewer
    assert got["name"] and got["ingredient_lines"] and got["directions"]
    assert got["source_url"] == MANIFEST[domain]["url"]       # the final url, carried through


@pytest.mark.parametrize("domain", JSON_LD)
def test_every_jsonld_fixture_names_its_author(domain):
    """Author resolution is the quietest failure in this reader — an unhandled shape yields '' and
    the recipe imports with no source rather than erroring. All nine carry one."""
    assert read(domain)["source"], f"{domain} lost its author"


@pytest.mark.parametrize("domain,expected", [("recipetineats.com", "Nagi"),
                                             ("thewoksoflife.com", "Kaitlin")])
def test_author_given_only_as_an_id_reference_is_resolved(domain, expected):
    """Two fixtures give author as a bare {"@id": ...} that must be resolved against the graph.

    recipetineats repeats that @id FOUR times — one real Person plus three bare back-references —
    so a last-wins index keeps a stub and the name vanishes. index_by_id prefers the named node.
    """
    assert read(domain)["source"] == expected


# ----------------------------------------------------------------- sections
def test_howtosection_becomes_a_heading_line_with_a_colon():
    got = read("hot-thai-kitchen.com")
    lines = got["directions"]
    assert len(lines) == 12                                   # 3 loose + (1 + 3) + (1 + 4)
    assert lines[3] == "How to make nam jim jeaw dipping sauce:"   # \xa0 folded, colon already there
    assert lines[7] == "To grill the chicken:"
    assert not lines[0].endswith(":")                         # the preamble stays plain


def test_a_section_name_without_a_colon_gets_one():
    """The colon is how "this is a section" survives a seam that carries only a flat list of
    strings — so it is appended when the publisher didn't write one, and never doubled."""
    out = reader.directions([
        {"@type": "HowToSection", "name": "For the dashi",
         "itemListElement": [{"@type": "HowToStep", "text": "Soak the kombu."}]},
        {"@type": "HowToSection", "name": "Already punctuated:",
         "itemListElement": [{"@type": "HowToStep", "text": "Fry."}]},
    ])
    assert out == ["For the dashi:", "Soak the kombu.", "Already punctuated:", "Fry."]


def test_plain_string_instructions_are_split_into_lines():
    assert reader.directions("Mix it.\n\nBake it.\n") == ["Mix it.", "Bake it."]


# ----------------------------------------------------------------- refusals
@pytest.mark.parametrize("domain", NO_RECIPE)
def test_pages_without_a_jsonld_recipe_refuse(domain):
    got = read(domain)
    assert isinstance(got, reader.Refused)
    assert got.code in ("NO_STRUCTURED_DATA", "NOT_A_RECIPE")
    assert got.detail


def test_nigella_refuses_because_microdata_is_not_this_layers_job():
    got = read("nigella.com")
    assert isinstance(got, reader.Refused)
    assert got.code == "NO_STRUCTURED_DATA"          # it carries microdata; that is U3


def test_a_page_with_other_jsonld_says_what_it_found_instead():
    """A page describing an Article is a different failure from a page describing nothing, and the
    cascade can say so. lahbco/probablyworthsharing/notanothercookingshow are all this case."""
    got = read("lahbco.com")
    assert got.code == "NOT_A_RECIPE"
    assert "Article" in got.detail and got.context


def test_incomplete_recipe_refuses_and_names_what_is_missing():
    page = ('<script type="application/ld+json">'
            '{"@type":"Recipe","name":"Half a recipe","recipeIngredient":["1 egg"]}</script>')
    got = reader.read(page, "https://example.test/x")
    assert got.code == "INCOMPLETE" and "steps" in got.detail


def test_unparseable_block_is_skipped_not_fatal():
    """A page may carry several blocks; one bad one must not lose the good one."""
    page = ('<script type="application/ld+json">{ this is not json </script>'
            '<script type="application/ld+json">'
            '{"@type":"Recipe","name":"Fine","recipeIngredient":["1 egg"],'
            '"recipeInstructions":[{"@type":"HowToStep","text":"Cook."}]}</script>')
    got = reader.read(page, "https://example.test/x")
    assert not isinstance(got, reader.Refused) and got["name"] == "Fine"


# ----------------------------------------------------------------- field mapping
@pytest.mark.parametrize("iso,expected", [
    ("PT20M", "20 min"), ("PT1H", "1 hr"), ("PT1H15M", "1 hr 15 min"),
    ("PT2H45M", "2 hr 45 min"), ("PT90M", "1 hr 30 min"),      # normalised, not left as 90 min
    ("PT45M30S", "45 min"),                                     # seconds dropped
    ("", ""), (None, ""), ("nonsense", ""), ("PT0S", ""),
])
def test_durations_become_the_strings_this_db_already_stores(iso, expected):
    assert reader.duration_text(iso) == expected


def test_a_duration_range_object_takes_the_upper_bound():
    """seriouseats publishes BOTH cookTime and totalTime as Durations with minValue/maxValue. These
    are single-value columns, so one end has to be chosen, and it is the upper one: a cook time is a
    planning input, so underestimating is the costlier error — 45 min for something that takes 70
    makes dinner late, while overestimating only leaves slack."""
    assert reader.duration_text({"@type": "Duration", "minValue": "PT45M", "maxValue": "PT70M"}) == "1 hr 10 min"
    got = read("seriouseats.com")
    assert got["cook_time"] == "1 hr 10 min"            # PT45M-PT70M
    assert got["total_time"] == "1 hr 20 min"           # PT55M-PT80M, the same treatment
    assert got["prep_time"] == "10 min"                 # a plain string on the same page, unaffected


def test_a_duration_object_without_a_range_still_reads():
    """Not every Duration object carries min/max; a bare value must not fall through to ''."""
    assert reader.duration_text({"@type": "Duration", "value": "PT25M"}) == "25 min"
    assert reader.duration_text({"@type": "Duration"}) == ""


def test_missing_time_is_empty_not_none():
    assert read("recipetineats.com")["total_time"] == ""       # the page omits totalTime


@pytest.mark.parametrize("value,expected", [
    (4, "4"), ("2 to 4 servings", "2 to 4 servings"),
    (["4", "4 servings"], "4"), (['16', 'one 8" square'], "16"), ([], ""), (None, ""),
])
def test_yield_takes_the_number_when_given_a_list(value, expected):
    assert reader.yield_text(value) == expected


def test_categories_merge_category_and_cuisine_from_lists_or_commas():
    assert read("thewoksoflife.com")["categories"] == ["Tofu", "Chinese"]
    assert reader.terms("Dinner, Lunch, Main course") == ["Dinner", "Lunch", "Main course"]
    assert reader.terms(["A", {"name": "B"}]) == ["A", "B"]


def test_entities_and_markup_in_values_are_cleaned():
    assert reader.text("thigh &amp; drumstick") == "thigh & drumstick"
    assert reader.text("Bob&#39;s Red Mill") == "Bob's Red Mill"
    assert reader.text("a<b>bold</b> step") == "a bold step"          # tags stripped
    assert reader.text("&lt;not a tag&gt;") == "<not a tag>"          # ...but escaped ones survive
    assert reader.text("ends with nbsp\xa0") == "ends with nbsp"


def test_rating_is_always_zero_never_the_publishers_average():
    """aggregateRating is strangers' opinion. This app's ratings are cook-gated by design, and the
    outcome data is the whole point — importing a publisher's average would poison it."""
    for domain in JSON_LD:
        assert read(domain)["rating"] == 0


def test_uid_and_hash_are_empty_for_a_url_import():
    got = read("bbcgoodfood.com")
    assert got["uid"] == "" and got["hash"] == ""
    assert got["images"] == [] and got["primary_photo"] is None and got["notes"] == ""


# ----------------------------------------------------------------- the seam
def test_the_sectioned_recipe_survives_clean_recipe_and_plan_recipe():
    """THE PROOF THE SEAM HOLDS. The reader's output goes through the REAL cleanup and write plan,
    and the two HowToSections come out the far end as is_heading step rows at the right positions —
    which is the entire reason `directions` became a list."""
    got = read("hot-thai-kitchen.com")
    plan = iw.plan_recipe(cleanup.clean_recipe(got), {}, set())
    assert plan["decision"] == "write"
    assert plan["recipe"]["author"] == "Pailin Chongchitnant"
    assert plan["recipe"]["servings"] == "4"
    assert [s["position"] for s in plan["steps"] if s["is_heading"]] == [3, 7]
    assert plan["steps"][3]["text"] == "How to make nam jim jeaw dipping sauce:"
    assert plan["steps"][7]["text"] == "To grill the chicken:"
    assert len(plan["steps"]) == 12 and len(plan["ingredients"]) == 21


@pytest.mark.parametrize("domain", JSON_LD)
def test_every_jsonld_fixture_plans_a_writable_recipe(domain):
    """Not just parseable — actually plannable, for all nine."""
    plan = iw.plan_recipe(cleanup.clean_recipe(read(domain)), {}, set())
    assert plan["decision"] == "write"
    assert plan["recipe"]["name"] and plan["ingredients"] and plan["steps"]


# ----------------------------------------------------------------- purity
def test_the_reader_touches_no_network():
    """U1 is pure: HTML in, dict out. If a future change reaches for a URL, this fails."""
    real = socket.socket
    socket.socket = lambda *a, **k: pytest.fail("the reader opened a socket")
    try:
        assert read("allrecipes.com")["name"]
    finally:
        socket.socket = real
