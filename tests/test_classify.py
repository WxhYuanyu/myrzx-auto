"""已知 fixture 应被正确分类，且不应互相误判。"""

from __future__ import annotations

from src.vision.classify import classify_scene
from src.vision.types import Scene


EXPECTED = {
    "world": Scene.WORLD_MAP,
    "association": Scene.ASSOCIATION,
    "commission": Scene.COMMISSION_LIST,
    "quest_detail": Scene.QUEST_DETAIL,
    "city_explore": Scene.CITY_LILITOS,
    "stage_map": Scene.STAGE_MAP,
    "stage_1_3": Scene.STAGE_1_3,
    "explore_bubble": Scene.STAGE_1_3,
}

WALKTHROUGH_EXPECTED = {
    "wt_world_south": Scene.WORLD_MAP,
    "wt_world_lilitos": Scene.WORLD_MAP,
    "wt_city": Scene.CITY_LILITOS,
    "wt_association": Scene.ASSOCIATION,
    "wt_commission_list": Scene.COMMISSION_LIST,
    "wt_quest_detail": Scene.QUEST_DETAIL,
    "wt_after_accept_toast": Scene.QUEST_DETAIL,
    "wt_after_accept": Scene.QUEST_DETAIL,
    "wt_list_after_accept": Scene.COMMISSION_LIST,
    "wt_association_leave": Scene.ASSOCIATION,
    "wt_city_explore": Scene.CITY_LILITOS,
    "wt_stage_map": Scene.STAGE_MAP,
    "wt_stage_1_3_npc": Scene.STAGE_1_3,
    "wt_story_dialog": Scene.STORY_DIALOG,
    "wt_battle": Scene.BATTLE,
    "wt_victory": Scene.VICTORY,
    "wt_post_story": Scene.STORY_DIALOG,
    "wt_stage_quest_done": Scene.STAGE_1_3,
    "wt_quest_log": Scene.QUEST_LOG,
    "wt_quest_finish": Scene.QUEST_DETAIL,
    "wt_loot": Scene.LOOT_REWARD,
    "wt_quest_log_done": Scene.QUEST_LOG,
}


def test_classify_each_known_screen(screens, templates):
    for name, expected in EXPECTED.items():
        result = classify_scene(screens[name], templates)
        assert result.scene is expected, (
            f"{name} 应识别为 {expected.value}，实际是 {result.scene.value}："
            f"{result.reason}"
        )
        assert result.best is not None
        assert result.best.score >= 0.75


def test_classify_walkthrough_screens(walkthrough, templates):
    for name, expected in WALKTHROUGH_EXPECTED.items():
        result = classify_scene(walkthrough[name], templates)
        assert result.scene is expected, (
            f"{name} 应识别为 {expected.value}，实际是 {result.scene.value}："
            f"{result.reason}"
        )
        assert result.best is not None
        assert result.best.score >= 0.75


def test_world_map_uses_aglaen_or_lilitos(screens, templates):
    result = classify_scene(screens["world"], templates)
    labels = {m.label for m in result.matches}
    assert "阿格莱恩" in labels or "王城莉莉托斯" in labels
    assert result.scene is Scene.WORLD_MAP


def test_commission_list_prefers_title_over_short_words(screens, templates):
    """列表标题含「协会」「委托」，不应被城内或室内模板抢走。"""
    result = classify_scene(screens["commission"], templates)
    assert result.scene is Scene.COMMISSION_LIST
    assert any(m.label == "驯养师协会委托中心" for m in result.matches)


def test_quest_detail_beats_background_list_title(screens, templates):
    """详情弹窗背后仍露出变暗的委托中心标题，必须判为任务详情。"""
    result = classify_scene(screens["quest_detail"], templates)
    assert result.scene is Scene.QUEST_DETAIL
    labels = {m.label for m in result.matches}
    assert "任务详情" in labels or "接收" in labels


def test_claim_detail_beats_quest_log(walkthrough, templates):
    """领取详情打开时背景仍是任务日志，必须判为任务详情。"""
    result = classify_scene(walkthrough["wt_quest_finish"], templates)
    assert result.scene is Scene.QUEST_DETAIL


def test_loot_beats_quest_log(walkthrough, templates):
    """获得物品弹窗叠在任务日志上，必须判为获得物品。"""
    result = classify_scene(walkthrough["wt_loot"], templates)
    assert result.scene is Scene.LOOT_REWARD


def test_victory_beats_battle_hud(walkthrough, templates):
    """胜利结算时战斗 HUD 可能残留，必须判为战斗胜利。"""
    result = classify_scene(walkthrough["wt_victory"], templates)
    assert result.scene is Scene.VICTORY


def test_capital_comes_from_the_subtitle_not_the_association(screens, templates):
    """没有标题栏的裁切只剩共用的「协会」，不能判成王城莉莉托斯。"""
    cropped = classify_scene(screens["city"], templates)
    full = classify_scene(screens["city_explore"], templates)
    assert cropped.scene is not Scene.CITY_LILITOS
    assert full.scene is Scene.CITY_LILITOS
    assert full.best is not None
    assert full.best.label == "阿格莱恩独立王国首都"


def test_bubble_crop_is_stage_1_3(screens, templates):
    result = classify_scene(screens["explore_bubble"], templates)
    assert result.scene is Scene.STAGE_1_3
    assert any(m.label == "初步探索" for m in result.matches)
