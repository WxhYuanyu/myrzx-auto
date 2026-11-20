"""五个上报问题的合成画面测试。不连模拟器，也不跑 --live。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LANGREN
from src.tasks.navigation import (
    city_is_target,
    click_or_pan_to_place,
    confirmed_city_name,
    kind_from_title,
)
from src.tasks.priority_flows import _wrong_city, step_check_item, step_enter_3_20, step_explore
from src.tasks.recipes import get_recipe
from src.tasks.scroll import BAG_ITEM_REGION, SHOP_LIST_REGION, ListScroll, cell_signature
from src.tasks.shop_buy import ShopBuyTask
from src.vision.classify import Classification, classify_scene
from src.vision.image import load_bgr
from src.vision.templates import templates_by_id
from src.vision.types import Scene

ROOT = Path(__file__).resolve().parents[1]
NODE_3_20 = ROOT / "tests" / "fixtures" / "priority" / "node_3_20.png"
BOARD = ROOT / "tests" / "fixtures" / "multi_battle" / "02_commission_list.png"


def _paste(canvas: np.ndarray, image: np.ndarray, x: int, y: int) -> None:
    height, width = image.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]
    x = min(max(0, x), max(0, canvas_w - width))
    y = min(max(0, y), max(0, canvas_h - height))
    canvas[y : y + height, x : x + width] = image


def test_stage_3_20_crop_keeps_the_digits_and_clicks_the_node(templates):
    spec = templates_by_id(templates)["stage_flag_3_20"]
    gray = cv2.cvtColor(spec.image_bgr, cv2.COLOR_BGR2GRAY)
    # 数字在中下部，最底下几行应是留白，而不是把笔画切在边上。
    assert float(gray[-8:].mean()) > float(gray[80:100].mean())
    assert spec.image_bgr.shape[1] >= 60
    assert "3-20" in spec.notes or spec.label == "3-20"

    node = load_bgr(NODE_3_20)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("奇怪的魔物"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index("enter_3_20")
    result = task.plan(node)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "3-20"
    assert result.action.match is not None
    assert result.action.match.template_id in {"stage_flag_3_20", "stage_node_3_20"}
    box = result.action.match.box
    assert result.action.x == box.center[0]
    assert result.action.y == box.center[1]
    assert result.action.x is not None and result.action.x < 80
    # 点击落在旗帜中部的星星上，不在画面右侧的气泡上。
    assert box.x2 < 90


def test_generic_deep_explore_is_not_stage_1_3(templates):
    by_id = templates_by_id(templates)
    deep = by_id["stage_node_deep"].image_bgr
    cave = by_id["stage_map_sweet_cave"].image_bgr
    title = by_id["stage_1_3_title"].image_bgr

    only_deep = np.zeros((420, 360, 3), dtype=np.uint8)
    _paste(only_deep, deep, 40, 80)
    alone = classify_scene(only_deep, templates)
    assert alone.scene is not Scene.STAGE_1_3

    with_map = np.zeros((460, 420, 3), dtype=np.uint8)
    _paste(with_map, cave, 20, 30)
    _paste(with_map, deep, 200, 180)
    mapped = classify_scene(with_map, templates)
    assert mapped.scene is Scene.STAGE_MAP
    assert mapped.scene is not Scene.STAGE_1_3

    titled = np.zeros((460, 420, 3), dtype=np.uint8)
    _paste(titled, title, 8, 8)
    _paste(titled, deep, 180, 160)
    real = classify_scene(titled, templates)
    assert real.scene is Scene.STAGE_1_3
    assert real.best is not None
    assert real.best.template_id == "stage_1_3_title"


def test_langren_goes_down_then_right_and_stops_if_still_missing(templates):
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    clf = Classification(scene=Scene.WORLD_MAP, reason="测试大地图")
    first = np.zeros((480, 360, 3), dtype=np.uint8)
    first[120:300, 40:300] = (20, 80, 20)
    down = click_or_pan_to_place(task, first, clf, LANGREN)
    assert down.action is not None
    assert down.action.kind == "swipe"
    assert down.action.label == "向上滑动地图"
    assert down.action.x == down.action.x2
    assert down.action.y is not None and down.action.y2 is not None
    assert down.action.y2 < down.action.y

    moved = first.copy()
    moved[120:300, 40:300] = (20, 140, 40)
    still_down = click_or_pan_to_place(task, moved, clf, LANGREN)
    assert still_down.action is not None
    assert still_down.action.label == "向上滑动地图"
    assert still_down.action.x == still_down.action.x2

    stuck = click_or_pan_to_place(task, moved, clf, LANGREN)
    assert stuck.action is not None
    assert stuck.action.label == "向左滑动地图"
    assert stuck.action.y == stuck.action.y2
    assert stuck.action.x is not None and stuck.action.x2 is not None
    assert stuck.action.x2 < stuck.action.x
    assert stuck.action.label != "向上滑动地图"

    halted = click_or_pan_to_place(task, moved, clf, LANGREN)
    assert halted.status == "halt_missing"
    assert halted.action is not None
    assert halted.action.kind == "halt"
    assert "右下角" in halted.message
    assert "已停止" in halted.message
    assert halted.action.x is None


def test_langren_clicks_only_after_the_bottom_right(templates):
    by_id = templates_by_id(templates)
    image = np.zeros((480, 360, 3), dtype=np.uint8)
    image[120:300, 40:300] = (30, 90, 30)
    _paste(image, by_id["world_langren"].image_bgr, 40, 210)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    clf = Classification(scene=Scene.WORLD_MAP, reason="测试大地图")
    first = click_or_pan_to_place(task, image, clf, LANGREN)
    assert first.action is not None
    assert first.action.kind == "swipe"
    assert first.action.label == "向上滑动地图"
    second = click_or_pan_to_place(task, image, clf, LANGREN)
    assert second.action is not None
    assert second.action.label == "向左滑动地图"
    clicked = click_or_pan_to_place(task, image, clf, LANGREN)
    assert clicked.action is not None
    assert clicked.action.kind == "click"
    assert clicked.action.label == "浪人岬"


def test_other_place_still_pans_by_landmarks(walkthrough, templates):
    from src.tasks.locations import NAN_SERAM

    image = walkthrough["wt_world_lilitos"]
    task = DailyCommissionTask(specs=templates)
    clf = classify_scene(image, templates)
    found = click_or_pan_to_place(task, image, clf, NAN_SERAM)
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "南赛拉姆"


def _pattern(seed: int, box: tuple[int, int, int, int], shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = box
    rng = np.random.default_rng(seed)
    canvas[y1:y2, x1:x2] = rng.integers(20, 220, size=(y2 - y1, x2 - x1, 3), dtype=np.uint8)
    return canvas


def test_list_scroll_stops_only_after_two_stable_compares():
    scroll = ListScroll(region=(40, 200, 200, 400), max_swipes=12)
    frame = (1920, 1080)
    box = scroll.box_on(np.zeros(frame + (3,), dtype=np.uint8))
    assert box is not None

    def precise(image, region_box):
        return cell_signature(image[region_box[1] : region_box[3], region_box[0] : region_box[2]])

    images = [_pattern(seed, box, frame) for seed in (1, 2, 3, 3, 3, 3)]
    decisions = [scroll.observe(image, precise) for image in images]
    assert decisions[:-1] == ["swipe"] * (len(decisions) - 1)
    assert decisions[-1] == "bottom"
    assert scroll.reached_bottom
    assert scroll.hit_cap is False


def test_blank_list_region_is_not_the_bottom():
    scroll = ListScroll(region=SHOP_LIST_REGION, max_swipes=3)
    blank = np.zeros((1920, 1080, 3), dtype=np.uint8)

    def precise(image, box):
        return cell_signature(image[box[1] : box[3], box[0] : box[2]])

    first = scroll.observe(blank, precise)
    assert first == "swipe"
    second = scroll.observe(blank, precise)
    assert second == "inconclusive"
    assert scroll.reached_bottom is False


def test_shop_keeps_swiping_while_the_list_region_changes():
    task = ShopBuyTask()
    task._find_item = lambda image, item: None
    task._shop_precise = lambda image, box: cell_signature(
        image[box[1] : box[3], box[0] : box[2]]
    )
    clf = Classification(scene=Scene.UNKNOWN, reason="测试金币清单")
    box = task.scroll.box_on(np.zeros((1920, 1080, 3), dtype=np.uint8))
    assert box is not None
    moving = _pattern(7, box, (1920, 1080))
    nxt = _pattern(8, box, (1920, 1080))
    first = task._plan_gold_list(moving, clf)
    assert first.action is not None
    assert first.action.kind == "swipe"
    assert first.action.y == int(1920 * 0.70)
    assert first.action.y2 == int(1920 * 0.70) - 160
    kinds = ["swipe"]
    for _ in range(4):
        result = task._plan_gold_list(nxt, clf)
        assert result.action is not None
        assert result.action.label != "购买"
        assert "购买全部" not in (result.message or "")
        kinds.append(result.action.kind)
        if task.scroll.reached_bottom:
            break
    assert kinds[1] == "swipe"
    assert task.scroll.reached_bottom
    assert task.scroll.hit_cap is False
    assert kinds.count("swipe") >= 3


def test_bag_scroll_reaches_the_bottom_before_giving_up(templates):
    recipe = get_recipe("换换口味")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.phase = task.phase
    task.bag_tab_ready = True
    by_id = templates_by_id(templates)
    title = by_id["ui_bag_title"].image_bgr
    back = by_id["ui_bag_back"].image_bgr
    base = np.zeros((1920, 1080, 3), dtype=np.uint8)
    _paste(base, title, 20, 40)
    _paste(base, back, 900, 30)
    box = ListScroll(region=BAG_ITEM_REGION, max_swipes=4).box_on(base)
    assert box is not None
    frames = []
    for seed in (1, 2, 3, 3, 3, 3):
        frame = base.copy()
        rng = np.random.default_rng(seed)
        x1, y1, x2, y2 = box
        frame[y1:y2, x1:x2] = rng.integers(30, 200, size=(y2 - y1, x2 - x1, 3), dtype=np.uint8)
        frames.append(frame)
    clf = classify_scene(frames[0], templates)
    swipes = []
    closed = None
    for frame in frames:
        result = step_check_item(task, frame, clf)
        assert result.action is not None
        if result.action.kind == "swipe":
            swipes.append(result.action.label)
            continue
        closed = result
        break
    assert swipes
    assert all(label == "下翻背包" for label in swipes)
    assert closed is not None
    assert closed.action is not None
    assert closed.action.kind == "click"
    assert "滑到底" in (closed.action.message or "")
    assert task.item_ready is False


def _board(by_id) -> np.ndarray:
    title = by_id["commission_adventurer_title"].image_bgr
    canvas = np.zeros((title.shape[0] + 820, title.shape[1] + 40, 3), dtype=np.uint8)
    _paste(canvas, title, 16, 12)
    return canvas


def test_eager_card_is_found_at_the_lower_right_and_not_on_other_cards(templates):
    by_id = templates_by_id(templates)
    card = load_bgr(ROOT / "assets" / "reference" / "quest-enthusiastic-adventurer.png")
    canvas = _board(by_id)
    x, y = canvas.shape[1] - card.shape[1] - 12, canvas.shape[0] - card.shape[0] - 12
    _paste(canvas, card, x, y)
    _paste(canvas, by_id["commission_zhazha_bulin"].image_bgr, 30, 680)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者"))
    result = task.plan(canvas)
    assert result.scene is Scene.COMMISSION_LIST
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "“热情”的冒险者"
    assert result.action.x is not None and result.action.y is not None
    assert x <= result.action.x <= x + card.shape[1]
    assert y <= result.action.y <= y + card.shape[0]
    assert result.action.x > 200

    others = _board(by_id)
    _paste(others, by_id["commission_zhazha_bulin"].image_bgr, 40, 200)
    _paste(others, by_id["commission_change_taste"].image_bgr, 40, 320)
    missed = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者")).plan(others)
    assert missed.status == "halt_missing"
    assert missed.action is not None
    assert missed.action.kind == "halt"
    assert "“热情”的冒险者" in missed.message
    assert missed.action.label != "喳喳布林入侵"


def test_eager_card_can_be_confirmed_without_the_clipped_title(templates):
    by_id = templates_by_id(templates)
    card = load_bgr(ROOT / "assets" / "reference" / "quest-enthusiastic-adventurer.png").copy()
    card[4:46, 84:230] = card[80, 20]
    canvas = _board(by_id)
    _paste(canvas, card, 300, canvas.shape[0] - card.shape[0] - 20)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者"))
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "“热情”的冒险者"
    assert result.action.x is not None and result.action.x > 300


def test_eager_card_on_the_real_board_fixture(templates):
    board = load_bgr(BOARD)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("“热情”的冒险者"))
    result = task.plan(board)
    assert result.scene is Scene.COMMISSION_LIST
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "“热情”的冒险者"
    assert result.action.match is not None
    assert result.action.match.template_id == "commission_eager_adventurer"
    assert result.action.match.score >= 0.9


def test_shop_on_world_map_clicks_city_not_leave(templates):
    """阿格莱恩上已看见王城时，只进城，不点左下「离开」。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
    _paste(canvas, by_id["world_lilitos_full"].image_bgr, 789, 738)
    for tid, x, y in (
        ("association_leave", 40, 1760),
        ("stage_leave", 40, 1820),
    ):
        if tid in by_id:
            _paste(canvas, by_id[tid].image_bgr, x, y)
    task = ShopBuyTask()
    task.specs = templates
    task.by_id = by_id
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert "离开" not in (result.action.label or "")
    assert "离开" not in (result.message or "")
    assert result.action.label in {"王城莉莉托斯", "莉莉托斯"} or "莉莉托斯" in (result.action.label or "")




