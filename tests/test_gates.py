"""The three gates in scripts/gates/, run against real schemas.

⚠️ WHY THIS FILE EXISTS. These tools checked every corpus pass and the notes go-live from a session
scratchpad under /private/tmp, where nothing tested them and a macOS restart would have taken them.
The one behaviour most worth not losing is the refusal: a gate that passes because it found nothing
is worse than no gate, because it teaches everyone the check is green.

⚠️ NOT ONE TEST HERE OPENS THE LIVE DATABASE. Every fixture is built under tmp_path on the real
schema by migrate.py. tests/dbguard.py would raise anyway, and this file does not lean on that.
"""
import json
import pathlib
import sqlite3
import sys

import pytest

import dbguard  # noqa: F401
import harness  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "gates"))

import migrate                      # noqa: E402
import snapshot_serialize as ss     # noqa: E402

import compare as gcompare          # noqa: E402
import state as gstate              # noqa: E402
import tablediff as gtablediff      # noqa: E402


# ---- fixtures ------------------------------------------------------------------------------------

def _schema(path):
    """The real schema, plus the one user every baseline's user_id points at.

    ⚠️ WITHOUT THE USER ROW EVERY BASELINE IS A FOREIGN-KEY VIOLATION, and the gate reports
    foreign_key_violations, so the fixture would have failed its own integrity check. Found by
    running it."""
    migrate.DB = path
    migrate.migrate(verbose=False)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO users (id, email, password_hash, created_at) "
                "VALUES (1, 'gate@test.invalid', 'x', '2026-01-01T00:00:00Z')")
    con.commit()
    return con


def _recipe(con, rid, steps=("Mix it", "Bake it"), baseline=True, drift=None):
    """One recipe with steps, and a reason='original' baseline computed by the app's OWN serializer.

    `baseline=True` makes the recipe byte-equal to its baseline, which is what puts it in the
    short-circuit set. `drift` is text written into step 0 AFTER the baseline, which is how a
    recipe gets an annotation entry.
    """
    con.execute("INSERT INTO recipes (id, name, source) VALUES (?,?, 'app')", (rid, rid.title()))
    rows = []
    for i, text in enumerate(steps):
        cur = con.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, text) "
                          "VALUES (?,?,0,?)", (rid, i, text))
        rows.append({"id": cur.lastrowid, "position": i, "is_heading": 0, "text": text,
                     "heading_level": None})
    if baseline:
        blob = ss.content_blob({"id": rid, "name": rid.title()}, [], rows)
        con.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, reason, content, created_at) "
                    "VALUES (?,1,'original',?, '2026-01-01T00:00:00Z')", (rid, blob))
    if drift is not None:
        con.execute("UPDATE recipe_steps SET text = ? WHERE recipe_id = ? AND position = 0",
                    (drift, rid))
    con.commit()
    return rows


def _corpus(tmp_path, name="gate.db"):
    """Two byte-equal recipes and one that has drifted, which is a reading worth comparing."""
    db = tmp_path / name
    con = _schema(db)
    _recipe(con, "beans")
    _recipe(con, "biscuits")
    _recipe(con, "brownies", drift="Mix it well")
    con.close()
    return db


def _empty(tmp_path, name="empty.db"):
    db = tmp_path / name
    _schema(db).close()
    return db


# ---- state.py reads, and reads read-only ---------------------------------------------------------

def test_the_reading_names_the_byte_equal_set_and_the_annotation_set(tmp_path):
    st = gstate.read_state(_corpus(tmp_path))
    assert st["short_circuit"] == ["beans", "biscuits"], "a recipe matching its baseline is in"
    assert "brownies" not in st["short_circuit"], "a recipe that changed is out"
    assert list(st["annotations"]) == ["brownies"]
    assert st["annotation_entries"] >= 1 and st["annotation_recipes"] == 1
    assert st["integrity_check"] == "ok"
    assert st["foreign_key_violations"] == 0
    assert st["counts"]["recipes"] == 3


def test_the_reading_opens_the_database_read_only(tmp_path):
    """⚠️ READ-ONLY BY CONSTRUCTION, NOT BY INTENTION. mode=ro means SQLite refuses the write, so
    this holds for anything that opens a database through open_ro, including a future gate."""
    con = gstate.open_ro(_corpus(tmp_path))
    try:
        with pytest.raises(sqlite3.OperationalError) as e:
            con.execute("DELETE FROM recipes")
        assert "readonly" in str(e.value).lower()
    finally:
        con.close()


