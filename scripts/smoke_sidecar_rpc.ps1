$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Sidecar = Join-Path $Root "src-tauri\binaries\chaoxing-agent-python-x86_64-pc-windows-msvc.exe"
$RuntimeDir = Join-Path $Root ".tmp\sidecar-smoke"

if (!(Test-Path $Sidecar)) {
  throw "Sidecar not found: $Sidecar. Run scripts\build_python_sidecar.ps1 first."
}

New-Item -ItemType Directory -Force $RuntimeDir | Out-Null

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Sidecar
$psi.Arguments = "--rpc"
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.Environment["CHAOXING_AGENT_DATA_DIR"] = $RuntimeDir

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi

try {
  [void]$proc.Start()
  $ready = $proc.StandardOutput.ReadLine()
  if ($ready -notmatch '"type"\s*:\s*"event"' -or $ready -notmatch '"event"\s*:\s*"ready"') {
    throw "Expected ready event, got: $ready"
  }

  $proc.StandardInput.WriteLine('{"type":"request","id":1,"method":"ping","params":{}}')
  $proc.StandardInput.Flush()
  $response = $proc.StandardOutput.ReadLine()
  if ($response -notmatch '"type"\s*:\s*"response"' -or $response -notmatch '"pong"\s*:\s*true') {
    throw "Expected ping response, got: $response"
  }

  Write-Host "Sidecar RPC smoke passed"
}
finally {
  if (!$proc.HasExited) {
    $proc.Kill()
  }
  $proc.Dispose()
}
