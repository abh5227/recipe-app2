"""Phase 1d — method-text step scaler (stepscale.parse_step).

Heaviest emphasis on the NEVER-SCALE guard: a missed quantity is a harmless inconvenience,
but a wrongly-scaled temperature / time / dimension is a silent hazard — so those are tested
hardest. The scaling MATH is the Phase 1a JS scaler (no JS harness), so these target the
deterministic server-side parser; the live formatting parity is in the manual checklist."""
import pytest

import stepscale as ss
import build_db


def _scalable(text):
    """Texts of spans the renderer would actually scale (explicit markup or heuristic)."""
    return [s["text"] for s in ss.parse_step(text)
            if s["category"] in (ss.MARKED_SCALE, ss.HEURISTIC_SCALE)]


def _categories(text):
    return [s["category"] for s in ss.parse_step(text)]


# ----------------------------------------------------------------- never-scale guard
NEVER_SCALE = [
    "bake at 350°F",
    "knead for 10 minutes",
    "rest 1 hour",
    "9x13 pan",
    "9×13 pan",                     # unicode × variant
    "12-inch skillet",
    "roll to 1/4-inch thick",       # 1/4 looks like a scalable fraction; "inch" must guard it
    "cook to 160°F internal",
    "bake 20 to 25 minutes",        # range beside a time unit — BOTH numbers guarded
    "preheat to 375°F / 190°C",
    "about ¾ inch / 2 cm apart",
    "simmer 4–6 minutes",
]


@pytest.mark.parametrize("text", NEVER_SCALE)
def test_never_scale(text):
    assert _scalable(text) == [], f"a fixed number was tagged scalable in: {text!r}"


def test_guard_claims_not_just_skips():
    # the guard CLAIMS the number (GUARDED), it isn't the heuristic choosing to skip
    assert ss.GUARDED in _categories("bake at 350°F")
    assert ss.GUARDED in _categories("9x13 pan")
    # a range beside a time unit is one guarded span covering both numbers
    guarded = [s["text"] for s in ss.parse_step("bake 20 to 25 minutes") if s["category"] == ss.GUARDED]
    assert guarded == ["20 to 25 minutes"]


def test_quarter_inch_guarded_at_every_factor():
    # the exact span text never changes regardless of factor (client scales nothing here)
    spans = ss.parse_step("roll to 1/4-inch thick")
    assert all(s["category"] != ss.HEURISTIC_SCALE for s in spans)
    assert "1/4" in "".join(s["text"] for s in spans)   # preserved verbatim


# ----------------------------------------------------------------- markup overrides
def test_marked_lock_never_scales():
    assert _categories("{{!350°F}}") == [ss.MARKED_LOCK]
    assert _scalable("{{!350°F}}") == []


def test_marked_scale_scales():
    assert _scalable("stir in {{2 tbsp}} oil") == ["2 tbsp"]


def test_markup_beats_guard():
    # an explicit {{...}} forces scaling even on text the guard would otherwise claim
    assert ss.parse_step("{{350°F}}")[0]["category"] == ss.MARKED_SCALE


def test_markup_markers_stripped_from_display():
    joined = "".join(s["text"] for s in ss.api_spans("set oven to {{!350°F}}, add {{2 tbsp}} oil"))
    assert "{{" not in joined and "}}" not in joined and "!" not in joined
    assert joined == "set oven to 350°F, add 2 tbsp oil"


# ----------------------------------------------------------------- heuristic + unitless
def test_heuristic_scales_number_plus_unit():
    scale = [s for s in ss.parse_step("stir in 2 cups water") if s["category"] == ss.HEURISTIC_SCALE]
    assert len(scale) == 1
    assert scale[0]["text"] == "2 cups"
    assert scale[0]["value"] == 2.0 and scale[0]["unit"] == "cups"   # client renders 2 * factor


def test_divide_into_4_is_unitless_not_scaled():
    spans = ss.parse_step("divide into 4 pieces")
    assert _scalable("divide into 4 pieces") == []
    assert any(s["category"] == ss.UNITLESS and s["text"] == "4" for s in spans)


def test_mixed_sentence_only_the_quantity_scales():
    text = "add 2 cups flour and bake 1 hour at 350°F"
    assert _scalable(text) == ["2 cups"]
    guarded = [s["text"] for s in ss.parse_step(text) if s["category"] == ss.GUARDED]
    assert guarded == ["1 hour", "350°F"]


# ----------------------------------------------------------------- fl oz tokenization
def test_fl_oz_is_one_unit():
    scale = [s for s in ss.parse_step("2 fl oz vodka") if s["category"] == ss.HEURISTIC_SCALE]
    assert scale[0]["text"] == "2 fl oz" and scale[0]["unit"].lower() == "fl oz"
    # a bare-oz weight still scales and isn't confused with the oz inside fl oz
    assert _scalable("3 oz cheese") == ["3 oz"]


# ----------------------------------------------------------------- value parsing
def test_value_parsing_fraction_and_unicode():
    assert ss.parse_step("add {{1 1/2 cups}} water")[1]["value"] == 1.5
    half = [s for s in ss.parse_step("1½ tsp salt") if s["category"] == ss.HEURISTIC_SCALE][0]
    assert half["value"] == 1.5 and half["unit"] == "tsp"


# ----------------------------------------------------------------- coverage report
def test_parser_category_counts_small_fixture():
    cats = _categories("add 2 cups flour, knead 10 minutes, divide into 4, bake at 350°F")
    assert cats.count(ss.HEURISTIC_SCALE) == 1     # 2 cups
    assert cats.count(ss.GUARDED) == 2             # 10 minutes, 350°F
    assert cats.count(ss.UNITLESS) == 1            # 4


def test_build_report_runs_on_seed(kitchen):
    with kitchen.conn() as c:
        cov = build_db.compute_step_coverage(c)
    assert cov                                                  # at least one recipe
    assert all(r["marked_scale"] == 0 and r["marked_lock"] == 0 for r in cov.values())
    gy = cov["Thai BBQ Chicken (Gai Yang)"]                     # all temps/times -> guarded
    assert gy["heuristic"] == 0 and gy["guarded"] > 0
