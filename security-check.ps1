param([string]$PythonPath = "")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($PythonPath) {
    $python = $PythonPath
} else {
    $localPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    $python = if (Test-Path $localPython) { $localPython } else { (Get-Command python).Source }
}

& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "The installed dependency set is inconsistent." }

& $python -m scripts.check_dependency_policy
if ($LASTEXITCODE -ne 0) { throw "A runtime dependency violates the minimum security policy." }

& $python -m pip_audit -r requirements.txt --progress-spinner off --strict
if ($LASTEXITCODE -ne 0) { throw "The runtime dependency audit found a vulnerability or could not complete." }

& $python -m bandit -q -r app.py gifmaker scripts
if ($LASTEXITCODE -ne 0) { throw "The Python security scan found an issue." }

& $python -m ruff check app.py gifmaker scripts tests
if ($LASTEXITCODE -ne 0) { throw "The Ruff static analysis found an issue." }

& $python -m mypy app.py gifmaker scripts
if ($LASTEXITCODE -ne 0) { throw "The strict type analysis found an issue." }

$zizmorCommand = Get-Command zizmor -ErrorAction SilentlyContinue
if ($zizmorCommand) {
    $zizmor = $zizmorCommand.Source
} else {
    $toolDirectory = Split-Path -Parent $python
    $zizmor = Join-Path $toolDirectory $(if ($IsWindows -or $env:OS -eq "Windows_NT") { "zizmor.exe" } else { "zizmor" })
}
& $zizmor --pedantic .github/workflows
if ($LASTEXITCODE -ne 0) { throw "The GitHub Actions security analysis found an issue." }

Write-Host "Dependency, source, type, and workflow security checks passed."
