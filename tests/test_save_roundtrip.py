"""The save must not destroy what the client never sends back.

⚠️ THE PAYLOADS HERE ARE THE CLIENT'S OWN OUTPUT, NOT A LITERAL. tests/fixtures/save-roundtrip.json
is captured from static/save-payload.js by scripts/gen_save_roundtrip.mjs, and
tests/js/save-payload-sync.test.js holds the client to it. That is the gap
previews/save-path-scoping.md found: the Python suite had 20-plus PUT tests, every payload
hand-written, and a no-edit save was clearing `label`, overwriting `raw_text` with the displayed
label and wiping all four linkage columns on every row of the recipe. Nothing went red.
"""
import copy
import json
import pathlib

import pytest

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "save-roundtrip.json")
                 .read_text(encoding="utf-8"))

# Every column a row carries. `id` is excluded on purpose: the save still deletes and reinserts, so
# ids churn by design until option C (update in place) lands. Everything else must survive.
COLS = ("position", "is_heading", "qty", "quantity", "unit", "ingredient_id", "label", "note",
        "raw_text", "grams", "secondary_measure", "catalog_id", "link_confidence", "link_rule",
        "link_matched")

# ⚠️ THE FIXTURE'S ids ARE INSERTED VERBATIM (option C commit 1). The payloads carry the id the
# client read off the GET, so the stored row and the payload have to agree on one. They are 9001+
# and 9101+ to clear the rows the fixture recipes already hold. See scripts/gen_save_roundtrip.mjs.


def _seed(kitchen, rows=None, steps=None, name="Round Trip"):
    """A recipe whose stored rows are EXACTLY the fixture's, written straight to the table.

    Direct SQL on purpose: these are shapes only an import or a linkage pass produces (a NULL label
    beside a populated raw_text, a catalog_id, a harvested weight), and no API creates them.
    """
    rows = FIX["rows"] if rows is None else rows
    steps = FIX["steps"] if steps is None else steps
    rid = kitchen.client.post("/api/recipes", json={
        "name": name, "ingredients": [], "steps": ["placeholder"],
    }).get_json()["id"]
    with kitchen.conn() as c:
        c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
        c.execute("DELETE FROM recipe_steps WHERE recipe_id=?", (rid,))
        c.execute("INSERT OR IGNORE INTO ingredients (id, name, source, concept) "
                  "VALUES ('egg_pasta', 'egg pasta', 'app', '')")
        for r in rows:
            row = r["row"]
            c.execute(f"INSERT INTO recipe_ingredients (id, recipe_id, {','.join(COLS)}) "
                      f"VALUES (?,?,{','.join('?' * len(COLS))})",
                      (row.get("id"), rid, *[row[k] for k in COLS]))
        for s in steps:
            st = s["row"]
            c.execute("INSERT INTO recipe_steps (id, recipe_id, position, is_heading, text) "
                      "VALUES (?,?,?,?,?)",
                      (st.get("id"), rid, st["position"], st["is_heading"], st["text"]))
        c.commit()
    return rid


def _rows(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            f"SELECT id,{','.join(COLS)} FROM recipe_ingredients WHERE recipe_id=? "
            f"ORDER BY position, id", (rid,))]


def _steps(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, position, is_heading, text FROM recipe_steps WHERE recipe_id=? "
            "ORDER BY position, id", (rid,))]


def _strip_ids(rows):
    return [{k: v for k, v in r.items() if k != "id"} for r in rows]


def _stripped(entries):
    """The fixture's entries with the id taken out of BOTH halves — the payload an older client
    sends, against a recipe whose rows were inserted the ordinary way."""
    return [{**e,
             "row": {k: v for k, v in e["row"].items() if k != "id"},
             "payload": {k: v for k, v in e["payload"].items() if k != "id"}}
            for e in entries]


def _save(kitchen, rid, rows=None, steps=None, name="Round Trip"):
    """PUT the recipe back with the client's own payload for every row."""
    payload = {
        "name": name,
        "ingredients": [r["payload"] for r in (FIX["rows"] if rows is None else rows)],
        "steps": [s["payload"] for s in (FIX["steps"] if steps is None else steps)],
    }
    return kitchen.client.put(f"/api/recipes/{rid}", json=payload)


