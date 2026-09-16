"""Symmetric encryption for third-party credentials stored on behalf of the user.

Today's only use: a target's basic-auth password (backend/routers/targets.py). This is a
fundamentally different case from a user's own account password (hashed via argon2, never
read back) or an API/reset token (SHA-256'd, only ever compared, never decrypted) — a target's
basic-auth password is a credential to a *different* system that the worker must actually
present on each check, so it inherently has to be reversible. Hashing isn't an option here;
the real choice is plaintext-at-rest vs. symmetric encryption, and given this project's
existing security posture (no known-insecure defaults, JWT_SECRET's fail-fast treatment),
encryption is the right call for credentials a user hands us to a third-party system.

Fernet (from the `cryptography` package) is a standard, simple authenticated symmetric scheme
— no need for anything more elaborate at this project's scale. CREDENTIAL_ENCRYPTION_KEY has
no default (see config.py) and must be set identically on this service AND both worker
regions, since the worker decrypts exactly what this module encrypts. Constructing Fernet at
import time means a malformed/missing key fails the app at startup, not on the first
credential encrypted — matching JWT_SECRET's fail-fast behavior.
"""

from cryptography.fernet import Fernet

from config import settings

_fernet = Fernet(settings.CREDENTIAL_ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext credential for storage. Returns a Fernet token (URL-safe base64
    text), suitable for a TEXT column."""
    return _fernet.encrypt(plaintext.encode()).decode()
