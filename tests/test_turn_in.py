"""类型2交物品「仇恨会令我成长」：共用动词 + 这条委托自己的配方。

类型1「喳喳布林入侵」仍走 tests/test_daily_commission.py 里的干跑。
"""

from __future__ import annotations

import pytest

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.recipes import (
    PENDING_COMMISSIONS,
    RECIPES_BY_NAME,
    CommissionKind,
    CommissionRecipe,
    get_recipe,
    register_recipe,
)
from src.vision.classify import classify_scene
from src.vision.image import load_bgr
from src.vision.match import find_template
from src.vision.templates import templates_by_id
from src.vision.types import Scene
from tests.conftest import ROOT, TURN_IN_ORDER


def _hatred(templates) -> DailyCommissionTask:
    return DailyCommissionTask(specs=templates, recipe=get_recipe("仇恨会令我成长"))


def test_default_recipe_keeps_zhazha_spelling(templates):
    task = DailyCommissionTask(specs=templates)
    assert task.recipe is get_recipe()
    assert task.recipe.name == "喳喳布林入侵"
    assert task.recipe.kind is CommissionKind.BATTLE
    labels = {
        spec.label
        for spec in templates
        if spec.id in {"commission_zhazha_bulin", "quest_log_zhazha"}
    }
    assert labels == {"喳喳布林入侵"}


def test_unknown_commission_is_refused_without_a_fake_stage():
    assert PENDING_COMMISSIONS == ()
    assert set(RECIPES_BY_NAME) == {
        "喳喳布林入侵",
        "仇恨会令我成长",
        "“热情”的冒险者",
    }
    with pytest.raises(KeyError, match="尚未收录"):
        get_recipe("没有这条委托")
    empty = CommissionRecipe(
        quest_id="pending",
        name="还在走查",
        kind=CommissionKind.TURN_IN,
        card_template="",
        log_template="",
        objective_template=None,
        npc_template=None,
        objective_text="",
        city_label_template=None,
    )
    with pytest.raises(ValueError):
        register_recipe(empty)
    assert "还在走查" not in RECIPES_BY_NAME


def test_turn_in_frames_classify(turn_in, templates):
    expected = {
        "region": Scene.REGION_CRYSTIA,
        "commission": Scene.COMMISSION_LIST,
        "after_accept": Scene.QUEST_DETAIL,
        "city_npc": Scene.CITY_TURANDON,
        "story": Scene.STORY_DIALOG,
        "city_scroll": Scene.CITY_TURANDON,
        "quest_finish": Scene.QUEST_DETAIL,
        "loot": Scene.LOOT_REWARD,
    }
    for name, scene in expected.items():
        result = classify_scene(turn_in[name], templates)
        assert result.scene is scene, f"{name}: {result.reason}"


def test_turn_in_opens_crystia_tab_instead_of_entering_lilitos(walkthrough, templates):
    task = _hatred(templates)
    south = task.plan(walkthrough["wt_world_south"])
    assert south.action is not None
    assert south.action.kind == "click"
    assert south.action.label == "前往克里斯汀"
    assert south.action.x is not None and south.action.x < 450
    assert south.action.y is not None and 1580 < south.action.y < 1720
    assert south.action.label != "离开"
    assert south.action.label != "王城莉莉托斯"

    task = _hatred(templates)
    city = task.plan(walkthrough["wt_world_lilitos"])
    assert city.action is not None
    assert city.action.kind == "swipe"
    assert city.action.label == "向上滑动地图"
    assert city.action.label != "离开"
    assert city.action.label != "王城莉莉托斯"
    assert "前往克里斯汀" in (city.action.message or "")


def test_turn_in_closes_lilitos_board(walkthrough, templates):
    task = _hatred(templates)
    result = task.plan(walkthrough["wt_commission_list"])
    assert result.scene is Scene.COMMISSION_LIST
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "返回"
    assert "图兰顿沙漠" in (result.action.message or "")
    assert "扫荡" not in (result.action.label or "")


def test_shared_board_and_receive_still_click_the_same_buttons(screens, walkthrough, templates):
    """走错协会时离开；对的协会里「委托」，以及详情上的「接收」，仍是共用按钮。"""
    task = _hatred(templates)
    wrong = task.plan(walkthrough["wt_association"])
    assert wrong.action is not None
    assert wrong.action.label == "离开"
    assert task.phase is Phase.ACCEPT

    type1 = DailyCommissionTask(specs=templates)
    board = type1.plan(walkthrough["wt_association"])
    assert board.action is not None
    assert board.action.label == "委托"

    detail = task.plan(screens["quest_detail"])
    assert detail.action is not None
    assert detail.action.label == "接收"
    assert task.phase is Phase.GO_STAGE


def test_city_before_accept_opens_association_not_the_face(turn_in, templates):
    task = _hatred(templates)
    result = task.plan(turn_in["city_npc"])
    assert result.scene is Scene.CITY_TURANDON
    assert result.action is not None
    assert result.action.label == "协会"
    assert result.action.kind == "click"


def test_adventurer_face_is_gone_after_the_dialogue(turn_in, templates):
    by_id = templates_by_id(templates)
    before = find_template(turn_in["city_npc"], by_id["npc_adventurer"])
    after = find_template(turn_in["city_scroll"], by_id["npc_adventurer"])
    assert before is not None and before.score >= 0.9
    assert after is None
    # 脸在左下，三点气泡在脸的右边。
    assert before.box.center[0] < 140


