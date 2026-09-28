"""The save refuses to empty a row it is keeping.

⚠️ THIS GUARDS A CLASS OF BUG, NOT A BUG. The real editor cannot trip it: nonEmptyRows and
nonEmptySteps prune a blank row before the payload is built, so a blank row simply does not arrive,
and a row the payload drops is an ordinary delete. What trips it is the SERVER reading the payload
differently from how the client wrote it.

It has nearly happened once. Option C gave a non-heading step an object wire form so it could carry
a row id, and write_recipe_rows read a step as `step if isinstance(step, str) else ""`. Every object
step would have been written BLANK — the whole method of every recipe, on its first save, answered
with a 200. That was caught by reading the code. This is the test that does not need anyone to read
the code.
"""
import copy

import pytest

import app as app_module


def _make(kitchen, name="Guarded"):
    return kitchen.client.post("/api/recipes", json={
        "name": name,
        "ingredients": [{"heading": "FOR THE SAUCE"},
                        {"quantity": "2", "unit": "tbsp", "text": "soy sauce", "note": ""},
                        {"quantity": "1", "unit": "tsp", "text": "sesame oil", "note": ""}],
        "steps": [{"heading": "MAKE IT"}, "Whisk the sauce.", "Rest it."],
    }).get_json()["id"]


def _served(kitchen, rid):
    return kitchen.client.get(f"/api/recipes/{rid}").get_json()


def _payload(got, **over):
    body = {
        "name": got["recipe"]["name"],
        "ingredients": [
            {"id": x["id"], "heading": x["heading"] if x.get("heading") is not None
             else (x["raw_text"] or "")} if x["is_heading"]
            else {"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
                  "text": x["label"] or x["raw_text"] or "", "note": x["note"] or ""}
            for x in got["ingredients"]],
        "steps": [{"id": x["id"], "heading": x["text"]} if x["is_heading"]
                  else {"id": x["id"], "text": x["text"]} for x in got["steps"]],
    }
    body.update(over)
    return body


def _rows(kitchen, rid):
    with kitchen.conn() as c:
        return ([dict(r) for r in c.execute(
                    "SELECT * FROM recipe_ingredients WHERE recipe_id=? ORDER BY position, id", (rid,))],
                [dict(r) for r in c.execute(
                    "SELECT * FROM recipe_steps WHERE recipe_id=? ORDER BY position, id", (rid,))])


# --------------------------------------------------------------------------------------------- #
# The shape that nearly shipped
# --------------------------------------------------------------------------------------------- #
def test_a_step_shape_the_server_reads_as_empty_is_refused(kitchen):
    """⚠️ THE CLIENT/SERVER MISMATCH, SIMULATED. A client sends its step text under a key the server
    does not read. _step_parts resolves the text to "", the row keeps its id, and the save would
    quietly blank it. Before this guard the answer was 200 and the method was gone."""
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    before = _rows(kitchen, rid)
    body = _payload(got)
    body["steps"] = [s if "heading" in s else {"id": s["id"], "body": s["text"]}   # wrong key
                     for s in body["steps"]]
    # The guard RAISES, so the route answers 500 rather than 200. The point is the second
    # assertion: the transaction rolled back and the recipe is untouched.
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 500
    assert _rows(kitchen, rid) == before          # and NOTHING was committed


