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
        "rating", "uid", "hash", "images", "primary_photo",
        "source_rating"}   # migration 048: the publisher's number, kept apart from "rating"

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
    assert set(got) == KEYS                                   # exactly the 18, no more, no fewer
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
    assert got["primary_photo"] is None and got["notes"] == ""


# ----------------------------------------------------------------- the image
# `images` used to be a hardcoded [] with "a later pass" beside it. It now carries the candidate
# urls in the page's own order. NOTHING is chosen here — see image_urls' docstring and url_image.
def test_every_readable_fixture_publishes_an_image():
    """Nine of nine. There is no "usually absent" case to design around, which is also why there is
    no og:image fallback: it would never fire."""
    for domain in JSON_LD:
        assert read(domain)["images"], f"{domain} lost its image"


def test_the_order_the_page_published_is_the_order_that_comes_out():
    """hot-thai-kitchen publishes three thumbnails before the full-size photo. Reordering here would
    hide from url_image.pick_hero the one thing it needs to fix that."""
    got = read("hot-thai-kitchen.com")["images"]
    assert len(got) == 4
    assert got[0].endswith("-225x225.jpg")
    assert got[-1].endswith("gai-yang-bbq-chicken-new-sq-2.jpg")


@pytest.mark.parametrize("domain,shape", [
    ("kingarthurbaking.com", "a bare ImageObject dict"),
    ("bbcgoodfood.com", "a list holding one dict"),
    ("cooking.nytimes.com", "a list of four dicts"),
    ("minimalistbaker.com", "a list holding one string"),
    ("thewoksoflife.com", "a list of four strings"),
])
def test_all_four_published_shapes_yield_http_urls(domain, shape):
    got = read(domain)["images"]
    assert got, shape
    assert all(u.startswith("https://") for u in got), shape


def test_the_dict_form_prefers_url_and_falls_back_to_contentUrl():
    """nytimes carries both, holding the same value. contentUrl alone is legal and unseen here."""
    assert reader.image_urls({"@type": "ImageObject", "url": "https://a.test/1.jpg",
                              "contentUrl": "https://a.test/2.jpg"}) == ["https://a.test/1.jpg"]
    assert reader.image_urls({"@type": "ImageObject",
                              "contentUrl": "https://a.test/2.jpg"}) == ["https://a.test/2.jpg"]


def test_a_bare_string_is_accepted_though_no_fixture_publishes_one():
    assert reader.image_urls("https://a.test/hero.jpg") == ["https://a.test/hero.jpg"]


def test_a_relative_url_is_resolved_against_the_page():
    assert reader.image_urls("/img/hero.jpg", "https://a.test/recipes/x") == ["https://a.test/img/hero.jpg"]


@pytest.mark.parametrize("value", [None, "", [], {}, [None, ""], {"@type": "ImageObject"}])
def test_an_absent_or_empty_image_yields_no_candidates_and_never_raises(value):
    assert reader.image_urls(value) == []


def test_values_that_are_not_web_urls_are_dropped_before_the_transport_layer():
    """A data: or file: value would otherwise be handed to the fetcher. url_image refuses them too,
    but a value the page chose should not reach it in the first place."""
    assert reader.image_urls(["data:image/png;base64,iVBORw0KGgo=", "file:///etc/passwd",
                              "javascript:alert(1)", "https://a.test/ok.jpg"]) == ["https://a.test/ok.jpg"]


def test_duplicate_candidates_are_collapsed():
    """recipetineats publishes the same file four times with different resize parameters. Identical
    urls are worth dropping; differing ones are not, because they may differ in size."""
    assert reader.image_urls(["https://a.test/x.jpg", "https://a.test/x.jpg"]) == ["https://a.test/x.jpg"]


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


# ---------------------------------------------------------------- the publisher's number (item 9)
# ⚠️ THIS IS NOT THE COOK'S RATING. It is a dated observation of one web page, stored apart in
# recipe_source_ratings. The reader's "rating": 0 is unchanged and these tests pin that it stays 0.

def test_source_rating_is_read_but_never_becomes_the_cooks_rating():
    """Eight of the nine Recipe fixtures publish one, and reading it must not touch `rating`."""
    carried = {d: read(d)["source_rating"] for d in JSON_LD if isinstance(read(d), dict)}
    with_rating = {d: v for d, v in carried.items() if v}
    assert len(with_rating) == 8
    assert set(carried) - set(with_rating) == {"bbcgoodfood.com"}   # its Recipe node has none
    for d in JSON_LD:
        assert read(d)["rating"] == 0        # the cook's verdict is untouched on every single one


