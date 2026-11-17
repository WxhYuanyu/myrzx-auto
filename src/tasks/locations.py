"""大地图位置图谱。

记录每一片区域地图，以及其上已经能认出的地点：这座城或这个地点属于哪一片区域、
在哪张 1080×1920 实走截图上、要点哪里。配方只引用这里的地点，后续给其他地区
的委托规划路线时，先补这条记录，再补城内协会和委托板。

地图滑动后标签会跟着移动。规划时先认地名；看不见就平移，直到名称进入画面再点。
记录坐标只说明某张实走截图上标签曾经在哪，不能在标签不在画面上时拿来猜点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.vision.types import Scene

REF_WIDTH = 1080
REF_HEIGHT = 1920


def scale_point(
    image: np.ndarray,
    x: int,
    y: int,
    *,
    ref_w: int = REF_WIDTH,
    ref_h: int = REF_HEIGHT,
) -> tuple[int, int]:
    """把 1080×1920 上记录的点缩放到当前截图像素。"""
    height, width = image.shape[:2]
    return int(round(x * width / ref_w)), int(round(y * height / ref_h))


@dataclass(frozen=True)
class Region:
    """一片区域大地图，例如阿格莱恩、克里斯汀。"""

    id: str
    name: str
    banner_template: str
    scene: Scene
    # 在「另一片」区域地图上，点这个页签可以进来。
    inbound_tab_template: str | None = None
    inbound_tab_label: str | None = None
    inbound_tab_click: tuple[int, int] | None = None
    inbound_tab_source: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class MapPlace:
    """区域地图上的一座城或一个地点。"""

    id: str
    name: str
    region: Region
    map_label_template: str | None = None
    map_label_fallback: str | None = None
    map_click: tuple[int, int] | None = None
    map_click_source: str | None = None
    map_click_box: tuple[int, int, int, int] | None = None
    city_scene: Scene | None = None
    association_header: str | None = None
    board_title: str | None = None
    association_templates: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    @property
    def has_city_route(self) -> bool:
        """已经走过城内协会和委托板，可以按这条路接取委托。"""
        return self.city_scene is not None


AGLAEN = Region(
    id="aglaen",
    name="阿格莱恩",
    banner_template="world_aglaen",
    scene=Scene.WORLD_MAP,
    inbound_tab_template="region_tab_aglaen",
    inbound_tab_label="返阿格莱恩",
    inbound_tab_click=(887, 1815),
    inbound_tab_source="tests/fixtures/turn_in/01_region_crystia.png",
    notes=(
        "左上蓝色横幅「阿格莱恩 / Allgreen Independent Kingdom」。"
        "去克里斯汀时，先把地图滑到南边的「浪人岬」，再手指从左向右滑，"
        "把左边被切掉的「前往克里斯汀」整块拉出来再点；"
        "这个页签不是常驻底栏，停在王城附近时看不见。"
        "不要用左下「离开」切换区域：停在当前城市上时，离开会回城。"
    ),
)

CRYSTIA = Region(
    id="crystia",
    name="克里斯汀",
    banner_template="world_crystia",
    scene=Scene.REGION_CRYSTIA,
    inbound_tab_template="region_tab_crystia",
    inbound_tab_label="前往克里斯汀",
    inbound_tab_click=(214, 1637),
    inbound_tab_source="tests/fixtures/walkthrough/01_world_south.png",
    notes=(
        "左上横幅「克里斯汀 / The United Realms of Crystia」。"
        "右下「返阿格莱恩」可回到阿格莱恩。左下「离开」在这张图上不要用来切区域。"
    ),
)

LILITOS = MapPlace(
    id="lilitos",
    name="王城莉莉托斯",
    region=AGLAEN,
    map_label_template="world_lilitos_full",
    map_label_fallback="world_lilitos",
    map_click=(660, 648),
    map_click_source="tests/fixtures/walkthrough/02_world_lilitos.png",
    map_click_box=(515, 615, 290, 67),
    city_scene=Scene.CITY_LILITOS,
    association_header="association_lilitos_header",
    board_title="commission_center_title",
    association_templates=("city_association",),
    notes="阿格莱恩的王城。协会标题是「莉莉托斯协会」，委托板是「驯养师协会委托中心」。",
)

LIANHU = MapPlace(
    id="lianhu",
    name="莉安湖",
    region=AGLAEN,
    map_label_template="world_lianhu",
    map_click=(875, 1121),
    map_click_source="tests/fixtures/walkthrough/02_world_lilitos.png",
    map_click_box=(790, 1088, 170, 67),
    notes="阿格莱恩地图上王城东南方的湖边地点。城内路线尚未走查。",
)

BEI_SERAM = MapPlace(
    id="bei_seram",
    name="北赛拉姆",
    region=AGLAEN,
    map_label_template="world_bei_seram",
    map_click=(136, 1311),
    map_click_source="tests/fixtures/walkthrough/02_world_lilitos.png",
    map_click_box=(18, 1278, 237, 67),
    notes=(
        "阿格莱恩地图上王城西南的地点。记录坐标来自能看见王城的那张图；"
        "滑到南边后标签位置会变。城内路线尚未走查。"
    ),
)

NAN_SERAM = MapPlace(
    id="nan_seram",
    name="南赛拉姆",
    region=AGLAEN,
    map_label_template="world_nan_seram",
    map_click=(630, 880),
    map_click_source="tests/fixtures/walkthrough/01_world_south.png",
    map_click_box=(535, 850, 190, 60),
    notes=(
        "阿格莱恩南部地点。看见它却看不见王城时，应向下滑动地图以露出北边的王城。"
        "在 02_world_lilitos.png 里它会出现在更靠下的位置。城内路线尚未走查。"
    ),
)

LANGREN = MapPlace(
    id="langren",
    name="浪人岬",
    region=AGLAEN,
    map_label_template="world_langren",
    map_click=(825, 1580),
    map_click_source="tests/fixtures/walkthrough/01_world_south.png",
    map_click_box=(720, 1545, 210, 70),
    notes="阿格莱恩南端海边，靠近「前往克里斯汀」页签。城内路线尚未走查。",
)

TURANDON = MapPlace(
    id="turandon",
    name="图兰顿沙漠",
    region=CRYSTIA,
    map_label_template="region_turandon",
    map_click=(475, 1020),
    map_click_source="tests/fixtures/turn_in/01_region_crystia.png",
    map_click_box=(258, 984, 434, 72),
    city_scene=Scene.CITY_TURANDON,
    association_header="association_turandon_header",
    board_title="commission_adventurer_title",
    association_templates=("city_turandon_association", "city_association"),
    notes="克里斯汀西部的边境都市。协会标题是「图兰顿沙漠协会」，委托板是「冒险者协会委托中心」。",
)

NAR = MapPlace(
    id="nar",
    name="纳尔本",
    region=CRYSTIA,
    map_label_template="region_nar",
    map_click=(990, 537),
    map_click_source="tests/fixtures/turn_in/01_region_crystia.png",
    map_click_box=(900, 500, 180, 75),
    notes=(
        "克里斯汀地图右上的地点。现有截图右侧被裁切，截图可见「纳尔」，正确全称是「纳尔本」；"
        "完整地名若更长，待补图后再改。城内路线尚未走查。"
    ),
)

SAINT_CASARE = MapPlace(
    id="st_casare",
    name="圣卡萨雷斯",
    region=CRYSTIA,
    map_label_template="region_st_casare",
    map_click=(970, 1225),
    map_click_source="tests/fixtures/turn_in/01_region_crystia.png",
    map_click_box=(860, 1188, 220, 74),
    notes=(
        "克里斯汀地图右侧的地点。正确全称是「圣卡萨雷斯」。"
        "现有截图右侧略裁切，飘带上只露出「圣卡萨雷」。城内路线尚未走查。"
    ),
)

LITRILE = MapPlace(
    id="litrile",
    name="利特利尔大区",
    region=CRYSTIA,
    notes=(
        "克里斯汀西侧、粉树一带。还没有实走截图，因此没有地名模板，也不记录坐标。"
        "在克里斯汀地图上要往西平移，看见「利特利尔大区」再点；读不出名字就停。"
    ),
)

REGIONS: dict[str, Region] = {
    AGLAEN.id: AGLAEN,
    CRYSTIA.id: CRYSTIA,
}

PLACES: tuple[MapPlace, ...] = (
    LILITOS,
    LIANHU,
    BEI_SERAM,
    NAN_SERAM,
    LANGREN,
    TURANDON,
    NAR,
    SAINT_CASARE,
    LITRILE,
)

PLACES_BY_ID: dict[str, MapPlace] = {place.id: place for place in PLACES}
PLACES_BY_NAME: dict[str, MapPlace] = {place.name: place for place in PLACES}

# 利特利尔大区属于克里斯汀，但没有实走截图。不要补坐标或假模板。


def places_in(region: Region) -> tuple[MapPlace, ...]:
    """某一片区域地图上已经记录的地点，按图谱顺序。"""
    return tuple(place for place in PLACES if place.region.id == region.id)
