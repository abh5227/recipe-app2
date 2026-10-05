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
    tmp_path.mkdir(parents=True, exist_ok=True)      # callers pass subdirectories for distinct DBs
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


# ---- rounds.py: the per-round declaration --------------------------------------------------------

import rounds as grounds          # noqa: E402

FULL = {"round": "probe", "why": "a test", "short_circuit": "unchanged",
        "annotations": "unchanged", "counts": {}, "tables": "identical"}


def _spec(tmp_path, **over):
    spec = dict(FULL)
    spec.update(over)
    p = tmp_path / "round.json"
    p.write_text(json.dumps(spec))
    return p


def test_a_missing_round_file_fails(tmp_path):
    """⚠️ A GO-LIVE WITH NO DECLARATION IS NOT A GO-LIVE WITH AN EMPTY ONE."""
    with pytest.raises(grounds.BadRound) as e:
        grounds.load_round(tmp_path / "nothing-here.json")
    assert "no round file" in str(e.value)


@pytest.mark.parametrize("missing", grounds.REQUIRED)
def test_every_key_is_required_so_silence_is_never_consent(tmp_path, missing):
    """⚠️ AN OMISSION IS THE MOST LIKELY WAY A REAL MOVE GOES UNDECLARED, so an omission fails
    rather than defaulting to "unchanged"."""
    spec = {k: v for k, v in FULL.items() if k != missing}
    p = tmp_path / "round.json"
    p.write_text(json.dumps(spec))
    with pytest.raises(grounds.BadRound) as e:
        grounds.load_round(p)
    assert missing in str(e.value)


def test_a_round_file_that_is_not_json_fails(tmp_path):
    p = tmp_path / "round.json"
    p.write_text("{not json")
    with pytest.raises(grounds.BadRound) as e:
        grounds.load_round(p)
    assert "not valid JSON" in str(e.value)


@pytest.mark.parametrize("bad", [
    {"short_circuit": "whatever"},
    {"annotations": 7},
    {"counts": []},
    {"counts": {"users": 4}},
    {"counts": {"users": [4]}},
    {"tables": "mostly"},
    {"tables": {"only": ["users"]}},
])
def test_a_malformed_declaration_fails_rather_than_being_guessed_at(tmp_path, bad):
    spec = dict(FULL)
    spec.update(bad)
    p = tmp_path / "round.json"
    p.write_text(json.dumps(spec))
    with pytest.raises(grounds.BadRound):
        grounds.load_round(p)


def test_nothing_moves_declared_explicitly_passes_when_nothing_moved(tmp_path):
    st = gstate.read_state(_corpus(tmp_path))
    assert grounds.check(st, st, grounds.load_round(_spec(tmp_path))) == []


def test_an_empty_reading_fails_the_round_gate_too(tmp_path):
    """The refusal is compare.py's, called from here rather than copied."""
    empty = gstate.read_state(_empty(tmp_path))
    fails = grounds.check(empty, empty, grounds.load_round(_spec(tmp_path)))
    assert any("nothing to compare" in f for f in fails)


