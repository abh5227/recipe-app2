"""Phase 1c — volume->weight reference table, the shared name-matcher (incl. curated
aliases), and the build-time conversion-coverage report."""
import pytest

import weights
import build_db


def test_ingredient_weights_seeded(kitchen):
    assert kitchen.count("ingredient_weights") > 0


def test_grams_per_ml_values(kitchen):
    # density = grams / reference-volume-in-mL, computed at seed time
    with kitchen.conn() as c:
        apf = c.execute(
            "SELECT grams_per_ml FROM ingredient_weights WHERE lookup_key = 'all purpose flour'"
        ).fetchone()[0]
        honey = c.execute(
            "SELECT grams_per_ml FROM ingredient_weights WHERE lookup_key = 'honey'"
        ).fetchone()[0]
    assert apf == pytest.approx(120 / 236.588)     # "1 cup"
    assert honey == pytest.approx(21 / 14.7868)    # "1 tablespoon" (non-cup reference)


def test_matcher_exact_fuzzy_alias_decline():
    rows = [
        {"lookup_key": "bread flour", "display_name": "Bread Flour", "grams_per_ml": 0.5},
        {"lookup_key": "all purpose flour", "display_name": "All-Purpose Flour", "grams_per_ml": 0.51},
        {"lookup_key": "sugar granulated white", "display_name": "Sugar (granulated white)", "grams_per_ml": 0.84},
        {"lookup_key": "olive oil", "display_name": "Olive oil", "grams_per_ml": 0.85},
        {"lookup_key": "salt table", "display_name": "Salt (table)", "grams_per_ml": 1.22},
        {"lookup_key": "salt kosher diamond crystal", "display_name": "Salt (Kosher Diamond Crystal)", "grams_per_ml": 0.54},
        {"lookup_key": "salt kosher mortons", "display_name": "Salt (Kosher Morton's)", "grams_per_ml": 1.08},
    ]
    idx = weights.build_index(rows)

    # exact normalized match
    assert weights.match_weight("bread flour", idx)[0] == 0.5
    # fuzzy: case + hyphen folding
    assert weights.match_weight("All-Purpose Flour", idx)[0] == 0.51
    # fuzzy: base-name fallback ("sugar" -> "Sugar (granulated white)")
    assert weights.match_weight("sugar", idx)[0] == 0.84

    # alias resolves (curated same-ingredient synonyms)
    assert weights.match_weight("extra-virgin olive oil", idx)[0] == 0.85
    assert weights.match_weight("EVOO", idx)[0] == 0.85
    assert weights.match_weight("plain flour", idx)[0] == 0.51

    # kosher-salt default resolves to Diamond Crystal SPECIFICALLY, pinned so it can't
    # silently drift to Morton's later (Morton's is ~2x heavier by volume).
    assert weights.match_weight("kosher salt", idx)[0] == 0.54   # Diamond Crystal
    assert weights.match_weight("kosher salt", idx)[0] != 1.08   # NOT Morton's

    # guardrail — the alias map is NOT qualifier-stripping:
    # near-but-different names still DECLINE rather than snap to a wrong density.
    assert weights.match_weight("caster sugar", idx) is None    # ~190 g/cup, not granulated 198
    assert weights.match_weight("salt", idx) is None            # bare salt: still ambiguous
    assert weights.match_weight("sea salt", idx) is None        # still ambiguous, no "what I use"
    assert weights.match_weight("dragonfruit", idx) is None     # absent from the chart


def test_convert_to_grams_flows_through_matcher():
    # convert_to_grams (013) rides along as element [2]; absent column defaults to True.
    rows = [
        {"lookup_key": "all purpose flour", "display_name": "All-Purpose Flour",
         "grams_per_ml": 0.51, "convert_to_grams": 1},
        {"lookup_key": "olive oil", "display_name": "Olive oil",
         "grams_per_ml": 0.85, "convert_to_grams": 0},
        {"lookup_key": "bread flour", "display_name": "Bread Flour", "grams_per_ml": 0.5},
    ]
    idx = weights.build_index(rows)
    assert weights.match_weight("all-purpose flour", idx)[2] is True   # staple -> converts
    assert weights.match_weight("olive oil", idx)[2] is False          # oil -> declines
    assert weights.match_weight("bread flour", idx)[2] is True         # column absent -> default


def test_seeded_convert_flags(kitchen):
    # the real CSV-driven flags: staples / soft dairy / pastes / liquids TRUE; oils + raw
    # produce FALSE. Butter is the deliberate fats exception (baking weighs butter).
    with kitchen.conn() as c:
        def flag(key):
            return c.execute(
                "SELECT convert_to_grams FROM ingredient_weights WHERE lookup_key = ?", (key,)
            ).fetchone()[0]
        assert flag("all purpose flour") == 1
        assert flag("butter") == 1
        assert flag("milk fresh") == 1
        assert flag("honey") == 1
        assert flag("tomato paste") == 1            # a paste, not raw produce -> converts
        assert flag("olive oil") == 0
        assert flag("vegetable oil") == 0
        assert flag("garlic minced") == 0
        assert flag("onions diced") == 0


