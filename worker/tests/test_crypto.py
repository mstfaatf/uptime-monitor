"""decrypt_secret() — the worker's half of the basic-auth credential encryption introduced in
Phase 6 prompt 6.2 (backend/security/crypto.py holds the encrypting half). Encrypts directly
with the `cryptography` package using the same CREDENTIAL_ENCRYPTION_KEY conftest.py sets for
the whole test session, rather than importing the backend's module — the two services are
independently deployed and never share a runtime; this mirrors that boundary instead of
cheating around it.
"""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from crypto import decrypt_secret


def _encrypt_with_test_key(plaintext: str) -> str:
    fernet = Fernet(os.environ["CREDENTIAL_ENCRYPTION_KEY"].encode())
    return fernet.encrypt(plaintext.encode()).decode()


def test_decrypt_secret_round_trips_what_the_matching_key_encrypted():
    ciphertext = _encrypt_with_test_key("hunter2")
    assert decrypt_secret(ciphertext) == "hunter2"


def test_decrypt_secret_raises_on_ciphertext_from_a_different_key():
    other_key = Fernet.generate_key()
    ciphertext = Fernet(other_key).encrypt(b"hunter2").decode()
    with pytest.raises(InvalidToken):
        decrypt_secret(ciphertext)