def test_a_count_that_moves_undeclared_fails(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["counts"]["users"] = before["counts"]["users"] + 3
    fails = grounds.check(before, after, grounds.load_round(_spec(tmp_path)))
    assert any("did not declare it" in f and "users" in f for f in fails)


def test_a_declared_count_move_that_happens_passes(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    was = before["counts"]["users"]
    after["counts"]["users"] = was - 1
    spec = grounds.load_round(_spec(tmp_path, counts={"users": [was, was - 1]}))
    assert grounds.check(before, after, spec) == []


def test_a_declared_count_move_that_does_not_happen_fails(tmp_path):
    """⚠️ BOTH DIRECTIONS. A round that declares a removal and removes nothing has not run."""
    st = gstate.read_state(_corpus(tmp_path))
    was = st["counts"]["users"]
    spec = grounds.load_round(_spec(tmp_path, counts={"users": [was, was - 1]}))
    fails = grounds.check(st, st, spec)
    assert any("declared" in f and "users" in f for f in fails)


def test_a_declared_count_the_reading_does_not_carry_fails(tmp_path):
    st = gstate.read_state(_corpus(tmp_path))
    spec = grounds.load_round(_spec(tmp_path, counts={"not_a_table": [1, 0]}))
    fails = grounds.check(st, st, spec)
    assert any("readings do not carry it" in f for f in fails)


def test_an_undeclared_short_circuit_move_fails_and_a_declared_one_passes(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["short_circuit"] = [r for r in before["short_circuit"] if r != "beans"]

    fails = grounds.check(before, after, grounds.load_round(_spec(tmp_path)))
    assert any("declared the short-circuit set unchanged" in f for f in fails)

    spec = grounds.load_round(_spec(tmp_path, short_circuit={"left": ["beans"], "joined": []}))
    assert grounds.check(before, after, spec) == []


def test_an_undeclared_annotation_change_fails_and_a_declared_one_passes(tmp_path):
    before = gstate.read_state(_corpus(tmp_path))
    after = json.loads(json.dumps(before))
    after["annotations"]["brownies"] = [["x", "y", "z", "", "", ""]]

    fails = grounds.check(before, after, grounds.load_round(_spec(tmp_path)))
    assert any("declared the annotations unchanged" in f for f in fails)

    spec = grounds.load_round(_spec(tmp_path, annotations={"brownies": "changed"}))
    assert grounds.check(before, after, spec) == []


def test_an_undeclared_table_change_fails_and_a_declared_one_passes(tmp_path):
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    con.execute("INSERT INTO note_kinds (kind, header, position) VALUES ('probe','Probe',99)")
    con.commit()
    con.close()

    fails = grounds.check_tables(db, twin, grounds.load_round(_spec(tmp_path)))
    assert any("note_kinds differs and the round did not declare it" in f for f in fails)

    spec = grounds.load_round(_spec(tmp_path, tables={"except": ["note_kinds"]}))
    assert grounds.check_tables(db, twin, spec) == []


def test_a_table_declared_as_changing_that_is_identical_fails(tmp_path):
    """⚠️ BOTH DIRECTIONS AGAIN. A declaration is a claim about what happened, not a permission
    slip, so an unused exception means the round did not do what it said."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    spec = grounds.load_round(_spec(tmp_path, tables={"except": ["users"]}))
    fails = grounds.check_tables(db, twin, spec)
    assert any("declared as changing and is identical" in f for f in fails)


def test_the_command_line_refuses_a_missing_round_file(tmp_path, capsys):
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(_corpus(tmp_path))))
    code = grounds.main(["--round", str(tmp_path / "gone.json"),
                         "--before", str(st), "--after", str(st)])
    assert code == 2
    assert "NOT USABLE" in capsys.readouterr().out


def test_the_command_line_passes_a_clean_round(tmp_path, capsys):
    """⚠️ A READING PER DATABASE. The readings now have to describe the databases passed in, so a
    single reading reused for both sides is refused."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(gstate.read_state(db)))
    a.write_text(json.dumps(gstate.read_state(twin)))
    code = grounds.main(["--round", str(_spec(tmp_path)), "--before", str(b), "--after", str(a),
                         "--a-db", str(db), "--b-db", str(twin)])
    assert code == 0
    assert "EXACTLY WHAT IT DECLARED" in capsys.readouterr().out


@pytest.mark.parametrize("tables", ["identical", {"except": ["users"]}])
def test_no_round_passes_without_the_two_databases(tmp_path, capsys, tables):
    """⚠️ THE STRONGEST CLAIM WAS THE ONE THAT WENT UNCHECKED. The table half ran only when both
    databases were given, and their absence was complained about only when the round declared an
    exception. So "tables": "identical", the claim that NO table differs, passed while comparing
    nothing, and printed that the round did exactly what it declared."""
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(_corpus(tmp_path))))
    code = grounds.main(["--round", str(_spec(tmp_path, tables=tables)),
                         "--before", str(st), "--after", str(st)])
    assert code == 1
    assert "no databases were given" in capsys.readouterr().out


def test_a_table_difference_invisible_to_the_readings_still_fails_the_round(tmp_path, capsys):
    """⚠️ THE EXACT CASE THAT PASSED. Two databases agreeing on every key state.py records, and
    differing in one users row. The readings cannot see it and the table half must."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    con.execute("UPDATE users SET email = 'someone-else@test.invalid' WHERE id = 1")
    con.commit()
    con.close()

    before, after = gstate.read_state(db), gstate.read_state(twin)
    assert before["counts"] == after["counts"], "the fixture must be invisible to the counts"
    assert before["short_circuit"] == after["short_circuit"]
    assert gcompare.differences(before, after) == [], "and invisible to the plain comparator"

    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(before))
    a.write_text(json.dumps(after))
    code = grounds.main(["--round", str(_spec(tmp_path)), "--before", str(b), "--after", str(a),
                         "--a-db", str(db), "--b-db", str(twin)])
    assert code == 1, "the round gate passed a database difference"
    assert "users differs and the round did not declare it" in capsys.readouterr().out


def test_the_integrity_rule_lives_in_one_place():
    """⚠️ A COMMENT CLAIMING A RULE IS SHARED IS NOT A SHARED RULE. rounds.py carried a
    byte-identical copy of compare.py's integrity block, four lines under a comment saying the
    refusals above were compare.py's and not a second copy."""
    rounds_src = (REPO / "scripts" / "gates" / "rounds.py").read_text()
    assert "integrity_check is not ok" not in rounds_src, "rounds.py restates the integrity rule"
    assert "integrity_problems(" in rounds_src, "and it does not call the shared one"
    assert "def integrity_problems" in (REPO / "scripts" / "gates" / "compare.py").read_text()


# ---- the committed round files are usable --------------------------------------------------------

def test_every_committed_round_file_loads():
    """⚠️ A ROUND FILE THAT DOES NOT PARSE IS FOUND ON GO-LIVE NIGHT OTHERWISE. Stated over the
    folder, so the next round's file is checked the moment it is committed."""
    folder = REPO / "golive" / "rounds"
    files = sorted(folder.glob("*.json"))
    assert files, "no round files, so this test is checking nothing"
    for p in files:
        spec = grounds.load_round(p)
        assert spec["round"] == p.stem, f"{p.name} names itself {spec['round']!r}"
        assert spec["why"].strip(), f"{p.name} has an empty reason"


def test_this_round_declares_the_account_removal():
    """The round in flight. Named so the declaration and the work cannot drift apart silently."""
    spec = grounds.load_round(REPO / "golive" / "rounds"
                              / "2026-10-05-remove-demo-accounts.json")
    assert spec["counts"]["users"] == [4, 1], "three accounts out of four"
    assert spec["short_circuit"] == "unchanged", "no recipe leaves the byte-equal set"
    assert spec["annotations"] == "unchanged", "and no annotation entry moves"
    changed = set(spec["tables"]["except"])
    assert "users" in changed
    for t in ("recipes", "recipe_notes", "recipe_steps", "recipe_ingredients", "recipe_snapshots"):
        assert t not in changed, f"{t} must not change in an account removal"


def test_no_gate_hardcodes_its_own_expected_moves():
    """⚠️ THE THING THIS REPLACED. A hardcoded expected-moves block inside the gate went stale and
    printed ten failures that were all false, so nothing in scripts/gates/ may carry one.

    ⚠️ IT LOOKS FOR AN ASSIGNMENT, NOT FOR THE WORD. rounds.py names INTENDED in its docstring to
    say what it replaced and why, which is the record worth keeping. A first version of this test
    grepped the word and failed on that explanation, which would have pushed the reason out of the
    file to keep the test quiet."""
    import ast as _ast
    for p in sorted((REPO / "scripts" / "gates").glob("*.py")):
        tree = _ast.parse(p.read_text())
        for node in tree.body:                      # module level only: a local is not a declaration
            targets = (node.targets if isinstance(node, _ast.Assign)
                       else [node.target] if isinstance(node, _ast.AnnAssign) else [])
            for t in targets:
                name = getattr(t, "id", "")
                assert "INTENDED" not in name.upper(), \
                    f"{p.name} declares {name}, an expected-moves block inside the gate again"


def test_a_column_mixing_null_and_text_does_not_break_the_comparison(tmp_path):
    """⚠️ FOUND ON THE FIRST REAL DATABASE. The comparison sorted its rows, and Python 3 will not
    order None against str, so a table with both in one column raised TypeError. Every fixture here
    was uniform, so the suite was green and the tool died on recipes.author."""
    db = tmp_path / "mixed.db"
    con = _schema(db)
    con.execute("INSERT INTO recipes (id, name, source, author) VALUES ('a','A','app','Someone')")
    con.execute("INSERT INTO recipes (id, name, source, author) VALUES ('b','B','app',NULL)")
    con.commit()
    con.close()
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    assert gtablediff.differences(db, twin, report=lambda *a: None) == []


def test_a_duplicate_row_appearing_is_caught(tmp_path):
    """⚠️ A MULTISET, NOT A SET. recipe_steps carries no uniqueness on (recipe_id, position), so two
    identical rows are a real state and collapsing them to one would hide a duplicate being added."""
    db = _corpus(tmp_path)
    twin = tmp_path / "twin.db"
    twin.write_bytes(db.read_bytes())
    con = sqlite3.connect(twin)
    row = con.execute("SELECT recipe_id, position, is_heading, text, heading_level "
                      "FROM recipe_steps LIMIT 1").fetchone()
    con.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, text, heading_level) "
                "VALUES (?,?,?,?,?)", row)
    con.commit()
    con.close()
    assert "recipe_steps" in gtablediff.differences(db, twin, report=lambda *a: None)


