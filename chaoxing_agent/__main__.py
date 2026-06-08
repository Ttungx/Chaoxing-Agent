"""`python -m chaoxing_agent --rpc` 入口。

Rust Tauri 侧通过 `uv run python -m chaoxing_agent --rpc` 启动本包，
stdin/stdout 跑 NDJSON RPC，stderr 走原生日志（被 Tauri 侧转发到 log 通道）。

本入口负责：
1. 解析 `--rpc`（目前是唯一支持的运行模式；保留扩展位）
2. 初始化 config（首次运行从 .example 复制）
3. 构造 HandlerContext：ConfigHolder / PauseGate / state dict
4. 注册 14 个 RPC handler
5. 启动 RpcServer.serve()，先 emit `ready` 事件再进入主循环

启动顺序必须保证：
- `ready` 事件 flush 到 stdout 后，serve() 才进入 readline
- 这样 Tauri 侧 `app.listen("ready", ...)` 拿到事件时，子进程已准备好处理请求
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 让 `python -m chaoxing_agent` 跑在项目根（main.py / config/ / models/ 同级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from chaoxing_agent import paths
from chaoxing_agent.config_holder import ConfigHolder
from chaoxing_agent.core.config_init import ensure_config_files
from chaoxing_agent.pause_gate import PauseGate
from chaoxing_agent.rpc_handlers import HandlerContext, make_handlers
from chaoxing_agent.rpc_server import RpcServer


def _load_initial_config() -> dict:
    """从 config/config.json 读初始 dict；缺失时初始化。"""
    ensure_config_files()
    config_path = paths.runtime_config_dir() / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        # 配置文件损坏不应阻塞 RPC 启动（前端可走 update_config 修复）
        logging.warning(f"config.json 读取失败，使用空配置: {e}")
        return {}


def _build_server() -> RpcServer:
    initial = _load_initial_config()
    config = ConfigHolder(initial=initial)
    pause_gate = PauseGate()
    state: dict = {}

    # 先建 RpcServer（handler emit 需要它的引用），再绑 ctx
    # 把 sys.stdout/stdin 包成 RpcServer 期望的 write_line/readline 接口
    server = RpcServer(stdin=_StdinAdapter(), stdout=_StdoutAdapter())
    ctx = HandlerContext(
        rpc=server,
        pause_gate=pause_gate,
        config=config,
        state=state,
    )
    for method, handler in make_handlers(ctx).items():
        server.register(method, handler)
    return server


class _StdoutAdapter:
    """把 sys.stdout 适配成 RpcServer 期望的 write_line(line) 接口。

    序列化由 RpcServer 内部的 asyncio.Lock 提供（self._write_lock），
    所以这里直接写即可，不需要额外的线程锁。
    """

    def write_line(self, line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()


class _StdinAdapter:
    """把 sys.stdin 适配成 RpcServer 期望的 readline() 接口（阻塞读行）。"""

    def readline(self) -> str:
        return sys.stdin.readline()


async def _run_rpc() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    server = _build_server()
    # 通知 Rust 侧：子进程已就绪，可以发请求
    await server.emit("ready", {"ts": _now_iso()})
    await server.serve()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chaoxing_agent",
        description="ChaoxingAgent RPC server (driven by Tauri host).",
    )
    parser.add_argument(
        "--rpc",
        action="store_true",
        help="Run in NDJSON RPC mode over stdin/stdout (default and only mode).",
    )
    parser.add_argument(
        "--calibration-subprocess",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.calibration_subprocess:
        from chaoxing_agent.calibration_subprocess import main as calibration_main
        return calibration_main()

    if not args.rpc:
        parser.print_help()
        return 2

    try:
        asyncio.run(_run_rpc())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