def test_the_reading_uses_the_app_s_own_serializer_rather_than_its_own_copy(tmp_path):
    """⚠️ ONE RULE, ONE FUNCTION. The scratchpad version projected the snapshot fields itself and
    drifted the moment notes left the blob, so every recipe differed from its baseline and the gate
    passed while comparing nothing. A recipe is byte-equal here only because content_blob says so."""
    db = _corpus(tmp_path)
    con = gstate.open_ro(db)
    try:
        stored = con.execute("SELECT content FROM recipe_snapshots WHERE recipe_id = 'beans' "
                             "AND reason = 'original'").fetchone()[0]
        assert gstate.current_blob(con, "beans") == stored
    finally:
        con.close()
    assert "notes" not in stored, "notes are not in the blob, so a reading must not emit them"


def test_a_table_the_database_does_not_have_reads_as_none_rather_than_raising(tmp_path):
    """A database older than a migration is a legitimate BEFORE side."""
    db = tmp_path / "old.db"
    con = _schema(db)
    con.execute("DROP TABLE recipe_note_step_refs")
    con.execute("DROP TABLE recipe_notes_original")
    con.commit()
    con.close()
    st = gstate.read_state(db)
    assert st["counts"]["recipe_note_step_refs"] is None
    assert st["counts"]["recipe_notes_original"] is None
    assert st["counts"]["recipes"] == 0


def test_the_reading_round_trips_through_the_command_line(tmp_path, capsys):
    out = tmp_path / "reading.json"
    assert gstate.main(["--db", str(_corpus(tmp_path)), "--out", str(out)]) == 0
    st = json.loads(out.read_text())
    assert st["short_circuit"] == ["beans", "biscuits"]
    assert "read-only" in capsys.readouterr().out


# ---- compare.py: the empty-reading refusal -------------------------------------------------------

def test_two_empty_readings_agree_and_are_still_refused(tmp_path):
    """⚠️ THE ONE THAT MATTERS. Two empty readings are byte-identical, so every comparison of them
    passes. A reading taken against the wrong path is empty rather than wrong-looking."""
    empty = gstate.read_state(_empty(tmp_path))
    assert empty["short_circuit"] == [] and empty["annotations"] == {}
    diffs = gcompare.differences(empty, empty)
    assert diffs, "a gate with nothing to compare must FAIL, not pass"
    assert any("nothing to compare" in d for d in diffs)
    assert any("before:" in d for d in diffs) and any("after:" in d for d in diffs), \
        "both sides are named, so the reader knows which reading was empty"


@pytest.mark.parametrize("side", ["before", "after"])
def test_one_empty_side_is_refused_whichever_side_it_is(tmp_path, side):
    full = gstate.read_state(_corpus(tmp_path))
    empty = gstate.read_state(_empty(tmp_path, "e.db"))
    before, after = (empty, full) if side == "before" else (full, empty)
    diffs = gcompare.differences(before, after)
    assert any(d.startswith(f"{side}:") for d in diffs), diffs


def test_a_reading_with_no_recipes_is_refused_even_with_entries_present():
    """The three refusals are separate, so a reading cannot satisfy one and skip another."""
    faked = {"short_circuit": ["beans"], "annotations": {"beans": [["a", "b", "c", "", "", ""]]},
             "counts": {"recipes": 0}, "integrity_check": "ok", "foreign_key_violations": 0}
    assert any("0 recipes" in d for d in gcompare.differences(faked, faked))


def test_the_command_line_exits_non_zero_on_an_empty_reading(tmp_path, capsys):
    e, f = tmp_path / "e.json", tmp_path / "f.json"
    e.write_text(json.dumps(gstate.read_state(_empty(tmp_path))))
    f.write_text(json.dumps(gstate.read_state(_corpus(tmp_path))))
    assert gcompare.main([str(e), str(f)]) == 1
    assert "GATE FAILED" in capsys.readouterr().out


# ---- compare.py: sets, not counts ----------------------------------------------------------------

def test_an_identical_reading_passes(tmp_path, capsys):
    st = gstate.read_state(_corpus(tmp_path))
    assert gcompare.differences(st, st) == []
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(st))
    b.write_text(json.dumps(st))
    assert gcompare.main([str(a), str(b)]) == 0
    assert "IDENTICAL" in capsys.readouterr().out


def test_one_recipe_leaving_the_byte_equal_set_while_another_joins_is_caught(tmp_path):
    """⚠️ THE COUNT HOLDS STILL AND THE SET DOES NOT. This is the case a gate stated as a number
    cannot see, and it is exactly what a corpus pass should have to explain."""
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["short_circuit"] = sorted(set(after["short_circuit"]) - {"beans"} | {"brownies"})
    assert len(before["short_circuit"]) == len(after["short_circuit"]), "the count is unchanged"
    diffs = gcompare.differences(before, after)
    assert any("short-circuit set moved" in d for d in diffs)
    assert any("beans" in d for d in diffs) and any("brownies" in d for d in diffs)


def test_one_annotation_entry_replacing_another_is_caught(tmp_path):
    """49 entries stay 49, and the entries are not the same entries."""
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    entries = after["annotations"]["brownies"]
    entries[0] = list(entries[0][:-1]) + ["something else entirely"]
    assert before["annotation_entries"] == after["annotation_entries"]
    diffs = gcompare.differences(before, after)
    assert any("annotation entries changed on brownies" in d for d in diffs)
    assert any(d.strip().startswith("gone") for d in diffs)
    assert any(d.strip().startswith("new") for d in diffs)


