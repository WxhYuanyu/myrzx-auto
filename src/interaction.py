"""点击抽象：带确认回调钩子、动作间隔、光标恢复。

Windows 上后续可用 PostMessage（首选，不移动光标）或 SendInput。
Linux / macOS 上安全地做成空操作或明确报错，避免误点。
真实点击默认关闭，只有在 Windows 且显式传入 live=True 时才会发出。
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from src import config
from src.window import is_windows

logger = logging.getLogger("myrzx.interaction")


class Clicker(Protocol):
    def click(self, x: int, y: int, *, hwnd: int | None = None, hold_ms: int | None = None) -> None:
        """在客户区坐标 (x, y) 单击；hold_ms 为按住时间。"""
        ...


class DryRunClicker:
    """只记录计划点击，不向系统发送任何输入。"""

    def __init__(self) -> None:
        self.history: list[tuple[int, int]] = []

    def click(self, x: int, y: int, *, hwnd: int | None = None, hold_ms: int | None = None) -> None:
        self.history.append((x, y))
        logger.info("dry-run：计划点击客户区坐标 (%d, %d)，不会发送真实点击", x, y)


class NoOpClicker:
    """Linux 下的安全桩：拒绝真实点击。"""

    def click(self, x: int, y: int, *, hwnd: int | None = None, hold_ms: int | None = None) -> None:
        raise RuntimeError(
            f"当前系统 {sys.platform} 不能发送游戏点击。"
            "请在 Windows 上使用 --live，或改用 --dry-run。"
        )


class WindowsClicker:
    """向目标窗口客户区发送鼠标左键单击。

    优先 PostMessage（不移动系统光标）。若调用方以后要改用 SendInput，
    应先保存光标位置，发送后再恢复。
    """

    def __init__(self, hwnd: int) -> None:
        if not is_windows():
            raise RuntimeError("WindowsClicker 只能在 Windows 上创建。")
        self.hwnd = int(hwnd)

    def click(self, x: int, y: int, *, hwnd: int | None = None, hold_ms: int | None = None) -> None:
        target = int(hwnd or self.hwnd)
        _post_click(target, x, y, hold_ms=hold_ms)
        time.sleep(config.ACTION_INTERVAL_SEC)


def make_clicker(*, live: bool, hwnd: int | None = None) -> Clicker:
    if not live:
        return DryRunClicker()
    if not is_windows():
        return NoOpClicker()
    if hwnd is None:
        raise RuntimeError("--live 需要先找到游戏窗口。")
    return WindowsClicker(hwnd)


def click_and_confirm(
    clicker: Clicker,
    grab: Callable[[], np.ndarray],
    x: int,
    y: int,
    confirm: Callable[[np.ndarray], bool],
    *,
    timeout: float | None = None,
    poll: float | None = None,
    hwnd: int | None = None,
) -> bool:
    """点击后轮询画面，直到 confirm(frame) 为真或超时。

    confirm 由任务层提供，例如「已进入协会室内」。
    返回是否在时限内确认成功。
    """
    timeout = config.CONFIRM_TIMEOUT_SEC if timeout is None else timeout
    poll = config.CONFIRM_POLL_SEC if poll is None else poll
    logger.info("点击 (%d, %d)，随后等待画面确认，时限 %.1f 秒", x, y, timeout)
    clicker.click(x, y, hwnd=hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        frame = grab()
        try:
            ok = bool(confirm(frame))
        except Exception:
            logger.exception("确认回调出错")
            ok = False
        if ok:
            logger.info("点击后画面确认成功")
            return True
    logger.warning("点击 (%d, %d) 后在 %.1f 秒内未得到预期画面", x, y, timeout)
    return False


def _post_click(hwnd: int, x: int, y: int, hold_ms: int | None = None) -> None:
    try:
        import win32gui  # type: ignore
        import win32con  # type: ignore
        import win32api  # type: ignore
    except ImportError as exc:
        raise RuntimeError("真实点击需要 pywin32。请执行: pip install pywin32") from exc

    # lParam 打包客户区坐标
    lparam = win32api.MAKELONG(int(x), int(y))
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep((hold_ms or 20) / 1000.0)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    logger.info("已向 HWND=0x%X 发送 PostMessage 单击 (%d, %d)", hwnd, x, y)
