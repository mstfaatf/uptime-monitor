# Uptime Monitor worker: periodic HTTP checks, writes to Postgres
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip first -- see backend/Dockerfile's comment on the same line (same base-image CVEs).
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
