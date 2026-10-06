"""scripts/remove_demo_rows.py, RUN against the real schema.

⚠️ THE SIGNATURE IS THE WHOLE POINT, SO MOST OF THESE BREAK IT. The 7 rows are named by id, and an
id is a position in a table: it meant one thing when the script was written and can mean another by
the time it runs. Each test takes one clause of one row's signature away and checks the script
refuses the WHOLE run rather than that row.

⚠️ AND THE ONE THAT MATTERS MOST IS THE RATED COOK. `edit_cook` writes rating, rated_at and caption
onto an existing row and never rewrites `source`, so a demo-seeded cook somebody later rated through
the UI is machine-made by its source and a person's own work by its content. The same defect was
measured in remove_demo_accounts.py by review, where a cook carrying rating 4.5 and a caption was
deleted with no refusal and exit 0.
"""
import importlib.util
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import migrate            # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "remove_demo_rows", REPO / "scripts" / "remove_demo_rows.py")
rdr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rdr)

OWNER = rdr.OWNER_EMAIL
# The two seeding runs' stamps, as they appear in a timestamp: "<minute>:<second>".
RUN_A, RUN_B = "2026-07-25 13:30:45", "2026-07-26 16:16:26"


def _db(tmp_path, cook_extras=(), stamps=None):
    """The real schema with the 7 demo rows exactly as live carries them, plus real rows beside
    them, so a test can tell "refused everything" from "refused the right thing"."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "rows.db"
    migrate.DB = path
    migrate.migrate(verbose=False, db=path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES (1,?,?,?)",
              (OWNER, "hash", "2026-07-24 04:10:38"))
    for rid in ("1-2-3-4-5-tofu", "acqua-pazza", "adventist-gumbo", "bbq-gulf-snapper",
                "aloo-potato-parathas"):
        c.execute("INSERT INTO recipes (id, name, source, owner) VALUES (?,?, 'app', 1)",
                  (rid, rid.replace("-", " ")))

    stamps = stamps or {}
    # the 3 demo cooks
    for cid, rid in ((211, "1-2-3-4-5-tofu"), (212, "acqua-pazza"), (213, "adventist-gumbo")):
        extra = dict(cook_extras).get(cid, {})
        c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source, rating, caption)"
                  " VALUES (?,?,1,'2026-07-25',?,?,?)",
                  (cid, rid, extra.get("source", "demo-seed"),
                   extra.get("rating"), extra.get("caption")))
    # a REAL cook beside them, which must survive every run
    c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source, rating) "
              "VALUES (400,'acqua-pazza',1,'2026-09-01','app',4.5)")

    # the 3 demo posts and the demo comment
    c.execute("INSERT INTO shared_posts (id, user_id, recipe_id, caption, created_at) "
              "VALUES (2,1,'bbq-gulf-snapper','proud of this one',?)", (stamps.get(2, RUN_A),))
    c.execute("INSERT INTO shared_posts (id, user_id, cook_log_id, caption, created_at) "
              "VALUES (8,1,211,'sunday bake with the kids',?)", (stamps.get(8, RUN_B),))
    c.execute("INSERT INTO shared_posts (id, user_id, recipe_id, created_at) "
              "VALUES (9,1,'aloo-potato-parathas',?)", (stamps.get(9, RUN_B),))
    c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
              "VALUES (3,8,1,'will send it over tonight',?)", (stamps.get("c3", RUN_B),))
    # a REAL post with a REAL comment, neither named by the script
    c.execute("INSERT INTO shared_posts (id, user_id, recipe_id, caption, created_at) "
              "VALUES (50,1,'acqua-pazza','tonight',  '2026-10-05 20:06:27')")
    c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
              "VALUES (60,50,1,'my own words','2026-10-05 20:07:00')")
    c.commit()
    c.close()
    return path


def _count(path, table, where="1=1"):
    c = sqlite3.connect(path)
    try:
        return c.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}').fetchone()[0]
    finally:
        c.close()


def _run(path, apply_it=False):
    lines = []
    code = rdr.run(path, apply_it, out=lines.append)
    return code, "\n".join(lines)


# ---- the happy path ------------------------------------------------------------------------------

def test_the_seven_rows_go_and_nothing_else_does(tmp_path):
    db = _db(tmp_path / "ok")
    code, out = _run(db, apply_it=True)
    assert code == 0, out
    assert "7 rows deleted" in out
    assert _count(db, "shared_posts") == 1 and _count(db, "shared_posts", "id = 50") == 1
    assert _count(db, "comments") == 1 and _count(db, "comments", "id = 60") == 1
    assert _count(db, "cook_log") == 1 and _count(db, "cook_log", "id = 400") == 1
    assert _count(db, "recipes") == 5, "a recipe moved, which this round declares it does not"


def test_a_dry_run_writes_nothing_and_counts_the_same_rows(tmp_path):
    db = _db(tmp_path / "dry")
    before = pathlib.Path(db).read_bytes()
    code, out = _run(db, apply_it=False)
    assert code == 0
    assert "7 rows would go" in out
    assert pathlib.Path(db).read_bytes() == before, "the dry run wrote to the database"


def test_the_dry_run_and_the_apply_name_the_same_seven(tmp_path):
    """⚠️ A SECOND HAND-WRITTEN QUERY IS HOW A PREVIEW AND A RUN DRIFT APART. Both halves read one
    WHERE per row, so the preview is the run."""
    dry = _run(_db(tmp_path / "a"), apply_it=False)[1]
    wet = _run(_db(tmp_path / "b"), apply_it=True)[1]
    rows = lambda t: [ln.split()[0] + " " + ln.split()[1] for ln in t.splitlines()
                      if ln.startswith("    ") and ln.strip()[0].isalpha()]
    assert rows(dry) == rows(wet) != []


# ---- the signature refuses when the picture has changed ------------------------------------------

@pytest.mark.parametrize("field,value,why", [
    ("rating", 4.5, "carries no rating"),
    ("caption", "best yet", "carries no caption"),
])
def test_a_demo_cook_somebody_later_rated_or_captioned_refuses(tmp_path, field, value, why):
    """The clause that protects outcome data. Nothing is written and the cook is still there."""
    db = _db(tmp_path / f"rated-{field}", cook_extras=((212, {field: value}),))
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert why in out and "cook_log 212" in out
    assert _count(db, "cook_log", "id = 212") == 1
    assert _count(db, "shared_posts") == 4, "it deleted the posts before refusing on the cook"


def test_a_cook_whose_source_is_no_longer_demo_refuses(tmp_path):
    """A row that has become an ordinary cook since this was written is not this script's to take."""
    db = _db(tmp_path / "source", cook_extras=((213, {"source": "app"}),))
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "machine-made by source" in out
    assert _count(db, "cook_log", "id = 213") == 1