def _annotations(kitchen, rid):
    return kitchen.client.get(f"/api/recipes/{rid}").get_json()["annotations"]


# --------------------------------------------------------------------------------------------- #
# A no-edit save changes nothing
# --------------------------------------------------------------------------------------------- #
def test_a_no_edit_save_leaves_every_ingredient_row_identical(kitchen):
    rid = _seed(kitchen)
    before = _rows(kitchen, rid)
    assert _save(kitchen, rid).status_code == 200
    after = _rows(kitchen, rid)
    assert len(after) == len(before)
    assert _strip_ids(after) == _strip_ids(before)


def test_a_no_edit_save_leaves_every_step_identical(kitchen):
    rid = _seed(kitchen)
    before = _steps(kitchen, rid)
    assert _save(kitchen, rid).status_code == 200
    assert _strip_ids(_steps(kitchen, rid)) == _strip_ids(before)


def test_the_linkage_columns_survive_a_save(kitchen):
    """⚠️ 2,767 live rows over 293 recipes carry these, and nothing in the payload mentions them."""
    rid = _seed(kitchen)
    linked = lambda: [(r["raw_text"], r["catalog_id"], r["link_confidence"], r["link_rule"],
                       r["link_matched"]) for r in _rows(kitchen, rid)]
    before = linked()
    assert any(x[1] is not None for x in before)          # the fixture really does carry links
    _save(kitchen, rid)
    assert linked() == before


def test_a_no_edit_save_does_not_move_the_annotations(kitchen):
    """⚠️ MEASURED FROM A SETTLED RECIPE, NOT A FRESHLY SEEDED ONE. update_recipe also calls
    sync_original_heading_layout, which brings the baseline's heading layout into step with the
    rows on the FIRST save. That is a real and wanted change, so the contract is that the save
    after it moves nothing. Checked against live data the same way: birria-tacos, already settled,
    returned the same 2 annotations before and after."""
    rid = _seed(kitchen)
    _save(kitchen, rid)                       # let the heading sync settle
    before = _annotations(kitchen, rid)
    _save(kitchen, rid)
    assert _annotations(kitchen, rid) == before


def test_a_second_no_edit_save_also_changes_nothing_at_all(kitchen):
    """⚠️ THIS ONCE ASSERTED THE OPPOSITE. Until option C commit 2 the save deleted the recipe's
    rows and reinserted them, so it ended `assert ids != ids` — the ids churned by design and
    nothing outside these two tables could point at a row. They now hold still."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    once = _rows(kitchen, rid)
    _save(kitchen, rid)
    twice = _rows(kitchen, rid)
    assert twice == once                                          # ids included


def test_raw_text_is_never_rebuilt_from_qty_and_label(kitchen):
    """The imported shape: raw_text carries the amount and an aside the label does not."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    row = [r for r in _rows(kitchen, rid) if r["label"] == "guajillo chillies, dried"][0]
    assert row["raw_text"] == "25 g (0.9 oz) guajillo chillies, dried"


def test_a_null_label_stays_null(kitchen):
    """The Paprika shape. The client sends raw_text as `text`, and writing that to `label` would
    quietly fill 373 live rows the reparse round is still deciding about."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    row = [r for r in _rows(kitchen, rid) if r["raw_text"] == "extra virgin olive oil"][0]
    assert row["label"] is None


def test_the_unit_the_client_rewrites_still_matches_its_stored_row(kitchen):
    """⚠️ canonicalizeUnit sends "1 teaspoon" back as "1 tsp". 1,157 of 3,349 live rows are rewritten
    that way and 66 of them carry a weight. Comparing the raw strings made every one a key MISS."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    row = [r for r in _rows(kitchen, rid) if r["raw_text"] == "kosher salt"][0]
    assert row["unit"] == "teaspoon"        # the stored spelling is kept, not healed to "tsp"
    assert row["qty"] == "1 teaspoon"
    assert row["grams"] == 6.0              # and the weight carried, which a key miss would clear
    assert row["catalog_id"] == "Q4116639"


