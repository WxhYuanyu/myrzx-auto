"""窗口配置与非 Windows 行为（不依赖 pywin32）。"""

from __future__ import annotations

import pytest

from src import config
from src.window import WindowError, find_game_window, is_windows, list_windows


def test_default_emulator_is_mumu():
    assert config.DEFAULT_EMULATOR == "mumu"
    assert "MuMu模拟器" in config.WINDOW_TITLE_KEYWORDS
    assert "MuMu安卓设备" in config.WINDOW_TITLE_KEYWORDS
    for name in ("MuMuPlayer", "NemuPlayer", "MuMuNxDevice"):
        assert name in config.RENDER_CHILD_NAMES
    assert "Qt5156QWindowIcon" in config.WINDOW_CLASS_HINTS
    assert "Qt5QWindowIcon" in config.WINDOW_CLASS_HINTS


@pytest.mark.skipif(is_windows(), reason="本项验证非 Windows 上的明确报错")
def test_list_windows_errors_clearly_off_windows():
    with pytest.raises(WindowError) as exc:
        list_windows()
    assert "Windows" in str(exc.value)


@pytest.mark.skipif(is_windows(), reason="本项验证非 Windows 上的明确报错")
def test_find_game_window_errors_clearly_off_windows():
    with pytest.raises(WindowError) as exc:
        find_game_window()
    assert "Windows" in str(exc.value)
