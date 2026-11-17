"""每条每日委托一份短配方。共用动词在 src/tasks/verbs.py。

类型1：进关卡，点 NPC 的脸，跳过剧情后战斗，再领奖。
类型2：交物品。背包里已经有东西时，城内点 NPC 的脸并跳过剧情即可上交。
类型3：同一关打几场。事件弹窗关掉后重进，不计入次数；正式胜利才计数。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

from src import config
from src.tasks.locations import (
    BEI_SERAM,
    LANGREN,
    LIANHU,
    LILITOS,
    LITRILE,
    MapPlace,
    NAN_SERAM,
    NAR,
    TURANDON,
)
from src.vision.types import Scene


class CommissionKind(str, Enum):
    BATTLE = "battle"
    TURN_IN = "turn_in"
    MULTI_BATTLE = "multi_battle"


class CommissionTier(IntEnum):
    """每日委托的三档。用户原先叫优先 / 次级 / 最后，程序里改成高 / 中 / 低。"""

    HIGH = 0
    MEDIUM = 1
    LOW = 2

    @property
    def zh_name(self) -> str:
        return ("高", "中", "低")[int(self)]


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
    # 高 / 中 / 低。扫城时先把所有高级做完，再从头扫中级，再扫低级。
    tier: CommissionTier = CommissionTier.HIGH
    # 接取前要先在背包里确认有这件物品。没有就不点「接收」。
    required_item_template: str | None = None
    required_item_name: str = ""


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

# 这两条都要先回莉安湖协会和会长对话，但 2-9 / 2-20 之后的做法不一样，不能共用一条「打关」路线。
# 单条跑完先不点「完成」。六次每日委托都做完后，再用 --claim 一起领奖。
_POISON_BARREL_STEPS = (
    "accept_board",
    "leave_association",
    "reenter_association",
    "talk_dashu",
    "skip_story",
    "leave_association",
    "explore",
    "fight_stage",
    "talk_youth",
    "skip_story",
    "battle",
)

_MAN_EATER_STEPS = (
    "accept_board",
    "leave_association",
    "reenter_association",
    "talk_dashu",
    "skip_story",
    "leave_association",
    "explore",
    "fight_stage",
    "enter_basic_starts_battle",
    "battle",
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
    objective_text="在莉安湖协会与协会会长对话，再去 2-9 与青年对话",
    location=LIANHU,
    stage_flag_template="stage_flag_2_9",
    stage_label="2-9",
    flow="lianhu_poison_barrel",
    steps=_POISON_BARREL_STEPS,
    summary=(
        "处理毒桶：莉安湖协会接取后离开再进协会，点「协会大叔」的脸（不点气泡），"
        "跳过剧情。离开协会，从城里点「探险」，在莉安湖地区点 2-9 旗帜"
        "（点旗帜和「2-9」，不点气泡）。在选关页点左下「青年 / 年轻的小哥」的脸，"
        "不要点气泡，也不要点「进入」或「扫荡」。跳过剧情后战斗会自己开始；"
        "战斗中只点「跳过剧情」。胜利和掉落点「触摸继续」，战后剧情再跳过。"
        "跑完先不点「完成」，六次每日委托都做完后再一起领奖。"
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
    objective_text="在莉安湖协会与协会会长对话，再去 2-20-1 讨伐食人花",
    location=LIANHU,
    stage_flag_template="stage_flag_2_20",
    stage_node="basic",
    stage_label="2-20-1",
    flow="lianhu_man_eater",
    steps=_MAN_EATER_STEPS,
    summary=(
        "讨伐食人花：莉安湖协会接取后离开再进协会，点「协会大叔」的脸（不点气泡），"
        "跳过剧情。离开协会，从城里点「探险」，在莉安湖地区点 2-20 旗帜"
        "（点旗帜和「2-20」，不点气泡）。在选关页点左侧「初步探索」的星星"
        "（2-20-1），不要只点「初步探索」四个字，也不要点岛上的气泡、"
        "「进入」或「扫荡」。点星星后战斗会自己开始；战斗中途若有对白，"
        "点右上「跳过剧情」。胜利和掉落后，跑完先不点「完成」，"
        "六次每日委托都做完后再一起领奖。"
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
    awaiting_crops=frozenset(),
    flow="seram_talk_return",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "enter_3_20",
        "talk_youth",
        "skip_story",
        "leave_stage",
        "fight_3_23_2",
        "battle",
        "leave_stage",
        "return_3_20",
        "talk_youth",
        "skip_story",
        "claim",
    ),
    summary=(
        "奇怪的魔物：北赛拉姆接取后离开协会，点城里「探险」进地区。"
        "先点 3-20 旗帜（不要点气泡）和青年的脸，跳过剧情后点「离开」。"
        "再点 3-23 旗帜，点「深入探索」的星星选中节点，然后点「进入」，不要点「扫荡」。"
        "和讨伐食人花不同，这里点星星不会自己开打。战斗结束后再「离开」，"
        "回 3-20 点青年的脸交任务。单条跑完不点「完成」，六次都做完后用 --claim 一起领。"
        "卡片上的铠甲骑士不是这个 NPC。"
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


def _pending_recipe(
    *,
    quest_id: str,
    name: str,
    kind: CommissionKind,
    location: MapPlace,
    tier: CommissionTier,
    objective_text: str,
    summary: str,
    stage_flag_template: str | None = None,
    stage_node: str | None = None,
    stage_label: str = "",
    fights_required: int = 1,
) -> CommissionRecipe:
    """中、低级里还没实机走查的委托。可以登记和排序，但不会编造点击。"""
    card = f"commission_{quest_id}"
    log = f"quest_log_{quest_id}"
    awaiting = {card, log}
    if stage_flag_template:
        awaiting.add(stage_flag_template)
    return CommissionRecipe(
        quest_id=quest_id,
        name=name,
        kind=kind,
        card_template=card,
        log_template=log,
        objective_template=None,
        npc_template=None,
        objective_text=objective_text,
        location=location,
        stage_flag_template=stage_flag_template,
        fights_required=fights_required,
        flow="pending",
        steps=("accept_board", "pending"),
        stage_node=stage_node,
        stage_label=stage_label,
        awaiting_crops=frozenset(awaiting),
        summary=summary,
        tier=tier,
    )


CHANGE_TASTE = CommissionRecipe(
    quest_id="change_taste",
    name="换换口味",
    kind=CommissionKind.TURN_IN,
    card_template="commission_change_taste",
    log_template="quest_log_change_taste",
    objective_template=None,
    npc_template="npc_strange_bat",
    objective_text="交给龙骨滩5-5的奇怪的蝙蝠1份可疑的果汁",
    location=LANGREN,
    stage_flag_template="stage_flag_5_5",
    stage_label="5-5",
    awaiting_crops=frozenset(),
    flow="langren_turn_in",
    steps=(
        "check_item",
        "accept_board",
        "leave_association",
        "explore",
        "fight_stage",
        "talk_on_stage",
        "skip_story",
        "claim",
    ),
    summary=(
        "换换口味：浪人岬协会接取的中级交物品委托。"
        "目标是交给龙骨滩 5-5 的「奇怪的蝙蝠」1 份可疑的果汁。"
        "接取前先打开背包「道具」页确认有可疑的果汁：有才点「接收」，没有就不接。"
        "扫城时跳过这条且不占用每日次数；单独 --quest 则停下说明没有果汁。"
        "详情页在接收前看不到所需物品，所以必须先查背包。怎么获得果汁还没走查，不会去打关或猜商店。"
        "离开协会后点城里「探险」进浪人岬地区；5-5 默认画面上常常看不见，"
        "要平移地区图直到看见旗帜再点，不要点旁边的对话气泡，也不要点「扫荡」。"
        "进 5-5 选关页后点左下「奇怪的蝙蝠」的头像（不要点气泡），再跳过剧情即可上交。"
        "单条跑完不点「完成」，六次都做完后用 --claim 一起领。"
    ),
    tier=CommissionTier.MEDIUM,
    required_item_template="item_suspicious_juice",
    required_item_name="可疑的果汁",
)

MAKE_MEDICINE = _pending_recipe(
    quest_id="make_medicine",
    name="制作药物",
    kind=CommissionKind.BATTLE,
    location=LITRILE,
    tier=CommissionTier.MEDIUM,
    objective_text="利特利尔大区的中级委托。任务要求还没补全。",
    summary="制作药物：图8 利特利尔大区的中级委托。流程还没实机走查，不会瞎点。",
)

ADVENTURE_SQUAD = _pending_recipe(
    quest_id="adventure_squad",
    name="冒险小队寻求支援",
    kind=CommissionKind.MULTI_BATTLE,
    location=NAR,
    tier=CommissionTier.MEDIUM,
    objective_text="讨伐30只卡布缇莫（5-A7-3，每次10只）",
    stage_flag_template="stage_flag_5_a7",
    stage_node="basic",
    stage_label="5-A7-3",
    fights_required=3,
    summary=(
        "冒险小队寻求支援：图7 纳尔本接取的中级委托，去 5-A7-3 打三次"
        "（每次10只卡布缇莫）。流程还没实机走查，不会瞎点。"
    ),
)

ROAD_SAFE_LANGREN = _pending_recipe(
    quest_id="road_safe_langren",
    name="保证商路畅通",
    kind=CommissionKind.BATTLE,
    location=LANGREN,
    tier=CommissionTier.LOW,
    objective_text="接委托后通关 5-A2 初步探索",
    stage_flag_template="stage_flag_5_a2",
    stage_node="basic",
    stage_label="5-A2",
    summary=(
        "保证商路畅通（浪人岬）：图5 的低级委托，通关 5-A2 初步探索。"
        "和南赛拉姆那条同名委托不是同一条。流程还没实机走查，不会瞎点。"
    ),
)

PROTECT_REPAIRMAN = _pending_recipe(
    quest_id="protect_repairman",
    name="保护维修工",
    kind=CommissionKind.BATTLE,
    location=NAN_SERAM,
    tier=CommissionTier.LOW,
    objective_text="挑战 4-2 任务",
    stage_flag_template="stage_flag_4_2",
    stage_label="4-2",
    summary="保护维修工：图4 南赛拉姆的低级委托，挑战 4-2。流程还没实机走查，不会瞎点。",
)

ROAD_SAFE_NAN_SERAM = _pending_recipe(
    quest_id="road_safe_nan_seram",
    name="保证商路畅通",
    kind=CommissionKind.BATTLE,
    location=NAN_SERAM,
    tier=CommissionTier.LOW,
    objective_text="挑战 4-21-1",
    stage_flag_template="stage_flag_4_21",
    stage_node="basic",
    stage_label="4-21-1",
    summary=(
        "保证商路畅通（南赛拉姆）：图4 的低级委托，挑战 4-21-1。"
        "和浪人岬那条同名委托不是同一条。流程还没实机走查，不会瞎点。"
    ),
)

# 高、中、低各按从图1到图9的地区顺序。同地区里保持表中的先后。
ALL_RECIPES: tuple[CommissionRecipe, ...] = (
    ZHAZHA_BULIN,
    POISON_BARREL,
    HOT_SPRING,
    MAN_EATER,
    STRANGE_BEAST,
    ROAD_BLOCKER,
    TRAPPED_COMPANION,
    LET_THEM_REST,
    HATRED_GROWTH,
    EAGER_ADVENTURER,
    CHANGE_TASTE,
    MAKE_MEDICINE,
    ADVENTURE_SQUAD,
    ROAD_SAFE_LANGREN,
    PROTECT_REPAIRMAN,
    ROAD_SAFE_NAN_SERAM,
)

# 表里的简称对到游戏里的标题。
NAME_ALIASES: dict[str, str] = {
    "仇恨令我成长": "仇恨会令我成长",
    "热情的冒险者": "“热情”的冒险者",
}

RECIPES_BY_NAME: dict[str, CommissionRecipe] = {}
for _recipe in ALL_RECIPES:
    # 同名委托（例如两个「保证商路畅通」）按地点区分，不覆盖先写入的那条。
    RECIPES_BY_NAME.setdefault(_recipe.name, _recipe)

# 还没走完的委托不要往这里填名字。未知名称会直接拒绝。
PENDING_COMMISSIONS: tuple[str, ...] = ()


def normalize_quest_name(name: str) -> str:
    """把表里的简称换成游戏标题。"""
    return NAME_ALIASES.get(name, name)


def recipes_named(name: str) -> tuple[CommissionRecipe, ...]:
    title = normalize_quest_name(name)
    return tuple(recipe for recipe in ALL_RECIPES if recipe.name == title)


def get_recipe(name: str | None = None, *, location: str | None = None) -> CommissionRecipe:
    """按屏幕上的委托标题取配方。未知名称直接拒绝，不编造路线。

    「保证商路畅通」有两条，必须带上地点（浪人岬或南赛拉姆）。
    """
    if not name:
        return ZHAZHA_BULIN
    found = recipes_named(name)
    if not found:
        known = "、".join(dict.fromkeys(recipe.name for recipe in ALL_RECIPES))
        raise KeyError(
            f"尚未收录委托「{name}」。已有配方：{known}。"
            "不会为未收录的委托补阶段，也不会造模板。"
        )
    if len(found) == 1:
        return found[0]
    if location:
        for recipe in found:
            if recipe.location is not None and recipe.location.name == location:
                return recipe
    places = "、".join(
        recipe.location.name if recipe.location is not None else "未知地点" for recipe in found
    )
    raise KeyError(
        f"「{normalize_quest_name(name)}」有不止一条，请注明地点：{places}。"
        "不会随便挑一条。"
    )


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
