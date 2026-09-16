"""encrypt_secret() — the backend's half of the basic-auth credential encryption introduced in
Phase 6 prompt 6.2 (worker/crypto.py holds the decrypting half, exercised in worker/tests/
test_crypto.py against its own copy of the same test key). Decrypts here with a raw Fernet
built from the same CREDENTIAL_ENCRYPTION_KEY conftest.py sets, rather than importing the
worker's module — the two services never share a runtime, same boundary as elsewhere in this
codebase (backend/security/ssrf.py vs worker/ssrf.py)."""

import os

from cryptography.fernet import Fernet

from security.crypto import encrypt_secret


def test_encrypt_secret_output_is_not_the_plaintext():
    ciphertext = encrypt_secret("hunter2")
    assert ciphertext != "hunter2"
    assert "hunter2" not in ciphertext


def test_encrypt_secret_is_decryptable_with_the_same_key():
    fernet = Fernet(os.environ["CREDENTIAL_ENCRYPTION_KEY"].encode())
    ciphertext = encrypt_secret("hunter2")
    assert fernet.decrypt(ciphertext.encode()).decode() == "hunter2"
