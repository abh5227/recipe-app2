"""build_library.apply_folds — moving a duplicate row's names onto the row that answers for it.

Like test_library_names_generator, this cannot run the real pipeline: a rowset needs join.db
(894 MB) and sources.db (5.18 GB), neither committed nor present in CI. So it tests the half with
no such dependency, rows in and rows out, with the two collaborators apply_folds actually depends
on stubbed to the shapes the real ones return.

⚠️ THE CRITICAL TEST IS test_dying_row_stays_cut_through_both_annotates. cut_by is assigned in
exactly one place, annotate, as apply_cuts(...), and build() calls annotate TWICE after the fold.
A fold that marked the dying row by writing cut_by would pass a naive check and be silently erased
before the row ever reached write_library_names. That is the failure this file exists to catch.
"""
import build_library
from build_library import apply_cuts, apply_folds, norm_name


def _row(ident, canonical, variations=None, anchor="wikidata", **kw):
    """A row carrying the fields apply_folds reads. A real row carries ~36 more."""
    row = {
        "id": ident, "canonical": canonical, "anchor": anchor,
        "variations": {canonical: {(anchor, "label", "en")}},
        "hand_reasons": [], "trimmed": [], "sources": [anchor], "n_variations": 0,
    }
    for name, tags in (variations or {}).items():
        row["variations"][name] = set(tags)
    row["n_variations"] = len(row["variations"]) - 1
    row.update(kw)
    return row


def _fold(ident, into, into_canonical="", reason="it is a name, not a row", anchor="wikidata"):
    return {(anchor, ident): [{"anchor": anchor, "id": ident, "action": "fold", "variation": "",
                               "reason": reason, "marked": "2026-08-31",
                               "into": into, "into_canonical": into_canonical}]}


def _annotate_cut(rows):
    """What annotate does to cut_by, isolated: recompute it from the row, every time."""
    for row in rows:
        row["cut_by"] = apply_cuts(row, {}, {})
    return rows


def test_names_move_onto_the_survivor():
    dying = _row("Q1", "Allium sativum", {"Aglio": {("wikidata", "alias", "it")},
                                          "garlic": {("wikidata", "alias", "en")}})
    survivor = _row("Q2", "garlic")
    done, refused, dangling = apply_folds([dying, survivor], _fold("Q1", "Q2"), {}, {})
    assert (refused, dangling) == ([], [])
    assert len(done) == 1
    assert "Aglio" in survivor["variations"], "a name only the dying row had must arrive"
    assert "Allium sativum" in survivor["variations"], "the dying canonical is itself an alias now"
    assert survivor["canonical"] == "garlic", "the survivor keeps its own canonical"


def test_dedupe_is_by_norm_name_and_unions_the_tags():
    dying = _row("Q1", "Allium sativum", {"Garlic": {("agrovoc", "alt", "en")}})
    survivor = _row("Q2", "garlic")
    apply_folds([dying, survivor], _fold("Q1", "Q2"), {}, {})
    keys = [k for k in survivor["variations"] if norm_name(k) == norm_name("garlic")]
    assert len(keys) == 1, "'Garlic' must not land beside 'garlic' as a second key"
    assert ("agrovoc", "alt", "en") in survivor["variations"][keys[0]], "tags union, never overwrite"
    assert ("wikidata", "label", "en") in survivor["variations"][keys[0]], "the survivor keeps its own tag"


def test_dying_row_stays_cut_through_both_annotates():
    """⚠️ THE REGRESSION THIS FILE EXISTS FOR. build() re-derives cut_by twice after the fold."""
    dying = _row("Q1", "Allium sativum")
    survivor = _row("Q2", "garlic")
    apply_folds([dying, survivor], _fold("Q1", "Q2"), {}, {})
    for pass_number in (1, 2):
        _annotate_cut([dying, survivor])
        assert dying["cut_by"], f"the folded row must still be cut after annotate #{pass_number}"
        assert "folded" in dying["cut_by"]
        assert not survivor["cut_by"], "the survivor must never be cut by the fold"
    assert dying["cut_by"] == apply_cuts(dying, {}, {}), "the mark is re-derived, not stored"


