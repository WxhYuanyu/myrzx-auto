"""高 / 中 / 低扫城，以及「换换口味」接取前查背包里的「可疑的果汁」。"""

from __future__ import annotations

import numpy as np
import pytest

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.daily_sweep import (
    SweepState,
    recipes_in_sweep_order,
    sweep_plan_text,
)
from src.tasks.locations import LANGREN, LIANHU, LILITOS
from src.tasks.recipes import CommissionTier, get_recipe
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _paste(by_id, template_ids: tuple[str, ...], *, height: int = 800, width: int = 1400):
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x = 20
    y = 20
    for template_id in template_ids:
        image = by_id[template_id].image_bgr
        canvas[y : y + image.shape[0], x : x + image.shape[1]] = image
        x += image.shape[1] + 24
    return canvas


def test_manifest_keeps_shop_bag_and_new_quest_templates(templates):
    by_id = templates_by_id(templates)
    assert len(templates) == 127
    for template_id in (
        "city_explore_label",
        "commission_change_taste",
        "item_suspicious_juice",
        "npc_strange_bat",
        "quest_log_change_taste",
        "stage_3_23_deep",
        "stage_flag_3_20",
        "stage_flag_3_23",
        "stage_flag_5_5",
        "ui_bag_back",
        "ui_bag_icon",
        "ui_bag_tab_items",
        "ui_bag_title",
        "city_shop",
        "shop_buy",
        "shop_item_juice",
        "shop_item_magic_iron",
        "shop_name_magic_iron",
        "shop_item_jade_dream",
        "shop_name_jade_dream",
    ):
        assert template_id in by_id
    assert by_id["city_shop"].scales == (0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1)
    for template_id, label in (
        ("shop_item_magic_iron", "魔铁矿"),
        ("shop_name_magic_iron", "魔铁矿"),
        ("shop_item_jade_dream", "翡翠之梦"),
        ("shop_name_jade_dream", "翡翠之梦"),
    ):
        spec = by_id[template_id]
        assert spec.label == label
        assert spec.role == "status"
        assert spec.scene is None
        assert spec.is_click_target is False
    # 清单里这两张标成通用 CITY。它们是 click_only，不参与页面判断。
    assert by_id["city_explore_label"].scene is None
    assert by_id["ui_bag_icon"].scene is None
    assert by_id["ui_bag_title"].scene is Scene.BAG


def test_shop_buy_targets_and_one_row_swipe():
    from src.tasks.shop_buy import SHOP_ITEMS, SHOP_SWIPE_MAX, ShopBuyTask
    from src.vision.classify import Classification

    task = ShopBuyTask()
    assert task.results == {
        "juice": "pending",
        "jade_dream": "pending",
        "magic_iron": "pending",
    }
    by_item = {item.item_id: item for item in SHOP_ITEMS}
    assert by_item["juice"].name == "可疑的果汁"
    assert by_item["juice"].confirm_id == "shop_confirm_juice"
    assert by_item["jade_dream"].name == "翡翠之梦"
    assert by_item["jade_dream"].name_id == "shop_name_jade_dream"
    assert by_item["jade_dream"].confirm_id == ""
    assert by_item["magic_iron"].name == "魔铁矿"
    assert by_item["magic_iron"].name_id == "shop_name_magic_iron"
    assert by_item["magic_iron"].confirm_id == ""
    assert SHOP_SWIPE_MAX == 48

    task._require = lambda image, template_id: None
    image = np.zeros((1920, 1080, 3), dtype=np.uint8)
    result = task._plan_gold_list(
        image,
        Classification(scene=Scene.UNKNOWN, reason="测试金币清单"),
    )
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.y == int(1920 * 0.70)
    assert result.action.y2 == int(1920 * 0.70) - 160
    assert "扫荡" not in (result.action.label + result.action.message)
    assert "购买全部" not in result.action.message


