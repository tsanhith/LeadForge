"""Password hashing with the standard library (PBKDF2-HMAC-SHA256, per-user salt).

No third-party crypto dependency — ``hashlib.pbkdf2_hmac`` is well-suited for password
storage. The stored format is ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`` so the
iteration count can be raised later without breaking existing hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import os

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iter_s)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)  # constant-time
