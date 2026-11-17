"""七条优先委托：各自的步骤、已有裁切，以及还缺图时必须停住。"""

from __future__ import annotations

import numpy as np
import pytest

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import BEI_SERAM, LIANHU, NAR, TURANDON
from src.tasks.recipes import RECIPES_BY_NAME, get_recipe
from src.vision.classify import Classification
from src.vision.image import load_bgr
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Scene
from tests.conftest import ROOT

PRIORITY = ROOT / "tests" / "fixtures" / "priority"


def _task(templates, name: str) -> DailyCommissionTask:
    return DailyCommissionTask(specs=templates, recipe=get_recipe(name))


def _at(task: DailyCommissionTask, step: str) -> DailyCommissionTask:
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def test_seven_names_are_registered_and_unknown_still_raises():
    names = {
        "处理毒桶",
        "讨伐食人花",
        "温泉治疗",
        "奇怪的魔物",
        "阻碍道路的家伙",
        "受困的同伴",
        "请让他们安息",
    }
    assert names <= set(RECIPES_BY_NAME)
    with pytest.raises(KeyError, match="尚未收录"):
        get_recipe("没有这条委托")


def test_place_names_use_the_atlas_spelling():
    poison = get_recipe("处理毒桶")
    assert poison.location is LIANHU
    assert poison.location.name == "莉安湖"
    assert "利安湖" not in poison.summary
    assert get_recipe("讨伐食人花").location is LIANHU
    assert get_recipe("温泉治疗").location is LIANHU
    assert get_recipe("奇怪的魔物").location is BEI_SERAM
    road = get_recipe("阻碍道路的家伙")
    assert road.location is NAR
    assert road.location.name == "纳尔本"
    assert get_recipe("请让他们安息").location is TURANDON
    trapped = get_recipe("受困的同伴")
    assert trapped.location is None
    assert trapped.unmapped_place == "利特利尔大区"


def test_poison_and_man_eater_share_the_reenter_flow_but_not_the_stage():
    poison = get_recipe("处理毒桶")
    flower = get_recipe("讨伐食人花")
    assert poison.flow == flower.flow == "lianhu_reenter_dashu"
    assert poison.steps == flower.steps
    assert poison.steps.index("leave_association") < poison.steps.index("reenter_association")
    assert poison.steps.index("reenter_association") < poison.steps.index("talk_dashu")
    assert poison.stage_label == "2-9"
    assert poison.stage_node is None
    assert flower.stage_label == "2-20-1"
    assert flower.stage_node == "basic"
    assert poison.npc_template == flower.npc_template == "npc_xiehui_dashu"
    assert "npc_dashu_card_dutong" in poison.npc_templates
    assert "npc_dashu_card_shire" in flower.npc_templates
    assert "stage_flag_2_9" in poison.awaiting_crops
    assert "stage_flag_2_20" in flower.awaiting_crops


def test_strange_beast_returns_to_3_20_and_does_not_use_the_card_knight():
    recipe = get_recipe("奇怪的魔物")
    steps = recipe.steps
    assert steps.index("enter_3_20") < steps.index("talk_youth")
    assert steps.index("talk_youth") < steps.index("fight_3_23_2")
    assert steps.index("fight_3_23_2") < steps.index("return_3_20")
    assert steps.index("return_3_20") < steps.index("claim")
    assert steps.count("talk_youth") == 2
    assert recipe.npc_template == "npc_qingnian"
    assert recipe.stage_label == "3-23-2"
    assert recipe.stage_node == "deep"
    assert "stage_flag_3_23" in recipe.awaiting_crops


