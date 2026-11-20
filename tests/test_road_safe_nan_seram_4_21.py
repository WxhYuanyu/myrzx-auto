"""南赛拉姆「保证商路畅通」：先在商店和梅姬塔对话，再打 4-21 初步探索。

进入探索后不用滑动。必须看到 4-C1 左边小屋和任务对话圈才点 4-21。
不点小屋、气泡、4-22、4-23、4-C1、底部矿洞/回程/探索队或扫荡。不跑 --live。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LANGREN, NAN_SERAM
from src.tasks.priority_flows import (
    ADVANCE,
    step_enter_4_21_basic,
    step_find_4_21,
    step_talk_mejita,
)
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import load_templates
from src.vision.types import Scene

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nan_seram_region_4_21_1080.png"
_FLAG_BOX = (730, 1198, 122, 218)
_HOUSE_BOX = (530, 1510, 165, 190)
_BUBBLE_BOX = (852, 1188, 86, 100)
_FLAG_4_22 = (548, 1290, 157, 220)
_FLAG_4_23 = (330, 1420, 190, 198)
_FLAG_4_C1 = (700, 1455, 170, 203)
# 底部「矿洞」按钮大约在这里，测试时确认不会点到它。
_MINE_UI = (430, 1710, 280, 200)


def _templates():
    return load_templates()


def _task(templates, step: str = "find_4_21") -> DailyCommissionTask:
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("保证商路畅通", location="南赛拉姆"),
    )
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.STAGE_MAP) -> Classification:
    return Classification(scene=scene, reason="测试南赛拉姆保证商路畅通 4-21")


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
    # 大张南赛拉姆地区图不在这次上传里。按实机框把小屋、4-21 和对话圈拼上。
    image = np.full((1920, 1080, 3), 40, dtype=np.uint8)
    root = Path(__file__).resolve().parents[1] / "assets" / "templates"
    house = cv2.imread(str(root / "nan_seram_c1_house.png"))
    flag = cv2.imread(str(root / "stage_flag_4_21.png"))
    bubble = cv2.imread(str(root / "quest_bubble_4_21.png"))
    assert house is not None and flag is not None and bubble is not None
    _paste(image, house, _HOUSE_BOX[0], _HOUSE_BOX[1])
    _paste(image, flag, _FLAG_BOX[0], _FLAG_BOX[1])
    _paste(image, bubble, _BUBBLE_BOX[0], _BUBBLE_BOX[1])
    return image


def _blank(h=1920, w=1080):
    return np.full((h, w, 3), 30, dtype=np.uint8)


def test_same_name_requires_location_and_stays_low():
    with pytest.raises(KeyError):
        get_recipe("保证商路畅通")
    recipe = get_recipe("保证商路畅通", location="南赛拉姆")
    assert recipe.location is NAN_SERAM
    assert recipe.tier is CommissionTier.LOW
    assert recipe.kind is CommissionKind.BATTLE
    assert recipe.quest_id == "road_safe_nan_seram"
    assert recipe.stage_flag_template == "stage_flag_4_21"
    assert recipe.stage_label == "4-21"
    assert recipe.stage_node == "basic"
    assert recipe.npc_template == "npc_mejita"
    assert recipe.card_template == "commission_road_safe_nan_seram"
    assert recipe.log_template == "commission_road_safe_nan_seram"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "enter_shop",
        "talk_mejita",
        "skip_story",
        "leave_shop",
        "explore",
        "find_4_21",
        "enter_4_21_basic",
        "battle",
        "claim",
    )
    langren = get_recipe("保证商路畅通", location="浪人岬")
    assert langren.location is LANGREN
    assert langren.quest_id == "road_safe_langren"
    assert langren.npc_template == "npc_metaya"
    assert "talk_metaya" in langren.steps
    assert "enter_5_a2_basic" in langren.steps
    assert "talk_mejita" not in langren.steps
    assert "find_4_21" not in langren.steps


def test_finds_4_21_on_default_view_without_swiping():
    templates = _templates()
    image = _region()
    result = step_find_4_21(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action.kind == "click"
    fx, fy, fw, fh = _FLAG_BOX
    assert fx <= result.action.x <= fx + fw
    assert fy <= result.action.y <= fy + fh
    bx, by, bw, bh = _BUBBLE_BOX
    assert not (bx <= result.action.x <= bx + bw and by <= result.action.y <= by + bh)
    hx, hy, hw, hh = _HOUSE_BOX
    assert not (hx <= result.action.x <= hx + hw and hy <= result.action.y <= hy + hh)
    for box in (_FLAG_4_22, _FLAG_4_23, _FLAG_4_C1, _MINE_UI):
        x, y, w, h = box
        assert not (x <= result.action.x <= x + w and y <= result.action.y <= y + h)
    assert "滑动" not in (result.action.message or "")
    assert "滑动" not in (result.action.label or "")


def test_covers_house_and_does_not_swipe():
    templates = _templates()
    image = _cover(_region(), _HOUSE_BOX)
    result = step_find_4_21(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action.kind == "halt"
    assert result.action.kind != "swipe"
    assert "停下" in (result.action.message or "")
    assert "不要自行滑动" in (result.action.message or "")


def test_covers_bubble_and_does_not_swipe():
    templates = _templates()
    image = _cover(_region(), _BUBBLE_BOX)
    result = step_find_4_21(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action.kind == "halt"
    assert result.action.kind != "swipe"


def test_covers_flag_and_does_not_click_neighbors():
    templates = _templates()
    image = _cover(_region(), _FLAG_BOX)
    result = step_find_4_21(_task(templates), image, _clf())
    assert result is not ADVANCE
    assert result.action.kind == "halt"
    assert result.action.kind != "swipe"


def test_already_on_stage_select_advances():
    templates = _templates()
    canvas = _blank()
    basic = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "stage_4_21_basic.png"))
    assert basic is not None
    _paste(canvas, basic, 200, 400)
    result = step_find_4_21(_task(templates), canvas, _clf(Scene.UNKNOWN))
    assert result is ADVANCE


def test_talk_mejita_clicks_face_not_buy():
    templates = _templates()
    canvas = _blank()
    face = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "npc_mejita.png"))
    assert face is not None
    fx, fy = 200, 220
    _paste(canvas, face, fx, fy)
    buy = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "shop_buy.png"))
    if buy is not None:
        bx, by = 800, 1500
        _paste(canvas, buy, bx, by)
    result = step_talk_mejita(_task(templates, "talk_mejita"), canvas, _clf(Scene.UNKNOWN))
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert fx <= result.action.x < fx + face.shape[1]
    assert fy <= result.action.y < fy + face.shape[0]
    if buy is not None:
        assert not (
            800 <= result.action.x < 800 + buy.shape[1]
            and 1500 <= result.action.y < 1500 + buy.shape[0]
        )


def test_talk_mejita_advances_on_story():
    templates = _templates()
    result = step_talk_mejita(
        _task(templates, "talk_mejita"),
        _blank(),
        _clf(Scene.STORY_DIALOG),
    )
    assert result is ADVANCE


def test_enter_4_21_basic_clicks_star_not_sweep():
    templates = _templates()
    canvas = _blank()
    star = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "stage_4_21_basic.png"))
    assert star is not None
    sx, sy = 200, 500
    _paste(canvas, star, sx, sy)
    sweep = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "stage_sweep.png"))
    if sweep is None:
        sweep = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "btn_sweep.png"))
    if sweep is not None:
        _paste(canvas, sweep, 700, 1600)
    result = step_enter_4_21_basic(_task(templates, "enter_4_21_basic"), canvas, _clf(Scene.UNKNOWN))
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert sx <= result.action.x < sx + star.shape[1]
    assert sy <= result.action.y < sy + star.shape[0]
    if sweep is not None:
        assert not (
            700 <= result.action.x < 700 + sweep.shape[1]
            and 1600 <= result.action.y < 1600 + sweep.shape[0]
        )
    assert "扫荡" not in (result.action.label or "")


def test_enter_4_21_basic_clicks_enter_after_star():
    templates = _templates()
    canvas = _blank()
    # stage_enter 默认尺度会跳过 1.0，这里用已有的金色「进入」（尺度含 1.0）验证会点「进入」。
    enter = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "stage_enter_gold.png"))
    if enter is None:
        pytest.skip("没有 stage_enter_gold 裁切")
    _paste(canvas, enter, 400, 1400)
    result = step_enter_4_21_basic(_task(templates, "enter_4_21_basic"), canvas, _clf(Scene.UNKNOWN))
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert 400 <= result.action.x < 400 + enter.shape[1]
    assert 1400 <= result.action.y < 1400 + enter.shape[0]
    assert "进入" in (result.action.message or "") or "进入" in (result.action.label or "")


def test_enter_4_21_basic_advances_in_battle():
    templates = _templates()
    result = step_enter_4_21_basic(
        _task(templates, "enter_4_21_basic"),
        _blank(),
        _clf(Scene.BATTLE),
    )
    assert result is ADVANCE
