"""RPC handler 集合 — 注册到 RpcServer 处理 14 个 RPC method。

设计：
- 每个 handler 是 async 函数 (params: dict) -> dict
- HandlerContext 持 RpcServer (用于 emit 事件), PauseGate, ConfigHolder, state dict
- 通过 make_handlers(ctx) 拿到 dict[str, Handler]，传给 RpcServer.register

适配说明（与现有 v1 代码对齐）：
- WindowInfo.field_name → window_title（不是 title），client_rect 是 tuple
- trace_logger 尚未提供 list_sessions / get_session_detail — 内联扫 trace/ 目录
- model_config 尚未提供 switch_active_model / test_model_connection — 内联实现
- _start_run 依赖待实现的 AsyncStateMachine（Phase 5），当前 import 失败会抛 ImportError
"""
import asyncio
import json
import logging
import os
import time
from base64 import b64encode
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable

from chaoxing_agent import paths
from chaoxing_agent.core import (
    window_selector,
)
from chaoxing_agent.pause_gate import PauseGate
from chaoxing_agent.config_holder import ConfigHolder, HOT_FIELDS

log = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[dict]]


class HandlerContext:
    """RPC handler 共享上下文。"""

    def __init__(
        self,
        rpc,
        pause_gate: PauseGate,
        config: ConfigHolder,
        state: dict,
    ) -> None:
        self.rpc = rpc
        self.pause_gate = pause_gate
        self.config = config
        self.state = state  # 运行时状态（StateMachine 引用等）


def make_handlers(ctx: HandlerContext) -> dict[str, Handler]:
    return {
        "ping": _ping,
        "list_windows": _list_windows(ctx),
        "get_calibration": _get_calibration(ctx),
        "launch_calibration_wizard": _launch_calibration_wizard(ctx),
        "start_run": _start_run(ctx),
        "stop_run": _stop_run(ctx),
        "pause_decision": _pause_decision(ctx),
        "list_trace_sessions": _list_trace_sessions(ctx),
        "get_session_detail": _get_session_detail(ctx),
        "get_config": _get_config(ctx),
        "update_config": _update_config(ctx),
        "get_model_services": _get_model_services(ctx),
        "switch_model": _switch_model(ctx),
        "test_model": _test_model(ctx),
    }


# =========================================================================
# Ping
# =========================================================================

async def _ping(params: dict) -> dict:
    return {"pong": True, "ts": time.time()}


# =========================================================================
# list_windows
# =========================================================================