def test_duplicate_rows_are_matched_one_to_one_not_many_to_one(kitchen):
    """Two rows share a name and a qty. Each must get its OWN stored row back, never the first
    match twice. Measured on live: 17 of 297 recipes repeat the full key over 50 rows."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    flour = [r for r in _rows(kitchen, rid) if r["raw_text"] == "flour"]
    assert len(flour) == 2
    assert all(r["grams"] == 120.0 and r["catalog_id"] == "Q95388739" for r in flour)
    water = [r for r in _rows(kitchen, rid) if r["raw_text"] == "water"]
    assert [r["link_rule"] for r in water] == ["exact", "form_strip:cold"]   # told apart by qty


def test_a_heading_survives_a_save(kitchen):
    rid = _seed(kitchen)
    _save(kitchen, rid)
    head = [r for r in _rows(kitchen, rid) if r["is_heading"]]
    assert len(head) == 1 and head[0]["raw_text"] == "FOR THE SAUCE:"
    assert head[0]["note"] == ""          # the stored spelling, not drifted to NULL


def test_a_note_row_survives_a_save(kitchen):
    rid = _seed(kitchen)
    _save(kitchen, rid)
    row = [r for r in _rows(kitchen, rid) if r["label"] == "soy sauce"][0]
    assert row["note"] == "all-purpose or light"
    assert row["raw_text"] == "2 tbsp soy sauceall-purpose or light"


def test_a_linked_row_keeps_its_item_and_its_source_line(kitchen):
    rid = _seed(kitchen)
    _save(kitchen, rid)
    row = [r for r in _rows(kitchen, rid) if r["ingredient_id"] == "egg_pasta"][0]
    assert row["raw_text"] == "200 g fresh egg pasta, cut into ribbons"
    assert row["label"] == "egg pasta" and row["catalog_id"] == "en:egg-pasta"


# --------------------------------------------------------------------------------------------- #
# A real edit touches only the row that was edited
# --------------------------------------------------------------------------------------------- #
def test_editing_one_rows_text_changes_only_that_row(kitchen):
    rid = _seed(kitchen)
    before = {r["position"]: r for r in _rows(kitchen, rid)}
    rows = copy.deepcopy(FIX["rows"])
    rows[2]["payload"]["text"] = "cold-pressed rapeseed oil"      # was 'extra virgin olive oil'
    assert _save(kitchen, rid, rows=rows).status_code == 200

    after = {r["position"]: r for r in _rows(kitchen, rid)}
    edited = after[2]
    assert edited["label"] == "cold-pressed rapeseed oil"
    assert edited["raw_text"] == "cold-pressed rapeseed oil"      # it IS the new source line
    assert edited["catalog_id"] is None and edited["link_confidence"] is None
    for pos in before:
        if pos == 2:
            continue
        assert {k: v for k, v in after[pos].items() if k != "id"} == \
               {k: v for k, v in before[pos].items() if k != "id"}


def test_changing_only_the_amount_keeps_the_line_and_its_link(kitchen):
    """⚠️ AN EXTENSION OF THE KEY THE SCOPE PROPOSED, and the reason is the brief's own rule: a row
    the user did not edit keeps everything. Changing "2 tbsp" to "3 tbsp" does not edit the
    ingredient. The harvested WEIGHT still goes, because a weight belongs to the amount it came
    from, which is what test_edit_preserves_unchanged_harvested_grams pins."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[3]["payload"]["quantity"] = "2"                          # kosher salt, was "1 teaspoon"
    _save(kitchen, rid, rows=rows)
    row = [r for r in _rows(kitchen, rid) if r["raw_text"] == "kosher salt"][0]
    assert row["qty"] == "2 tsp"
    assert row["catalog_id"] == "Q4116639"                        # the link survives the amount
    assert row["grams"] is None                                   # the weight does not


