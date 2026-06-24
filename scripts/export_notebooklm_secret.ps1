# Refresh GitHub secret from local NotebookLM storage_state.json
# Prerequisite: notebooklm auth check --test must pass

$ErrorActionPreference = "Stop"
$storage = Join-Path $env:USERPROFILE ".notebooklm\profiles\default\storage_state.json"

if (-not (Test-Path $storage)) {
    Write-Error "Not found: $storage`nRun: python scripts/save_notebooklm_auth.py"
}

Write-Host "Checking local auth..."
notebooklm auth check --test
if ($LASTEXITCODE -ne 0) {
    Write-Error "Auth check failed. Re-login first (python scripts/save_notebooklm_auth.py)"
}

Write-Host "Updating NOTEBOOKLM_AUTH_JSON on Battatawada/youtube..."
Get-Content $storage -Raw | gh secret set NOTEBOOKLM_AUTH_JSON --repo Battatawada/youtube
Write-Host "Done. Re-run the GitHub Actions workflow."
