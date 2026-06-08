"""AsyncStateMachine — 状态机的异步版，配合 RPC server + PauseGate 跑。

与 v1 StateMachine 的区别：
- run() / _process_one_step() / _pause() 都是 async
- 用 await ctx.pause_gate.wait(step, reason) 替代 input()
- 关键节点通过 ctx.rpc.emit() 推送事件给前端：
  - "step_started"     — 每 step 开始
  - "step_completed"   — 每 step 完成（含 question / answer / confidence / screenshot）
  - "screenshot"       — 截图流（每 step 推一张）
  - "paused"           — 暂停时附带 screenshot
  - "log"              — stderr 风格日志
  - "stopped"          — 正常退出
  - "crashed"          — 致命错误
- 支持 request_stop() 让 RPC 优雅终止
- 同业务逻辑：截图 → vision 解析 → solver 作答 → 点击 → 检测翻页
"""
import asyncio
import base64
import io
import logging
import traceback
from datetime import datetime
from typing import Optional

from chaoxing_agent.core.coordinate_mapper import CoordinateMapper
from chaoxing_agent.core.click_executor import click_options, click_next_button
from chaoxing_agent.core.errors import FatalStopError, PauseRequiredError, RecoverableError
from chaoxing_agent.core.page_change_detector import wait_for_change
from chaoxing_agent.core.screen_capture import capture_phone_screen, check_window_alive, check_window_size_unchanged
from chaoxing_agent.core.trace_logger import TraceLogger
from models.model_config import ModelConfig, get_solver_config, get_vision_config, load_model_services
from models.text_solver import solve as text_solve
from models.vision_parser import parse as vision_parse

log = logging.getLogger(__name__)


def _box_in_image(box: list[int], width: int, height: int) -> bool:
    """判断视觉模型返回的 box 是否完全位于截图内。"""
    if len(box) != 4:
        return False
    x1, y1, x2, y2 = box
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height


