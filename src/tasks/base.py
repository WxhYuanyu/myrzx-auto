"""任务基类：等待预算、点击并确认、统一日志。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from src import config
from src.interaction import Clicker, click_and_confirm
from src.vision.types import Match, Scene

logger = logging.getLogger("myrzx.task")


@dataclass
class PlannedAction:
    """一次计划中的操作。dry-run 只打印，不执行。"""

    kind: str  # click / halt / wait / swipe
    label: str
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    match: Match | None = None
    message: str = ""
    delay_sec: float | None = None
    hold_ms: int | None = None

    def brief(self) -> str:
        if self.kind == "click" and self.x is not None and self.y is not None:
            if self.hold_ms:
                text = f"稍微按住「{self.label}」@ ({self.x}, {self.y}) {self.hold_ms / 1000:.1f}秒"
            else:
                text = f"点击「{self.label}」@ ({self.x}, {self.y})"
            if self.delay_sec:
                text += f"，随后等待 {self.delay_sec:.1f} 秒"
            return text
        if self.kind == "swipe" and None not in (self.x, self.y, self.x2, self.y2):
            return f"滑动「{self.label}」({self.x}, {self.y}) → ({self.x2}, {self.y2})"
        if self.kind == "halt":
            return f"停止：{self.message or self.label}"
        if self.kind == "wait":
            return f"等待：{self.label}" + (f" {self.message}" if self.message else "")
        return f"{self.kind}: {self.label} {self.message}".strip()


@dataclass
class StepResult:
    scene: Scene
    reason: str
    matches: list[Match] = field(default_factory=list)
    action: PlannedAction | None = None
    status: str = "continue"  # continue / halt_need_next_screen / halt_missing / unknown / skip_unknown / waiting_battle / done
    message: str = ""

    def brief(self) -> str:
        lines = [
            f"识别页面: {self.scene.value}（{self.scene.zh_name}）",
            f"原因: {self.reason}",
        ]
        if self.matches:
            lines.append("匹配结果:")
            for match in self.matches:
                lines.append(f"  - {match.brief()}")
        if self.action:
            lines.append(f"下一步: {self.action.brief()}")
        if self.message:
            lines.append(self.message)
        lines.append(f"状态: {self.status}")
        return "\n".join(lines)


class TaskBase:
    name = "task"

    def __init__(self) -> None:
        self.log = logging.getLogger(f"myrzx.task.{self.name}")

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        raise NotImplementedError

    def press_and_confirm(
        self,
        clicker: Clicker,
        grab: Callable[[], np.ndarray],
        action: PlannedAction,
        confirm: Callable[[np.ndarray], bool],
        *,
        timeout: float | None = None,
    ) -> bool:
        if action.kind != "click" or action.x is None or action.y is None:
            self.log.error("press_and_confirm 收到非点击动作: %s", action)
            return False
        self.log.info("执行 %s", action.brief())
        ok = click_and_confirm(
            clicker,
            grab,
            action.x,
            action.y,
            confirm,
            timeout=timeout if timeout is not None else config.CONFIRM_TIMEOUT_SEC,
        )
        if ok:
            self.log.info("步骤成功：%s 后画面已确认", action.label)
        else:
            self.log.warning(
                "步骤失败：点击「%s」后未在时限内看到预期页面", action.label
            )
        return ok

    def sleep(self, seconds: float | None = None) -> None:
        time.sleep(config.ACTION_INTERVAL_SEC if seconds is None else seconds)
