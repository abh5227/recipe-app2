"""scripts/remove_demo_accounts.py, RUN against the real schema.

⚠️ NOTHING CASCADES FROM users, SO THE SCRIPT'S ORDER IS THE WHOLE CORRECTNESS ARGUMENT. All 13
foreign keys pointing at users are ON DELETE NO ACTION, which means the final DELETE on users only
succeeds once every reference has been cleared on purpose. A test that only checked "the accounts
are gone" would pass against a script that deleted nothing and raised, so these check the order and
the survivors as well.

⚠️ AND THE SCRIPT MUST REFUSE AN ACCOUNT THAT OWNS ANYTHING REAL. That is the case where removal is
a decision rather than a cleanup, and the refusal is what makes the script safe to point at live.
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
    "remove_demo_accounts", REPO / "scripts" / "remove_demo_accounts.py")
rda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rda)

KEEP = "real@person.test"


def _db(tmp_path, with_demo=True):
    """The real schema, one real account, and the three demo accounts with demo social rows."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "accounts.db"
    migrate.DB = path
    migrate.migrate(verbose=False)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    users = [(1, KEEP)] + ([(2, "test@test.com"), (3, "alex@demo.test"),
                            (4, "mira@demo.test")] if with_demo else [])
    for uid, email in users:
        c.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES (?,?,?,?)",
                  (uid, email, f"hash-for-{email}", "2026-01-01 00:00:00"))
    c.execute("INSERT INTO recipes (id, name, source, owner) VALUES ('beans','Beans','app',1)")
    if with_demo:
        # a cook each, a post each, the real account's post, and comments that cross over
        for cid, uid in ((209, 2), (214, 3), (215, 4), (300, 1)):
            c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source) "
                      "VALUES (?,'beans',?, '2026-07-01','demo-seed')", (cid, uid))
        for pid, uid in ((1, 2), (6, 3), (7, 4), (8, 1)):
            c.execute("INSERT INTO shared_posts (id, user_id, recipe_id, created_at) "
                      "VALUES (?,?, 'beans', '2026-07-01')", (pid, uid))
        c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
                  "VALUES (1, 8, 3, 'demo on the real post', '2026-07-01')")
        c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
                  "VALUES (3, 8, 1, 'the real account on its own post', '2026-07-01')")
        c.execute("INSERT INTO comments (id, post_id, author_id, body, created_at) "
                  "VALUES (4, 6, 1, 'how hot was the pan?', '2026-07-01')")
        c.execute("INSERT INTO friendships (requester_id, addressee_id, status, created_at) "
                  "VALUES (1, 3, 'accepted', '2026-07-01')")
        c.execute("INSERT INTO invites (id, code, created_by, created_at, used_by) "
                  "VALUES (1, 'CODE', 1, '2026-07-01', 2)")
    c.commit()
    c.close()
    return path


def _count(path, table, where="1=1"):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}').fetchone()[0]
    finally:
        c.close()


# ---- the dry run writes nothing ------------------------------------------------------------------

def test_a_dry_run_changes_nothing(tmp_path):
    """⚠️ THE DEFAULT IS A PREVIEW. Every pass in this repo dry-runs until it is told to apply."""
    path = _db(tmp_path)
    before = path.read_bytes()
    lines = []
    assert rda.run(path, apply_it=False, out=lines.append) == 0
    assert path.read_bytes() == before, "the dry run wrote to the database"
    assert any("dry run, nothing written" in l for l in lines)
    assert _count(path, "users") == 4


def test_the_dry_run_counts_exactly_what_the_apply_deletes(tmp_path):
    """⚠️ ONE WHERE, TWO USES. A preview written as its own query stops describing the run."""
    dry, wet = [], []
    rda.run(_db(tmp_path / "a"), apply_it=False, out=dry.append)
    rda.run(_db(tmp_path / "b"), apply_it=True, out=wet.append)
    nums = lambda lines: [l.split()[-1] for l in lines if l.startswith("    ") and
                          l.split()[-1].isdigit()]
    assert nums(dry) == nums(wet), f"preview {nums(dry)} against run {nums(wet)}"


# ---- the apply, and what survives ----------------------------------------------------------------

def test_the_three_accounts_go_and_the_real_one_stays(tmp_path):
    path = _db(tmp_path)
    assert rda.run(path, apply_it=True, out=lambda *a: None) == 0
    assert _count(path, "users") == 1
    assert _count(path, "users", f"email = '{KEEP}'") == 1


def test_the_real_account_s_login_row_is_untouched(tmp_path):
    """The one thing that must survive byte for byte, or the owner cannot get back in."""
    path = _db(tmp_path)
    row = lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True).execute(
        "SELECT id, email, password_hash, display_name, is_admin, created_at FROM users "
        "WHERE email = ?", (KEEP,)).fetchone()
    was = row()
    rda.run(path, apply_it=True, out=lambda *a: None)
    assert row() == was


