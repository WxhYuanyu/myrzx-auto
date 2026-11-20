"""--live 循环：拒绝扫荡、战斗中不点、识别失败会重试再停。"""

from __future__ import annotations

import numpy as np

from src.interaction import DryRunClicker
from src.live import run_live
from src.tasks.base import PlannedAction, StepResult
from src.vision.types import Scene


class ScriptedTask:
    def __init__(self, results: list[StepResult]) -> None:
        self._results = list(results)

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        if not self._results:
            return StepResult(
                scene=Scene.UNKNOWN,
                reason="",
                action=PlannedAction(kind="halt", label="空", message="没有下一步"),
                status="unknown",
                message="没有下一步",
            )
        return self._results.pop(0)


def _grab() -> np.ndarray:
    return np.zeros((8, 8, 3), dtype=np.uint8)


def test_refuses_sweep_without_clicking():
    task = ScriptedTask(
        [
            StepResult(
                scene=Scene.STAGE_9_7,
                reason="",
                action=PlannedAction(kind="click", label="扫荡", x=557, y=1806),
                status="continue",
            )
        ]
    )
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "refused"
    assert clicker.history == []


def test_clicks_then_finishes():
    task = ScriptedTask(
        [
            StepResult(
                scene=Scene.ASSOCIATION,
                reason="",
                action=PlannedAction(kind="click", label="委托", x=940, y=1740),
                status="continue",
            ),
            StepResult(
                scene=Scene.LOOT_REWARD,
                reason="",
                action=None,
                status="done",
                message="委托已完成。",
            ),
        ]
    )
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "done"
    assert clicker.history == [(940, 1740)]


def test_does_not_click_while_waiting_for_battle():
    task = ScriptedTask(
        [
            StepResult(
                scene=Scene.BATTLE,
                reason="",
                action=PlannedAction(kind="wait", label="等待战斗"),
                status="waiting_battle",
            ),
            StepResult(
                scene=Scene.VICTORY,
                reason="",
                action=None,
                status="done",
            ),
        ]
    )
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "done"
    assert clicker.history == []


def test_retries_missing_target_then_halts():
    missing = StepResult(
        scene=Scene.CITY_TURANDON,
        reason="",
        action=PlannedAction(kind="halt", label="未找到协会", message="未找到协会"),
        status="halt_missing",
        message="未找到协会",
    )
    task = ScriptedTask([missing] * 5)
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "halted"
    assert "协会" in result.message
    assert clicker.history == []


class StickyTask:
    def __init__(self, result: StepResult) -> None:
        self._result = result

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        return self._result


def test_repeated_non_battle_wait_is_treated_as_stuck():
    task = StickyTask(
        StepResult(
            scene=Scene.COMMISSION_LIST,
            reason="",
            action=PlannedAction(kind="wait", label="委托已接取", message="请离开本页"),
            status="skip_unknown",
            message="已接取委托，当前仍停在委托列表。",
        )
    )
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "stuck"
    assert clicker.history == []


def test_battle_wait_is_not_treated_as_stuck():
    waiting = StepResult(
        scene=Scene.BATTLE,
        reason="",
        action=PlannedAction(kind="wait", label="等待战斗"),
        status="waiting_battle",
    )
    done = StepResult(scene=Scene.VICTORY, reason="", action=None, status="done")
    task = ScriptedTask([waiting] * 8 + [done])
    clicker = DryRunClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "done"
    assert clicker.history == []



class RecordingClicker:
    def __init__(self) -> None:
        self.history: list[tuple] = []

    def click(self, x: int, y: int, *, hwnd: int | None = None) -> None:
        self.history.append(("click", x, y))

    def swipe(self, x: int, y: int, x2: int, y2: int, *, hwnd: int | None = None) -> None:
        self.history.append(("swipe", x, y, x2, y2))


def _shop_swipe() -> StepResult:
    return StepResult(
        scene=Scene.UNKNOWN,
        reason="",
        action=PlannedAction(
            kind="swipe",
            label="向上滑动商店清单",
            x=540,
            y=1344,
            x2=540,
            y2=1184,
        ),
        status="continue",
    )


class ShiftingGrab:
    """每次截图整体变亮一点，模拟清单还在往下走。"""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> np.ndarray:
        frame = np.full((64, 64, 3), min(255, self.n * 20), dtype=np.uint8)
        self.n += 1
        return frame


def test_repeated_shop_swipe_continues_while_list_still_moves():
    done = StepResult(scene=Scene.UNKNOWN, reason="", action=None, status="done", message="买完了")
    task = ScriptedTask([_shop_swipe()] * 12 + [done])
    clicker = RecordingClicker()
    result = run_live(task, ShiftingGrab(), clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "done"
    assert result.message == "买完了"
    assert len(clicker.history) == 12
    assert all(item[0] == "swipe" for item in clicker.history)


def test_repeated_shop_swipe_stops_only_when_frame_is_unchanged():
    task = StickyTask(_shop_swipe())
    clicker = RecordingClicker()
    result = run_live(task, _grab, clicker, sleep=lambda _s: None, timeout_sec=5)
    assert result.status == "stuck"
    assert "清单" in result.message
    # 第 1 次滑动 same_streak=0，连滑 4 次画面不变后第 5 次规划才停，实际执行 4 次。
    assert len(clicker.history) == 4
