# Technical Specification — Multi-User Uptime Monitoring Dashboard

## Goal
Build a multi-tenant web application where users can sign up, log in, and access a private dashboard to add and manage their own URLs. A background worker checks those URLs on a schedule, stores results in a SQL database, and the frontend displays current status and historical data.

## Locked Tech Stack
- Frontend: Next.js
- Backend API: FastAPI (Python)
- Database: PostgreSQL
- Worker: Python background service
- DevOps: Docker (local), Kubernetes manifests (local cluster)

## Services
1. Frontend (Next.js)
2. API (FastAPI)
3. Worker (scheduled URL checker)
4. Database (PostgreSQL)

Each service runs in its own container.

## Authentication
- Email + password authentication
- Password hashing using Argon2 (bcrypt acceptable)
- Auth via HTTP-only cookies
- No tokens stored in localStorage
- Endpoints:
  - POST /auth/register
  - POST /auth/login
  - POST /auth/logout
  - GET /auth/me

## Data Model

### users
- id (primary key)
- email (unique)
- password_hash
- created_at

### targets
- id (primary key)
- user_id (foreign key → users.id)
- url
- name (optional)
- created_at

### checks
- id (primary key)
- target_id (foreign key → targets.id)
- checked_at
- status_code (nullable)
- latency_ms (nullable)
- is_up (boolean)
- error (nullable text)

Indexes:
- targets(user_id)
- checks(target_id, checked_at DESC)

## API Endpoints

### Targets (ownership enforced)
- GET /targets  
  Returns all targets owned by the authenticated user.
- POST /targets  
  Creates a new target owned by the authenticated user.
- DELETE /targets/{id}  
  Deletes a target only if it belongs to the authenticated user.

### Status / History
- GET /targets/status  
  Returns each target with its latest check result.
- GET /targets/{id}/checks?limit=20  
  Returns recent checks for a target (ownership enforced).

## Monitoring Logic
- Worker runs every 5 minutes (configurable)
- For each target:
  - Perform HTTP HEAD or GET request
  - Timeout after 8–10 seconds
  - Measure latency in milliseconds
  - Record timestamp, status code, latency, and error if any
- is_up = true if response received and status code is 2xx or 3xx
- is_up = false otherwise

## Security Requirements
- Strict per-user authorization on all target and check access
- Block SSRF-style URLs:
  - localhost / 127.0.0.1
  - private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
  - link-local (169.254.0.0/16)
- Rate limit login attempts and target creation
- Secrets provided via environment variables only

## Deliverables
- Docker Compose setup for local development
- Kubernetes manifests for local cluster deployment
- Clear separation between frontend, API, and worker
- Clean Git history showing incremental development
