"""地震防范改造：4-7 必须在「结晶矿洞」上方，且带任务对话圈。对话两次。不滑动，不点 4-6 / 矿洞 / 气泡。不跑 --live。"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import NAN_SERAM
from src.tasks.priority_flows import ADVANCE, step_find_4_7
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _task(templates, step: str = "find_4_7") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("地震防范改造"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试地震防范改造 4-7")


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


def _cave(by_id):
    return by_id["nan_seram_crystal_cave"].image_bgr


def _layout(image, by_id, *, cave=True, flag=True, bubble=True, use_46=False):
    """按用户地标图上的相对位置摆放：4-7 在矿洞上方偏左。"""
    cx, cy = 80, 1100
    if cave:
        _paste(image, _cave(by_id), cx, cy)
    flag_img = by_id["stage_flag_4_6" if use_46 else "stage_flag_4_7"].image_bgr
    # 与实机裁切一致：旗帜在矿洞上方，水平落在矿洞范围内。
    fx, fy = cx + 66, cy - 124
    if flag:
        _paste(image, flag_img, fx, fy)
    bx, by = fx + flag_img.shape[1] + 4, fy + 8
    if bubble:
        _paste(image, _bubble(by_id), bx, by)
    return (cx, cy, fx, fy, bx, by, flag_img)


def test_quake_proof_recipe_talks_twice_and_is_low_tier():
    recipe = get_recipe("地震防范改造")
    assert recipe.location is NAN_SERAM
    assert recipe.tier is CommissionTier.LOW
    assert recipe.kind is CommissionKind.TURN_IN
    assert recipe.stage_flag_template == "stage_flag_4_7"
    assert recipe.stage_label == "4-7"
    assert recipe.npc_template == "npc_dama"
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "explore",
        "find_4_7",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "claim",
    )
    assert recipe.steps.count("talk_on_stage") == 2
    assert recipe.steps.count("skip_story") == 2
    assert "fight_stage" not in recipe.steps
    assert "结晶矿洞" in recipe.summary
    assert "4-6" in recipe.summary
    assert "对话两次" in recipe.summary
    assert "无需滑动" in recipe.summary


def test_crystal_cave_and_4_6_are_not_click_targets(templates):
    by_id = templates_by_id(templates)
    cave = by_id["nan_seram_crystal_cave"]
    assert cave.label == "结晶矿洞"
    assert cave.is_click_target is False
    assert cave.threshold == 0.8
    flag46 = by_id["stage_flag_4_6"]
    assert flag46.label == "4-6"
    assert flag46.is_click_target is False


def test_4_7_with_cave_and_bubble_is_clicked_not_cave_or_bubble(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    cx, cy, fx, fy, bx, by, flag_img = _layout(image, by_id)
    cave_img = _cave(by_id)
    bubble = _bubble(by_id)
    result = step_find_4_7(_task(templates), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "4-7"
    assert fx <= result.action.x < fx + flag_img.shape[1]
    assert fy <= result.action.y < fy + flag_img.shape[0]
    assert not (bx <= result.action.x < bx + bubble.shape[1] and by <= result.action.y < by + bubble.shape[0])
    assert not (cx <= result.action.x < cx + cave_img.shape[1] and cy <= result.action.y < cy + cave_img.shape[0])


def test_4_7_without_cave_is_not_clicked(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, cave=False)
    result = step_find_4_7(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有结晶矿洞却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"
    assert result.action is None or result.action.kind != "swipe"


def test_4_7_without_bubble_is_not_clicked(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, bubble=False)
    result = step_find_4_7(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"没有任务对话圈却点了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"
    assert result.action is None or result.action.kind != "swipe"


def test_4_6_above_cave_is_not_clicked_as_4_7(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    _layout(image, by_id, use_46=True)
    result = step_find_4_7(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把 4-6 点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"


def test_flag_to_the_right_of_cave_is_not_clicked_as_4_7(templates):
    """4-6 在结晶矿洞右边，即使被 4-7 模板认到、旁边还有对话圈，也不能点。"""
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    cave_img = _cave(by_id)
    flag = by_id["stage_flag_4_7"].image_bgr
    bubble = _bubble(by_id)
    cx, cy = 80, 1100
    _paste(image, cave_img, cx, cy)
    fx, fy = cx + cave_img.shape[1] + 80, cy - 124
    _paste(image, flag, fx, fy)
    _paste(image, bubble, fx + flag.shape[1] + 4, fy + 8)
    result = step_find_4_7(_task(templates), image, _clf())
    if result.action is not None and result.action.kind == "click":
        raise AssertionError(
            f"把矿洞右边的旗点成了「{result.action.label}」@({result.action.x}, {result.action.y})"
        )
    assert result.action is None or result.action.kind == "halt"


def test_missing_4_7_halts_without_swiping(templates):
    image = _region_map(templates)
    result = step_find_4_7(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind == "halt"
    assert "无需滑动" in (result.action.message or result.message or "")
    assert result.action.kind != "swipe"


def test_stage_page_with_dama_advances_to_talk(templates):
    by_id = templates_by_id(templates)
    image = _region_map(templates)
    npc = by_id["npc_dama"].image_bgr
    _paste(image, npc, 40, 1400)
    result = step_find_4_7(_task(templates), image, _clf())
    assert result is ADVANCE