# --------------------------------------------------------------------------------------------- #
# Moving rows around
# --------------------------------------------------------------------------------------------- #
def test_reorder_insert_and_delete_leave_every_surviving_row_intact(kitchen):
    rid = _seed(kitchen)
    before = {r["raw_text"]: r for r in _rows(kitchen, rid) if not r["is_heading"]}

    rows = copy.deepcopy(FIX["rows"])
    rows[1], rows[5] = rows[5], rows[1]                            # reorder
    rows.pop(4)                                                    # delete the note row
    rows.insert(3, {"shape": "new", "row": {}, "payload":
                    {"quantity": "1", "unit": "pinch", "text": "saffron", "note": ""}})
    assert _save(kitchen, rid, rows=rows).status_code == 200

    after = {r["raw_text"]: r for r in _rows(kitchen, rid) if not r["is_heading"]}
    assert "2 tbsp soy sauceall-purpose or light" not in after     # the deleted row is gone
    assert after["saffron"]["label"] == "saffron"                  # the new row is a new line
    assert after["saffron"]["catalog_id"] is None
    for name in ("25 g (0.9 oz) guajillo chillies, dried", "extra virgin olive oil", "kosher salt",
                 "200 g fresh egg pasta, cut into ribbons"):
        a, b = after[name], before[name]
        assert a["catalog_id"] == b["catalog_id"] and a["grams"] == b["grams"]
        assert a["label"] == b["label"] and a["raw_text"] == b["raw_text"]
    # and the reorder really did happen, so the rows above were matched across a move
    assert after["25 g (0.9 oz) guajillo chillies, dried"]["position"] != \
           before["25 g (0.9 oz) guajillo chillies, dried"]["position"]