def test_sweep_visits_high_then_medium_then_low_by_map_number():
    high = [recipe.name for recipe in recipes_in_sweep_order(CommissionTier.HIGH)]
    assert high[:5] == ["喳喳布林入侵", "处理毒桶", "温泉治疗", "讨伐食人花", "奇怪的魔物"]
    assert high.index("奇怪的魔物") < high.index("阻碍道路的家伙")
    medium = [recipe.name for recipe in recipes_in_sweep_order(CommissionTier.MEDIUM)]
    assert medium == ["换换口味", "冒险小队寻求支援", "制作药物"]
    low = [
        (recipe.location.name, recipe.name)
        for recipe in recipes_in_sweep_order(CommissionTier.LOW)
    ]
    assert low == [
        ("南赛拉姆", "保护维修工"),
        ("南赛拉姆", "保证商路畅通"),
        ("浪人岬", "保证商路畅通"),
    ]
    text = sweep_plan_text()
    assert text.index("【高级】") < text.index("【中级】") < text.index("【低级】")
    assert "换换口味" in text
    assert "奇怪的魔物" in text
    with pytest.raises(KeyError, match="不止一条"):
        get_recipe("保证商路畅通")
    assert get_recipe("保证商路畅通", location="浪人岬").stage_label == "5-A2"
    assert get_recipe("仇恨令我成长").name == "仇恨会令我成长"


def test_change_taste_checks_the_bag_before_accept(templates):
    recipe = get_recipe("换换口味")
    assert recipe.steps[0] == "check_item"
    assert recipe.kind.value == "turn_in"
    assert recipe.tier is CommissionTier.MEDIUM
    assert recipe.location is LANGREN
    assert recipe.required_item_name == "可疑的果汁"
    assert recipe.required_item_template == "item_suspicious_juice"
    assert recipe.npc_template == "npc_strange_bat"
    assert recipe.stage_flag_template == "stage_flag_5_5"
    assert "接收前看不到所需物品" in recipe.summary

    by_id = templates_by_id(templates)
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    # 委托列表上导航会让路，这时才打开背包查果汁。
    opened = task.plan(_paste(by_id, ("commission_center_title", "ui_bag_icon"), height=700, width=1200))
    assert opened.action is not None
    assert opened.action.kind == "click"
    assert opened.action.label == "背包"
    assert "可疑的果汁" in (opened.action.message or "")
    assert opened.action.label != "任务卷轴"

    bag = _paste(
        by_id,
        ("ui_bag_title", "ui_bag_tab_items", "ui_bag_back", "item_suspicious_juice"),
    )
    tab = task.plan(bag)
    assert tab.action is not None
    assert tab.action.label == "道具"
    found = task.plan(bag)
    assert task.item_ready is True
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "返回"
    assert "不要点这件物品" in (found.action.message or "")


def test_missing_juice_halts_one_quest_and_skips_during_a_sweep(templates):
    by_id = templates_by_id(templates)
    marker = by_id["stage_map_sweet_cave"].image_bgr
    stage = np.zeros((marker.shape[0] + 40, marker.shape[1] + 40, 3), dtype=np.uint8)
    stage[20 : 20 + marker.shape[0], 20 : 20 + marker.shape[1]] = marker

    single = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    single.phase = Phase.GO_STAGE
    single.item_ready = False
    halted = single.plan(stage)
    assert halted.status == "halt_missing"
    assert halted.action is not None
    assert halted.action.kind == "halt"
    assert halted.action.label == "没有所需物品"
    assert "不接取「换换口味」" in halted.message
    assert "不会占用每日次数" in halted.message

    sweep_task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    sweep_task.phase = Phase.GO_STAGE
    sweep_task.item_ready = False
    sweep_task.auto_sweep = True
    sweep_task.sweep = SweepState.start()
    sweep_task.sweep.tier = CommissionTier.MEDIUM
    sweep_task.sweep.place_id = LANGREN.id
    sweep_task.recipe = sweep_task.sweep.travel_recipe()
    skipped = sweep_task.plan(stage)
    assert skipped.status == "continue"
    assert skipped.action is not None
    assert skipped.action.kind == "wait"
    assert "不接取「换换口味」" in skipped.message
    assert "不占用每日次数" in skipped.message
    assert sweep_task.sweep.completed == 0
    assert "change_taste" in sweep_task.sweep.finished_ids
    assert sweep_task.recipe.name == "冒险小队寻求支援"


