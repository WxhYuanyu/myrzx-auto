"""类型3多场战斗「“热情”的冒险者」。

事件弹窗不计数。正式「战斗胜利」才算一次，打满 3 次才离开。
类型1「喳喳布林入侵」的干跑仍由 tests/test_daily_commission.py 覆盖。
"""

from __future__ import annotations

from src import config
from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.recipes import CommissionKind, get_recipe
from src.vision.classify import classify_scene
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Scene


def _eager(templates) -> DailyCommissionTask:
    return DailyCommissionTask(specs=templates, recipe=get_recipe(config.MULTI_BATTLE_COMMISSION))


def _forbid_sweep(action) -> None:
    assert action is not None
    assert action.label != "扫荡"
    if action.kind == "click" and action.x is not None and action.y is not None:
        on_sweep = 400 < action.x < 700 and action.y > 1750
        assert not on_sweep, (action.label, action.x, action.y)


def test_recipe_is_three_fights_on_9_7(templates):
    recipe = get_recipe(config.MULTI_BATTLE_COMMISSION)
    assert recipe.kind is CommissionKind.MULTI_BATTLE
    assert recipe.fights_required == 3
    assert recipe.region_switch == "tab"
    assert recipe.stage_flag_template == "stage_flag_9_7"
    assert recipe.objective_text == config.MULTI_BATTLE_OBJECTIVE
    assert recipe.city_scene is Scene.CITY_TURANDON
    task = DailyCommissionTask(specs=templates)
    assert task.recipe.name == "喳喳布林入侵"
    assert "嗫" not in task.recipe.name
    assert "嗥" not in task.recipe.name


def test_multi_battle_frames_classify(multi_battle, templates):
    expected = {
        "region": Scene.REGION_CRYSTIA,
        "commission": Scene.COMMISSION_LIST,
        "after_accept": Scene.QUEST_DETAIL,
        "stage_map": Scene.STAGE_DESERT,
        "stage_select": Scene.STAGE_9_7,
        "event": Scene.STAGE_EVENT,
        "event_loot": Scene.LOOT_REWARD,
        "battle_start": Scene.BATTLE,
        "victory": Scene.VICTORY,
        "battle_loot": Scene.LOOT_REWARD,
        "city_npc": Scene.CITY_TURANDON,
        "story": Scene.STORY_DIALOG,
        "city_scroll": Scene.CITY_TURANDON,
        "quest_loot": Scene.LOOT_REWARD,
    }
    for name, scene in expected.items():
        result = classify_scene(multi_battle[name], templates)
        assert result.scene is scene, f"{name}: {result.reason}"


def test_region_tab_is_not_leave(walkthrough, templates):
    task = _eager(templates)
    south = task.plan(walkthrough["wt_world_south"])
    action = south.action
    assert action is not None
    assert action.kind == "click"
    assert action.label == "前往克里斯汀"
    assert action.x is not None and action.x < 450
    assert action.y is not None and 1580 < action.y < 1720
    _forbid_sweep(action)

    task = _eager(templates)
    opened = task.plan(walkthrough["wt_world_lilitos"])
    assert opened.action is not None
    assert opened.action.kind == "halt"
    assert opened.action.label != "离开"
    assert opened.action.label != "王城莉莉托斯"


def test_flag_9_7_is_not_a_neighbor(multi_battle, templates):
    spec = templates_by_id(templates)["stage_flag_9_7"]
    image = multi_battle["stage_map"].copy()
    match = find_template(image, spec)
    assert match is not None
    x, y = match.box.center
    assert 650 < x < 820
    assert 950 < y < 1100
    blanked = image.copy()
    blanked[match.box.y : match.box.y2, match.box.x : match.box.x2] = 0
    again = find_template(blanked, spec)
    assert again is None or again.score < 0.9


def test_eager_face_is_not_the_turn_in_adventurer(multi_battle, turn_in, templates):
    spec = templates_by_id(templates)["npc_eager_adventurer"]
    face = find_template(multi_battle["city_npc"], spec)
    assert face is not None
    assert face.box.center[0] < 180
    assert find_template(turn_in["city_npc"], spec) is None
    assert find_template(multi_battle["commission"], spec) is None


