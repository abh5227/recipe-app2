"""auth: password-hash helpers (auth-1) + Flask-Login endpoints / invite consumption (auth-2).

The endpoint tests use the `kitchen` fixture's freshly-built temp DB (which includes the users/invites
tables from migration 017). There's no invite-generation endpoint yet (that's is_admin-gated, a later
stage), so `_seed_invite` inserts an inviter user + an invite row directly. The flow the app exercises
is plain dialect-agnostic ORM (select / User / Invite / s.add / s.commit — no on_conflict, no text(),
no ORDER BY on a nullable column), so it behaves identically on Postgres; the SQLite run here covers it.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app as app_module
from auth import hash_password, verify_password


def _fresh():
    """A brand-new test client (independent cookie jar) on the same, harness-redirected app."""
    return app_module.app.test_client()


def _seed_invite(kitchen, code="INV-CODE", expires_at=None, inviter_email="admin@ex.com"):
    """Insert an inviter (is_admin=1) + a single invite row directly; return the invite code."""
    with kitchen.conn() as c:
        c.execute(
            "INSERT INTO users (email, password_hash, display_name, is_admin, created_at) "
            "VALUES (?,?,?,?,?)",
            (inviter_email, hash_password("adminpw"), "Admin", 1, "2026-01-01 00:00:00"),
        )
        uid = c.execute("SELECT id FROM users WHERE email=?", (inviter_email,)).fetchone()[0]
        c.execute(
            "INSERT INTO invites (code, created_by, created_at, expires_at) VALUES (?,?,?,?)",
            (code, uid, "2026-01-01 00:00:00", expires_at),
        )
        c.commit()
    return code


# ---- auth-1: password-hash helpers ----
def test_password_hash_roundtrips_and_rejects_wrong():
    h = hash_password("s3kret-pw")
    assert h != "s3kret-pw"                       # stored hashed, never plaintext
    assert verify_password("s3kret-pw", h) is True
    assert verify_password("wrong-pw", h) is False


def test_hash_is_salted_distinct_per_call():
    # werkzeug salts each hash, so the same password hashes differently but both verify
    a, b = hash_password("same"), hash_password("same")
    assert a != b
    assert verify_password("same", a) and verify_password("same", b)


# ---- auth-2: signup + invite consumption ----
def test_signup_valid_invite_creates_user_and_consumes_invite(kitchen):
    code = _seed_invite(kitchen)
    r = kitchen.client.post("/api/signup", json={
        "email": "New.User@Ex.com", "password": "hunter2", "display_name": "New", "invite_code": code,
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["email"] == "new.user@ex.com"          # normalized to lowercase
    assert body["is_admin"] is False
    assert body["display_name"] == "New"
    assert "password_hash" not in body                 # never leak the hash
    # the invite is consumed (single-use bookkeeping set)
    with kitchen.conn() as c:
        inv = c.execute("SELECT used_by, used_at FROM invites WHERE code=?", (code,)).fetchone()
        usr = c.execute("SELECT id FROM users WHERE email='new.user@ex.com'").fetchone()
    assert inv["used_by"] == usr["id"]
    assert inv["used_at"] is not None
    # and signup logged the new user in — session persists on the same client
    me = kitchen.client.get("/api/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == "new.user@ex.com"


def test_signup_reused_invite_rejected(kitchen):
    code = _seed_invite(kitchen)
    first = kitchen.client.post("/api/signup", json={"email": "a@ex.com", "password": "pw", "invite_code": code})
    assert first.status_code == 201
    second = _fresh().post("/api/signup", json={"email": "b@ex.com", "password": "pw", "invite_code": code})
    assert second.status_code == 400
    assert "used" in second.get_json()["error"].lower()


def test_signup_invalid_invite_rejected(kitchen):
    r = kitchen.client.post("/api/signup", json={"email": "a@ex.com", "password": "pw", "invite_code": "NOPE"})
    assert r.status_code == 400


def test_signup_expired_invite_rejected(kitchen):
    code = _seed_invite(kitchen, code="OLD", expires_at="2000-01-01 00:00:00")
    r = kitchen.client.post("/api/signup", json={"email": "a@ex.com", "password": "pw", "invite_code": code})
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"].lower()


def test_signup_duplicate_email_rejected(kitchen):
    _seed_invite(kitchen, code="C1", inviter_email="admin1@ex.com")
    r1 = kitchen.client.post("/api/signup", json={"email": "dup@ex.com", "password": "pw", "invite_code": "C1"})
    assert r1.status_code == 201
    _seed_invite(kitchen, code="C2", inviter_email="admin2@ex.com")   # a second, unused invite
    r2 = _fresh().post("/api/signup", json={"email": "Dup@ex.com", "password": "pw", "invite_code": "C2"})
    assert r2.status_code == 409


def test_signup_requires_email_password_and_invite(kitchen):
    code = _seed_invite(kitchen)
    assert kitchen.client.post("/api/signup", json={"password": "pw", "invite_code": code}).status_code == 400
    assert _fresh().post("/api/signup", json={"email": "x@ex.com", "invite_code": code}).status_code == 400
    assert _fresh().post("/api/signup", json={"email": "x@ex.com", "password": "pw"}).status_code == 400


# ---- auth-2: login / logout / me ----
def test_login_correct_wrong_and_unknown(kitchen):
    code = _seed_invite(kitchen)
    kitchen.client.post("/api/signup", json={"email": "log@ex.com", "password": "rightpw", "invite_code": code})
    ok = _fresh().post("/api/login", json={"email": "Log@ex.com", "password": "rightpw"})   # email case-insensitive
    assert ok.status_code == 200
    assert ok.get_json()["email"] == "log@ex.com"
    wrong = _fresh().post("/api/login", json={"email": "log@ex.com", "password": "nope"})
    assert wrong.status_code == 401
    assert wrong.get_json()["error"] == "invalid credentials"                                # generic
    unknown = _fresh().post("/api/login", json={"email": "nobody@ex.com", "password": "x"})
    assert unknown.status_code == 401
    assert unknown.get_json()["error"] == "invalid credentials"                              # no email-exists leak


def test_logout_and_me_states(kitchen):
    code = _seed_invite(kitchen)
    c = _fresh()
    c.post("/api/signup", json={"email": "s@ex.com", "password": "pw", "invite_code": code})
    me_in = c.get("/api/me")                              # logged in via signup, same client
    assert me_in.status_code == 200
    assert me_in.get_json()["user"]["email"] == "s@ex.com"
    assert c.post("/api/logout").status_code == 200
    me_out = c.get("/api/me")                             # our SPA-friendly choice: 200 {"user": null}
    assert me_out.status_code == 200
    assert me_out.get_json()["user"] is None


def test_me_logged_out_is_200_null_not_401(kitchen):
    r = _fresh().get("/api/me")                           # never logged in on this client
    assert r.status_code == 200
    assert r.get_json() == {"user": None}


# ---- auth-2: create_admin bootstrap script ----
def test_create_admin_makes_admin_who_can_log_in(kitchen):
    from create_admin import create_admin
    uid = create_admin("Boss@Ex.com", "bosspw", "Boss")
    with kitchen.conn() as c:
        row = c.execute("SELECT email, is_admin, password_hash FROM users WHERE id=?", (uid,)).fetchone()
    assert row["email"] == "boss@ex.com"                  # lowercased
    assert row["is_admin"] == 1
    assert verify_password("bosspw", row["password_hash"])
    login = kitchen.client.post("/api/login", json={"email": "boss@ex.com", "password": "bosspw"})
    assert login.status_code == 200
    assert login.get_json()["is_admin"] is True


def test_create_admin_rejects_duplicate_email(kitchen):
    from create_admin import create_admin
    import pytest
    create_admin("dupe@ex.com", "pw")
    with pytest.raises(ValueError):
        create_admin("Dupe@ex.com", "pw2")


# ---- auth-3a: admin-gated invite generation ----
def _admin_client(kitchen, email="admin@ex.com", pw="adminpw"):
    """A test client logged in as a freshly-bootstrapped admin (is_admin=1)."""
    from create_admin import create_admin
    create_admin(email, pw)
    c = _fresh()
    r = c.post("/api/login", json={"email": email, "password": pw})
    assert r.status_code == 200 and r.get_json()["is_admin"] is True
    return c


def test_admin_generates_invite(kitchen):
    c = _admin_client(kitchen)
    r = c.post("/api/invites", json={})
    assert r.status_code == 201
    body = r.get_json()
    assert body["code"] and body["created_at"] and body["expires_at"] is None
    # the row exists, attributed to the admin, and is unused
    with kitchen.conn() as conn:
        row = conn.execute(
            "SELECT i.used_by, i.used_at, u.email FROM invites i JOIN users u ON u.id = i.created_by "
            "WHERE i.code = ?", (body["code"],)
        ).fetchone()
    assert row["email"] == "admin@ex.com"
    assert row["used_by"] is None and row["used_at"] is None


def test_generated_invite_round_trips_into_signup(kitchen):
    """The full lifecycle: admin GENERATES an invite (3a) → invitee CONSUMES it at signup (auth-2)."""
    c = _admin_client(kitchen)
    code = c.post("/api/invites", json={}).get_json()["code"]
    signup = _fresh().post("/api/signup", json={
        "email": "invitee@ex.com", "password": "pw", "invite_code": code,
    })
    assert signup.status_code == 201
    with kitchen.conn() as conn:
        used_by = conn.execute("SELECT used_by FROM invites WHERE code=?", (code,)).fetchone()["used_by"]
        invitee = conn.execute("SELECT id FROM users WHERE email='invitee@ex.com'").fetchone()["id"]
    assert used_by == invitee                              # consumed by exactly the signing-up user


def test_non_admin_cannot_generate_invite(kitchen):
    """Default-deny: a logged-in NON-admin is refused (403) — the is_admin gate."""
    c = _admin_client(kitchen)
    code = c.post("/api/invites", json={}).get_json()["code"]
    user_client = _fresh()                                 # signup logs this client in as a non-admin
    user_client.post("/api/signup", json={"email": "u@ex.com", "password": "pw", "invite_code": code})
    r = user_client.post("/api/invites", json={})
    assert r.status_code == 403
    assert "admin" in r.get_json()["error"].lower()


def test_logged_out_cannot_generate_invite(kitchen):
    r = _fresh().post("/api/invites", json={})             # not logged in → the 401 login gate
    assert r.status_code == 401


def test_generated_codes_are_random_and_distinct(kitchen):
    c = _admin_client(kitchen)
    codes = {c.post("/api/invites", json={}).get_json()["code"] for _ in range(5)}
    assert len(codes) == 5                                 # all distinct (not sequential/predictable)
    assert all(len(code) >= 20 for code in codes)          # long, high-entropy token


def test_invite_expiry_is_generated_and_enforced(kitchen):
    """Optional expiry: an admin sets a past expiry → the generated code is rejected at signup."""
    c = _admin_client(kitchen)
    r = c.post("/api/invites", json={"expires_at": "2000-01-01"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["expires_at"] == "2000-01-01 00:00:00"     # normalized to now_utc() format
    signup = _fresh().post("/api/signup", json={
        "email": "late@ex.com", "password": "pw", "invite_code": body["code"],
    })
    assert signup.status_code == 400
    assert "expired" in signup.get_json()["error"].lower()


def test_invite_bad_expiry_rejected(kitchen):
    c = _admin_client(kitchen)
    r = c.post("/api/invites", json={"expires_at": "not-a-date"})
    assert r.status_code == 400


# ---- auth-3a: admin invite listing (least-exposure) ----
def test_admin_lists_own_invites_with_used_status(kitchen):
    c = _admin_client(kitchen)
    code = c.post("/api/invites", json={}).get_json()["code"]
    before = c.get("/api/invites").get_json()["invites"]
    assert any(i["code"] == code and i["used"] is False for i in before)
    # consume it, then it flips to used
    _fresh().post("/api/signup", json={"email": "x@ex.com", "password": "pw", "invite_code": code})
    after = c.get("/api/invites").get_json()["invites"]
    mine = next(i for i in after if i["code"] == code)
    assert mine["used"] is True
    # least-exposure: never leak WHO consumed it (no used_by / email in the payload)
    assert all("used_by" not in i and "email" not in i for i in after)


def test_non_admin_cannot_list_invites(kitchen):
    c = _admin_client(kitchen)
    code = c.post("/api/invites", json={}).get_json()["code"]
    user_client = _fresh()
    user_client.post("/api/signup", json={"email": "u@ex.com", "password": "pw", "invite_code": code})
    assert user_client.get("/api/invites").status_code == 403
    assert _fresh().get("/api/invites").status_code == 401   # logged out → 401


# ---- auth-3b: the login gate (private pilot — reads + writes require login) ----
def test_gated_read_route_401_then_200(kitchen):
    """A read route is gated: 401 unauthenticated, 200 as the logged-in harness client."""
    anon = _fresh()                                       # fresh cookie jar → not logged in
    blocked = anon.get("/api/recipes")
    assert blocked.status_code == 401
    assert blocked.get_json() == {"error": "authentication required"}
    assert kitchen.client.get("/api/recipes").status_code == 200   # harness client is authenticated


def test_gated_write_route_401_unauthenticated(kitchen):
    r = _fresh().post("/api/recipes", json={"name": "X", "ingredients": [], "steps": []})
    assert r.status_code == 401                           # write also gated (no auth → blocked)


def test_public_routes_reachable_unauthenticated(kitchen):
    anon = _fresh()
    # /api/me is public: 200 with {user:null} when logged out (a gated route would 401 instead)
    me = anon.get("/api/me")
    assert me.status_code == 200 and me.get_json() == {"user": None}
    # /api/login is public: reaching the handler (bad creds → 401 "invalid credentials"), NOT the
    # gate's 401 "authentication required" — proves the allowlist lets it through to the view.
    login = anon.post("/api/login", json={"email": "nobody@ex.com", "password": "x"})
    assert login.status_code == 401 and login.get_json()["error"] == "invalid credentials"
    # the SPA shell (/) is not gated (must load before auth) — never the gate's 401
    assert anon.get("/").status_code != 401


def test_logged_out_kitchen_client_is_blocked(kitchen_logged_out):
    """The make_kitchen(login=False) opt-out yields an unauthenticated client (gated → 401)."""
    assert kitchen_logged_out.client.get("/api/recipes").status_code == 401
