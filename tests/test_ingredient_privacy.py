"""GET /api/ingredients/<iid> is gated by ownership (Panel stage 2a).

The route was a bare primary-key lookup. Any logged-in user could read any row by id, and ids are
slugified NAMES (`garlic`, `egg_pasta`), so the id space is guessable by typing food words. Nothing
leaked, because every row was shared, but the Panel's stage 3 creates the first personal rows and
this had to be closed before there was anything behind it to take.

⚠️ THE ONE TEST THAT MATTERS IS test_user_B_cannot_read_user_As_personal_row. Everything else here
is either the behavior-neutral proof (shared rows still serve to everyone) or a property of the
refusal (uniform, childless, unguessable).

Personal rows are inserted directly. The create path that stamps an owner does not exist yet (that
is stage 3), so a direct insert is the only way to have one, and it is also the honest fixture: it
builds exactly the row shape stage 3 will produce, with nothing else in the way.
"""
import app
import harness


def _client(email):
    """A second logged-in client, mirroring test_comments.py::_user_client."""
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _personal(kitchen, iid, name, owner):
    """A row owned by one user. concept MUST be supplied (migration 031 defaults it to '' and a
    partial unique index permits exactly one such row) — the stage-1 lesson, applied."""
    with kitchen.conn() as c:
        c.execute(
            "INSERT INTO ingredients (id, name, descr, concept, owner, source, created_at) "
            "VALUES (?,?,?,?,?,'app',?)",
            (iid, name, f"{name}, privately kept", iid, owner, app.now_utc()),
        )


# ---- behavior-neutral on today's data ------------------------------------------------------------

def test_all_36_shared_rows_still_serve_to_the_harness_user(kitchen):
    """⚠️ THE NO-REGRESSION PROOF. Every row in the app today is owner NULL, so the gate must block
    nothing. Not a sample: all 36, because a check that passes garlic and fails one other row would
    be a silent hole in the field guide."""
    with kitchen.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM ingredients")]
    assert len(ids) == 36
    assert kitchen.count("ingredients", "owner IS NULL") == 36
    for iid in ids:
        r = kitchen.client.get(f"/api/ingredients/{iid}")
        assert r.status_code == 200, iid
        assert r.get_json()["id"] == iid


def test_a_shared_row_serves_to_a_DIFFERENT_user_too(kitchen):
    """Shared means shared. A second account reads the same row, with the same body."""
    _, b = _client("privacy-b@test.local")
    mine = kitchen.client.get("/api/ingredients/garlic").get_json()
    theirs = b.get("/api/ingredients/garlic")
    assert theirs.status_code == 200
    assert theirs.get_json() == mine


# ---- the hole being closed -----------------------------------------------------------------------

def test_user_A_can_read_their_OWN_personal_row(kitchen):
    """The gate is an ownership check, not a ban on personal rows."""
    a_id, a = _client("privacy-a@test.local")
    _personal(kitchen, "a_gochujang", "Gochujang", a_id)
    r = a.get("/api/ingredients/a_gochujang")
    assert r.status_code == 200
    d = r.get_json()
    assert d["id"] == "a_gochujang"
    assert d["name"] == "Gochujang"


def test_user_B_cannot_read_user_As_personal_row(kitchen):
    """⚠️ THIS IS THE FIX. Before it, B got 200 and A's whole row by typing a guessable id."""
    a_id, _ = _client("privacy-a@test.local")
    _, b = _client("privacy-b@test.local")
    _personal(kitchen, "a_gochujang", "Gochujang", a_id)

    r = b.get("/api/ingredients/a_gochujang")
    assert r.status_code == 404
    assert r.get_json() == {"error": "ingredient not found"}


def test_the_refusal_carries_none_of_the_row(kitchen):
    """Not just "no 200". The body must not carry the name, the description, or the id back — a
    refusal that echoes what it refused is the same leak with a worse status code."""
    a_id, _ = _client("privacy-a@test.local")
    _, b = _client("privacy-b@test.local")
    _personal(kitchen, "a_kombu", "Kombu", a_id)

    body = b.get("/api/ingredients/a_kombu").get_data(as_text=True)
    assert "Kombu" not in body
    assert "privately kept" not in body
    assert "a_kombu" not in body


def test_the_children_of_a_hidden_row_are_not_served_either(kitchen):
    """The route also returns season, regions and used_in. Those are separate queries keyed on the
    same id, so a fix that refused the row but still ran them would hand back the shape of it."""
    a_id, _ = _client("privacy-a@test.local")
    _, b = _client("privacy-b@test.local")
    _personal(kitchen, "a_yuzu", "Yuzu", a_id)
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredient_seasons (ingredient_id, month) VALUES ('a_yuzu', 12)")
        rid = c.execute("SELECT id FROM regions LIMIT 1").fetchone()["id"]
        c.execute("INSERT INTO ingredient_regions (ingredient_id, region_id, position) "
                  "VALUES ('a_yuzu', ?, 0)", (rid,))

    r = b.get("/api/ingredients/a_yuzu")
    assert r.status_code == 404
    assert set(r.get_json()) == {"error"}      # no season / regions / used_in keys at all


def test_A_still_sees_their_own_row_while_B_is_refused(kitchen):
    """Both halves in one test, because the failure mode worth catching is a gate that hides the row
    from EVERYONE, which would pass the refusal test on its own."""
    a_id, a = _client("privacy-a@test.local")
    _, b = _client("privacy-b@test.local")
    _personal(kitchen, "a_shiso", "Shiso", a_id)
    assert a.get("/api/ingredients/a_shiso").status_code == 200
    assert b.get("/api/ingredients/a_shiso").status_code == 404


# ---- the refusal is uniform ----------------------------------------------------------------------

def test_not_yours_is_indistinguishable_from_does_not_exist(kitchen):
    """⚠️ WHY 404 AND NOT 403. Status AND body match byte for byte, so a guesser walking food words
    learns nothing about which ones somebody keeps privately. 403 would answer that question."""
    a_id, _ = _client("privacy-a@test.local")
    _, b = _client("privacy-b@test.local")
    _personal(kitchen, "a_gochujang", "Gochujang", a_id)

    hidden = b.get("/api/ingredients/a_gochujang")
    absent = b.get("/api/ingredients/no_such_ingredient_at_all")
    assert hidden.status_code == absent.status_code == 404
    assert hidden.get_data() == absent.get_data()


def test_a_nonexistent_id_still_404s(kitchen):
    """The pre-existing behavior, pinned so the new predicate can't turn a miss into a 500."""
    r = kitchen.client.get("/api/ingredients/definitely_not_a_food")
    assert r.status_code == 404
    assert r.get_json() == {"error": "ingredient not found"}


# ---- the login gate underneath -------------------------------------------------------------------

def test_an_anonymous_request_is_still_401(kitchen_logged_out):
    """The ownership check sits BEHIND the login gate and does not replace it. An unauthenticated
    request never reaches current_user.id."""
    r = kitchen_logged_out.client.get("/api/ingredients/garlic")
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


def test_the_route_is_not_on_the_public_allowlist(kitchen):
    """Pins the gate at its source, not just its effect."""
    assert "get_ingredient" not in app.PUBLIC_ENDPOINTS
