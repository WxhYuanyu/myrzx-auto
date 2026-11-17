"""--live 循环：截图 → 规划 → 执行。默认关闭，需显式打开。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from src import config
from src.interaction import Clicker
from src.tasks.base import PlannedAction, StepResult
from src.tasks.daily_commission import DailyCommissionTask

logger = logging.getLogger("myrzx.live")


@dataclass
class LiveRunResult:
    status: str
    message: str
    steps: int = 0
    last: StepResult | None = None
    history: list[str] = field(default_factory=list)


def is_sweep_action(action: PlannedAction | None) -> bool:
    if action is None or action.kind != "click":
        return False
    return "扫荡" in (action.label or "")


def run_live(
    task: DailyCommissionTask,
    grab: Callable[[], np.ndarray],
    clicker: Clicker,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    timeout_sec: float | None = None,
    max_steps: int | None = None,
    log: Callable[[str], None] | None = None,
) -> LiveRunResult:
    """按当前画面一路执行到完成、停住或超时。

    从世界地图、区域地图、城镇或协会都能起步；认不出的中间页先等，
    不会点「扫荡」，战斗中只等待。
    """
    timeout_sec = config.LIVE_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    emit = log or (lambda _line: None)
    deadline = now() + timeout_sec
    steps = 0
    history: list[str] = []
    miss_streak = 0
    same_streak = 0
    last_key: tuple | None = None
    last_result: StepResult | None = None

    while now() < deadline:
        if max_steps is not None and steps >= max_steps:
            message = f"已达到最大步数 {max_steps}，停止。"
            emit(message)
            return LiveRunResult("timeout", message, steps, last_result, history)

        frame = grab()
        result = task.plan(frame)
        last_result = result
        steps += 1
        line = _format_step(steps, result)
        history.append(line)
        emit(line)
        logger.info("%s", line)

        if result.status == "done":
            message = "委托已完成。"
            emit(message)
            return LiveRunResult("done", message, steps, result, history)

        action = result.action
        if is_sweep_action(action):
            message = "计划要点「扫荡」，已停止以免误点。"
            emit(message)
            return LiveRunResult("refused", message, steps, result, history)

        key = (
            result.status,
            result.scene.value if result.scene is not None else "",
            action.kind if action else "",
            action.label if action else "",
            action.x if action else None,
            action.y if action else None,
        )
        if key == last_key:
            same_streak += 1
        else:
            same_streak = 0
            last_key = key

        if result.status in {"halt_missing", "unknown"}:
            miss_streak += 1
            if miss_streak >= config.LIVE_UNKNOWN_RETRY:
                message = result.message or (
                    action.message if action else "无法继续"
                )
                emit(f"停止：{message}")
                return LiveRunResult("halted", message, steps, result, history)
            sleep(config.CONFIRM_POLL_SEC)
            continue
        miss_streak = 0

        if result.status == "waiting_battle" or (action and action.kind == "wait"):
            if result.status != "waiting_battle" and same_streak >= config.LIVE_STUCK_LIMIT:
                message = (
                    result.message
                    or (action.message if action else None)
                    or "连续多次停在同一等待，画面没有变化，已停止。"
                )
                emit(f"停止：{message}")
                return LiveRunResult("stuck", message, steps, result, history)
            wait_for = (
                action.delay_sec
                if action and action.delay_sec
                else (
                    config.BATTLE_POLL_SEC
                    if result.status == "waiting_battle"
                    else config.CONFIRM_POLL_SEC
                )
            )
            sleep(wait_for)
            continue

        if result.status == "skip_unknown" or action is None:
            if same_streak >= config.LIVE_STUCK_LIMIT:
                message = (
                    result.message
                    or (action.message if action else None)
                    or "连续多次无法规划下一步，已停止。"
                )
                emit(f"停止：{message}")
                return LiveRunResult("stuck", message, steps, result, history)
            sleep(config.CONFIRM_POLL_SEC)
            continue

        if action.kind == "halt":
            message = action.message or result.message or action.label
            emit(f"停止：{message}")
            return LiveRunResult("halted", message, steps, result, history)

        if action.kind == "click":
            if action.x is None or action.y is None:
                message = f"点击「{action.label}」缺少坐标，已停止。"
                emit(message)
                return LiveRunResult("halted", message, steps, result, history)
            if same_streak >= config.LIVE_STUCK_LIMIT:
                message = (
                    f"连续 {same_streak + 1} 次计划点击「{action.label}」"
                    f"@ ({action.x}, {action.y})，画面没有变化，已停止。"
                )
                emit(message)
                return LiveRunResult("stuck", message, steps, result, history)
            clicker.click(action.x, action.y)
            sleep(action.delay_sec or config.ACTION_INTERVAL_SEC)
            continue

        if action.kind == "swipe":
            swipe = getattr(clicker, "swipe", None)
            if not callable(swipe) or None in (
                action.x,
                action.y,
                action.x2,
                action.y2,
            ):
                message = "需要滑动画面，但当前点击后端不能滑动，已停止。"
                emit(message)
                return LiveRunResult("halted", message, steps, result, history)
            if same_streak >= config.LIVE_STUCK_LIMIT:
                message = "地图滑动多次后仍看不到目标，已停止。"
                emit(message)
                return LiveRunResult("stuck", message, steps, result, history)
            swipe(action.x, action.y, action.x2, action.y2)
            sleep(action.delay_sec or config.ACTION_INTERVAL_SEC)
            continue

        message = f"未处理的动作：{action.kind} {action.label}"
        emit(message)
        return LiveRunResult("halted", message, steps, result, history)

    message = f"在 {timeout_sec:.0f} 秒内没有完成委托，已停止。"
    emit(message)
    return LiveRunResult("timeout", message, steps, last_result, history)


def _format_step(steps: int, result: StepResult) -> str:
    action = result.action.brief() if result.action else "无动作"
    return f"[{steps}] {result.scene.zh_name} / {result.status} → {action}"
