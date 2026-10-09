"""Round B revision 4, A1: the "your changes" mark for a second amount.

The page draws the mark from the entries get_recipe sends (static/annotation-index.js slots them,
static/ledger-row.js draws them). Andy's three cases are pinned here at the level that decides
whether a mark exists at all, through the real save path: an edit to only the second amount is an
entry, putting it back removes it, and a save that changes nothing makes none.

⚠️ THE MARK IS DISPLAY ONLY. The entry these tests read has been emitted by snapshot_diff since Edit
mode first carried the field. Revision 4 changed what the client does with it, not whether it
exists, so these tests passed before the client change as well. tests/js/ledger-render.test.js
holds the drawing."""
import harness  # noqa: F401  (ensures repo/tests on sys.path)


def _tofu(client):
    rid = client.post("/api/recipes", json={
        "name": "Second Amount Dish",
        "ingredients": [{"qty": "1 block", "secondary_measure": "14 oz", "text": "firm tofu"},
                        {"qty": "1 cup", "text": "flour"}],
        "steps": ["Press the tofu"],
    }).get_json()["id"]
    return rid


def _save(client, rid, second):
    rows = client.get(f"/api/recipes/{rid}").get_json()["ingredients"]
    tofu, flour = rows
    r = client.put(f"/api/recipes/{rid}", json={
        "name": "Second Amount Dish",
        "ingredients": [{"id": tofu["id"], "qty": "1 block", "secondary_measure": second,
                         "text": "firm tofu"},
                        {"id": flour["id"], "qty": "1 cup", "text": "flour"}],
        "steps": ["Press the tofu"],
    })
    assert r.status_code == 200, r.get_json()
    return client.get(f"/api/recipes/{rid}").get_json()


def test_an_edit_to_only_the_second_amount_is_marked(kitchen):
    rid = _tofu(kitchen.client)
    d = _save(kitchen.client, rid, "400 g")
    assert d["ingredients"][0]["qty"] == "1 block"            # the first amount did not move
    assert [(a["kind"], a["type"], a["field"], a["from"], a["to"]) for a in d["annotations"]] == [
        ("ingredient", "modified", "second_amount", "14 oz", "400 g")]
    assert d["annotations"][0]["row_id"] == d["ingredients"][0]["id"]


def test_putting_the_second_amount_back_takes_the_mark_away(kitchen):
    rid = _tofu(kitchen.client)
    _save(kitchen.client, rid, "400 g")
    assert _save(kitchen.client, rid, "14 oz")["annotations"] == []


def test_a_save_that_changes_nothing_makes_no_mark(kitchen):
    rid = _tofu(kitchen.client)
    assert _save(kitchen.client, rid, "14 oz")["annotations"] == []


def test_clearing_the_second_amount_is_marked_too(kitchen):
    rid = _tofu(kitchen.client)
    d = _save(kitchen.client, rid, "")
    assert [(a["field"], a["from"], a["to"]) for a in d["annotations"]] == [
        ("second_amount", "14 oz", "")]