def test_the_recipe_and_its_owner_are_untouched(tmp_path):
    path = _db(tmp_path)
    rda.run(path, apply_it=True, out=lambda *a: None)
    assert _count(path, "recipes") == 1
    assert _count(path, "recipes", "owner = 1") == 1


def test_the_real_account_s_own_cook_survives(tmp_path):
    """Only THEIR rows go. A removal that took the owner's cooks would be a data loss."""
    path = _db(tmp_path)
    rda.run(path, apply_it=True, out=lambda *a: None)
    assert _count(path, "cook_log") == 1
    assert _count(path, "cook_log", "user_id = 1") == 1


def test_the_demo_social_rows_all_go(tmp_path):
    path = _db(tmp_path)
    rda.run(path, apply_it=True, out=lambda *a: None)
    assert _count(path, "shared_posts") == 1, "only the real account's post is left"
    assert _count(path, "shared_posts", "user_id = 1") == 1
    assert _count(path, "friendships") == 0
    assert _count(path, "invites") == 0


def test_there_are_no_foreign_key_violations_afterwards(tmp_path):
    """⚠️ THE CHECK THE NO ACTION KEYS EXIST TO FORCE. A dangling user_id is the failure this
    whole ordering question is about."""
    path = _db(tmp_path)
    rda.run(path, apply_it=True, out=lambda *a: None)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.close()


# ---- the collateral is named before it happens ---------------------------------------------------

def test_a_comment_of_the_real_account_s_on_a_demo_post_is_named_in_advance(tmp_path):
    """⚠️ comments.post_id IS ON DELETE CASCADE, so removing a demo post takes the owner's own words
    with it. The script prints the sentence before anything happens, because a person should read
    their own line before it goes."""
    path = _db(tmp_path)
    lines = []
    rda.run(path, apply_it=False, out=lines.append)
    text = "\n".join(lines)
    assert "belong to ANOTHER account" in text
    assert "how hot was the pan?" in text, "the owner's own comment is not named"


def test_that_comment_really_does_go_and_the_one_on_its_own_post_stays(tmp_path):
    """The warning above has to describe what happens, so both halves are checked."""
    path = _db(tmp_path)
    rda.run(path, apply_it=True, out=lambda *a: None)
    assert _count(path, "comments", "id = 4") == 0, "the cascade did not reach it after all"
    assert _count(path, "comments", "id = 3") == 1, "a comment on the owner's own post survives"
    assert _count(path, "comments") == 1


# ---- it refuses an account that owns anything real -----------------------------------------------

@pytest.mark.parametrize("table,col,extra", [
    ("recipes", "owner", "INSERT INTO recipes (id,name,source,owner) VALUES ('d','D','app',3)"),
    ("ratings", "user_id",
     "INSERT INTO ratings (recipe_id,user_id,rating,rated_on) "
     "VALUES ('beans',3,5,'2026-07-01')"),
    ("recipe_snapshots", "user_id",
     "INSERT INTO recipe_snapshots (recipe_id,user_id,reason,content,created_at) "
     "VALUES ('beans',3,'original','{}','2026-07-01')"),
])
def test_it_refuses_when_a_demo_account_owns_something_real(tmp_path, table, col, extra):
    """⚠️ THE CASE WHERE REMOVAL IS A DECISION, NOT A CLEANUP. Measured on live before this was
    written: the three own 0 recipes, 0 snapshots, 0 ratings, 0 queue entries and 0 photos."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute(extra)
    c.commit()
    c.close()
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 1, "it applied anyway"
    assert any("REFUSING" in l for l in lines)
    assert _count(path, "users") == 4, "it must not have deleted anything"


def test_it_refuses_an_account_with_a_real_logged_cook(tmp_path):
    """⚠️ THE REFUSAL GUARDED A FROZEN TABLE. Migration 048 moved ratings INTO cook_log.rating, and
    nothing has written the `ratings` table since, so the list checked a table the app cannot fill
    while cook_log, which holds the outcome data this app exists to capture, was on the delete list
    with no refusal. Measured before the fix: an account with 25 cooks of which 12 were rated was
    deleted with no REFUSING line and exit 0."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source, rating) "
              "VALUES (900,'beans',2,'2026-08-01','app',5)")
    c.commit()
    c.close()
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 1, "it deleted a real cook"
    text = "\n".join(lines)
    assert "REFUSING" in text and "logged cooks" in text
    assert _count(path, "users") == 4, "nothing may be deleted when it refuses"
    assert _count(path, "cook_log", "id = 900") == 1


