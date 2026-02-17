# Run Alembic migrations (run from backend/)
# Usage: .\scripts\migrate.ps1   or   pwsh -File scripts/migrate.ps1
# Requires DATABASE_URL (sync URL is derived: postgresql+asyncpg -> postgresql)
Set-Location $PSScriptRoot\..
alembic upgrade head
