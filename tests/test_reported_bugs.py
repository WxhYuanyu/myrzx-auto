"""五个上报问题的合成画面测试。不连模拟器，也不跑 --live。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import LANGREN
from src.tasks.navigation import click_or_pan_to_place
from src.tasks.priority_flows import step_check_item
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
    assert down.action.label == "向下滑动地图"
    assert down.action.x == down.action.x2
    assert down.action.y is not None and down.action.y2 is not None
    assert down.action.y2 > down.action.y

    moved = first.copy()
    moved[120:300, 40:300] = (20, 140, 40)
    still_down = click_or_pan_to_place(task, moved, clf, LANGREN)
    assert still_down.action is not None
    assert still_down.action.label == "向下滑动地图"
    assert still_down.action.x == still_down.action.x2

    stuck = click_or_pan_to_place(task, moved, clf, LANGREN)
    assert stuck.action is not None
    assert stuck.action.label == "向右滑动地图"
    assert stuck.action.y == stuck.action.y2
    assert stuck.action.x is not None and stuck.action.x2 is not None
    assert stuck.action.x2 > stuck.action.x
    assert stuck.action.label != "向下滑动地图"

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
    assert first.action.label == "向下滑动地图"
    second = click_or_pan_to_place(task, image, clf, LANGREN)
    assert second.action is not None
    assert second.action.label == "向右滑动地图"
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
