# FastAPI API service for Uptime Monitor
FROM python:3.12-slim

WORKDIR /app

# Install dependencies. Upgrade pip first -- the python:3.12-slim base image ships an old pip
# with several known CVEs (mostly path-traversal/tarfile-extraction issues affecting a
# malicious package index or crafted wheel, not this project's threat model directly, but a
# trivial, safe, no-behavior-change fix found via pip-audit in prompt 5.8).
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

EXPOSE 8000
# Run migrations then uvicorn (inline to avoid CRLF issues with script on Windows).
# ${PORT:-8000}: Railway injects PORT and expects the app to bind to it; falls back to 8000
# when PORT is unset (local/Docker Compose), which is the port docker-compose.yml publishes.
#
# --proxy-headers --forwarded-allow-ips='*': without this, uvicorn's ProxyHeadersMiddleware
# only trusts X-Forwarded-For from a direct-connecting peer at 127.0.0.1 (its own default) --
# on Railway the direct peer is Railway's own edge/proxy, never 127.0.0.1, so this was silently
# never trusted and request.client.host stayed whichever internal Railway address happened to
# connect. Confirmed live in prompt 5.8: slowapi's rate limiting (keyed by
# request.client.host) never triggered at all under a real burst against the deployed service
# — every request looked like a different, ungrouped "client". '*' is safe here specifically
# because Railway is the only way to reach this container at all; there is no direct-internet
# path that could spoof this header past a proxy that isn't there.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