def test_a_cook_carrying_a_photo_refuses(tmp_path):
    """cook_photos.cook_log_id is nullable, so "no photo points at this cook" is a real question and
    a photo is a person's own work by any reading."""
    db = _db(tmp_path / "photo")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO cook_photos (cook_log_id, recipe_id, user_id, path, added_at) "
              "VALUES (211,'1-2-3-4-5-tofu',1,'images/x.jpg','2026-07-25 00:00:00')")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "carries no photo" in out and "cook_log 211" in out
    assert _count(db, "cook_log", "id = 211") == 1


def test_a_post_whose_timestamp_is_not_a_seeding_stamp_refuses(tmp_path):
    """⚠️ THE ID ALONE WOULD HAVE DELETED THIS. The row is id 9 under the owner's id, and its
    timestamp says a person made it, so the run stops."""
    db = _db(tmp_path / "stamp", stamps={9: "2026-10-05 20:06:27"})
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "stamped by a seeding run" in out and "shared_posts 9" in out
    assert _count(db, "shared_posts", "id = 9") == 1
    assert _count(db, "comments", "id = 3") == 1, "it deleted the comment before refusing"


def test_a_row_that_is_gone_refuses_rather_than_passing(tmp_path):
    """A row already removed is not a no-op, it is a changed picture. "7 of 7" is the claim."""
    db = _db(tmp_path / "absent")
    c = sqlite3.connect(db)
    c.execute("DELETE FROM shared_posts WHERE id = 2")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "is not in this database at all" in out


def test_a_post_under_another_account_refuses(tmp_path):
    """These rows are being removed BECAUSE they carry the owner's id. One that does not is a
    different row with the same number."""
    db = _db(tmp_path / "other")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, email, password_hash, created_at) "
              "VALUES (2,'someone@else.test','h','2026-01-01 00:00:00')")
    c.execute("UPDATE shared_posts SET user_id = 2 WHERE id = 8")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "shared under the owner's id" in out


def test_an_unlisted_demo_cook_refuses(tmp_path):
    """A demo row the script does not name means the picture grew since it was measured, which is a
    person's decision. Stated over `source`, which no route writes."""
    db = _db(tmp_path / "unlisted")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source) "
              "VALUES (999,'acqua-pazza',1,'2026-07-25','demo-2b')")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "demo rows this script does not name" in out and "cook 999" in out
    assert _count(db, "cook_log", "id = 999") == 1


