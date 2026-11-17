"""大地图位置图谱：城市属于哪片区域，以及记录的点击位置。"""

from __future__ import annotations

from pathlib import Path

from src.tasks.locations import (
    AGLAEN,
    BEI_SERAM,
    CRYSTIA,
    LANGREN,
    LIANHU,
    LILITOS,
    NAN_SERAM,
    NAR,
    PLACES,
    PLACES_BY_NAME,
    REF_HEIGHT,
    REF_WIDTH,
    SAINT_CASARE,
    TURANDON,
    places_in,
    scale_point,
)
from src.tasks.recipes import get_recipe
from src.vision.image import load_bgr
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Scene
from tests.conftest import ROOT


def test_recipes_point_at_recorded_places():
    zhazha = get_recipe("喳喳布林入侵")
    assert zhazha.location is LILITOS
    assert zhazha.location.region is AGLAEN
    assert zhazha.location.name == "王城莉莉托斯"

    hatred = get_recipe("仇恨会令我成长")
    assert hatred.location is TURANDON
    assert hatred.location.region is CRYSTIA
    assert hatred.location.name == "图兰顿沙漠"

    eager = get_recipe("“热情”的冒险者")
    assert eager.location is TURANDON


def test_every_visible_place_is_recorded():
    aglaen = {place.name for place in places_in(AGLAEN)}
    assert aglaen == {"王城莉莉托斯", "莉安湖", "北赛拉姆", "南赛拉姆", "浪人岬"}
    crystia = {place.name for place in places_in(CRYSTIA)}
    assert crystia == {"图兰顿沙漠", "纳尔本", "圣卡萨雷"}
    assert {place.name for place in PLACES} == aglaen | crystia
    assert LILITOS.has_city_route
    assert TURANDON.has_city_route
    assert not LIANHU.has_city_route
    assert not NAR.has_city_route
    assert PLACES_BY_NAME["图兰顿沙漠"] is TURANDON


def test_scale_point_keeps_1080x1920():
    image = load_bgr(ROOT / TURANDON.map_click_source)
    assert image.shape[1] == REF_WIDTH
    assert image.shape[0] == REF_HEIGHT
    assert scale_point(image, 475, 1020) == (475, 1020)


def _assert_recorded_click(templates, place, *, max_delta: int = 25):
    assert place.map_label_template
    assert place.map_click is not None
    assert place.map_click_source
    image = load_bgr(ROOT / place.map_click_source)
    by_id = templates_by_id(templates)
    match = find_template(image, by_id[place.map_label_template])
    assert match is not None, f"{place.name} 在 {place.map_click_source} 上没有匹配到模板"
    cx, cy = match.box.center
    rec_x, rec_y = place.map_click
    assert abs(cx - rec_x) <= max_delta, f"{place.name} x {cx} vs {rec_x}"
    assert abs(cy - rec_y) <= max_delta, f"{place.name} y {cy} vs {rec_y}"


def test_recorded_clicks_match_templates(templates):
    for place in (
        LILITOS,
        LIANHU,
        BEI_SERAM,
        NAN_SERAM,
        LANGREN,
        TURANDON,
        NAR,
        SAINT_CASARE,
    ):
        _assert_recorded_click(templates, place)


def test_turandon_and_lilitos_belong_to_expected_regions():
    assert TURANDON.region.name == "克里斯汀"
    assert TURANDON.city_scene is Scene.CITY_TURANDON
    assert TURANDON.map_click == (475, 1020)
    assert LILITOS.region.name == "阿格莱恩"
    assert LILITOS.city_scene is Scene.CITY_LILITOS
    assert LILITOS.map_click == (660, 648)


def test_bei_seram_template_also_matches_south_view(templates):
    image = load_bgr(ROOT / "tests/fixtures/walkthrough/01_world_south.png")
    match = find_template(image, templates_by_id(templates)["world_bei_seram"])
    assert match is not None
    # 南边视野里北赛拉姆更靠上，不能再用王城那张图的记录坐标。
    assert match.box.center[1] < 600
