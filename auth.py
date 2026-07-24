"""auth.py — authentication helpers.

auth-1: password hashing only (werkzeug — ships with Flask, no new dependency). NO routes, NO
Flask-Login wiring yet — the LoginManager, the JSON /api/login|logout|signup|me endpoints, and the
gated-signup check land in auth-2. Kept as its own module so auth-2 grows here rather than bloating
app.py.
"""
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password):
    """Hash a plaintext password for storage in users.password_hash (werkzeug pbkdf2 by default)."""
    return generate_password_hash(password)


def verify_password(password, password_hash):
    """True iff `password` matches the stored hash (constant-time compare, via werkzeug)."""
    return check_password_hash(password_hash, password)
