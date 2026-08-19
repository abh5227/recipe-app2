"""U2: the reader cascade, provenance, and refusal composition.

Everything runs against U0's committed fixtures — no network, no DB. There is one real layer today
(json-ld); the ordering and short-circuit behaviour is proved with STUB layers defined here rather
than by shipping a placeholder in url_cascade.LAYERS, so production carries no dummy while the
guarantees U3 and U6 depend on are still pinned.
"""
import json
import pathlib
import socket

import pytest

import url_cascade as cascade

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"
MANIFEST = {r["domain"]: r for r in json.loads((FIXTURES / "manifest.json").read_text())}

JSON_LD = sorted(d for d, r in MANIFEST.items() if r["case"] == "json-ld")

# The exact message each non-JSON-LD fixture must produce. Pinned as literals: this text is what the
# user reads when an import fails, and it is the whole reason the refusal taxonomy was kept rich.
EXPECTED = {
    "lahbco.com": "json-ld: found Article and ImageObject, not Recipe",
    "notanothercooking.tv": "json-ld: found BlogPosting and ImageObject, not Recipe",
    "probablyworthsharing.com": "json-ld: found Article and ImageObject, not Recipe",
    "nigella.com": "json-ld: no JSON-LD on the page",
    "youtube.com": "json-ld: no JSON-LD on the page",
}


def run(domain):
    row = MANIFEST[domain]
    return cascade.read(row["url"], (FIXTURES / row["file"]).read_text(errors="replace"))


def page(body):
    return f'<script type="application/ld+json">{body}</script>'


# ----------------------------------------------------------------- success
@pytest.mark.parametrize("domain", JSON_LD)
def test_jsonld_fixtures_read_and_carry_their_provenance(domain):
    got = run(domain)
    assert isinstance(got, cascade.Read), got
    assert got.provenance == {"layer": "json-ld"}
    assert got.normalized["name"] and got.normalized["ingredient_lines"] and got.normalized["directions"]


def test_the_normalized_dict_is_passed_through_untouched():
    """Provenance rides ALONGSIDE the seam. The cascade must not add an 18th key — the dict is the
    reader->cleanup contract, and clean_recipe has no use for how it was obtained."""
    from test_url_jsonld import KEYS               # the same 17 the reader emits
    assert set(run("bbcgoodfood.com").normalized) == KEYS


# ----------------------------------------------------------------- refusal composition
@pytest.mark.parametrize("domain", sorted(EXPECTED))
def test_pages_with_no_jsonld_recipe_produce_the_expected_message(domain):
    got = run(domain)
    assert isinstance(got, cascade.Failed)
    assert got.message == EXPECTED[domain]


def test_a_page_carrying_other_jsonld_is_not_called_structureless():
    """lahbco has TWO ld+json blocks. Reporting 'no structured data' would be false, and useless —
    'found Article and ImageObject' tells the user this is a blog post, not a recipe page."""
    got = run("lahbco.com")
    assert "no JSON-LD" not in got.message
    assert got.refusals[0].code == "NOT_A_RECIPE"


def test_a_page_with_no_jsonld_at_all_says_so():
    got = run("youtube.com")
    assert got.refusals[0].code == "NO_STRUCTURED_DATA"


def test_every_refusal_is_carried_not_just_the_message():
    got = run("nigella.com")
    assert len(got.refusals) == len(cascade.LAYERS)
    assert got.refusals[0].layer == "json-ld"


def test_and_list_caps_the_types_it_names():
    assert cascade.and_list(["Article", "ImageObject", "Organization", "WebSite"]) == "Article and ImageObject"
    assert cascade.and_list(["Article"]) == "Article"
    assert cascade.and_list([]) == ""
    assert cascade.and_list(["a", "b", "c"], limit=3) == "a, b and c"


# ----------------------------------------------------------------- the usable bar
def test_a_recipe_with_no_steps_is_refused_not_accepted():
    """USABLE = name + >=1 ingredient + >=1 step. A page yielding an ingredient list and nothing to
    do with it is not a recipe, and accepting it is how junk gets imported that looks plausible."""
    got = cascade.read("https://example.test/x", page(
        '{"@type":"Recipe","name":"Half","recipeIngredient":["1 egg"]}'))
    assert isinstance(got, cascade.Failed)
    assert got.refusals[0].code == "INCOMPLETE"
    assert got.message == "json-ld: a Recipe with no steps"


def test_a_recipe_with_no_ingredients_is_refused():
    got = cascade.read("https://example.test/x", page(
        '{"@type":"Recipe","name":"Half","recipeInstructions":[{"@type":"HowToStep","text":"Cook."}]}'))
    assert got.refusals[0].code == "INCOMPLETE"
    assert got.message == "json-ld: a Recipe with no ingredients"


