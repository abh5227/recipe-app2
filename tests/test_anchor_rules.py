"""Rule 5, the pasta-parent anchor, and the bagel override.

⚠️ THESE READ vocab/ AND NOTHING ELSE. join.db is 894 MB and sources.db is 5.18 GB, both
git-ignored, so a test that builds the library cannot run in CI. The rule's whole content
is a P279 lookup, and vocab/wikidata-superclasses.json IS committed, so the predicate is
testable at full fidelity without either database.
"""
import build_library
import ingredient_cuts as CUTS

SUPERCLASSES = build_library.load_vocab()[1]

# ⚠️ Q-ids, not names, because a Wikidata label can change and the anchor cannot.
RIGATONI, DITALINI, PENNE = "Q20024", "Q3711859", "Q1063736"
MACARONI, LINGUINE = "Q20019", "Q20035"
# hop 2: their P279 parent is 'gnocchi' or 'stuffed pasta', which is itself a child of
# Q178. Both are plated dishes and both must stay out.
GNOCCHI_ALLA_SORRENTINA, CRAB_RANGOON = "Q3772617", "Q3298630"
# ⚠️ Wikidata splits spaghetti in two and gives BOTH the kind 'Dish or prepared food'.
SPAGHETTI_THE_DISH, SPAGHETTI_THE_SHAPE = "Q128257664", "Q20026"


def admitted(*, already=frozenset()):
    """The rule over every item the vocabulary knows about."""
    return build_library.pasta_rule(set(SUPERCLASSES), SUPERCLASSES, already)


def test_pasta_rule_admits_the_shapes_the_kind_field_refuses():
    """The five corpus gap lines are two Rigatoni, one Mezze Rigatoni and two Ditalini."""
    got = admitted()
    for q in (RIGATONI, DITALINI, PENNE, MACARONI, LINGUINE):
        assert q in got, f"{q} names Q178 as a direct superclass and must be admitted"


def test_the_admitted_shapes_are_exactly_the_ones_rule_one_cannot_reach():
    """⚠️ THE REASON THE RULE IS NEEDED, asserted rather than described. Every shape above
    carries a kind, and the kind is 'Dish or prepared food', so rule 1 refuses all five."""
    kinds = build_library.load_vocab()[0]
    for q in (RIGATONI, DITALINI, PENNE, MACARONI, LINGUINE):
        item = kinds.get(q, {}).get("kinds", {})
        assert build_library.INGREDIENT not in item
        assert build_library.DISH_KINDS & set(item), f"{q} lost its dish kind, recheck rule 5"


def test_pasta_rule_stops_at_one_hop():
    """⚠️ THE BOUNDARY. Both of these reach Q178 in exactly two hops, through 'gnocchi'
    and through 'stuffed pasta'. Two hops was measured and refused: it admits 231 items
    instead of 146 and its one extra corpus resolution is wrong."""
    got = admitted()
    for q in (GNOCCHI_ALLA_SORRENTINA, CRAB_RANGOON):
        assert "Q178" not in SUPERCLASSES.get(q, ()), f"{q} is no longer a two-hop case"
        assert any("Q178" in SUPERCLASSES.get(p, ())
                   for p in SUPERCLASSES.get(q, ())), f"{q} no longer reaches Q178 at hop 2"
        assert q not in got, f"{q} is a plated dish two hops out and must stay out"


def test_pasta_rule_leaves_both_spaghetti_items_alone():
    """⚠️ HONEST ABOUT WHAT IT MISSES. Neither spaghetti item is a direct child of Q178,
    so the shape is missed as well as the dish. That is the price of one hop and it costs
    no corpus line, because 'spaghetti' already has a row through Open Food Facts."""
    got = admitted()
    assert SPAGHETTI_THE_DISH not in got
    assert SPAGHETTI_THE_SHAPE not in got


def test_pasta_rule_yields_to_the_earlier_rules():
    """An item another rule already anchored must not be admitted twice."""
    assert RIGATONI not in admitted(already={RIGATONI})


def test_bagel_is_an_override_because_no_rule_can_reach_it():
    """⚠️ Its P279 parent is 'yeast bread', which is under Q7802 and not under Q178, so
    rule 5 cannot see it at any hop. Admitting the bread class was measured at 674 rows
    for this one line."""
    assert "bagel" in CUTS.OVERRIDES
    failure, ident, reason = CUTS.OVERRIDES["bagel"]
    assert ident == "Q272502"
    assert "Q178" not in SUPERCLASSES.get(ident, ()), "bagel is reachable now, drop the override"
    assert failure == "C", "bagel is class C: Wikidata classified it, and classified it wrong"


def test_every_override_states_a_failure_class_and_a_reason():
    """'No reason, no override' is the list's own rule, so it is worth a guard."""
    for term, (failure, ident, reason) in CUTS.OVERRIDES.items():
        assert failure in {"A", "B", "C"}, f"{term} has an unknown failure class {failure!r}"
        assert ident and reason.strip(), f"{term} is missing an identifier or a reason"