def _list_windows(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        proc_name = params.get("process_name", "")
        pid = params.get("pid")

        windows = []
        if pid is not None:
            for w in window_selector.enumerate_visible_windows(int(pid)):
                windows.append(w)
        elif proc_name:
            procs = window_selector.find_processes_by_name(proc_name)
            for p in procs:
                for w in window_selector.enumerate_visible_windows(p.info["pid"]):
                    windows.append(w)

        return {
            "windows": [
                {
                    "hwnd": w.hwnd,
                    "pid": w.pid,
                    "title": w.window_title,
                    "rect": list(w.client_rect),
                }
                for w in windows
            ]
        }
    return handler


# =========================================================================
# get_calibration
# =========================================================================

def _get_calibration(ctx: HandlerContext) -> Handler:
    """返回当前校准状态。通过 ctx.config 读取（测试友好），
    但也回退到磁盘读取（向导写盘后前端重新拉取时保证新鲜）。
    """
    async def handler(params: dict) -> dict:
        cfg = ctx.config.snapshot()
        target = cfg.get("target") or {}
        viewport = cfg.get("viewport") or {}

        last_capture_b64 = _latest_capture_b64()

        return {
            "target": {
                "hwnd": target.get("selected_hwnd"),
                "pid": target.get("pid"),
                "title": target.get("window_title", ""),
                "process_name": target.get("process_name", ""),
            } if target.get("selected_hwnd") else None,
            "client_rect": target.get("client_rect"),
            "phone_viewport_in_client": viewport.get("phone_viewport_in_client"),
            "phone_viewport_ratio": viewport.get("phone_viewport_ratio"),
            "last_capture_b64": last_capture_b64,
        }
    return handler


def _latest_capture_b64() -> str | None:
    """扫 trace/ 目录，读最新 session 最新 step 的截图并 base64 编码。"""
    trace_dir = paths.trace_dir()
    if not trace_dir.is_dir():
        return None
    session_dirs = sorted(
        [d for d in trace_dir.iterdir() if d.is_dir() and d.name.startswith("session_")],
        reverse=True,
    )
    if not session_dirs:
        return None
    try:
        pngs = sorted(session_dirs[0].glob("step_*.png"), reverse=True)
        if not pngs:
            return None
        img_bytes = pngs[0].read_bytes()
        return b64encode(img_bytes).decode("ascii")
    except Exception:
        log.warning("latest_capture_b64 failed", exc_info=True)
        return None


# =========================================================================
# launch_calibration_wizard
# =========================================================================

def _launch_calibration_wizard(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        from chaoxing_agent.calibration_wizard import run_wizard

        # 状态机运行中拒绝
        sm_task = ctx.state.get("sm_task")
        if sm_task and not sm_task.done():
            raise RuntimeError("状态机运行中，标定不可修改")

        # 跑向导（独立子进程），等完成
        await run_wizard()

        # 标定向导写盘后，重新从磁盘加载 config
        config_path = paths.runtime_config_dir() / "config.json"
        if config_path.exists():
            fresh = json.loads(config_path.read_text(encoding="utf-8"))
            # 将 _data 替换为磁盘最新内容
            ctx.config._data = fresh

        # 发事件触发前端刷新
        await ctx.rpc.emit("calibration_changed", {"source": "wizard"})

        return {"accepted": True}
    return handler


# =========================================================================
# start_run / stop_run
# =========================================================================

def _start_run(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        # 启动 AsyncStateMachine（Phase 5 实现）
        try:
            from chaoxing_agent.async_state_machine import AsyncStateMachine
        except ImportError:
            raise RuntimeError(
                "AsyncStateMachine 尚未实现（Phase 5）。"
                "请确保 chaoxing_agent/async_state_machine.py 存在。"
            )

        sm = AsyncStateMachine(ctx, params)
        ctx.state["sm"] = sm
        task = asyncio.create_task(sm.run())
        ctx.state["sm_task"] = task
        return {"session_id": sm.session_id}
    return handler


def _stop_run(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        sm = ctx.state.get("sm")
        if sm:
            sm.request_stop()
        if ctx.pause_gate.is_pending():
            ctx.pause_gate.resolve("quit")
        task = ctx.state.get("sm_task")
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        ctx.state.pop("sm", None)
        ctx.state.pop("sm_task", None)
        return {"stopped_at_step": sm.step if sm else 0}
    return handler


# =========================================================================
# pause_decision
# =========================================================================

def _pause_decision(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        decision = params.get("decision", "retry")
        ctx.pause_gate.resolve(decision)
        return {"ok": True}
    return handler


# =========================================================================
# trace sessions
# =========================================================================

def _trace_dir() -> Path:
    return paths.trace_dir()


def _scan_sessions(limit: int = 50) -> list[dict]:
    """扫描 trace/ 目录，返回 session 摘要列表。"""
    trace_dir = _trace_dir()
    if not trace_dir.is_dir():
        return []
    sessions = []
    for d in sorted(trace_dir.iterdir(), reverse=True):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        stop_reason = None
        stop_file = d / "STOP_REASON.txt"
        if stop_file.exists():
            stop_reason = stop_file.read_text(encoding="utf-8").strip()

        step_count = len(list(d.glob("step_*.json")))
        started_at = d.name.replace("session_", "").replace("_", ":", 1)

        sessions.append({
            "session_id": d.name,
            "started_at": started_at,
            "step_count": step_count,
            "stop_reason": stop_reason,
        })
        if len(sessions) >= limit:
            break
    return sessions


def _read_session_detail(session_id: str, step: int | None = None) -> dict:
    """读取指定 session 的详细数据。"""
    session_dir = _trace_dir() / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"session 不存在: {session_id}")

    if step is not None:
        # 返回指定 step
        step_file = session_dir / f"step_{step:03d}.json"
        if not step_file.exists():
            raise FileNotFoundError(f"step {step} 不存在于 session {session_id}")
        with open(step_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # 返回所有 step
        steps = []
        for f in sorted(session_dir.glob("step_*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                steps.append(json.load(fh))
        return {"session_id": session_id, "steps": steps}


def _list_trace_sessions(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        limit = int(params.get("limit", 50))
        sessions = _scan_sessions(limit=limit)
        return {"sessions": sessions}
    return handler


def _get_session_detail(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        session_id = params["session_id"]
        step = params.get("step")
        return _read_session_detail(session_id, step=step)
    return handler


# =========================================================================
# config
# =========================================================================

def _get_config(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        return ctx.config.snapshot()
    return handler


def _update_config(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        patch = params.get("patch", {})
        hot_fields = await ctx.config.update(patch)
        return {"hot_fields": hot_fields, "new_config": ctx.config.snapshot()}
    return handler


# =========================================================================
# model services
# =========================================================================

def _model_services_path() -> Path:
    return paths.runtime_config_dir() / "model_services.json"


def _read_model_services() -> dict:
    """读 model_services.json，返回完整 dict。"""
    from models.model_config import load_model_services
    return load_model_services()


def _write_model_services(data: dict) -> None:
    """写回 model_services.json。"""
    model_services_path = _model_services_path()
    model_services_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_services_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_model_services(ctx: HandlerContext) -> Handler:
    async def handler(params: dict) -> dict:
        return _read_model_services()
    return handler


def _switch_model(ctx: HandlerContext) -> Handler:
    """切换选定模型角色（vision / solver）到指定 provider key。

    仅多 provider registry 结构支持切换：
      {"vision": {"key1": {...}, "key2": ...}, "selected": {"vision_model": "key1"}}

    v2 单 provider（flat）结构没有可切换 key，必须显式拒绝，避免返回假成功。
    """
    async def handler(params: dict) -> dict:
        role = params["role"]
        key = params["key"]

        services = _read_model_services()
        if role not in services:
            raise ValueError(f"未知角色: {role}，可用角色: {list(services.keys())}")

        section = services[role]
        if isinstance(section, dict) and "api_type" in section:
            raise ValueError(
                f"角色 {role} 当前是单 provider 结构，不能通过 key 切换；"
                "请编辑 config/model_services.json 或使用 CHAOXING_<ROLE>_<FIELD> 覆盖。"
            )
        if not isinstance(section, dict):
            raise ValueError(f"角色 {role} 配置必须是 provider dict")
        if key not in section:
            raise ValueError(f"角色 {role} 下无此 provider key: {key}")

        # 持久化 selected 选择；同时写新字段和旧字段，兼容已有调用。
        if "selected" not in services or not isinstance(services["selected"], dict):
            services["selected"] = {}
        services["selected"][f"{role}_model"] = key
        services["selected"][role] = key
        _write_model_services(services)

        # 通知前端配置变更
        await ctx.rpc.emit("config_changed", {
            "new_config": ctx.config.snapshot(),
            "hot_fields": ["selected"],
        })
        return {"ok": True}
    return handler


def _test_model(ctx: HandlerContext) -> Handler:
    """测试指定模型服务的连通性。"""
    async def handler(params: dict) -> dict:
        role = params["role"]
        key = params["key"]

        services = _read_model_services()
        if role not in services:
            raise ValueError(f"未知角色: {role}")

        # 判断结构获取 provider entry
        section = services[role]
        if isinstance(section, dict) and "api_type" in section:
            entry = section  # 单 provider 结构
        else:
            if key not in section:
                raise ValueError(f"角色 {role} 下无此 provider key: {key}")
            entry = section[key]

        # 加载环境变量
        from chaoxing_agent.core.env_settings import load_env_file
        load_env_file()

        from models.model_config import _build_config, make_openai_client
        try:
            cfg = _build_config(entry)
        except RuntimeError as e:
            # API key 缺失
            return {"ok": False, "latency_ms": None, "error": str(e)}

        client = make_openai_client(cfg)

        t0 = time.time()
        try:
            # 走 OpenAIClient 公开契约；不要越过 wrapper 访问内部 SDK 属性。
            await asyncio.to_thread(
                client.chat,
                [{"role": "user", "content": "Hi"}],
            )
            latency = int((time.time() - t0) * 1000)
            return {"ok": True, "latency_ms": latency, "error": None}
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "error": str(e)}
    return handler
