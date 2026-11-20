"""温泉治疗：酒馆先和独眼猎人对话，再在莉安湖 2-11 与温泉对话后战斗。

地区图上看不见时从左边缘划到中间。必须看到 2-5 旁小屋和任务对话圈才点 2-11。
不点小屋、气泡、2-10、2-12、2-5、2-6、扫荡、进入或驯养师。不跑 --live。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LIANHU
from src.tasks.priority_flows import (
    ADVANCE,
    step_enter_tavern,
    step_find_2_11,
    step_leave_tavern,
    step_skip_in_battle,
    step_talk_hunter,
)
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lianhu_region_1080.png"
_FLAG_BOX = (525, 995, 119, 190)
_HOUSE_BOX = (644, 750, 92, 225)
_BUBBLE_BOX = (655, 970, 105, 110)
_FLAG_2_10 = (770, 990, 230, 220)
_FLAG_2_12 = (255, 1005, 230, 215)


def _task(templates, step: str = "find_2_11") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("温泉治疗"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试温泉治疗 2-11")


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def _cover(image, box):
    x, y, w, h = box
    image[y : y + h, x : x + w] = 40
    return image


def _region():
    image = cv2.imread(str(_FIXTURE))
    if image is not None:
        return image
    # 大张莉安湖地区图不在这次上传里。按实机框把小屋、2-11 和对话圈拼上。
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    root = Path(__file__).resolve().parents[1] / "assets" / "templates"
    house = cv2.imread(str(root / "lianhu_wagon_house.png"))
    flag = cv2.imread(str(root / "stage_flag_2_11.png"))
    bubble = cv2.imread(str(root / "quest_bubble_2_11.png"))
    assert house is not None and flag is not None and bubble is not None
    _paste(image, house, _HOUSE_BOX[0], _HOUSE_BOX[1])
    _paste(image, flag, _FLAG_BOX[0], _FLAG_BOX[1])
    _paste(image, bubble, _BUBBLE_BOX[0], _BUBBLE_BOX[1])
    return image


def test_hot_spring_recipe_stays_high_and_has_tavern_then_2_11():
    recipe = get_recipe("温泉治疗")
    assert recipe.location is LIANHU
    assert recipe.tier is CommissionTier.HIGH
    assert recipe.kind is CommissionKind.BATTLE
    assert recipe.stage_flag_template == "stage_flag_2_11"
    assert recipe.stage_label == "2-11"
    assert recipe.npc_template == "npc_hot_spring"
    assert recipe.card_template == "commission_hot_spring"
    assert recipe.log_template == "commission_hot_spring"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "enter_tavern",
        "talk_hunter",
        "skip_story",
        "leave_tavern",
        "explore",
        "find_2_11",
        "talk_on_stage",
        "skip_story",
        "skip_in_battle",
        "battle",
        "skip_story",
        "claim",
    )
    assert "独眼猎人" in recipe.summary
    assert "酒馆" in recipe.summary
    assert "小屋" in recipe.summary
    assert "从左边缘划到中间" in recipe.summary or "按住左边缘划到中间" in recipe.summary
    assert "轻轻划" in recipe.summary
    assert "大划" in recipe.summary
    assert "10 秒" in recipe.summary
    assert "只针对这条" in recipe.summary
    assert "2-10" in recipe.summary
    assert "2-12" in recipe.summary
    assert "驯养师" in recipe.summary
    assert "扫荡" in recipe.summary
    assert "完成" in recipe.summary
    assert "高级" in recipe.summary


def test_aux_and_neighbor_templates_are_not_click_targets(templates):
    by_id = templates_by_id(templates)
    assert by_id["stage_flag_2_11"].is_click_target is True
    assert by_id["lianhu_wagon_house"].is_click_target is False
    assert by_id["stage_flag_2_10"].is_click_target is False
    assert by_id["stage_flag_2_12"].is_click_target is False
    assert by_id["npc_tamer"].is_click_target is False
    assert by_id["quest_bubble_2_11"].is_click_target is False
    assert by_id["tavern_title"].is_click_target is False
    assert by_id["npc_one_eyed_hunter"].is_click_target is True
    assert by_id["npc_hot_spring"].is_click_target is True
    assert by_id["city_tavern"].is_click_target is True


def test_2_11_with_house_and_bubble_is_clicked_not_house_or_bubble(templates):
    image = _region()
    result = step_find_2_11(_task(templates), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "2-11"
    fx, fy, fw, fh = _FLAG_BOX
    assert fx <= result.action.x <= fx + fw
    assert fy <= result.action.y <= fy + fh
    bx, by, bw, bh = _BUBBLE_BOX
    assert not (bx <= result.action.x <= bx + bw and by <= result.action.y <= by + bh)
    hx, hy, hw, hh = _HOUSE_BOX
    house_cx, house_cy = hx + hw // 2, hy + hh // 2
    assert (result.action.x, result.action.y) != (house_cx, house_cy)
    assert result.action.label not in {"扫荡", "2-10", "2-12", "小屋"}
    message = result.action.message or ""
    assert "小屋" in message
    assert "不要点" in message or "不点" in message


def test_2_11_without_bubble_is_not_clicked_and_swipes_edge_to_center(templates):
    image = _cover(_region(), _BUBBLE_BOX)
    result = step_find_2_11(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind == "swipe"
    height, width = image.shape[:2]
    mid_x, mid_y = width // 2, height // 2
    edge_x = max(8, int(width * 0.04))
    assert result.action.x == edge_x
    assert result.action.x2 == mid_x
    assert result.action.y == mid_y
    assert result.action.y2 == mid_y
    assert "边缘" in result.action.label and "中间" in result.action.label
    assert "轻轻" not in result.action.label
    message = result.action.message or ""
    assert "左边缘" in message or "边缘" in message
    assert "中间" in message
    assert "大划" in message
    assert result.action.x != int(width * 0.70)


def test_2_11_without_house_is_not_clicked_even_with_flag_and_bubble(templates):
    image = _cover(_region(), _HOUSE_BOX)
    result = step_find_2_11(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.kind == "swipe"


def test_flag_to_the_right_of_house_is_not_clicked_as_2_11(templates):
    """把 2-11 盖住，只留右边的 2-10，不能把 2-10 当成 2-11 点。"""
    image = _cover(_region(), _FLAG_BOX)
    result = step_find_2_11(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "click"
    if result.action.kind == "swipe":
        return
    assert result.action.label != "2-10"


def test_same_view_after_swipe_stops_when_the_map_does_not_move(templates):
    image = _cover(_region(), _BUBBLE_BOX)
    task = _task(templates)
    first = step_find_2_11(task, image, _clf())
    assert first.action is not None and first.action.kind == "swipe"
    second = step_find_2_11(task, image, _clf())
    assert second.action is not None
    assert second.action.kind == "halt"
    assert "不再移动" in (second.action.message or second.message or "")
    assert "2-11" in (second.action.message or second.message or "")


def test_default_view_without_region_map_does_not_swipe(templates):
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    result = step_find_2_11(_task(templates), image, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind != "swipe"
    assert result.action.kind != "click"
    assert "2-11" in (result.action.message or result.message or "")


def test_already_on_stage_select_advances(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    spring = by_id["npc_hot_spring"].image_bgr
    _paste(image, spring, 0, 1528)
    result = step_find_2_11(_task(templates), image, _clf())
    assert result is ADVANCE


def test_enter_tavern_clicks_the_building_not_a_shop(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    tavern = by_id["city_tavern"].image_bgr
    tx, ty = 200, 800
    _paste(image, tavern, tx, ty)
    shop = by_id.get("city_shop")
    if shop is not None:
        _paste(image, shop.image_bgr, 700, 800)
    result = step_enter_tavern(_task(templates, "enter_tavern"), image, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "酒馆"
    assert tx <= result.action.x < tx + tavern.shape[1]
    assert ty <= result.action.y < ty + tavern.shape[0]
    assert result.action.label not in {"商店", "协会", "探险", "兑换"}
    assert "气泡" in (result.action.message or "")


def test_talk_hunter_clicks_the_face_not_tamer_or_bubble(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    face = by_id["npc_one_eyed_hunter"].image_bgr
    fx, fy = 0, 1288
    _paste(image, face, fx, fy)
    tamer = by_id["npc_tamer"].image_bgr
    _paste(image, tamer, 0, 1548)
    bubble = by_id.get("quest_bubble_map") or by_id.get("quest_bubble")
    bx = fx + face.shape[1] + 8
    by = fy + 8
    if bubble is not None:
        _paste(image, bubble.image_bgr, bx, by)
    result = step_talk_hunter(_task(templates, "talk_hunter"), image, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "独眼猎人"
    assert fx <= result.action.x < fx + face.shape[1]
    assert fy <= result.action.y < fy + face.shape[0]
    assert not (0 <= result.action.x < tamer.shape[1] and 1548 <= result.action.y < 1548 + tamer.shape[0])
    if bubble is not None:
        bw, bh = bubble.image_bgr.shape[1], bubble.image_bgr.shape[0]
        assert not (bx <= result.action.x < bx + bw and by <= result.action.y < by + bh)
    message = result.action.message or ""
    assert "独眼猎人" in message
    assert "驯养师" in message
    assert "气泡" in message


def test_leave_tavern_clicks_leave_then_city_advances(templates):
    by_id = templates_by_id(templates)
    inside = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    title = by_id["tavern_title"].image_bgr
    leave = by_id["tavern_leave"].image_bgr
    _paste(inside, title, 20, 232)
    lx, ly = 8, 1768
    _paste(inside, leave, lx, ly)
    result = step_leave_tavern(_task(templates, "leave_tavern"), inside, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "离开"
    assert lx <= result.action.x < lx + leave.shape[1]
    assert ly <= result.action.y < ly + leave.shape[0]
    assert "兑换" in (result.action.message or "")

    city = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    explore = (by_id.get("city_explore_label") or by_id["city_explore"]).image_bgr
    _paste(city, explore, 40, 1600)
    advanced = step_leave_tavern(_task(templates, "leave_tavern"), city, _clf(Scene.UNKNOWN))
    assert advanced is ADVANCE


def test_skip_in_battle_clicks_skip_when_already_fighting(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    skip = (by_id.get("skip_story_tight") or by_id["skip_story"]).image_bgr
    _paste(image, skip, 740, 40)
    task = _task(templates, "skip_in_battle")
    result = step_skip_in_battle(task, image, _clf(Scene.BATTLE))
    assert result.action is not None
    assert result.action.kind == "click"
    assert "跳过" in (result.action.label or result.action.message or "")
    assert task.step_armed is True


def test_skip_in_battle_waits_during_battle_without_skip(templates):
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    task = _task(templates, "skip_in_battle")
    result = step_skip_in_battle(task, image, _clf(Scene.BATTLE))
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind == "wait"
    assert result.status == "waiting_battle"
    assert task.step_armed is not True


def test_skip_in_battle_advances_on_victory(templates):
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    result = step_skip_in_battle(_task(templates, "skip_in_battle"), image, _clf(Scene.VICTORY))
    assert result is ADVANCE


def test_skip_in_battle_does_not_finish_on_pre_battle_story(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    skip = (by_id.get("skip_story_tight") or by_id["skip_story"]).image_bgr
    _paste(image, skip, 740, 40)
    task = _task(templates, "skip_in_battle")
    result = step_skip_in_battle(task, image, _clf(Scene.STORY_DIALOG))
    assert result.action is not None
    assert result.action.kind == "click"
    assert task.step_armed is not True
