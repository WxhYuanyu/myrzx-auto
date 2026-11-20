"""收集维修材料：4-2 必须在「地下遗迹」左边，且带任务对话圈。对话两次。看不见就往右大划。不点 4-1 / 4-3 / 4-Z / 遗迹 / 气泡。不跑 --live。"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import NAN_SERAM
from src.tasks.priority_flows import ADVANCE, step_find_4_2
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene

# 与用户地区图放大到 1080 宽后的相对位置一致：4-2 在地下遗迹左下方。
_SCALE = 1080 / 493
_RUINS_SRC = (276, 496, 454, 602)
_FLAG_SRC = (198, 610, 254, 678)
_FLAG_DX = int(round((_FLAG_SRC[0] - _RUINS_SRC[0]) * _SCALE))
_FLAG_DY = int(round((_FLAG_SRC[1] - _RUINS_SRC[1]) * _SCALE))


def _task(templates, step: str = "find_4_2") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("收集维修材料"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试收集维修材料 4-2")


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def _region_map(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    if "stage_return" in by_id:
        _paste(image, by_id["stage_return"].image_bgr, 40, 1800)
    return image


def _bubble(by_id):
    return (by_id.get("quest_bubble_map") or by_id["quest_bubble"]).image_bgr


def _ruins(by_id):
    return by_id["nan_seram_underground_ruins"].image_bgr


def _layout(image, by_id, *, ruins=True, flag=True, bubble=True, flag_id="stage_flag_4_2", fx=None, fy=None):
    """按用户地区图上的相对位置摆放：4-2 在地下遗迹左边偏下。"""
    cx, cy = 520, 900
    if ruins:
        _paste(image, _ruins(by_id), cx, cy)
    flag_img = by_id[flag_id].image_bgr
    if fx is None:
        fx = cx + _FLAG_DX
    if fy is None:
        fy = cy + _FLAG_DY
    if flag:
        _paste(image, flag_img, fx, fy)
    bx, by = fx + flag_img.shape[1] + 4, fy + 8
    if bubble:
        _paste(image, _bubble(by_id), bx, by)
    return (cx, cy, fx, fy, bx, by, flag_img)


def test_collect_repair_recipe_talks_twice_and_is_low_tier():
    recipe = get_recipe("收集维修材料")
    assert recipe.location is NAN_SERAM
    assert recipe.tier is CommissionTier.LOW
    assert recipe.kind is CommissionKind.TURN_IN
    assert recipe.stage_flag_template == "stage_flag_4_2"
    assert recipe.stage_label == "4-2"
    assert recipe.npc_template == "npc_repair_worker"
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "explore",
        "find_4_2",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "claim",
    )
    assert recipe.steps.count("talk_on_stage") == 2
    assert recipe.steps.count("skip_story") == 2
    assert "fight_stage" not in recipe.steps
    assert "地下遗迹" in recipe.summary
    assert "4-1" in recipe.summary
    assert "对话两次" in recipe.summary
    assert "大划" in recipe.summary


def test_underground_ruins_and_neighbor_flags_are_not_click_targets(templates):
    by_id = templates_by_id(templates)
    ruins = by_id["nan_seram_underground_ruins"]
    assert ruins.label == "地下遗迹"
    assert ruins.is_click_target is False
    assert ruins.threshold == 0.8
    assert by_id["stage_flag_4_1"].is_click_target is False
    assert by_id["stage_flag_4_3"].is_click_target is False
    assert by_id["stage_flag_4_2"].is_click_target is True


def test_4_2_with_ruins_and_bubble_is_clicked_not_ruins_or_bubble(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    cx, cy, fx, fy, bx, by, flag_img = _layout(image, by_id)
    ruins_img = _ruins(by_id)
    bubble = _bubble(by_id)
    result = step_find_4_2(_task(templates), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "4-2"
    assert fx <= result.action.x < fx + flag_img.shape[1]
    assert fy <= result.action.y < fy + flag_img.shape[0]
    assert not (bx <= result.action.x < bx + bubble.shape[1] and by <= result.action.y < by + bubble.shape[0])
    assert not (cx <= result.action.x < cx + ruins_img.shape[1] and cy <= result.action.y < cy + ruins_img.shape[0])


def test_4_2_without_ruins_is_not_clicked(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, ruins=False)
    result = step_find_4_2(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有地下遗迹却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )


def test_4_2_without_bubble_is_not_clicked(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, bubble=False)
    result = step_find_4_2(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有任务对话圈却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"
    assert result.action is None or result.action.kind != "swipe"


def test_4_1_in_4_2_slot_is_not_clicked(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, flag_id="stage_flag_4_1")
    result = step_find_4_2(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把 4-1 点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )


def test_flag_to_the_right_of_ruins_is_not_clicked_as_4_2(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    ruins_img = _ruins(by_id)
    flag = by_id["stage_flag_4_2"].image_bgr
    bubble = _bubble(by_id)
    cx, cy = 80, 900
    _paste(image, ruins_img, cx, cy)
    fx, fy = cx + ruins_img.shape[1] + 40, cy + 20
    _paste(image, flag, fx, fy)
    _paste(image, bubble, fx + flag.shape[1] + 4, fy + 8)
    result = step_find_4_2(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把遗迹右边的旗点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"


def test_flag_far_below_ruins_is_not_clicked_as_4_2(templates):
    """4-1 在地下遗迹更下方，即使被 4-2 模板认到、旁边还有对话圈，也不能点。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    ruins_img = _ruins(by_id)
    flag = by_id["stage_flag_4_2"].image_bgr
    bubble = _bubble(by_id)
    cx, cy = 520, 900
    _paste(image, ruins_img, cx, cy)
    fx, fy = cx - 60, cy + ruins_img.shape[0] + 80
    _paste(image, flag, fx, fy)
    _paste(image, bubble, fx + flag.shape[1] + 4, fy + 8)
    result = step_find_4_2(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把遗迹下方的旗点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"


def test_missing_ruins_on_region_map_swipes_east_heavily(templates):
    image = _region_map(templates)
    task = _task(templates)
    result = step_find_4_2(task, image, _clf())
    assert result.action is not None
    assert result.action.kind == "swipe"
    # 大划到底：从 0.70 宽划到 0.32 宽，不是从中间轻轻划到边缘。
    assert result.action.x == int(1080 * 0.70)
    assert result.action.x2 == int(1080 * 0.32)
    assert result.action.y == 1920 // 2
    assert "大划" in (result.action.message or result.message or "") or "划到底" in (result.action.message or result.message or "")


def test_right_edge_without_ruins_halts(templates):
    image = _region_map(templates)
    task = _task(templates)
    first = step_find_4_2(task, image, _clf())
    assert first.action is not None and first.action.kind == "swipe"
    second = step_find_4_2(task, image, _clf())
    assert second.action is not None
    assert second.action.kind == "halt"
    text = second.action.message or second.message or ""
    assert "右" in text


def test_stage_page_with_repair_worker_advances_to_talk(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    npc = by_id["npc_repair_worker"].image_bgr
    _paste(image, npc, 40, 1400)
    result = step_find_4_2(_task(templates), image, _clf())
    assert result is ADVANCE
