"""MuMu / Android ADB 截图和点击。

窗口 PostMessage 经常到不了模拟器里的游戏，所以 --live 默认走 ADB：
用 screencap 取 1080×1920 画面，再用 input tap 按同一套坐标点击。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import which

import numpy as np

from src import config
from src.vision.image import load_bgr

logger = logging.getLogger("myrzx.adb")


class AdbError(RuntimeError):
    """找不到 adb、设备不在线，或截图/点击失败。"""


@dataclass
class AdbDevice:
    adb_path: str
    serial: str

    def run(
        self,
        args: list[str],
        *,
        timeout: float = 20.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.adb_path, "-s", self.serial, *args]
        logger.debug("adb: %s", " ".join(cmd))
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_no_window_flag(),
            )
        except FileNotFoundError as exc:
            raise AdbError(f"找不到 adb：{self.adb_path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb 超时：{' '.join(args)}") from exc
        if check and completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()
            raise AdbError(f"adb {' '.join(args)} 失败：{err or completed.returncode}")
        return completed


def _no_window_flag() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def find_adb_path() -> str:
    configured = Path(config.ADB_PATH)
    if configured.is_file():
        return str(configured)
    for raw in config.ADB_CANDIDATE_PATHS:
        path = Path(raw)
        if path.is_file():
            return str(path)
    found = which("adb")
    if found:
        return found
    raise AdbError(
        "找不到 adb。请确认 MuMu 已安装，或在 src/config.py 里填写 ADB_PATH。"
    )


def _run_adb(
    adb_path: str,
    args: list[str],
    *,
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [adb_path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_no_window_flag(),
        )
    except FileNotFoundError as exc:
        raise AdbError(f"找不到 adb：{adb_path}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb 超时：{' '.join(args)}") from exc


def list_adb_devices(adb_path: str) -> dict[str, str]:
    completed = _run_adb(adb_path, ["devices"])
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise AdbError(f"adb devices 失败：{err or completed.returncode}")
    devices: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]
    return devices


def connect_adb(serial: str | None = None) -> AdbDevice:
    """优先连接 127.0.0.1:16384，不行再试备选端口。"""
    adb_path = find_adb_path()
    preferred: list[str] = []
    for item in (serial, config.ADB_SERIAL, *config.ADB_SERIAL_FALLBACKS):
        if item and item not in preferred:
            preferred.append(item)

    devices = list_adb_devices(adb_path)
    for item in preferred:
        if devices.get(item) == "device":
            logger.info("使用已在线的 ADB 设备 %s", item)
            return AdbDevice(adb_path, item)

    for item in preferred:
        _run_adb(adb_path, ["connect", item], timeout=10.0)

    devices = list_adb_devices(adb_path)
    for item in preferred:
        if devices.get(item) == "device":
            logger.info("已连接 ADB 设备 %s", item)
            return AdbDevice(adb_path, item)

    for item, state in devices.items():
        if state == "device":
            logger.info("改用已在线的 ADB 设备 %s", item)
            return AdbDevice(adb_path, item)

    raise AdbError(
        "没有可用的 ADB 设备。请确认 MuMu 已打开，默认端口是 127.0.0.1:16384。"
        + (f" 当前：{devices}" if devices else "")
    )


class AdbFrameSource:
    """通过 adb screencap 拉取当前游戏画面，返回 BGR 图。"""

    def __init__(self, device: AdbDevice, *, remote: str | None = None) -> None:
        self.device = device
        self.remote = remote or config.ADB_SCREENCAP_REMOTE
        self._local = Path(tempfile.gettempdir()) / "myrzx_screencap.png"

    def grab(self) -> np.ndarray:
        self.device.run(["shell", "screencap", "-p", self.remote])
        if self._local.exists():
            try:
                self._local.unlink()
            except OSError:
                pass
        self.device.run(["pull", self.remote, str(self._local)])
        if not self._local.is_file() or self._local.stat().st_size < 100:
            raise AdbError("adb 截图失败：本地文件为空。")
        return load_bgr(self._local)


class AdbClicker:
    """按设备像素坐标发送 input tap / swipe。"""

    def __init__(self, device: AdbDevice) -> None:
        self.device = device

    def click(
        self,
        x: int,
        y: int,
        *,
        hwnd: int | None = None,
        hold_ms: int | None = None,
    ) -> None:
        # 进入地区时短促的 input tap 可能被忽略，改用同点滑动来按住一小会。
        if hold_ms and int(hold_ms) > 0:
            self.device.run(
                [
                    "shell",
                    "input",
                    "swipe",
                    str(int(x)),
                    str(int(y)),
                    str(int(x)),
                    str(int(y)),
                    str(int(hold_ms)),
                ]
            )
            logger.info("adb 稍微按住 (%d, %d) %d毫秒", int(x), int(y), int(hold_ms))
            return
        self.device.run(["shell", "input", "tap", str(int(x)), str(int(y))])
        logger.info("adb 点击 (%d, %d)", int(x), int(y))

    def swipe(
        self,
        x: int,
        y: int,
        x2: int,
        y2: int,
        duration_ms: int = 400,
    ) -> None:
        self.device.run(
            [
                "shell",
                "input",
                "swipe",
                str(int(x)),
                str(int(y)),
                str(int(x2)),
                str(int(y2)),
                str(int(duration_ms)),
            ]
        )
        logger.info(
            "adb 滑动 (%d, %d) → (%d, %d)",
            int(x),
            int(y),
            int(x2),
            int(y2),
        )
