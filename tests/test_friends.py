"""Friend-graph tests (social sub-stage 1) — the two-user cases the single-user harness can't cover.

Runs on the fast SQLite suite: the `kitchen` fixture builds the test DB + logs in harness user A, and
`_user_client` mints additional users with their own logged-in clients (the harness supports arbitrary
users via ensure_test_user(email=…) + login_test_client). Covers request→accept→list→unfriend, the
reverse-duplicate auto-accept (the one real subtlety), self-friend, the enumeration-safe unknown-email
response, and the structural authz denials. Dialect-independent — the PG echo lives in
test_pg_integration.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app         # noqa: E402
import harness     # noqa: E402

A_EMAIL = harness.HARNESS_USER_EMAIL   # the kitchen client is logged in as this user (A)


def _user_client(email):
    """Create user `email` in the current test DB and return (id, a logged-in test client). Relies on
    the `kitchen` fixture having pointed app.DB at the temp DB first."""
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _statuses(kitchen):
    with kitchen.conn() as c:
        return c.execute("SELECT requester_id, addressee_id, status FROM friendships").fetchall()


# ---- request -> accept -> list (the happy path) --------------------------------------------------

def test_request_accept_list(kitchen):
    a = kitchen.client
    _bid, b = _user_client("friend-b@test.local")

    r = a.post("/api/friends/requests", json={"email": "friend-b@test.local"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    # pending: A sees it outgoing, B sees it incoming — never in the other's bucket
    la = a.get("/api/friends").get_json()
    assert [f["email"] for f in la["outgoing"]] == ["friend-b@test.local"]
    assert la["friends"] == [] and la["incoming"] == []
    lb = b.get("/api/friends").get_json()
    assert [f["email"] for f in lb["incoming"]] == [A_EMAIL]
    assert lb["friends"] == [] and lb["outgoing"] == []

    assert b.post("/api/friends/accept", json={"email": A_EMAIL}).status_code == 200

    # accepted: each sees the other as a friend, nothing pending
    la, lb = a.get("/api/friends").get_json(), b.get("/api/friends").get_json()
    assert [f["email"] for f in la["friends"]] == ["friend-b@test.local"]
    assert [f["email"] for f in lb["friends"]] == [A_EMAIL]
    assert la["incoming"] == [] and la["outgoing"] == []


# ---- the reverse-duplicate auto-accept (the one real correctness subtlety) ------------------------

def test_reverse_duplicate_auto_accepts_one_row(kitchen):
    a = kitchen.client
    _bid, b = _user_client("b@test.local")

    a.post("/api/friends/requests", json={"email": "b@test.local"})     # A -> B pending
    r = b.post("/api/friends/requests", json={"email": A_EMAIL})        # B -> A : mutual intent
    assert r.status_code == 200

    rows = _statuses(kitchen)
    assert len(rows) == 1                       # ONE row, not two
    assert rows[0]["status"] == "accepted"      # auto-accepted, not a second pending

    assert [f["email"] for f in a.get("/api/friends").get_json()["friends"]] == ["b@test.local"]
    assert [f["email"] for f in b.get("/api/friends").get_json()["friends"]] == [A_EMAIL]


def test_idempotent_rerequest_no_duplicate(kitchen):
    a = kitchen.client
    _user_client("b@test.local")
    assert a.post("/api/friends/requests", json={"email": "b@test.local"}).status_code == 200
    assert a.post("/api/friends/requests", json={"email": "b@test.local"}).status_code == 200
    assert len(_statuses(kitchen)) == 1         # composite PK + the fwd-exists branch: no dup, no error


# ---- self-friend + enumeration-safety ------------------------------------------------------------

def test_self_friend_rejected(kitchen):
    r = kitchen.client.post("/api/friends/requests", json={"email": A_EMAIL})
    assert r.status_code == 400
    assert len(_statuses(kitchen)) == 0


def test_request_unknown_email_is_uniform_success_no_row(kitchen):
    a = kitchen.client
    r_unknown = a.post("/api/friends/requests", json={"email": "nobody@nowhere.test"})
    assert r_unknown.status_code == 200 and r_unknown.get_json()["ok"] is True
    assert len(_statuses(kitchen)) == 0                    # no row created for a non-user

    # indistinguishable from a real request: identical status + body
    _user_client("real@test.local")
    r_real = a.post("/api/friends/requests", json={"email": "real@test.local"})
    assert r_real.status_code == r_unknown.status_code
    assert r_real.get_json() == r_unknown.get_json()       # same shape -> can't enumerate accounts


# ---- authorization denials (structural, default-deny) --------------------------------------------

def test_cannot_accept_request_addressed_to_someone_else(kitchen):
    a = kitchen.client
    _user_client("b@test.local")
    _cid, c = _user_client("c@test.local")
    a.post("/api/friends/requests", json={"email": "b@test.local"})     # A -> B
    # C tries to accept A's request (which is addressed to B, not C)
    assert c.post("/api/friends/accept", json={"email": A_EMAIL}).status_code == 404
    assert _statuses(kitchen)[0]["status"] == "pending"    # untouched


def test_accept_nonexistent_request_404(kitchen):
    a = kitchen.client
    _user_client("b@test.local")
    assert a.post("/api/friends/accept", json={"email": "b@test.local"}).status_code == 404


def test_nonparty_cannot_delete_edge(kitchen):
    a = kitchen.client
    _bid, b = _user_client("b@test.local")
    _cid, c = _user_client("c@test.local")
    a.post("/api/friends/requests", json={"email": "b@test.local"})
    b.post("/api/friends/accept", json={"email": A_EMAIL})              # A <-> B accepted
    # C has no edge to B, so deleting "b@test.local" as C is a 404 and leaves the A-B edge intact
    assert c.delete("/api/friends", json={"email": "b@test.local"}).status_code == 404
    assert len(_statuses(kitchen)) == 1


# ---- list buckets + the one DELETE (unfriend / decline / cancel) ---------------------------------

def test_list_buckets_separated(kitchen):
    a = kitchen.client
    _user_client("b@test.local")                  # A -> B : outgoing
    _cid, c = _user_client("c@test.local")        # C -> A : incoming
    _did, d = _user_client("d@test.local")        # A <-> D : friend
    a.post("/api/friends/requests", json={"email": "b@test.local"})
    c.post("/api/friends/requests", json={"email": A_EMAIL})
    a.post("/api/friends/requests", json={"email": "d@test.local"})
    d.post("/api/friends/accept", json={"email": A_EMAIL})

    la = a.get("/api/friends").get_json()
    assert [f["email"] for f in la["outgoing"]] == ["b@test.local"]
    assert [f["email"] for f in la["incoming"]] == ["c@test.local"]
    assert [f["email"] for f in la["friends"]] == ["d@test.local"]


def test_delete_handles_unfriend_and_decline(kitchen):
    a = kitchen.client
    _bid, b = _user_client("b@test.local")

    # unfriend an accepted edge
    a.post("/api/friends/requests", json={"email": "b@test.local"})
    b.post("/api/friends/accept", json={"email": A_EMAIL})
    assert a.delete("/api/friends", json={"email": "b@test.local"}).status_code == 200
    assert len(_statuses(kitchen)) == 0

    # decline a pending request (the SAME handler)
    a.post("/api/friends/requests", json={"email": "b@test.local"})
    assert b.delete("/api/friends", json={"email": A_EMAIL}).status_code == 200
    assert len(_statuses(kitchen)) == 0

    # cancel my own outgoing pending (again, the same handler)
    a.post("/api/friends/requests", json={"email": "b@test.local"})
    assert a.delete("/api/friends", json={"email": "b@test.local"}).status_code == 200
    assert len(_statuses(kitchen)) == 0