def test_an_inserted_row_cannot_steal_a_line_a_later_row_matches_exactly(kitchen):
    """⚠️ THE TIERS RUN OVER THE WHOLE RECIPE, EXACT first, never one pass per row.

    The fixture's two water rows are told apart only by their amount. Insert a third water row
    with an amount neither of them has, and a row-by-row carry resolves the new row FIRST: it
    misses the exact tier, falls to the name tier, and consumes the "3 tbsp" row's stored line
    and link. The "3 tbsp" row then takes the "2 tbsp" row's, and the "2 tbsp" row is left with
    nothing. One insertion, two untouched rows corrupted, and a brand new row wearing another
    line's link. Salt for the dough and salt for the brine is the same shape."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows.insert(5, {"shape": "new", "row": {}, "payload":
                    {"quantity": "1", "unit": "cup", "text": "water", "note": ""}})
    assert _save(kitchen, rid, rows=rows).status_code == 200

    water = [r for r in _rows(kitchen, rid) if r["raw_text"] == "water"]
    assert len(water) == 3
    fresh = [r for r in water if r["qty"] == "1 cup"][0]
    assert fresh["catalog_id"] is None                   # the new row is a NEW row
    assert fresh["link_rule"] is None
    kept = {r["qty"]: r for r in water if r["qty"] != "1 cup"}
    assert kept["3 tbsp"]["link_rule"] == "exact"        # each stored row stayed on its own line
    assert kept["2 tbsp"]["link_rule"] == "form_strip:cold"
    assert all(r["catalog_id"] == "water" for r in kept.values())


# --------------------------------------------------------------------------------------------- #
# Option C, commit 1: the row id makes the round trip, and the server ignores it
#
# The read half was ALREADY true and is pinned here rather than added: get_recipe selects the whole
# table, so `id` has always been served on every ingredient and step row, and enterEditMode's
# structuredClone has always copied it into the draft. It was dropped on the way BACK, by
# ingToPayload / stepToPayload, which is why no row id survived a save.
# --------------------------------------------------------------------------------------------- #
def test_the_api_serves_a_row_id_on_every_ingredient_and_step(kitchen):
    rid = _seed(kitchen)
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert [r["id"] for r in got["ingredients"]] == [r["row"]["id"] for r in FIX["rows"]]
    assert [x["id"] for x in got["steps"]] == [x["row"]["id"] for x in FIX["steps"]]


def test_a_payload_carrying_ids_saves_exactly_like_one_without(kitchen):
    """Commit 1 is additive: the id rides along and nothing reads it yet. Commit 2 is where it
    starts to mean something, and this is the before-picture it has to change."""
    with_ids = _seed(kitchen)
    assert _save(kitchen, with_ids).status_code == 200

    without = _seed(kitchen, rows=_stripped(FIX["rows"]), steps=_stripped(FIX["steps"]),
                    name="Round Trip, Older Client")
    assert _save(kitchen, without, name="Round Trip, Older Client",
                 rows=_stripped(FIX["rows"]), steps=_stripped(FIX["steps"])).status_code == 200

    assert _strip_ids(_rows(kitchen, with_ids)) == _strip_ids(_rows(kitchen, without))
    assert _strip_ids(_steps(kitchen, with_ids)) == _strip_ids(_steps(kitchen, without))


def test_a_step_sent_as_an_object_keeps_its_text(kitchen):
    """⚠️ THE ONE THAT WOULD HAVE EATEN EVERY STEP. write_recipe_rows read a step as
    `step if isinstance(step, str) else ""`, so the new {"id": …, "text": …} form would have been
    written BLANK on every save, and a blank step is how the client deletes one."""
    rid = _seed(kitchen)
    assert _save(kitchen, rid).status_code == 200
    assert [x["text"] for x in _steps(kitchen, rid)] == [x["row"]["text"] for x in FIX["steps"]]
    assert [x["is_heading"] for x in _steps(kitchen, rid)] == [1, 0, 0]


def test_a_step_sent_as_a_bare_string_still_works(kitchen):
    """The import review posts plain text and a browser holding the old bundle over a deploy will
    too, so the string form is not going away."""
    rid = _seed(kitchen)
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [], "steps": ["Whisk it.", {"heading": "THEN"}]})
    assert r.status_code == 200
    assert [(x["is_heading"], x["text"]) for x in _steps(kitchen, rid)] == \
           [(0, "Whisk it."), (1, "THEN")]


def test_a_step_object_is_still_checked_for_a_library_link_that_names_nothing(kitchen):
    """The [[key]] gate read `(step or {}).get("heading", "")`, so an object step's links would
    have gone unchecked — the same silent miss as the blank text above, on the validation side."""
    rid = _seed(kitchen)
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": None, "text": "Fold in the [[nonesuch]]."}]})
    assert r.status_code == 400
    assert "nonesuch" in r.get_json()["error"]


def test_an_object_step_may_carry_a_link_the_recipe_already_stands_on(kitchen):
    """The standing-link let-through has to reach the object form too, or the five recipes migration
    046 stranded become unsaveable again the moment the client sends objects."""
    rid = _seed(kitchen)
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_steps SET text='Fold in the [[gone_away]].' WHERE recipe_id=? "
                  "AND is_heading=0", (rid,))
        c.commit()
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": None, "text": "Fold in the [[gone_away]]."}]})
    assert r.status_code == 200


# --------------------------------------------------------------------------------------------- #
# Option C, commit 2: the save updates in place, so a row id is permanent
# --------------------------------------------------------------------------------------------- #
def _ids(kitchen, rid):
    return [r["id"] for r in _rows(kitchen, rid)]


def _step_ids(kitchen, rid):
    return [x["id"] for x in _steps(kitchen, rid)]


def _drop_id(entries, i):
    """The fixture's entries with entry `i` arriving WITHOUT an id — an older client's payload, or
    a row the editor added. The stored row still has its id."""
    out = copy.deepcopy(entries)
    out[i]["payload"].pop("id", None)
    return out


def test_a_no_edit_save_keeps_every_row_id(kitchen):
    rid = _seed(kitchen)
    before, before_steps = _ids(kitchen, rid), _step_ids(kitchen, rid)
    assert _save(kitchen, rid).status_code == 200
    assert _ids(kitchen, rid) == before
    assert _step_ids(kitchen, rid) == before_steps


def test_a_reorder_keeps_every_id_and_only_moves_the_positions(kitchen):
    """The marks come later (commit 4). What this pins is that a drag is not a delete and an
    insert: every row is the same row afterwards, at a new position."""
    rid = _seed(kitchen)
    before = {r["id"]: r["raw_text"] for r in _rows(kitchen, rid)}

    rows = copy.deepcopy(FIX["rows"])
    rows[1], rows[5] = rows[5], rows[1]
    rows.append(rows.pop(2))                                  # and one moved to the end
    steps = copy.deepcopy(FIX["steps"])
    steps[1], steps[2] = steps[2], steps[1]
    assert _save(kitchen, rid, rows=rows, steps=steps).status_code == 200

    after = {r["id"]: r["raw_text"] for r in _rows(kitchen, rid)}
    assert after == before                                    # same ids, same lines on them
    assert [r["position"] for r in _rows(kitchen, rid)] == list(range(len(FIX["rows"])))
    assert [x["text"] for x in _steps(kitchen, rid)] == \
           [FIX["steps"][i]["row"]["text"] for i in (0, 2, 1)]
    assert sorted(_step_ids(kitchen, rid)) == sorted(x["row"]["id"] for x in FIX["steps"])


def test_the_duplicate_case_can_no_longer_swap(kitchen):
    """⚠️ THE RECORDED ROADMAP C-CASE, closed by construction.

    The fixture's two water rows are told apart only by their amount, and they carry DIFFERENT link
    rules. Edit the first one's amount to the second one's and the carry key collides: the exact
    tier finds one stored row for ("2 tbsp", "water"), line 0 claims it and takes its link, line 1
    falls to the name tier and takes the other's. Each line keeps a real link to a real row and the
    two are swapped, which no count and no byte-comparison of the recipe can see. An id cannot
    collide with anything, so each line stays on its own row."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[5]["payload"]["quantity"] = "2"                      # was 3 tbsp, now identical to rows[6]
    assert _save(kitchen, rid, rows=rows).status_code == 200

    water = [r for r in _rows(kitchen, rid) if r["raw_text"] == "water"]
    assert [r["id"] for r in water] == [9006, 9007]            # their own rows, in place
    assert [r["link_rule"] for r in water] == ["exact", "form_strip:cold"]   # NOT swapped
    assert [r["qty"] for r in water] == ["2 tbsp", "2 tbsp"]


