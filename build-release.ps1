$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Run install.bat first to create the local Python environment."
}

& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Development dependencies could not be installed." }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "security-check.ps1")
if ($LASTEXITCODE -ne 0) { throw "Security checks failed; the release was not built." }

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; the release was not built." }

& $python -m PyInstaller --noconfirm --clean --distpath release --workpath build GIFmakerAthome.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build the executable." }

$executable = Join-Path $PSScriptRoot "release\GIFmakerAthome.exe"
$checksum = (Get-FileHash $executable -Algorithm SHA256).Hash.ToLowerInvariant()
"$checksum  GIFmakerAthome.exe" | Set-Content (Join-Path $PSScriptRoot "release\SHA256SUMS.txt") -Encoding ascii

Write-Host "Release created at release\GIFmakerAthome.exe"
Write-Host "Checksum created at release\SHA256SUMS.txt"
