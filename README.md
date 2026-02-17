# Uptime Monitor (Multi-User)

A full-stack web application where users can create accounts, log in, and manage a private dashboard of monitored URLs. A background worker periodically checks those URLs, stores results in a SQL database, and the dashboard displays current status and historical uptime data.

## Architecture
- **Frontend**: Next.js (UI, dashboard, auth flows)
- **Backend API**: FastAPI (authentication, authorization, CRUD, data access)
- **Worker**: Python background service for scheduled URL checks
- **Database**: PostgreSQL
- **DevOps**: Docker for local development, Kubernetes manifests for local clusters

## Core Features
- User signup, login, logout
- Cookie-based authentication (HTTP-only cookies)
- Per-user dashboard (each user only sees their own URLs)
- Add and remove monitored URLs
- Periodic uptime checks (status code, latency, timestamp)
- Store and display recent uptime history

## Repository Structure
- `frontend/` — Next.js frontend
- `backend/` — FastAPI backend
- `worker/` — background monitoring service
- `k8s/` — Kubernetes manifests
- `docker-compose.yml` — local development stack
- `SPEC.md` — detailed technical specification

## Development
This project is designed to run locally using Docker Compose. Kubernetes is used for learning and demonstration via a local cluster (kind or minikube).

Secrets are managed via environment variables. No secrets are committed to the repository.