def test_enter_is_above_sweep_and_confirm_is_on_the_button(multi_battle, templates):
    task = _eager(templates)
    task.phase = Phase.GO_STAGE
    entered = task.plan(multi_battle["stage_select"])
    action = entered.action
    assert action is not None
    assert action.kind == "click"
    assert action.label == "进入"
    assert action.x is not None and abs(action.x - 540) < 80
    assert action.y is not None and 1540 < action.y < 1700
    _forbid_sweep(action)

    event = task.plan(multi_battle["event"])
    ok = event.action
    assert ok is not None
    assert ok.label == "确定"
    assert ok.y is not None and 1360 < ok.y < 1480
    assert task.fights_done == 0
    _forbid_sweep(ok)


def test_full_three_fight_walk_ignores_events(multi_battle, walkthrough, templates):
    task = _eager(templates)
    frames = multi_battle

    tab = task.plan(walkthrough["wt_world_south"])
    assert tab.action is not None and tab.action.label == "前往克里斯汀"

    city_gate = task.plan(frames["region"])
    assert city_gate.action is not None
    assert city_gate.action.label == "图兰顿沙漠"

    card = task.plan(frames["commission"])
    assert card.action is not None
    assert card.action.label == config.MULTI_BATTLE_COMMISSION
    assert card.action.x is not None and card.action.x < 700

    detail = task.plan(frames["after_accept"])
    assert detail.action is not None
    assert detail.action.label == "返回"
    assert task.phase is Phase.GO_STAGE

    task.fights_done = 0
    explore = task.plan(frames["city_npc"])
    assert explore.action is not None
    assert explore.action.label == "探险"
    _forbid_sweep(explore.action)

    flag = task.plan(frames["stage_map"])
    assert flag.action is not None and flag.action.label == "9-7"

    first_enter = task.plan(frames["stage_select"])
    assert first_enter.action is not None and first_enter.action.label == "进入"

    event = task.plan(frames["event"])
    assert event.action is not None and event.action.label == "确定"
    assert task.fights_done == 0
    event_loot = task.plan(frames["event_loot"])
    assert event_loot.action is not None and event_loot.action.label == "触摸继续"
    assert task.fights_done == 0
    assert task.loot_claimed is False

    again = task.plan(frames["stage_select"])
    assert again.action is not None and again.action.label == "进入"

    start = task.plan(frames["battle_start"])
    assert start.action is not None
    assert start.action.kind == "wait"
    assert start.status == "waiting_battle"
    assert start.action.x is None

    for expected in (1, 2, 3):
        victory = task.plan(frames["victory"])
        assert victory.action is not None and victory.action.label == "触摸继续"
        assert task.fights_done == expected
        loot = task.plan(frames["battle_loot"])
        assert loot.action is not None and loot.action.label == "触摸继续"
        assert task.fights_done == expected
        assert task.loot_claimed is False
        if expected < 3:
            still = task.plan(frames["stage_select"])
            assert still.action is not None and still.action.label == "进入"

    leave = task.plan(frames["stage_select"])
    assert leave.action is not None
    assert leave.action.label == "离开"
    assert leave.action.x is not None and leave.action.x < 300
    _forbid_sweep(leave.action)

    home = task.plan(frames["stage_map"])
    assert home.action is not None and home.action.label == "回程"
    assert home.action.x is not None and home.action.x < 400

    talk = task.plan(frames["city_npc"])
    assert talk.action is not None
    assert talk.action.match is not None
    assert talk.action.match.template_id == "npc_eager_adventurer"
    assert talk.action.x is not None and talk.action.x < 180
    assert talk.action.label != "探险"

    story = task.plan(frames["story"])
    assert story.action is not None
    assert story.action.label == "跳过剧情"
    assert story.action.y is not None and story.action.y < 150
    assert task.phase is Phase.CLAIM

    scroll = task.plan(frames["city_scroll"])
    assert scroll.action is not None
    assert scroll.action.x is not None and 750 < scroll.action.x < 980
    assert scroll.action.y is not None and 150 < scroll.action.y < 320

    reward = task.plan(frames["quest_loot"])
    assert reward.action is not None and reward.action.label == "触摸继续"
    assert task.loot_claimed is True

    for step in (
        tab, city_gate, card, detail, explore, flag, first_enter, event,
        event_loot, again, start, leave, home, talk, story, scroll, reward,
    ):
        _forbid_sweep(step.action)
