"""制作药物：接取后离开协会，点城里左下角冒险者的头像并跳过剧情，不打关。不跑 --live。"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LITRILE
from src.tasks.priority_flows import ADVANCE, step_accept_board, step_city_talk, step_claim
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def _task(templates, step: str = "accept_board") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("制作药物"))
    if step == "accept_board":
        task.phase = Phase.ACCEPT
    else:
        task.phase = Phase.GO_STAGE
        task.step_index = task.recipe.steps.index(step)
    task.saw_continent = True
    task.pending_city = "利特利尔大区"
    return task


def _clf(scene: Scene, reason: str = "测试制作药物") -> Classification:
    return Classification(scene=scene, reason=reason)


def _association_room(templates, commission_id: str):
    by_id = templates_by_id(templates)
    image = np.zeros((1920, 1080, 3), dtype=np.uint8)
    board = by_id[commission_id].image_bgr
    leave = by_id["association_leave"].image_bgr
    _paste(image, board, 1080 - board.shape[1] - 20, 1920 - board.shape[0] - 40)
    _paste(image, leave, 20, 1920 - leave.shape[0] - 20)
    return image


def test_make_medicine_is_a_medium_turn_in_without_battle():
    recipe = get_recipe("制作药物")
    assert recipe.location is LITRILE
    assert recipe.tier is CommissionTier.MEDIUM
    assert recipe.kind is CommissionKind.TURN_IN
    assert recipe.flow == "litrile_make_medicine"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.card_template == "commission_make_medicine"
    assert recipe.npc_template == "npc_make_medicine"
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "claim",
    )
    assert "fight_stage" not in recipe.steps
    assert "explore" not in recipe.steps
    assert "左下角" in recipe.summary
    assert "不打关" in recipe.summary


def test_make_medicine_clicks_commission_in_unknown_association_room(templates):
    """利特利尔的「委托」木牌是 click_only，室内常被判成 UNKNOWN，必须先点「委托」。"""
    image = _association_room(templates, "association_commission_turandon")
    result = step_accept_board(_task(templates), image, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "委托"
    assert result.action.label != "离开"


def test_make_medicine_clicks_commission_when_room_is_association(templates):
    image = _association_room(templates, "association_commission_turandon")
    result = step_accept_board(_task(templates), image, _clf(Scene.ASSOCIATION))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "委托"


def test_make_medicine_clicks_its_card_once_the_board_is_open(templates):
    by_id = templates_by_id(templates)
    image = np.zeros((1920, 1080, 3), dtype=np.uint8)
    title = by_id["commission_center_title"].image_bgr
    card = by_id["commission_make_medicine"].image_bgr
    _paste(image, title, 20, 20)
    x, y = 400, 400
    _paste(image, card, x, y)
    result = step_accept_board(_task(templates), image, _clf(Scene.COMMISSION_LIST))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "制作药物"
    assert x <= result.action.x < x + card.shape[1]
    assert y <= result.action.y < y + card.shape[0]


def test_city_talk_clicks_the_adventurer_face_not_the_bubble(templates):
    by_id = templates_by_id(templates)
    image = np.full((1920, 1080, 3), 30, dtype=np.uint8)
    face = by_id["npc_make_medicine"].image_bgr
    bubble = (by_id.get("quest_bubble") or by_id["quest_bubble_map"]).image_bgr
    # 离开协会后出现在城里左下角附近。
    x, y = 40, 1600
    _paste(image, face, x, y)
    bx, by = x + face.shape[1] + 8, y + 20
    _paste(image, bubble, bx, by)
    result = step_city_talk(_task(templates, "city_talk"), image, _clf(Scene.UNKNOWN))
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "冒险者"
    assert x <= result.action.x < x + face.shape[1]
    assert y <= result.action.y < y + face.shape[0]
    assert not (bx <= result.action.x < bx + bubble.shape[1] and by <= result.action.y < by + bubble.shape[0])


def test_claim_does_not_click_complete(templates):
    result = step_claim(_task(templates, "claim"), np.zeros((1920, 1080, 3), dtype=np.uint8), _clf(Scene.UNKNOWN))
    assert result.status == "done"
    assert result.action is None or result.action.kind != "click"
    text = (result.action.message if result.action is not None else "") + (result.message or "")
    assert "完成" in text or "领" in text
