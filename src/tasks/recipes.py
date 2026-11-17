"""每条每日委托一份短配方。共用动词在 src/tasks/verbs.py。

类型1：进关卡，点 NPC 的脸，跳过剧情后战斗，再领奖。
类型2：交物品。背包里已经有东西时，城内点 NPC 的脸并跳过剧情即可上交。
类型3：同一关打几场。事件弹窗关掉后重进，不计入次数；正式胜利才计数。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src import config
from src.tasks.locations import BEI_SERAM, LIANHU, LILITOS, LITRILE, MapPlace, NAR, TURANDON
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
    location: MapPlace | None = None
    stage_flag_template: str | None = None
    region_banner_template: str | None = None
    city_label_template: str | None = None
    city_scene: Scene | None = None
    fights_required: int = 1
    # leave：阿格莱恩点左下「离开」。tab：点左侧区域页签，不点「离开」。
    region_switch: str = "leave"
    # 空字符串走原来的三条委托。其余值在 src/tasks/priority_flows.py 里各走各的步骤。
    flow: str = ""
    steps: tuple[str, ...] = ()
    stage_node: str | None = None
    stage_label: str = ""
    # 这些模板 id 还没有裁切。走到那一步必须停，不能造一张假图去点。
    awaiting_crops: frozenset[str] = frozenset()
    # 同一张脸的备用裁切。对话时和 npc_template 一起取分数最高的。
    npc_templates: tuple[str, ...] = ()
    # 地图册里没有的区域。有值时在区域地图上直接停，不编造坐标。
    unmapped_place: str | None = None
    summary: str = ""


# 画面原文是「喳喳布林入侵」。
ZHAZHA_BULIN = CommissionRecipe(
    quest_id="zhazha_bulin",
    name=config.PRIORITY_COMMISSION,
    kind=CommissionKind.BATTLE,
    card_template="commission_zhazha_bulin",
    log_template="quest_log_zhazha",
    objective_template="quest_accepted_obj",
    npc_template="npc_child",
    objective_text="消灭 莉莉托斯郊外 1-3 的入侵的喳喳布林",
    location=LILITOS,
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
    location=TURANDON,
    region_banner_template="world_crystia",
    city_label_template="region_turandon",
    city_scene=Scene.CITY_TURANDON,
    region_switch="tab",
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
    location=TURANDON,
    stage_flag_template="stage_flag_9_7",
    region_banner_template="world_crystia",
    city_label_template="region_turandon",
    city_scene=Scene.CITY_TURANDON,
    fights_required=config.MULTI_BATTLE_FIGHTS,
    region_switch="tab",
)

_DASHU_FACES = (
    "npc_xiehui_dashu",
    "npc_dashu_card_dutong",
    "npc_dashu_card_shire",
)

# 处理毒桶和讨伐食人花是同一条路线，只是关卡不同。不要并进别的类型1。
_REENTER_DASHU_STEPS = (
    "accept_board",
    "leave_association",
    "reenter_association",
    "talk_dashu",
    "skip_story",
    "leave_association",
    "explore",
    "fight_stage",
    "battle",
    "claim",
)

POISON_BARREL = CommissionRecipe(
    quest_id="poison_barrel",
    name="处理毒桶",
    kind=CommissionKind.BATTLE,
    card_template="commission_poison_barrel",
    log_template="commission_poison_barrel",
    objective_template=None,
    npc_template="npc_xiehui_dashu",
    npc_templates=_DASHU_FACES,
    objective_text="在莉安湖协会找到协会大叔，再去打 2-9",
    location=LIANHU,
    stage_flag_template="stage_flag_2_9",
    stage_label="2-9",
    awaiting_crops=frozenset({"stage_flag_2_9"}),
    flow="lianhu_reenter_dashu",
    steps=_REENTER_DASHU_STEPS,
    summary=(
        "处理毒桶：阿格莱恩点莉安湖 → 协会接取 → 离开后再进协会 → "
        "点协会大叔的脸（不点气泡）→ 跳过剧情 → 去打 2-9 → "
        "战斗中只点跳过剧情 → 卷轴、标题、完成、获得物品"
    ),
)

MAN_EATER = CommissionRecipe(
    quest_id="man_eater",
    name="讨伐食人花",
    kind=CommissionKind.BATTLE,
    card_template="commission_man_eater",
    log_template="commission_man_eater",
    objective_template=None,
    npc_template="npc_xiehui_dashu",
    npc_templates=_DASHU_FACES,
    objective_text="在莉安湖协会找到协会大叔，再去打 2-20-1",
    location=LIANHU,
    stage_flag_template="stage_flag_2_20",
    stage_node="basic",
    stage_label="2-20-1",
    awaiting_crops=frozenset({"stage_flag_2_20"}),
    flow="lianhu_reenter_dashu",
    steps=_REENTER_DASHU_STEPS,
    summary=(
        "讨伐食人花：与处理毒桶相同，离开协会再进去点协会大叔的脸，"
        "然后打 2-20-1（初步探索）。不点扫荡。"
    ),
)

HOT_SPRING = CommissionRecipe(
    quest_id="hot_spring",
    name="温泉治疗",
    kind=CommissionKind.BATTLE,
    card_template="commission_hot_spring",
    log_template="quest_log_hot_spring",
    objective_template=None,
    npc_template="npc_hot_spring",
    objective_text="在莉安湖关卡 2-11 上与任务 NPC 对话后战斗",
    location=LIANHU,
    stage_flag_template="stage_flag_2_11",
    stage_label="2-11",
    awaiting_crops=frozenset(
        {
            "commission_hot_spring",
            "quest_log_hot_spring",
            "npc_hot_spring",
            "stage_flag_2_11",
        }
    ),
    flow="lianhu_stage_talk",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "fight_stage",
        "talk_on_stage",
        "skip_story",
        "battle",
        "claim",
    ),
    summary=(
        "温泉治疗：莉安湖接取后离开协会，到关卡 2-11 上点任务 NPC 的脸"
        "（不在协会里），跳过剧情后在同一关战斗。标题和脸的裁切还没有。"
    ),
)

STRANGE_BEAST = CommissionRecipe(
    quest_id="strange_beast",
    name="奇怪的魔物",
    kind=CommissionKind.BATTLE,
    card_template="commission_strange_beast",
    log_template="commission_strange_beast",
    objective_template=None,
    npc_template="npc_qingnian",
    objective_text="在北赛拉姆 3-20 与青年对话，前往 3-23-2 战斗，再回 3-20 交任务",
    location=BEI_SERAM,
    stage_flag_template="stage_flag_3_23",
    stage_node="deep",
    stage_label="3-23-2",
    awaiting_crops=frozenset({"stage_flag_3_23"}),
    flow="seram_talk_return",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "enter_3_20",
        "talk_youth",
        "skip_story",
        "fight_3_23_2",
        "battle",
        "return_3_20",
        "talk_youth",
        "skip_story",
        "claim",
    ),
    summary=(
        "奇怪的魔物：北赛拉姆接取后到 3-20 点青年的脸，打 3-23-2，"
        "再回到 3-20 交任务。卡片上的铠甲骑士不是这个 NPC。"
    ),
)

ROAD_BLOCKER = CommissionRecipe(
    quest_id="road_blocker",
    name="阻碍道路的家伙",
    kind=CommissionKind.BATTLE,
    card_template="commission_road_blocker",
    log_template="quest_log_road_blocker",
    objective_template=None,
    npc_template="npc_road_blocker",
    objective_text="纳尔本接取后与任务 NPC 对话，再打 7-5-1",
    location=NAR,
    stage_flag_template="stage_flag_7_5",
    stage_node="basic",
    stage_label="7-5-1",
    awaiting_crops=frozenset(
        {
            "commission_road_blocker",
            "quest_log_road_blocker",
            "npc_road_blocker",
            "stage_flag_7_5",
        }
    ),
    flow="narben_type1",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "talk_task_npc",
        "skip_story",
        "fight_7_5_1",
        "battle",
        "claim",
    ),
    summary=(
        "阻碍道路的家伙：克里斯汀的纳尔本，标准类型1，战斗是 7-5-1（初步探索）。"
        "标题、NPC 和关卡裁切还没有。"
    ),
)

TRAPPED_COMPANION = CommissionRecipe(
    quest_id="trapped_companion",
    name="受困的同伴",
    kind=CommissionKind.BATTLE,
    card_template="commission_trapped_companion",
    log_template="quest_log_trapped_companion",
    objective_template=None,
    npc_template="npc_trapped_companion",
    objective_text="利特利尔大区清 8-B4 初步探索",
    location=LITRILE,
    stage_flag_template="stage_flag_8_b4",
    stage_node="basic",
    stage_label="8-B4",
    awaiting_crops=frozenset(
        {
            "commission_trapped_companion",
            "quest_log_trapped_companion",
            "npc_trapped_companion",
            "stage_flag_8_b4",
        }
    ),
    flow="litrile_type1",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "talk_task_npc",
        "skip_story",
        "fight_8_b4_basic",
        "battle",
        "claim",
    ),
    summary=(
        "受困的同伴：利特利尔大区在克里斯汀西侧，标准类型1，清 8-B4 初步探索"
        "（不是深入或完全）。大地图上看见「利特利尔大区」再点，不编造坐标。"
    ),
)

LET_THEM_REST = CommissionRecipe(
    quest_id="let_them_rest",
    name="请让他们安息",
    kind=CommissionKind.BATTLE,
    card_template="commission_let_them_rest",
    log_template="commission_let_them_rest",
    objective_template=None,
    npc_template="npc_let_them_rest",
    objective_text="离开图兰顿沙漠协会后点城内委托人的脸，再打 9-7 深入探索",
    location=TURANDON,
    stage_flag_template="stage_flag_9_7",
    stage_node="deep",
    stage_label="9-7深入探索",
    city_scene=Scene.CITY_TURANDON,
    region_banner_template="world_crystia",
    city_label_template="region_turandon",
    region_switch="tab",
    flow="turandon_city_deep",
    steps=(
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "explore",
        "fight_9_7_deep",
        "battle",
        "claim",
    ),
    summary=(
        "请让他们安息：图兰顿沙漠接取后，在协会门口点卡片左侧那张脸（不点气泡），"
        "跳过剧情，再进 9-7 深入探索。不是 9-7-1 初步探索，也不点扫荡。"
    ),
)

RECIPES_BY_NAME: dict[str, CommissionRecipe] = {
    ZHAZHA_BULIN.name: ZHAZHA_BULIN,
    HATRED_GROWTH.name: HATRED_GROWTH,
    EAGER_ADVENTURER.name: EAGER_ADVENTURER,
    POISON_BARREL.name: POISON_BARREL,
    MAN_EATER.name: MAN_EATER,
    HOT_SPRING.name: HOT_SPRING,
    STRANGE_BEAST.name: STRANGE_BEAST,
    ROAD_BLOCKER.name: ROAD_BLOCKER,
    TRAPPED_COMPANION.name: TRAPPED_COMPANION,
    LET_THEM_REST.name: LET_THEM_REST,
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