def test_a_database_with_no_owner_account_refuses(tmp_path):
    """The owner is resolved from the email, so a database without that account has no owner whose
    rows these are, and an id written in by hand would have matched anyone."""
    db = _db(tmp_path / "noowner")
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = OFF")
    c.execute("UPDATE users SET email = 'somebody@else.test' WHERE id = 1")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "there is no account" in out


# ---- the shape of the script itself --------------------------------------------------------------

def test_the_owner_is_named_by_email_and_not_by_id():
    """⚠️ AN ID IS A POSITION AND AN EMAIL IS A PERSON. The script resolves one from the other."""
    src = (REPO / "scripts" / "remove_demo_rows.py").read_text()
    assert 'OWNER_EMAIL = "andyhannah2014@gmail.com"' in src
    assert ":uid" in src, "the owner is no longer a bound parameter"
    assert "user_id = 1" not in src and "author_id = 1" not in src, "an id is written in by hand"


def test_the_delete_order_is_comments_then_posts_then_cooks():
    """Both cascades point inward, so this order is what makes every row's own statement count it."""
    tables = [t for t, _rid, _w, _c in rdr.DEMO_ROWS]
    assert tables == ["comments"] + ["shared_posts"] * 3 + ["cook_log"] * 3


def test_the_script_names_its_database_and_refuses_live():
    src = (REPO / "scripts" / "remove_demo_rows.py").read_text()
    assert "--db" in src and "--i-mean-live" in src
    assert "from corpus_guard import refuse_live" in src, "the shared guard is not imported"
    assert "def is_live" not in src, "the guard was copied instead of imported"


def test_every_row_states_a_signature_and_not_only_an_id():
    for table, rid, what, checks in rdr.DEMO_ROWS:
        assert checks, f"{table} {rid} has no signature, so only its id identifies it"
        assert what.strip(), f"{table} {rid} does not say what it is"
        assert len(checks) >= 2, f"{table} {rid} rests on one clause"


def test_the_where_carries_every_clause():
    """The count and the DELETE share one WHERE, and it names the whole signature, not just the id."""
    where = rdr._where(rdr._COOK_CHECKS)
    assert where.startswith("id = :rid AND ")
    for _why, sql in rdr._COOK_CHECKS:
        assert sql in where


# ---- nothing unnamed goes with them --------------------------------------------------------------
# ⚠️ THE DEFECT THE REVIEW FOUND, AND IT WAS A DELETION, NOT A WARNING. The script enumerated two
# cascades in prose and concluded a cascade had nothing left to reach. The schema has four children
# of these three tables, `recipe_snapshots` was in no clause at all, and the ordering only ever
# protected rows the script itself names. Each case below was deleted silently with 7 printed and
# exit 0, because `rowcount` counts direct deletes and a cascade KEEPS integrity, so neither the
# total nor PRAGMA foreign_key_check could see it.

def test_the_cascade_children_are_read_from_the_schema(tmp_path):
    """Four, not the two the prose remembered."""
    db = _db(tmp_path / "children")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        assert rdr.cascade_children(c, "cook_log") == [
            ("cook_photos", "cook_log_id"), ("recipe_snapshots", "cook_log_id"),
            ("shared_posts", "cook_log_id")]
        assert rdr.cascade_children(c, "shared_posts") == [("comments", "post_id")]
        assert rdr.cascade_children(c, "comments") == []
    finally:
        c.close()


def test_a_comment_the_owner_wrote_on_a_demo_post_refuses(tmp_path):
    """The owner's own words, written today, on one of the posts going. A cascade would take them."""
    db = _db(tmp_path / "hanger-comment")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
              "VALUES (70, 2, 1, 'still thinking about this one', '2026-10-05 20:30:00')")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "a CASCADE would take rows this script does not name" in out
    assert "comments 70 points at shared_posts 2" in out
    assert _count(db, "comments", "id = 70") == 1
    assert _count(db, "shared_posts", "id = 2") == 1, "it deleted the post before refusing"


def test_a_post_the_owner_shared_of_a_demo_cook_refuses(tmp_path):
    """A real post pointing at a cook that is going. shared_posts.cook_log_id is ON DELETE CASCADE."""
    db = _db(tmp_path / "hanger-post")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO shared_posts (id, user_id, cook_log_id, caption, created_at) "
              "VALUES (51, 1, 212, 'made it again', '2026-10-05 20:31:00')")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "shared_posts 51 points at cook_log 212" in out
    assert _count(db, "shared_posts", "id = 51") == 1
    assert _count(db, "cook_log", "id = 212") == 1


