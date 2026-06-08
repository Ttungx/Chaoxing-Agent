"""Trace 日志 — 每步截图 + JSON 落盘"""

import json
from datetime import datetime
from pathlib import Path

from chaoxing_agent import paths


class TraceLogger:
    """管理 trace/ 目录，保存每步截图和 JSON"""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else paths.trace_dir()
        session_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = self.base_dir / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        print(f"[Trace] 日志目录: {self.session_dir}")

    def save_step(self, step_data: dict):
        """保存一步的截图和 JSON。

        注意：本方法不修改 ``step_data`` —— PIL Image 也不会出现在 JSON 中。
        """
        step_num = step_data["step"]
        timestamp = datetime.now().isoformat()

        screenshot_filename = f"step_{step_num:03d}.png"
        screenshot_path = self.session_dir / screenshot_filename
        img = step_data.get("screenshot_img")
        if img is not None:
            img.save(screenshot_path)

        # Build JSON-safe view: omit PIL Image and other non-serializable fields.
        json_safe_keys = (
            "step", "page_state", "question_type", "question", "options",
            "vision_confidence", "vision_raw_json", "solver_answer",
            "solver_confidence", "solver_reason", "solver_raw_json",
            "clicked_options", "next_button", "page_changed",
            "page_change_ratio", "error",
        )
        trace_entry = {k: step_data.get(k) for k in json_safe_keys}
        trace_entry["step"] = step_num
        trace_entry["timestamp"] = timestamp
        trace_entry["screenshot"] = str(screenshot_path)

        json_filename = f"step_{step_num:03d}.json"
        json_path = self.session_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(trace_entry, f, ensure_ascii=False, indent=2)

    def save_pause(self, step_num: int, screenshot, vision_result: dict, solver_result: dict | None, reason: str):
        """暂停时额外保存现场"""
        pause_dir = self.session_dir / f"pause_step_{step_num:03d}"
        pause_dir.mkdir(exist_ok=True)

        if screenshot:
            screenshot.save(pause_dir / "screenshot_at_pause.png")

        with open(pause_dir / "vision_result.json", "w", encoding="utf-8") as f:
            json.dump(vision_result, f, ensure_ascii=False, indent=2)

        if solver_result:
            with open(pause_dir / "solver_result.json", "w", encoding="utf-8") as f:
                json.dump(solver_result, f, ensure_ascii=False, indent=2)

        (pause_dir / "pause_reason.txt").write_text(reason, encoding="utf-8")

    def save_stop(self, reason: str):
        """最终停止时记录原因"""
        (self.session_dir / "STOP_REASON.txt").write_text(reason, encoding="utf-8")
