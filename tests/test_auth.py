"""auth-1: password-hash helpers (no routes/login yet)."""
from auth import hash_password, verify_password


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
