"""利特利尔大区高级「受困的同伴」：协会外对话后，找 8-B4 打初步探索。

协会接取后离开，在城里点冒险者头像（不点气泡），再进地区。
必须先认出 8-B4 左上方的木瞭望塔，再点塔下方带任务对话圈的旗帜。
看不见就从右边缘向左边缘轻轻划一下，只划一次，还没有就停。
战斗胜利并领取战斗奖励之后再跳过剧情。不点完成、扫荡、底部矿洞。不跑 --live。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LITRILE
from src.tasks.priority_flows import (
    ADVANCE,
    step_city_talk,
    step_enter_8_b4_basic,
    step_find_8_b4,
)
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.image import load_bgr
from src.vision.templates import load_templates
from src.vision.types import Scene

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "assets" / "templates"
FIXTURE = ROOT / "tests" / "fixtures" / "litril_region_8_b4_1080.png"

FLAG_BOX = (538, 1090, 652, 1284)
TOWER_BOX = (452, 944, 548, 1112)
D5_BOX = (500, 760, 680, 940)
MINE_UI_Y = 1680
BUBBLE_XY = (650, 1100)


def _templates():
    return load_templates()


def _task(templates, step: str = "find_8_b4") -> DailyCommissionTask:
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("受困的同伴"),
    )
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试受困的同伴")


def _blank(h=1920, w=1080):
    return np.full((h, w, 3), 30, dtype=np.uint8)


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def _region_base():
    """有实机地区图就用它。仓库里没有那张大图时，按实机框把塔和旗帜拼上。"""
    if FIXTURE.is_file():
        return load_bgr(FIXTURE)
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    tower = cv2.imread(str(TEMPLATES / "litril_b4_tower.png"))
    flag = cv2.imread(str(TEMPLATES / "stage_flag_8_b4.png"))
    assert tower is not None and flag is not None
    _paste(image, tower, TOWER_BOX[0], TOWER_BOX[1])
    _paste(image, flag, FLAG_BOX[0], FLAG_BOX[1])
    return image


def _region_with_bubble():
    image = _region_base()
    bubble = cv2.imread(str(TEMPLATES / "quest_bubble_8_b4.png"))
    assert bubble is not None
    _paste(image, bubble, BUBBLE_XY[0], BUBBLE_XY[1])
    return image


def _in_box(x, y, box):
    x1, y1, x2, y2 = box
    return x1 <= x < x2 and y1 <= y < y2


def test_trapped_companion_stays_high_and_talks_outside_association():
    recipe = get_recipe("受困的同伴")
    medicine = get_recipe("制作药物")
    assert recipe.location is LITRILE
    assert recipe.tier is CommissionTier.HIGH
    assert recipe.kind is CommissionKind.BATTLE
    assert recipe.quest_id == "trapped_companion"
    assert recipe.stage_flag_template == "stage_flag_8_b4"
    assert recipe.stage_label == "8-B4"
    assert recipe.npc_template == "npc_trapped_companion"
    assert recipe.card_template == "commission_trapped_companion"
    assert recipe.log_template == "commission_trapped_companion"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "explore",
        "find_8_b4",
        "enter_8_b4_basic",
        "battle",
        "skip_story",
        "claim",
    )
    assert "fight_8_b4_basic" not in recipe.steps
    # 制作药物不能被这条改掉：同在利特利尔，也是协会外冒险者，但是交物品、不打关。
    assert medicine.kind is CommissionKind.TURN_IN
    assert medicine.tier is CommissionTier.MEDIUM
    assert medicine.steps == (
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "claim",
    )
    assert "find_8_b4" not in medicine.steps
    assert "battle" not in medicine.steps


def test_find_8_b4_clicks_flag_not_tower_bubble_or_neighbors():
    templates = _templates()
    image = _region_with_bubble()
    result = step_find_8_b4(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "8-B4"
    x, y = result.action.x, result.action.y
    assert _in_box(x, y, FLAG_BOX)
    assert not _in_box(x, y, TOWER_BOX)
    assert not _in_box(x, y, D5_BOX)
    assert not (BUBBLE_XY[0] <= x < BUBBLE_XY[0] + 56 and BUBBLE_XY[1] <= y < BUBBLE_XY[1] + 68)
    assert y < MINE_UI_Y
    text = (result.action.message or "") + result.message
    assert "瞭望塔" in text
    assert "扫荡" in text
    assert "矿洞" in text


def test_find_8_b4_without_bubble_does_not_click():
    templates = _templates()
    image = _region_base()
    result = step_find_8_b4(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.label != "8-B4"
    assert result.action.kind == "swipe"
    assert result.action.label == "从右边缘向左边缘滑动地图"
    assert result.action.x == 1080 - max(8, int(1080 * 0.04))
    assert result.action.x2 == max(8, int(1080 * 0.04))
    assert result.action.x2 < result.action.x
    assert "从左边缘向中间" not in (result.action.label or "")
    assert result.action.label != "向左轻轻滑动地图"
    assert result.action.label != "向左滑动地图"


def test_find_8_b4_swipes_once_from_right_edge_then_stops():
    templates = _templates()
    # 纯色图不像地区图时应当停，不盲划。用一张挡住旗帜的地区图来测只划一次。
    region = _region_with_bubble()
    x1, y1, x2, y2 = FLAG_BOX
    region[y1:y2, x1:x2] = 40
    task = _task(templates)
    first = step_find_8_b4(task, region, _clf())
    assert first.action is not None
    assert first.action.kind == "swipe"
    assert first.action.label == "从右边缘向左边缘滑动地图"
    assert first.action.x == 1080 - max(8, int(1080 * 0.04))
    assert first.action.x2 == max(8, int(1080 * 0.04))
    assert first.action.x2 < first.action.x
    assert first.action.y == 1920 // 2
    assert first.action.y2 == first.action.y
    assert "只划" in (first.action.message or "")
    assert "从左边缘向中间" not in (first.action.message or "")
    assert "从屏幕中间" not in (first.action.message or "")
    # 已经划过一次：即使画面还能动，也不再划，直接停。
    second = step_find_8_b4(task, region, _clf())
    assert second.action is not None
    assert second.action.kind == "halt"
    assert "8-B4" in second.message
    assert "一次" in second.message
    assert second.status == "halt_missing"
    assert "扫荡" in second.message
    third = step_find_8_b4(task, region, _clf())
    assert third.action is not None
    assert third.action.kind == "halt"


def test_find_8_b4_without_tower_does_not_click_even_with_flag_and_bubble():
    templates = _templates()
    image = _region_with_bubble()
    x1, y1, x2, y2 = TOWER_BOX
    image[y1:y2, x1:x2] = 40
    result = step_find_8_b4(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.label != "8-B4"


def test_find_8_b4_advances_when_already_on_stage():
    templates = _templates()
    canvas = _blank()
    basic = cv2.imread(str(TEMPLATES / "stage_8_b4_basic.png"))
    assert basic is not None
    _paste(canvas, basic, 200, 900)
    result = step_find_8_b4(_task(templates), canvas, _clf())
    assert result is ADVANCE


def test_city_talk_clicks_adventurer_not_bubble():
    templates = _templates()
    canvas = _blank()
    face = cv2.imread(str(TEMPLATES / "npc_trapped_companion.png"))
    assert face is not None
    fx, fy = 80, 1500
    _paste(canvas, face, fx, fy)
    result = step_city_talk(_task(templates, "city_talk"), canvas, _clf(Scene.UNKNOWN))
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert fx <= result.action.x < fx + face.shape[1]
    assert fy <= result.action.y < fy + face.shape[0]
    assert "气泡" in (result.action.message or "")


def test_enter_8_b4_basic_clicks_star():
    templates = _templates()
    canvas = _blank()
    basic = cv2.imread(str(TEMPLATES / "stage_8_b4_basic.png"))
    assert basic is not None
    bx, by = 200, 900
    _paste(canvas, basic, bx, by)
    result = step_enter_8_b4_basic(_task(templates, "enter_8_b4_basic"), canvas, _clf())
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind == "click"
    assert bx <= result.action.x < bx + basic.shape[1]
    assert by <= result.action.y < by + basic.shape[0]
    assert "扫荡" in (result.action.message or "")
    assert "初步探索" in (result.action.message or "")


def test_enter_8_b4_clicks_enter_when_visible_and_advances_in_battle():
    templates = _templates()
    canvas = _blank()
    enter = cv2.imread(str(TEMPLATES / "stage_enter_gold.png"))
    assert enter is not None
    ex, ey = 700, 1400
    # 金色进入在选关页偏下，但不要落到扫荡那一排（约 y=1750）。
    _paste(canvas, enter, ex, ey)
    result = step_enter_8_b4_basic(_task(templates, "enter_8_b4_basic"), canvas, _clf())
    assert result is not ADVANCE
    assert result.action is not None
    assert result.action.kind == "click"
    assert ex <= result.action.x < ex + enter.shape[1]
    assert ey <= result.action.y < ey + enter.shape[0]
    assert "扫荡" in (result.action.message or "")

    battle = step_enter_8_b4_basic(
        _task(templates, "enter_8_b4_basic"),
        _blank(),
        _clf(Scene.BATTLE),
    )
    assert battle is ADVANCE