def test_the_same_duplicate_case_DOES_swap_without_ids(kitchen):
    """The other half of the proof. Strip the ids and the identical payload swaps the two rows'
    links, which is what every save did before commit 2 and what the fallback still does when a
    client cannot tell the server which row is which."""
    rows = _stripped(FIX["rows"])
    rid = _seed(kitchen, rows=rows, name="Round Trip, No Ids")
    rows[5]["payload"]["quantity"] = "2"
    assert _save(kitchen, rid, rows=rows, name="Round Trip, No Ids").status_code == 200

    water = [r for r in _rows(kitchen, rid) if r["raw_text"] == "water"]
    assert [r["link_rule"] for r in water] == ["form_strip:cold", "exact"]   # swapped


def test_an_id_less_line_still_falls_back_to_the_carry_and_keeps_its_row(kitchen):
    """A row arriving with no id is matched the old way, and the row it matches is UPDATED rather
    than replaced, so even the fallback preserves the id."""
    rid = _seed(kitchen)
    assert _save(kitchen, rid, rows=_drop_id(FIX["rows"], 3)).status_code == 200
    row = [r for r in _rows(kitchen, rid) if r["raw_text"] == "kosher salt"][0]
    assert row["id"] == 9004                                   # the same row, not a new one
    assert row["grams"] == 6.0 and row["catalog_id"] == "Q4116639"
    assert row["qty"] == "1 teaspoon"                          # the stored spelling, carried


