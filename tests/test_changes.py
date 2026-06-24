"""Per-person change layers: edits, removals, clears, additions, sections, validation,
and that a rebuild preserves all of it."""


def test_edit_remove_clear(kitchen):
    pos = kitchen.first_line_pos("gai-yang")
    cl = kitchen.client

    edit = cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "edit", "qty": "2x"})
    assert edit.status_code == 200
    assert edit.get_json()["changes"]["andy"]["edits"][str(pos)] == "2x"

    remove = cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "remove"})
    assert pos in remove.get_json()["changes"]["andy"]["removes"]

    clear = cl.delete(f"/api/recipes/gai-yang/people/andy/lines/{pos}")
    andy = clear.get_json()["changes"].get("andy", {})
    assert str(pos) not in andy.get("edits", {})
    assert pos not in andy.get("removes", [])


def test_per_person_independent(kitchen):
    pos = kitchen.first_line_pos("gai-yang")
    cl = kitchen.client
    cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "edit", "qty": "6"})
    cl.put(f"/api/recipes/gai-yang/people/vedant/lines/{pos}", json={"kind": "edit", "qty": "8"})
    ch = cl.get("/api/recipes/gai-yang").get_json()["changes"]
    assert ch["andy"]["edits"][str(pos)] == "6"
    assert ch["vedant"]["edits"][str(pos)] == "8"


def test_additions_linked_and_plain(kitchen):
    cl = kitchen.client
    linked = cl.post("/api/recipes/gai-yang/people/andy/additions",
                     json={"qty": "1", "item": "garlic", "note": ", smashed"})
    assert linked.status_code == 200
    assert any(a["ingredient_id"] == "garlic" for a in linked.get_json()["changes"]["andy"]["additions"])

    plain = cl.post("/api/recipes/gai-yang/people/andy/additions",
                    json={"qty": "to taste", "text": "extra chili"})
    adds = plain.get_json()["changes"]["andy"]["additions"]
    assert any(a["raw_text"] == "extra chili" and a["ingredient_id"] is None for a in adds)


def test_addition_section(kitchen):
    cl = kitchen.client  # gai-yang has a "Marinade" section heading
    ok = cl.post("/api/recipes/gai-yang/people/andy/additions", json={"text": "msg", "section": "Marinade"})
    assert ok.status_code == 200
    assert any(a["section"] == "Marinade" for a in ok.get_json()["changes"]["andy"]["additions"])

    bad = cl.post("/api/recipes/gai-yang/people/andy/additions", json={"text": "x", "section": "Not A Section"})
    assert bad.status_code == 400


def test_change_validation(kitchen):
    cl = kitchen.client
    pos = kitchen.first_line_pos("gai-yang")
    assert cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "edit", "qty": ""}).status_code == 400
    assert cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "bogus"}).status_code == 400
    assert cl.put(f"/api/recipes/gai-yang/people/ghost/lines/{pos}", json={"kind": "remove"}).status_code == 404
    assert cl.post("/api/recipes/gai-yang/people/andy/additions", json={"item": "not-real"}).status_code == 400
    assert cl.post("/api/recipes/gai-yang/people/andy/additions", json={}).status_code == 400


def test_changes_rejected_on_app_recipe(kitchen):
    cl = kitchen.client
    cl.post("/api/recipes", json={"name": "App R", "ingredients": [{"qty": "1", "text": "x"}], "steps": ["go"]})
    assert cl.put("/api/recipes/app-r/people/andy/lines/0", json={"kind": "remove"}).status_code == 400


def test_rebuild_preserves_changes(kitchen):
    cl = kitchen.client
    pos = kitchen.first_line_pos("gai-yang")
    cl.put(f"/api/recipes/gai-yang/people/andy/lines/{pos}", json={"kind": "edit", "qty": "6"})
    cl.post("/api/recipes/gai-yang/people/andy/additions", json={"text": "chili flakes", "section": "Marinade"})

    kitchen.rebuild()

    with kitchen.conn() as c:
        edit = c.execute(
            "SELECT new_qty FROM recipe_line_changes "
            "WHERE recipe_id='gai-yang' AND person_id='andy' AND position=?", (pos,)).fetchone()
        additions = c.execute(
            "SELECT COUNT(*) FROM recipe_additions WHERE recipe_id='gai-yang'").fetchone()[0]
    assert edit and edit[0] == "6"
    assert additions >= 1
    assert kitchen.fk_orphans() == []
