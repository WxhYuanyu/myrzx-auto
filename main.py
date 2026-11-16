#!/usr/bin/env python3
"""牧羊人之心日常自动化入口。

默认是 dry-run：只识别画面、打印匹配框和计划动作，不发送真实点击。
真实点击必须同时满足：在 Windows 上，并且显式加上 --live。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 保证直接 `python main.py` 时能找到 src
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import config  # noqa: E402
from src.tasks.daily_commission import DailyCommissionTask  # noqa: E402
from src.vision.image import load_bgr  # noqa: E402
from src.window import (  # noqa: E402
    WindowError,
    find_game_window,
    format_window_tree,
    is_windows,
    list_windows,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

_TASK_SUMMARY = (
    "每日委托：王城莉莉托斯 → 协会 → 委托 → 喳喳布林入侵 → 接收 → "
    "返回/离开 → 探险 → 1-3 → 与小孩对话 → 跳过剧情 → 等待战斗 → "
    "触摸继续 → 任务日志 → 完成 → 获得物品"
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_windows:
        return _cmd_list_windows()

    if args.live:
        return _cmd_live()

    # 默认 dry-run
    path = Path(args.dry_run) if args.dry_run else config.DEFAULT_FIXTURE_DIR
    return _cmd_dry_run(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="牧羊人之心日常自动化（当前范围：每日委托「喳喳布林入侵」全程）",
    )
    parser.add_argument(
        "--dry-run",
        nargs="?",
        const=str(config.DEFAULT_FIXTURE_DIR),
        metavar="PATH",
        help="对一张图或一个文件夹做识别与路径规划，不点击。"
        "省略路径时使用 tests/fixtures/walkthrough 下的实走截图。",
    )
    parser.add_argument(
        "--list-windows",
        action="store_true",
        help="在 Windows 上列出顶层窗口及相关子窗口的标题/类名，便于锁定 MuMu 精确匹配。",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="（默认关闭）在 Windows 上对模拟器窗口执行真实点击。Linux 上会被拒绝。",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="打印调试日志。",
    )
    return parser


def _cmd_list_windows() -> int:
    if not is_windows():
        print("当前不是 Windows，无法枚举模拟器窗口。")
        print()
        print("默认会查找 MuMu 模拟器，标题关键词：")
        print("  优先: " + " / ".join(config.MUMU_TITLE_KEYWORDS))
        print("  备选: " + " / ".join(config.MUMU_TITLE_FALLBACK_KEYWORDS))
        print("类名参考: " + " / ".join(config.MUMU_CLASS_HINTS))
        print(
            "找到顶层窗口后，会对渲染子窗口截图和点击（避开工具栏）："
            + " / ".join(config.MUMU_RENDER_CHILD_NAMES)
        )
        print()
        print("请在运行游戏的 Windows 电脑上执行:")
        print("  python main.py --list-windows")
        print("把完整输出发给开发者，以便锁定你这台机器上的精确标题和类名。")
        return 0

    try:
        windows = list_windows(include_children=True)
    except WindowError as exc:
        print(f"枚举窗口失败: {exc}")
        return 2

    print(format_window_tree(windows))
    print()
    try:
        found = find_game_window()
    except WindowError as exc:
        print("== 当前未能自动选用 ==")
        print(str(exc))
        return 1

    print("== 当前将选用 ==")
    print("顶层: " + found.top_level.brief())
    if found.used_render_child:
        print("渲染子窗口（将对此窗口截图和点击，避开工具栏）:")
        print("  " + found.target.brief())
    else:
        print("未找到 MuMuPlayer / NemuPlayer / MuMuNxDevice 子窗口，")
        print("将退回顶层客户区（可能含工具栏，请把 --list-windows 输出发给开发者）。")
        print("  " + found.target.brief())
    return 0


def _cmd_dry_run(path: Path) -> int:
    if not path.exists():
        print(f"路径不存在: {path}")
        return 2
    images = _collect_images(path)
    if not images:
        print(f"没有找到图片: {path}")
        return 2

    task = DailyCommissionTask()
    print(f"dry-run：共 {len(images)} 张图，不会发送真实点击。")
    print(f"任务: {_TASK_SUMMARY}")
    print()

    last_status = "continue"
    saw_skip = False
    for index, image_path in enumerate(images, start=1):
        print(f"[{index}/{len(images)}] {image_path.name}")
        image = load_bgr(image_path)
        h, w = image.shape[:2]
        print(f"    尺寸: {w}x{h}")
        result = task.plan(image)
        for line in result.brief().splitlines():
            print(f"    {line}")
        print()
        last_status = result.status
        if result.status == "skip_unknown":
            saw_skip = True

    if last_status == "done":
        print("==== 路径规划结束（委托已完成）====")
        print(_TASK_SUMMARY)
        print("战斗过程中不会点击；未收录的中间页会跳过。任何阶段都不会点「扫荡」。")
    elif last_status == "waiting_battle":
        print("==== 路径规划结束（正在等待战斗）====")
        print("已进入战斗，应继续轮询截图直到「战斗胜利」，不要点击。")
    elif last_status == "halt_need_next_screen":
        print("==== 路径规划结束（还缺画面）====")
        print("已知步骤无法继续，请补充对应截图。")
    elif last_status == "halt_missing":
        print("==== 在已知页面上缺少目标，已停止 ====")
    elif last_status == "unknown":
        print("==== 未能识别页面，已停止 ====")
    elif last_status == "skip_unknown" or saw_skip:
        print("==== dry-run 结束（已跳过未收录的中间页）====")
    else:
        print("==== dry-run 结束 ====")
    return 0


def _cmd_live() -> int:
    if not is_windows():
        print(
            f"错误：--live 只在 Windows 上可用（当前是 {sys.platform}）。"
            "请先用 python main.py --dry-run 查看识别结果。"
        )
        return 2

    try:
        found = find_game_window()
    except WindowError as exc:
        print(f"未能找到游戏窗口: {exc}")
        return 1

    print("已找到窗口，但 --live 的完整循环还需要先确认渲染子窗口截图可用，")
    print("并且用 --list-windows 核对这台机器上的精确标题和类名。")
    print("顶层: " + found.top_level.brief())
    print("目标: " + found.target.brief())
    print()
    print("状态机已覆盖「喳喳布林入侵」全程（接取、探险、小孩对话、等待战斗、领奖）。")
    print("请先运行 python main.py --list-windows，以及 --dry-run 验证识别。")
    print("确认窗口后再把真实点击循环接上。未收录的中间页会跳过，不会点「扫荡」。")
    return 0


def _collect_images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = [
        p
        for p in sorted(path.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    ]
    return files


if __name__ == "__main__":
    sys.exit(main())
