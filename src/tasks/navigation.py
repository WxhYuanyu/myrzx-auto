"""从任意画面退回当前大区地图，再在大区地图上进城。

位置优先看左上角标题栏（标题 + 副标题）：模板对得上就用模板，
否则用调用方提供的标题读取（OCR）。认不出就不点。

退回（一次只走一步，直到看见阿格莱恩或克里斯汀）：
- 嵌套区域点「回程」，回到上一级「…地区」。标题读得出（如「雨林之底」）
  或读不出（如「滨海小镇」）都一样：画面上有「回程」就点它，不为每个地点做标题模板。
  不点「雨林之底→」「冥土之国→」「←深海之城」这类传送门，也不点关卡或「扫荡」。
- 标题以「地区」结尾（如「纳尔本地区」）点「回程」回城。
- 选关 / 副本准备页点左下「离开」，不点「扫荡」。
- 城内标题是城市名（不是「…地区」）时，目标若不是这座城，点「大地图」。
  不点本城的「协会」或「探险」。协会是各城共用的建筑，不能用来判断是不是王城。

跨区：
- 人在阿格莱恩、目标在克里斯汀：停在地图最上侧时看不到「前往克里斯汀」，
  先把视野往南拉，看到页签再点。不点左下「离开」。
- 人在克里斯汀、目标在阿格莱恩：点右下「返阿格莱恩」。左下「离开」只回当前城。
- 同一张大区地图上地名可能在屏外（利特利尔大区在西侧）。平移到看见名称再点，
  不按记录坐标猜。没有模板也读不出名字时停住。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from src import config
from src.tasks.base import PlannedAction, StepResult
from src.tasks.locations import PLACES, MapPlace
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


def confirmed_city_name(task: Any, image: np.ndarray, clf: Any) -> str | None:
    """当前城名。只认标题栏或已经由标题模板定下的城市场景，不认「协会」。"""
    heading = read_heading(task, image)
    if heading is not None and heading.kind == "city":
        return heading.title
    if clf.scene is Scene.CITY_TURANDON:
        return "图兰顿沙漠"
    if clf.scene is Scene.CITY_LILITOS:
        return "王城莉莉托斯"
    return None


def city_is_target(task: Any, image: np.ndarray, clf: Any) -> bool:
    place = getattr(task.recipe, "location", None)
    if place is None:
        return False
    return confirmed_city_name(task, image, clf) == place.name


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
        "还没到目标城，这一页也不是大区地图或委托界面。"
        "画面上有「回程」，点它退回上一级。不依赖具体地点的标题模板。"
        + _portal_sentence()
        + "也不会点关卡或「扫荡」。"
    )
    return task._click_result(clf.scene, clf, list(clf.matches), match, message)


def _target(task: Any) -> MapPlace | None:
    return getattr(task.recipe, "location", None)


def step(task: Any, image: np.ndarray, clf: Any) -> StepResult | None:
    """导航一步。返回 None 表示人已经在目标城里，或这一页交给委托流程。"""
    if clf.scene in _QUEST_SCENES:
        return None
    heading = read_heading(task, image)
    if heading is not None and heading.kind == "portal" and task.phase is Phase.ACCEPT:
        missing = (
            f"读到「{heading.title}」，这是传送门而不是地点标题。"
            + _portal_sentence()
            + "嵌套区域要离开时只点「回程」。"
        )
        return _halt(clf, clf.scene, "拒绝传送门", missing)

    city = None
    if heading is not None and heading.kind == "city":
        city = heading.title
    elif clf.scene is Scene.CITY_TURANDON:
        city = "图兰顿沙漠"
    elif clf.scene is Scene.CITY_LILITOS:
        city = "王城莉莉托斯"

    target = _target(task)
    if city and target and city != target.name:
        return task._plan_open_world_map(image, clf, clf.scene, here=city)
    if city and target and city == target.name:
        return None

    on_continent = clf.scene in {Scene.WORLD_MAP, Scene.REGION_CRYSTIA} or (
        heading is not None and heading.kind == "continent"
    )
    if on_continent:
        return task._plan_region_to_place(image, clf)

    in_quest_stage = clf.scene in _PREP_SCENES or clf.scene is Scene.STAGE_DESERT
    if task.phase is Phase.ACCEPT:
        if heading is not None and heading.kind in {"region_stage", "nested"}:
            return click_return(task, image, clf, heading)
        if clf.scene is Scene.STAGE_DESERT:
            return click_return(
                task,
                image,
                clf,
                Heading("图兰顿沙漠地区", "", "region_stage"),
            )
        if (heading is not None and heading.kind == "stage_prep") or clf.scene in _PREP_SCENES:
            return verbs.leave_stage_select(
                task,
                image,
                clf,
                clf.scene,
                "选关或副本准备页点左下「离开」。不会点「扫荡」。",
            )
        # 标题还没录入（滨海小镇等）时也要退回，不能把这一页交给委托板。
        unlisted = click_unlisted_return(task, image, clf)
        if unlisted is not None:
            return unlisted
        return None
    if in_quest_stage:
        return None
    return click_unlisted_return(task, image, clf)


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


def pan_direction(task: Any, image: np.ndarray, place: MapPlace) -> str | None:
    """地名不在画面上时，往哪边拉地图才能把它拉进来。"""
    if place.id == "litrile":
        return "west"
    if place.region.id == "crystia":
        if place.id in {"nar", "st_casare"}:
            return "east"
        return None
    if place.region.id != "aglaen":
        return None
    if place.id == "lilitos":
        return "north"
    if place.id in {"nan_seram", "langren"}:
        return "south"
    looking_south = any(
        task._require(image, template_id) is not None
        for template_id in ("world_nan_seram", "world_langren", "region_tab_crystia")
    )
    if place.id in {"lianhu", "bei_seram"}:
        return "north" if looking_south else "south"
    return "south"


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
        matches = _merge(matches, label)
        return task._click_result(
            place.region.scene,
            clf,
            matches,
            label,
            f"左上角是「{place.region.name}」。点击「{place.name}」进入。",
        )

    if place.id == "lilitos":
        _arm_pan(task, "lilitos:north")
        return task._plan_world(image, clf)

    if not can_recognize_name(task, place):
        where = "西侧、粉树一带" if place.id == "litrile" else "这张大区地图上"
        missing = (
            f"「{place.name}」在「{place.region.name}」{where}。"
            "缺少地名模板，当前也读不出这个名字，不会编造点击，也不会按固定坐标猜点。"
        )
        return _halt(clf, place.region.scene, f"未找到{place.name}", missing)

    direction = pan_direction(task, image, place)
    if direction is None:
        missing = (
            f"左上角已确认是「{place.region.name}」，但没有匹配到「{place.name}」。"
            "不会按记录坐标猜点，也不会改点别的地名。"
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