class AsyncStateMachine:
    """异步状态机 — 主循环编排，串联全部流程，通过事件与前端通信。"""

    def __init__(self, ctx, opts: dict):
        self.ctx = ctx
        self.opts = opts
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.step = 0
        self._stop_requested = False
        self.consecutive_errors = 0

        # Lazy resources (initialized at run() start so tests can create the object)
        self._mapper: Optional[CoordinateMapper] = None
        self._trace_logger: Optional[TraceLogger] = None
        self._vision_config: Optional[ModelConfig] = None
        self._solver_config: Optional[ModelConfig] = None
        self._hwnd: int = 0
        self._expected_client_rect: tuple = (0, 0, 0, 0)
        self._viewport: dict = {}
        self._thresholds: dict = {}
        self._timing: dict = {}
        self._page_change_cfg: dict = {}
        self._max_steps: int = 200
        self._max_consecutive_errors: int = 3
        self._loading_retry_max: int = 3
        self._loading_retry_delay: float = 1.0
        self._pause_on_popup: bool = True
        self._pause_on_unknown: bool = True

    def request_stop(self):
        """设置停止标志，让 run() 在下一轮循环退出。"""
        self._stop_requested = True

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self):
        """主循环：每 step 处理一道题，遇 max_steps / 致命错误 / 停止请求时退出。"""
        self._ensure_ready()

        try:
            while not self._stop_requested and self.step < self._max_steps:
                self._mapper.refresh()

                try:
                    advance = await self._process_one_step()
                except RecoverableError as e:
                    self.consecutive_errors += 1
                    await self._emit_log("WARN", f"step {self.step + 1} 可恢复异常 (第{self.consecutive_errors}次): {e}")
                    if self.consecutive_errors >= self._max_consecutive_errors:
                        raise FatalStopError(
                            f"连续异常超过 {self._max_consecutive_errors} 次"
                        ) from e
                    await asyncio.sleep(1)
                    continue
                except PauseRequiredError as e:
                    await self._pause_save_direct(str(e))
                    continue

                if self._stop_requested:
                    break

                if advance:
                    self.step += 1
                    self.consecutive_errors = 0

            # 正常退出
            reason = "max_steps" if self.step >= self._max_steps else "user_requested"
            self._trace_logger.save_stop(reason)
            await self._emit_event("stopped", {
                "reason": reason,
                "total_steps": self.step,
            })

        except FatalStopError as e:
            await self._emit_log("ERROR", f"step {self.step + 1} 致命错误: {e}")
            self._trace_logger.save_stop(str(e))
            await self._emit_event("crashed", {"reason": str(e)})
        except asyncio.CancelledError:
            await self._emit_log("INFO", "状态机被取消")
            raise
        except Exception as e:
            log.exception("状态机未预期错误")
            await self._emit_log("ERROR", f"未预期错误: {e}\n{traceback.format_exc()}")
            try:
                await self._emit_event("crashed", {"reason": str(e)})
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------
    # 单题处理（同 v1 业务逻辑）
    # ------------------------------------------------------------------

    async def _process_one_step(self) -> bool:
        """处理一道题的完整流程。

        Returns:
            True  → 步数前进（advance step）
            False → 重试当前步（retry）
        """
        await self._emit_event("step_started", {"step": self.step + 1})

        # ── 1. 检查窗口存活 ──
        if not check_window_alive(self._hwnd):
            self._trace_logger.save_stop("window_gone")
            await self._emit_event("stopped", {
                "reason": "window_gone",
                "total_steps": self.step,
            })
            self._stop_requested = True
            return False

        # ── 2. 窗口尺寸是否变化 ──
        if not check_window_size_unchanged(
            self._hwnd,
            self._expected_client_rect,
            self._thresholds.get("window_size_change_ratio", 0.05),
        ):
            advance = await self._pause_save(
                None, None, None,
                f"窗口尺寸已变化（>{self._thresholds.get('window_size_change_ratio', 0.05):.0%}），"
                f"请重新标定手机画面区域。skip 继续 / retry 重试",
            )
            # 如果用户 skip，让步数前进（跳过这题）
            return advance

        # ── 3. 截屏 ──
        screenshot = await asyncio.to_thread(capture_phone_screen, self._hwnd, self._viewport)
        await self._emit_event("screenshot", {
            "step": self.step + 1,
            "page_state": "question",
            "image_b64": self._img_to_b64(screenshot),
            "width": screenshot.width,
            "height": screenshot.height,
        })

        # ── 4. 视觉解析 ──
        vision = await asyncio.to_thread(vision_parse, screenshot, self._vision_config)

        # ── 5. 交卷检测 ──
        if vision.page_state == "submit" or vision.buttons.submit.visible:
            self._trace_logger.save_stop("submit_detected")
            await self._emit_event("stopped", {
                "reason": "submit_detected",
                "total_steps": self.step,
            })
            self._stop_requested = True
            return False

        # ── 6. finished ──
        if vision.page_state == "finished":
            self._trace_logger.save_stop("finished")
            await self._emit_event("stopped", {
                "reason": "finished",
                "total_steps": self.step,
            })
            self._stop_requested = True
            return False

        # ── 7. 弹窗检测 ──
        if vision.popup.visible and self._pause_on_popup:
            return await self._pause_save(
                screenshot, vision, None,
                "检测到弹窗，请手动处理后选择 retry / skip",
            )

        # ── 8. 未知页面状态 ──
        if vision.page_state == "unknown" and self._pause_on_unknown:
            return await self._pause_save(
                screenshot, vision, None,
                "无法识别页面状态，请检查后选择 retry / skip",
            )

        # ── 9. loading 处理 ──
        if vision.page_state == "loading":
            return await self._handle_loading(screenshot)

        # ── 10. 非 question 状态 ──
        if vision.page_state != "question":
            return await self._pause_save(
                screenshot, vision, None,
                f"未预期的页面状态: {vision.page_state}，请检查",
            )

        # ── 11. 视觉置信度检查 ──
        vt = self._thresholds.get("vision_text_confidence", 0.75)
        vl = self._thresholds.get("vision_layout_confidence", 0.75)
        if vision.confidence.text < vt or vision.confidence.layout < vl:
            return await self._pause_save(
                screenshot, vision, None,
                f"视觉置信度过低 (text={vision.confidence.text:.2f} layout={vision.confidence.layout:.2f})",
            )

        # ── 12. 选项检查 ──
        if not vision.options:
            return await self._pause_save(screenshot, vision, None, "视觉模型未识别到选项")

        # ── 13. 下一题按钮检查 ──
        if not vision.buttons.next.visible or not vision.buttons.next.box:
            return await self._pause_save(screenshot, vision, None, "未识别到下一题按钮")

        for opt in vision.options:
            if not _box_in_image(opt.box, screenshot.width, screenshot.height):
                return await self._pause_save(
                    screenshot,
                    vision,
                    None,
                    f"选项 {opt.key} 坐标越界: {opt.box}，截图尺寸={screenshot.width}x{screenshot.height}",
                )

        if not _box_in_image(vision.buttons.next.box, screenshot.width, screenshot.height):
            return await self._pause_save(
                screenshot,
                vision,
                None,
                f"下一题按钮坐标越界: {vision.buttons.next.box}，截图尺寸={screenshot.width}x{screenshot.height}",
            )

        # ── 14. 构建选项字典 ──
        opts_dict = {opt.key: opt.text for opt in vision.options}

        # ── 15. 作答 ──
        solver = await asyncio.to_thread(
            text_solve, vision.question_type, vision.question_text, opts_dict, self._solver_config,
        )

        # ── 16. 答案置信度检查 ──
        if solver.confidence < self._thresholds.get("solver_confidence", 0.70):
            return await self._pause_save(
                screenshot, vision, solver,
                f"文本模型置信度过低 ({solver.confidence:.2f})",
            )

        # ── 17. 答案映射检查 ──
        for answer_key in solver.answer:
            if answer_key not in opts_dict:
                return await self._pause_save(
                    screenshot, vision, solver,
                    f"答案 '{answer_key}' 无法映射到选项 {list(opts_dict.keys())}",
                )

        # ── 18. 点击选项 ──
        await asyncio.to_thread(click_options, solver.answer, vision.options, self._mapper, self._timing)

        # ── 19. 点击前截图（用于翻页检测） ──
        before_img = await asyncio.to_thread(capture_phone_screen, self._hwnd, self._viewport)

        # ── 20. 点击下一题 ──
        await asyncio.to_thread(click_next_button, vision.buttons.next.box, self._mapper, self._timing)

        # ── 21. 等待翻页 ──
        def _capture():
            return capture_phone_screen(self._hwnd, self._viewport)

        changed, after_img = await asyncio.to_thread(wait_for_change, before_img, _capture, self.ctx.config.snapshot())
        if not changed:
            return await self._pause_save(
                after_img or before_img,
                vision,
                solver,
                f"点击下一题后页面未变化（已等待{self._timing.get('max_page_change_wait', 3.0)}秒）",
            )

        # ── 22. 构建 step_data ──
        clicked = []
        for answer_key in solver.answer:
            opt = next(o for o in vision.options if o.key == answer_key)
            scx, scy = self._mapper.box_center_screen(opt.box)
            clicked.append({
                "key": answer_key,
                "box": opt.box,
                "image_center": [(opt.box[0] + opt.box[2]) // 2, (opt.box[1] + opt.box[3]) // 2],
                "screen_center": [scx, scy],
            })

        nscx, nscy = self._mapper.box_center_screen(vision.buttons.next.box)
        step_data = {
            "step": self.step + 1,
            "screenshot_img": screenshot,
            "page_state": vision.page_state,
            "question_type": vision.question_type,
            "question": vision.question_text,
            "options": opts_dict,
            "vision_confidence": {"text": vision.confidence.text, "layout": vision.confidence.layout},
            "vision_raw_json": vision.model_dump(),
            "solver_answer": solver.answer,
            "solver_confidence": solver.confidence,
            "solver_reason": solver.reason,
            "solver_raw_json": solver.model_dump(),
            "clicked_options": clicked,
            "next_button": {
                "box": vision.buttons.next.box,
                "image_center": [
                    (vision.buttons.next.box[0] + vision.buttons.next.box[2]) // 2,
                    (vision.buttons.next.box[1] + vision.buttons.next.box[3]) // 2,
                ],
                "screen_center": [nscx, nscy],
            },
            "page_changed": True,
            "error": None,
        }
        self._trace_logger.save_step(step_data)

        await self._emit_event("step_completed", {
            "step": self.step + 1,
            "question": vision.question_text,
            "options": opts_dict,
            "answer": solver.answer,
            "confidence": solver.confidence,
            "page_changed": True,
        })

        return True  # advance step

    # ------------------------------------------------------------------
    # loading 处理（同 v1）
    # ------------------------------------------------------------------

    async def _handle_loading(self, screenshot) -> bool:
        """处理 loading 状态：循环截图直到页面变化或超时。"""
        for i in range(self._loading_retry_max):
            await self._emit_log("INFO", f"页面 loading，等待 {self._loading_retry_delay}s 后重试 ({i + 1}/{self._loading_retry_max})")
            await asyncio.sleep(self._loading_retry_delay)
            screenshot = await asyncio.to_thread(capture_phone_screen, self._hwnd, self._viewport)
            vision = await asyncio.to_thread(vision_parse, screenshot, self._vision_config)
            if vision.page_state != "loading":
                await self._emit_log("INFO", f"页面状态变为: {vision.page_state}")
                # 不是 loading 了但还没处理这题，返回 False 让外层重新走 _process_one_step
                return False
        return await self._pause_save(screenshot, None, None, "页面持续 loading，请检查")

    # ------------------------------------------------------------------
    # 暂停机制
    # ------------------------------------------------------------------

    async def _pause(self, reason: str) -> str:
        """推 paused 事件，等前端发决策 (retry / skip / quit)。"""
        try:
            img = await asyncio.to_thread(capture_phone_screen, self._hwnd, self._viewport)
        except Exception:
            img = None

        await self._emit_event("paused", {
            "step": self.step + 1,
            "reason": reason,
            "screenshot_b64": self._img_to_b64(img) if img else None,
        })

        decision = await self.ctx.pause_gate.wait(self.step + 1, reason)
        await self._emit_log("INFO", f"暂停决策: {decision} (step {self.step + 1})")

        if decision == "quit":
            raise FatalStopError(f"用户选择退出: {reason}")

        return decision  # "retry" or "skip"

    async def _pause_save(self, screenshot, vision_result, solver_result, reason: str) -> bool:
        """暂停并保存现场。返回 True → advance step (skip)，False → retry。"""
        self._trace_logger.save_pause(
            self.step + 1,
            screenshot,
            vision_result.model_dump() if vision_result else {},
            solver_result.model_dump() if solver_result else None,
            reason,
        )
        decision = await self._pause(reason)
        return decision == "skip"

    async def _pause_save_direct(self, reason: str):
        """直接 pause（无现场数据），用于 PauseRequiredError 异常 catch 分支。"""
        decision = await self._pause(reason)
        if decision == "skip":
            self.step += 1
            self.consecutive_errors = 0

    # ------------------------------------------------------------------
    # 初始化和工具方法
    # ------------------------------------------------------------------

    def _ensure_ready(self):
        """从 ctx.config 读取完整配置，初始化窗口依赖的模块。"""
        cfg = self.ctx.config.snapshot()

        target = cfg.get("target", {})
        self._hwnd = target.get("selected_hwnd")
        if not self._hwnd:
            raise FatalStopError("未绑定目标窗口，请先运行窗口选择。")
        self._expected_client_rect = tuple(target.get("client_rect", (0, 0, 0, 0)))

        self._viewport = cfg.get("viewport", {})
        vp = self._viewport.get("phone_viewport_in_client", {})
        if not vp.get("width"):
            raise FatalStopError("未标定手机画面区域，请先运行区域选择。")

        self._mapper = CoordinateMapper(self._hwnd, self._viewport)
        self._trace_logger = TraceLogger()

        # 加载模型服务
        model_services = load_model_services()
        self._vision_config = get_vision_config(model_services)
        self._solver_config = get_solver_config(model_services)

        # 运行时配置
        runtime = cfg.get("runtime", {})
        self._max_steps = runtime.get("max_steps", 200)
        self._max_consecutive_errors = runtime.get("max_consecutive_errors", 3)
        self._loading_retry_max = runtime.get("loading_retry_max", 3)
        self._loading_retry_delay = runtime.get("loading_retry_delay", 1.0)
        self._pause_on_popup = runtime.get("pause_on_popup", True)
        self._pause_on_unknown = runtime.get("pause_on_unknown", True)

        self._thresholds = cfg.get("thresholds", {})
        self._timing = cfg.get("timing", {})
        self._page_change_cfg = cfg.get("page_change", {})

    @staticmethod
    def _img_to_b64(img) -> str:
        """PIL Image → base64 JPEG string (data URL format)。"""
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    async def _emit_event(self, event: str, data: dict):
        """推送事件到前端。"""
        if self.ctx.rpc:
            try:
                await self.ctx.rpc.emit(event, data)
            except Exception as e:
                log.warning(f"emit {event} failed: {e}")

    async def _emit_log(self, level: str, message: str):
        """推送日志事件。"""
        log_line = f"[{self.session_id}] step={self.step + 1} {message}"
        getattr(log, level.lower(), log.info)(log_line)
        await self._emit_event("log", {
            "level": level,
            "message": log_line,
            "ts": datetime.now().isoformat(),
        })