def test_a_mismatch_across_every_step_is_refused(kitchen):
    """A mismatch hits the whole recipe at once, not one row, which is exactly why it is worth
    catching: 200 with an empty method looks like a successful save."""
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    body = _payload(got)
    body["steps"] = [{"id": s["id"], "body": "x"} if "heading" not in s else s
                     for s in body["steps"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 500


def test_an_ingredient_the_server_reads_as_nameless_is_refused(kitchen):
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    before = _rows(kitchen, rid)
    body = _payload(got)
    body["ingredients"] = [dict(x, text="") if "text" in x else x for x in body["ingredients"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 500
    assert _rows(kitchen, rid) == before


def test_a_heading_the_server_reads_as_titleless_is_refused(kitchen):
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    body = _payload(got)
    body["ingredients"] = [dict(x, heading="") if "heading" in x else x
                           for x in body["ingredients"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 500


# --------------------------------------------------------------------------------------------- #
# What the guard must NOT refuse
# --------------------------------------------------------------------------------------------- #
def test_deleting_a_row_by_id_is_allowed(kitchen):
    """⚠️ THE EXEMPTION ANDY NAMED. A row the payload drops is gone on purpose, and clearing a step's
    text IS how the editor deletes one — nonEmptySteps prunes it, so it never arrives at all."""
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    body = _payload(got)
    body["steps"] = [s for s in body["steps"] if s.get("text") != "Rest it."]
    body["ingredients"] = [x for x in body["ingredients"] if x.get("text") != "sesame oil"]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    ings, steps = _rows(kitchen, rid)
    assert [x["text"] for x in steps] == ["MAKE IT", "Whisk the sauce."]
    assert "sesame oil" not in [x["label"] for x in ings]


def test_deleting_every_row_is_allowed(kitchen):
    """Emptying a recipe on purpose is an edit, not a blanking."""
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_payload(got, ingredients=[], steps=[])).status_code == 200
    ings, steps = _rows(kitchen, rid)
    assert ings == [] and steps == []


def test_a_no_edit_save_is_allowed(kitchen):
    rid = _make(kitchen)
    before = _rows(kitchen, rid)
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_payload(_served(kitchen, rid))).status_code == 200
    assert _rows(kitchen, rid) == before


def test_editing_a_row_to_new_text_is_allowed(kitchen):
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    body = _payload(got)
    body["steps"] = [dict(s, text="Whisk it hard.") if s.get("text") == "Whisk the sauce." else s
                     for s in body["steps"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    _, steps = _rows(kitchen, rid)
    assert "Whisk it hard." in [x["text"] for x in steps]


def test_a_row_that_was_already_empty_is_not_a_problem(kitchen):
    """The guard is about a row that READ as something and stops reading as anything. A row that was
    already blank going in has nothing to lose, so it is not reported."""
    rid = _make(kitchen)
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_steps SET text='' WHERE recipe_id=? AND text='Rest it.'", (rid,))
        c.commit()
    got = _served(kitchen, rid)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_payload(got)).status_code == 200


def test_converting_a_line_to_a_heading_is_allowed(kitchen):
    """The row still reads as something — its title — so the conversion is not a blanking."""
    rid = _make(kitchen)
    got = _served(kitchen, rid)
    target = next(x for x in got["ingredients"] if not x["is_heading"])
    body = _payload(got)
    body["ingredients"] = [{"id": target["id"], "heading": "FOR THE BRINE"}
                           if x.get("id") == target["id"] else x for x in body["ingredients"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200


# --------------------------------------------------------------------------------------------- #
# The function on its own
# --------------------------------------------------------------------------------------------- #
def test_blanked_row_problems_is_empty_when_nothing_moved():
    rows = [{"id": 1, "position": 0, "is_heading": 0, "text": "Whisk."}]
    assert app_module.blanked_row_problems(rows, rows, "step") == []


def test_blanked_row_problems_ignores_a_row_that_is_gone():
    before = [{"id": 1, "position": 0, "is_heading": 0, "text": "Whisk."}]
    assert app_module.blanked_row_problems(before, [], "step") == []


def test_blanked_row_problems_reports_the_id_and_the_old_text():
    before = [{"id": 7, "position": 0, "is_heading": 0, "text": "Whisk."}]
    after = [{"id": 7, "position": 0, "is_heading": 0, "text": "   "}]
    got = app_module.blanked_row_problems(before, after, "step")
    assert len(got) == 1
    assert "id=7" in got[0] and "'Whisk.'" in got[0]


def test_whitespace_only_counts_as_empty():
    before = [{"id": 7, "position": 0, "is_heading": 0, "label": "salt", "raw_text": "1 tsp salt"}]
    after = [{"id": 7, "position": 0, "is_heading": 0, "label": "  ", "raw_text": ""}]
    assert len(app_module.blanked_row_problems(before, after, "ingredient")) == 1
