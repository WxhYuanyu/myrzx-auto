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
from src.tasks.claim_dailies import ClaimDailiesTask  # noqa: E402
from src.tasks.shop_buy import ShopBuyTask  # noqa: E402
from src.tasks.daily_commission import DailyCommissionTask  # noqa: E402
from src.tasks.phase import Phase  # noqa: E402
from src.tasks.daily_sweep import SweepState, first_recipe_for_sweep, sweep_plan_text  # noqa: E402
from src.tasks.recipes import CommissionKind, get_recipe  # noqa: E402
from src.vision.image import load_bgr  # noqa: E402
from src.adb_io import AdbClicker, AdbError, AdbFrameSource, connect_adb  # noqa: E402
from src.live import run_live  # noqa: E402
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
_TURN_IN_SUMMARY = (
    "每日委托：阿格莱恩「离开」→ 克里斯汀 → 图兰顿沙漠 → 协会 → 委托 → "
    "仇恨会令我成长 → 接收 → 返回/离开 → 点冒险者的脸 → 跳过剧情 → "
    "任务卷轴 → 标题 → 完成 → 获得物品"
)
_MULTI_BATTLE_SUMMARY = (
    "每日委托：阿格莱恩「前往克里斯汀」→ 图兰顿沙漠 → 协会 → 委托 → "
    "“热情”的冒险者 → 接收 → 探险 → 9-7 初步探索点「进入」三次"
    "（事件弹窗不计数）→ 离开 → 回程 → 点冒险者的脸 → 跳过剧情 → "
    "任务卷轴 → 标题 → 完成 → 获得物品"
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

    if args.list_quests:
        print(sweep_plan_text(), end="")
        return 0
    if args.claim and args.shop:
        print("不能同时使用 --claim 和 --shop。")
        return 2
    if args.live and args.claim:
        return _cmd_claim()
    if args.claim:
        print("一起领取已完成的每日委托需要同时加上 --live。")
        return 2
    if args.live and args.shop:
        return _cmd_shop()
    if args.shop:
        print("购买金币商店的目标商品需要同时加上 --live。")
        return 2
    if args.live:
        return _cmd_live(args.quest, location=args.location, start_phase=args.phase)

    if args.quest is None and not args.dry_run:
        print(sweep_plan_text(), end="")
        return 0

    # 默认 dry-run
    path = Path(args.dry_run) if args.dry_run else config.DEFAULT_FIXTURE_DIR
    quest = args.quest if args.quest is not None else config.PRIORITY_COMMISSION
    return _cmd_dry_run(path, quest, location=args.location)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "牧羊人之心日常自动化。每日委托按高 / 中 / 低三档，"
            "从图1起一个地区一个地区先做完高级，再从头扫中级，最后扫低级。"
        ),
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
        help="（默认关闭）通过 MuMu 的 ADB 截图并真实点击。不写 --quest 时按高 / 中 / 低扫城。",
    )
    parser.add_argument(
        "--claim",
        action="store_true",
        help="六次每日委托都做完后，一起打开带绿勾的任务卷轴，点每条标题和米色「完成」领奖。"
        "必须与 --live 一起使用。单条委托跑完时不会点「完成」。",
    )
    parser.add_argument(
        "--shop",
        action="store_true",
        help="在任意一座城打开「商店」，点右下「金币」，把目标商品买空"
        "（目前是可疑的果汁、魔铁矿）。买空是指可购数量变为 0/n"
        "（不一定是 0/2，只有 1 份就是 0/1）或「购买」变灰。"
        "清单里没有的就跳过。必须与 --live 一起使用。"
        "不会点「购买全部」「兑换」「时装」「氪金」。",
    )
    parser.add_argument(
        "--list-quests",
        action="store_true",
        help="打印高 / 中 / 低三档的扫城顺序，不截图也不点击。",
    )
    parser.add_argument(
        "--quest",
        default=None,
        help="只做这一条委托的标题。不写时，--live 会按高 / 中 / 低从图1起扫城。"
        "「保证商路畅通」有两条，必须再加 --location 浪人岬 或 --location 南赛拉姆。"
        "表里的「仇恨令我成长」「热情的冒险者」也会认成游戏标题。"
        "未知名称会直接停止，不会编造路线。",
    )
    parser.add_argument(
        "--location",
        default=None,
        metavar="PLACE",
        help="同名委托要注明地点。例如：--quest 保证商路畅通 --location 浪人岬。",
    )
    parser.add_argument(
        "--phase",
        default=None,
        metavar="NAME",
        help="从指定阶段接着跑。例如已经接取委托后，用 GO_STAGE 关闭列表并继续交物品或去战斗。",
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


def _summary_for(quest_name: str, location: str | None = None) -> str:
    recipe = get_recipe(quest_name, location=location)
    if recipe.summary:
        return recipe.summary
    if recipe.kind is CommissionKind.TURN_IN:
        return _TURN_IN_SUMMARY
    if recipe.kind is CommissionKind.MULTI_BATTLE:
        return _MULTI_BATTLE_SUMMARY
    return _TASK_SUMMARY


def _cmd_dry_run(path: Path, quest_name: str, location: str | None = None) -> int:
    if not path.exists():
        print(f"路径不存在: {path}")
        return 2
    images = _collect_images(path)
    if not images:
        print(f"没有找到图片: {path}")
        return 2
    try:
        recipe = get_recipe(quest_name, location=location)
    except KeyError as exc:
        print(str(exc))
        return 2

    task = DailyCommissionTask(recipe=recipe)
    summary = _summary_for(quest_name, location)
    print(f"dry-run：共 {len(images)} 张图，不会发送真实点击。")
    print(f"任务: {summary}")
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
        print(summary)
        print("未收录的中间页会跳过。任何阶段都不会点「扫荡」。")
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


def _cmd_live(quest_name: str | None, location: str | None = None, start_phase: str | None = None) -> int:
    auto_sweep = not quest_name
    try:
        recipe = first_recipe_for_sweep() if auto_sweep else get_recipe(quest_name, location=location)
    except KeyError as exc:
        print(str(exc))
        return 2

    try:
        device = connect_adb()
    except AdbError as exc:
        print(f"未能连接模拟器 ADB: {exc}")
        return 1

    task = DailyCommissionTask(recipe=recipe)
    if auto_sweep:
        task.auto_sweep = True
        task.sweep = SweepState.start()
        task.recipe = task.sweep.travel_recipe()
    if start_phase:
        try:
            task.phase = Phase(start_phase)
        except ValueError:
            names = ", ".join(item.value for item in Phase)
            print(f"未知阶段「{start_phase}」，可选：{names}")
            return 2
    source = AdbFrameSource(device)
    clicker = AdbClicker(device)
    if auto_sweep:
        summary = "按高 / 中 / 低三档扫城。单条做完先不点「完成」。"
        print(f"--live：ADB {device.serial} 截图并点击，按高 / 中 / 低从图1起扫城。")
        print(sweep_plan_text(), end="")
    else:
        summary = _summary_for(quest_name, location)
        print(f"--live：ADB {device.serial} 截图并点击，任务「{recipe.name}」。")
        print(f"任务: {summary}")
    if start_phase:
        print(f"从阶段 {task.phase.value} 继续。")
    print("从当前画面开始跑完全程。请不要手动点击。任何阶段都不会点「扫荡」。")
    print()

    result = run_live(task, source.grab, clicker, log=print)
    print()
    print(result.message)
    return 0 if result.status == "done" else 1


def _cmd_claim() -> int:
    try:
        device = connect_adb()
    except AdbError as exc:
        print(f"未能连接模拟器 ADB: {exc}")
        return 1

    task = ClaimDailiesTask()
    source = AdbFrameSource(device)
    clicker = AdbClicker(device)
    print(f"--live --claim：ADB {device.serial}，领取已完成的每日委托。")
    print("会点带绿勾的卷轴，再点每条标题（不点绿色印章）和详情里的米色「完成」。")
    print("未完成的委托不会去点。请不要手动点击。任何阶段都不会点「扫荡」。")
    print()
    result = run_live(task, source.grab, clicker, log=print)
    print()
    print(result.message)
    return 0 if result.status == "done" else 1


def _cmd_shop() -> int:
    try:
        device = connect_adb()
    except AdbError as exc:
        print(f"未能连接模拟器 ADB: {exc}")
        return 1

    task = ShopBuyTask()
    source = AdbFrameSource(device)
    clicker = AdbClicker(device)
    print(f"--live --shop：ADB {device.serial}，在任意一座城打开「商店」购买目标商品。")
    print("所有地区都是同一家商店。会点右下「金币」，拖动清单找到商品后点同一行的「购买」。")
    print("确认弹窗里的商品名对得上才点「是」，一直买到可购数量为 0 或「购买」变灰。")
    print("不会点「购买全部」「兑换」「时装」「氪金」。清单里没有的商品会跳过并说明。")
    print()
    result = run_live(task, source.grab, clicker, log=print)
    print()
    print(result.message)
    return 0 if result.status == "done" else 1


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