# ---- the refined empty rule: no reading ever passes, a declared zero does -------------------------

def _no_recipes(tmp_path):
    """A reading from a database with the tables and no rows. This is "nothing was read"."""
    return gstate.read_state(_empty(tmp_path, "norows.db"))


def _fresh_import(tmp_path):
    """⚠️ A REAL AND HEALTHY STATE, AND THE ONE THE OLD RULE REFUSED. Every recipe byte-equal to
    its baseline and nobody has edited anything, which is a corpus freshly loaded from an import and
    the exact shape of a first go-live."""
    db = tmp_path / "fresh.db"
    con = _schema(db)
    _recipe(con, "beans")
    _recipe(con, "biscuits")
    con.close()
    st = gstate.read_state(db)
    assert st["counts"]["recipes"] == 2 and st["short_circuit"] and st["annotations"] == {}
    return st


def test_a_reading_with_no_recipes_fails_whatever_the_round_declares(tmp_path):
    """⚠️ NEVER DECLARABLE. A reading taken against the wrong path agrees with anything, and two of
    them are byte-identical."""
    none = _no_recipes(tmp_path)
    for spec in (_spec(tmp_path), _spec(tmp_path, short_circuit="none", annotations="none")):
        fails = grounds.check(none, none, grounds.load_round(spec))
        assert any("0 recipes" in f for f in fails), \
            "a round declared its way past a reading that found nothing"


