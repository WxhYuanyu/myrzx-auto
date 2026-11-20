"""南赛拉姆低级「保护维修工」：在已找过的 4-2 与维修工人对话两次后战斗。

二次对话后进入战斗；战斗胜利并领取战斗奖励之后才会出现对话，再跳过剧情。4-2 找法和维修工人头像沿用「收集维修材料」。
不点气泡、地下遗迹、4-1、4-3、扫荡或「完成」。不跑 --live。
"""

from __future__ import annotations

import numpy as np

from src.tasks.daily_commission import DailyCommissionTask, Phase
from src.tasks.locations import NAN_SERAM
from src.tasks.priority_flows import ADVANCE, step_battle, step_skip_story, step_talk_on_stage
from src.tasks.recipes import CommissionKind, CommissionTier, get_recipe
from src.vision.classify import Classification
from src.vision.templates import load_templates
from src.vision.types import Scene


def _templates():
    return load_templates()


def _task(templates, step: str = "talk_on_stage") -> DailyCommissionTask:
    task = DailyCommissionTask(
        specs=templates,
        recipe=get_recipe("保护维修工"),
    )
    task.phase = Phase.GO_STAGE
    task.step_index = task.recipe.steps.index(step)
    return task


def _clf(scene: Scene = Scene.UNKNOWN) -> Classification:
    return Classification(scene=scene, reason="测试保护维修工")


def _blank(h=1920, w=1080):
    return np.full((h, w, 3), 30, dtype=np.uint8)


def _paste(canvas, image, x, y):
    h, w = image.shape[:2]
    canvas[y : y + h, x : x + w] = image


def test_protect_repairman_stays_low_and_reuses_4_2():
    recipe = get_recipe("保护维修工")
    collect = get_recipe("收集维修材料")
    assert recipe.location is NAN_SERAM
    assert recipe.tier is CommissionTier.LOW
    assert recipe.kind is CommissionKind.BATTLE
    assert recipe.quest_id == "protect_repairman"
    assert recipe.stage_flag_template == "stage_flag_4_2"
    assert recipe.stage_label == "4-2"
    assert recipe.npc_template == "npc_repair_worker"
    assert recipe.card_template == "commission_protect_repairman"
    assert recipe.log_template == "commission_protect_repairman"
    assert recipe.awaiting_crops == frozenset()
    assert recipe.steps == (
        "accept_board",
        "leave_association",
        "explore",
        "find_4_2",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "battle",
        "skip_story",
        "claim",
    )
    # 收集维修材料不能被这条改掉：同样找 4-2、同样对话两次，但没有战斗和战后跳过。
    assert collect.kind is CommissionKind.TURN_IN
    assert collect.stage_flag_template == "stage_flag_4_2"
    assert collect.npc_template == "npc_repair_worker"
    assert collect.steps == (
        "accept_board",
        "leave_association",
        "explore",
        "find_4_2",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "claim",
    )
    assert "battle" not in collect.steps
    assert collect.steps[-1] == "claim"
    assert recipe.steps[-2] == "skip_story"
    assert recipe.steps[-3] == "battle"


def test_talk_on_stage_clicks_repair_worker_not_bubble():
    import cv2
    from pathlib import Path

    templates = _templates()
    canvas = _blank()
    face = cv2.imread(
        str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "npc_repair_worker.png")
    )
    assert face is not None
    fx, fy = 80, 1500
    _paste(canvas, face, fx, fy)
    result = step_talk_on_stage(_task(templates, "talk_on_stage"), canvas, _clf())
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert fx <= result.action.x < fx + face.shape[1]
    assert fy <= result.action.y < fy + face.shape[0]


def test_skip_story_after_battle_clicks_skip():
    import cv2
    from pathlib import Path

    templates = _templates()
    canvas = _blank()
    skip = cv2.imread(
        str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "skip_story.png")
    )
    if skip is None:
        skip = cv2.imread(
            str(Path(__file__).resolve().parents[1] / "assets" / "templates" / "skip_story_tight.png")
        )
    assert skip is not None
    # 避免默认尺度跳过 1.0 时贴不上，把按钮放到右上并保留原尺寸；若匹配不到再放大。
    sx, sy = 740, 40
    if sx + skip.shape[1] > 1080:
        sx = 1080 - skip.shape[1] - 8
    _paste(canvas, skip, sx, sy)
    task = _task(templates, "skip_story")
    # 用领取战斗奖励之后那一次跳过（steps 里最后一个 skip_story）
    task.step_index = task.recipe.steps.index("battle") + 1
    assert task.recipe.steps[task.step_index] == "skip_story"
    result = step_skip_story(task, canvas, _clf(Scene.STORY_DIALOG))
    assert result is not ADVANCE
    assert result.action.kind == "click"
    assert sx <= result.action.x < sx + skip.shape[1]
    assert sy <= result.action.y < sy + skip.shape[0]


def test_second_skip_advances_if_battle_already_started():
    templates = _templates()
    task = _task(templates, "skip_story")
    # 第二次对话后的 skip_story，下一步是 battle
    first = task.recipe.steps.index("talk_on_stage")
    second_talk = task.recipe.steps.index("talk_on_stage", first + 1)
    task.step_index = second_talk + 1
    assert task.recipe.steps[task.step_index] == "skip_story"
    assert task.recipe.steps[task.step_index + 1] == "battle"
    result = step_skip_story(task, _blank(), _clf(Scene.BATTLE))
    assert result is ADVANCE

def test_battle_does_not_skip_before_claiming_rewards():
    templates = _templates()
    task = _task(templates, "battle")
    result = step_battle(task, _blank(), _clf(Scene.STORY_DIALOG))
    assert result is not ADVANCE
    assert result.action.kind in {"wait", "halt"}
    assert not getattr(task, "battle_reward_seen", False)


def test_battle_claims_loot_then_advances_to_skip():
    templates = _templates()
    task = _task(templates, "battle")
    loot = step_battle(task, _blank(), _clf(Scene.LOOT_REWARD))
    assert loot is not ADVANCE
    assert loot.action.kind == "click"
    assert getattr(task, "battle_reward_seen", False)
    # 领取战斗奖励之后才把对话交给下一步「跳过剧情」。
    result = step_battle(task, _blank(), _clf(Scene.STORY_DIALOG))
    assert result is ADVANCE
