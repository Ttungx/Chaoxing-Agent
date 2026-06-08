"""RPC handlers 单元测试。

覆盖确定性 handler（ping, config, calibration, pause_decision, model services）；
list_windows 和 trace handlers 只做最小烟雾测试（mock 掉 OS / GUI 调用）。
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from chaoxing_agent.rpc_handlers import make_handlers, HandlerContext
from chaoxing_agent.pause_gate import PauseGate
from chaoxing_agent.config_holder import ConfigHolder


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def ctx(tmp_path: Path, monkeypatch) -> HandlerContext:
    """标准 HandlerContext，config 写 tmp_path 隔离。"""
    monkeypatch.chdir(tmp_path)
    config = ConfigHolder(
        {
            "timing": {"a": 1.0},
            "thresholds": {"b": 0.5},
            "target": {
                "selected_hwnd": 12345,
                "process_name": "test.exe",
                "pid": 100,
                "window_title": "测试窗口",
                "client_rect": [0, 0, 1280, 720],
            },
            "viewport": {
                "phone_viewport_in_client": {"x": 100, "y": 50, "width": 720, "height": 1280},
                "phone_viewport_ratio": {"x": 0.1, "y": 0.1, "width": 0.6, "height": 1.0},
            },
            "runtime": {"max_steps": 10},
        },
        config_path=tmp_path / "config.json",
    )
    rpc = None  # handlers that need rpc only used in non-test paths
    pause = PauseGate()
    state = {}
    return HandlerContext(rpc=rpc, pause_gate=pause, config=config, state=state)


# =========================================================================
# ping
# =========================================================================

@pytest.mark.asyncio
async def test_ping(ctx):
    h = make_handlers(ctx)["ping"]
    r = await h({})
    assert r["pong"] is True
    assert "ts" in r


# =========================================================================
# get_config
# =========================================================================

@pytest.mark.asyncio
async def test_get_config(ctx):
    h = make_handlers(ctx)["get_config"]
    r = await h({})
    assert r["timing"]["a"] == 1.0
    assert r["target"]["selected_hwnd"] == 12345
    assert r["viewport"]["phone_viewport_in_client"]["x"] == 100


# =========================================================================
# update_config — hot fields
# =========================================================================

@pytest.mark.asyncio
async def test_update_config_hot(ctx):
    h = make_handlers(ctx)["update_config"]
    r = await h({"patch": {"timing": {"a": 9.0}, "thresholds": {"b": 0.9}}})
    assert set(r["hot_fields"]) == {"timing", "thresholds"}
    # snapshot 已更新
    assert r["new_config"]["timing"]["a"] == 9.0


@pytest.mark.asyncio
async def test_update_config_cold_rejected(ctx):
    h = make_handlers(ctx)["update_config"]
    r = await h({"patch": {"target": {"selected_hwnd": 999}}})
    assert r["hot_fields"] == []
    # snapshot 不变
    snap = ctx.config.snapshot()
    assert snap["target"]["selected_hwnd"] == 12345


# =========================================================================
# get_calibration
# =========================================================================

@pytest.mark.asyncio
async def test_get_calibration(ctx):
    h = make_handlers(ctx)["get_calibration"]
    r = await h({})
    assert r["target"] is not None
    assert r["target"]["hwnd"] == 12345
    assert r["target"]["title"] == "测试窗口"
    assert r["target"]["pid"] == 100
    assert r["client_rect"] == [0, 0, 1280, 720]
    assert r["phone_viewport_in_client"] is not None
    assert r["phone_viewport_in_client"]["x"] == 100
    # 无 trace 目录时 last_capture_b64 应为 None
    assert r["last_capture_b64"] is None


@pytest.mark.asyncio
async def test_get_calibration_no_target(ctx: HandlerContext):
    """target.selected_hwnd 为 None 时返回 null target。"""
    ctx.config._data["target"] = {"selected_hwnd": None, "pid": None, "window_title": "", "process_name": ""}
    h = make_handlers(ctx)["get_calibration"]
    r = await h({})
    assert r["target"] is None


# =========================================================================
# pause_decision
# =========================================================================

@pytest.mark.asyncio
async def test_pause_decision_resolves_gate(ctx):
    gate_task = asyncio.create_task(ctx.pause_gate.wait(1, "test"))
    await asyncio.sleep(0.01)  # 让 waiter 注册
    h = make_handlers(ctx)["pause_decision"]
    r = await h({"decision": "skip"})
    assert r["ok"] is True
    decision = await asyncio.wait_for(gate_task, timeout=1.0)
    assert decision == "skip"


# =========================================================================
# stop_run
# =========================================================================


@pytest.mark.asyncio
async def test_stop_run_returns_promptly_for_pending_task(ctx):
    class FakeStateMachine:
        def __init__(self):
            self.step = 7
            self.stop_requested = False

        def request_stop(self):
            self.stop_requested = True

    blocker = asyncio.Event()

    async def never_finishes():
        await blocker.wait()

    sm = FakeStateMachine()
    task = asyncio.create_task(never_finishes())
    ctx.state["sm"] = sm
    ctx.state["sm_task"] = task

    h = make_handlers(ctx)["stop_run"]
    result = await asyncio.wait_for(h({}), timeout=0.2)

    assert result == {"stopped_at_step": 7}
    assert sm.stop_requested is True
    assert task.cancelled() or task.cancelling() > 0

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_stop_run_releases_pending_pause_gate(ctx):
    class FakeStateMachine:
        def __init__(self):
            self.step = 3
            self.stop_requested = False

        def request_stop(self):
            self.stop_requested = True

    wait_task = asyncio.create_task(ctx.pause_gate.wait(3, "paused"))
    await asyncio.sleep(0.01)

    sm = FakeStateMachine()
    ctx.state["sm"] = sm
    ctx.state["sm_task"] = asyncio.create_task(asyncio.sleep(10))

    h = make_handlers(ctx)["stop_run"]
    await asyncio.wait_for(h({}), timeout=0.2)

    decision = await asyncio.wait_for(wait_task, timeout=1.0)
    assert decision == "quit"
    assert sm.stop_requested is True


# =========================================================================
# list_windows — sanity (mock 掉 enumerate_visible_windows)
# =========================================================================

@pytest.mark.asyncio
async def test_list_windows_empty(ctx):
    """无匹配进程时返回空列表。"""
    with patch("chaoxing_agent.core.window_selector.enumerate_visible_windows") as mock_enum:
        mock_enum.return_value = []
        h = make_handlers(ctx)["list_windows"]
        r = await h({"process_name": "nonexistent.exe"})
        assert r["windows"] == []


# =========================================================================
# trace sessions — 隔离测试
# =========================================================================

def test_scan_sessions_no_trace_dir(tmp_path: Path, monkeypatch):
    """trace/ 不存在时返回空列表。"""
    from chaoxing_agent.rpc_handlers import _scan_sessions
    monkeypatch.chdir(tmp_path)
    assert _scan_sessions() == []


def test_scan_sessions_with_data(tmp_path: Path, monkeypatch):
    """trace/ 目录有 session 数据时正确读取。"""
    from chaoxing_agent.rpc_handlers import _scan_sessions, _read_session_detail

    monkeypatch.chdir(tmp_path)
    trace = tmp_path / "trace"
    trace.mkdir()

    session_dir = trace / "session_20250101_120000"
    session_dir.mkdir()

    # 写 step 数据
    step_data = {"step": 1, "question": "test", "screenshot": "step_001.png"}
    (session_dir / "step_001.json").write_text(json.dumps(step_data), encoding="utf-8")

    (session_dir / "STOP_REASON.txt").write_text("user stop", encoding="utf-8")

    sessions = _scan_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session_20250101_120000"
    assert sessions[0]["step_count"] == 1
    assert sessions[0]["stop_reason"] == "user stop"

    # get_session_detail
    detail = _read_session_detail("session_20250101_120000")
    assert detail["session_id"] == "session_20250101_120000"
    assert len(detail["steps"]) == 1
    assert detail["steps"][0]["question"] == "test"

    # get single step
    step = _read_session_detail("session_20250101_120000", step=1)
    assert step["step"] == 1
    assert step["question"] == "test"

    # missing step
    with pytest.raises(FileNotFoundError):
        _read_session_detail("session_20250101_120000", step=99)


# =========================================================================
# model services
# =========================================================================

@pytest.mark.asyncio
async def test_get_model_services_returns_dict(ctx):
    """get_model_services 读取真实的 model_services.json 并返回 dict。"""
    h = make_handlers(ctx)["get_model_services"]
    r = await h({})
    assert "vision" in r
    assert "solver" in r
    assert "api_type" in r["vision"]
    assert "base_url" in r["solver"]


# =========================================================================
# switch_model / test_model
# =========================================================================


def test_test_model_uses_openai_client_chat_contract(ctx, monkeypatch):
    """模型测试应调用 OpenAIClient.chat，而不是不存在的 client.client。"""
    h = make_handlers(ctx)["test_model"]
    fake_services = {
        "vision": {
            "api_type": "openai",
            "base_url": "https://example.test/v1",
            "api_key_env": "VISION_API_KEY",
            "model_id": "test-model",
        }
    }
    fake_client = MagicMock()
    fake_client.chat.return_value = "ok"

    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setattr("chaoxing_agent.rpc_handlers._read_model_services", lambda: fake_services)
    monkeypatch.setattr("models.model_config.make_openai_client", lambda cfg: fake_client)

    result = asyncio.run(h({"role": "vision", "key": ""}))

    assert result["ok"] is True
    assert isinstance(result["latency_ms"], int)
    assert result["error"] is None
    fake_client.chat.assert_called_once()


def test_switch_model_rejects_flat_provider_shape(ctx, monkeypatch):
    """flat 单 provider 结构没有可切换 provider key，不能返回假成功。"""
    h = make_handlers(ctx)["switch_model"]
    fake_services = {
        "vision": {
            "api_type": "openai",
            "base_url": "https://example.test/v1",
            "api_key_env": "VISION_API_KEY",
            "model_id": "test-model",
        }
    }

    monkeypatch.setattr("chaoxing_agent.rpc_handlers._read_model_services", lambda: fake_services)

    with pytest.raises(ValueError, match="单 provider"):
        asyncio.run(h({"role": "vision", "key": "other"}))


def test_switch_model_writes_selected_model_key_for_registry(ctx, monkeypatch):
    """多 provider 注册表结构应写 selected.<role>_model，供运行时 loader 和前端共用。"""
    class FakeRpc:
        async def emit(self, event, data):
            self.event = event
            self.data = data

    ctx.rpc = FakeRpc()
    h = make_handlers(ctx)["switch_model"]
    fake_services = {
        "selected": {},
        "vision": {
            "gemini": {
                "api_type": "openai",
                "base_url": "https://example.test/v1",
                "api_key_env": "VISION_API_KEY",
                "model_id": "gemini-2.5-flash",
            }
        },
    }
    written = {}

    monkeypatch.setattr("chaoxing_agent.rpc_handlers._read_model_services", lambda: fake_services)
    monkeypatch.setattr("chaoxing_agent.rpc_handlers._write_model_services", lambda data: written.update(data))

    result = asyncio.run(h({"role": "vision", "key": "gemini"}))

    assert result == {"ok": True}
    assert written["selected"]["vision_model"] == "gemini"
    assert written["selected"]["vision"] == "gemini"  # 兼容旧字段
    assert ctx.rpc.event == "config_changed"
