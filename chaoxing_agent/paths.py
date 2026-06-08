"""Path helpers for source and packaged ChaoxingAgent runtimes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Return the repository root in source mode."""
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """Return whether Python is running from a frozen executable."""
    return bool(getattr(sys, "frozen", False))


def executable_dir() -> Path:
    """Return the directory containing the frozen exe, or project root in source mode."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_root() -> Path:
    """Return immutable bundled resources: prompts and config templates."""
    override = os.environ.get("CHAOXING_AGENT_RESOURCE_DIR")
    if override:
        return Path(override).resolve()
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return executable_dir() / "resources"
    return project_root()


def runtime_root() -> Path:
    """Return writable runtime data root for config and trace output."""
    override = os.environ.get("CHAOXING_AGENT_DATA_DIR")
    if override:
        return Path(override).resolve()
    if is_frozen():
        return executable_dir()
    return project_root()


def resource_config_dir() -> Path:
    return resource_root() / "config"


def runtime_config_dir() -> Path:
    return runtime_root() / "config"


def trace_dir() -> Path:
    if os.environ.get("CHAOXING_AGENT_DATA_DIR") or is_frozen():
        return runtime_root() / "trace"
    return Path("trace")


def prompt_path(name: str) -> Path:
    return resource_root() / "prompts" / name
