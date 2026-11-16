"""查找模拟器/游戏窗口。仅在 Windows 上真正枚举；其他系统给出明确错误。

默认面向 MuMu：先找标题含「MuMu模拟器」或「MuMu安卓设备」的可见顶层窗口，
再定位渲染子窗口（MuMuPlayer / NemuPlayer / MuMuNxDevice），
截图和点击都对准子窗口客户区，避开外壳工具栏。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from collections.abc import Sequence

from src import config


class WindowError(RuntimeError):
    """找不到窗口，或当前系统不支持窗口枚举。"""


@dataclass
class WindowRecord:
    hwnd: int
    title: str
    class_name: str
    visible: bool
    left: int
    top: int
    width: int
    height: int
    client_width: int
    client_height: int
    children: list["WindowRecord"] = field(default_factory=list)

    def brief(self) -> str:
        vis = "可见" if self.visible else "隐藏"
        return (
            f"HWND=0x{self.hwnd:X} title={self.title!r} class={self.class_name!r} "
            f"{vis} rect=({self.left},{self.top},{self.width}x{self.height}) "
            f"client={self.client_width}x{self.client_height}"
        )


@dataclass
class FoundWindow:
    """最终用于截图/点击的窗口，以及它所属的顶层外壳。"""

    top_level: WindowRecord
    target: WindowRecord  # 优先为渲染子窗口
    used_render_child: bool

    @property
    def hwnd(self) -> int:
        return self.target.hwnd


def is_windows() -> bool:
    return sys.platform == "win32"


def list_windows(*, include_children: bool = True) -> list[WindowRecord]:
    """枚举可见顶层窗口，可选带上子窗口。非 Windows 会抛出 WindowError。"""
    if not is_windows():
        raise WindowError(
            "窗口枚举只在 Windows 上可用。"
            "请在安装了 MuMu 模拟器的 Windows 电脑上运行: python main.py --list-windows"
        )
    return _list_windows_win32(include_children=include_children)


def find_game_window(
    title_keywords: Sequence[str] | None = None,
    fallback_keywords: Sequence[str] | None = None,
    render_child_names: Sequence[str] | None = None,
) -> FoundWindow:
    """按配置查找 MuMu（或其他已配置模拟器）的主窗口与渲染子窗口。"""
    title_keywords = tuple(title_keywords or config.WINDOW_TITLE_KEYWORDS)
    fallback_keywords = tuple(
        fallback_keywords or config.WINDOW_TITLE_FALLBACK_KEYWORDS
    )
    render_child_names = tuple(render_child_names or config.RENDER_CHILD_NAMES)

    windows = list_windows(include_children=True)
    candidates = _pick_candidates(windows, title_keywords)
    if not candidates:
        candidates = _pick_candidates(windows, fallback_keywords)
    if not candidates:
        sample = ", ".join(
            f"{w.title!r}" for w in windows[:8] if w.title
        ) or "(没有带标题的可见窗口)"
        raise WindowError(
            "没有找到匹配的模拟器窗口。"
            f"当前配置关键词={list(title_keywords) + list(fallback_keywords)}。"
            f"可见窗口标题示例: {sample}。"
            "请运行 python main.py --list-windows 并把输出发给开发者以便锁定标题/类名。"
        )

    # 多个相似 Qt 窗口时取客户区最大的可见主窗口（更新器通常更小）。
    top = max(candidates, key=lambda w: w.client_width * w.client_height)
    child = _find_render_child(top, render_child_names)
    if child is not None:
        return FoundWindow(top_level=top, target=child, used_render_child=True)
    return FoundWindow(top_level=top, target=top, used_render_child=False)


def format_window_tree(windows: Sequence[WindowRecord]) -> str:
    """把顶层及子窗口格式化成可读清单，供 --list-windows 使用。"""
    lines = ["== 顶层窗口 =="]
    for win in windows:
        lines.append(win.brief())
        for child in win.children:
            prefix = "    "
            lines.append(prefix + child.brief())
            for grand in child.children:
                lines.append(prefix + prefix + grand.brief())
    return "\n".join(lines)


def _pick_candidates(
    windows: Sequence[WindowRecord], keywords: Sequence[str]
) -> list[WindowRecord]:
    if not keywords:
        return []
    picked: list[WindowRecord] = []
    for win in windows:
        if not win.visible:
            continue
        if win.width <= 0 or win.height <= 0:
            continue
        title = win.title or ""
        if any(key and key in title for key in keywords):
            picked.append(win)
    return picked


def _find_render_child(
    top: WindowRecord, names: Sequence[str]
) -> WindowRecord | None:
    def _walk(nodes: Sequence[WindowRecord]) -> WindowRecord | None:
        for node in nodes:
            haystack = f"{node.title}\0{node.class_name}"
            if any(name and name in haystack for name in names):
                if node.width > 0 and node.height > 0:
                    return node
            nested = _walk(node.children)
            if nested is not None:
                return nested
        return None

    return _walk(top.children)


# ---------------------------------------------------------------------------
# Windows 实现（延迟 import pywin32）
# ---------------------------------------------------------------------------

def _list_windows_win32(*, include_children: bool) -> list[WindowRecord]:
    try:
        import win32gui  # type: ignore
        import win32con  # type: ignore
    except ImportError as exc:
        raise WindowError(
            "在 Windows 上枚举窗口需要 pywin32。请执行: pip install pywin32"
        ) from exc

    tops: list[WindowRecord] = []

    def _enum_top(hwnd: int, _extra: object) -> bool:
        # 只要顶层窗口；不可见的也列出，方便对照，但查找时会再过滤。
        if win32gui.GetParent(hwnd):
            return True
        record = _describe_hwnd(win32gui, win32con, hwnd)
        if include_children:
            record.children = _enum_children(win32gui, win32con, hwnd, depth=0)
        tops.append(record)
        return True

    win32gui.EnumWindows(_enum_top, None)
    # 可见、有标题的排在前面，便于阅读
    tops.sort(key=lambda w: (not w.visible, not bool(w.title), -(w.width * w.height)))
    return tops


def _enum_children(win32gui, win32con, parent: int, *, depth: int) -> list[WindowRecord]:
    children: list[WindowRecord] = []
    if depth > 3:
        return children

    def _callback(hwnd: int, _extra: object) -> bool:
        record = _describe_hwnd(win32gui, win32con, hwnd)
        record.children = _enum_children(win32gui, win32con, hwnd, depth=depth + 1)
        children.append(record)
        return True

    try:
        win32gui.EnumChildWindows(parent, _callback, None)
    except Exception:
        # 某些窗口不允许枚举子窗口
        pass
    return children


def _describe_hwnd(win32gui, win32con, hwnd: int) -> WindowRecord:
    title = ""
    class_name = ""
    try:
        title = win32gui.GetWindowText(hwnd) or ""
    except Exception:
        title = ""
    try:
        class_name = win32gui.GetClassName(hwnd) or ""
    except Exception:
        class_name = ""
    visible = False
    try:
        visible = bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        visible = False
    left = top = width = height = 0
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = max(0, right - left)
        height = max(0, bottom - top)
    except Exception:
        pass
    client_w = client_h = 0
    try:
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        client_w = max(0, cr - cl)
        client_h = max(0, cb - ct)
    except Exception:
        pass
    return WindowRecord(
        hwnd=int(hwnd),
        title=title,
        class_name=class_name,
        visible=visible,
        left=int(left),
        top=int(top),
        width=int(width),
        height=int(height),
        client_width=int(client_w),
        client_height=int(client_h),
    )
