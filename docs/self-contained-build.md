# Self-Contained Windows Build

This project ships as a self-contained Windows program directory:

```text
ChaoxingAgent/
  ChaoxingAgent.exe
  binaries/
    chaoxing-agent-python.exe
  config/
    config.json
    model_services.json
    .env
  trace/
```

The Tauri app starts the bundled Python sidecar and talks to it over the existing NDJSON RPC protocol.

## Prerequisites

The build machine needs:

- Node.js and npm
- Rust toolchain
- uv
- PyInstaller in the uv environment

Install PyInstaller:

```powershell
$env:UV_CACHE_DIR='E:\codex\Chaoxing-Agent\.uv-cache'
uv pip install 'pyinstaller>=6.0.0'
```

Warm Rust dependencies:

```powershell
cd src-tauri
cargo check
```

## Build

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_release_prereqs.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke_sidecar_rpc.ps1
```

If the prerequisite check fails, fix the listed item first.

The build output is a portable program directory at:

```text
.dist/ChaoxingAgent/
```

This flow builds the Tauri release executable with `--no-bundle` and assembles the
portable directory directly, so it does not require WiX or network access to fetch
installer tooling.

## Notes

- `config/.env` is never bundled with real keys.
- First launch copies config templates into the runtime config directory.
- Debug Tauri runs Python from source with `uv run python -m chaoxing_agent --rpc`.
- Release Tauri runs the bundled sidecar from `binaries/chaoxing-agent-python.exe`.
