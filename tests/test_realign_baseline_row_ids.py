"""scripts/realign_baseline_row_ids.py — it fixes a baseline whose ONLY drift is row ids, and it
refuses everything else.

The repair exists because the old save path replaced wait and storage rows instead of updating them,
so a save that changed nothing moved the row ids, and the snapshot records them. The recipe stopped
being byte-equal to its baseline and left the short-circuit silently, since snapshot_diff compares by
meaning and reported 0 entries.

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
import realign_baseline_row_ids as rl  # noqa: E402


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
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, rid)
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (blob, rid))
        c.commit()
    return rid


def _baseline(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? "
                         "AND reason='original'", (rid,)).fetchone()[0]


def _set_baseline(kitchen, rid, blob):
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (blob, rid))
        c.commit()


def _bend_wait_id(blob, new_id):
    doc = json.loads(blob)
    doc["waits"][0]["id"] = new_id
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def test_a_baseline_whose_only_drift_is_a_row_id_is_realigned(dish, kitchen):
    _set_baseline(kitchen, dish, _bend_wait_id(_baseline(kitchen, dish), 99999))
    with app.orm_session() as s:
        assert app.serialize_recipe_content(s, dish) != _baseline(kitchen, dish)

    rl.run(str(kitchen.db), apply=True)

    with app.orm_session() as s:
        assert app.serialize_recipe_content(s, dish) == _baseline(kitchen, dish)
        assert app._recipe_annotations(s, dish) == []


def test_a_dry_run_writes_nothing(dish, kitchen):
    bent = _bend_wait_id(_baseline(kitchen, dish), 99999)
    _set_baseline(kitchen, dish, bent)
    rl.run(str(kitchen.db), apply=False)
    assert _baseline(kitchen, dish) == bent, "a dry run rewrote the baseline"


def test_a_baseline_that_differs_in_anything_else_is_left_alone(dish, kitchen):
    """⚠️ THE ABORT THIS SCRIPT EXISTS BEHIND. A recipe the cook really edited must keep its
    baseline, because that baseline is the only record of what it looked like when it was born."""
    doc = json.loads(_baseline(kitchen, dish))
    doc["waits"][0]["id"] = 99999
    doc["waits"][0]["label"] = "something the cook never typed"
    bent = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
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


def test_bare_ignores_row_ids_and_nothing_else():
    """The comparison the whole abort rests on."""
    a = json.dumps({"waits": [{"id": 1, "label": "x"}], "recipe": {"name": "n"}},
                   sort_keys=True, separators=(",", ":"))
    b = json.dumps({"waits": [{"id": 77, "label": "x"}], "recipe": {"name": "n"}},
                   sort_keys=True, separators=(",", ":"))
    c = json.dumps({"waits": [{"id": 1, "label": "y"}], "recipe": {"name": "n"}},
                   sort_keys=True, separators=(",", ":"))
    assert rl._bare(a) == rl._bare(b), "a differing id should not show"
    assert rl._bare(a) != rl._bare(c), "a differing label MUST show"
