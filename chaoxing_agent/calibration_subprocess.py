"""独立子进程入口：跑 Tkinter 标定向导，写入 config，退出。

为什么用独立模块而不是 calibration_wizard.py 内部直接调：
- Tkinter mainloop 是同步阻塞，必须在独立进程跑
- 独立模块方便 pyinstaller 打包时只 import Tkinter
"""
import json
import sys
from pathlib import Path

from chaoxing_agent import paths

CONFIG_DIR = paths.runtime_config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"


def _load_or_create_config() -> dict:
    """加载 config.json，不存在则创建默认模板（同 main.py 的做法）。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_config(config: dict) -> None:
    """保存配置到 config.json。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def main() -> int:
    """Tkinter 标定向导入口，返回退出码。"""
    # 导入放函数内，避免顶层 import 触发 Tkinter（在不需要的进程中加载）
    from chaoxing_agent.core.viewport_selector import select as select_viewport
    from chaoxing_agent.core.window_selector import WindowInfo

    config = _load_or_create_config()
    target = config.get("target") or {}
    if not target.get("selected_hwnd"):
        print("未绑定目标窗口", file=sys.stderr)
        return 2

    client_rect = target.get("client_rect", [0, 0, 0, 0])
    win_info = WindowInfo(
        hwnd=target["selected_hwnd"],
        pid=target.get("pid"),
        process_name=target.get("process_name", ""),
        window_title=target.get("window_title", ""),
        client_rect=tuple(client_rect),
        screen_rect=tuple(client_rect),
        width=client_rect[2] - client_rect[0] if len(client_rect) == 4 else 0,
        height=client_rect[3] - client_rect[1] if len(client_rect) == 4 else 0,
    )
    vp = select_viewport(win_info)  # 阻塞到用户完成框选

    # 写入 config（字段名与 main.py _save_viewport_to_config 保持一致）
    config["viewport"] = {
        "lock_window_size_after_calibration": True,
        "phone_viewport_in_client": {
            "x": vp.x,
            "y": vp.y,
            "width": vp.width,
            "height": vp.height,
        },
        "phone_viewport_ratio": {
            "x": vp.ratio_x,
            "y": vp.ratio_y,
            "width": vp.ratio_w,
            "height": vp.ratio_h,
        },
    }
    _save_config(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
