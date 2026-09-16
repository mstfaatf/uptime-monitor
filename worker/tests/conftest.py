"""Session-wide test setup. Must run before any test module imports `config`, `crypto`, or
`main` — all three build/depend on a module-level object that requires
CREDENTIAL_ENCRYPTION_KEY (config.py's Settings(), crypto.py's Fernet(...)) at import time, and
pytest loads conftest.py before collecting test modules, so setting it here (once, for the
whole session) is enough. Not a real secret — this suite never talks to a real database or
encrypts anything meaningful, it just needs *a* validly-shaped Fernet key so the module-level
constructions in config.py/crypto.py don't raise.
"""

import os

os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "rb6dazPc4DmaBkvWvYNyP6LnsEdNoJCNeUbyTxwvY7o=")
