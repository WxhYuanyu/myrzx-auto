"""退回当前大区，以及在大区地图上跨区、平移找城。"""

from __future__ import annotations

import numpy as np
import pytest

from src.tasks.daily_commission import DailyCommissionTask
from src.tasks.phase import Phase
from src.tasks.locations import LANGREN, LITRILE, NAN_SERAM, SAINT_CASARE
from src.tasks.navigation import (
    PORTAL_EXAMPLES,
    click_or_pan_to_place,
    kind_from_title,
    normalize_place_title,
)
from src.tasks.recipes import get_recipe
from src.vision.classify import classify_scene
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Box, Match, Scene


class _Ocr:
    def __init__(self, hits=None, title=None):
        self.hits = hits or {}
        self.title = title

    def find_text(self, image, text):
        return list(self.hits.get(text, []))

    def read_title(self, image):
        return self.title


def _paste(canvas, tile, x, y):
    height, width = tile.shape[:2]
    canvas[y : y + height, x : x + width] = tile
    return canvas


def test_title_kinds_follow_the_bar_not_a_portal():
    assert kind_from_title("雨林之底") == "nested"
    assert kind_from_title("纳尔本地区") == "region_stage"
    assert kind_from_title("图兰顿沙漠地区") == "region_stage"
    assert kind_from_title("图兰顿沙漠") == "city"
    assert kind_from_title("阿格莱恩") == "continent"
    assert kind_from_title("克里斯汀") == "continent"
    assert kind_from_title("巡逻走廊 9-7") == "stage_prep"
    assert kind_from_title("莉莉托斯近郊 1-3") == "stage_prep"
    assert kind_from_title("莉安湖") == "city"
    assert kind_from_title("利安湖") == "nested"
    assert kind_from_title("纳尔本") == "city"
    assert kind_from_title("纳尔") == "nested"
    assert kind_from_title("圣卡萨雷斯") == "city"
    assert kind_from_title("利特利尔大区") == "city"
    assert normalize_place_title("莉莉托斯") == "王城莉莉托斯"
    assert kind_from_title("莉莉托斯") == "city"
    for portal in PORTAL_EXAMPLES:
        assert kind_from_title(portal) == "portal"
    with pytest.raises(KeyError, match="尚未收录"):
        get_recipe("没有这条委托")
    assert SAINT_CASARE.name == "圣卡萨雷斯"
    assert LITRILE.map_click is None
    assert LITRILE.map_label_template is None


def test_nested_area_clicks_return_and_not_a_portal(templates):
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    tile = by_id["stage_return"].image_bgr
    _paste(canvas, tile, 40, 700)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("阻碍道路的家伙"))
    task.title_reader = lambda image: ("雨林之底", "")
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "回程"
    assert "传送门" in (result.action.message or "")
    assert "雨林之底" in (result.action.message or "")
    for portal in PORTAL_EXAMPLES:
        assert portal not in (result.action.label or "")
    assert result.action.x is not None and 40 < result.action.x < 40 + tile.shape[1]