def test_source_rating_coerces_the_published_type():
    """⚠️ Publishers send BOTH '4.70' and 5, so a reader that trusts the type gets one of them wrong."""
    assert reader.source_rating({"ratingValue": "4.70", "ratingCount": "885"})["value"] == 4.7
    assert reader.source_rating({"ratingValue": 5, "ratingCount": 1972})["value"] == 5.0
    assert reader.source_rating({"ratingValue": "4.70"})["count"] is None
    assert reader.source_rating({"ratingCount": "10"}) is None        # no value -> no observation
    assert reader.source_rating({"ratingValue": "n/a"}) is None
    assert reader.source_rating(None) is None and reader.source_rating("4.5") is None


def test_the_five_point_scale_is_recorded_as_an_assumption():
    """⚠️ bestRating is absent from all 8. A 9.2 out of 10 stored as 9.2 out of 5 is a false claim,
    so the guess is carried with the number rather than silently applied."""
    assumed = reader.source_rating({"ratingValue": "4.5"})
    assert assumed["scale"] == 5.0 and assumed["scale_assumed"] is True
    stated = reader.source_rating({"ratingValue": "9.2", "bestRating": "10"})
    assert stated["scale"] == 10.0 and stated["scale_assumed"] is False
    for d in JSON_LD:
        got = read(d)
        if isinstance(got, dict) and got["source_rating"]:
            assert got["source_rating"]["scale_assumed"] is True   # true for every real fixture


def test_rating_count_wins_over_review_count():
    """recipetineats publishes 2,124 ratings and 6 reviews for the same dish. Reading the smaller
    one understates the audience by a factor of 350."""
    both = reader.source_rating({"ratingValue": "4.96", "ratingCount": "2124", "reviewCount": "6"})
    assert both["count"] == 2124
    assert read("recipetineats.com")["source_rating"]["count"] == 2124
    only_reviews = reader.source_rating({"ratingValue": "4", "reviewCount": "12"})
    assert only_reviews["count"] == 12        # reviewCount is the fallback, not a competitor


# --------------------------------------------------------------------------- #
# rich_text: the writer's line breaks survive the read
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,want", [
    ("Line one.<br>Line two.", "Line one.\nLine two."),
    ("Line one.<br/>Line two.", "Line one.\nLine two."),
    ("<p>Para one.</p><p>Para two.</p>", "Para one.\n\nPara two."),
    ("Step A.\n\nAIR FRYER OPTION:\nShake off excess.",
     "Step A.\n\nAIR FRYER OPTION:\nShake off excess."),
])
def test_rich_text_keeps_the_break_that_text_collapses(raw, want):
    """⚠️ TWO LOSSES, AND THE TAG STRIP IS THE ONE THAT MATTERS MORE. It runs BEFORE the whitespace
    collapse and turns <br> into a space, so fixing only the collapse recovers nothing from a
    publisher who marks breaks in HTML. These cases fail if either half is left behind."""
    assert reader.rich_text(raw) == want
    assert "\n" not in reader.text(raw)          # the single-line reader is unchanged


@pytest.mark.parametrize("raw", ["One line only.", "a    b\tc", "<b>bold</b> and plain"])
def test_rich_text_matches_text_when_there_is_no_structure(raw):
    """A value with nothing to keep comes back exactly as before, which is what makes this safe to
    point at description without auditing every publisher."""
    assert reader.rich_text(raw) == reader.text(raw)


def test_runs_of_blank_lines_are_capped_at_one():
    assert reader.rich_text("<p>A</p>\n\n\n\n<p>B</p>") == "A\n\nB"


def test_horizontal_whitespace_still_collapses_inside_a_line():
    assert reader.rich_text("A    b\tc\nD     e") == "A b c\nD e"


def test_rich_text_handles_none_and_empty():
    assert reader.rich_text(None) == "" and reader.rich_text("") == ""


def test_a_section_name_stays_on_one_line():
    """The HowToSection NAME keeps text(), not rich_text. It is a heading, and the appended colon
    assumes one line."""
    instructions = [{"@type": "HowToSection", "name": "Make the sauce<br>quickly",
                     "itemListElement": [{"@type": "HowToStep", "text": "A.<br>B."}]}]
    lines = reader.directions(instructions)
    assert lines[0] == "Make the sauce quickly:"
    assert lines[1] == "A.\nB."
