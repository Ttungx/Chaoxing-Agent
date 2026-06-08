"""视觉模型解析 — 截图 → VisionResult"""

import base64
import io

from PIL import Image
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from chaoxing_agent import paths
from chaoxing_agent.core.errors import PauseRequiredError, RecoverableError
from models.json_extract import extract_all_json_objects, extract_first_json_object
from models.model_config import ModelConfig, make_openai_client
from schemas.vision_schema import VisionResult


def _load_prompt() -> str:
    """读取视觉模型提示词"""
    prompt_path = paths.prompt_path("vision_prompt.txt")
    if not prompt_path.exists():
        raise FileNotFoundError(f"视觉模型提示词文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def _image_to_base64_url(image: Image.Image, config: ModelConfig | None = None) -> str:
    """PIL Image → base64 data URL。

    默认保持 PNG；当 config.image_format == "jpeg" 时，仅改编码格式压缩体积，
    不缩放图片，避免视觉模型返回的 box 坐标与原截图尺寸不一致。
    """
    buf = io.BytesIO()
    image_format = (getattr(config, "image_format", "png") or "png").lower()
    if image_format in {"jpg", "jpeg"}:
        quality = int(getattr(config, "image_jpeg_quality", 65) or 65)
        image.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        image.save(buf, format="PNG")
        mime = "image/png"
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _extract_all_json(text: str) -> list[dict]:
    """从模型返回文本中提取所有候选 JSON 对象，按出现顺序返回。"""
    return extract_all_json_objects(text)


def _extract_json(text: str) -> dict:
    """从模型返回文本中提取第一个候选 JSON 对象。"""
    try:
        return extract_first_json_object(text)
    except ValueError as e:
        raise RecoverableError("无法从模型返回内容中提取 JSON") from e


def parse(image: Image.Image, config: ModelConfig) -> VisionResult:
    """发送手机截图到视觉模型，返回结构化 VisionResult"""
    prompt = _load_prompt()
    b64_url = _image_to_base64_url(image, config)

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": [
            {"type": "text", "text": f"图片尺寸: {image.width}x{image.height}，请解析页面结构。"},
            {"type": "image_url", "image_url": {"url": b64_url}},
        ]},
    ]

    if config.api_type == "openai":
        client = make_openai_client(config)
    else:
        raise PauseRequiredError(f"不支持的 api_type: {config.api_type!r}（当前仅支持 'openai'）")

    try:
        raw_text = client.chat(messages)
    except AuthenticationError as e:
        # 401/403 — API key 无效，重试无意义，必须让人介入
        raise PauseRequiredError(f"视觉模型鉴权失败: {e}") from e
    except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as e:
        # 网络/限流/5xx — 可恢复
        raise RecoverableError(f"视觉模型调用失败 (可重试): {type(e).__name__}: {e}") from e

    # 在所有候选 JSON 中挑出第一个能通过 schema 校验的。
    # 避免把模型在文本里"举例"的内嵌 JSON 误当成顶层输出。
    candidates = _extract_all_json(raw_text)
    if not candidates:
        raise PauseRequiredError(f"视觉模型返回内容中无法提取 JSON\n原始内容: {raw_text[:500]}")

    last_err: Exception | None = None
    for cand in candidates:
        try:
            return VisionResult.model_validate(cand)
        except Exception as e:
            last_err = e
            continue

    raise PauseRequiredError(
        f"视觉模型返回 JSON 校验失败: {last_err}\n原始内容: {raw_text[:500]}"
    ) from last_err
