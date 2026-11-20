"""浪人岬低级委托「保证商路畅通」的步骤顺序和关键点击。不跑 --live。"""

from __future__ import annotations

import numpy as np
import pytest

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LANGREN, NAN_SERAM
from src.tasks.priority_flows import (
    step_claim,
    step_enter_shop,
    step_fight_5_a2,
    step_talk_metaya,
)
from src.tasks.recipes import CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _recipe():
    return get_recipe("保证商路畅通", location="浪人岬")


def _task(templates, step: str) -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=_recipe())
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.UNKNOWN) -> Classification:
    return Classification(scene=scene, reason="测试保证商路畅通")


def _paste(canvas: np.ndarray, image: np.ndarray, x: int, y: int) -> None:
    height, width = image.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]
    x = min(max(0, x), max(0, canvas_w - width))
    y = min(max(0, y), max(0, canvas_h - height))
    canvas[y : y + height, x : x + width] = image


def test_road_safe_langren_recipe_order_and_stays_low():
    recipe = _recipe()
    assert recipe.quest_id == "road_safe_langren"
    assert recipe.flow == "langren_road_safe"
    assert recipe.tier is CommissionTier.LOW
    assert recipe.location is LANGREN
    assert recipe.stage_label == "5-A2"
    assert recipe.stage_node == "basic"
    assert recipe.npc_template == "npc_metaya"
    assert recipe.card_template == "commission_road_safe_langren"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "enter_shop",
        "talk_metaya",
        "skip_story",
        "leave_shop",
        "explore",
        "fight_5_a2",
        "enter_5_a2_basic",
        "battle",
        "leave_stage",
        "claim",
    )
    # 先商店对话，再去 5-A2；一起领，不在中途点「完成」。
    assert recipe.steps.index("enter_shop") < recipe.steps.index("talk_metaya")
    assert recipe.steps.index("talk_metaya") < recipe.steps.index("skip_story")
    assert recipe.steps.index("leave_shop") < recipe.steps.index("explore")
    assert recipe.steps.index("explore") < recipe.steps.index("fight_5_a2")
    assert recipe.steps.index("fight_5_a2") < recipe.steps.index("enter_5_a2_basic")
    assert recipe.steps[-1] == "claim"
    # 南赛拉姆那条是另一条已写好的低级流程，不能被浪人岬覆盖。
    other = get_recipe("保证商路畅通", location="南赛拉姆")
    assert other.location is NAN_SERAM
    assert other.quest_id == "road_safe_nan_seram"
    assert other.flow == "nan_seram_road_safe"
    assert other.stage_label == "4-21"


def test_claim_does_not_click_finish(templates):
    task = _task(templates, "claim")
    image = np.zeros((1920, 1080, 3), dtype=np.uint8)
    result = step_claim(task, image, _clf())
    assert result.status == "done"
    assert result.action is not None
    assert result.action.kind == "halt"
    message = result.action.message or result.message or ""
    assert "先不点「完成」" in message
    assert "完成" in message
    assert result.action.label != "完成"


def test_fight_5_a2_light_swipes_finger_left_when_flag_missing(templates):
    by_id = templates_by_id(templates)
    assert "stage_flag_5_a2" in by_id
    assert "stage_return" in by_id
    # 1080×1920 地区图：有返回箭头，没有 5-A2 旗帜。
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    _paste(image, by_id["stage_return"].image_bgr, 40, 40)
    task = _task(templates, "fight_5_a2")
    result = step_fight_5_a2(task, image, _clf(Scene.STAGE_MAP))
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向左轻轻滑动地图"
    # 轻轻划：从屏幕中间到左边缘（手指往左，内容往右）。
    assert result.action.x == 1080 // 2
    assert result.action.y == result.action.y2 == 1920 // 2
    assert result.action.x2 == max(8, int(1080 * 0.04))
    assert result.action.x2 < result.action.x
    message = result.action.message or ""
    assert "5-A2" in message
    assert "扫荡" in message
    assert "手指往左" in message
    # 不要用普通大划的起点（约 0.70 宽）。
    assert result.action.x != int(1080 * 0.70)


def test_fight_5_a2_stops_when_the_map_stops_moving(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    _paste(image, by_id["stage_return"].image_bgr, 40, 40)
    task = _task(templates, "fight_5_a2")
    first = step_fight_5_a2(task, image, _clf(Scene.STAGE_MAP))
    assert first.action is not None and first.action.kind == "swipe"
    # 同一张画面再走一步：地图不再移动，应该安全停下并说明。
    second = step_fight_5_a2(task, image, _clf(Scene.STAGE_MAP))
    assert second.status == "halt_missing"
    assert second.action is not None
    assert second.action.kind == "halt"
    message = second.action.message or second.message or ""
    assert "5-A2" in message
    assert "不再移动" in message or "安全停下" in message
    assert "扫荡" in message


def test_talk_metaya_clicks_the_face_not_a_bubble(templates):
    by_id = templates_by_id(templates)
    assert "npc_metaya" in by_id
    face = by_id["npc_metaya"].image_bgr
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    face_x, face_y = 40, 1500
    _paste(image, face, face_x, face_y)
    # 在头像右侧贴一个对话圈，点击必须落在脸上，不能落在气泡上。
    bubble = by_id.get("quest_bubble_map") or by_id.get("quest_bubble")
    bubble_x = face_x + face.shape[1] + 8
    bubble_y = face_y + 20
    if bubble is not None:
        _paste(image, bubble.image_bgr, bubble_x, bubble_y)
    task = _task(templates, "talk_metaya")
    result = step_talk_metaya(task, image, _clf())
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "梅塔娅"
    fx, fy = result.action.x, result.action.y
    assert face_x <= fx < face_x + face.shape[1]
    assert face_y <= fy < face_y + face.shape[0]
    if bubble is not None:
        bx, by = bubble_x, bubble_y
        bw, bh = bubble.image_bgr.shape[1], bubble.image_bgr.shape[0]
        assert not (bx <= fx < bx + bw and by <= fy < by + bh)
    message = result.action.message or ""
    assert "梅塔娅" in message
    assert "气泡" in message
    assert "购买" in message


def test_enter_shop_clicks_city_shop_not_the_bag(templates):
    by_id = templates_by_id(templates)
    assert "city_shop" in by_id
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    shop = by_id["city_shop"].image_bgr
    shop_x, shop_y = 400, 700
    _paste(image, shop, shop_x, shop_y)
    bag = by_id.get("ui_bag_icon")
    if bag is not None:
        _paste(image, bag.image_bgr, 900, 40)
    task = _task(templates, "enter_shop")
    result = step_enter_shop(task, image, _clf())
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "商店"
    assert shop_x <= result.action.x < shop_x + shop.shape[1]
    assert shop_y <= result.action.y < shop_y + shop.shape[0]
    if bag is not None:
        assert result.action.label != "背包"
        assert result.action.y > 200
    message = result.action.message or ""
    assert "商店" in message
    assert "背包" in message
