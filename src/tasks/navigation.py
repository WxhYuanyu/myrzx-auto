"""先退回大区地图，再在大区地图上进城。

退回时先不管当前是不是目标城，直到看见「阿格莱恩」或「克里斯汀」：
- 看到「回程」就点「回程」。不为「滨海小镇」这类地点做标题模板。
  不点「雨林之底→」「冥土之国→」「←深海之城」这类传送门，也不点关卡或「扫荡」。
- 看到左下「离开」就点它，不限于选关页（结晶矿洞这类页面也一样）。不点「扫荡」「兑换」「战阵」或矿层入口。
  已经在阿格莱恩或克里斯汀大地图上时，不用「离开」换区。
- 城里点「大地图」，不点本城的「协会」或「探险」。
- 已经进了目标城的协会室内（共用的「委托」、协会「离开」或标题里的「协会」）就停。
  不再点「离开」出去，也不把这一步交给委托板去点「接收」。
认不出退回按钮就停，不编造点击。

看见大区地图之后再判断目标在哪一边：
- 人在阿格莱恩、目标在克里斯汀：先手指上划到南边的「浪人岬」。
  「前往克里斯汀」常常只在左边缘露出右半截，还要手指从左向右滑，
  把左边的内容拉进画面，整块旗帜对上再点。不点左下「离开」。
- 人在克里斯汀、目标在阿格莱恩：点右下「返阿格莱恩」。左下「离开」只回当前城。
- 同一张大区地图上地名可能在屏外。用已经看见的地标和布局判断往哪边拉，
  看见目标地名再点，不按记录坐标猜。没有模板也读不出名字时停住。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from src import config
from src.tasks.base import PlannedAction, StepResult
from src.tasks.locations import PLACES, REGIONS, MapPlace, Region, places_in
from src.tasks.phase import Phase
from src.tasks import verbs
from src.vision.ocr import NullOcrProvider
from src.vision.types import Match, Scene

# 传送门文案带箭头，绝不是退回按钮。
PORTAL_EXAMPLES = ("雨林之底→", "冥土之国→", "←深海之城")

_STAGE_PREP_RE = re.compile(r"\d+-\d+|近郊|巡逻走廊|选关|副本")

_SUBTITLE_CITY = {
    "阿格莱恩独立王国首都": "王城莉莉托斯",
    "克里斯汀西部的边境都市": "图兰顿沙漠",
}

# 模板 id → (标题, 副标题, 种类)。种类不靠全屏截图，只靠这块标题。
_HEADING_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    ("desert_stage_header", "图兰顿沙漠地区", "", "region_stage"),
    ("stage_9_7_title", "巡逻走廊 9-7", "", "stage_prep"),
    ("stage_1_3_title", "莉莉托斯近郊 1-3", "", "stage_prep"),
    ("city_turandon_title", "图兰顿沙漠", "克里斯汀西部的边境都市", "city"),
    ("city_capital_subtitle", "王城莉莉托斯", "阿格莱恩独立王国首都", "city"),
    ("world_crystia", "克里斯汀", "The United Realms of Crystia", "continent"),
    ("world_aglaen", "阿格莱恩", "Allgreen Independent Kingdom", "continent"),
)

_KIND_RANK = {
    "stage_prep": 0,
    "region_stage": 1,
    "portal": 1,
    "nested": 2,
    "city": 3,
    "continent": 4,
}

_QUEST_SCENES = frozenset(
    {
        Scene.ASSOCIATION,
        Scene.COMMISSION_LIST,
        Scene.QUEST_DETAIL,
        Scene.QUEST_LOG,
        Scene.LOOT_REWARD,
        Scene.BATTLE,
        Scene.VICTORY,
        Scene.STORY_DIALOG,
        Scene.STAGE_EVENT,
    }
)

_PREP_SCENES = frozenset({Scene.STAGE_1_3, Scene.STAGE_9_7, Scene.STAGE_MAP})

PLACE_TITLES = frozenset(place.name for place in PLACES) | {"王城莉莉托斯", "莉莉托斯"}


@dataclass(frozen=True)
class Heading:
    title: str
    subtitle: str
    kind: str  # continent / city / region_stage / nested / stage_prep / portal


def is_portal_text(text: str) -> bool:
    """传送门标签带箭头，例如「雨林之底→」「←深海之城」。"""
    stripped = text.strip()
    if not stripped:
        return False
    return any(mark in stripped for mark in ("→", "←", "->", "<-"))


def normalize_place_title(title: str) -> str:
    """城内木牌有时只写「莉莉托斯」。近郊、协会、地区不算这座城。"""
    title = title.strip()
    if any(token in title for token in ("近郊", "协会", "地区")):
        return title
    if title == "莉莉托斯":
        return "王城莉莉托斯"
    return title


def kind_from_title(title: str, subtitle: str = "") -> str:
    """由标题栏文字判断这一页是大区、城、地区关卡、嵌套区域还是选关。"""
    title = title.strip()
    subtitle = subtitle.strip()
    if is_portal_text(title):
        return "portal"
    title = normalize_place_title(title)
    if title in {"阿格莱恩", "克里斯汀"}:
        return "continent"
    if title.endswith("地区"):
        return "region_stage"
    if _STAGE_PREP_RE.search(title):
        return "stage_prep"
    if title in PLACE_TITLES or subtitle in _SUBTITLE_CITY:
        return "city"
    if title:
        return "nested"
    if subtitle in _SUBTITLE_CITY:
        return "city"
    return "unknown"


def resolve_heading(title: str, subtitle: str = "") -> Heading | None:
    kind = kind_from_title(title, subtitle)
    if kind == "unknown":
        return None
    if kind == "portal":
        return Heading(title.strip(), subtitle.strip(), "portal")
    title = normalize_place_title(title)
    if kind == "city":
        if title not in PLACE_TITLES and subtitle in _SUBTITLE_CITY:
            title = _SUBTITLE_CITY[subtitle]
        elif not title and subtitle in _SUBTITLE_CITY:
            title = _SUBTITLE_CITY[subtitle]
    return Heading(title, subtitle.strip(), kind)


def _reader_heading(task: Any, image: np.ndarray) -> Heading | None:
    reader = getattr(task, "title_reader", None)
    if reader is None:
        ocr = getattr(task, "ocr", None)
        reader = getattr(ocr, "read_title", None)
    if reader is None:
        return None
    got = reader(image) if callable(reader) else reader.read_title(image)
    if not got:
        return None
    if isinstance(got, tuple):
        title = str(got[0] or "")
        subtitle = str(got[1] or "") if len(got) > 1 else ""
    else:
        title, subtitle = str(got), ""
    return resolve_heading(title, subtitle)


def read_heading(task: Any, image: np.ndarray) -> Heading | None:
    """左上角标题。高分模板优先；没有模板时用标题读取 / OCR。"""
    found: list[tuple[float, Heading]] = []
    for template_id, title, subtitle, kind in _HEADING_TEMPLATES:
        if template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is None:
            continue
        found.append((match.score, Heading(title, subtitle, kind)))
    best: Heading | None = None
    best_score = 0.0
    if found:
        found.sort(key=lambda item: (-item[0], _KIND_RANK.get(item[1].kind, 9)))
        best_score, best = found[0]
        if best_score >= 0.90:
            return best
    reader = _reader_heading(task, image)
    if reader is not None:
        return reader
    return best


def _town_name_from_titles(task: Any, image: np.ndarray) -> str | None:
    """左上木牌上的地名。每座已有木牌裁切的城都走这里，不看整张城的背景。"""
    best_name = None
    best_score = 0.0
    for place in PLACES:
        template_id = place.city_title_template
        if not template_id or template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is not None and match.score > best_score:
            best_name = place.name
            best_score = match.score
    return best_name


def confirmed_city_name(task: Any, image: np.ndarray, clf: Any) -> str | None:
    """当前城名。只认标题栏或已经由标题模板定下的城市场景，不认「协会」。"""
    named = _town_name_from_titles(task, image)
    if named:
        return named
    heading = read_heading(task, image)
    if heading is not None and heading.kind == "city":
        return heading.title
    if clf.scene is Scene.CITY_TURANDON:
        return "图兰顿沙漠"
    if clf.scene is Scene.CITY_LILITOS:
        return "王城莉莉托斯"
    return None


CITY_WIDGETS = (
    "city_association",
    "city_turandon_association",
    "city_world_map",
    "city_world_map_text",
    "city_explore",
)


def in_city(task: Any, image: np.ndarray) -> bool:
    """协会、大地图或探险这类共用城镇控件出现，说明已经进了城，不是大地图过渡。"""
    return verbs.best_of(task, image, CITY_WIDGETS) is not None


def city_is_target(task: Any, image: np.ndarray, clf: Any) -> bool:
    place = getattr(task.recipe, "location", None)
    if place is None:
        return False
    named = confirmed_city_name(task, image, clf)
    if named and named != place.name:
        return False
    if named == place.name:
        return True
    # 刚在区域地图上点过这座城，下一张城内图就按它处理。标题若写成别的城则上面已经否掉。
    return in_city(task, image) and getattr(task, "pending_city", None) == place.name


def _halt(clf: Any, scene: Scene, label: str, message: str) -> StepResult:
    return StepResult(
        scene=scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(kind="halt", label=label, message=message),
        status="halt_missing",
        message=message,
    )


def _portal_sentence() -> str:
    names = "」「".join(PORTAL_EXAMPLES)
    return f"不会点「{names}」这类传送门。"


def click_return(task: Any, image: np.ndarray, clf: Any, heading: Heading) -> StepResult:
    """地区图或嵌套区域：只点「回程」。"""
    scene = clf.scene
    if heading.kind == "nested":
        message = (
            f"标题是「{heading.title}」。点「回程」回到上一级地区。"
            + _portal_sentence()
        )
    else:
        message = (
            f"标题是「{heading.title}」。点「回程」回到城内。"
            + _portal_sentence()
            + "也不会改点关卡。"
        )
    match = task._require(image, "stage_return")
    if match is None:
        missing = (
            f"标题是「{heading.title}」，应点「回程」，但没有匹配到「回程」。"
            + _portal_sentence()
        )
        return _halt(clf, scene, "未找到回程", missing)
    return task._click_result(scene, clf, list(clf.matches), match, message)


def click_unlisted_return(task: Any, image: np.ndarray, clf: Any) -> StepResult | None:
    """还没到目标城时，未录入的嵌套地图只要有「回程」就点。

    「滨海小镇」这类地点不单独做标题模板。匹配的是按钮本身，不是传送门或「扫荡」。
    """
    match = task._require(image, "stage_return")
    if match is None or match.label != "回程" or is_portal_text(match.label):
        return None
    message = (
        "先退回大地图，直到看见「阿格莱恩」或「克里斯汀」。"
        "这一页有「回程」就点它，不论当前是不是目标城，也不依赖地点标题模板。"
        + _portal_sentence()
        + "也不会点关卡或「扫荡」。"
    )
    return task._click_result(clf.scene, clf, list(clf.matches), match, message)


def _target(task: Any) -> MapPlace | None:
    return getattr(task.recipe, "location", None)


def _city_name(heading: Heading | None, clf: Any) -> str | None:
    if heading is not None and heading.kind == "city":
        return heading.title
    if clf.scene is Scene.CITY_TURANDON:
        return "图兰顿沙漠"
    if clf.scene is Scene.CITY_LILITOS:
        return "王城莉莉托斯"
    return None


@dataclass(frozen=True)
class RegionSight:
    """当前画面属于哪一片大区，以及是哪条线索认出来的。"""

    region: Region
    match: Match
    clue: str  # banner / place / tab


def _map_showing_inbound_tab(destination: Region) -> Region | None:
    """进入 destination 的页签画在另一片大区上。两片时就是剩下的那片。"""
    others = [region for region in REGIONS.values() if region.id != destination.id]
    if len(others) == 1:
        return others[0]
    return None


def recognize_region(task: Any, image: np.ndarray) -> RegionSight | None:
    """认当前大区。标题、对面的区域页签、本区地名标签，任何一条稳定线索都算。

    看到「返阿格莱恩」说明人在克里斯汀；看到「前往克里斯汀」说明人在阿格莱恩。
    以后再加新区，仍走标题、页签和 places_in 里的地名，不另写一套。
    """
    sights: list[RegionSight] = []
    for region in REGIONS.values():
        if region.banner_template in task.by_id:
            banner = task._require(image, region.banner_template)
            if banner is not None:
                sights.append(RegionSight(region, banner, "banner"))
        for place in places_in(region):
            label = find_place_label(task, image, place)
            if label is not None:
                sights.append(RegionSight(region, label, "place"))
        if not region.inbound_tab_template or region.inbound_tab_template not in task.by_id:
            continue
        tab = task._require(image, region.inbound_tab_template)
        host = _map_showing_inbound_tab(region)
        if tab is not None and host is not None:
            sights.append(RegionSight(host, tab, "tab"))
    if not sights:
        return None
    best: dict[str, RegionSight] = {}
    for sight in sights:
        current = best.get(sight.region.id)
        if current is None or sight.match.score > current.match.score:
            best[sight.region.id] = sight
    return max(best.values(), key=lambda sight: sight.match.score)


def _on_continent(heading: Heading | None, clf: Any) -> bool:
    if clf.scene in {Scene.WORLD_MAP, Scene.REGION_CRYSTIA}:
        return True
    return heading is not None and heading.kind == "continent"


def _needs_map(task: Any) -> bool:
    """还没看见过大区地图。接取前一律先退回去，哪怕人已经在目标城。"""
    return task.phase is Phase.ACCEPT and not getattr(task, "saw_continent", False)


def _leave_stage(task: Any, image: np.ndarray, clf: Any) -> StepResult:
    return verbs.leave_stage_select(
        task,
        image,
        clf,
        clf.scene,
        "选关或副本准备页点左下「离开」。不会点「扫荡」。",
    )


def _is_stage_prep(heading: Heading | None, clf: Any) -> bool:
    if clf.scene in _PREP_SCENES:
        return True
    return heading is not None and heading.kind == "stage_prep"


def _halt_unrecognized_exit(clf: Any) -> StepResult:
    missing = (
        "还没看见「阿格莱恩」或「克里斯汀」。"
        "这一页没有「回程」，也没有左下「离开」或城里的「大地图」。"
        "认不出怎么退回，不会编造点击，也不会点传送门或「扫荡」。"
    )
    return _halt(clf, clf.scene, "认不出退回", missing)


CITY_WORLD_MAP_BUTTONS = (
    "city_world_map",
    "city_world_map_text",
    "city_world_map_text_alt",
)


def find_city_world_map(task: Any, image: np.ndarray) -> Match | None:
    """城里的「大地图」三个字。王城木牌和各城共用的紧裁文字，认到任一即可。"""
    return verbs.best_of(task, image, CITY_WORLD_MAP_BUTTONS)


def _click_corner_leave(task: Any, image: np.ndarray, clf: Any) -> StepResult | None:
    """还没回到大地图时，左下「离开」就点。不限选关页，也不点屏幕中部的按钮。"""
    match = verbs.best_of(task, image, ("stage_leave", "association_leave"))
    if match is None or match.label != "离开" or is_portal_text(match.label):
        return None
    x, y = task._click_point(match)
    width, height = image.shape[1], image.shape[0]
    sweep_y = int(round(height * 1750 / 1920))
    if x > width * 0.4 or (y >= sweep_y and x > width * 0.3):
        return None
    message = (
        "还没看见「阿格莱恩」或「克里斯汀」。点左下「离开」退回，不限于选关页。"
        "不会点「扫荡」「兑换」「战阵」或矿层入口。"
    )
    return task._click_result(clf.scene, clf, list(clf.matches), match, message)


def _return_until_continent(
    task: Any, image: np.ndarray, clf: Any, heading: Heading | None
) -> StepResult:
    """先退回大地图。不根据地点标题决定要不要退。"""
    if heading is not None and heading.kind in {"region_stage", "nested"}:
        return click_return(task, image, clf, heading)
    if clf.scene is Scene.STAGE_DESERT:
        return click_return(
            task,
            image,
            clf,
            Heading("图兰顿沙漠地区", "", "region_stage"),
        )
    backed = click_unlisted_return(task, image, clf)
    if backed is not None:
        return backed
    if _is_stage_prep(heading, clf):
        return _leave_stage(task, image, clf)
    left = _click_corner_leave(task, image, clf)
    if left is not None:
        return left
    city = _city_name(heading, clf)
    if city is not None or clf.scene in {Scene.CITY_LILITOS, Scene.CITY_TURANDON}:
        return task._plan_open_world_map(
            image, clf, clf.scene, here=city, returning=True
        )
    if find_city_world_map(task, image) is not None:
        return task._plan_open_world_map(
            image, clf, clf.scene, here=city, returning=True
        )
    if heading is not None and heading.kind == "portal":
        missing = (
            f"读到「{heading.title}」，这是传送门而不是地点标题。"
            + _portal_sentence()
            + "要退回时只点「回程」。"
        )
        return _halt(clf, clf.scene, "拒绝传送门", missing)
    return _halt_unrecognized_exit(clf)


def _quest_widget_visible(task: Any, image: np.ndarray) -> bool:
    """画面上已经有委托卡片、NPC 或详情，交给委托流程，不当成大地图过渡。"""
    recipe = task.recipe
    candidates = (
        getattr(recipe, "card_template", None),
        getattr(recipe, "log_template", None),
        getattr(recipe, "npc_template", None),
        "association_commission",
        "association_commission_turandon",
        "quest_detail_title",
    )
    for template_id in candidates:
        if template_id and template_id in task.by_id and task._require(image, template_id):
            return True
    return False


def _click_city_association(task: Any, image: np.ndarray, clf: Any, place_name: str) -> StepResult:
    match = verbs.best_of(task, image, ("city_association", "city_turandon_association"))
    if match is None or match.label != "协会":
        missing = (
            f"已确认在「{place_name}」，但没有匹配到「协会」。"
            "不会点商店、酒馆、探险、农场、挑战任务或对话气泡。"
        )
        return _halt(clf, clf.scene, "未找到协会", missing)
    message = (
        f"已进入「{place_name}」。点「协会」。"
        "不点商店、酒馆、探险、农场、挑战任务或对话气泡。"
    )
    return task._click_result(clf.scene, clf, list(clf.matches), match, message)


def _settle_unrecognized_exit(
    task: Any, image: np.ndarray, clf: Any, exiting: StepResult
) -> StepResult | None:
    """退回按钮没对上时：已经在城里就按目标城处理，不要空等大地图。"""
    unrecognized = (
        exiting.status == "halt_missing"
        and exiting.action is not None
        and exiting.action.label == "认不出退回"
    )
    if unrecognized and in_city(task, image):
        # 还没回过大地图时，目标城也先出城，这里不点「协会」。
        if getattr(task, "saw_continent", False) and city_is_target(task, image, clf):
            place = _target(task)
            return _click_city_association(
                task, image, clf, place.name if place is not None else "目标城"
            )
        return task._plan_open_world_map(
            image,
            clf,
            clf.scene,
            here=confirmed_city_name(task, image, clf),
            returning=True,
        )
    if unrecognized and getattr(task, "saw_continent", False):
        if _quest_widget_visible(task, image):
            return None
        return _wait_for_region(clf)
    if unrecognized and task.phase is not Phase.ACCEPT:
        return None
    return exiting


def _wait_for_region(clf: Any) -> StepResult:
    """切换大区后的过渡帧。先等，不要交给委托板。"""
    message = (
        "这一帧还认不出是「阿格莱恩」还是「克里斯汀」，也还没进入目标城。"
        "先等下一帧继续导航，不会按委托卡片停下，也不会编造点击。"
    )
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(kind="wait", label="等待大地图", message=message),
        status="skip_unknown",
        message=message,
    )


# 协会室内的共用标志。不是某一座城的整张室内底图，也不包括城门口的「协会」招牌。
_ASSOCIATION_ROOM_SIGNS = (
    "association_commission",
    "association_commission_turandon",
    "association_leave",
    "association_lilitos_header",
    "association_turandon_header",
)


def _template_hit(task: Any, image: np.ndarray, template_id: str) -> bool:
    return template_id in task.by_id and task._require(image, template_id) is not None


def _any_template(task: Any, image: np.ndarray, template_ids: tuple[str, ...]) -> bool:
    return any(_template_hit(task, image, template_id) for template_id in template_ids)


def _raw_title_text(task: Any, image: np.ndarray) -> str:
    reader = getattr(task, "title_reader", None)
    if reader is None:
        ocr = getattr(task, "ocr", None)
        reader = getattr(ocr, "read_title", None)
    if not callable(reader):
        return ""
    got = reader(image)
    if not got:
        return ""
    if isinstance(got, tuple):
        return str(got[0] or "")
    return str(got)


def _city_in_association_title(title: str) -> str | None:
    """标题写着某座城的协会，例如「莉莉托斯协会」。委托中心列表不算室内。"""
    if "协会" not in title or "委托中心" in title:
        return None
    for place in PLACES:
        if place.name in title:
            return place.name
        short = place.name.removeprefix("王城").removesuffix("大区")
        if short and short != place.name and short in title:
            return place.name
    return None


def _whose_association(task: Any, image: np.ndarray) -> str | None:
    """专属标题能确定是哪座城的协会。认不出就返回 None，不靠整张室内底图。"""
    best_name: str | None = None
    best_score = 0.0
    for place in PLACES:
        header = place.association_header
        if not header or not _template_hit(task, image, header):
            continue
        match = task._require(image, header)
        if match is not None and match.score > best_score:
            best_name = place.name
            best_score = match.score
    if best_name is not None:
        return best_name
    return _city_in_association_title(_raw_title_text(task, image))


def _in_target_association_room(task: Any, image: np.ndarray) -> bool:
    """回过大地图之后，已经站在目标城的协会室内。两边大区同一套。"""
    place = _target(task)
    if place is None or task.phase is not Phase.ACCEPT:
        return False
    if not getattr(task, "saw_continent", False):
        return False
    title = _raw_title_text(task, image)
    in_room = _any_template(task, image, _ASSOCIATION_ROOM_SIGNS) or (
        "协会" in title and "委托中心" not in title
    )
    if not in_room:
        return False
    whose = _whose_association(task, image)
    if whose is not None:
        return whose == place.name
    pending = getattr(task, "pending_city", None)
    if pending is not None and pending != place.name:
        return False
    # 标题或室内「委托」已经说明在协会里，又认不出是别的城，就当作到达。
    # 只有左下「离开」时，必须是刚点进的这座城，避免把矿洞或选关页当成协会。
    has_commission = _any_template(
        task, image, ("association_commission", "association_commission_turandon")
    )
    has_title = "协会" in title and "委托中心" not in title
    if has_commission or has_title:
        return True
    return _template_hit(task, image, "association_leave") and pending == place.name


def _arrived_at_association(clf: Any, place_name: str) -> StepResult:
    message = (
        f"已经进入「{place_name}」的协会。导航到此结束，"
        "不再点「离开」出协会，也不点委托板上的「接收」。"
    )
    return StepResult(
        scene=Scene.ASSOCIATION,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(kind="halt", label="已到协会", message=message),
        status="halt_missing",
        message=message,
    )


def step(task: Any, image: np.ndarray, clf: Any) -> StepResult | None:
    """导航一步。回过大地图并进入目标协会后停住，不把这一步交给委托板。"""
    if clf.scene in _QUEST_SCENES and clf.scene is not Scene.ASSOCIATION:
        return None
    if task.phase is not Phase.ACCEPT and (
        clf.scene in _PREP_SCENES or clf.scene is Scene.STAGE_DESERT
    ):
        return None
    heading = read_heading(task, image)
    if recognize_region(task, image) is not None or _on_continent(heading, clf):
        task.saw_continent = True
        return task._plan_region_to_place(image, clf)
    saw = getattr(task, "saw_continent", False)
    if task.phase is Phase.ACCEPT and saw and _in_target_association_room(task, image):
        place = _target(task)
        return _arrived_at_association(clf, place.name if place is not None else "目标城")
    if clf.scene is Scene.ASSOCIATION:
        return None
    if task.phase is Phase.ACCEPT and saw and city_is_target(task, image, clf):
        place = _target(task)
        return _click_city_association(
            task, image, clf, place.name if place is not None else "目标城"
        )
    if task.phase is Phase.ACCEPT and not saw:
        return _settle_unrecognized_exit(
            task, image, clf, _return_until_continent(task, image, clf, heading)
        )
    if city_is_target(task, image, clf):
        return None
    return _settle_unrecognized_exit(
        task, image, clf, _return_until_continent(task, image, clf, heading)
    )


def _usable_ocr(task: Any) -> bool:
    ocr = getattr(task, "ocr", None)
    return ocr is not None and not isinstance(ocr, NullOcrProvider)


def can_recognize_name(task: Any, place: MapPlace) -> bool:
    for template_id in (place.map_label_template, place.map_label_fallback):
        if template_id and template_id in task.by_id:
            return True
    return _usable_ocr(task)


def find_place_label(task: Any, image: np.ndarray, place: MapPlace) -> Match | None:
    ids = [
        template_id
        for template_id in (place.map_label_template, place.map_label_fallback)
        if template_id
    ]
    found = task._require_best(image, *ids) if ids else None
    if found is not None and not is_portal_text(found.label):
        return found
    if not _usable_ocr(task):
        return None
    hits = [
        hit
        for hit in task.ocr.find_text(image, place.name)
        if not is_portal_text(hit.label)
    ]
    if not hits:
        return None
    return max(hits, key=lambda item: item.score)


def _visible_landmarks(task: Any, image: np.ndarray, place: MapPlace) -> list[MapPlace]:
    """当前大区上已经认出来、且不是目标本身的地名。"""
    found: list[MapPlace] = []
    for other in places_in(place.region):
        if other.id == place.id or other.layout_east_south is None:
            continue
        if find_place_label(task, image, other) is not None:
            found.append(other)
    return found


def pan_direction(task: Any, image: np.ndarray, place: MapPlace) -> str | None:
    """用地标到目标的布局向量决定往哪边拉。+x 东，+y 南。不是点击坐标。

    |dx| 大于 |dy| 就东西向，否则南北向。两边大区同一套。
    """
    if place.layout_east_south is None:
        return None
    landmarks = _visible_landmarks(task, image, place)
    if not landmarks:
        return None
    count = float(len(landmarks))
    cx = sum(item.layout_east_south[0] for item in landmarks) / count
    cy = sum(item.layout_east_south[1] for item in landmarks) / count
    tx, ty = place.layout_east_south
    dx = tx - cx
    dy = ty - cy
    if abs(dx) <= 1e-6 and abs(dy) <= 1e-6:
        return None
    if abs(dx) > abs(dy):
        return "east" if dx > 0 else "west"
    return "south" if dy > 0 else "north"


def _arm_pan(task: Any, key: str) -> None:
    if getattr(task, "_pan_key", None) != key:
        task._pan_key = key
        task.map_swipes = 0


def _swipe(image: np.ndarray, direction: str) -> PlannedAction:
    height, width = image.shape[:2]
    if direction == "south":
        # 手指上移，把南边拉进画面。停在最上侧时南边不在屏上。
        label, x1, y1, x2, y2 = (
            "向上滑动地图",
            width // 2,
            int(height * 0.62),
            width // 2,
            int(height * 0.32),
        )
    elif direction == "north":
        label, x1, y1, x2, y2 = (
            "向下滑动地图",
            width // 2,
            int(height * 0.42),
            width // 2,
            int(height * 0.73),
        )
    elif direction == "west":
        label, x1, y1, x2, y2 = (
            "向右滑动地图",
            int(width * 0.32),
            height // 2,
            int(width * 0.70),
            height // 2,
        )
    elif direction == "east":
        label, x1, y1, x2, y2 = (
            "向左滑动地图",
            int(width * 0.70),
            height // 2,
            int(width * 0.32),
            height // 2,
        )
    else:
        raise ValueError(direction)
    return PlannedAction(kind="swipe", label=label, x=x1, y=y1, x2=x2, y2=y2)


def _pan_message(place: MapPlace, direction: str, index: int) -> str:
    side = {
        "west": "西侧",
        "east": "东侧",
        "south": "南边",
        "north": "北边",
    }[direction]
    return (
        f"「{place.region.name}」上还看不到「{place.name}」（在{side}）。"
        "平移地图，直到看见这个名字再点。不要假设它已经在屏幕上，"
        f"也不按固定坐标猜点。第 {index}/{config.MAP_SWIPE_MAX} 次滑动。"
    )


def click_or_pan_to_place(
    task: Any,
    image: np.ndarray,
    clf: Any,
    place: MapPlace,
) -> StepResult:
    """已经站在正确的大区地图上：看见地名就点，看不见就平移，不猜坐标。"""
    matches = list(clf.matches)
    label = find_place_label(task, image, place)
    if label is not None:
        task.map_swipes = 0
        task._pan_key = None
        task.pending_city = place.name
        matches = _merge(matches, label)
        return task._click_result(
            place.region.scene,
            clf,
            matches,
            label,
            f"左上角是「{place.region.name}」。点击「{place.name}」进入。",
        )

    if not can_recognize_name(task, place):
        missing = (
            f"「{place.name}」在「{place.region.name}」上。"
            "缺少地名模板，当前也读不出这个名字，不会编造点击，也不会按坐标猜点。"
        )
        return _halt(clf, place.region.scene, f"未找到{place.name}", missing)

    direction = pan_direction(task, image, place)
    if direction is None:
        missing = (
            f"「{place.region.name}」上还看不到「{place.name}」，"
            "也没有能用来判断方向的地标。不会按坐标猜点，也不会点「离开」。"
        )
        return _halt(clf, place.region.scene, f"未找到{place.name}", missing)

    key = f"{place.id}:{direction}"
    _arm_pan(task, key)
    if task.map_swipes >= config.MAP_SWIPE_MAX:
        missing = (
            f"已滑动地图 {config.MAP_SWIPE_MAX} 次，仍然看不到「{place.name}」。"
            "不会按固定坐标猜点。"
        )
        return _halt(clf, place.region.scene, f"未找到{place.name}", missing)
    task.map_swipes += 1
    action = _swipe(image, direction)
    action.message = _pan_message(place, direction, task.map_swipes)
    return StepResult(
        scene=place.region.scene,
        reason=clf.reason,
        matches=matches,
        action=action,
        status="continue",
        message=action.message,
    )


def _merge(matches: list[Match], new: Match | None) -> list[Match]:
    if new is None:
        return matches
    if any(item.template_id == new.template_id for item in matches):
        return matches
    return list(matches) + [new]
