"""纳尔本高级委托「阻碍道路的家伙」：步骤顺序、城里点冒险者、找 7-5、7-5-1 初步探索。不跑 --live。"""

from __future__ import annotations

import cv2

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import NAR
from src.tasks.priority_flows import ADVANCE, step_city_talk, step_claim, step_fight_7_5_1
from src.tasks.recipes import CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _task(templates, step: str) -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("阻碍道路的家伙"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.UNKNOWN) -> Classification:
    return Classification(scene=scene, reason="测试阻碍道路的家伙")


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def test_recipe_order_tier_and_crops():
    recipe = get_recipe("阻碍道路的家伙")
    assert recipe.tier is CommissionTier.HIGH
    assert recipe.location is NAR
    assert recipe.awaiting_crops == frozenset()
    assert recipe.card_template == recipe.log_template == "commission_road_blocker"
    assert recipe.npc_template == "npc_road_blocker"
    assert recipe.stage_flag_template == "stage_flag_7_5"
    assert recipe.stage_label == "7-5-1" and recipe.stage_node == "basic"
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "explore",
        "fight_7_5_1",
        "battle",
        "leave_stage",
        "claim",
    )
    # 不回去找冒险者，不在关卡上对话。
    assert "talk_task_npc" not in recipe.steps
    assert recipe.steps.count("city_talk") == 1


def test_city_talk_clicks_the_adventurer_face_in_the_lower_left(templates):
    by_id = templates_by_id(templates)
    face = by_id["npc_road_blocker"].image_bgr
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    x, y = 60, 1450
    _paste(image, face, x, y)
    bubble = by_id["quest_bubble_map"].image_bgr
    bx, by = x + face.shape[1] + 10, y + 30
    _paste(image, bubble, bx, by)
    result = step_city_talk(_task(templates, "city_talk"), image, _clf())
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "年轻的冒险者"
    assert x <= result.action.x < x + face.shape[1]
    assert y <= result.action.y < y + face.shape[0]
    assert not (bx <= result.action.x < bx + bubble.shape[1])


def test_7_5_missing_pans_right_with_the_verified_swipe_then_stops(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    _paste(image, by_id["stage_return"].image_bgr, 40, 1800)
    task = _task(templates, "fight_7_5_1")
    first = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert first.action is not None and first.action.kind == "swipe"
    # 和 3-20 / 浪人岬一样用 _swipe 的 east：手指左滑，内容往右。
    assert first.action.label == "向左滑动地图"
    assert first.action.x2 < first.action.x
    assert "7-5" in first.action.message and "扫荡" in first.action.message
    # 画面没动：到边，停下说明，不再滑。
    second = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert second.status == "halt_missing"
    assert "不再移动" in second.action.message


def test_7_5_flag_is_clicked_not_the_bubble(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    flag = by_id["stage_flag_7_5"].image_bgr
    x, y = 400, 1200
    _paste(image, flag, x, y)
    _paste(image, by_id["quest_bubble_map"].image_bgr, x + flag.shape[1] + 4, y)
    task = _task(templates, "fight_7_5_1")
    result = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert result.action is not None and result.action.kind == "click"
    assert result.action.label == "7-5"
    assert x <= result.action.x < x + flag.shape[1]
    assert task.node_selected is False
    assert task.step_armed is False  # 还要在同一步选「初步探索」


def test_7_5_1_star_then_enter_never_sweep(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    star = by_id["stage_7_5_basic"].image_bgr
    _paste(image, star, 120, 1000)
    # 真实 1080x1920 画面上「离开」约为 1-3 小裁切的 2.2 倍。
    leave = by_id["stage_leave"].image_bgr
    leave = cv2.resize(leave, (int(leave.shape[1] * 2.2), int(leave.shape[0] * 2.2)))
    _paste(image, leave, 10, 1800)
    task = _task(templates, "fight_7_5_1")
    picked = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert picked.action is not None and picked.action.kind == "click"
    assert picked.action.label == "初步探索"
    assert task.node_selected is True
    # 只是选中、还没出「进入」：等，不点扫荡。
    waiting = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert waiting.action is None or waiting.action.kind != "click"
    # 出现「进入」：点「进入」。
    enter = by_id["stage_enter_gold"].image_bgr
    image = image.copy()  # 新的一帧（匹配缓存按帧）
    _paste(image, enter, 700, 1500)
    entered = step_fight_7_5_1(task, image, _clf(Scene.STAGE_MAP))
    assert entered.action is not None and entered.action.kind == "click"
    assert entered.action.label != "扫荡"
    assert entered.action.y < int(1920 * 1750 / 1920)


def test_7_5_1_star_that_starts_battle_directly_advances(templates):
    task = _task(templates, "fight_7_5_1")
    task.node_selected = True
    image = np.zeros((1920, 1080, 3), dtype=np.uint8)
    assert step_fight_7_5_1(task, image, _clf(Scene.BATTLE)) is ADVANCE
    # 点星星后的过场帧：等，不回头找旗帜或乱滑。
    transition = step_fight_7_5_1(task, image, _clf(Scene.UNKNOWN))
    assert transition.action is None or transition.action.kind not in {"click", "swipe"}


def test_claim_does_not_click_finish(templates):
    task = _task(templates, "claim")
    result = step_claim(task, np.zeros((1920, 1080, 3), dtype=np.uint8), _clf())
    assert result.status == "done"
    assert result.action.kind == "halt"
    assert "先不点「完成」" in result.action.message