def test_the_minimum_usable_recipe_is_accepted():
    got = cascade.read("https://example.test/x", page(
        '{"@type":"Recipe","name":"Toast","recipeIngredient":["1 slice bread"],'
        '"recipeInstructions":[{"@type":"HowToStep","text":"Toast it."}]}'))
    assert isinstance(got, cascade.Read)
    assert got.normalized["servings_raw"] == "" and got.normalized["source"] == ""   # the rest optional


# ----------------------------------------------------------------- ordering and short-circuit
def _reads(name):
    def layer(url, html):
        return cascade.Read({"name": name}, {"layer": name})
    return layer


def _refuses(name, detail="nothing here"):
    calls = []

    def layer(url, html):
        calls.append(url)
        return cascade.Refusal(name, "NO_STRUCTURED_DATA", detail)
    layer.calls = calls
    return layer


def test_the_first_layer_to_succeed_wins_and_later_layers_never_run():
    """A later, weaker layer must never overwrite a better one's answer — that is what makes this a
    cascade rather than a merge."""
    second = _refuses("never-called")
    got = cascade.read("u", "h", layers=(_reads("first"), second))
    assert got.provenance == {"layer": "first"}
    assert second.calls == [], "a layer ran after one had already succeeded"


def test_a_refusing_layer_falls_through_to_the_next():
    """The guarantee U3 and U6 slot into: refuse, and the next reader gets a clean shot at the page."""
    first = _refuses("first")
    got = cascade.read("u", "h", layers=(first, _reads("second")))
    assert isinstance(got, cascade.Read) and got.provenance == {"layer": "second"}
    assert first.calls == ["u"]


def test_every_layer_refusing_composes_them_in_order():
    got = cascade.read("u", "h", layers=(_refuses("json-ld", "no JSON-LD on the page"),
                                         _refuses("microdata", "no schema.org/Recipe scope"),
                                         _refuses("heuristics", "no list looked like ingredients")))
    assert [r.layer for r in got.refusals] == ["json-ld", "microdata", "heuristics"]
    assert got.message == ("json-ld: no JSON-LD on the page\n"
                           "microdata: no schema.org/Recipe scope\n"
                           "heuristics: no list looked like ingredients")


def test_no_layers_at_all_is_not_a_crash():
    got = cascade.read("u", "h", layers=())
    assert isinstance(got, cascade.Failed) and got.refusals == ()
    assert got.message == "no reader was tried"


def test_the_shipped_layer_order():
    assert [l.__name__ for l in cascade.LAYERS] == ["jsonld_layer"]      # U3/U6 append here


# ----------------------------------------------------------------- provenance persistence
def test_provenance_becomes_a_recipe_level_import_flags_row():
    """position=None is the existing recipe-level convention; the row shape is exactly what
    commit_plan already inserts, so U5 can append it to plan['review_flags'] with no schema change."""
    row = cascade.provenance_flag_row(run("recipetineats.com").provenance)
    assert row == {"position": None, "flag": "imported_via", "reason": "json-ld"}


def test_the_provenance_row_matches_what_commit_plan_inserts():
    """Pinned against the real writer: the keys must be columns on import_flags, or the Core insert
    raises CompileError at write time rather than here."""
    from models import ImportFlag
    row = cascade.provenance_flag_row({"layer": "json-ld"})
    columns = {c.name for c in ImportFlag.__table__.columns}
    assert set(row) <= columns
    assert "recipe_id" not in row          # commit_plan supplies it
    assert "created_at" not in row         # the column has a server default


def test_the_row_shape_matches_the_other_recipe_level_flags():
    """import_write builds recipe-level flags as {position, flag, reason}; this is the same shape,
    and the ONLY difference is that it uses `reason` to carry the layer."""
    import import_write as iw
    import import_cleanup as cleanup
    plan = iw.plan_recipe(cleanup.clean_recipe(dict(
        name="X", uid="u", hash="h", ingredient_lines=["1 egg"], directions=[],
        servings_raw="", categories=[], source="", source_url="", notes="",
        description="", rating=0, prep_time="", cook_time="", total_time="",
        images=[], primary_photo=None)), {}, set())
    existing = [f for f in plan["review_flags"] if f["position"] is None]
    assert existing, "expected a recipe-level flag (no_directions) to compare against"
    assert set(existing[0]) == set(cascade.provenance_flag_row({"layer": "json-ld"}))


# ----------------------------------------------------------------- purity
def test_the_cascade_touches_no_network():
    real = socket.socket
    socket.socket = lambda *a, **k: pytest.fail("the cascade opened a socket")
    try:
        assert isinstance(run("allrecipes.com"), cascade.Read)
    finally:
        socket.socket = real