def test_the_cut_mark_has_sheet_text():
    """write_sheet does CUT_RULE_TEXT[c] for every mark, so an unregistered one is a KeyError."""
    dying = _row("Q1", "Allium sativum")
    apply_folds([dying, _row("Q2", "garlic")], _fold("Q1", "Q2"), {}, {})
    for mark in apply_cuts(dying, {}, {}):
        assert mark in build_library.CUT_RULE_TEXT


def test_the_survivor_records_what_it_absorbed():
    dying = _row("Q1", "Allium sativum", {"Aglio": {("wikidata", "alias", "it")}})
    survivor = _row("Q2", "garlic")
    apply_folds([dying, survivor], _fold("Q1", "Q2", reason="a name, not a row"), {}, {})
    assert survivor["folded_from"] == [("Q1", "Allium sativum", 2, "a name, not a row")]
    assert survivor["absorbed"] == ["Aglio", "Allium sativum"]
    assert dying["folded_into"] == ("Q2", "garlic")
    assert "folded into garlic (Q2)" in dying["hand_reasons"][0]
    assert survivor["n_variations"] == len(survivor["variations"]) - 1


def test_identity_is_not_copied():
    dying = _row("Q1", "Allium sativum", why="a taxon", how="its own Latin name", kinds=["taxon"])
    survivor = _row("Q2", "garlic", why="Wikidata kind is Ingredient", how="the anchor's English name",
                    kinds=["Ingredient or foodstuff"])
    apply_folds([dying, survivor], _fold("Q1", "Q2"), {}, {})
    assert survivor["why"] == "Wikidata kind is Ingredient"
    assert survivor["how"] == "the anchor's English name"
    assert survivor["kinds"] == ["Ingredient or foodstuff"]
    assert survivor["id"] == "Q2" and survivor["anchor"] == "wikidata"


def test_self_fold_is_refused():
    row = _row("Q1", "garlic")
    done, refused, _ = apply_folds([row], _fold("Q1", "Q1"), {}, {})
    assert done == [] and len(refused) == 1
    assert "cannot fold into itself" in refused[0][1]


def test_chain_fold_is_refused():
    a, b, c = _row("Q1", "A"), _row("Q2", "B"), _row("Q3", "C")
    rules = _fold("Q1", "Q2"); rules.update(_fold("Q2", "Q3"))
    done, refused, _ = apply_folds([a, b, c], rules, {}, {})
    assert any("itself being folded" in why for _, why in refused)
    assert not a.get("folded_into"), "a fold into a dying row must not happen"


def test_missing_target_is_refused():
    done, refused, _ = apply_folds([_row("Q1", "A")], _fold("Q1", "Q404"), {}, {})
    assert done == [] and "no row carries id 'Q404'" in refused[0][1]


def test_cut_target_is_refused():
    dying = _row("Q1", "Allium sativum")
    target = _row("Q2", "garlic", hand_reasons=["removed"])       # apply_cuts marks this 'hand'
    done, refused, _ = apply_folds([dying, target], _fold("Q1", "Q2"), {}, {})
    assert done == [] and "itself cut" in refused[0][1]


def test_into_canonical_mismatch_is_refused():
    """The ids are opaque, so the readable column is checked rather than trusted."""
    dying, survivor = _row("Q1", "Allium sativum"), _row("Q2", "garlic")
    done, refused, _ = apply_folds([dying, survivor], _fold("Q1", "Q2", "onion"), {}, {})
    assert done == [] and "into_canonical" in refused[0][1]
    done, refused, _ = apply_folds([dying, survivor], _fold("Q1", "Q2", "Garlic"), {}, {})
    assert len(done) == 1 and refused == [], "the check is by norm_name, not exact case"


def test_dangling_fold_is_reported_not_fatal():
    done, refused, dangling = apply_folds([_row("Q2", "garlic")], _fold("Q404", "Q2"), {}, {})
    assert done == [] and refused == []
    assert len(dangling) == 1 and "no row carries that" in dangling[0][1]


def test_a_fold_without_a_target_is_refused():
    done, refused, _ = apply_folds([_row("Q1", "A"), _row("Q2", "B")], _fold("Q1", ""), {}, {})
    assert done == [] and "names no target" in refused[0][1]
