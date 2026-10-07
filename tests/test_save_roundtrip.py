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
        "link_matched", "heading")

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
                      # .get: the fixture rows are LINES, so they carry no `heading` (052)
                      (row.get("id"), rid, *[row.get(k) for k in COLS]))
        for s in steps:
            st = s["row"]
            # heading_level defaults to 1, so the fixture's level-1 and its non-heading rows can
            # leave the key out and still seed the state the column actually holds.
            c.execute("INSERT INTO recipe_steps "
                      "(id, recipe_id, position, is_heading, heading_level, text) "
                      "VALUES (?,?,?,?,?,?)",
                      (st.get("id"), rid, st["position"], st["is_heading"],
                       st.get("heading_level", 1), st["text"]))
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
            "SELECT id, position, is_heading, heading_level, text FROM recipe_steps "
            "WHERE recipe_id=? ORDER BY position, id", (rid,))]


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
    # ⚠️ DERIVED FROM THE FIXTURE, NOT RESTATED. This read [1, 0, 0] and broke the moment migration
    #    059 added three step shapes to the fixture, which is the second time a literal tally in a
    #    test has gone red on a correct addition. The fixture is the source of truth for the shapes
    #    the save must survive, so the expectation reads it.
    assert [x["is_heading"] for x in _steps(kitchen, rid)] == \
           [x["row"]["is_heading"] for x in FIX["steps"]]
    assert [x["heading_level"] for x in _steps(kitchen, rid)] == \
           [(x["row"].get("heading_level", 1) if x["row"]["is_heading"] else 1)
            for x in FIX["steps"]], "a level is stored on a heading and never on an ordinary step"


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
    order = [0, 2, 1] + list(range(3, len(FIX["steps"])))     # the swap above, then the rest as-is
    assert [x["text"] for x in _steps(kitchen, rid)] == \
           [FIX["steps"][i]["row"]["text"] for i in order]
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
    survivors = [x["row"]["id"] for i, x in enumerate(FIX["steps"]) if i != 1]
    assert _step_ids(kitchen, rid) == survivors
    assert [x["position"] for x in _steps(kitchen, rid)] == list(range(len(survivors)))


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


# --------------------------------------------------------------------------------------------- #
# Converting a line to a heading, and back (migration 052)
#
# ⚠️ THIS SECTION ONCE ASSERTED THE OPPOSITE, and the opposite was a data-loss bug. The save used to
# NULL a heading row's amount, weight, note and four linkage columns on purpose, so that a heading
# could not carry stale numbers. The editor holds them in memory, so converting back and forth
# looked lossless until you SAVED while it was a heading. After that the line was gone.
#
# Nothing needed to be hidden in the first place: the reading view renders a heading as its title
# alone and the diff compares headings on the title alone. What was missing was somewhere to put
# the title, which migration 052 added.
# --------------------------------------------------------------------------------------------- #
def _heading_payload(rid_, title):
    return {"shape": "toggled", "row": {}, "payload": {"id": rid_, "heading": title}}


def _as_line(x):
    """One SERVED row, as the client's ingToPayload would send it if it were a line. The linked and
    unlinked branches really are different keys — `item` + `label` against `text` — and sending the
    wrong one drops the library link, which is the editor's rename rule doing its job."""
    base = {"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
            "note": x["note"] or ""}
    if x["ingredient_id"]:
        return {**base, "item": x["ingredient_id"], "label": x["label"] or x["raw_text"] or ""}
    return {**base, "text": x["label"] or x["raw_text"] or ""}


def _as_payload(x):
    """One SERVED row as ingToPayload sends it, heading or line. A heading's title resolves the way
    headingText() does: `heading` when set, else raw_text."""
    if x["is_heading"]:
        title = x["heading"] if x.get("heading") is not None else (x["raw_text"] or "")
        return {"id": x["id"], "heading": title}
    return _as_line(x)


