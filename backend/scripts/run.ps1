# Run the API with uvicorn (run from backend/)
# Usage: .\scripts\run.ps1   or   pwsh -File scripts/run.ps1
Set-Location $PSScriptRoot\..
uvicorn main:app --reload --host 0.0.0.0 --port 8000