def test_lianhu_opening_clicks_the_atlas_label_not_the_capital(walkthrough, templates):
    task = _task(templates, "处理毒桶")
    result = task.plan(walkthrough["wt_world_lilitos"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "莉安湖"
    assert result.action.label != "王城莉莉托斯"


def test_narben_opening_clicks_narben_not_turandon(turn_in, templates):
    task = _task(templates, "阻碍道路的家伙")
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "纳尔本"
    assert result.action.label != "图兰顿沙漠"


def test_let_them_rest_reuses_the_crystia_opening(walkthrough, turn_in, templates):
    task = _task(templates, "请让他们安息")
    south = task.plan(walkthrough["wt_world_south"])
    assert south.action is not None
    assert south.action.kind == "click"
    assert south.action.label == "前往克里斯汀"
    assert south.action.label != "离开"

    task = _task(templates, "请让他们安息")
    region = task.plan(turn_in["region"])
    assert region.action is not None
    assert region.action.label == "图兰顿沙漠"


def test_litrile_halts_without_a_made_up_click(walkthrough, templates):
    task = _task(templates, "受困的同伴")
    result = task.plan(walkthrough["wt_world_lilitos"])
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.x is None
    assert "利特利尔大区" in result.message
    assert "编造" in result.message
    assert result.action.label != "王城莉莉托斯"


def test_reenter_association_clicks_the_door_not_explore(walkthrough, templates):
    task = _at(_task(templates, "处理毒桶"), "leave_association")
    leaving = task.plan(walkthrough["wt_association"])
    assert leaving.action is not None
    assert leaving.action.kind == "click"
    assert leaving.action.label == "离开"

    back = task.plan(walkthrough["wt_city"])
    assert back.action is not None
    assert back.action.kind == "click"
    assert back.action.label == "协会"
    assert back.action.label != "探险"


def test_dashu_click_lands_on_the_face_not_the_bubble(templates):
    image = load_bgr(PRIORITY / "npc_xiehui_dashu.png")
    task = _at(_task(templates, "处理毒桶"), "talk_dashu")
    result = task.plan(image)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "协会大叔"
    assert result.action.match is not None
    assert result.action.match.template_id == "npc_xiehui_dashu"
    assert result.action.x is not None and result.action.x < 110
    assert result.action.y is not None and result.action.y < 160
    assert "气泡" in (result.action.message or "")


def test_youth_and_3_20_crops_are_clicked_and_3_23_does_not_reuse_3_20(templates):
    node = load_bgr(PRIORITY / "node_3_20.png")
    youth = load_bgr(PRIORITY / "npc_qingnian.png")

    entered = _at(_task(templates, "奇怪的魔物"), "enter_3_20").plan(node)
    assert entered.action is not None
    assert entered.action.kind == "click"
    assert entered.action.label == "3-20"
    assert entered.action.x is not None and entered.action.x < 80

    talked = _at(_task(templates, "奇怪的魔物"), "talk_youth").plan(youth)
    assert talked.action is not None
    assert talked.action.kind == "click"
    assert talked.action.label == "青年"
    assert talked.action.x is not None and talked.action.x < 130

    fight = _at(_task(templates, "奇怪的魔物"), "fight_3_23_2").plan(node)
    assert fight.status == "halt_missing"
    assert fight.action is not None
    assert fight.action.kind == "halt"
    assert "3-23-2" in fight.message
    assert "3-20" in fight.message

    back = _at(_task(templates, "奇怪的魔物"), "return_3_20").plan(node)
    assert back.action is not None
    assert back.action.kind == "click"
    assert back.action.label == "3-20"


def test_enter_3_20_does_not_click_flag_1_3(walkthrough, templates):
    result = _at(_task(templates, "奇怪的魔物"), "enter_3_20").plan(walkthrough["wt_stage_map"])
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.label != "1-3"
    assert "3-20" in result.message


def test_stage_flags_that_are_not_cropped_halt(walkthrough, templates):
    poison = _at(_task(templates, "处理毒桶"), "fight_stage").plan(walkthrough["wt_stage_map"])
    assert poison.status == "halt_missing"
    assert poison.action is not None and poison.action.kind == "halt"
    assert "2-9" in poison.message
    assert "初步" in poison.message
    assert poison.action.label != "1-3"

    flower = _at(_task(templates, "讨伐食人花"), "fight_stage").plan(walkthrough["wt_stage_map"])
    assert flower.status == "halt_missing"
    assert "2-20-1" in flower.message
    assert "初步探索" in flower.message

    spring = _at(_task(templates, "温泉治疗"), "talk_on_stage").plan(
        np.zeros((200, 200, 3), dtype=np.uint8)
    )
    assert spring.status == "halt_missing"
    assert "2-11" in spring.message
    assert "裁切" in spring.message
    assert "协会大叔" in spring.message
    assert spring.action is not None and spring.action.kind == "halt"

    road = _at(_task(templates, "阻碍道路的家伙"), "fight_7_5_1").plan(
        np.zeros((200, 200, 3), dtype=np.uint8)
    )
    assert road.status == "halt_missing"
    assert "7-5-1" in road.message
    assert "初步" in road.message
    assert "扫荡" in road.message

    trapped = _at(_task(templates, "受困的同伴"), "fight_8_b4_basic").plan(
        np.zeros((200, 200, 3), dtype=np.uint8)
    )
    assert trapped.status == "halt_missing"
    assert "8-B4" in trapped.message
    assert "初步探索" in trapped.message
    assert "深入" in trapped.message


def test_missing_card_does_not_click_another_quest(turn_in, templates):
    task = _task(templates, "温泉治疗")
    result = task.plan(turn_in["commission"])
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert "裁切" in result.message
    assert result.action.label != "仇恨会令我成长"


def test_rest_title_is_tight_and_the_face_excludes_the_badge(templates):
    by_id = templates_by_id(templates)
    card = load_bgr(PRIORITY / "card_qingrang_tamen_anshen.png")
    title = find_template(card, by_id["commission_let_them_rest"])
    assert title is not None and title.score >= 0.9
    assert title.box.center[0] > card.shape[1] * 0.45

    face_image = load_bgr(PRIORITY / "face_qingrang_tamen_anshen.png")
    face = find_template(face_image, by_id["npc_let_them_rest"])
    assert face is not None and face.score >= 0.9
    assert face.box.y2 < 115

    task = _at(_task(templates, "请让他们安息"), "accept_board")
    task.phase = Phase.ACCEPT
    clicked = task.plan(card)
    assert clicked.action is not None
    assert clicked.action.kind == "click"
    assert clicked.action.label == "请让他们安息"
    assert clicked.action.x is not None and clicked.action.x > card.shape[1] * 0.4


def test_rest_city_face_is_clicked_and_a_different_adventurer_is_not(turn_in, templates):
    face_image = load_bgr(PRIORITY / "face_qingrang_tamen_anshen.png")
    hit = _at(_task(templates, "请让他们安息"), "city_talk").plan(face_image)
    assert hit.action is not None
    assert hit.action.kind == "click"
    assert hit.action.label == "城内委托人"
    assert hit.action.y is not None and hit.action.y < 110
    assert "气泡" in (hit.action.message or "")

    other = _at(_task(templates, "请让他们安息"), "city_talk").plan(turn_in["city_npc"])
    assert other.action is not None
    assert other.action.kind == "wait"
    assert other.status == "skip_unknown"
    assert other.action.label != "冒险者"
    assert "裁切还没有" not in other.message


def test_9_7_deep_is_not_the_basic_path(multi_battle, templates):
    eager = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("“热情”的冒险者"),
    )
    eager.phase = Phase.GO_STAGE
    basic = eager.plan(multi_battle["stage_select"])
    assert basic.action is not None
    assert basic.action.label == "进入"
    assert "初步" in (basic.action.message or "")

    deep_task = _at(_task(templates, "请让他们安息"), "fight_9_7_deep")
    flag = deep_task.plan(multi_battle["stage_map"])
    assert flag.action is not None
    assert flag.action.kind == "click"
    assert flag.action.label == "9-7"
    assert "深入" in (flag.action.message or "")

    select = _at(_task(templates, "请让他们安息"), "fight_9_7_deep").plan(
        multi_battle["stage_select"]
    )
    assert select.action is not None
    assert select.action.label != "初步探索"
    assert select.action.label != "扫荡"
    assert select.action.label != "进入"
    if select.action.kind == "click":
        assert select.action.label == "深入探索"
    else:
        assert select.status == "halt_missing"
        assert "深入" in select.message
        assert "初步" in select.message


def test_battle_wait_clicks_skip_and_otherwise_waits(walkthrough, templates):
    plain = DailyCommissionTask(specs=templates)
    plain.phase = Phase.IN_BATTLE
    clf = Classification(scene=Scene.BATTLE, reason="unit", matches=[])
    waiting = plain._plan_battle(walkthrough["wt_battle"], clf)
    assert waiting.status == "waiting_battle"
    assert waiting.action is not None and waiting.action.kind == "wait"

    plain._match_cache = {}
    battle = walkthrough["wt_battle"].copy()
    skip = templates_by_id(templates)["skip_story"].image_bgr
    height, width = skip.shape[:2]
    battle[16 : 16 + height, battle.shape[1] - width - 12 : battle.shape[1] - 12] = skip
    skipping = plain._plan_battle(battle, clf)
    assert skipping.action is not None
    assert skipping.action.kind == "click"
    assert skipping.action.label == "跳过剧情"
    assert skipping.action.y is not None and skipping.action.y < 200


def test_board_titles_match_their_cards(templates):
    by_id = templates_by_id(templates)
    cards = {
        "commission_poison_barrel": "card_chuli_dutong.png",
        "commission_man_eater": "card_taofa_shirenhua.png",
        "commission_strange_beast": "card_qiguai_mowu.png",
    }
    for template_id, filename in cards.items():
        image = load_bgr(PRIORITY / filename)
        match = find_template(image, by_id[template_id])
        assert match is not None and match.score >= 0.9, template_id
        assert match.box.center[0] > image.shape[1] * 0.35
