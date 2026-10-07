"""scripts/realign_baseline.py — it realigns a baseline that drifted for one of THREE declared
machine reasons, and it refuses everything else.

The repair exists because three machine-origin changes moved a baseline's bytes without changing
anything a cook would recognise, so the recipe left the byte-equal short-circuit silently while
snapshot_diff reported 0 entries. Measured on live 2026-10-01: 6 of 300 recipes, 66 differences,
none of them visible anywhere.

  1. a row id      — the old save path replaced wait and storage rows instead of updating them
  2. a released link — migration 046 nulled 50 ingredient_ids and left the baselines alone
  3. null vs empty — the old save path wrote "" over a column stored as NULL

These tests pin the DECISIONS: which baselines it may rewrite, which it must leave alone, and that
the abort is armed. A pass that can rewrite a baseline is the most dangerous kind in this repo,
because the baseline is the only record of what a recipe looked like when it was born.
"""
import json
import sys

import pytest

import app
import harness  # noqa: F401
sys.path.insert(0, "scripts")
import realign_baseline as rl  # noqa: E402


def _dump(doc):
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@pytest.fixture
def dish(kitchen):
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Realign", "ingredients": [{"qty": "1", "text": "flour"}],
        "steps": ["Mix.", "Wait."]}).get_json()["id"]
    kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Realign",
        "ingredients": [{"quantity": "1", "unit": "", "text": "flour"}],
        "steps": [{"id": s["id"], "text": s["text"]}
                  for s in kitchen.client.get(f"/api/recipes/{rid}").get_json()["steps"]],
        "waits": [{"kind": "rising", "label": "2 hr"}]})
    _sync(kitchen, rid)
    return rid


def _sync(kitchen, rid):
    """Make the baseline byte-equal to current, so each test bends exactly one thing."""
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, rid)
    _set_baseline(kitchen, rid, blob)


def _baseline(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? "
                         "AND reason='original'", (rid,)).fetchone()[0]


def _set_baseline(kitchen, rid, blob):
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (blob, rid))
        c.commit()


def _current(rid):
    with app.orm_session() as s:
        return app.serialize_recipe_content(s, rid)


def _bend(blob, fn):
    doc = json.loads(blob)
    fn(doc)
    return _dump(doc)


def _is_realigned(kitchen, rid):
    with app.orm_session() as s:
        return (app.serialize_recipe_content(s, rid) == _baseline(kitchen, rid)
                and app._recipe_annotations(s, rid) == [])


# ---- case 1, a row id -----------------------------------------------------------------------

def test_a_baseline_whose_only_drift_is_a_row_id_is_realigned(dish, kitchen):
    _set_baseline(kitchen, dish, _bend(_baseline(kitchen, dish),
                                       lambda d: d["waits"][0].update(id=99999)))
    assert _current(dish) != _baseline(kitchen, dish)
    rl.run(str(kitchen.db), apply=True)
    assert _is_realigned(kitchen, dish)


# ---- case 2, a released ingredient link -----------------------------------------------------

def test_a_link_whose_row_is_gone_is_realigned(dish, kitchen):
    """Migration 046's leftover: the baseline names an ingredient the table no longer holds."""
    _set_baseline(kitchen, dish, _bend(_baseline(kitchen, dish),
                                       lambda d: d["ingredients"][0].update(ingredient_id="ghost")))
    assert _current(dish) != _baseline(kitchen, dish)
    rl.run(str(kitchen.db), apply=True)
    assert _is_realigned(kitchen, dish)


def test_a_link_whose_row_still_exists_is_left_alone(dish, kitchen):
    """⚠️ THE THIRD CLAUSE, AND IT IS NOT DECORATION. A link naming a row that still exists is not
    a release. Only a vanished row proves the machine did it."""
    with kitchen.conn() as c:
        c.execute("INSERT OR IGNORE INTO ingredients (id, name, source, concept) "
                  "VALUES ('realign-probe', 'Realign Probe', 'seed', '')")
        c.commit()
    bent = _bend(_baseline(kitchen, dish),
                 lambda d: d["ingredients"][0].update(ingredient_id="realign-probe"))
    _set_baseline(kitchen, dish, bent)
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == bent, "a link to a row that exists was realigned away"


def test_a_re_link_is_left_alone(dish, kitchen):
    """The other direction. The baseline has no link and the live row has a real one, which is
    something gaining a link, not losing one."""
    with kitchen.conn() as c:
        c.execute("INSERT OR IGNORE INTO ingredients (id, name, source, concept) "
                  "VALUES ('realign-probe', 'Realign Probe', 'seed', '')")
        c.execute("UPDATE recipe_ingredients SET ingredient_id='realign-probe' "
                  "WHERE recipe_id=?", (dish,))
        c.commit()
    before = _baseline(kitchen, dish)
    assert _current(dish) != before
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == before, "a re-link was realigned away"


# ---- case 3, null written as an empty string ------------------------------------------------

def test_null_against_empty_is_realigned(dish, kitchen):
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET descr='' WHERE id=?", (dish,))
        c.commit()
    _set_baseline(kitchen, dish, _bend(_current(dish), lambda d: d["recipe"].update(descr=None)))
    assert _current(dish) != _baseline(kitchen, dish)
    rl.run(str(kitchen.db), apply=True)
    assert _is_realigned(kitchen, dish)


