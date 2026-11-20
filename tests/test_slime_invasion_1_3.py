"""史莱姆入侵：1-3 必须在「甜蜜幻窟」上面偏左，且带任务对话圈。对话两次后战斗。不滑动。不点 1-2 / 1-4 / 帐篷 / 气泡。不跑 --live。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LILITOS
from src.tasks.priority_flows import ADVANCE, step_find_1_3, step_skip_story
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lilitos_region_1080.png"
# 与用户地区图放大到 1080 宽后的匹配位置一致。
_FLAG_BOX = (750, 956, 154, 120)
_CAVE_BOX = (728, 1068, 352, 220)


def _task(templates, step: str = "find_1_3") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("史莱姆入侵"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试史莱姆入侵 1-3")


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def _bubble(by_id):
    return (by_id.get("quest_bubble_map") or by_id["quest_bubble"]).image_bgr


def _region(templates):
    image = cv2.imread(str(_FIXTURE))
    if image is not None:
        return image
    # 大张莉莉托斯地区图不在这次上传里。按实机框把甜蜜幻窟和 1-3 拼上。
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    by_id = templates_by_id(templates)
    # 甜蜜幻窟是旧的小裁切，在 1080 宽的地区图上大约按 2.2 倍出现，框就是 _CAVE_BOX。
    cave = by_id["stage_map_sweet_cave"].image_bgr
    cave = cv2.resize(cave, (_CAVE_BOX[2], _CAVE_BOX[3]), interpolation=cv2.INTER_CUBIC)
    _paste(image, cave, _CAVE_BOX[0], _CAVE_BOX[1])
    _paste(image, by_id["stage_flag_1_3"].image_bgr, _FLAG_BOX[0], _FLAG_BOX[1])
    return image


def _with_bubble(image, by_id, *, at="1-3"):
    bubble = _bubble(by_id)
    if at == "1-3":
        fx, fy, fw, fh = _FLAG_BOX
        _paste(image, bubble, fx + fw + 4, fy + 8)
    elif at == "1-4":
        # 1-4 裁切在 (915, 820)，气泡放在旗帜右侧。
        _paste(image, bubble, 1078 - bubble.shape[1] - 2, 830)
    return image


def test_slime_invasion_recipe_talks_twice_then_battles_and_is_low_tier():
    recipe = get_recipe("史莱姆入侵")
    assert recipe.location is LILITOS
    assert recipe.tier is CommissionTier.LOW
    assert recipe.kind is CommissionKind.BATTLE
    assert recipe.stage_flag_template == "stage_flag_1_3"
    assert recipe.stage_label == "1-3"
    assert recipe.npc_template == "npc_slime_youth"
    assert recipe.card_template == "commission_slime_invasion"
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "explore",
        "find_1_3",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "battle",
        "claim",
    )
    assert recipe.steps.count("talk_on_stage") == 2
    assert recipe.steps.count("skip_story") == 2
    assert recipe.steps[-2] == "battle"
    assert recipe.steps[-1] == "claim"
    assert "甜蜜幻窟" in recipe.summary
    assert "无需滑动" in recipe.summary
    assert "12 秒" in recipe.summary
    assert "只针对这条" in recipe.summary
    assert "对话两次" in recipe.summary
    assert "1-2" in recipe.summary
    assert "1-4" in recipe.summary
    assert "扫荡" in recipe.summary
    assert "完成" in recipe.summary


def test_zhazha_bulin_still_uses_the_same_1_3_flag_and_is_unchanged():
    recipe = get_recipe("喳喳布林入侵")
    assert recipe.stage_flag_template == "stage_flag_1_3"
    assert recipe.npc_template == "npc_child"
    assert recipe.location is LILITOS
    assert recipe.flow == ""
    assert "find_1_3" not in recipe.steps


def test_sweet_cave_and_neighbor_flags_are_not_click_targets(templates):
    by_id = templates_by_id(templates)
    cave = by_id["stage_map_sweet_cave"]
    assert cave.label == "甜蜜幻窟"
    assert cave.is_click_target is False
    assert by_id["stage_flag_1_2"].is_click_target is False
    assert by_id["stage_flag_1_4"].is_click_target is False
    assert by_id["stage_flag_1_3"].is_click_target is True


def test_1_3_with_cave_and_bubble_is_clicked_not_cave_or_bubble(templates):
    by_id = templates_by_id(templates)
    image = _with_bubble(_region(templates), by_id, at="1-3")
    result = step_find_1_3(_task(templates), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "1-3"
    fx, fy, fw, fh = _FLAG_BOX
    assert fx <= result.action.x <= fx + fw
    assert fy <= result.action.y <= fy + fh
    bubble = _bubble(by_id)
    bx, by = fx + fw + 4, fy + 8
    assert not (bx <= result.action.x <= bx + bubble.shape[1] and by <= result.action.y <= by + bubble.shape[0])
    cx, cy, cw, ch = _CAVE_BOX
    # 旗帜和帐篷略有重叠，但点击必须落在旗帜框内，不能点到帐篷主体中心。
    cave_cx, cave_cy = cx + cw // 2, cy + ch // 2
    assert (result.action.x, result.action.y) != (cave_cx, cave_cy)
    assert result.action.label != "扫荡"
    assert "不要点「扫荡」" in result.action.message or "不点" in result.action.message
    assert "甜蜜幻窟" in result.action.message


def test_1_3_without_bubble_is_not_clicked(templates):
    image = _region(templates)
    result = step_find_1_3(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.kind != "swipe"
    assert "甜蜜幻窟" in (result.message or result.action.message or "")
    assert "滑动" in (result.action.message or result.message or "")


def test_1_3_without_sweet_cave_is_not_clicked_even_with_flag_and_bubble(templates):
    by_id = templates_by_id(templates)
    image = _with_bubble(_region(templates), by_id, at="1-3")
    cx, cy, cw, ch = _CAVE_BOX
    image[cy : cy + ch, cx : cx + cw] = 40
    result = step_find_1_3(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.kind != "swipe"


def test_flag_to_the_right_of_cave_with_bubble_is_not_clicked_as_1_3(templates):
    """把 1-3 盖住，只留右边的 1-4 和对话圈，不能把 1-4 当成 1-3 点。"""
    by_id = templates_by_id(templates)
    image = _region(templates)
    fx, fy, fw, fh = _FLAG_BOX
    image[fy : fy + fh, fx : fx + fw] = 40
    image = _with_bubble(image, by_id, at="1-4")
    result = step_find_1_3(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.kind != "swipe"


def test_default_view_without_valid_1_3_does_not_swipe(templates):
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    if "stage_return" in templates_by_id(templates):
        back = templates_by_id(templates)["stage_return"].image_bgr
        _paste(image, back, 40, 1800)
    result = step_find_1_3(_task(templates), image, _clf())
    assert result.action is not None
    assert result.action.kind != "swipe"
    assert result.action.kind != "click"
    assert "滑动" in (result.action.message or result.message or "")


def test_already_on_stage_select_advances(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    enter = (by_id.get("stage_enter_gold") or by_id["stage_enter"]).image_bgr
    _paste(image, enter, 700, 1500)
    result = step_find_1_3(_task(templates), image, _clf())
    assert result is ADVANCE


def test_skip_story_advances_when_battle_already_started(templates):
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    task = _task(templates)
    task.step_index = 7
    assert task.recipe.steps[task.step_index] == "skip_story"
    assert task.recipe.steps[task.step_index + 1] == "battle"
    result = step_skip_story(task, image, _clf(Scene.BATTLE))
    assert result is ADVANCE


def test_first_skip_story_does_not_advance_just_because_scene_is_battle(templates):
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    task = _task(templates)
    task.step_index = 5
    assert task.recipe.steps[task.step_index] == "skip_story"
    assert task.recipe.steps[task.step_index + 1] == "talk_on_stage"
    result = step_skip_story(task, image, _clf(Scene.BATTLE))
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind != "click"
