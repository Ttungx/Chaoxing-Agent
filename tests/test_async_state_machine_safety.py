from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from chaoxing_agent.async_state_machine import AsyncStateMachine
from chaoxing_agent.config_holder import ConfigHolder
from chaoxing_agent.pause_gate import PauseGate
from schemas.vision_schema import (
    VisionButton,
    VisionButtons,
    VisionConfidence,
    VisionOption,
    VisionResult,
)


def _make_ctx(tmp_path):
    cfg = ConfigHolder(
        {
            "target": {
                "selected_hwnd": 12345,
                "client_rect": [0, 0, 388, 928],
            },
            "viewport": {
                "phone_viewport_in_client": {
                    "x": 0,
                    "y": 0,
                    "width": 388,
                    "height": 928,
                }
            },
            "runtime": {"max_steps": 1},
            "thresholds": {
                "vision_text_confidence": 0.75,
                "vision_layout_confidence": 0.75,
                "solver_confidence": 0.7,
            },
            "timing": {},
            "page_change": {},
        },
        config_path=tmp_path / "config.json",
    )
    rpc = MagicMock()
    rpc.emit = AsyncMock()
    return type(
        "Ctx",
        (),
        {
            "config": cfg,
            "rpc": rpc,
            "pause_gate": PauseGate(),
            "state": {},
        },
    )()


def _make_vision(option_box, next_box):
    return VisionResult(
        page_state="question",
        question_type="single_choice",
        question_text="题干",
        options=[VisionOption(key="A", text="选项A", box=option_box)],
        buttons=VisionButtons(
            previous=VisionButton(visible=False),
            next=VisionButton(visible=True, text="下一题", box=next_box),
            submit=VisionButton(visible=False),
        ),
        confidence=VisionConfidence(text=0.95, layout=0.95),
    )


def _ready_sm(ctx):
    sm = AsyncStateMachine(ctx, {})
    sm._hwnd = 12345
    sm._expected_client_rect = (0, 0, 388, 928)
    sm._viewport = {
        "phone_viewport_in_client": {
            "x": 0,
            "y": 0,
            "width": 388,
            "height": 928,
        }
    }
    sm._thresholds = {
        "vision_text_confidence": 0.75,
        "vision_layout_confidence": 0.75,
        "solver_confidence": 0.7,
    }
    sm._timing = {}
    sm._trace_logger = MagicMock()
    sm._mapper = MagicMock()
    return sm


@pytest.mark.asyncio
async def test_async_option_box_out_of_image_pauses_before_solver(tmp_path):
    ctx = _make_ctx(tmp_path)
    sm = _ready_sm(ctx)
    screenshot = Image.new("RGB", (388, 928))

    with (
        patch("chaoxing_agent.async_state_machine.check_window_alive", return_value=True),
        patch("chaoxing_agent.async_state_machine.check_window_size_unchanged", return_value=True),
        patch("chaoxing_agent.async_state_machine.capture_phone_screen", return_value=screenshot),
        patch(
            "chaoxing_agent.async_state_machine.vision_parse",
            return_value=_make_vision([0, 100, 500, 150], [0, 800, 380, 850]),
        ),
        patch("chaoxing_agent.async_state_machine.text_solve") as solve,
        patch.object(sm, "_pause_save", AsyncMock(return_value=False)) as pause,
    ):
        result = await sm._process_one_step()

    assert result is False
    solve.assert_not_called()
    assert "选项 A 坐标越界" in pause.call_args.args[3]


@pytest.mark.asyncio
async def test_async_next_button_box_out_of_image_pauses_before_solver(tmp_path):
    ctx = _make_ctx(tmp_path)
    sm = _ready_sm(ctx)
    screenshot = Image.new("RGB", (388, 928))

    with (
        patch("chaoxing_agent.async_state_machine.check_window_alive", return_value=True),
        patch("chaoxing_agent.async_state_machine.check_window_size_unchanged", return_value=True),
        patch("chaoxing_agent.async_state_machine.capture_phone_screen", return_value=screenshot),
        patch(
            "chaoxing_agent.async_state_machine.vision_parse",
            return_value=_make_vision([0, 100, 380, 150], [300, 900, 500, 960]),
        ),
        patch("chaoxing_agent.async_state_machine.text_solve") as solve,
        patch.object(sm, "_pause_save", AsyncMock(return_value=False)) as pause,
    ):
        result = await sm._process_one_step()

    assert result is False
    solve.assert_not_called()
    assert "下一题按钮坐标越界" in pause.call_args.args[3]
