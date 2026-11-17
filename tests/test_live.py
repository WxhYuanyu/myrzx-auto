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