def test_a_count_that_moves_is_reported_with_both_values(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["counts"]["steps"] = before["counts"]["steps"] + 1
    assert any("count steps:" in d for d in gcompare.differences(before, after))


def test_a_broken_integrity_check_or_a_foreign_key_violation_fails_the_gate(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["integrity_check"] = "*** in database main ***"
    assert any("integrity_check is not ok" in d for d in gcompare.differences(before, after))
    after = json.loads(json.dumps(before))
    after["foreign_key_violations"] = 2
    assert any("foreign-key violations after" in d for d in gcompare.differences(before, after))


# ---- tablediff.py --------------------------------------------------------------------------------

def test_two_copies_of_one_database_are_identical(tmp_path):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    assert gtablediff.differences(db, twin, report=lambda *a: None) == []


def test_a_changed_row_is_found_and_the_table_is_named(tmp_path):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    con.execute("UPDATE recipe_steps SET text = 'something else' WHERE position = 0")
    con.commit()
    con.close()
    assert gtablediff.differences(db, twin, report=lambda *a: None) == ["recipe_steps"]


def test_a_table_only_one_side_has_is_reported_rather_than_skipped(tmp_path):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    con.execute("DROP TABLE recipe_note_step_refs")
    con.commit()
    con.close()
    assert "recipe_note_step_refs" in gtablediff.differences(db, twin, report=lambda *a: None)


def test_it_compares_every_table_not_a_chosen_list_of_content_tables(tmp_path):
    """⚠️ FOUND BY RUNNING IT WIDE. After the notes go-live every content table was identical and
    sqlite_sequence was not, which is what showed rows had been created and removed rather than
    nothing having happened. A list of eleven tables cannot answer that."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    con.execute("INSERT INTO note_kinds (kind, header, position) "
                "VALUES ('probe', 'Probe', 99)")
    con.commit()
    con.close()
    assert "note_kinds" in gtablediff.differences(db, twin, report=lambda *a: None)


def test_storage_order_is_not_mistaken_for_a_change(tmp_path):
    """Two databases holding the same rows in a different physical order are the same data."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    con = _schema(twin)
    _recipe(con, "biscuits")              # inserted in the other order
    _recipe(con, "beans")
    _recipe(con, "brownies", drift="Mix it well")
    con.close()
    rows = lambda p: sorted(tuple(r) for r in sqlite3.connect(p).execute(
        "SELECT recipe_id, position, text FROM recipe_steps"))
    assert rows(db) == rows(twin), "the fixture really does hold the same rows"
    assert "recipes" not in gtablediff.differences(db, twin, report=lambda *a: None)


def test_tablediff_opens_both_sides_read_only(tmp_path):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    gtablediff.differences(db, twin, report=lambda *a: None)
    assert db.read_bytes() == twin.read_bytes(), "comparing two databases changes neither"


def test_the_command_line_exits_non_zero_when_they_differ(tmp_path, capsys):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    assert gtablediff.main([str(db), str(twin)]) == 0
    assert "EVERY TABLE IS IDENTICAL" in capsys.readouterr().out
    con = sqlite3.connect(twin)
    con.execute("DELETE FROM recipe_steps WHERE position = 1")
    con.commit()
    con.close()
    assert gtablediff.main([str(db), str(twin)]) == 1
    assert "TABLES THAT DIFFER" in capsys.readouterr().out


# ---- the gates stay read-only ---------------------------------------------------------------------

def test_no_gate_contains_a_write_statement():
    """The read-only claim is checked rather than trusted, the way the exemption list in
    tests/test_live_guards.py is checked. Stated over the folder, so a fourth gate is covered."""
    import re
    writes = re.compile(r"\b(INSERT\s+(INTO|OR)|UPDATE\s+\w+\s+SET|DELETE\s+FROM"
                        r"|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\b", re.IGNORECASE)
    gates = sorted((REPO / "scripts" / "gates").glob("*.py"))
    assert gates, "the gates folder is empty, so this test is checking nothing"
    for p in gates:
        body = "\n".join(l for l in p.read_text().splitlines()
                         if not l.strip().startswith("#"))
        assert writes.findall(body) == [], f"{p.name} is a gate and contains a write"


def test_every_gate_opens_through_the_one_read_only_helper():
    """One rule, one function. A gate that spells sqlite3.connect itself can forget mode=ro."""
    for p in sorted((REPO / "scripts" / "gates").glob("*.py")):
        src = p.read_text()
        if "sqlite3.connect(" not in src:
            continue
        assert p.name == "state.py", f"{p.name} opens a database without going through open_ro"
        assert "mode=ro" in src