def test_unlisted_coastal_town_clicks_return_not_the_commission_board(templates):
    """滨海小镇没有标题模板。有「回程」就要点，不能停成委托标题还没裁切。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
    tile = by_id["stage_return"].image_bgr
    _paste(canvas, tile, 55, 1800)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(canvas)
    assert result.scene is Scene.UNKNOWN
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "回程"
    assert result.action.label != "扫荡"
    text = f"{result.message} {result.action.message}"
    assert "标题裁切" not in text
    assert "委托板" not in text
    assert "传送门" in (result.action.message or "")
    for portal in PORTAL_EXAMPLES:
        assert portal not in (result.action.label or "")
    assert result.action.x is not None and 55 < result.action.x < 55 + tile.shape[1]


def test_region_stage_title_clicks_return_home(templates):
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, by_id["stage_return"].image_bgr, 40, 700)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("阻碍道路的家伙"))
    task.title_reader = lambda image: ("纳尔本地区", "危险区域")
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "回程"
    assert "纳尔本地区" in (result.action.message or "")
    assert result.action.label != "扫荡"


def test_portal_text_never_becomes_a_click(templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    task.title_reader = lambda image: ("冥土之国→", "")
    blank = np.zeros((800, 700, 3), dtype=np.uint8)
    result = task.plan(blank)
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.x is None
    assert "传送门" in result.message


def test_stage_prep_clicks_leave_and_never_sweep(multi_battle, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者"))
    result = task.plan(multi_battle["stage_select"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "离开"
    assert result.action.label != "扫荡"
    assert "扫荡" in (result.action.message or "")
    assert result.action.x is not None and result.action.x < 400


def test_desert_region_during_accept_clicks_return_not_the_flag(multi_battle, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者"))
    result = task.plan(multi_battle["stage_map"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "回程"
    assert result.action.label != "9-7"
    assert result.action.label != "扫荡"


def test_other_city_opens_world_map_not_association_or_explore(templates):
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, by_id["city_association"].image_bgr, 80, 200)
    _paste(canvas, by_id["city_explore"].image_bgr, 400, 500)
    _paste(canvas, by_id["city_world_map"].image_bgr, 200, 400)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("仇恨会令我成长"))
    task.title_reader = lambda image: ("纳尔本", "")
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "大地图"
    assert result.action.label != "协会"
    assert result.action.label != "探险"
    assert "协会" in (result.action.message or "")
    assert "探险" in (result.action.message or "")


def test_confirmed_city_reenters_association_not_explore(templates):
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, by_id["city_association"].image_bgr, 80, 220)
    _paste(canvas, by_id["city_explore"].image_bgr, 420, 480)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("处理毒桶"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index("reenter_association")
    task.title_reader = lambda image: ("莉安湖", "")
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "协会"
    assert result.action.label != "探险"
    assert result.action.label != "大地图"


def test_aglaen_top_does_not_assume_crystia_tab_is_visible(walkthrough, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("仇恨会令我成长"))
    result = task.plan(walkthrough["wt_world_lilitos"])
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向上滑动地图"
    assert "不要假设" in (result.action.message or "")
    assert "最上" in (result.action.message or "")
    assert result.action.label != "离开"
    assert result.action.label != "王城莉莉托斯"

    arrived = DailyCommissionTask(specs=templates, recipe=get_recipe("仇恨会令我成长"))
    south = arrived.plan(walkthrough["wt_world_south"])
    assert south.action is not None
    assert south.action.kind == "click"
    assert south.action.label == "前往克里斯汀"
    assert south.action.label != "离开"


def test_crystia_returns_by_the_corner_tab_not_leave(turn_in, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "返阿格莱恩"
    assert result.action.label != "离开"
    assert result.action.x is not None and result.action.x > 700


def test_litrile_without_a_template_halts_on_crystia(turn_in, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(turn_in["region"])
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.x is None
    assert "利特利尔大区" in result.message
    assert "坐标" in result.message
    assert "不会" in result.message
    assert result.action.label != "图兰顿沙漠"
    assert result.action.label != "离开"


def test_litrile_ocr_click_uses_the_visible_name(turn_in, templates):
    hit = Match(
        "ocr",
        "利特利尔大区",
        None,
        "ocr",
        Box(120, 640, 90, 36),
        0.96,
        1.0,
    )
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("受困的同伴"),
        ocr=_Ocr({ "利特利尔大区": [hit] }),
    )
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "利特利尔大区"
    assert result.action.x == hit.box.center[0]
    assert result.action.y == hit.box.center[1]


def test_litrile_ocr_miss_pans_west_then_stops(turn_in, templates):
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("受困的同伴"),
        ocr=_Ocr(),
    )
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向右滑动地图"
    assert result.action.x2 is not None and result.action.x is not None
    assert result.action.x2 > result.action.x
    assert "西" in (result.action.message or "")
    assert result.action.label != "图兰顿沙漠"
    for _ in range(6):
        result = task.plan(turn_in["region"])
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.x is None
    assert "坐标" in result.message


def test_moved_label_is_clicked_where_it_is_not_where_it_was(walkthrough, templates):
    image = walkthrough["wt_world_lilitos"]
    task = DailyCommissionTask(specs=templates)
    clf = classify_scene(image, templates)
    found = click_or_pan_to_place(task, image, clf, NAN_SERAM)
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "南赛拉姆"
    assert found.action.y is not None and found.action.y > 1600

    hidden = click_or_pan_to_place(task, image, clf, LANGREN)
    assert hidden.action is not None
    assert hidden.action.kind == "swipe"
    assert hidden.action.label == "向上滑动地图"
    assert hidden.action.kind != "click"
    assert "浪人岬" in (hidden.action.message or "")
    assert "坐标" in (hidden.action.message or "")


def test_world_map_button_is_the_plaque_and_matches_both_cities(turn_in, walkthrough, templates):
    by_id = templates_by_id(templates)
    tile = by_id["city_world_map"].image_bgr
    assert tile.shape[0] <= 80
    assert tile.shape[1] < 260
    tab = by_id["region_tab_crystia"].image_bgr
    assert tab.shape[0] <= 56
    lilitos = find_template(walkthrough["wt_city"], by_id["city_world_map"])
    turandon = find_template(turn_in["city_npc"], by_id["city_world_map"])
    assert lilitos is not None and lilitos.score >= 0.9
    assert turandon is not None and turandon.score >= 0.9
    south = find_template(walkthrough["wt_world_south"], by_id["region_tab_crystia"])
    north = find_template(walkthrough["wt_world_lilitos"], by_id["region_tab_crystia"])
    assert south is not None and south.score >= 0.9
    assert north is None


def test_capital_crop_without_a_title_does_not_enter_the_association(screens, templates):
    task = DailyCommissionTask(specs=templates)
    result = task.plan(screens["city"])
    assert result.scene is not Scene.CITY_LILITOS
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.label != "协会"
