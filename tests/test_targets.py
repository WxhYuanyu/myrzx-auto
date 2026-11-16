"""在对应 fixture 上定位点击目标，框要落在人工标定的区域内。"""

from __future__ import annotations

from src.vision.bubble import find_explore_nodes, find_quest_bubble, select_node_by_bubble
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Box


# 裁模板时记录的源图坐标 (x0, y0, x1, y1)，匹配框应与之有较高 IoU。
# stage_flag_1_3 已换成带「1-3」字样的全分辨率裁切，在旧 07 图上约以 0.45 倍命中。
EXPECTED_BOXES = {
    "world_aglaen": ("world", Box(12, 110, 198, 38)),
    "world_lilitos": ("world", Box(178, 316, 144, 30)),
    "city_association": ("city", Box(138, 402, 64, 34)),
    "association_commission": ("association", Box(368, 398, 108, 114)),
    "commission_center_title": ("commission", Box(5, 4, 370, 46)),
    "commission_zhazha_bulin": ("commission", Box(310, 270, 142, 28)),
    "quest_detail_title": ("quest_detail", Box(16, 20, 189, 50)),
    "quest_accept": ("quest_detail", Box(355, 345, 125, 70)),
    "quest_not_accepted": ("quest_detail", Box(18, 350, 137, 30)),
    "city_capital_subtitle": ("city_explore", Box(4, 98, 216, 30)),
    "city_explore": ("city_explore", Box(290, 755, 188, 71)),
    "stage_map_sweet_cave": ("stage_map", Box(185, 300, 160, 100)),
    "stage_flag_1_3": ("stage_map", Box(195, 250, 69, 54)),
    "stage_1_3_title": ("stage_1_3", Box(8, 72, 232, 38)),
    "stage_node_basic": ("stage_1_3", Box(45, 448, 130, 34)),
    "stage_node_deep": ("stage_1_3", Box(178, 352, 120, 33)),
    "stage_node_full": ("stage_1_3", Box(318, 448, 140, 37)),
    "stage_enter": ("stage_1_3", Box(175, 630, 137, 95)),
    "association_leave": ("association", Box(5, 470, 105, 42)),
    "quest_bubble": ("explore_bubble", Box(116, 100, 42, 42)),
}

WALKTHROUGH_BOXES = {
    "world_lilitos_full": ("wt_world_lilitos", Box(515, 615, 290, 67)),
    "skip_story": ("wt_story_dialog", Box(755, 14, 310, 86)),
    "npc_child": ("wt_stage_1_3_npc", Box(0, 1355, 155, 180)),
    "battle_victory": ("wt_victory", Box(220, 890, 640, 135)),
    "touch_continue": ("wt_victory", Box(280, 1255, 520, 53)),
    "stage_flag_1_3": ("wt_stage_map", Box(678, 1118, 154, 120)),
    "quest_finish": ("wt_quest_finish", Box(800, 1240, 235, 115)),
    "loot_title": ("wt_loot", Box(380, 520, 320, 100)),
    "quest_log_zhazha": ("wt_quest_log", Box(80, 448, 320, 57)),
    "quest_scroll_check": ("wt_stage_quest_done", Box(845, 85, 90, 80)),
}


def test_find_named_targets_on_source_fixtures(screens, templates):
    by_id = templates_by_id(templates)
    for template_id, (screen_name, expected) in EXPECTED_BOXES.items():
        match = find_template(screens[screen_name], by_id[template_id])
        assert match is not None, f"未找到模板 {template_id} 于 {screen_name}"
        assert match.score >= 0.85, (
            f"{template_id} 分数过低: {match.score:.3f} @ scale={match.scale}"
        )
        assert match.box.iou(expected) >= 0.7, (
            f"{template_id} 框 {match.box} 与标定 {expected} IoU 过低 "
            f"({match.box.iou(expected):.3f})"
        )


def test_find_walkthrough_targets(walkthrough, templates):
    by_id = templates_by_id(templates)
    for template_id, (screen_name, expected) in WALKTHROUGH_BOXES.items():
        match = find_template(walkthrough[screen_name], by_id[template_id])
        assert match is not None, f"未找到模板 {template_id} 于 {screen_name}"
        assert match.score >= 0.90, (
            f"{template_id} 分数过低: {match.score:.3f} @ scale={match.scale}"
        )
        assert match.box.iou(expected) >= 0.7, (
            f"{template_id} 框 {match.box} 与标定 {expected} IoU 过低 "
            f"({match.box.iou(expected):.3f})"
        )


def test_lilitos_label_is_under_characters(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["world"], by_id["world_lilitos"])
    assert match is not None
    cx, cy = match.box.center
    h, w = screens["world"].shape[:2]
    assert 0.35 * w < cx < 0.80 * w
    assert 0.30 * h < cy < 0.55 * h


def test_association_button_is_bottom_right(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["association"], by_id["association_commission"])
    assert match is not None
    cx, cy = match.box.center
    h, w = screens["association"].shape[:2]
    assert cx > 0.65 * w
    assert cy > 0.70 * h


def test_zhazha_card_is_bottom_right(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["commission"], by_id["commission_zhazha_bulin"])
    assert match is not None
    assert match.label == "喳喳布林入侵"
    cx, cy = match.box.center
    h, w = screens["commission"].shape[:2]
    assert cx > 0.55 * w
    assert cy > 0.50 * h