def test_the_carry_is_built_over_only_what_the_id_pass_left(kitchen):
    """⚠️ THE ONE LINE THAT WOULD HAVE MADE COMMIT 2 A DATA-LOSS BUG.

    Line 0 claims stored row 9006 by id. Line 1 arrives with NO id and a new amount, so its exact
    key misses and it falls to the name tier, whose "water" bucket is [9006, 9007] in order. Built
    over ALL the stored rows, the name tier hands it 9006 — the row line 0 is already writing — and
    both lines update one row. Built over the leftovers, 9006 is not in the bucket at all and line 1
    correctly gets 9007."""
    rid = _seed(kitchen)
    rows = _drop_id(FIX["rows"], 6)
    rows[6]["payload"]["quantity"] = "5"                       # miss the exact tier on purpose
    assert _save(kitchen, rid, rows=rows).status_code == 200

    water = [r for r in _rows(kitchen, rid) if r["raw_text"] == "water"]
    assert len(water) == 2                                     # neither line was lost
    assert [r["id"] for r in water] == [9006, 9007]
    assert [r["qty"] for r in water] == ["3 tbsp", "5 tbsp"]
    assert [r["link_rule"] for r in water] == ["exact", "form_strip:cold"]


def test_a_row_id_from_another_recipe_is_refused(kitchen):
    """⚠️ REFUSED, NOT IGNORED. Ignoring it would write the line as a new row, which reads like
    success and loses whatever the client thought it was editing."""
    # ⚠️ THE OTHER RECIPE TAKES ITS IDS FROM THE SEQUENCE, not the fixture's hand-written ones,
    #    or the two recipes would collide on the same primary keys.
    other = _seed(kitchen, rows=_stripped(FIX["rows"]), steps=_stripped(FIX["steps"]),
                  name="Someone Else")
    rid = _seed(kitchen, name="Round Trip")
    before, before_steps = _rows(kitchen, rid), _steps(kitchen, rid)

    stolen = _rows(kitchen, other)[0]["id"]
    rows = copy.deepcopy(FIX["rows"])
    rows[1]["payload"]["id"] = stolen
    r = _save(kitchen, rid, rows=rows)
    assert r.status_code == 400
    assert str(stolen) in r.get_json()["error"]
    assert _rows(kitchen, rid) == before                       # and nothing was written
    assert _steps(kitchen, rid) == before_steps


def test_a_step_id_from_another_recipe_is_refused(kitchen):
    other = _seed(kitchen, rows=_stripped(FIX["rows"]), steps=_stripped(FIX["steps"]),
                  name="Someone Else")
    rid = _seed(kitchen, name="Round Trip")
    steps = copy.deepcopy(FIX["steps"])
    steps[1]["payload"]["id"] = _steps(kitchen, other)[0]["id"]
    assert _save(kitchen, rid, steps=steps).status_code == 400


def test_a_row_id_the_payload_uses_twice_is_refused(kitchen):
    """Two lines claiming one row means the second update overwrites the first and one line goes."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[6]["payload"]["id"] = rows[5]["payload"]["id"]
    r = _save(kitchen, rid, rows=rows)
    assert r.status_code == 400
    assert "twice" in r.get_json()["error"]


def test_a_row_id_that_is_not_a_whole_number_is_refused(kitchen):
    rid = _seed(kitchen)
    for bad in ("9006", 9006.5, True, [9006]):
        rows = copy.deepcopy(FIX["rows"])
        rows[5]["payload"]["id"] = bad
        assert _save(kitchen, rid, rows=rows).status_code == 400, f"accepted {bad!r}"


def test_a_deleted_line_is_deleted_and_the_survivors_keep_their_ids(kitchen):
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    del rows[4]                                                # the note row
    assert _save(kitchen, rid, rows=rows).status_code == 200
    assert _ids(kitchen, rid) == [9001, 9002, 9003, 9004, 9006, 9007, 9008, 9009, 9010, 9011]
    assert not [r for r in _rows(kitchen, rid) if r["label"] == "soy sauce"]


def test_a_deleted_step_is_deleted_and_the_survivors_keep_their_ids(kitchen):
    """The one that matters for the plan-ahead wait: a wait pointing at a step by id must see that
    step's id unchanged when a DIFFERENT step is removed."""
    rid = _seed(kitchen)
    steps = copy.deepcopy(FIX["steps"])
    del steps[1]
    assert _save(kitchen, rid, steps=steps).status_code == 200
    assert _step_ids(kitchen, rid) == [9101, 9103]
    assert [x["position"] for x in _steps(kitchen, rid)] == [0, 1]


