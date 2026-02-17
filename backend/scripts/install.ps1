# Install dependencies (run from backend/)
# Usage: .\scripts\install.ps1   or   pwsh -File scripts/install.ps1
Set-Location $PSScriptRoot\..
pip install -r requirements.txt