def test_accept_button_is_bottom_right(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["quest_detail"], by_id["quest_accept"])
    assert match is not None
    assert match.label == "接收"
    cx, cy = match.box.center
    h, w = screens["quest_detail"].shape[:2]
    assert cx > 0.65 * w
    assert cy > 0.70 * h


def test_explore_button_is_bottom_right(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["city_explore"], by_id["city_explore"])
    assert match is not None
    assert match.label == "探险"
    cx, cy = match.box.center
    h, w = screens["city_explore"].shape[:2]
    assert cx > 0.55 * w
    assert cy > 0.85 * h


def test_association_template_also_hits_full_city(screens, templates):
    """02 裁的「协会」也应能在 06 完整城内图上找到。"""
    by_id = templates_by_id(templates)
    match = find_template(screens["city_explore"], by_id["city_association"])
    assert match is not None
    assert match.score >= 0.85
    cx, cy = match.box.center
    h, w = screens["city_explore"].shape[:2]
    assert 0.20 * w < cx < 0.55 * w
    assert 0.45 * h < cy < 0.70 * h


def test_flag_1_3_is_near_map_center_not_other_flags(screens, templates):
    by_id = templates_by_id(templates)
    match = find_template(screens["stage_map"], by_id["stage_flag_1_3"])
    assert match is not None
    assert match.label == "1-3"
    cx, cy = match.box.center
    h, w = screens["stage_map"].shape[:2]
    # 1-3 在关卡图中部；1-1 偏上、1-5 偏右下，不应落到那些位置。
    assert 0.40 * w < cx < 0.70 * w
    assert 0.35 * h < cy < 0.60 * h


def test_fullres_flag_includes_label_and_hits_only_1_3(walkthrough, templates):
    """带「1-3」字样的旗帜模板应打在 1-3，而不是右侧的 1-4。"""
    by_id = templates_by_id(templates)
    image = walkthrough["wt_stage_map"]
    match = find_template(image, by_id["stage_flag_1_3"])
    assert match is not None
    cx, cy = match.box.center
    h, w = image.shape[:2]
    # 实走画面中 1-3 约在 (755, 1178)；1-4 更靠右下。
    assert 680 < cx < 830
    assert 1100 < cy < 1260
    assert 0.60 * w < cx < 0.80 * w
    assert 0.55 * h < cy < 0.70 * h


def test_npc_is_face_not_bubble(walkthrough, templates):
    by_id = templates_by_id(templates)
    image = walkthrough["wt_stage_1_3_npc"]
    match = find_template(image, by_id["npc_child"])
    assert match is not None
    cx, cy = match.box.center
    # 头像约 (90, 1460)；边缘气泡更靠右。
    assert 40 < cx < 160
    assert 1380 < cy < 1520


def test_finish_button_is_mid_lower_not_screen_bottom(walkthrough, templates):
    by_id = templates_by_id(templates)
    image = walkthrough["wt_quest_finish"]
    match = find_template(image, by_id["quest_finish"])
    assert match is not None
    cx, cy = match.box.center
    h = image.shape[0]
    # 实走按钮中心约 (910, 1310)；点 y=1800 会点空。
    assert 850 < cx < 980
    assert 1240 < cy < 1380
    assert cy < h - 400


def test_scroll_check_absent_before_battle(walkthrough, templates):
    by_id = templates_by_id(templates)
    before = find_template(walkthrough["wt_stage_1_3_npc"], by_id["quest_scroll_check"])
    after = find_template(walkthrough["wt_stage_quest_done"], by_id["quest_scroll_check"])
    assert before is None
    assert after is not None
    assert after.score >= 0.90


def test_accept_button_absent_after_accept(walkthrough, templates):
    by_id = templates_by_id(templates)
    before = find_template(walkthrough["wt_quest_detail"], by_id["quest_accept"])
    after = find_template(walkthrough["wt_after_accept"], by_id["quest_accept"])
    assert before is not None
    assert after is None


def test_bubble_found_on_09_not_on_08(screens, templates):
    bubble_08 = find_quest_bubble(screens["stage_1_3"], templates)
    bubble_09 = find_quest_bubble(screens["explore_bubble"], templates)
    assert bubble_08 is None
    assert bubble_09 is not None
    assert bubble_09.score >= 0.85
    cx, cy = bubble_09.box.center
    h, w = screens["explore_bubble"].shape[:2]
    # 气泡在局部图中上部、略偏右，不要误配成左侧橙色箭头。
    assert 0.45 * w < cx < 0.85 * w
    assert 0.20 * h < cy < 0.55 * h


def test_three_nodes_and_enter_visible_on_full_1_3(screens, templates):
    nodes = find_explore_nodes(screens["stage_1_3"], templates)
    labels = {n.label for n in nodes}
    assert labels == {"初步探索", "深入探索", "完全探索"}
    by_id = templates_by_id(templates)
    enter = find_template(screens["stage_1_3"], by_id["stage_enter"])
    assert enter is not None
    assert enter.label == "进入"


def test_bubble_snaps_to_basic_node_on_09(screens, templates):
    selection = select_node_by_bubble(screens["explore_bubble"], templates)
    assert selection is not None
    assert selection.node is not None
    assert selection.node_label == "初步探索"
    # 气泡应在节点上方。
    assert selection.bubble.box.center[1] < selection.node.box.center[1]