def test_missing_card_leaves_for_next_region_during_sweep(templates):
    """扫城时列表里没有当前这条，关列表去下一站；单独 --quest 仍停止。"""
    by_id = templates_by_id(templates)
    board = _paste(by_id, ("commission_center_title",), height=800, width=1400)

    single = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    halted = single.plan(board)
    assert halted.status == "halt_missing"
    assert halted.action is not None
    assert halted.action.kind == "halt"
    assert "没有找到「喳喳布林入侵」" in halted.message
    assert "不会改点其他委托" in halted.message

    sweep_task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    sweep_task.auto_sweep = True
    sweep_task.sweep = SweepState.start()
    assert sweep_task.sweep.place_id == LILITOS.id
    closed = sweep_task.plan(board)
    assert closed.status == "continue"
    assert closed.action is not None
    assert closed.action.kind == "click"
    assert closed.action.label == "返回"
    assert "换下一站" in (closed.action.message or "")
    assert sweep_task.sweep_move_next is True
    assert sweep_task.sweep.completed == 0
    assert "zhazha_bulin" in sweep_task.sweep.finished_ids

    # 列表关掉后，在协会/城里才会换下一张图。空白页足够触发这一步。
    advanced = sweep_task.plan(np.zeros((400, 400, 3), dtype=np.uint8))
    assert sweep_task.sweep.place_id == LIANHU.id
    assert sweep_task.recipe.name == "处理毒桶"
    assert sweep_task.phase is Phase.ACCEPT
    assert advanced.status in {"continue", "halt_missing"}


def test_sweep_skips_missing_crops_and_picks_other_card_here(templates):
    """莉安湖扫城：温泉治疗还没有标题裁切，应跳过并点本城已有裁切的「讨伐食人花」。"""
    by_id = templates_by_id(templates)
    board = _paste(
        by_id,
        ("commission_center_title", "commission_man_eater"),
        height=800,
        width=1400,
    )
    sweep_task = DailyCommissionTask(specs=templates, recipe=get_recipe("处理毒桶"))
    sweep_task.auto_sweep = True
    sweep_task.sweep = SweepState.start()
    sweep_task.sweep.place_id = LIANHU.id
    sweep_task.recipe = sweep_task.sweep.travel_recipe()
    picked = sweep_task.plan(board)
    assert picked.status == "continue"
    assert picked.action is not None
    assert picked.action.kind == "click"
    assert "讨伐食人花" in (picked.action.message or picked.message or "")
    assert picked.action.label != "返回"
    assert "hot_spring" in sweep_task.sweep.finished_ids
    assert sweep_task.sweep.completed == 0
    assert sweep_task.recipe.name == "讨伐食人花"


def test_sweep_leaves_when_only_uncropped_quests_remain(templates):
    """本城只剩下缺裁切的委托时，关列表去下一站，单独 --quest 仍停止。"""
    by_id = templates_by_id(templates)
    board = _paste(by_id, ("commission_center_title",), height=800, width=1400)

    single = DailyCommissionTask(specs=templates, recipe=get_recipe("温泉治疗"))
    halted = single.plan(board)
    assert halted.status == "halt_missing"
    assert "裁切" in halted.message

    sweep_task = DailyCommissionTask(specs=templates, recipe=get_recipe("处理毒桶"))
    sweep_task.auto_sweep = True
    sweep_task.sweep = SweepState.start()
    sweep_task.sweep.place_id = LIANHU.id
    # 本城能认的另外两条先当作今天没有，只剩下缺裁切的「温泉治疗」。
    sweep_task.sweep.skip(get_recipe("处理毒桶"))
    sweep_task.sweep.skip(get_recipe("讨伐食人花"))
    sweep_task.recipe = get_recipe("温泉治疗")
    closed = sweep_task.plan(board)
    assert closed.status == "continue"
    assert closed.action is not None
    assert closed.action.kind == "click"
    assert closed.action.label == "返回"
    assert "换下一站" in (closed.action.message or "")
    assert "hot_spring" in sweep_task.sweep.finished_ids
    assert sweep_task.sweep.completed == 0
    assert sweep_task.sweep_move_next is True


