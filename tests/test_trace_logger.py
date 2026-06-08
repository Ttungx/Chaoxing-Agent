"""trace_logger 的回归测试。"""

import json
import pytest
from PIL import Image

from chaoxing_agent.core.trace_logger import TraceLogger


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """隔离 trace 目录到 tmp_path。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_step_data(step_num=1, img=None):
    return {
        "step": step_num,
        "screenshot_img": img or Image.new("RGB", (10, 10), (255, 0, 0)),
        "page_state": "question",
        "question_type": "single_choice",
        "question": "示例题",
        "options": {"A": "a", "B": "b"},
        "vision_confidence": {"text": 0.9, "layout": 0.9},
        "vision_raw_json": {"x": 1},
        "solver_answer": ["A"],
        "solver_confidence": 0.95,
        "solver_reason": "ok",
        "solver_raw_json": {"y": 2},
        "clicked_options": [],
        "next_button": {"box": [0, 0, 10, 10]},
        "page_changed": True,
        "error": None,
    }


def test_save_step_does_not_mutate_caller_dict(trace_dir):
    """save_step 不应破坏调用方传入的 dict。"""
    logger = TraceLogger()
    step_data = _make_step_data()
    snapshot = dict(step_data)
    snapshot["screenshot_img"] = step_data["screenshot_img"]  # PIL Image 不可 hash 进 dict 但可比较
    has_screenshot_before = "screenshot_img" in step_data

    logger.save_step(step_data)

    assert "screenshot_img" in step_data, "save_step 不应弹出 caller 的 screenshot_img"
    # 其它字段也应原样
    assert step_data["step"] == snapshot["step"]
    assert step_data["page_state"] == snapshot["page_state"]
    assert step_data["solver_answer"] == snapshot["solver_answer"]


def test_save_step_creates_screenshot_and_json(trace_dir):
    logger = TraceLogger()
    step_data = _make_step_data()
    logger.save_step(step_data)
    session = logger.session_dir
    assert (session / "step_001.png").exists()
    assert (session / "step_001.json").exists()


def test_save_step_json_does_not_contain_image_field(trace_dir):
    """JSON 文件不应包含 PIL Image（无法序列化）。"""
    logger = TraceLogger()
    step_data = _make_step_data()
    logger.save_step(step_data)
    json_path = logger.session_dir / "step_001.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "screenshot_img" not in data


def test_save_pause_creates_subdir_with_files(trace_dir):
    logger = TraceLogger()
    img = Image.new("RGB", (10, 10))
    logger.save_pause(
        step_num=1,
        screenshot=img,
        vision_result={"page_state": "unknown"},
        solver_result={"answer": ["A"]},
        reason="test reason",
    )
    pause_dir = logger.session_dir / "pause_step_001"
    assert (pause_dir / "screenshot_at_pause.png").exists()
    assert (pause_dir / "vision_result.json").exists()
    assert (pause_dir / "solver_result.json").exists()
    assert (pause_dir / "pause_reason.txt").read_text(encoding="utf-8") == "test reason"


def test_save_pause_handles_none_solver(trace_dir):
    logger = TraceLogger()
    img = Image.new("RGB", (10, 10))
    logger.save_pause(
        step_num=2,
        screenshot=img,
        vision_result={"page_state": "question"},
        solver_result=None,
        reason="no solver",
    )
    pause_dir = logger.session_dir / "pause_step_002"
    assert not (pause_dir / "solver_result.json").exists()  # None 时不写


def test_save_stop_writes_reason_file(trace_dir):
    logger = TraceLogger()
    logger.save_stop("用户中断")
    assert (logger.session_dir / "STOP_REASON.txt").read_text(encoding="utf-8") == "用户中断"


def test_trace_logger_uses_runtime_trace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOXING_AGENT_DATA_DIR", str(tmp_path))
    logger = TraceLogger()
    assert logger.session_dir.parent == tmp_path / "trace"
