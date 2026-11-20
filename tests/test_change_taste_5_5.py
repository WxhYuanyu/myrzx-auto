"""换换口味：5-5 必须在「恶骸之狱」右边，且带任务对话圈。不把 5-9 / 5-A5 / 5-A2 当成 5-5。不跑 --live。"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LANGREN
from src.tasks.priority_flows import ADVANCE, step_fight_5_5
from src.tasks.recipes import CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _task(templates, step: str = "fight_5_5") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试换换口味 5-5")


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


def _prison(by_id):
    return by_id["langren_evil_prison"].image_bgr


def test_change_taste_uses_fight_5_5_not_generic_fight_stage():
    recipe = get_recipe("换换口味")
    assert recipe.location is LANGREN
    assert recipe.tier is CommissionTier.MEDIUM
    assert recipe.stage_flag_template == "stage_flag_5_5"
    assert recipe.stage_label == "5-5"
    assert recipe.steps == (
        "check_item",
        "accept_board",
        "leave_association",
        "explore",
        "fight_5_5",
        "talk_on_stage",
        "skip_story",
        "claim",
    )
    assert "fight_stage" not in recipe.steps
    assert "右下角偏左" in recipe.summary
    assert "恶骸之狱" in recipe.summary
    assert "5-9" in recipe.summary
    assert "5-A5" in recipe.summary
    assert "对话圈" in recipe.summary


def test_5_a2_threshold_raised_after_5_a5_false_positive(templates):
    spec = templates_by_id(templates)["stage_flag_5_a2"]
    assert spec.threshold == 0.9
    assert "0.856" in (spec.notes or "")


def test_evil_prison_template_is_not_a_click_target(templates):
    spec = templates_by_id(templates)["langren_evil_prison"]
    assert spec.label == "恶骸之狱"
    assert spec.is_click_target is False
    assert spec.threshold == 0.8
    assert "5-9" in (spec.notes or "")


def test_5_5_without_bubble_does_not_click_and_pans_south(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    prison = _prison(by_id)
    flag = by_id["stage_flag_5_5"].image_bgr
    _paste(image, prison, 40, 1100)
    _paste(image, flag, 40 + prison.shape[1] + 8, 1180)
    result = step_fight_5_5(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向上滑动地图"
    assert result.action.y2 < result.action.y
    assert result.action.label != "5-5"


def test_5_5_with_bubble_but_no_prison_is_not_clicked(templates):
    """实机把右侧的 5-9 以 0.899 认成 5-5。没有恶骸之狱时，即使有对话圈也不能点。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    flag = by_id["stage_flag_5_5"].image_bgr
    bubble = _bubble(by_id)
    x, y = 800, 1200
    _paste(image, flag, x, y)
    _paste(image, bubble, x + flag.shape[1] + 4, y + 20)
    result = step_fight_5_5(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有恶骸之狱却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind in {"swipe", "halt"}


def test_5_5_flag_is_clicked_not_the_bubble_or_prison(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    prison = _prison(by_id)
    flag = by_id["stage_flag_5_5"].image_bgr
    bubble = _bubble(by_id)
    px, py = 40, 1100
    _paste(image, prison, px, py)
    x, y = px + prison.shape[1] + 8, py + 80
    _paste(image, flag, x, y)
    bx, by = x + flag.shape[1] + 4, y + 20
    _paste(image, bubble, bx, by)
    result = step_fight_5_5(_task(templates), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "5-5"
    assert x <= result.action.x < x + flag.shape[1]
    assert y <= result.action.y < y + flag.shape[0]
    assert not (bx <= result.action.x < bx + bubble.shape[1] and by <= result.action.y < by + bubble.shape[0])
    assert not (px <= result.action.x < px + prison.shape[1] and py <= result.action.y < py + prison.shape[0])


def test_flag_far_right_of_prison_is_not_clicked_as_5_5(templates):
    """恶骸之狱在左、候选旗在屏幕另一侧时，不能当成它右边的 5-5。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    prison = _prison(by_id)
    flag = by_id["stage_flag_5_5"].image_bgr
    bubble = _bubble(by_id)
    _paste(image, prison, 10, 1100)
    x, y = 980, 1200
    _paste(image, flag, x, y)
    _paste(image, bubble, x - 40, y + 20)
    result = step_fight_5_5(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把远处的旗点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind in {"swipe", "halt"}


def test_5_a2_flag_is_not_clicked_as_5_5_even_with_bubble(templates):
    """实机把 5-A5 认成 5-A2 后又当成 5-5 点进去。只有 5-A2 旗时，即使旁边有对话圈也不能点。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    flag = by_id["stage_flag_5_a2"].image_bgr
    bubble = _bubble(by_id)
    x, y = 500, 1100
    _paste(image, flag, x, y)
    _paste(image, bubble, x + flag.shape[1] + 4, y + 20)
    result = step_fight_5_5(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把 5-A2 旗点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind in {"swipe", "halt"}


def test_overlapping_5_a2_blocks_a_false_5_5(templates):
    """同一位置两面旗都像，分数又接近时，不能当成 5-5 去点。没有恶骸之狱时更不能点。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    flag_a2 = by_id["stage_flag_5_a2"].image_bgr
    flag_55 = by_id["stage_flag_5_5"].image_bgr
    bubble = _bubble(by_id)
    x, y = 480, 1080
    _paste(image, flag_a2, x, y)
    _paste(image, flag_55, x + 10, y + 10)
    _paste(image, bubble, x + max(flag_a2.shape[1], flag_55.shape[1]) + 8, y + 20)
    result = step_fight_5_5(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有恶骸之狱却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )


def test_5_5_missing_pans_south_then_east_then_stops(templates):
    image = _region_map(templates)
    task = _task(templates)
    first = step_fight_5_5(task, image, _clf())
    assert first.action is not None and first.action.kind == "swipe"
    assert first.action.label == "向上滑动地图"
    assert "右下角偏左" in (first.action.message or "")
    second = step_fight_5_5(task, image, _clf())
    assert second.action is not None and second.action.kind == "swipe"
    assert second.action.label == "向左滑动地图"
    assert second.action.x2 < second.action.x
    third = step_fight_5_5(task, image, _clf())
    assert third.status == "halt_missing"
    assert "右下角" in (third.action.message or "")
    assert "恶骸之狱" in (third.action.message or "")
    assert "5-A5" in (third.action.message or "") or "5-A2" in (third.action.message or "")
    assert "扫荡" in (third.action.message or "")


def test_fight_5_5_advances_when_bat_is_already_visible(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    _paste(image, by_id["npc_strange_bat"].image_bgr, 40, 1400)
    result = step_fight_5_5(_task(templates), image, _clf(Scene.STAGE_MAP))
    assert result is ADVANCE