def test_sweep_leaves_association_after_missing_card(templates):
    """关列表后若还在协会里，要点「离开」去下一站，不能再把「委托」点开。"""
    by_id = templates_by_id(templates)
    board = _paste(by_id, ("commission_center_title",), height=800, width=1400)
    room = _paste(
        by_id,
        ("association_commission", "association_leave"),
        height=800,
        width=1400,
    )
    sweep_task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    sweep_task.auto_sweep = True
    sweep_task.sweep = SweepState.start()
    closed = sweep_task.plan(board)
    assert closed.action is not None
    assert closed.action.label == "返回"
    assert sweep_task.sweep_move_next is True

    left = sweep_task.plan(room)
    assert left.status == "continue"
    assert left.action is not None
    assert left.action.kind == "click"
    assert left.action.label == "离开"
    assert "委托" not in (left.action.label or "")
    assert "再去" in (left.action.message or "")
    assert sweep_task.sweep.place_id == LIANHU.id
    assert sweep_task.recipe.name == "处理毒桶"
    assert sweep_task.phase is Phase.ACCEPT


def test_mid_battle_unknown_keeps_waiting_for_victory(templates):
    """开场「战斗即将开始」消失后，未识别帧要继续等胜利，不能去找大地图。

    实机 MuMu 还没复核这一段。
    """
    import time

    from src.tasks import navigation
    from src.vision.classify import classify_scene

    recipe = get_recipe("“热情”的冒险者")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.phase = Phase.IN_BATTLE
    task.saw_continent = True
    task.battle_started_at = time.monotonic()

    blank = np.zeros((1920, 1080, 3), dtype=np.uint8)
    clf = classify_scene(blank, templates)
    assert clf.scene is Scene.UNKNOWN
    assert navigation.step(task, blank, clf) is None

    result = task.plan(blank)
    assert result.status == "waiting_battle"
    assert result.action is not None
    assert result.action.kind == "wait"
    assert "等待大地图" not in (result.message or "")
    assert "大地图" not in (result.message or "")
    assert "阿格莱恩" not in (result.message or "")
    assert "战斗胜利" in (result.message or "")
    assert "扫荡" in (result.message or "")
    assert result.action.label != "扫荡"
    assert result.action.label != "完成"


def test_flow_recipe_mid_battle_unknown_also_waits(templates):
    """有分步流程的委托（如「处理毒桶」）在战斗中认不出画面时，同样继续等胜利。

    实机 MuMu 还没复核这一段。
    """
    import time

    from src.tasks import navigation
    from src.vision.classify import classify_scene

    recipe = get_recipe("处理毒桶")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.phase = Phase.IN_BATTLE
    task.saw_continent = True
    task.battle_started_at = time.monotonic()
    if recipe.steps and "battle" in recipe.steps:
        task.step_index = recipe.steps.index("battle")

    blank = np.zeros((1920, 1080, 3), dtype=np.uint8)
    clf = classify_scene(blank, templates)
    assert clf.scene is Scene.UNKNOWN
    assert navigation.step(task, blank, clf) is None

    result = task.plan(blank)
    assert result.status == "waiting_battle"
    assert result.action is not None
    assert result.action.kind == "wait"
    assert "等待大地图" not in (result.message or "")
    assert "大地图" not in (result.message or "")
    assert "阿格莱恩" not in (result.message or "")
    assert "战斗胜利" in (result.message or "")
    assert result.action.label != "扫荡"
    assert result.action.label != "完成"


def test_flow_battle_returns_to_stage_and_keeps_going(templates):
    """选关页重新出现「离开」时，这一场已经结束，要接着离开，不能一直等下一场胜利。"""
    by_id = templates_by_id(templates)
    stage = np.zeros((900, 800, 3), dtype=np.uint8)
    title = by_id["stage_1_3_title"].image_bgr
    leave = by_id["stage_leave"].image_bgr
    stage[20 : 20 + title.shape[0], 20 : 20 + title.shape[1]] = title
    # 左下，避开中间偏下的「扫荡」。
    stage[700 : 700 + leave.shape[0], 16 : 16 + leave.shape[1]] = leave
    recipe = get_recipe("奇怪的魔物")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.phase = Phase.IN_BATTLE
    task.step_index = recipe.steps.index("battle")
    result = task.plan(stage)
    assert result.scene is Scene.STAGE_1_3
    assert result.action is not None
    assert result.status == "continue"
    assert result.action.kind == "click"
    assert result.action.label == "离开"
    assert "阿格莱恩" not in (result.message or "")
    assert "等待大地图" not in (result.message or "")
    assert "战斗胜利" not in (result.message or "")
    assert result.action.label != "扫荡"
    assert result.action.label != "完成"
