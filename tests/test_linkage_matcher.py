"""linkage_matcher.match - the blocked-decision branch, and the fall-through it was missing.

THE DEFECT. strip_forms searches for the fewest-words-removed name the caller accepts, and the
matcher's predicate accepts a catalog name OR a decided one. A decided name has no catalog row
behind it, so when the search stopped at one and the decision was then blocked (a FORM word had
been dropped, and a form word changes which food it is), the branch returned UNMATCHED. Every
deeper strip that would have reached a real row went untried, because the search had already been
told it was finished.

Carried open in docs/open-library-queues.md since before the Wikibooks pass.
"""
import linkage_matcher as lm


def cat_of(*pairs):
    """{normalized name: [(library_id, canonical)]}, the shape load_catalog returns."""
    out = {}
    for name, lid, canon in pairs:
        out.setdefault(name, []).append((lid, canon))
    return out


def test_a_blocked_decision_falls_through_to_the_catalog():
    """'dried red foo': one strip reaches a DECIDED name, and 'dried' blocks the decision. The row
    the second strip reaches is a real one and must be returned."""
    cat = cat_of(("foo", "L1", "Foo"))
    decided = {"red foo": ("L9", "Red Foo", "settled by the corpus")}
    tier, matched, rows, rule = lm.match("dried red foo", cat, decided)
    assert tier == "FORM_STRIP"
    assert (matched, rows) == ("foo", [("L1", "Foo")])
    assert rule == "form_strip:dried red"


def test_the_fall_through_still_refuses_an_ambiguous_target():
    """Falling through must not weaken the two-rows-one-name refusal. A name the catalog holds
    twice goes dark, exactly as it does on the ordinary path."""
    cat = cat_of(("foo", "L1", "Foo"), ("foo", "L2", "Other Foo"))
    decided = {"red foo": ("L9", "Red Foo", "settled by the corpus")}
    assert lm.match("dried red foo", cat, decided)[0] == "AMBIGUOUS"


def test_a_blocked_decision_with_nothing_behind_it_is_still_a_miss():
    """⚠️ THE LIVE CASE, and the fall-through does NOT rescue it. 'fresh coriander' strips to
    'coriander', 'fresh' is a form word so the cilantro judgement is blocked, and the catalog holds
    no bare 'coriander' row at all. A miss is the correct answer and the rule string says why."""
    cat = cat_of(("cilantro", "L1", "cilantro"), ("coriander seed", "L2", "coriander seed"))
    decided = {"coriander": ("L1", "cilantro", "settled by the corpus")}
    tier, matched, rows, rule = lm.match("fresh coriander", cat, decided)
    assert (tier, rows) == ("UNMATCHED", [])
    assert rule == "decision blocked: a form word was dropped"


def test_a_decision_still_fires_after_a_prep_strip_only():
    """The branch above it is untouched. 'chopped coriander' drops a PREP word, so the judgement
    applies and the line reaches cilantro rather than falling through."""
    cat = cat_of(("cilantro", "L1", "cilantro"))
    decided = {"coriander": ("L1", "cilantro", "settled by the corpus")}
    tier, matched, _rows, rule = lm.match("chopped coriander", cat, decided)
    assert (tier, matched) == ("DECIDED", "cilantro")
    assert rule.startswith("settled by the corpus after prep strip:")


def test_ground_coriander_is_never_sent_to_cilantro_by_the_fall_through():
    """⚠️ THE REGRESSION THE GUARD EXISTS FOR. Ground coriander is the SEED. The fall-through
    searches the catalog, so it can only ever reach a row the catalog really holds, and the
    cilantro row is not reachable from a stripped 'coriander' that no catalog key spells."""
    cat = cat_of(("cilantro", "L1", "cilantro"))
    decided = {"coriander": ("L1", "cilantro", "settled by the corpus")}
    tier, _m, rows, _r = lm.match("ground coriander", cat, decided)
    assert tier == "UNMATCHED" and rows == []