def test_whitespace_is_not_folded(dish, kitchen):
    """⚠️ ONLY None AGAINST "", NEVER WHITESPACE. units.compare_text folds a re-wrap and this must
    not: a cook who re-wrapped a headnote made a real edit."""
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET descr='one line' WHERE id=?", (dish,))
        c.commit()
    # ⚠️ descr, NOT notes. This bent the retired recipes.notes copy until migration 063 dropped it.
    #    The question is the same for any text field the baseline carries: a baseline that differs
    #    from the row only by whitespace is still a difference and must not be folded away.
    bent = _bend(_current(dish), lambda d: d["recipe"].update(descr="one  line"))
    _set_baseline(kitchen, dish, bent)
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == bent, "a re-wrap was folded away"


# ---- all three at once ----------------------------------------------------------------------

def test_all_three_cases_together_are_realigned(dish, kitchen):
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET descr='' WHERE id=?", (dish,))
        c.commit()

    def bend(d):
        d["recipe"]["descr"] = None
        d["waits"][0]["id"] = 99999
        d["ingredients"][0]["ingredient_id"] = "ghost"

    _set_baseline(kitchen, dish, _bend(_current(dish), bend))
    rl.run(str(kitchen.db), apply=True)
    assert _is_realigned(kitchen, dish)


# ---- the refusals ---------------------------------------------------------------------------

def test_a_dry_run_writes_nothing(dish, kitchen):
    bent = _bend(_baseline(kitchen, dish), lambda d: d["waits"][0].update(id=99999))
    _set_baseline(kitchen, dish, bent)
    rl.run(str(kitchen.db), apply=False)
    assert _baseline(kitchen, dish) == bent, "a dry run rewrote the baseline"


def test_a_baseline_that_differs_in_anything_else_is_left_alone(dish, kitchen):
    """⚠️ THE ABORT THIS SCRIPT EXISTS BEHIND. A recipe the cook really edited must keep its
    baseline, because that baseline is the only record of what it looked like when it was born."""
    def bend(d):
        d["waits"][0]["id"] = 99999
        d["waits"][0]["label"] = "something the cook never typed"

    bent = _bend(_baseline(kitchen, dish), bend)
    _set_baseline(kitchen, dish, bent)
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == bent, "a real difference was overwritten"


def test_a_recipe_carrying_real_marks_is_left_alone(dish, kitchen):
    """The ordinary annotated case: a cook edited a step, the page shows it, nothing here applies."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    kitchen.client.put(f"/api/recipes/{dish}", json={
        "name": d["recipe"]["name"],
        "ingredients": [{"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
                         "text": x["label"]} for x in d["ingredients"]],
        "steps": [{"id": d["steps"][0]["id"], "text": "Mix it differently."},
                  {"id": d["steps"][1]["id"], "text": d["steps"][1]["text"]}]})
    before = _baseline(kitchen, dish)
    with app.orm_session() as s:
        assert app._recipe_annotations(s, dish), "the fixture should carry a mark here"
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == before


def test_a_byte_equal_recipe_is_not_touched(dish, kitchen):
    before = _baseline(kitchen, dish)
    rl.run(str(kitchen.db), apply=True)
    assert _baseline(kitchen, dish) == before


# ---- the comparison the whole abort rests on ------------------------------------------------

def test_normalize_erases_the_three_cases_and_nothing_else():
    live = {"realign-probe"}

    def blob(**over):
        doc = {"recipe": {"name": "n", "descr": None},
               "waits": [{"id": 1, "label": "x"}],
               "ingredients": [{"id": 5, "ingredient_id": None, "label": "flour", "note": None}]}
        for k, v in over.items():
            path, _, field = k.partition("__")
            target = doc[path][0] if isinstance(doc[path], list) else doc[path]
            target[field] = v
        return _dump(doc)

    base = blob()
    assert rl._normalize(base, live) == rl._normalize(blob(waits__id=77), live), "a row id should not show"
    assert rl._normalize(base, live) == rl._normalize(blob(recipe__descr=""), live), "null vs empty should not show"
    assert rl._normalize(base, live) == rl._normalize(blob(ingredients__ingredient_id="ghost"), live), \
        "a link to a vanished row should not show"

    assert rl._normalize(base, live) != rl._normalize(blob(waits__label="y"), live), "a label MUST show"
    assert rl._normalize(base, live) != rl._normalize(blob(recipe__descr="something"), live), "real text MUST show"
    assert rl._normalize(base, live) != rl._normalize(blob(ingredients__ingredient_id="realign-probe"), live), \
        "a link to a row that EXISTS must show"


def test_a_notes_row_is_one_of_the_row_lists_the_script_can_realign():
    """⚠️ notes JOINED ROW_LISTS WITH MIGRATION 060 AND WAS LEFT OUT. A machine drift inside a note
    row fell through to the raw comparison, so the recipe was reported as differing in something
    real and could never be realigned. It failed safe rather than mis-writing, and it failed on
    exactly the rows this round added."""
    import realign_baseline

    assert "notes" in realign_baseline.ROW_LISTS

    stored = {"recipe": {"name": "X"},
              "notes": [{"id": 12, "position": 0, "kind": "notes", "text": "A note.",
                         "step_id": None, "ingredient_row_id": None}]}
    current = {"recipe": {"name": "X"},
               "notes": [{"id": 108, "position": 0, "kind": "notes", "text": "A note.",
                          "step_id": None, "ingredient_row_id": None}]}
    import json
    cases, _detail = realign_baseline._cases(json.dumps(stored), json.dumps(current),
                                             live_ingredients=set())
    assert list(cases) == [realign_baseline.CASE_ID], cases