def test_a_line_toggled_to_a_heading_keeps_everything_it_was_carrying(kitchen):
    rid = _seed(kitchen)
    before = [r for r in _rows(kitchen, rid) if r["id"] == 9004][0]
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "FOR THE BRINE")
    assert _save(kitchen, rid, rows=rows).status_code == 200

    row = [r for r in _rows(kitchen, rid) if r["id"] == 9004][0]
    assert row["is_heading"] == 1
    assert row["heading"] == "FOR THE BRINE"          # the title, in its own column
    assert row["raw_text"] == before["raw_text"]      # the SOURCE LINE, untouched
    for col in ("qty", "quantity", "unit", "label", "note", "grams", "secondary_measure",
                "catalog_id", "link_confidence", "link_rule", "link_matched"):
        assert row[col] == before[col], f"{col} was destroyed by the toggle to a heading"


def test_convert_save_reload_convert_back_save_is_byte_identical(kitchen):
    """⚠️ ANDY'S OWN TEST, and the one the bug failed. Convert a line to a heading, SAVE, read the
    recipe back the way a reload does, convert it back from what the GET served, and save again.
    Every column of every row has to be where it started, ids included."""
    rid = _seed(kitchen)
    _save(kitchen, rid)                                # let the heading sync settle
    start, start_steps = _rows(kitchen, rid), _steps(kitchen, rid)

    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "FOR THE BRINE")
    assert _save(kitchen, rid, rows=rows).status_code == 200

    # the reload: rebuild the payload from what the API serves, the way the editor's draft does
    served = kitchen.client.get(f"/api/recipes/{rid}").get_json()["ingredients"]
    back = [{"shape": "reloaded", "row": {},
             "payload": _as_line(x) if x["id"] == 9004 else _as_payload(x)}
            for x in served]                           # 9004: toggleRowType heading -> line
    assert _save(kitchen, rid, rows=back).status_code == 200

    assert _rows(kitchen, rid) == start                # ids, amounts, links, weights, raw_text
    assert _steps(kitchen, rid) == start_steps


def test_a_headings_hidden_values_never_reach_the_snapshot_as_its_text(kitchen):
    """The blob a reader diffs against carries the TITLE in raw_text for a heading row, so the
    annotation for a converted line reads as a heading called "FOR THE BRINE" and never as the
    dormant source line sitting in the same row."""
    import json
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "FOR THE BRINE")
    _save(kitchen, rid, rows=rows)
    kitchen.client.post(f"/api/recipes/{rid}/cooked-and-rated", json={"rating": 4})
    with kitchen.conn() as c:
        blob = json.loads(c.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='cook' "
            "ORDER BY id DESC LIMIT 1", (rid,)).fetchone()[0])
    head = [r for r in blob["ingredients"] if r["is_heading"] and r["position"] == 3][0]
    assert head["raw_text"] == "FOR THE BRINE"        # the title, not the dormant source line
    assert "heading" not in head                       # and the extra key never enters the blob


