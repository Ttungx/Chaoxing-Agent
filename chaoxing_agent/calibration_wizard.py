"""标定向导的子进程 wrapper。

Tkinter mainloop 是同步阻塞的，必须跑在独立子进程，
否则会卡住 RPC 事件循环，导致前端无响应。

设计：
- `asyncio.create_subprocess_exec` 拉一个 `python -m chaoxing_agent.calibration_subprocess`
- 子进程跑 Tkinter 向导，写入 config/config.json，然后退出
- 父进程（RPC server）`await proc.wait()` 即可，期间 RPC 正常处理其他请求
"""
import asyncio
import sys
from pathlib import Path

from chaoxing_agent import paths


SUBPROCESS_MODULE = "chaoxing_agent.calibration_subprocess"


async def run_wizard() -> None:
    """拉起子进程跑 Tkinter 向导，等完成。

    抛 RuntimeError 如果子进程退出码非 0，stderr 内容会附在异常消息里。
    """
    repo_root = Path(__file__).resolve().parent.parent
    if paths.is_frozen():
        cmd = [sys.executable, "--calibration-subprocess"]
        cwd = str(paths.runtime_root())
    else:
        cmd = [sys.executable, "-m", SUBPROCESS_MODULE]
        cwd = str(repo_root)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace") if stderr else "<no stderr>"
        raise RuntimeError(
            f"标定向导子进程退出码 {proc.returncode}\n{err_text}"
        )
