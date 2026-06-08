$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = Join-Path $Root ".dist\python-sidecar"
$WorkPath = Join-Path $DistRoot "build"
$SpecPath = Join-Path $DistRoot "spec"
$OutputPath = Join-Path $DistRoot "dist"
$BinaryDir = Join-Path $Root "src-tauri\binaries"
$TargetName = "chaoxing-agent-python"
$TauriBinaryName = "chaoxing-agent-python-x86_64-pc-windows-msvc.exe"

New-Item -ItemType Directory -Force $DistRoot, $WorkPath, $SpecPath, $OutputPath, $BinaryDir | Out-Null
$env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"

$DataSep = ";"
$PromptData = "$(Join-Path $Root 'prompts')${DataSep}prompts"
$ConfigData = "$(Join-Path $Root 'config\config.json.example')${DataSep}config"
$ModelServicesData = "$(Join-Path $Root 'config\model_services.json.example')${DataSep}config"
$EnvData = "$(Join-Path $Root 'config\.env.example')${DataSep}config"

Push-Location $Root
try {
  uv run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)" 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in the uv environment. Run: uv pip install 'pyinstaller>=6.0.0'"
  }

  uv run pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $TargetName `
    --distpath $OutputPath `
    --workpath $WorkPath `
    --specpath $SpecPath `
    --add-data $PromptData `
    --add-data $ConfigData `
    --add-data $ModelServicesData `
    --add-data $EnvData `
    --hidden-import chaoxing_agent.async_state_machine `
    --hidden-import chaoxing_agent.calibration_subprocess `
    --hidden-import models.model_config `
    --hidden-import models.openai_client `
    --hidden-import win32timezone `
    --collect-submodules win32com `
    chaoxing_agent\__main__.py

  $BuiltExe = Join-Path $OutputPath "$TargetName.exe"
  if (!(Test-Path $BuiltExe)) {
    throw "PyInstaller did not produce $BuiltExe"
  }

  Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $BinaryDir $TauriBinaryName) -Force
  Write-Host "Python sidecar built: $(Join-Path $BinaryDir $TauriBinaryName)"
}
finally {
  Pop-Location
}