@pytest.mark.parametrize("source", ["demo-seed", "demo-2b"])
def test_a_demo_cook_does_not_trigger_the_refusal(tmp_path, source):
    """The demo rows are what the script is for, so the refusal has to see past them. Live's three
    accounts hold 4 cook_log rows and every one carries one of these two sources."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source) "
              "VALUES (901,'beans',2,'2026-08-01',?)", (source,))
    c.commit()
    c.close()
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 0
    assert "REFUSING" not in "\n".join(lines)
    assert _count(path, "users") == 1


def test_the_real_ownership_list_covers_cook_log_and_marks_the_frozen_table():
    """Named so the frozen table's silence is never read as coverage again."""
    by_table = {t: (label, extra) for t, _, label, extra in rda.REAL_OWNERSHIP}
    assert "cook_log" in by_table, "the table holding every cook and rating is unguarded"
    assert by_table["cook_log"][1], "cook_log is guarded with no demo-source exception"
    assert "frozen" in by_table["ratings"][0], "the frozen ratings table is not marked as such"


def test_the_totals_say_they_count_direct_deletes_only(tmp_path):
    """⚠️ THE TOTAL DISAGREED WITH THE WARNING ABOVE IT. On a copy of live the preview said 21 rows
    and 22 went, the extra one being the owner's comment taken by a post cascade. The script named
    that row by hand and then printed a total that did not include it."""
    path = _db(tmp_path)
    for apply_it in (False, True):
        lines = []
        rda.run(_db(tmp_path / ("w" if apply_it else "d")), apply_it=apply_it, out=lines.append)
        text = "\n".join(lines)
        assert "DIRECTLY" in text, "the total does not say what it counts"
        assert "CASCADE" in text, "and does not say what it leaves out"


def test_an_absent_account_is_reported_rather_than_skipped(tmp_path):
    """An email this script cannot find is a fact worth printing, not a silent no-op."""
    path = _db(tmp_path, with_demo=False)
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 0
    text = "\n".join(lines)
    assert text.count("NOT PRESENT") == 3
    assert "nothing to do" in text
    assert _count(path, "users") == 1


# ---- the guard, and the shape the repo requires of a script that can write -----------------------

def test_the_script_wires_the_shared_guard_and_takes_a_path():
    src = (REPO / "scripts" / "remove_demo_accounts.py").read_text()
    assert "from corpus_guard import refuse_live" in src, "a second copy of the guard, not the guard"
    assert "def refuse_live" not in src
    assert '"--i-mean-live"' in src and '"--db"' in src and '"--apply"' in src


def test_the_accounts_are_named_by_email_and_not_parameterized():
    """⚠️ AN ID IS A POSITION IN A TABLE AND THE WRONG ONE DELETES THE WRONG PERSON. The list is in
    the file, so a run cannot be pointed at a different set from the command line."""
    assert rda.DEMO_EMAILS == ("test@test.com", "alex@demo.test", "mira@demo.test")
    src = (REPO / "scripts" / "remove_demo_accounts.py").read_text()
    assert "--email" not in src and "--user" not in src, \
        "the account list is settable from the command line now"


@pytest.mark.parametrize("field,value", [("rating", 4.5), ("caption", "best batch yet, less salt")])
def test_a_demo_cook_a_person_later_rated_or_captioned_refuses(tmp_path, field, value):
    """⚠️ THE SOURCE IS NEVER REWRITTEN. edit_cook writes rating, rated_at and caption onto an
    EXISTING row and leaves `source` alone, so a demo-seeded cook that somebody later rated through
    the UI is machine-made by its source and a person's own work by its content. Measured before
    the fix: a demo-seed row carrying rating 4.5 and a caption was deleted with no refusal and exit
    0, and the gate could not see it either, because cook_log 137 to 133 reads the same whether or
    not a rating went with the rows."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute(f"INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source, {field}) "
              f"VALUES (902,'beans',2,'2026-09-02','demo-seed',?)", (value,))
    c.commit()
    c.close()
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 1, "it deleted a person's own work"
    assert "REFUSING" in "\n".join(lines)
    assert _count(path, "cook_log", "id = 902") == 1
    assert _count(path, "users") == 4


def test_a_plain_demo_cook_with_neither_still_passes(tmp_path):
    """The exception has to stay wide enough to do the job it was added for."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO cook_log (id, recipe_id, user_id, cooked_on, source) "
              "VALUES (903,'beans',2,'2026-09-02','demo-2b')")
    c.commit()
    c.close()
    lines = []
    assert rda.run(path, apply_it=True, out=lines.append) == 0
    assert "REFUSING" not in "\n".join(lines)
    assert _count(path, "users") == 1