def test_renaming_a_converted_row_still_clears_its_link(kitchen):
    """The normal rename rule survives the trip through a heading. The id makes it the same ROW, so
    it keeps its id, and the new name makes it a new LINE, so the library link goes."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "FOR THE BRINE")
    _save(kitchen, rid, rows=rows)

    back = copy.deepcopy(FIX["rows"])
    back[3]["payload"] = {"id": 9004, "quantity": "1", "unit": "tsp",
                          "text": "flaky sea salt", "note": ""}       # was "kosher salt"
    assert _save(kitchen, rid, rows=back).status_code == 200
    row = [r for r in _rows(kitchen, rid) if r["id"] == 9004][0]
    assert row["is_heading"] == 0 and row["heading"] is None
    assert row["label"] == "flaky sea salt"
    assert row["raw_text"] == "flaky sea salt"        # a renamed line IS its own source line
    assert row["catalog_id"] is None and row["link_rule"] is None


def test_a_row_born_as_a_heading_has_nothing_dormant(kitchen):
    """Added as a heading, so there is nothing to keep. raw_text carries the title the way every
    pre-052 heading row does, so a reader that falls back to raw_text still reads it right."""
    rid = _seed(kitchen)
    rows = copy.deepcopy(FIX["rows"])
    rows.insert(4, {"shape": "new", "row": {}, "payload": {"id": None, "heading": "FOR THE GLAZE"}})
    assert _save(kitchen, rid, rows=rows).status_code == 200
    row = [r for r in _rows(kitchen, rid) if r["position"] == 4][0]
    assert row["is_heading"] == 1
    # ⚠️ heading IS NULL, and that is the rule: the title column is only used when raw_text is not
    # already the title. It keeps all 223 pre-052 heading rows on live untouched by their first save.
    assert row["heading"] is None and row["raw_text"] == "FOR THE GLAZE"
    for col in ("qty", "quantity", "unit", "label", "note", "grams", "catalog_id"):
        assert row[col] is None, f"a born heading came out carrying {col}"


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


# --------------------------------------------------------------------------------------------- #
# The heading sync must write a converted heading's TITLE into the baseline, not its source line
#
# ⚠️ A REGRESSION THE 052 WORK INTRODUCED. snapshot_headsync._reinterleave built its rows with a
# plain field copy and so skipped the projection content_blob applies. That was harmless while a
# heading's title WAS its raw_text, and wrong the moment a converted heading kept the line's source
# text there: the sync wrote "25 g (0.9 oz) guajillo chillies, dried" into the BASELINE as a section
# title, and the recipe page then reported an unrelated heading as renamed. Both builders now come
# through snapshot_serialize.snapshot_ing_row.
# --------------------------------------------------------------------------------------------- #
def _baseline(kitchen, rid):
    import json
    with kitchen.conn() as c:
        return json.loads(c.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'",
            (rid,)).fetchone()[0])


def _settle(kitchen, rid):
    """Rewrite the reason='original' baseline from the recipe's CURRENT rows, so the fixture recipe
    reads as unedited and _annotations() is []. 

    ⚠️ ONLY EVER IN A TEST. _seed writes the fixture's rows in by direct SQL AFTER the POST that
    created the recipe, so the baseline captured at birth holds the placeholder state and every
    fixture row reads as 'added' forever. Declaring the recipe born in its current state is the
    right thing HERE and a catastrophe in production, which is what sync_original_heading_layout's
    docstring spends its length on: it would erase every annotation the recipe should have had."""
    import app as app_module
    with app_module.orm_session() as s:
        blob = app_module.serialize_recipe_content(s, rid)
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (blob, rid))
        c.commit()


def test_the_baseline_never_gets_a_dormant_source_line_as_a_heading_title(kitchen):
    """⚠️ THE REGRESSION 052 INTRODUCED. The sync built its rows with a plain field copy, skipping
    the projection content_blob applies, so a converted heading's raw_text — which since 052 is the
    LINE's source text — went into the baseline as a section title."""
    rid = _seed(kitchen)
    _save(kitchen, rid)                                    # let the heading sync settle
    _settle(kitchen, rid)
    source_line = [r for r in _rows(kitchen, rid) if r["id"] == 9002][0]["raw_text"]
    assert source_line == "25 g (0.9 oz) guajillo chillies, dried"

    rows = copy.deepcopy(FIX["rows"])
    rows[1] = _heading_payload(9002, "FOR THE CHILLIES")
    assert _save(kitchen, rid, rows=rows).status_code == 200

    titles = [r["raw_text"] for r in _baseline(kitchen, rid)["ingredients"] if r["is_heading"]]
    assert source_line not in titles, "the baseline got the dormant SOURCE LINE as a heading title"
    # And the converted row is not copied into the baseline as a heading at all: the baseline still
    # holds it as the content LINE it was at birth. See _reinterleave's key_of.
    assert titles == ["FOR THE SAUCE:"]
    lines = [r["raw_text"] for r in _baseline(kitchen, rid)["ingredients"] if not r["is_heading"]]
    assert source_line in lines