def test_a_reading_with_none_of_the_tables_fails(tmp_path):
    """The other way a reading describes nothing: pointed at a database from before the migrations."""
    faked = {"short_circuit": [], "annotations": {},
             "counts": {k: None for k in ("recipes", "steps", "users")},
             "integrity_check": "ok", "foreign_key_violations": 0}
    fails = grounds.check(faked, faked,
                          grounds.load_round(_spec(tmp_path, short_circuit="none",
                                                   annotations="none")))
    assert any("every count is absent" in f for f in fails)


def test_a_reading_with_no_counts_at_all_fails(tmp_path):
    faked = {"short_circuit": ["beans"], "annotations": {}, "counts": {},
             "integrity_check": "ok", "foreign_key_violations": 0}
    fails = grounds.check(faked, faked, grounds.load_round(_spec(tmp_path, annotations="none")))
    assert any("no counts at all" in f for f in fails)


def test_a_genuine_zero_is_refused_when_the_round_does_not_declare_it(tmp_path):
    """⚠️ DIRECTION ONE. 0 annotations is still refused by default, because an empty set is how a
    reading taken against the wrong thing looks."""
    st = _fresh_import(tmp_path)
    fails = grounds.check(st, st, grounds.load_round(_spec(tmp_path)))
    assert any("NO annotation entries" in f for f in fails)
    assert any('must declare "annotations": "none"' in f for f in fails), \
        "the refusal does not say how to declare it"


def test_a_genuine_zero_passes_once_the_round_declares_it(tmp_path):
    """⚠️ DIRECTION TWO. A fresh import is a correct state, and a round that says so may proceed."""
    st = _fresh_import(tmp_path)
    assert grounds.check(st, st, grounds.load_round(_spec(tmp_path, annotations="none"))) == []


def test_declaring_a_set_empty_when_it_is_populated_fails(tmp_path):
    """A declaration is a claim about what is there, so it fails in both directions."""
    st = gstate.read_state(_corpus(tmp_path))
    assert st["annotations"], "the fixture must carry annotations for this to mean anything"
    fails = grounds.check(st, st, grounds.load_round(_spec(tmp_path, annotations="none")))
    assert any('declared "annotations": "none"' in f and "carries" in f for f in fails)


def test_an_empty_short_circuit_set_follows_the_same_two_rules(tmp_path):
    """Both emptiable sets behave the same way, so the rule is one rule."""
    st = gstate.read_state(_corpus(tmp_path))
    st["short_circuit"] = []                         # every recipe has drifted: real, and unusual
    fails = grounds.check(st, st, grounds.load_round(_spec(tmp_path)))
    assert any("short-circuit set is EMPTY" in f for f in fails)
    assert grounds.check(st, st, grounds.load_round(
        _spec(tmp_path, short_circuit="none"))) == []


