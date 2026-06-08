"""从 config/.env / 系统环境变量加载模型服务配置。

model_services.json（v2 单 provider 结构）:
  {
    "vision": {"api_type": "openai", "base_url": "...", "api_key_env": "VISION_API_KEY", "model_id": "..."},
    "solver": {"api_type": "openai", "base_url": "...", "api_key_env": "SOLVER_API_KEY", "model_id": "..."}
  }

.env 用于：
  1) 模型 API key（变量名由 provider 的 api_key_env 决定，常见为 VISION_API_KEY / SOLVER_API_KEY）
  2) 可选覆盖 provider 字段：CHAOXING_VISION_<FIELD> / CHAOXING_SOLVER_<FIELD>
     其中 <FIELD> ∈ {base_url, model_id, api_key_env, api_type}
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from chaoxing_agent import paths


def _get_config_dir() -> Path:
    """Runtime config directory."""
    return paths.runtime_config_dir()


# ---------------------------------------------------------------------------
# .env 加载
# ---------------------------------------------------------------------------


def load_env_file(env_path: Path | str | None = None) -> dict[str, str]:
    """加载 config/.env（若存在），并合并到 os.environ。

    返回加载到的 key/value（仅 .env 中的）。
    """
    if env_path is None:
        env_path = _get_config_dir() / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return {}

    raw = dotenv_values(env_path)
    found: dict[str, str] = {}
    for key, value in raw.items():
        if value is None or value.strip() == "":
            continue
        if key not in os.environ:
            os.environ[key] = value
        found[key] = value
    return found


# ---------------------------------------------------------------------------
# model_services.json 覆盖
# ---------------------------------------------------------------------------

_OVERRIDABLE_FIELDS = {"base_url", "model_id", "api_key_env", "api_type"}


def _apply_section_overrides(section: str, services_section: dict) -> int:
    """对单个 section 应用 CHAOXING_<SECTION>_<FIELD> 覆盖。"""
    count = 0
    for field in _OVERRIDABLE_FIELDS:
        env_name = f"CHAOXING_{section}_{field}".upper()
        if env_name not in os.environ:
            continue
        services_section[field] = os.environ[env_name]
        count += 1
    return count


def _apply_model_services_overrides(services: dict) -> int:
    """对 vision 与 solver 两个 section 应用 env 覆盖。"""
    count = 0
    for section in ("vision", "solver"):
        if section not in services or not isinstance(services[section], dict):
            continue
        count += _apply_section_overrides(section, services[section])
    return count


def apply_overrides(model_services: dict) -> tuple[int, int]:
    """从 .env + 系统 env 应用 model_services.json 覆盖。

    返回 (加载的 .env 键数, 应用到 model_services 的项数)。
    """
    loaded = load_env_file()
    n_models = _apply_model_services_overrides(model_services)
    return len(loaded), n_models


# ---------------------------------------------------------------------------
# 模板生成
# ---------------------------------------------------------------------------


def _default_template() -> str:
    """默认 .env.example 内容：仅两行 API key 占位。"""
    return (
        "# ChaoxingAgent — 模型服务 .env\n"
        "# 复制为 config/.env 后填入真实 key：\n"
        "#   cp config/.env.example config/.env\n"
        "# key 由 model_services.json 的 api_key_env 指向的变量名读取。\n"
        "\n"
        "VISION_API_KEY=\n"
        "SOLVER_API_KEY=\n"
    )


def write_default_env(target_path: Path | None = None, model_services: dict | None = None) -> Path:
    """写出 .env 模板（仅含两行 API key 占位）。

    `model_services` 参数仅为兼容旧调用保留；新结构下无需遍历 provider。
    """
    if target_path is None:
        target_path = _get_config_dir() / ".env.example"
    target_path.write_text(_default_template(), encoding="utf-8")
    return target_path


def list_supported_keys() -> list[str]:
    """返回所有支持的 CHAOXING_ 变量名。"""
    keys: list[str] = []
    for section in ("vision", "solver"):
        for field in sorted(_OVERRIDABLE_FIELDS):
            keys.append(f"CHAOXING_{section}_{field}".upper())
    return keys
