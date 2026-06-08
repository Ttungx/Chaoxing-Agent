"""从 example 模板初始化真实的 config.json / model_services.json。

example 入库，真实文件由 `.gitignore` 排除。首次运行 `main.py` 时若真实
文件不存在，则从 `*.example` 复制；用户也可以显式调用
`uv run python main.py --init-config` 强制重新生成。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterable

from chaoxing_agent import paths


def _config_dir() -> Path:
    """Resource config template directory.

    Kept as a small function because tests monkeypatch it.
    """
    return paths.resource_config_dir()


def _runtime_config_dir() -> Path:
    """Writable runtime config directory.

    When tests monkeypatch only ``_config_dir`` and do not opt into the new
    packaged runtime env vars, preserve the old behavior of writing beside the
    templates.
    """
    if os.environ.get("CHAOXING_AGENT_DATA_DIR"):
        return paths.runtime_config_dir()
    return _config_dir()


_PAIRS: list[tuple[str, str]] = [
    ("config.json.example", "config.json"),
    ("model_services.json.example", "model_services.json"),
]

_ENV_PAIR: tuple[str, str] = (".env.example", ".env")


def init_config_files(force: bool = False) -> list[tuple[str, str]]:
    """把缺失的真实文件从 example 复制。返回 (src, dst) 列表。

    `force=True` 时仅强制覆盖 JSON 配置；已有 `.env` 不覆盖，避免清空用户 API key。
    如果 `.env` 缺失，则仍会从 `.env.example` 创建。
    """
    src_dir = _config_dir()
    dst_dir = _runtime_config_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    out: list[tuple[str, str]] = []
    for example_name, real_name in _PAIRS:
        src = src_dir / example_name
        dst = dst_dir / real_name
        if not src.exists():
            # example 必须存在
            raise FileNotFoundError(f"模板文件缺失: {src}")
        if dst.exists() and not force:
            continue
        shutil.copyfile(src, dst)
        out.append((str(src), str(dst)))

    env_example, env_real = _ENV_PAIR
    env_src = src_dir / env_example
    env_dst = dst_dir / env_real
    if not env_src.exists():
        raise FileNotFoundError(f"模板文件缺失: {env_src}")
    if not env_dst.exists():
        shutil.copyfile(env_src, env_dst)
        out.append((str(env_src), str(env_dst)))

    return out


def ensure_config_files() -> list[tuple[str, str]]:
    """仅在缺失时复制。供 `main.py` 启动时调用。"""
    return init_config_files(force=False)


def init_env_example() -> Path:
    """刷新 .env.example 模板（不创建真实 .env）。"""
    from chaoxing_agent.core.env_settings import write_default_env
    return write_default_env()
