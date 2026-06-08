"""模型配置 — 读取 model_services.json + 客户端工厂。

新结构（v2 单 provider / OpenAI 兼容）：
  {
    "vision": {
      "api_type": "openai",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GOOGLE_API_KEY",
      "model_id": "gemini-2.5-flash",
      "extra_body": {"google": {"thinking_config": {"thinking_level": "low"}}}     // 可选
    },
    "solver": {
      "api_type": "openai",
      "base_url": "https://api.deepseek.com",
      "api_key_env": "DEEPSEEK_API_KEY",
      "model_id": "deepseek-chat",
      "extra_body": {"thinking": {"type": "enabled"}},                              // 可选
      "reasoning_effort": "high"                                                    // 可选
    }
  }

每个 section 只配一个 OpenAI 兼容 provider；
API key 从 api_key_env 指向的环境变量读，永远不写入 JSON。
可选字段 extra_body / reasoning_effort / use_response_format 透传到 OpenAI SDK。
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from chaoxing_agent import paths


@dataclass
class ModelConfig:
    api_type: str      # 当前固定 "openai"
    base_url: str
    api_key: str       # 已从环境变量读取的实际值
    model_id: str
    extra_body: dict = field(default_factory=dict)
    reasoning_effort: str | None = None
    use_response_format: bool = True
    max_tokens: int | None = None
    temperature: float | None = None
    image_format: str = "png"
    image_jpeg_quality: int = 65


def _get_config_dir() -> Path:
    return paths.runtime_config_dir()


def load_model_services() -> dict:
    """读取 model_services.json"""
    path = _get_config_dir() / "model_services.json"
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_api_key(env_var: str) -> str:
    """从环境变量读取 API Key"""
    key = os.environ.get(env_var, "")
    if not key:
        raise RuntimeError(
            f"环境变量 {env_var} 未设置。请设置后重试。\n"
            f"示例: set {env_var}=your-api-key"
        )
    return key


def _build_config(entry: dict) -> ModelConfig:
    api_type = entry.get("api_type")
    if api_type != "openai":
        raise ValueError(
            f"不支持的 api_type: {api_type!r}（当前仅支持 'openai' 兼容协议）"
        )
    return ModelConfig(
        api_type=api_type,
        base_url=entry["base_url"],
        api_key=_get_api_key(entry["api_key_env"]),
        model_id=entry["model_id"],
        extra_body=entry.get("extra_body") or {},
        reasoning_effort=entry.get("reasoning_effort"),
        use_response_format=bool(entry.get("use_response_format", True)),
        max_tokens=entry.get("max_tokens"),
        temperature=entry.get("temperature"),
        image_format=(entry.get("image_format") or "png").lower(),
        image_jpeg_quality=int(entry.get("image_jpeg_quality", 65)),
    )


def _select_role_entry(services: dict, role: str) -> dict:
    """返回 role 对应的 provider entry。

    兼容两种结构：
      1) v2 单 provider: {"vision": {"api_type": "openai", ...}}
      2) 多 provider registry: {"selected": {"vision_model": "gemini"}, "vision": {"gemini": {...}}}

    selected.<role>_model 是新字段；selected.<role> 作为旧 RPC 写法兼容。
    """
    section = services[role]
    if isinstance(section, dict) and "api_type" in section:
        return section

    selected = services.get("selected") or {}
    selected_key = selected.get(f"{role}_model") or selected.get(role)
    if not selected_key:
        raise KeyError(f"model_services.selected.{role}_model 未设置")
    if selected_key not in section:
        raise KeyError(f"model_services.{role} 中不存在 provider: {selected_key}")
    return section[selected_key]


def get_vision_config(services: dict) -> ModelConfig:
    """读取 vision provider 配置。"""
    return _build_config(_select_role_entry(services, "vision"))


def get_solver_config(services: dict) -> ModelConfig:
    """读取 solver provider 配置。"""
    return _build_config(_select_role_entry(services, "solver"))


def make_openai_client(config: ModelConfig):
    """根据 ModelConfig 构造 OpenAIClient（透传可选字段）。"""
    from models.openai_client import OpenAIClient
    return OpenAIClient(
        config,
        extra=config.extra_body,
        reasoning_effort=config.reasoning_effort,
        use_response_format=config.use_response_format,
    )
