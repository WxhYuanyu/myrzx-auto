"""每日委托状态机：接取、进 1-3、小孩对话、等待战斗、领奖。"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.vision.types import Scene
from tests.conftest import WALKTHROUGH_ORDER


def test_full_known_path_through_bubble(screens, templates):
    task = DailyCommissionTask(specs=templates)

    world = task.plan(screens["world"])
    assert world.scene is Scene.WORLD_MAP
    assert world.status == "continue"
    assert world.action is not None
    assert world.action.kind == "click"
    assert world.action.label == "王城莉莉托斯"

    city = task.plan(screens["city_explore"])
    assert city.scene is Scene.CITY_LILITOS
    assert city.status == "continue"
    assert city.action is not None
    assert city.action.label == "协会"

    association = task.plan(screens["association"])
    assert association.scene is Scene.ASSOCIATION
    assert association.status == "continue"
    assert association.action is not None
    assert association.action.label == "委托"

    listing = task.plan(screens["commission"])
    assert listing.scene is Scene.COMMISSION_LIST
    assert listing.status == "continue"
    assert listing.action is not None
    assert listing.action.label == "喳喳布林入侵"
    assert listing.action.kind == "click"
    assert task.phase is Phase.ACCEPT

    detail = task.plan(screens["quest_detail"])
    assert detail.scene is Scene.QUEST_DETAIL
    assert detail.status == "continue"
    assert detail.action is not None
    assert detail.action.label == "接收"
    assert task.phase is Phase.GO_STAGE

    city_after = task.plan(screens["city_explore"])
    assert city_after.scene is Scene.CITY_LILITOS
    assert city_after.status == "continue"
    assert city_after.action is not None
    assert city_after.action.label == "探险"

    stage_map = task.plan(screens["stage_map"])
    assert stage_map.scene is Scene.STAGE_MAP
    assert stage_map.status == "continue"
    assert stage_map.action is not None
    assert stage_map.action.label == "1-3"

    no_bubble = task.plan(screens["stage_1_3"])
    assert no_bubble.scene is Scene.STAGE_1_3
    assert no_bubble.status == "halt_need_next_screen"
    assert no_bubble.action is not None
    assert no_bubble.action.kind == "halt"
    assert "气泡" in no_bubble.message or "小孩" in no_bubble.message
    assert "初步探索" in no_bubble.message
    assert "进入" in no_bubble.message
    assert not task.awaiting_enter

    with_bubble = task.plan(screens["explore_bubble"])
    assert with_bubble.scene is Scene.STAGE_1_3
    assert with_bubble.action is not None
    assert with_bubble.action.kind == "click"
    assert with_bubble.action.label == "初步探索"
    assert task.awaiting_enter
    assert with_bubble.status == "halt_need_next_screen"
    assert "进入" in with_bubble.message


def test_after_node_click_plans_enter_then_waits_for_battle(screens, templates):
    task = DailyCommissionTask(specs=templates)
    task.phase = Phase.GO_STAGE
    task.awaiting_enter = True
    result = task.plan(screens["stage_1_3"])
    assert result.scene is Scene.STAGE_1_3
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "进入"
    assert result.status == "continue"
    assert task.phase is Phase.IN_BATTLE
    assert result.action.message is not None
    assert "扫荡" in result.action.message
    assert "战斗" in result.action.message or "进入" in result.action.message


def test_unknown_image_halts_before_accept(templates):
    task = DailyCommissionTask(specs=templates)
    blank = np.zeros((400, 400, 3), dtype=np.uint8)
    result = task.plan(blank)
    assert result.scene is Scene.UNKNOWN
    assert result.status == "halt_missing"
    assert result.action is not None
    assert result.action.kind == "halt"
    assert result.action.x is None
    assert "回程" in result.message
    assert "扫荡" in result.message


def test_unknown_image_is_skipped_after_accept(templates):
    task = DailyCommissionTask(specs=templates)
    task.phase = Phase.GO_STAGE
    blank = np.zeros((400, 400, 3), dtype=np.uint8)
    result = task.plan(blank)
    assert result.scene is Scene.UNKNOWN
    assert result.status == "skip_unknown"
    assert result.action is not None
    assert result.action.kind != "click"


def test_south_world_map_plans_swipe(walkthrough, templates):
    task = DailyCommissionTask(specs=templates)
    result = task.plan(walkthrough["wt_world_south"])
    assert result.scene is Scene.WORLD_MAP
    assert result.action is not None
    assert result.action.kind == "swipe"
    assert result.action.x2 == result.action.x
    assert result.action.y2 is not None and result.action.y is not None
    assert result.action.y2 > result.action.y
    assert result.status == "continue"


def test_battle_plans_wait_without_click(walkthrough, templates):
    task = DailyCommissionTask(specs=templates)
    task.phase = Phase.IN_BATTLE
    result = task.plan(walkthrough["wt_battle"])
    assert result.scene is Scene.BATTLE
    assert result.status == "waiting_battle"
    assert result.action is not None
    assert result.action.kind == "wait"
    assert result.action.kind != "click"


def test_walkthrough_full_path(walkthrough, templates):
    """按实走 22 帧走完整条「喳喳布林入侵」路径，不臆造点击。"""
    task = DailyCommissionTask(specs=templates)
    results = []
    phases = {}
    for name in WALKTHROUGH_ORDER:
        results.append((name, task.plan(walkthrough[name])))
        phases[name] = task.phase

    by_name = {name: result for name, result in results}

    south = by_name["wt_world_south"]
    assert south.action is not None and south.action.kind == "swipe"

    lilitos = by_name["wt_world_lilitos"]
    assert lilitos.action is not None
    assert lilitos.action.kind == "click"
    assert lilitos.action.label == "王城莉莉托斯"

    assert by_name["wt_city"].action is not None
    assert by_name["wt_city"].action.label == "协会"
    assert by_name["wt_association"].action.label == "委托"
    assert by_name["wt_commission_list"].action.label == "喳喳布林入侵"

    accept = by_name["wt_quest_detail"]
    assert accept.action is not None
    assert accept.action.label == "接收"
    assert task.phase is not Phase.ACCEPT

    for key in ("wt_after_accept_toast", "wt_after_accept", "wt_list_after_accept"):
        action = by_name[key].action
        assert action is not None
        assert action.kind == "click"
        assert action.label == "返回"
        assert action.delay_sec is not None and action.delay_sec > 0

    leave = by_name["wt_association_leave"]
    assert leave.action is not None
    assert leave.action.label == "离开"
    assert leave.action.delay_sec is not None

    assert by_name["wt_city_explore"].action.label == "探险"
    assert by_name["wt_stage_map"].action.label == "1-3"

    npc = by_name["wt_stage_1_3_npc"]
    assert npc.action is not None
    assert npc.action.kind == "click"
    assert npc.action.label == "小孩"
    assert npc.action.x is not None and npc.action.x < 200
    assert npc.action.y is not None and 1380 < npc.action.y < 1540
    assert phases["wt_stage_1_3_npc"] in {Phase.IN_BATTLE, Phase.CLAIM}

    skip = by_name["wt_story_dialog"]
    assert skip.action is not None
    assert skip.action.label == "跳过剧情"
    assert skip.action.y is not None and skip.action.y < 150

    battle = by_name["wt_battle"]
    assert battle.status == "waiting_battle"
    assert battle.action is not None
    assert battle.action.kind == "wait"

    victory = by_name["wt_victory"]
    assert victory.action is not None
    assert victory.action.kind == "click"
    assert victory.action.label == "触摸继续"
    # 中部或「触摸继续」本身，不应点到屏幕底部技能栏。
    assert victory.action.y is not None and 900 < victory.action.y < 1500

    post = by_name["wt_post_story"]
    assert post.action is not None
    assert post.action.label == "跳过剧情"

    scroll = by_name["wt_stage_quest_done"]
    assert scroll.action is not None
    assert scroll.action.kind == "click"
    assert "卷轴" in scroll.action.label or "勾" in scroll.action.label
    assert scroll.action.x is not None and 780 < scroll.action.x < 930
    assert scroll.action.y is not None and 170 < scroll.action.y < 260

    row = by_name["wt_quest_log"]
    assert row.action is not None
    assert row.action.label == "喳喳布林入侵"
    # 点标题行，不要点右侧印章。
    assert row.action.x is not None and row.action.x < 600

    finish = by_name["wt_quest_finish"]
    assert finish.action is not None
    assert finish.action.label == "完成"
    assert finish.action.y is not None
    assert 1200 < finish.action.y < 1400
    assert finish.action.y < 1600

    loot = by_name["wt_loot"]
    assert loot.action is not None
    assert loot.action.kind == "click"
    assert loot.action.label == "触摸继续"

    done = by_name["wt_quest_log_done"]
    assert done.status == "done"
    assert done.action is not None
    assert done.action.kind == "halt"
    assert task.phase is Phase.DONE

    # 全程不应点「扫荡」，也不应在战斗帧里点击。
    for name, result in results:
        if result.action is not None:
            assert "扫荡" not in (result.action.label or "")
        if name == "wt_battle":
            assert result.action is None or result.action.kind != "click"