def test_has_volume_unit_recognizes_spelled_out_millilitres():
    assert weights.has_volume_unit("240 millilitres") is True   # the 013 fix
    assert weights.has_volume_unit("240 milliliters") is True   # US spelling
    assert weights.has_volume_unit("2 cups") is True            # originals still work
    assert weights.has_volume_unit("1 tablespoon") is True
    assert weights.has_volume_unit("200 grams") is False        # weight, not a volume


def test_coverage_report_runs(kitchen):
    with kitchen.conn() as c:
        n_distinct, n_matched, unmatched, per_recipe = build_db.compute_coverage(c)
    assert n_distinct > 0
    assert 0 <= n_matched <= n_distinct
    assert len(unmatched) == n_distinct - n_matched
    counts = [cnt for _, cnt in unmatched]
    assert counts == sorted(counts, reverse=True)          # most-used first
    keys = [k for k, _ in unmatched]
    assert "water" not in keys                             # water matches the chart
    assert "garlic" in keys                                # ambiguous in chart -> declines
    assert per_recipe                                      # at least one recipe reported


def test_api_attaches_grams_per_ml(kitchen):
    d = kitchen.client.get("/api/recipes/gai-yang").get_json()
    by_name = {
        (l.get("label") or l.get("raw_text")): l
        for l in d["ingredients"] if not l.get("is_heading")
    }
    assert by_name["water"]["grams_per_ml"] == pytest.approx(227 / 236.588)
    assert by_name["fish sauce"]["grams_per_ml"] is None   # not in the chart -> declined
    # headings carry no grams_per_ml key at all
    assert all("grams_per_ml" not in l for l in d["ingredients"] if l.get("is_heading"))


def test_descriptor_aliases_resolve(kitchen):
    """Group A+B: every descriptor/word-order/brand variant seen in the imported recipes resolves
    to its chart row (so it converts in Metric), against the real seeded chart."""
    with kitchen.conn() as c:
        idx = weights.build_index(c.execute(
            "SELECT lookup_key, display_name, grams_per_ml, convert_to_grams FROM ingredient_weights"
        ).fetchall())
    cases = {
        "granulated sugar": "Sugar (granulated white)", "white granulated sugar": "Sugar (granulated white)",
        "king arthur unbleached all purpose flour": "All-Purpose Flour", "whole milk": "Milk (fresh)",
        "heavy cream": "Cream (heavy/light/half & half)", "double cream": "Cream (heavy/light/half & half)",
        "half and half": "Cream (heavy/light/half & half)", "unsalted butter": "Butter", "salted butter": "Butter",
        "plain yogurt": "Yogurt", "semisweet chocolate chips": "Chocolate chips",
        "dark chocolate chips": "Chocolate chips", "unsweetened cocoa": "Cocoa (unsweetened)",
        "cocoa powder": "Cocoa (unsweetened)", "light brown sugar": "Brown sugar (packed)",
        "dark brown sugar": "Brown sugar (packed)", "packed dark brown sugar": "Brown sugar (packed)",
        "ice water": "Water", "ice cold water": "Water", "warm water": "Water",
        "fresh lemon juice": "Lemon juice", "vanilla": "Vanilla extract",
        "king arthur pure vanilla extract": "Vanilla extract",
        "rolled oats": "Oats (rolled)", "tahini": "Tahini paste",
        "panko crumbs": "Breadcrumbs (Japanese panko)", "table salt": "Salt (table)",
        "diamond crystal kosher salt": "Salt (Kosher Diamond Crystal)",
    }
    for name, expected in cases.items():
        m = weights.match_weight(name, idx)
        assert m is not None, f"{name!r} should resolve, got None"
        assert m[1] == expected, f"{name!r} -> {m[1]!r}, expected {expected!r}"
        assert m[2] == 1, f"{name!r} target should be convert_to_grams=TRUE"


def test_alias_group_c_traps_decline(kitchen):
    """Decline-over-guess guard: look-alikes that are DIFFERENT ingredients/densities must NOT
    resolve, so a future alias/normalization change can't silently start mis-mapping them."""
    with kitchen.conn() as c:
        idx = weights.build_index(c.execute(
            "SELECT lookup_key, display_name, grams_per_ml, convert_to_grams FROM ingredient_weights"
        ).fetchall())
    for name in ("condensed milk", "golden caster sugar", "caster sugar", "glutinous rice flour",
                 "greek yogurt", "vanilla bean paste", "sea salt", "salt"):
        assert weights.match_weight(name, idx) is None, f"{name!r} must DECLINE, not alias"
    # a 'milk' alias must not hijack ingredients that own a distinct chart row
    assert weights.match_weight("coconut milk", idx)[1] == "Coconut milk (canned)"
    assert weights.match_weight("evaporated milk", idx)[1] == "Evaporated milk"