class _Title:
    def __init__(self, title: str) -> None:
        self.title = title

    def find_text(self, image, text):
        return []

    def read_title(self, image):
        return self.title


def test_langren_city_after_click_goes_to_association_not_back_to_map(templates):
    """刚从大地图点进浪人岬后，即使画面上还能匹配到「浪人岬」地名，也要点协会，不能再退回大地图。"""
    assert kind_from_title("浪人岬") == "city"
    assert kind_from_title("浪人岬地区") == "region_stage"
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, by_id["city_association"].image_bgr, 80, 220)
    _paste(canvas, by_id["city_world_map_text"].image_bgr, 40, 40)
    _paste(canvas, by_id["world_langren"].image_bgr, 400, 80)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task.saw_continent = True
    task.pending_city = "浪人岬"
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "协会"
    assert result.action.label not in {"大地图", "浪人岬", "探险", "回程", "离开"}
    assert result.action.kind != "swipe"


def test_langren_region_map_does_not_leave_before_accept(templates):
    """已经在「浪人岬地区」时，接取前也不要点「回程」退回大地图再进一次。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    if "stage_return" in by_id:
        _paste(canvas, by_id["stage_return"].image_bgr, 40, 640)
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("换换口味"),
        ocr=_Title("浪人岬地区"),
    )
    task.saw_continent = True
    task.pending_city = "浪人岬"
    result = task.plan(canvas)
    assert result.action is not None
    assert result.action.label not in {"回程", "离开", "大地图", "浪人岬"}
    assert result.action.label not in {"向上滑动地图", "向左滑动地图", "向下滑动地图", "向右滑动地图"}


JUICE_WITH_COUNT = ROOT / "tests" / "fixtures" / "suspicious_juice_with_count.png"


def _bag_screen(by_id) -> np.ndarray:
    canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
    _paste(canvas, by_id["ui_bag_title"].image_bgr, 20, 40)
    _paste(canvas, by_id["ui_bag_back"].image_bgr, 900, 30)
    return canvas


def test_bag_swipe_moves_one_row_not_a_whole_page(templates):
    """背包一次只滑大约一行，避免屏幕上已经看见的果汁被整页划走。"""
    recipe = get_recipe("换换口味")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.bag_tab_ready = True
    by_id = templates_by_id(templates)
    canvas = _bag_screen(by_id)
    clf = classify_scene(canvas, templates)
    result = step_check_item(task, canvas, clf)
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.label == "下翻背包"
    assert result.action.y is not None and result.action.y2 is not None
    assert result.action.y - result.action.y2 == 180


def test_bag_recognizes_visible_juice_even_with_count(templates):
    """画面上已经有果汁时要认出来并关背包，不能再往下划然后说没有。"""
    recipe = get_recipe("换换口味")
    by_id = templates_by_id(templates)
    juice = load_bgr(JUICE_WITH_COUNT)
    for scale in (1.0, 1.6):
        task = DailyCommissionTask(specs=templates, recipe=recipe)
        task.bag_tab_ready = True
        canvas = _bag_screen(by_id)
        width = max(8, int(round(juice.shape[1] * scale)))
        height = max(8, int(round(juice.shape[0] * scale)))
        scaled = cv2.resize(juice, (width, height), interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        _paste(canvas, scaled, 80, 700)
        clf = classify_scene(canvas, templates)
        result = step_check_item(task, canvas, clf)
        assert result.action is not None, scale
        assert result.action.kind == "click", (scale, result.action.kind, result.action.label)
        assert result.action.label in {"返回", "背包"}
        assert result.action.kind != "swipe"
        assert task.item_ready is True


def test_entering_a_region_is_a_short_press_not_a_hold(templates):
    """进入地区是稍微按住约 0.5 秒，不是按着不放。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((800, 700, 3), dtype=np.uint8)
    _paste(canvas, by_id["world_langren"].image_bgr, 200, 200)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task._langren_phase = "look"
    clf = classify_scene(canvas, templates)
    result = click_or_pan_to_place(task, canvas, clf, LANGREN)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "浪人岬"
    assert result.action.hold_ms == 500
    assert result.action.hold_ms < 1000