def test_converting_to_a_heading_and_back_leaves_no_marks_either_way(kitchen):
    """⚠️ ZERO MARKS IN BOTH DIRECTIONS, which is the whole of the fix. A converted row shows the
    same words on the page in a different style, and heading changes carry no annotation by existing
    ruling, so nothing about the recipe's content moved."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    _settle(kitchen, rid)
    assert _annotations(kitchen, rid) == []
    start = _rows(kitchen, rid)

    rows = copy.deepcopy(FIX["rows"])
    # ⚠️ THE TITLE IS THE ROW'S OWN NAME, because that is what toggleRowType seeds it with. A user
    #    who also RETYPES the title has taken that name off the page, and the removal is then
    #    reported on purpose — test_a_renamed_conversion_is_still_reported below.
    rows[3] = _heading_payload(9004, "kosher salt")
    assert _save(kitchen, rid, rows=rows).status_code == 200
    assert _annotations(kitchen, rid) == [], "converting to a heading left a mark"

    served = kitchen.client.get(f"/api/recipes/{rid}").get_json()["ingredients"]
    back = [{"shape": "back", "row": {},
             "payload": _as_line(x) if x["id"] == 9004 else _as_payload(x)} for x in served]
    assert _save(kitchen, rid, rows=back).status_code == 200
    assert _annotations(kitchen, rid) == [], "converting back left a mark"
    assert _rows(kitchen, rid) == start                    # byte-identical, ids included


def test_a_real_edit_alongside_a_conversion_still_marks(kitchen):
    """The suppression retires the converted row and nothing else."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    _settle(kitchen, rid)
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "kosher salt")         # convert one row
    rows[5]["payload"]["quantity"] = "9"                   # and really edit another
    assert _save(kitchen, rid, rows=rows).status_code == 200
    got = _annotations(kitchen, rid)
    assert len(got) == 1, got
    assert got[0]["kind"] == "ingredient" and got[0]["field"] == "amount"
    assert got[0]["to"] == "9 tbsp"


def test_a_renamed_conversion_emits_nothing(kitchen):
    """⚠️ THIS TEST USED TO ASSERT THE OPPOSITE, AND THE INVERSION IS THE DECISION. Convert a line AND
    retype the heading: before the baseline carried row ids the key was the row's NAME, so there was
    nothing left to recognise and the removal was the honest report. The id recognises the row however
    it is retitled, and the standing ruling on headings is that a kind change carries no annotation, so
    the honest report is now nothing at all. Same row, same words on the page, different style.

    The two halves that make it work are in different modules, which is why this test is at the seam
    rather than in the pure suite: snapshot_diff.suppress_kind_changes retires the pair by id, and
    snapshot_headsync._reinterleave declines to copy the new heading into the baseline as a section."""
    rid = _seed(kitchen)
    _save(kitchen, rid)
    _settle(kitchen, rid)
    rows = copy.deepcopy(FIX["rows"])
    rows[3] = _heading_payload(9004, "FOR THE BRINE")
    assert _save(kitchen, rid, rows=rows).status_code == 200
    assert _annotations(kitchen, rid) == []
    # and again, to prove it is stable rather than merely quiet on the first save
    assert _save(kitchen, rid, rows=rows).status_code == 200
    assert _annotations(kitchen, rid) == []


# ---- option C commit 3: the baseline carries row ids ---------------------------------------------

def _baseline(kitchen, rid):
    with kitchen.conn() as c:
        return json.loads(c.execute(
            "SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'",
            (rid,)).fetchone()["content"])


