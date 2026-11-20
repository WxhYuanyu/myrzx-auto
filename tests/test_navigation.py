"""退回当前大区，以及在大区地图上跨区、平移找城。"""

from __future__ import annotations

import numpy as np
import pytest

from src import config
from src.tasks.daily_commission import DailyCommissionTask
from src.tasks.phase import Phase
from pathlib import Path

from src.tasks.locations import AGLAEN, CRYSTIA, LANGREN, LITRILE, NAN_SERAM, SAINT_CASARE
from src.tasks.navigation import (
    PORTAL_EXAMPLES,
    _arm_pan,
    click_or_pan_to_place,
    kind_from_title,
    normalize_place_title,
    recognize_region,
    step as navigation_step,
)
from src.vision.image import load_bgr
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
    assert LITRILE.map_label_template == "world_litrile"
    assert LITRILE.name == "利特利尔大区"


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


def test_mine_with_leave_clicks_leave_before_the_continent(templates):
    """结晶矿洞没有回程和大地图。还没看见大区标题时，左下「离开」就点。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    tile = by_id["stage_leave"].image_bgr
    _paste(canvas, tile, 16, 630)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(canvas)
    assert result.scene is Scene.UNKNOWN
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "离开"
    assert result.action.label not in {"兑换", "战阵", "扫荡", "回程"}
    text = f"{result.message} {result.action.message}"
    assert "兑换" in text
    assert "战阵" in text
    assert "标题裁切" not in text
    assert result.action.x is not None and result.action.x < canvas.shape[1] * 0.4


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


def test_target_city_still_opens_the_world_map_first(walkthrough, templates):
    """人已经在目标城，也先点「大地图」，看到大区地图之后才进城接委托。"""
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    first = task.plan(walkthrough["wt_city"])
    assert first.status == "continue"
    assert first.action is not None
    assert first.action.kind == "click"
    assert first.action.label == "大地图"
    assert first.action.label != "协会"
    assert first.action.label != "探险"
    assert "阿格莱恩" in (first.action.message or "")
    assert task.saw_continent is False

    opened = task.plan(walkthrough["wt_world_lilitos"])
    assert opened.action is not None
    assert opened.action.label == "王城莉莉托斯"
    assert task.saw_continent is True

    entered = task.plan(walkthrough["wt_city"])
    assert entered.action is not None
    assert entered.action.label == "协会"


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


def test_langren_visible_but_cut_off_banner_swipes_finger_right(walkthrough, templates):
    """南边已有「浪人岬」，旗帜被切在左边缘时，手指从左向右滑，不点半截，也不点「离开」。"""
    image = walkthrough["wt_world_south"].copy()
    image[1560:1720, 0:480] = (32, 48, 32)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(image)
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向右滑动地图"
    assert result.action.x is not None and result.action.x2 is not None
    assert result.action.x2 > result.action.x
    assert result.action.y == result.action.y2
    assert "从左向右" in (result.action.message or "")
    assert "向左" not in (result.action.message or "")
    assert "浪人岬" in (result.action.message or "")
    assert "前往克里斯汀" in (result.action.message or "")
    assert result.action.label != "离开"
    assert result.action.label != "向左滑动地图"
    assert result.action.label != "向上滑动地图"

    task.crystia_reveal_swipes = config.MAP_SWIPE_MAX
    halted = task.plan(image)
    assert halted.status == "halt_missing"
    assert halted.action is not None
    assert halted.action.kind == "halt"
    assert halted.action.x is None
    assert halted.action.label != "离开"
    assert "离开" in halted.message


FIXTURE_CRYSTIA_WEST = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "navigation"
    / "crystia_west_litrile.png"
)


def _mask(image, y0, y1, x0, x1):
    painted = image.copy()
    painted[y0:y1, x0:x1] = (24, 32, 24)
    return painted


def test_real_crystia_map_clicks_litrile_not_the_commission_board(templates):
    image = load_bgr(FIXTURE_CRYSTIA_WEST)
    classified = classify_scene(image, templates)
    assert classified.scene is Scene.REGION_CRYSTIA
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(image)
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "利特利尔大区"
    text = f"{result.message} {result.action.message}"
    assert "委托板" not in text
    assert "标题裁切" not in text
    assert result.action.label != "离开"
    assert result.action.label != "返阿格莱恩"


def test_crystia_is_recognized_without_the_title_template(templates):
    image = load_bgr(FIXTURE_CRYSTIA_WEST)
    no_title = _mask(image, 180, 420, 0, 760)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    task._match_cache = {}
    by_clue = recognize_region(task, no_title)
    assert by_clue is not None and by_clue.region is CRYSTIA
    assert by_clue.clue in {"tab", "place"}
    clicked = task.plan(no_title)
    assert clicked.action is not None
    assert clicked.action.label == "利特利尔大区"
    assert "标题裁切" not in (clicked.message or "")

    by_id = templates_by_id(templates)
    only_place = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(only_place, by_id["region_turandon"].image_bgr, 40, 200)
    task._match_cache = {}
    sight = recognize_region(task, only_place)
    assert sight is not None and sight.region is CRYSTIA
    assert sight.clue == "place"
    assert sight.match.label == "图兰顿沙漠"
    walking = task.plan(only_place)
    assert walking.action is not None
    assert walking.status == "continue"
    assert "利特利尔大区" in (walking.action.message or "")
    assert "标题裁切" not in (walking.message or "")

    only_tab = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(only_tab, by_id["region_tab_aglaen"].image_bgr, 80, 500)
    task._match_cache = {}
    tab_sight = recognize_region(task, only_tab)
    assert tab_sight is not None and tab_sight.region is CRYSTIA
    assert tab_sight.clue == "tab"
    assert tab_sight.match.label == "返阿格莱恩"


def test_aglaen_is_recognized_without_the_title_template(walkthrough, templates):
    by_id = templates_by_id(templates)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    only_place = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(only_place, by_id["world_langren"].image_bgr, 80, 200)
    task._match_cache = {}
    by_place = recognize_region(task, only_place)
    assert by_place is not None and by_place.region is AGLAEN
    assert by_place.clue == "place"
    assert by_place.match.label == "浪人岬"
    stayed = task.plan(only_place)
    assert stayed.action is not None
    assert stayed.action.label != "离开"
    assert "标题裁切" not in (stayed.message or "")

    only_tab = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(only_tab, by_id["region_tab_crystia"].image_bgr, 20, 400)
    task._match_cache = {}
    by_tab = recognize_region(task, only_tab)
    assert by_tab is not None and by_tab.region is AGLAEN
    assert by_tab.clue == "tab"
    assert by_tab.match.label == "前往克里斯汀"
    south = walkthrough["wt_world_south"]
    assert recognize_region(task, _mask(south, 200, 400, 0, 700)).region is AGLAEN


def test_unknown_frame_after_a_continent_is_not_a_commission_board(templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    task.saw_continent = True
    blank = np.zeros((400, 400, 3), dtype=np.uint8)
    clf = classify_scene(blank, templates)
    nav = navigation_step(task, blank, clf)
    assert nav is not None
    assert nav.action is not None
    assert nav.action.kind == "wait"
    assert nav.status == "skip_unknown"
    planned = task.plan(blank)
    assert planned.action is not None
    text = f"{planned.message} {planned.action.message}"
    assert "标题裁切" not in text
    assert planned.action.kind == "wait"


def test_navigation_step_clicks_association_after_the_continent(walkthrough, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    city = walkthrough["wt_city"]
    before = classify_scene(city, templates)
    leaving = navigation_step(task, city, before)
    assert leaving is not None and leaving.action is not None
    assert leaving.action.label == "大地图"
    task.saw_continent = True
    entered = navigation_step(task, city, before)
    assert entered is not None and entered.action is not None
    assert entered.action.kind == "click"
    assert entered.action.label == "协会"
    world = classify_scene(walkthrough["wt_world_lilitos"], templates)
    assert navigation_step(task, walkthrough["wt_world_lilitos"], world) is not None


def test_crystia_returns_by_the_corner_tab_not_leave(turn_in, templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("喳喳布林入侵"))
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "返阿格莱恩"
    assert result.action.label != "离开"
    assert result.action.x is not None and result.action.x > 700


def test_litrile_hidden_on_the_old_crystia_view_pans_instead_of_guessing(turn_in, templates):
    """旧的克里斯汀截图上看不见利特利尔大区，就按地标平移，不按坐标猜。"""
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    result = task.plan(turn_in["region"])
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert "利特利尔大区" in (result.action.message or "")
    assert "坐标" in (result.action.message or "")
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


def test_litrile_ocr_miss_pans_by_landmarks_then_stops(turn_in, templates):
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("受困的同伴"),
        ocr=_Ocr(),
    )
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "向下滑动地图"
    assert result.action.y2 is not None and result.action.y is not None
    assert result.action.y2 > result.action.y
    assert result.action.label != "向右滑动地图"
    assert result.action.label != "图兰顿沙漠"
    assert result.action.label != "离开"
    for _ in range(config.MAP_SWIPE_MAX):
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
    assert hidden.action.x == hidden.action.x2
    assert hidden.action.y2 is not None and hidden.action.y is not None
    assert hidden.action.y2 < hidden.action.y
    assert "浪人岬" in (hidden.action.message or "")
    right = click_or_pan_to_place(task, image, clf, LANGREN)
    assert right.action is not None
    assert right.action.kind == "swipe"
    assert right.action.label == "向左滑动地图"
    assert right.action.y == right.action.y2
    assert right.action.x2 is not None and right.action.x is not None
    assert right.action.x2 < right.action.x
    stopped = click_or_pan_to_place(task, image, clf, LANGREN)
    assert stopped.status == "halt_missing"
    assert stopped.action is not None
    assert stopped.action.kind == "halt"
    assert "右下角" in (stopped.message or "")
    assert "已停止" in (stopped.message or "")


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


CITY_BEI_SERAM = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "navigation" / "city_bei_seram.png"
)


def test_city_world_map_text_is_clicked_in_any_town(walkthrough, turn_in, templates):
    """城里只要看见「大地图」三个字就点它。北赛拉姆、莉莉托斯、图兰顿同一条规则。"""
    bei = load_bgr(CITY_BEI_SERAM)
    result = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴")).plan(bei)
    assert result.status == "continue"
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "大地图"
    assert result.action.label not in {"协会", "探险", "农场", "商店", "酒馆", "挑战任务"}
    assert result.action.match is not None
    assert result.action.match.template_id == "city_world_map_text"
    assert (result.action.x, result.action.y) == result.action.match.box.center

    for image in (walkthrough["wt_city"], turn_in["city_npc"]):
        again = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴")).plan(image)
        assert again.status == "continue"
        assert again.action is not None
        assert again.action.kind == "click"
        assert again.action.label == "大地图"
        assert again.action.label not in {"协会", "探险"}
        assert again.action.match is not None
        assert (again.action.x, again.action.y) == again.action.match.box.center


CITY_LITRILE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "navigation" / "city_litrile.png"
)


def test_target_town_clicks_association_only_after_the_continent(templates):
    """没回过大地图时，目标城也先点大地图。回来之后才点协会。别的城仍点大地图。"""
    litrile = load_bgr(CITY_LITRILE)
    fresh = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴")).plan(litrile)
    assert fresh.status == "continue"
    assert fresh.action is not None
    assert fresh.action.kind == "click"
    assert fresh.action.label == "大地图"
    assert fresh.action.label != "协会"
    assert fresh.action.match is not None
    assert (fresh.action.x, fresh.action.y) == fresh.action.match.box.center

    by_title = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    by_title.saw_continent = True
    titled = by_title.plan(litrile)
    assert titled.status == "continue"
    assert titled.action is not None
    assert titled.action.kind == "click"
    assert titled.action.label == "协会"
    assert titled.action.label not in {"商店", "酒馆", "探险", "农场", "挑战任务", "大地图"}
    assert titled.action.match is not None
    assert titled.action.match.label == "协会"
    assert (titled.action.x, titled.action.y) == titled.action.match.box.center
    assert titled.action.label != "等待大地图"

    by_pending = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    by_pending.saw_continent = True
    by_pending.pending_city = "利特利尔大区"
    pending = by_pending.plan(litrile)
    assert pending.action is not None
    assert pending.action.kind == "click"
    assert pending.action.label == "协会"

    bei = load_bgr(CITY_BEI_SERAM)
    other = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    other.saw_continent = True
    opened = other.plan(bei)
    assert opened.status == "continue"
    assert opened.action is not None
    assert opened.action.kind == "click"
    assert opened.action.label == "大地图"
    assert opened.action.label != "协会"

    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, templates_by_id(templates)["city_association"].image_bgr, 80, 220)
    followed = DailyCommissionTask(specs=templates, recipe=get_recipe("处理毒桶"))
    followed.saw_continent = True
    followed.pending_city = "莉安湖"
    entered = followed.plan(canvas)
    assert entered.action is not None
    assert entered.action.kind == "click"
    assert entered.action.label == "协会"
    assert entered.action.label != "探险"


MAP8F_HALT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "navigation"
    / "nav-test-map8f-halt.png"
)


def test_landmarks_pan_north_toward_litrile_and_the_capital(walkthrough, templates):
    """停在南边地标时往北拉。利特利尔和图兰顿、王城和浪人岬同一套，不写死方向。"""
    south_crystia = load_bgr(MAP8F_HALT)
    litrile = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴")).plan(
        south_crystia
    )
    assert litrile.status == "continue"
    assert litrile.action is not None
    assert litrile.action.kind == "swipe"
    assert litrile.action.label == "向下滑动地图"
    assert litrile.action.y is not None and litrile.action.y2 is not None
    assert litrile.action.y2 > litrile.action.y
    assert litrile.action.label != "向右滑动地图"
    assert litrile.action.label != "离开"
    assert litrile.action.label != "返阿格莱恩"
    assert "利特利尔大区" in (litrile.action.message or "")

    capital = DailyCommissionTask(specs=templates).plan(walkthrough["wt_world_south"])
    assert capital.status == "continue"
    assert capital.action is not None
    assert capital.action.kind == "swipe"
    assert capital.action.label == "向下滑动地图"
    assert capital.action.y2 is not None and capital.action.y is not None
    assert capital.action.y2 > capital.action.y
    assert capital.action.label != "离开"
    assert "王城莉莉托斯" in (capital.action.message or "")

    visible = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴")).plan(
        load_bgr(FIXTURE_CRYSTIA_WEST)
    )
    assert visible.action is not None
    assert visible.action.kind == "click"
    assert visible.action.label == "利特利尔大区"
    assert visible.action.match is not None
    assert (visible.action.x, visible.action.y) == visible.action.match.box.center


def test_target_association_room_stops_without_leaving(walkthrough, screens, templates):
    """回过大地图后，目标城的协会室内是到达，不再点离开，也不去点接收。"""
    capital = DailyCommissionTask(specs=templates)
    capital.saw_continent = True
    for image in (walkthrough["wt_association"], screens["association"]):
        arrived = capital.plan(image)
        assert arrived.action is not None
        # 到达目标协会后交给接取流程点「委托」，不再把到达当成停止，也不点离开或接收。
        assert arrived.action.kind == "click"
        assert arrived.action.label == "委托"
        assert arrived.action.label != "离开"
        assert arrived.action.label != "接收"
        assert arrived.action.x is not None
        assert arrived.action.label != "大地图"

    desert = DailyCommissionTask(specs=templates, recipe=get_recipe("请让他们安息"))
    desert.saw_continent = True
    by_id = templates_by_id(templates)
    room = np.zeros((900, 800, 3), dtype=np.uint8)
    _paste(room, by_id["association_turandon_header"].image_bgr, 20, 40)
    _paste(room, by_id["association_leave"].image_bgr, 16, 800)
    desert_room = desert.plan(room)
    assert desert_room.action is not None
    # 画布上没有「委托」按钮，交给接取流程后会停在「未找到委托」，但绝不再点离开或接收。
    assert desert_room.action.label != "离开"
    assert desert_room.action.label != "接收"
    assert desert_room.action.label != "大地图"
    assert desert_room.action.label != "已到协会"
    assert desert_room.action.kind == "halt"
    assert desert_room.action.label == "未找到委托"

    wrong = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    wrong.saw_continent = True
    leaving = wrong.plan(walkthrough["wt_association"])
    assert leaving.action is not None
    assert leaving.action.kind == "click"
    assert leaving.action.label == "离开"
    assert leaving.action.match is not None
    assert (leaving.action.x, leaving.action.y) == leaving.action.match.box.center

    shared = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(shared, by_id["association_leave"].image_bgr, 16, 620)
    unnamed = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    unnamed.saw_continent = True
    unnamed.pending_city = "利特利尔大区"
    stopped = unnamed.plan(shared)
    assert stopped.action is not None
    assert stopped.action.label != "离开"
    assert stopped.action.label != "接收"
    assert stopped.action.label != "大地图"
    assert stopped.action.label != "已到协会"
    assert stopped.action.kind == "halt"
    # 无名协会室内没有委托板/标题裁切，接取流程会安全停下，但不能离开。
    assert stopped.action.label in ("未找到委托", "标题裁切还没有")

    still_outside = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    still_outside.saw_continent = True
    city = still_outside.plan(load_bgr(CITY_LITRILE))
    assert city.action is not None
    assert city.action.kind == "click"
    assert city.action.label == "协会"
    assert city.action.match is not None
    assert (city.action.x, city.action.y) == city.action.match.box.center

    other = DailyCommissionTask(specs=templates, recipe=get_recipe("受困的同伴"))
    other.saw_continent = True
    opened = other.plan(load_bgr(CITY_BEI_SERAM))
    assert opened.action is not None
    assert opened.action.kind == "click"
    assert opened.action.label == "大地图"
    assert opened.action.label != "协会"


def test_changing_pan_direction_resets_the_swipe_count(templates):
    task = DailyCommissionTask(specs=templates)
    task.map_swipes = 7
    _arm_pan(task, "litrile:west")
    assert task.map_swipes == 0
    task.map_swipes = 7
    _arm_pan(task, "litrile:west")
    assert task.map_swipes == 7
    _arm_pan(task, "lilitos:north")
    assert task.map_swipes == 0


def test_capital_crop_without_a_title_does_not_enter_the_association(screens, templates):
    task = DailyCommissionTask(specs=templates)
    result = task.plan(screens["city"])
    assert result.scene is not Scene.CITY_LILITOS
    assert result.action is not None
    assert result.action.kind != "click"
    assert result.action.label != "协会"
