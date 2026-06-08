"""ChaoxingAgent v1 — Windows 本地自动化答题工具

使用:
    uv run python main.py
    uv run python main.py --init-config     # 强制从 example 重新生成 config.json / model_services.json
    uv run python main.py --init-env        # 重新生成 config/.env.example

环境配置:
    config/.env 仅用于模型服务相关项:
      - 模型 API key（由 model_services.json 的 api_key_env 指向）
      - provider 字段覆盖：CHAOXING_VISION_<FIELD> / CHAOXING_SOLVER_<FIELD>
        其中 <FIELD> 可为 BASE_URL / MODEL_ID / API_KEY_ENV / API_TYPE
    其它运行时/标定参数在 config/config.json 中维护。
    真实 config.json / model_services.json 已被 .gitignore 排除，
    首次运行会自动从 *.example 复制。

流程:
    1. 输入进程名或 PID → 绑定窗口
    2. 手动框选手机画面区域
    3. 进入自动循环（截图→视觉解析→文本作答→点击→检测跳题）
    4. 遇到交卷按钮停止
"""

import json
import sys
from pathlib import Path

from chaoxing_agent import paths
from chaoxing_agent.core.config_init import ensure_config_files, init_config_files, init_env_example
from chaoxing_agent.core.env_settings import apply_overrides
from chaoxing_agent.core.errors import FatalStopError
from chaoxing_agent.core.state_machine import StateMachine
from chaoxing_agent.core.viewport_selector import select as select_viewport_fn
from chaoxing_agent.core.window_selector import select as select_window_fn
from models.model_config import load_model_services


CONFIG_DIR = paths.runtime_config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"


def _default_config() -> dict:
    """返回默认 config.json 模板。"""
    return {
        "target": {
            "process_name": "",
            "pid": None,
            "selected_hwnd": None,
            "window_title": "",
            "client_rect": [0, 0, 0, 0],
        },
        "viewport": {
            "lock_window_size_after_calibration": True,
            "phone_viewport_in_client": {"x": 0, "y": 0, "width": 0, "height": 0},
            "phone_viewport_ratio": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
        },
        "timing": {
            "between_multi_select_clicks": 0.2,
            "before_click_next": 0.2,
            "after_click_next": 0.5,
            "extra_wait_if_page_not_changed": 0.5,
            "max_page_change_wait": 3.0,
        },
        "thresholds": {
            "vision_text_confidence": 0.75,
            "vision_layout_confidence": 0.75,
            "solver_confidence": 0.70,
            "page_change_pixel_ratio": 0.03,
            "window_size_change_ratio": 0.05,
        },
        "page_change": {
            "compare_region_ratio": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.75},
            "compare_resize": [200, 200],
        },
        "runtime": {
            "max_steps": 200,
            "pause_on_popup": True,
            "pause_on_unknown": True,
            "save_trace": True,
            "loading_retry_max": 3,
            "loading_retry_delay": 1.0,
            "max_consecutive_errors": 3,
        },
    }


def _load_or_create_config() -> dict:
    """加载 config.json，不存在则创建默认模板。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    template = _default_config()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    return template


def _save_config(config: dict):
    """保存配置到 config.json。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _resolve_preconfigured_target(target: dict) -> dict | None:
    """若 config.json 里的 target 已预填 process_name / pid / hwnd，则直接绑定窗口。

    返回值结构与 config["target"] 一致（包含 selected_hwnd 等），
    绑定失败返回 None（调用方回落到交互式选择）。
    """
    pid = target.get("pid")
    process_name = (target.get("process_name") or "").strip()
    hwnd = target.get("selected_hwnd")

    # 必须有 pid 或 process_name；纯 hwnd 仍走"复用 hwnd"分支
    if not (pid or process_name):
        return None

    # 优先使用 pid（更精确）；没有 pid 才退到进程名
    user_input = str(pid) if pid else process_name

    try:
        win_info = select_window_fn(user_input)
    except SystemExit as e:
        print(f"[Target] 预配置 {user_input!r} 未找到可见窗口: {e}")
        print("[Target] 将回落到交互式选择。")
        return None

    # 如果用户额外指定了 hwnd，校验匹配；不匹配则警告但继续
    if hwnd and win_info.hwnd != hwnd:
        print(
            f"[Target] 警告: config.json 指定的 hwnd={hwnd} 与实际找到的 hwnd={win_info.hwnd} 不一致，"
            f"使用实际找到的窗口。"
        )

    return {
        "process_name": win_info.process_name,
        "pid": win_info.pid,
        "selected_hwnd": win_info.hwnd,
        "window_title": win_info.window_title,
        "client_rect": list(win_info.client_rect),
    }


def _save_window_to_config(config: dict, win_info):
    """将窗口信息写入 config['target']。"""
    config["target"] = {
        "process_name": win_info.process_name,
        "pid": win_info.pid,
        "selected_hwnd": win_info.hwnd,
        "window_title": win_info.window_title,
        "client_rect": list(win_info.client_rect),
    }
    _save_config(config)