def test_the_birth_baseline_records_every_row_id(kitchen):
    """⚠️ A BASELINE ROW AND ITS LIVE ROW USED TO BE CONNECTED BY NOTHING BUT THEIR TEXT. Option C
    gave each row an id that survives a save, and the baseline records it, so a renamed row is still
    recognisable as the row it always was. Both tables, headings included."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Id Baseline",
        "ingredients": [{"heading": "FOR THE BASE"}, {"qty": "2", "text": "eggs"}],
        "steps": [{"heading": "PREP"}, "Beat the eggs."],
    }).get_json()["id"]
    doc = _baseline(kitchen, rid)
    with kitchen.conn() as c:
        live_ing = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_ingredients WHERE recipe_id=? ORDER BY position, id", (rid,))]
        live_step = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id=? ORDER BY position, id", (rid,))]
    assert [r["id"] for r in doc["ingredients"]] == live_ing
    assert [r["id"] for r in doc["steps"]] == live_step
    assert None not in live_ing + live_step


def test_a_no_edit_save_leaves_the_baseline_byte_identical_including_ids(kitchen):
    """The byte-equal short-circuit is what keeps an unedited recipe's "your changes" empty without
    running the diff. Adding ids to the format would end it for every recipe at once if a save
    churned them, so this is the test that the ids are stable across a save, not just present."""
    rid = _seed(kitchen, name="Id Stable")
    _settle(kitchen, rid)
    before = _baseline(kitchen, rid)
    assert _save(kitchen, rid, name="Id Stable").status_code == 200
    import app as app_module
    with app_module.orm_session() as s:
        current = app_module.serialize_recipe_content(s, rid)
    assert json.loads(current) == before, "a no-edit save must leave the ids where they were"
    assert _annotations(kitchen, rid) == []


def test_an_id_less_step_payload_keeps_the_step_row_ids(kitchen):
    """⚠️ THE STRING WIRE FORM IS STILL LEGAL, AND IT USED TO RECREATE EVERY STEP ROW. A step carries
    no columns, so there was nothing to preserve across a rewrite — until the baseline started
    recording step ids, at which point an id-less save cost the recipe its short-circuit for good.
    An id-less step whose kind and text match a stored row now updates THAT row."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Id Less Steps", "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": [{"heading": "PREP"}, "Beat the eggs.", "Fold in the flour."],
    }).get_json()["id"]
    with kitchen.conn() as c:
        before = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id=? ORDER BY position", (rid,))]
    # the same steps again, in the id-less string/heading form the client no longer sends
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Id Less Steps", "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": [{"heading": "PREP"}, "Beat the eggs.", "Fold in the flour."],
    }).status_code == 200
    with kitchen.conn() as c:
        after = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id=? ORDER BY position", (rid,))]
    assert after == before
    assert _annotations(kitchen, rid) == []


def test_an_id_less_step_whose_text_changed_is_still_a_new_row(kitchen):
    """ONE TIER, EXACT. The carry is not a similarity match: a reworded step arriving with no id is a
    new row exactly as it was before, so the only behaviour that changed is the unambiguous one."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Id Less Edit", "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": ["Beat the eggs."],
    }).get_json()["id"]
    with kitchen.conn() as c:
        before = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id=?", (rid,))]
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Id Less Edit", "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": ["Beat the eggs well."],
    }).status_code == 200
    with kitchen.conn() as c:
        after = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_steps WHERE recipe_id=?", (rid,))]
    assert after != before


# ---- option C commit 4: a no-edit save writes nothing to the recipe row ---------------------------

# ⚠️ `notes` LEFT THIS TUPLE WITH THE COLUMN. It was a header field until migration 060 made a note
# a row, a derived copy until migration 063 dropped it, and the keep rule below governs the other
# nine exactly as it did. A note's own round-trip is tested against the ROWS, in test_note_api.py
# and test_save_omitted_lists.py.
HEADER = ("author", "source_url", "category", "servings", "prep_time", "cook_time",
          "total_time", "descr", "image")


def _header(kitchen, rid):
    with kitchen.conn() as c:
        return dict(c.execute(f"SELECT {','.join(HEADER)} FROM recipes WHERE id=?", (rid,)).fetchone())


def test_a_no_edit_save_leaves_a_null_header_field_null(kitchen):
    """⚠️ THE DEFECT THIS CLOSES COST A RECIPE ITS SHORT-CIRCUIT FOR GOOD. The client sends every header
    field as a trimmed string, so a column stored as NULL came back as "" and the save wrote it.
    Measured on live: 10 columns on 270 of 300 recipes, for a save that changed nothing. Nothing looked
    wrong, and brioche-bread's serialization stopped matching its baseline byte for byte, so its "your
    changes" ran the full diff on every page view from then on."""
    rid = _seed(kitchen, name="Null Header")
    with kitchen.conn() as c:
        c.execute(f"UPDATE recipes SET {', '.join(f'{f}=NULL' for f in HEADER)} WHERE id=?", (rid,))
        c.commit()
    before = _header(kitchen, rid)
    assert set(before.values()) == {None}
    # the client's own shape: every header field present, as a trimmed string
    payload = {"name": "Null Header", **{f: "" for f in HEADER},
               "ingredients": [r["payload"] for r in FIX["rows"]],
               "steps": [s["payload"] for s in FIX["steps"]]}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=payload).status_code == 200
    assert _header(kitchen, rid) == before, "a save with no edits must write nothing"


