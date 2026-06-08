$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"

function Test-CommandOk {
  param(
    [string]$Name,
    [scriptblock]$Command
  )

  try {
    & $Command | Out-Null
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
      Write-Host "[FAIL] $Name"
      return $false
    }
    Write-Host "[ OK ] $Name"
    return $true
  }
  catch {
    Write-Host "[FAIL] $Name - $($_.Exception.Message)"
    return $false
  }
}

$ok = $true

Push-Location $Root
try {
  $ok = (Test-CommandOk "uv environment" { uv run python --version }) -and $ok
  $ok = (Test-CommandOk "PyInstaller installed" {
    uv run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
  }) -and $ok
  $ok = (Test-CommandOk "frontend typecheck" { npm --prefix web run typecheck }) -and $ok

  if (Test-Path (Join-Path $Root "web\dist\index.html")) {
    Write-Host "[ OK ] frontend dist exists"
  }
  else {
    Write-Host "[FAIL] frontend dist missing - run: npm --prefix web run build"
    $ok = $false
  }

  $Sidecar = Join-Path $Root "src-tauri\binaries\chaoxing-agent-python-x86_64-pc-windows-msvc.exe"
  if (Test-Path $Sidecar) {
    Write-Host "[ OK ] Python sidecar exists"
  }
  else {
    Write-Host "[FAIL] Python sidecar missing - run: powershell -ExecutionPolicy Bypass -File scripts\build_python_sidecar.ps1"
    $ok = $false
  }

  Push-Location (Join-Path $Root "src-tauri")
  try {
    $ok = (Test-CommandOk "cargo check offline" { cargo check --offline }) -and $ok
  }
  finally {
    Pop-Location
  }
}
finally {
  Pop-Location
}

if (!$ok) {
  Write-Host ""
  Write-Host "Release prerequisites are not ready."
  Write-Host "Common fixes:"
  Write-Host "  uv pip install 'pyinstaller>=6.0.0'"
  Write-Host "  cargo check"
  Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build_python_sidecar.ps1"
  exit 1
}

Write-Host ""
Write-Host "Release prerequisites are ready."