def test_the_plain_comparator_still_refuses_every_empty_reading(tmp_path):
    """⚠️ compare.py HAS NO DECLARATION TO READ, so it keeps the strict rule. Relaxing the round
    gate must not relax the identity gate, which is what a spot-check with no round file uses."""
    st = _fresh_import(tmp_path)
    fails = gcompare.differences(st, st)
    assert any("NO annotation entries" in f for f in fails)
    none = _no_recipes(tmp_path)
    assert any("0 recipes" in f for f in gcompare.differences(none, none))


def test_this_round_does_not_declare_either_set_empty():
    """Live carries 280 byte-equal recipes and 49 annotation entries, so a "none" here would be
    wrong and would hide a real loss."""
    spec = grounds.load_round(REPO / "golive" / "rounds"
                              / "2026-10-05-remove-demo-accounts.json")
    assert spec["short_circuit"] != "none" and spec["annotations"] != "none"


# ---- a missing reading is named, not a traceback -------------------------------------------------

@pytest.mark.parametrize("which", ["--before", "--after"])
def test_a_missing_reading_is_named_rather_than_a_traceback(tmp_path, capsys, which):
    """⚠️ THE SAME COURTESY THE ROUND FILE GETS. A missing --round printed a written paragraph and a
    missing --before printed a bare FileNotFoundError, which is a worse answer to the same
    mistake."""
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(_corpus(tmp_path))))
    gone = tmp_path / "not-here.json"
    args = ["--round", str(_spec(tmp_path)),
            "--before", str(gone if which == "--before" else st),
            "--after", str(gone if which == "--after" else st)]
    assert grounds.main(args) == 2
    out = capsys.readouterr().out
    assert "NOT USABLE" in out and str(gone) in out and which in out
    assert "state.py" in out, "it does not say how to make one"


def test_a_reading_that_is_not_json_is_named_rather_than_a_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(_corpus(tmp_path))))
    assert grounds.main(["--round", str(_spec(tmp_path)), "--before", str(bad),
                         "--after", str(st)]) == 2
    assert "not valid JSON" in capsys.readouterr().out


def test_a_round_path_that_is_a_directory_is_refused_rather_than_raising(tmp_path):
    """load_round tested p.exists(), so a directory reached read_text() and raised IsADirectoryError."""
    with pytest.raises(grounds.BadRound):
        grounds.load_round(tmp_path)


# ---- the databases have to be the ones the readings describe --------------------------------------

def test_two_unrelated_databases_cannot_satisfy_the_table_half(tmp_path, capsys):
    """⚠️ NOTHING TIED THEM TOGETHER. state.py records the path it read in every reading and no gate
    looked at it, so readings taken from one database with --a-db and --b-db pointed at two
    unrelated throwaways printed that the round did exactly what it declared, exit 0."""
    real = _corpus(tmp_path / "real")
    other_a = _corpus(tmp_path / "oa")
    other_b = tmp_path / "ob.db"
    other_b.write_bytes(other_a.read_bytes())
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(gstate.read_state(real)))
    a.write_text(json.dumps(gstate.read_state(real)))
    code = grounds.main(["--round", str(_spec(tmp_path)), "--before", str(b), "--after", str(a),
                         "--a-db", str(other_a), "--b-db", str(other_b)])
    assert code == 1
    out = capsys.readouterr().out
    assert "the reading does not describe" in out


def test_the_same_database_twice_is_refused(tmp_path, capsys):
    """⚠️ WHAT AN OPERATOR TYPES WHEN THE BEFORE-COPY IS GONE. Comparing a database with itself
    makes every table trivially identical, so the table half passes while checking nothing."""
    db = _corpus(tmp_path)
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(db)))
    code = grounds.main(["--round", str(_spec(tmp_path)), "--before", str(st), "--after", str(st),
                         "--a-db", str(db), "--b-db", str(db)])
    assert code == 1
    assert "same database" in capsys.readouterr().out


@pytest.mark.parametrize("which", ["--a-db", "--b-db"])
def test_a_missing_database_is_named_rather_than_a_traceback(tmp_path, capsys, which):
    """The courtesy --before and --after got, extended to the half that was left behind: a missing
    --a-db printed a bare sqlite3.OperationalError."""
    db = _corpus(tmp_path)
    st = tmp_path / "s.json"
    st.write_text(json.dumps(gstate.read_state(db)))
    gone = tmp_path / "not-a-database.db"
    code = grounds.main(["--round", str(_spec(tmp_path)), "--before", str(st), "--after", str(st),
                         "--a-db", str(gone if which == "--a-db" else db),
                         "--b-db", str(gone if which == "--b-db" else db)])
    assert code == 2
    out = capsys.readouterr().out
    assert "NOT USABLE" in out and which in out and str(gone) in out