def test_a_header_field_holding_empty_string_is_left_alone_too(kitchen):
    """The rule keeps what is STORED, in either direction, so a column already holding "" is not
    quietly converted to NULL either. The point is that nothing is written, not that NULL wins."""
    rid = _seed(kitchen, name="Empty Header")
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET descr='', author=NULL WHERE id=?", (rid,))
        c.commit()
    payload = {"name": "Empty Header", "descr": "", "author": "",
               "ingredients": [r["payload"] for r in FIX["rows"]],
               "steps": [s["payload"] for s in FIX["steps"]]}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=payload).status_code == 200
    got = _header(kitchen, rid)
    assert got["descr"] == "" and got["author"] is None


def test_a_real_header_edit_is_still_written(kitchen):
    """The control. Keeping an unchanged field must not keep a changed one."""
    rid = _seed(kitchen, name="Real Header")
    payload = {"name": "Real Header", "descr": "A rich, eggy loaf.", "servings": "8",
               "ingredients": [r["payload"] for r in FIX["rows"]],
               "steps": [s["payload"] for s in FIX["steps"]]}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=payload).status_code == 200
    got = _header(kitchen, rid)
    assert got["descr"] == "A rich, eggy loaf." and got["servings"] == "8"


def test_a_whitespace_only_header_edit_is_written_but_marks_nothing(kitchen):
    """⚠️ THE TWO HALVES PULL OPPOSITE WAYS ON PURPOSE. The keep rule is the WEAKEST one that fixes the
    defect: null and empty are the same, and whitespace is NOT folded, because a user who re-wrapped a
    headnote made a real edit and a keep rule that collapsed whitespace would discard it. The DIFF folds
    whitespace, so no mark appears for it. Compare loosely, write faithfully."""
    rid = _seed(kitchen, name="Space Header")
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET descr='A rich loaf.' WHERE id=?", (rid,))
        c.commit()
    _settle(kitchen, rid)
    payload = {"name": "Space Header", "descr": "A rich  loaf. ",
               "ingredients": [r["payload"] for r in FIX["rows"]],
               "steps": [s["payload"] for s in FIX["steps"]]}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=payload).status_code == 200
    assert _header(kitchen, rid)["descr"] == "A rich  loaf. ", "the user's edit is stored as typed"
    assert _annotations(kitchen, rid) == [], "and the cook sees no change, so there is no mark"


# ---- a converted heading KEEPS its link markup (review fix 2) ------------------------------------
# ⚠️ THE LOSSLESS HALF OF THE FIX, AND THE REASON IT WAS NOT DONE IN _step_parts. The brackets must
# never print, and there were two ways to get there. Stripping the markup on the way in (the server
# applying move_link_out_of_label the way the importer does when it LIFTS a lead-in label) would
# spend the link to buy it: the step row menu converts a WHOLE step, the cook can convert it
# straight back, and nothing would bring the link back. So the markup is stored verbatim and the
# heading renderers show its words (showLinksAsWords, pinned in tests/js/step-editor.test.js). This
# file pins the other side of that contract: the save path does not touch it.

