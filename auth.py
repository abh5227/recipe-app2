"""auth.py — authentication: password hashing (auth-1) + the JSON auth endpoints (auth-2/3a).

auth-1 added the werkzeug password-hash helpers. auth-2 added the JSON auth endpoints
(signup / login / logout / me) as a Blueprint, plus the invite-CONSUMPTION logic. auth-3a adds the
admin-gated invite-GENERATION endpoint (POST /api/invites) — completing the invite lifecycle — plus a
list view (GET /api/invites). Flask-Login itself (the LoginManager, user_loader, and the 401
unauthorized handler) is wired in app.py — see its "authentication" block.

The signup/login/logout/me endpoints are PUBLIC; the /api/invites endpoints are ADMIN-gated (login +
is_admin, default-deny per docs/SECURITY.md). NO *existing* app route is gated yet (that's auth-3b) —
auth-3a only ADDS the new admin endpoints; it does not touch list_recipes/create_recipe/etc.

The endpoints reuse app.orm_session()/app.now_utc() via a call-time `import app` (inside the views) —
a deferred import so this module doesn't import app at load time (app.py imports auth to register the
blueprint + wire the user_loader; a top-level `import app` here would be circular). At request time app
is fully loaded, and reading orm_session() at call time honors BOTH DATABASE_URL and the test-harness
DB redirect (the frozen-engine trap from the Stage-1b miss).
"""
import datetime
import re
import secrets
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user
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


def admin_required(view):
    """Default-deny authorization gate (docs/SECURITY.md): the route runs ONLY for a logged-in admin.
    Layered so the two failure modes stay distinct — @login_required first (not logged in → the 401
    unauthorized handler fires), then an explicit is_admin check (logged in but not admin → 403). Used
    by the /api/invites endpoints; is_admin gates ONLY invite generation/listing, not a general
    superpower over other routes."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:                 # int-boolean 0/1; non-admin (0) → deny
            return jsonify({"error": "admin required"}), 403
        return view(*args, **kwargs)
    return wrapper


def _normalize_expiry(raw):
    """Return (stored_value, error). An invite's optional expiry, normalized to the now_utc() format
    ('YYYY-MM-DD HH:MM:SS') so signup's lexicographic `expires_at < now_utc()` compare stays correct.
    Absent/blank → (None, None) (no expiry); malformed → (None, message) so the caller can 400."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    try:
        dt = datetime.datetime.fromisoformat(str(raw).strip())   # accepts 'YYYY-MM-DD' and full datetimes
    except (ValueError, TypeError):
        return None, "expires_at must be an ISO date/datetime (e.g. 2026-12-31 or 2026-12-31 23:59:59)"
    return dt.strftime("%Y-%m-%d %H:%M:%S"), None


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


# ---- admin: invite generation + listing (auth-3a; is_admin-gated, default-deny) -----------------

@auth_bp.route("/api/invites", methods=["POST"])
@admin_required
def create_invite():
    """Generate a new single-use invite (admin only). The code is a cryptographically-random,
    unguessable token (secrets.token_urlsafe) — a predictable/sequential code would let uninvited
    people sign up, defeating the gated pilot. An optional `expires_at` (ISO date/datetime) is
    normalized and stored; else NULL (no expiry). One transaction. Returns the code so the admin can
    share it with the invitee (its purpose), plus created_at/expires_at — nothing else."""
    app = _app()
    payload = request.get_json(silent=True) or {}
    expires_at, err = _normalize_expiry(payload.get("expires_at"))
    if err:
        return jsonify({"error": err}), 400
    code = secrets.token_urlsafe(24)                  # ~32-char, 192-bit token; unguessable, non-sequential
    with app.orm_session() as s:
        invite = Invite(
            code=code, created_by=current_user.id, created_at=app.now_utc(),
            used_by=None, used_at=None, expires_at=expires_at,
        )
        s.add(invite)
        s.commit()
        body = {"code": invite.code, "created_at": invite.created_at, "expires_at": invite.expires_at}
    return jsonify(body), 201


@auth_bp.route("/api/invites", methods=["GET"])
@admin_required
def list_invites():
    """List the invites THIS admin created, with a used/unused flag — for tracking who's been invited
    and whether they've signed up. Least-exposure (docs/SECURITY.md): returns only code/created_at/
    expires_at + a boolean `used`; it deliberately does NOT reveal WHO consumed an invite (no used_by,
    no email), so it can't leak another user's identity."""
    app = _app()
    with app.orm_session() as s:
        rows = s.execute(
            select(Invite.code, Invite.created_at, Invite.expires_at, Invite.used_by)
            .where(Invite.created_by == current_user.id)
            .order_by(Invite.created_at.desc(), Invite.id.desc())
        ).all()
    invites = [
        {"code": r.code, "created_at": r.created_at, "expires_at": r.expires_at, "used": r.used_by is not None}
        for r in rows
    ]
    return jsonify({"invites": invites}), 200
