"""每条每日委托一份短配方。共用动词在 src/tasks/verbs.py。

类型1：进关卡，点 NPC 的脸，跳过剧情后战斗，再领奖。
类型2：交物品。背包里已经有东西时，城内点 NPC 的脸并跳过剧情即可上交。
类型3：同一关打几场。事件弹窗关掉后重进，不计入次数；正式胜利才计数。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src import config
from src.vision.types import Scene


class CommissionKind(str, Enum):
    BATTLE = "battle"
    TURN_IN = "turn_in"
    MULTI_BATTLE = "multi_battle"


@dataclass(frozen=True)
class CommissionRecipe:
    """一条委托要去哪、点哪张卡、把脸点在谁身上。"""

    quest_id: str
    name: str
    kind: CommissionKind
    card_template: str
    log_template: str
    objective_template: str | None
    npc_template: str | None
    objective_text: str
    stage_flag_template: str | None = None
    region_banner_template: str | None = None
    city_label_template: str | None = None
    city_scene: Scene | None = None
    fights_required: int = 1
    # leave：阿格莱恩点左下「离开」。tab：点左侧区域页签，不点「离开」。
    region_switch: str = "leave"


# 画面原文是「喳喳」，不是「嗥嗥」或「嗫嗫」。
ZHAZHA_BULIN = CommissionRecipe(
    quest_id="zhazha_bulin",
    name=config.PRIORITY_COMMISSION,
    kind=CommissionKind.BATTLE,
    card_template="commission_zhazha_bulin",
    log_template="quest_log_zhazha",
    objective_template="quest_accepted_obj",
    npc_template="npc_child",
    objective_text="消灭 莉莉托斯郊外 1-3 的入侵的喳喳布林",
    stage_flag_template="stage_flag_1_3",
    city_scene=Scene.CITY_LILITOS,
)

HATRED_GROWTH = CommissionRecipe(
    quest_id="hatred_growth",
    name=config.TURN_IN_COMMISSION,
    kind=CommissionKind.TURN_IN,
    card_template="commission_hatred_growth",
    log_template="quest_log_hatred",
    objective_template="quest_accepted_relic",
    npc_template="npc_adventurer",
    objective_text=config.TURN_IN_OBJECTIVE,
    region_banner_template="world_crystia",
    city_label_template="region_turandon",
    city_scene=Scene.CITY_TURANDON,
)

# 图兰顿沙漠协会的紫色紧急委托。只打 9-7 的「初步探索」三场。
EAGER_ADVENTURER = CommissionRecipe(
    quest_id="eager_adventurer",
    name=config.MULTI_BATTLE_COMMISSION,
    kind=CommissionKind.MULTI_BATTLE,
    card_template="commission_eager_adventurer",
    log_template="quest_log_eager",
    objective_template="quest_accepted_scorpion",
    npc_template="npc_eager_adventurer",
    objective_text=config.MULTI_BATTLE_OBJECTIVE,
    stage_flag_template="stage_flag_9_7",
    region_banner_template="world_crystia",
    city_label_template="region_turandon",
    city_scene=Scene.CITY_TURANDON,
    fights_required=config.MULTI_BATTLE_FIGHTS,
    region_switch="tab",
)

RECIPES_BY_NAME: dict[str, CommissionRecipe] = {
    ZHAZHA_BULIN.name: ZHAZHA_BULIN,
    HATRED_GROWTH.name: HATRED_GROWTH,
    EAGER_ADVENTURER.name: EAGER_ADVENTURER,
}

# 还没走完的委托不要往这里填名字。未知名称会直接拒绝。
PENDING_COMMISSIONS: tuple[str, ...] = ()


def get_recipe(name: str | None = None) -> CommissionRecipe:
    """按屏幕上的委托标题取配方。未知名称直接拒绝，不编造路线。"""
    if not name:
        return ZHAZHA_BULIN
    recipe = RECIPES_BY_NAME.get(name)
    if recipe is None:
        known = "、".join(RECIPES_BY_NAME)
        raise KeyError(
            f"尚未收录委托「{name}」。已有配方：{known}。"
            "不会为未收录的委托补阶段，也不会造模板。"
        )
    return recipe


def register_recipe(recipe: CommissionRecipe) -> None:
    """走查完成、并且模板已经在 manifest 里，才能登记。

    战斗配方必须有关卡旗帜；交物品配方必须有区域地图上的城市名。
    多场战斗还要写明打几场。没有这些就不要登记，以免跑出空阶段。
    """
    if recipe.kind is CommissionKind.BATTLE and not recipe.stage_flag_template:
        raise ValueError(f"「{recipe.name}」是战斗委托，但没有关卡旗帜模板。")
    if recipe.kind is CommissionKind.TURN_IN and not recipe.city_label_template:
        raise ValueError(f"「{recipe.name}」是交物品委托，但没有城市入口模板。")
    if recipe.kind is CommissionKind.MULTI_BATTLE:
        if not recipe.stage_flag_template:
            raise ValueError(f"「{recipe.name}」是多场战斗，但没有关卡旗帜模板。")
        if recipe.fights_required < 1:
            raise ValueError(f"「{recipe.name}」没有要打的场数。")
    if not recipe.card_template or not recipe.log_template:
        raise ValueError(f"「{recipe.name}」缺少委托卡片或日志标题模板。")
    RECIPES_BY_NAME[recipe.name] = recipe