def _link_steps(kitchen, text="Wilt the [[egg_pasta]] in the pan."):
    rid = _seed(kitchen, rows=[], steps=[{"row": {"id": 9100, "position": 0, "is_heading": 0,
                                                  "text": text}}])
    return rid


def test_a_step_converted_to_a_heading_keeps_its_link_markup(kitchen):
    rid = _link_steps(kitchen)
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": 9100, "heading": "Wilt the [[egg_pasta]] in the pan.", "level": 1}]})
    assert r.status_code == 200, r.get_json()
    rows = _steps(kitchen, rid)
    assert [(x["is_heading"], x["text"]) for x in rows] == \
           [(1, "Wilt the [[egg_pasta]] in the pan.")], "the save rewrote a heading's text"


def test_converting_back_to_a_step_restores_a_working_link(kitchen):
    rid = _link_steps(kitchen)
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": 9100, "heading": "Wilt the [[egg_pasta]] in the pan.", "level": 1}]
    }).status_code == 200
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": 9100, "text": "Wilt the [[egg_pasta]] in the pan."}]
    }).status_code == 200
    rows = _steps(kitchen, rid)
    assert [(x["is_heading"], x["text"]) for x in rows] == \
           [(0, "Wilt the [[egg_pasta]] in the pan.")]


def test_a_heading_may_carry_a_link_the_recipe_already_stands_on(kitchen):
    """The standing-link let-through reads BOTH wire forms (_step_parts), so a conversion cannot be
    refused on a key the step it came from was already allowed to carry."""
    rid = _seed(kitchen, rows=[], steps=[{"row": {"id": 9101, "position": 0, "is_heading": 0,
                                                  "text": "Fold in the [[gone_away]]."}}])
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": 9101, "heading": "Fold in the [[gone_away]].", "level": 1}]})
    assert r.status_code == 200, r.get_json()


def test_a_heading_naming_a_link_that_exists_nowhere_is_still_refused(kitchen):
    """Keeping the markup must not open a hole in the gate: a NEW key in a heading names nothing and
    is refused, exactly as it is in a step."""
    rid = _link_steps(kitchen)
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip", "ingredients": [],
        "steps": [{"id": 9100, "heading": "Wilt the [[nonesuch]].", "level": 1}]})
    assert r.status_code == 400
    assert "nonesuch" in r.get_json()["error"]


# ---- the notes, through the client's OWN payload --------------------------------------------------
# ⚠️ WHY THEY ARE HERE AT ALL. notesPayload is a hand-written key list exactly like ingToPayload's,
# and `title` was left out of it. The server reads absent-means-KEEP on a row matched by id, so
# Edit mode's Save wrote the stored title back over the one the cook had just typed: every title
# change in that view lost, with a 200 and nothing on screen. Every PUT test for the title passed,
# because every one of them hand-built a payload WITH the key in it. That is this file's own
# header sentence, applied to a second builder nobody had added to the fixture.

NOTE_COLS = ("position", "kind", "title", "text", "step_id", "ingredient_row_id")


def _seed_notes(kitchen, rid, notes=None):
    """The fixture's note rows, written straight to the table beside the ingredients and steps."""
    notes = FIX["notes"] if notes is None else notes
    with kitchen.conn() as c:
        c.execute("DELETE FROM recipe_notes WHERE recipe_id=?", (rid,))
        for n in notes:
            row = n["row"]
            if row["id"] < 0:
                continue                      # a draft note has no stored row yet, by definition
            c.execute(f"INSERT INTO recipe_notes (id, recipe_id, {','.join(NOTE_COLS)}) "
                      f"VALUES (?,?,{','.join('?' * len(NOTE_COLS))})",
                      # ⚠️ THE DRAFT'S TITLE AND THE STORED ONE ARE NOT THE SAME VALUE. The
                      #    cleared-title fixture row holds "   ", which is what the Title box
                      #    actually contains after a cook empties it, and the column's own CHECK
                      #    refuses a blank string. So the STORED side is NULL and the builder is
                      #    what has to turn one into the other.
                      (row["id"], rid,
                       *[((row.get(k) or "").strip() or None) if k == "title" else row.get(k)
                         for k in NOTE_COLS]))
        c.commit()
    return [n for n in notes if n["row"]["id"] > 0]


