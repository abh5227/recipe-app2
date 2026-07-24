"""auth.py — authentication: password hashing (auth-1) + the JSON auth endpoints (auth-2).

auth-1 added the werkzeug password-hash helpers. auth-2 adds the JSON auth endpoints
(signup / login / logout / me) as a Blueprint, plus the invite-consumption logic. Flask-Login itself
(the LoginManager, user_loader, and the 401 unauthorized handler) is wired in app.py — see its
"authentication" block. These endpoints are all PUBLIC; NO existing route is gated yet (that's auth-3).

The endpoints reuse app.orm_session()/app.now_utc() via a call-time `import app` (inside the views) —
a deferred import so this module doesn't import app at load time (app.py imports auth to register the
blueprint + wire the user_loader; a top-level `import app` here would be circular). At request time app
is fully loaded, and reading orm_session() at call time honors BOTH DATABASE_URL and the test-harness
DB redirect (the frozen-engine trap from the Stage-1b miss).
"""
import re

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from models import Invite, User

auth_bp = Blueprint("auth", __name__)

# Deliberately permissive: "local@label.label(.label)*", no spaces. Deliverability isn't our job here —
# we only reject the obviously-malformed (a later verify step / the client can do more). The domain
# labels exclude '.' ([^@\s.]) so each \. boundary is unambiguous — a LINEAR match, no backtracking.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


def hash_password(password):
    """Hash a plaintext password for storage in users.password_hash (werkzeug pbkdf2 by default)."""
    return generate_password_hash(password)


def verify_password(password, password_hash):
    """True iff `password` matches the stored hash (constant-time compare, via werkzeug)."""
    return check_password_hash(password_hash, password)


def _app():
    """Deferred import of app (avoids the app<->auth import cycle); safe to call at request time,
    when app is fully imported. Reads orm_session/now_utc off it fresh so the harness DB redirect holds."""
    import app
    return app


def user_json(user):
    """The PUBLIC shape of a user — NEVER includes password_hash. is_admin is surfaced as a bool
    (it is stored as an int-boolean 0/1)."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
    }


@auth_bp.route("/api/signup", methods=["POST"])
def signup():
    """Create an account. ALWAYS requires a valid, unused, unexpired invite code (gated signup) — the
    matching invite row is CONSUMED (used_by/used_at set) in the SAME transaction as the user insert, so
    account-create and invite-consume are atomic (either both land or neither does). On success the new
    user is logged in and returned (no password_hash). Public — no login required to reach it."""
    app = _app()
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    display_name = (payload.get("display_name") or "").strip() or None
    invite_code = (payload.get("invite_code") or "").strip()

    if not _EMAIL_RE.match(email):
        return jsonify({"error": "a valid email address is required"}), 400
    if not password:
        return jsonify({"error": "a password is required"}), 400
    if not invite_code:
        return jsonify({"error": "an invite code is required"}), 400

    with app.orm_session() as s:
        invite = s.execute(select(Invite).where(Invite.code == invite_code)).scalar_one_or_none()
        if invite is None:
            return jsonify({"error": "that invite code isn't valid"}), 400
        if invite.used_by is not None:                      # single-use, enforced inside the transaction
            return jsonify({"error": "that invite has already been used"}), 400
        # expires_at (if set) is a now_utc()-format "YYYY-MM-DD HH:MM:SS" string — fixed-width, so a
        # lexicographic compare is a chronological compare (no date parsing / no dialect divergence).
        if invite.expires_at is not None and invite.expires_at < app.now_utc():
            return jsonify({"error": "that invite has expired"}), 400
        if s.execute(select(User.id).where(User.email == email)).first() is not None:
            return jsonify({"error": "an account with that email already exists"}), 409

        user = User(
            email=email, password_hash=hash_password(password), display_name=display_name,
            is_admin=0, created_at=app.now_utc(),
        )
        s.add(user)
        s.flush()                                           # assign user.id before consuming the invite
        invite.used_by = user.id
        invite.used_at = app.now_utc()
        s.commit()                                          # user-create + invite-consume: one atomic txn
        body = user_json(user)
        login_user(user)                                    # start the session (sets the signed cookie)
    return jsonify(body), 201


@auth_bp.route("/api/login", methods=["POST"])
def login():
    """Log in with email + password. Generic 'invalid credentials' on ANY failure (unknown email or
    wrong password) so we never leak whether an email is registered. Public."""
    app = _app()
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    with app.orm_session() as s:
        user = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            return jsonify({"error": "invalid credentials"}), 401
        body = user_json(user)
        login_user(user)
    return jsonify(body), 200


@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    """End the session. A no-op (still 200) when nobody is logged in. Public."""
    logout_user()
    return jsonify({"ok": True}), 200


@auth_bp.route("/api/me", methods=["GET"])
def me():
    """The current user, or {"user": null} when logged out. Returns 200 in BOTH cases (SPA-friendly:
    the client branches on user===null at load instead of catching a 401). Public — deliberately NOT
    login_required, so the logged-out case does NOT hit the 401 unauthorized handler."""
    if current_user.is_authenticated:
        return jsonify({"user": user_json(current_user)}), 200
    return jsonify({"user": None}), 200
