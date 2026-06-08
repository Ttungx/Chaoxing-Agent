"""文本模型作答 — 题干+选项 → SolverResult"""

import json

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from chaoxing_agent import paths
from chaoxing_agent.core.errors import PauseRequiredError, RecoverableError
from models.json_extract import extract_all_json_objects, extract_first_json_object
from models.model_config import ModelConfig, make_openai_client
from schemas.solver_schema import SolverResult


def _load_prompt() -> str:
    """读取文本模型提示词"""
    prompt_path = paths.prompt_path("solver_prompt.txt")
    if not prompt_path.exists():
        raise FileNotFoundError(f"文本模型提示词文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def _extract_all_json(text: str) -> list[dict]:
    """从模型返回文本中提取所有候选 JSON 对象，按出现顺序返回。"""
    return extract_all_json_objects(text)


def _extract_json(text: str) -> dict:
    """从模型返回文本中提取第一个候选 JSON 对象。"""
    try:
        return extract_first_json_object(text)
    except ValueError as e:
        raise RecoverableError("无法从模型返回内容中提取 JSON") from e


def solve(question_type: str, question_text: str, options: dict[str, str], config: ModelConfig) -> SolverResult:
    """发送题干+选项到文本模型，返回 SolverResult"""
    prompt = _load_prompt()
    input_obj = {
        "question_type": question_type,
        "question": question_text,
        "options": options,
    }

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(input_obj, ensure_ascii=False)},
    ]

    if config.api_type == "openai":
        client = make_openai_client(config)
    else:
        raise PauseRequiredError(f"不支持的 api_type: {config.api_type!r}（当前仅支持 'openai'）")

    try:
        raw_text = client.chat(messages)
    except AuthenticationError as e:
        raise PauseRequiredError(f"文本模型鉴权失败: {e}") from e
    except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as e:
        raise RecoverableError(f"文本模型调用失败 (可重试): {type(e).__name__}: {e}") from e

    # 在所有候选 JSON 中挑出第一个能通过 schema 校验的。
    # 避免把模型在文本里"举例"的内嵌 JSON 误当成顶层输出。
    candidates = _extract_all_json(raw_text)
    if not candidates:
        raise PauseRequiredError(f"文本模型返回内容中无法提取 JSON\n原始内容: {raw_text[:500]}")

    last_err: Exception | None = None
    for cand in candidates:
        try:
            return SolverResult.model_validate(cand)
        except Exception as e:
            last_err = e
            continue

    raise PauseRequiredError(
        f"文本模型返回 JSON 校验失败: {last_err}\n原始内容: {raw_text[:500]}"
    ) from last_err