def _stored_notes(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            f"SELECT id,{','.join(NOTE_COLS)} FROM recipe_notes WHERE recipe_id=? "
            f"ORDER BY position, id", (rid,))]


def _put_with_notes(kitchen, rid, note_payloads):
    """Edit mode's Save: the client's own ingredient, step and note payloads, together."""
    return kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Round Trip",
        "ingredients": [r["payload"] for r in FIX["rows"]],
        "steps": [s["payload"] for s in FIX["steps"]],
        "notes": note_payloads,
    })


def test_a_no_edit_save_keeps_every_note_title(kitchen):
    """The client's payload, sent back unchanged. Every title has to survive it."""
    rid = _seed(kitchen, name="Notes Round Trip")
    stored = _seed_notes(kitchen, rid)
    before = _stored_notes(kitchen, rid)
    assert [n["title"] for n in before] == ["Flour", None, None, "To Freeze the pie shell",
                                            "Shaping"], before
    assert before[2]["title"] is None, "the cleared-title row has to be stored as NULL"

    r = _put_with_notes(kitchen, rid, [n["payload"] for n in stored])
    assert r.status_code == 200, r.get_json()
    assert _stored_notes(kitchen, rid) == before, "a no-edit save moved a note row"


def test_the_clients_payload_can_change_a_title_and_can_clear_one(kitchen):
    """⚠️ THE DEFECT, STATED AS A TEST. This sends the payload notesPayload ACTUALLY builds, not a
    hand-written one, so a key missing from that builder fails here."""
    import copy
    rid = _seed(kitchen, name="Notes Retitled")
    stored = _seed_notes(kitchen, rid)
    payloads = copy.deepcopy([n["payload"] for n in stored])

    payloads[0]["title"] = "Bread flour"          # changed
    payloads[1]["title"] = "Resting"              # set, where there was none
    payloads[3]["title"] = None                   # cleared
    r = _put_with_notes(kitchen, rid, payloads)
    assert r.status_code == 200, r.get_json()

    got = {n["id"]: n["title"] for n in _stored_notes(kitchen, rid)}
    assert got[9201] == "Bread flour"
    assert got[9202] == "Resting"
    assert got[9204] is None
    assert got[9205] == "Shaping", "an untouched note's title moved"


def test_the_clients_payload_never_lets_a_blank_title_reach_the_column(kitchen):
    """The fixture's third note carries "   " in the draft, and the builder sends null for it."""
    rid = _seed(kitchen, name="Notes Blank")
    stored = _seed_notes(kitchen, rid)
    cleared = next(n for n in FIX["notes"] if "CLEARED" in n["shape"])
    assert cleared["payload"]["title"] is None, "the builder sent a blank string"
    r = _put_with_notes(kitchen, rid, [n["payload"] for n in stored])
    assert r.status_code == 200, r.get_json()
    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM recipe_notes WHERE title = ''").fetchone()[0] == 0


def test_the_notes_fixture_is_the_builders_output_and_carries_the_title_key(kitchen):
    """⚠️ A CHECK THAT READ NOTHING FAILS. If the fixture lost its notes section, every test above
    would pass over an empty list."""
    assert len(FIX["notes"]) >= 5, FIX.get("notes")
    assert all("title" in n["payload"] for n in FIX["notes"]), \
        "the key must be present on every note, because absent means KEEP on the server"
    assert any(n["payload"]["title"] for n in FIX["notes"])
    assert any(n["payload"]["title"] is None for n in FIX["notes"])
