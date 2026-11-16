"""每条每日委托一份短配方。共用动词在 src/tasks/verbs.py。

类型1：进关卡，点 NPC 的脸，跳过剧情后战斗，再领奖。
类型2：交物品。背包里已经有东西时，城内点 NPC 的脸并跳过剧情即可上交。
类型3：另一条委托，走查还在进行。这里不登记配方，不写阶段，也不放模板。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src import config
from src.vision.types import Scene


class CommissionKind(str, Enum):
    BATTLE = "battle"
    TURN_IN = "turn_in"


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

RECIPES_BY_NAME: dict[str, CommissionRecipe] = {
    ZHAZHA_BULIN.name: ZHAZHA_BULIN,
    HATRED_GROWTH.name: HATRED_GROWTH,
}

# 类型3走查未完成。保持为空；不要往这里填任务名或假阶段。
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
            "类型3的走查还在进行，不会补阶段，也不会造模板。"
        )
    return recipe


def register_recipe(recipe: CommissionRecipe) -> None:
    """走查完成、并且模板已经在 manifest 里，才能登记。

    战斗配方必须有关卡旗帜；交物品配方必须有区域地图上的城市名。
    没有这些就不要登记，以免跑出空阶段。
    """
    if recipe.kind is CommissionKind.BATTLE and not recipe.stage_flag_template:
        raise ValueError(f"「{recipe.name}」是战斗委托，但没有关卡旗帜模板。")
    if recipe.kind is CommissionKind.TURN_IN and not recipe.city_label_template:
        raise ValueError(f"「{recipe.name}」是交物品委托，但没有城市入口模板。")
    if not recipe.card_template or not recipe.log_template:
        raise ValueError(f"「{recipe.name}」缺少委托卡片或日志标题模板。")
    RECIPES_BY_NAME[recipe.name] = recipe
