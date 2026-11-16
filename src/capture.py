"""截图抽象：测试注入图片；Windows 上截取窗口客户区。"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol

import numpy as np

from src.vision.image import load_bgr
from src.window import FoundWindow, WindowError, is_windows


class FrameSource(Protocol):
    def grab(self) -> np.ndarray:
        """返回当前画面，BGR uint8。"""
        ...


class ImageFrameSource:
    """把一张静态图当作画面来源，供测试和 --dry-run 使用。"""

    def __init__(self, image: str | Path | np.ndarray) -> None:
        self._image = load_bgr(image)

    def grab(self) -> np.ndarray:
        return self._image.copy()


class FolderFrameSource:
    """按顺序每次 grab 返回文件夹（或显式列表）里的下一张图。"""

    def __init__(self, images: Iterable[str | Path]) -> None:
        self._images = [Path(p) for p in images]
        if not self._images:
            raise ValueError("FolderFrameSource 需要至少一张图")
        self._index = 0

    def __len__(self) -> int:
        return len(self._images)

    def __iter__(self) -> Iterator[Path]:
        return iter(self._images)

    @property
    def paths(self) -> list[Path]:
        return list(self._images)

    def grab(self) -> np.ndarray:
        path = self._images[min(self._index, len(self._images) - 1)]
        self._index += 1
        return load_bgr(path)


class WindowCapture:
    """截取指定 HWND 的客户区。非 Windows 上初始化即报错。"""

    def __init__(self, hwnd: int) -> None:
        if not is_windows():
            raise WindowError("窗口截图只在 Windows 上可用。")
        self.hwnd = int(hwnd)

    def grab(self) -> np.ndarray:
        return capture_client_area(self.hwnd)


def capture_client_area(hwnd: int) -> np.ndarray:
    """截取窗口客户区为 BGR 图。优先 PrintWindow，失败则退回 BitBlt。"""
    if not is_windows():
        raise WindowError("窗口截图只在 Windows 上可用。")
    try:
        import win32gui  # type: ignore
        import win32ui  # type: ignore
        import win32con  # type: ignore
        from ctypes import windll
    except ImportError as exc:
        raise WindowError("窗口截图需要 pywin32。请执行: pip install pywin32") from exc

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = int(right - left)
    height = int(bottom - top)
    if width <= 0 or height <= 0:
        raise WindowError(f"窗口客户区尺寸无效: {width}x{height}")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)

    # PW_RENDERFULLCONTENT = 2，对 GPU/模拟器窗口更可靠。
    printed = False
    try:
        printed = bool(windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2))
    except Exception:
        printed = False
    if not printed:
        try:
            # 客户区相对窗口左上的偏移
            point_left, point_top = win32gui.ClientToScreen(hwnd, (0, 0))
            win_left, win_top, _, _ = win32gui.GetWindowRect(hwnd)
            ox = point_left - win_left
            oy = point_top - win_top
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (ox, oy), win32con.SRCCOPY)
        except Exception as exc:
            _cleanup_dc(win32gui, hwnd, hwnd_dc, mfc_dc, save_dc, bitmap)
            raise WindowError(f"截取窗口失败: {exc}") from exc

    try:
        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)
        array = np.frombuffer(bmp_bits, dtype=np.uint8)
        array = array.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
        # win32 位图为 BGRA
        bgr = array[:, :, :3].copy()
    finally:
        _cleanup_dc(win32gui, hwnd, hwnd_dc, mfc_dc, save_dc, bitmap)
    return bgr


def make_window_capture(found: FoundWindow) -> WindowCapture:
    return WindowCapture(found.hwnd)


def _cleanup_dc(win32gui, hwnd, hwnd_dc, mfc_dc, save_dc, bitmap) -> None:
    try:
        win32gui.DeleteObject(bitmap.GetHandle())
    except Exception:
        pass
    try:
        save_dc.DeleteDC()
    except Exception:
        pass
    try:
        mfc_dc.DeleteDC()
    except Exception:
        pass
    try:
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        pass

