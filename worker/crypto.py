"""Decrypts third-party credentials the backend encrypted — currently, a target's basic-auth
password (see backend/security/crypto.py's docstring for the full reasoning on why this needs
to be reversible, unlike a password/API-key/reset-token hash).

CREDENTIAL_ENCRYPTION_KEY (config.py) must be set to the exact same value as the backend's
copy of this env var — the two services are independently deployed but share one symmetric
key, not two separate ones. Constructing Fernet at import time means a malformed/missing key
fails the worker at startup, not on the first check of a target with basic auth configured.
"""

from cryptography.fernet import Fernet

from config import settings

_fernet = Fernet(settings.CREDENTIAL_ENCRYPTION_KEY.encode())


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a credential encrypted by backend/security/crypto.py's encrypt_secret(). Raises
    cryptography.fernet.InvalidToken if the ciphertext doesn't match this key (e.g. the two
    services' CREDENTIAL_ENCRYPTION_KEY values have drifted) — callers should treat that as a
    per-target failure, not let it crash the whole check cycle (see main.py's check_one)."""
    return _fernet.decrypt(ciphertext.encode()).decode()
