# FastAPI API service for Uptime Monitor
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

EXPOSE 8000
# Run migrations then uvicorn (inline to avoid CRLF issues with script on Windows).
# ${PORT:-8000}: Railway injects PORT and expects the app to bind to it; falls back to 8000
# when PORT is unset (local/Docker Compose), which is the port docker-compose.yml publishes.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
