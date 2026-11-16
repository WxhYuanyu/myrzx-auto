"""全局配置：窗口查找、超时、画面比例、资源路径。

默认为 MuMu 模拟器。窗口标题/类名均可在此修改，或之后用 --list-windows
在实际 Windows 环境锁定精确值。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATES_DIR = ASSETS_DIR / "templates"
TEMPLATE_MANIFEST = TEMPLATES_DIR / "manifest.json"
DEFAULT_FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "walkthrough"

# ---------------------------------------------------------------------------
# 窗口查找（默认 MuMu，可配置）
# ---------------------------------------------------------------------------
# 人们用安卓模拟器玩这款竖屏手游，没有官方 PC 客户端。
# 常见模拟器顶层窗口标题（占位默认走 MuMu，可改成你的实际标题）：
#   MuMu 12:     「MuMu模拟器12」
#   旧版 MuMu:   「MuMu模拟器」
#   MuMu 5.0:    「MuMu模拟器」「MuMuNxDevice」「MuMu安卓设备」
#   雷电:        「雷电模拟器」/ 「LDPlayer」
#   夜神:        「Nox」/ 「夜神模拟器」
DEFAULT_EMULATOR = "mumu"

# 优先挑选标题中包含以下任一关键词、且可见的主窗口。
# 有多个类似的 Qt 窗口（例如更新器）时，优先标题含「MuMu模拟器」或
# 「MuMu安卓设备」的可见窗口，再按客户区面积取最大的那个。
MUMU_TITLE_KEYWORDS = (
    "MuMu模拟器",
    "MuMu安卓设备",
)

# 次要标题关键词（当主关键词没命中时再试）。
MUMU_TITLE_FALLBACK_KEYWORDS = (
    "MuMuNxDevice",
    "MuMu Player",
    "MuMuPlayer",
)

# 顶层窗口类名参考（不同 MuMu 版本会变，只作提示，不作为唯一条件）。
MUMU_CLASS_HINTS = (
    "Qt5156QWindowIcon",  # MuMu 12 常见
    "Qt5QWindowIcon",
)

# 渲染子窗口：截图和点击应对准它，而不是带工具栏的完整外壳。
#   MuMu 12  -> 子窗口名/标题 MuMuPlayer
#   旧版 MuMu -> NemuPlayer
#   MuMu 5.0 -> MuMuNxDevice
MUMU_RENDER_CHILD_NAMES = (
    "MuMuPlayer",
    "NemuPlayer",
    "MuMuNxDevice",
)

# 若以后改用其他模拟器，可改这两个元组（或在运行时覆盖）。
WINDOW_TITLE_KEYWORDS = MUMU_TITLE_KEYWORDS
WINDOW_TITLE_FALLBACK_KEYWORDS = MUMU_TITLE_FALLBACK_KEYWORDS
WINDOW_CLASS_HINTS = MUMU_CLASS_HINTS
RENDER_CHILD_NAMES = MUMU_RENDER_CHILD_NAMES

# ---------------------------------------------------------------------------
# 视觉 / 交互
# ---------------------------------------------------------------------------
# 模板匹配默认阈值（TM_CCOEFF_NORMED）。多尺度用于裁切图与完整窗口之间的尺寸差。
MATCH_THRESHOLD = 0.75
# 优先尝试 1.0（同源全分辨率）和实机常见的 ~2.2（旧裁切模板对 1080 图），
# 以及 0.4–0.5（全分辨率模板对旧局部裁切图）。单模板 ≥0.98 提前结束。
TEMPLATE_SCALES = (
    1.00,
    2.20,
    2.25,
    2.00,
    0.45,
    0.50,
    0.40,
    0.60,
    0.70,
    0.80,
    0.90,
    1.10,
    1.20,
    1.35,
    1.50,
    1.75,
    2.50,
)

# 默认尺度里先扫完这一组；若已有 ≥0.90 的命中就不再扫更冷门的尺度。
FAST_SCALES = (1.00, 2.20, 2.25, 2.00, 0.45, 0.50, 0.40)

# 游戏为约 9:16 竖屏。完整模拟器客户区应接近此比例；
# 用户提供的部分截图是局部裁切，分类时不强制检查比例。
PORTRAIT_ASPECT = 9 / 16  # width / height
ASPECT_TOLERANCE = 0.08

ACTION_INTERVAL_SEC = 0.45
CONFIRM_TIMEOUT_SEC = 8.0
CONFIRM_POLL_SEC = 0.35
FIND_WINDOW_TIMEOUT_SEC = 5.0

# 关闭详情/列表后需要等关窗动画，否则紧接着点「离开」会被吃掉。
CLOSE_ANIMATION_SEC = 0.8
# 战斗自动进行，只轮询截图直到胜利；时限要留足几分钟。
BATTLE_TIMEOUT_SEC = 240.0
BATTLE_POLL_SEC = 0.8
# 世界地图若停在南赛拉姆、看不见王城莉莉托斯，向下滑动几次再放弃。
MAP_SWIPE_MAX = 4

# 委托相关。类型1按屏幕原文「喳喳布林入侵」（不是「嗥嗥」或「嗫嗫」）。
PRIORITY_COMMISSION = "喳喳布林入侵"
DAILY_COMMISSION_CAP = 6
# 已知奖励（wiki / 卡片 / 获得物品弹窗可见）：400 金币 + 20 氚金等；需通关 1-3。
PRIORITY_COMMISSION_REWARD = "400 金币 + 20 氚金"
PRIORITY_COMMISSION_STAGE = "1-3"
# 类型2：交物品。背包里已有圣遗物时，在图兰顿城内上交即可。
TURN_IN_COMMISSION = "仇恨会令我成长"
TURN_IN_OBJECTIVE = "收集1份失落的圣遗物后与图兰顿要塞的冒险者对话"