def _beisa_region_without_3_20(templates) -> np.ndarray:
    """进北赛拉姆地区后的默认视角：能判成地区图，但画面上没有 3-20。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
    canvas[200:1600, 80:1000] = (30, 80, 40)
    if "stage_return" in by_id:
        _paste(canvas, by_id["stage_return"].image_bgr, 40, 1680)
    if "stage_flag_5_5" in by_id:
        _paste(canvas, by_id["stage_flag_5_5"].image_bgr, 808, 1480)
    return canvas


def _strange_monster_task(templates, step: str = "enter_3_20") -> DailyCommissionTask:
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("奇怪的魔物"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def test_beisa_3_20_pans_to_upper_right_instead_of_halting(templates):
    """3-20 在右上角。默认视角看不见时先往北再往东找，不能一眼没看到就停。"""
    canvas = _beisa_region_without_3_20(templates)
    task = _strange_monster_task(templates)
    first = task.plan(canvas)
    assert first.action is not None
    assert first.action.kind == "swipe"
    assert first.action.label == "向下滑动地图"
    assert first.status != "halt"
    assert first.action.label not in {"5-5", "3-23", "3-20"}

    second = task.plan(canvas)
    assert second.action is not None
    assert second.action.kind == "swipe"
    assert second.action.label == "向左滑动地图"
    assert second.status != "halt"

    third = task.plan(canvas)
    assert third.action is not None
    assert third.action.kind == "halt"
    assert "右上角" in (third.action.message or "")
    assert third.action.label not in {"5-5", "3-23"}


def test_beisa_3_20_clicks_when_it_comes_into_view(templates):
    """平移途中一旦看见 3-20 就点旗帜，不要继续滑过去。"""
    by_id = templates_by_id(templates)
    canvas = _beisa_region_without_3_20(templates)
    task = _strange_monster_task(templates)
    first = task.plan(canvas)
    assert first.action is not None and first.action.kind == "swipe"

    flag = by_id["stage_flag_3_20"].image_bgr
    _paste(canvas, flag, 700, 200)
    found = task.plan(canvas)
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "3-20"
    assert found.action.match is not None
    assert found.action.match.template_id in {"stage_flag_3_20", "stage_node_3_20"}


def test_beisa_3_20_direct_step_clicks_after_earlier_miss(templates):
    """不走 plan() 时也不能把上一帧的「没找到」带到新截图上。"""
    by_id = templates_by_id(templates)
    canvas = _beisa_region_without_3_20(templates)
    task = _strange_monster_task(templates)
    clf = classify_scene(canvas, templates)
    first = step_enter_3_20(task, canvas, clf)
    assert first.action is not None and first.action.kind == "swipe"

    later = canvas.copy()
    _paste(later, by_id["stage_flag_3_20"].image_bgr, 700, 200)
    found = step_enter_3_20(task, later, classify_scene(later, templates))
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "3-20"



def test_beisa_3_20_clicks_flag_not_bubble_when_bubble_helps(templates):
    """有任务对话圈时，用它辅助确认 3-20，但必须点旗帜而不是气泡。"""
    by_id = templates_by_id(templates)
    if "quest_bubble_map" not in by_id or "stage_flag_3_20" not in by_id:
        raise AssertionError("缺少 quest_bubble_map 或 stage_flag_3_20 模板")
    canvas = _beisa_region_without_3_20(templates)
    flag = by_id["stage_flag_3_20"].image_bgr
    bubble = by_id["quest_bubble_map"].image_bgr
    _paste(canvas, flag, 700, 200)
    fh, fw = flag.shape[:2]
    bh, bw = bubble.shape[:2]
    # 对话圈贴在旗帜右侧，模拟实机位置。
    _paste(canvas, bubble, 700 + fw - 8, 200 + max(0, fh // 2 - bh // 2))
    task = _strange_monster_task(templates)
    found = step_enter_3_20(task, canvas, classify_scene(canvas, templates))
    assert found.action is not None
    assert found.action.kind == "click"
    assert found.action.label == "3-20"
    assert "对话圈" not in (found.action.label or "")


def test_beisa_3_20_does_not_click_bubble_alone(templates):
    """只有对话圈、没有 3-20 旗帜时，不能去点气泡。"""
    by_id = templates_by_id(templates)
    if "quest_bubble_map" not in by_id:
        raise AssertionError("缺少 quest_bubble_map 模板")
    canvas = _beisa_region_without_3_20(templates)
    bubble = by_id["quest_bubble_map"].image_bgr
    _paste(canvas, bubble, 800, 240)
    task = _strange_monster_task(templates)
    result = step_enter_3_20(task, canvas, classify_scene(canvas, templates))
    assert result.action is not None
    assert result.action.kind != "click" or result.action.label != "任务对话圈"
    if result.action.kind == "click":
        assert result.action.label == "3-20"
    else:
        assert result.action.kind in {"swipe", "halt"}

def test_bag_swipe_log_includes_recognition_score(templates):
    """看不见果汁而往下翻时，日志也必须写出这一帧的识别最高分，不能只写滑动。"""
    recipe = get_recipe("换换口味")
    task = DailyCommissionTask(specs=templates, recipe=recipe)
    task.bag_tab_ready = True
    by_id = templates_by_id(templates)
    canvas = _bag_screen(by_id)
    clf = classify_scene(canvas, templates)
    result = step_check_item(task, canvas, clf)
    assert result.action is not None
    assert result.action.kind == "swipe"
    text = result.action.message or result.message or ""
    assert "识别" in text
    assert "最高分" in text
    assert "阈值" in text
    assert "未过阈值" in text
    assert getattr(task, "bag_scan_report", None)
    assert "最高分" in task.bag_scan_report

def _langren_city_widgets(templates, *, capital_subtitle: bool = False) -> np.ndarray:
    """浪人岬城内：协会、大地图、探险。可选再贴上王城副标题模板。"""
    by_id = templates_by_id(templates)
    canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
    _paste(canvas, by_id["city_association"].image_bgr, 80, 400)
    world = by_id["city_world_map_text"].image_bgr
    _paste(canvas, world, 40, 1920 - world.shape[0] - 20)
    explore = (by_id.get("city_explore_label") or by_id.get("city_explore")).image_bgr
    _paste(canvas, explore, 1080 - explore.shape[1] - 20, 1920 - explore.shape[0] - 20)
    if capital_subtitle:
        _paste(canvas, by_id["city_capital_subtitle"].image_bgr, 20, 80)
    return canvas


def test_langren_after_leave_ignores_weak_capital_scene(templates):
    """离开协会后，即便画面被判成王城莉莉托斯，没有高分标题就不能点大地图，应点探险。"""
    canvas = _langren_city_widgets(templates)
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task.saw_continent = True
    task.pending_city = "浪人岬"
    task.phase = Phase.GO_STAGE
    clf = Classification(scene=Scene.CITY_LILITOS, reason="city_capital_subtitle score=0.756")
    assert confirmed_city_name(task, canvas, clf) != "王城莉莉托斯"
    assert city_is_target(task, canvas, clf) is True
    assert _wrong_city(task, canvas, clf) is False
    explored = step_explore(task, canvas, clf)
    assert explored.action is not None
    assert explored.action.kind == "click"
    assert explored.action.label == "探险"
    assert explored.action.hold_ms == 500
    assert explored.action.label != "大地图"
    planned = task.plan(canvas)
    assert planned.action is not None
    assert planned.action.kind == "click"
    assert planned.action.label == "探险"
    assert planned.action.label != "大地图"


def test_high_score_capital_title_still_leaves_when_target_is_langren(templates, walkthrough):
    """真的读到高分王城标题时，目标是浪人岬仍要点大地图离开。"""
    image = walkthrough["wt_city"]
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task.saw_continent = True
    task.pending_city = "浪人岬"
    task.phase = Phase.GO_STAGE
    result = task.plan(image)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "大地图"
    assert result.action.label != "探险"
    assert result.action.label != "协会"


def test_receive_retries_when_button_still_visible(templates, screens):
    """已经点过接收但按钮还在，说明没接上，要再点接收，不能返回离开。"""
    task = DailyCommissionTask(specs=templates, recipe=get_recipe("换换口味"))
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index("accept_board")
    result = task.plan(screens["quest_detail"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "接收"
    assert result.action.label != "返回"
    assert result.action.label != "离开"
