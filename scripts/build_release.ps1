$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"
$PortableDir = Join-Path $Root ".dist\ChaoxingAgent"
$ReleaseExe = Join-Path $Root "src-tauri\target\release\chaoxing-agent.exe"
$ReleaseSidecar = Join-Path $Root "src-tauri\target\release\chaoxing-agent-python.exe"

Push-Location $Root
try {
  npm --prefix web run typecheck
  npm --prefix web run build
  powershell -ExecutionPolicy Bypass -File scripts\build_python_sidecar.ps1

  npm --prefix web exec tauri -- build --no-bundle

  if (!(Test-Path $ReleaseExe)) {
    throw "Tauri did not produce $ReleaseExe"
  }
  if (!(Test-Path $ReleaseSidecar)) {
    throw "Tauri did not stage $ReleaseSidecar"
  }

  $PortableDirs = @(
    $PortableDir
    (Join-Path $PortableDir "binaries")
    (Join-Path $PortableDir "config")
    (Join-Path $PortableDir "trace")
  )
  New-Item -ItemType Directory -Path $PortableDirs -Force | Out-Null

  Copy-Item -LiteralPath $ReleaseExe -Destination (Join-Path $PortableDir "ChaoxingAgent.exe") -Force
  Copy-Item -LiteralPath $ReleaseSidecar -Destination (Join-Path $PortableDir "binaries\chaoxing-agent-python.exe") -Force
  Copy-Item -LiteralPath (Join-Path $Root "config\config.json.example") -Destination (Join-Path $PortableDir "config\config.json") -Force
  Copy-Item -LiteralPath (Join-Path $Root "config\model_services.json.example") -Destination (Join-Path $PortableDir "config\model_services.json") -Force
  Copy-Item -LiteralPath (Join-Path $Root "config\.env.example") -Destination (Join-Path $PortableDir "config\.env") -Force

  Write-Host "Portable release built: $PortableDir"
}
finally {
  Pop-Location
}