def test_a_new_line_gets_a_new_id_and_takes_nobody_elses(kitchen):
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows.insert(3, {"shape": "new", "row": {}, "payload":
                    {"id": None, "quantity": "1", "unit": "pinch", "text": "saffron", "note": ""}})
    assert _save(kitchen, rid, rows=rows).status_code == 200
    got = _rows(kitchen, rid)
    fresh = [r for r in got if r["raw_text"] == "saffron"][0]
    assert fresh["id"] not in {r["row"]["id"] for r in FIX["rows"]}
    assert fresh["catalog_id"] is None
    assert [r["id"] for r in got if r["raw_text"] != "saffron"] == \
           [r["row"]["id"] for r in FIX["rows"]]


def test_a_renamed_line_keeps_its_row_and_loses_its_link(kitchen):
    """The rename rule as it stands (ROADMAP holds the re-match-on-save follow-up). The id is the
    ROW's identity, so it survives; the link belongs to the LINE, so it does not."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[2]["payload"]["text"] = "cold-pressed rapeseed oil"
    assert _save(kitchen, rid, rows=rows).status_code == 200
    row = [r for r in _rows(kitchen, rid) if r["id"] == 9003][0]
    assert row["label"] == "cold-pressed rapeseed oil"
    assert row["raw_text"] == "cold-pressed rapeseed oil"
    assert row["catalog_id"] is None and row["link_rule"] is None


def test_a_line_toggled_to_a_heading_keeps_its_id_and_drops_its_amount(kitchen):
    """⚠️ THE REASON ONE BUILDER WRITES BOTH THE INSERT AND THE UPDATE. An UPDATE that only set the
    heading's own columns would leave the amount, the weight and all four linkage columns sitting
    on a heading row, where an insert had always left them NULL."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = {"shape": "toggled", "row": {}, "payload": {"id": 9004, "heading": "FOR THE BRINE"}}
    assert _save(kitchen, rid, rows=rows).status_code == 200
    row = [r for r in _rows(kitchen, rid) if r["id"] == 9004][0]
    assert row["is_heading"] == 1 and row["raw_text"] == "FOR THE BRINE"
    for col in ("qty", "quantity", "unit", "label", "grams", "secondary_measure",
                "catalog_id", "link_confidence", "link_rule", "link_matched"):
        assert row[col] is None, f"{col} survived the toggle to a heading"


def test_a_step_toggled_to_a_heading_keeps_its_id(kitchen):
    rid = _seed(kitchen)
    steps = copy.deepcopy(FIX["steps"])
    steps[1]["payload"] = {"id": 9102, "heading": "THEN COOK"}
    assert _save(kitchen, rid, steps=steps).status_code == 200
    row = [x for x in _steps(kitchen, rid) if x["id"] == 9102][0]
    assert row["is_heading"] == 1 and row["text"] == "THEN COOK"


def test_an_older_client_that_sends_no_ids_at_all_still_saves(kitchen):
    """Every row falls back, every step is written as a new row — which is exactly what every save
    did before commit 2. The content has to come out identical."""
    rows, steps = _stripped(FIX["rows"]), _stripped(FIX["steps"])
    rid = _seed(kitchen, rows=rows, steps=steps, name="Round Trip, No Ids")
    before = _strip_ids(_rows(kitchen, rid))
    assert _save(kitchen, rid, rows=rows, steps=steps, name="Round Trip, No Ids").status_code == 200
    assert _strip_ids(_rows(kitchen, rid)) == before
    assert [x["text"] for x in _steps(kitchen, rid)] == [x["row"]["text"] for x in FIX["steps"]]