def test_quest_log_clicks_title_not_the_stamp(turn_in, templates):
    """详情弹窗盖住了下半张日志。用同一帧弹窗上方的标题行验证要点标题。"""
    task = _hatred(templates)
    task.phase = Phase.CLAIM
    header = turn_in["quest_finish"][:514].copy()
    result = task.plan(header)
    assert result.scene is Scene.QUEST_LOG, result.reason
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "仇恨会令我成长"
    assert result.action.x is not None and result.action.x < 500
    assert result.action.label != "完成印章"


def test_turn_in_walk_never_sweeps_or_explores(turn_in, templates, walkthrough):
    task = _hatred(templates)
    results = []
    phases = {}
    for name in TURN_IN_ORDER:
        results.append((name, task.plan(turn_in[name])))
        phases[name] = task.phase
    by_name = dict(results)

    region = by_name["region"]
    assert region.scene is Scene.REGION_CRYSTIA
    assert region.action is not None
    assert region.action.label == "图兰顿沙漠"
    assert "克里斯汀" in (region.action.message or "")
    assert region.action.label != "离开"

    card = by_name["commission"]
    assert card.action is not None
    assert card.action.label == "仇恨会令我成长"
    assert phases["commission"] is Phase.ACCEPT
    assert card.action.x is not None and card.action.x < 600

    back = by_name["after_accept"]
    assert back.action is not None
    assert back.action.label == "返回"
    assert back.action.y is not None and back.action.y < 800
    assert back.action.delay_sec is not None and back.action.delay_sec > 0
    assert phases["after_accept"] is Phase.GO_STAGE

    face = by_name["city_npc"]
    assert face.action is not None
    assert face.action.label == "冒险者"
    assert face.action.x is not None and 20 < face.action.x < 140
    assert face.action.y is not None and 1320 < face.action.y < 1480

    story = by_name["story"]
    assert story.action is not None
    assert story.action.label == "跳过剧情"
    assert story.action.y is not None and story.action.y < 150
    assert phases["story"] is Phase.CLAIM

    scroll = by_name["city_scroll"]
    assert scroll.action is not None
    assert scroll.action.kind == "click"
    assert "卷轴" in scroll.action.label or "勾" in scroll.action.label
    assert scroll.action.x is not None and 780 < scroll.action.x < 940
    assert scroll.action.label not in {"协会", "探险", "邮件"}

    finish = by_name["quest_finish"]
    assert finish.action is not None
    assert finish.action.label == "完成"
    assert finish.action.y is not None
    assert 1200 < finish.action.y < 1400

    loot = by_name["loot"]
    assert loot.action is not None
    assert loot.action.label == "触摸继续"

    done = task.plan(walkthrough["wt_quest_log_done"])
    assert done.status == "done"
    assert done.action is not None
    assert done.action.kind == "halt"
    assert task.phase is Phase.DONE
    assert "仇恨会令我成长" in done.message

    for name, result in results:
        action = result.action
        assert action is not None
        assert "扫荡" not in (action.label or "")
        assert action.label not in {"探险", "进入", "王城莉莉托斯"}
        if name == "story":
            assert "要塞" in (action.message or "") or "跳过剧情" == action.label


def test_hatred_from_lilitos_city_opens_world_map(walkthrough, templates):
    task = _hatred(templates)
    result = task.plan(walkthrough["wt_city"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "大地图"
    assert result.action.label != "协会"


def test_hatred_from_lilitos_association_leaves(walkthrough, templates):
    task = _hatred(templates)
    result = task.plan(walkthrough["wt_association"])
    assert result.action is not None
    assert result.action.label == "离开"
    assert "图兰顿沙漠" in (result.action.message or "")


def test_type1_from_lilitos_city_still_enters_association(walkthrough, templates):
    task = DailyCommissionTask(specs=templates)
    result = task.plan(walkthrough["wt_city"])
    assert result.action is not None
    assert result.action.label == "协会"


def test_type1_from_crystia_clicks_aglaen_tab(turn_in, templates):
    task = DailyCommissionTask(specs=templates)
    result = task.plan(turn_in["region"])
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "返阿格莱恩"
    assert result.action.label != "图兰顿沙漠"
    assert result.action.label != "离开"


def test_hatred_card_matches_either_slot(turn_in, templates):
    """委托在面板上的格子不固定，要点标题，不能写死左下或右下。"""
    by_id = templates_by_id(templates)
    spec = by_id["commission_hatred_growth"]
    left = turn_in["commission"]
    right = load_bgr(ROOT / "tests/fixtures/nav/turandon_board_right.png")
    m_left = find_template(left, spec)
    m_right = find_template(right, spec)
    assert m_left is not None and m_left.score >= 0.9
    assert m_right is not None and m_right.score >= 0.9
    assert m_left.box.center[0] < 500
    assert m_right.box.center[0] > 700

    left_plan = _hatred(templates).plan(left)
    right_plan = _hatred(templates).plan(right)
    assert left_plan.action is not None and left_plan.action.label == "仇恨会令我成长"
    assert right_plan.action is not None and right_plan.action.label == "仇恨会令我成长"
    assert left_plan.action.x is not None and left_plan.action.x < 500
    assert right_plan.action.x is not None and right_plan.action.x > 700


def test_closes_list_after_accept_on_live_board(templates):
    """接取后列表右上的返回周围是协会背景，只能按箭头本身来点，不能空等。"""
    image = load_bgr(ROOT / "tests/fixtures/nav/turandon_list_after_accept.png")
    task = _hatred(templates)
    task.phase = Phase.GO_STAGE
    result = task.plan(image)
    assert result.action is not None
    assert result.action.kind == "click"
    assert result.action.label == "返回"
    assert result.action.x is not None and result.action.x > 900
    assert result.action.y is not None and 400 < result.action.y < 600
    assert result.status == "continue"

