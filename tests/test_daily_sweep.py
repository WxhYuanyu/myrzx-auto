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
from src.tasks.locations import LANGREN
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
    assert len(templates) == 122
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
    assert SHOP_SWIPE_MAX == 24

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