def test_a_cook_snapshot_refuses(tmp_path):
    """⚠️ THE CHILD THAT WAS IN NO CLAUSE AT ALL, and app.py writes one for EVERY logged cook, so a
    snapshot is the ordinary shape for a cook_log row rather than an edge case."""
    db = _db(tmp_path / "hanger-snapshot")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO recipe_snapshots (recipe_id, user_id, cook_log_id, reason, content, "
              "created_at) VALUES ('acqua-pazza', 1, 212, 'cook', '{}', '2026-07-22 00:00:00')")
    c.commit()
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 1
    assert "recipe_snapshots" in out and "points at cook_log 212" in out
    assert _count(db, "recipe_snapshots", "cook_log_id = 212") == 1


def test_the_rows_naming_each_other_are_still_allowed(tmp_path):
    """The refusal is about rows the script does NOT name. Comment 3 is on post 8 and post 8 points
    at cook 211, all three named, so the ordinary run is unaffected."""
    db = _db(tmp_path / "self-referential")
    c = sqlite3.connect(db)
    assert c.execute("SELECT post_id FROM comments WHERE id=3").fetchone()[0] == 8
    assert c.execute("SELECT cook_log_id FROM shared_posts WHERE id=8").fetchone()[0] == 211
    c.close()
    code, out = _run(db, apply_it=True)
    assert code == 0, out
    assert "7 rows deleted" in out


# ---- and the claim is checked, not asserted ------------------------------------------------------

def test_the_expected_moves_come_from_the_list_not_from_a_written_number():
    assert rdr.expected_moves() == {"comments": 1, "shared_posts": 3, "cook_log": 3}


def test_an_unexplained_move_is_reported_per_table():
    before = {"comments": 2, "shared_posts": 4, "cook_log": 4, "recipe_snapshots": 2, "recipes": 5}
    assert rdr.unexplained_moves(before, {"comments": 1, "shared_posts": 1, "cook_log": 1,
                                          "recipe_snapshots": 2, "recipes": 5}) == []
    drifted = rdr.unexplained_moves(before, {"comments": 1, "shared_posts": 1, "cook_log": 1,
                                             "recipe_snapshots": 1, "recipes": 5})
    assert len(drifted) == 1 and drifted[0].startswith("recipe_snapshots: 2 -> 1")


def test_table_counts_reads_every_table_from_the_schema(tmp_path):
    db = _db(tmp_path / "counts")
    c = sqlite3.connect(db)
    try:
        counts = rdr.table_counts(c)
    finally:
        c.close()
    assert len(counts) > 50, "the count sweep is reading a short list of tables"
    assert counts["cook_log"] == 4 and counts["shared_posts"] == 4
    assert not any(t.startswith("sqlite_") for t in counts)


def test_the_whole_database_is_verified_before_the_commit():
    """⚠️ THE ORDER IS THE POINT. A check after the commit is a post-mortem."""
    body = (REPO / "scripts" / "remove_demo_rows.py").read_text().split("def run(")[1]
    verify, commit = body.find("unexplained_moves(before"), body.find("con.commit()")
    assert verify != -1, "the run no longer compares the whole database"
    assert verify < commit, "the comparison happens after the commit, which is a post-mortem"


def test_the_round_file_declares_exactly_what_this_script_does():
    """⚠️ NOTHING TIED THE DECLARATION TO THE WORK, so the counts and the `except` list could drift
    from DEMO_ROWS and no test would say so. The gate holds the RUN to the round file, and this holds
    the round file to the script."""
    import json
    spec = json.loads((REPO / "golive" / "rounds" /
                       "2026-10-05-remove-demo-rows.json").read_text())
    moves = rdr.expected_moves()
    assert set(spec["counts"]) == set(moves), \
        "the round declares a different set of tables from the ones the script deletes from"
    for table, n in moves.items():
        before, after = spec["counts"][table]
        assert before - after == n, \
            f"the round declares {table} moving by {before - after} and the script deletes {n}"
    assert sorted(spec["tables"]["except"]) == sorted(moves), \
        "the tables excused from the row-for-row half are not the ones the script writes to"
    assert spec["short_circuit"] == "unchanged" and spec["annotations"] == "unchanged"
    for rid in (2, 8, 9, 3, 211, 212, 213):
        assert str(rid) in spec["why"], f"the round's why does not name row {rid}"