def _save_viewport_to_config(config: dict, vp_info):
    """将 viewport 信息写入 config['viewport']。"""
    config["viewport"] = {
        "lock_window_size_after_calibration": True,
        "phone_viewport_in_client": {
            "x": vp_info.x,
            "y": vp_info.y,
            "width": vp_info.width,
            "height": vp_info.height,
        },
        "phone_viewport_ratio": {
            "x": vp_info.ratio_x,
            "y": vp_info.ratio_y,
            "width": vp_info.ratio_w,
            "height": vp_info.ratio_h,
        },
    }
    _save_config(config)


def main():
    args = sys.argv[1:]
    if "--init-env" in args:
        out = init_env_example()
        print(f"已生成 env 模板: {out}")
        return
    if "--init-config" in args:
        pairs = init_config_files(force=True)
        for src, dst in pairs:
            print(f"已生成: {dst}  <-  {src}")
        return

    print("=" * 50)
    print("ChaoxingAgent v1")
    print("Windows 本地自动化答题工具")
    print("=" * 50)

    initialized = ensure_config_files()
    for src, dst in initialized:
        print(f"\n[Init] 已从 example 初始化: {dst}")
        print(f"       模板: {src}")
    if initialized:
        print("       请按需编辑后再运行。\n")

    config = _load_or_create_config()
    model_services = load_model_services()

    loaded_env, n_models = apply_overrides(model_services)
    if loaded_env:
        print(f"\n[Env] 加载 config/.env: {loaded_env} 条")
    if n_models:
        print(f"[Env] CHAOXING_* model_services 覆盖: {n_models} 项")

    target = config.get("target", {})

    # 1) 优先看 config.json 里的 target 设置（用户预填的进程名 / PID / hwnd）
    preconfigured = _resolve_preconfigured_target(target)
    if preconfigured is not None:
        # 已配置：直接绑定，不再交互
        if preconfigured.get("selected_hwnd") and preconfigured.get("process_name"):
            print(
                f"\n[Target] 来自 config.json: hwnd={preconfigured['selected_hwnd']} "
                f"pid={preconfigured.get('pid')} process={preconfigured.get('process_name')}"
            )
        # 关键：把预配置结果立刻写盘，后续 viewport 写盘时不能把它覆盖回 null。
        config["target"] = preconfigured
        _save_config(config)
        target = preconfigured
    # 2) 已有 selected_hwnd（程序之前回写或用户在 config.json 手动设置）—— 仍需问是否复用
    elif target.get("selected_hwnd"):
        print(f"\n已有窗口绑定: hwnd={target['selected_hwnd']} title='{target.get('window_title', '')}'")
        reuse = input("是否使用已有绑定？(y/n，n 则重新选择): ").strip().lower()
        if reuse != "y":
            target = {}
    # 3) 既没预设也没 hwnd：交互式输入
    if not target.get("selected_hwnd"):
        user_input = input("\n请输入目标进程名或 PID（也可先在 config.json 里设置 target.process_name / pid）: ").strip()
        if not user_input:
            print("未输入，退出。")
            return
        win_info = select_window_fn(user_input)
        _save_window_to_config(config, win_info)
        config = _load_or_create_config()
        target = config["target"]

    viewport = config.get("viewport", {})
    vp_in_client = viewport.get("phone_viewport_in_client", {})
    if vp_in_client.get("width", 0) > 0:
        print(f"\n已标定区域: {vp_in_client}")
        recal = input("是否使用已有标定？(y/n，n 则重新标定): ").strip().lower()
        if recal != "y":
            viewport = {}

    if not viewport.get("phone_viewport_in_client", {}).get("width", 0):
        from chaoxing_agent.core.window_selector import WindowInfo

        client_rect = target.get("client_rect", [0, 0, 0, 0])
        win_info = WindowInfo(
            hwnd=target["selected_hwnd"],
            pid=target["pid"],
            process_name=target["process_name"],
            window_title=target.get("window_title", ""),
            client_rect=tuple(client_rect),
            screen_rect=tuple(client_rect),
            width=client_rect[2] - client_rect[0] if len(client_rect) == 4 else 0,
            height=client_rect[3] - client_rect[1] if len(client_rect) == 4 else 0,
        )
        vp_info = select_viewport_fn(win_info)
        _save_viewport_to_config(config, vp_info)

    config = _load_or_create_config()

    print("\n" + "=" * 50)
    sm = None
    try:
        sm = StateMachine(config, model_services)
        sm.run()
    except FatalStopError as e:
        print(f"\n[FATAL] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    except Exception as e:
        print(f"\n[FATAL] 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        # 保存 trace 现场 — 让事后能复盘
        if sm is not None and hasattr(sm, "trace_logger"):
            try:
                sm.trace_logger.save_stop(f"未预期异常: {type(e).__name__}: {e}")
                print(f"[Trace] 现场已保存: {sm.trace_logger.session_dir}")
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
