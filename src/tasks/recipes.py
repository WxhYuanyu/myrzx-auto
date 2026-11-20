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
    log_template="commission_hot_spring",
    objective_template=None,
    npc_template="npc_hot_spring",
    objective_text="在莉安湖酒馆与独眼猎人对话，再去 2-11 与温泉对话后战斗",
    location=LIANHU,
    stage_flag_template="stage_flag_2_11",
    stage_label="2-11",
    awaiting_crops=frozenset(),
    flow="lianhu_hot_spring",
    steps=(
        "accept_board",
        "leave_association",
        "enter_tavern",
        "talk_hunter",
        "skip_story",
        "leave_tavern",
        "explore",
        "find_2_11",
        "talk_on_stage",
        "skip_story",
        "skip_in_battle",
        "battle",
        "skip_story",
        "claim",
    ),
    summary=(
        "温泉治疗：莉安湖协会接取后离开，先在城里点「酒馆」（不点气泡、商店、协会或探险），"
        "进酒吧后点「独眼猎人 / 强壮的雇佣猎人」的头像（不点气泡，也不点「驯养师」「兑换」「抽蛋」），跳过剧情，再点左下「离开」回城。"
        "然后点「探险」进莉安湖地区。2-11 在地图中间；看不见时按住左边缘划到中间（屏幕内容往右），"
        "不要用从中间划到边缘的轻轻划，也不要大划。划完后 2-11 会在画面中间。"
        "必须先认出 2-5 右边、2-6 左边的小屋，再点它下方带任务对话圈的 2-11 旗帜。"
        "不要点小屋，不要点气泡，不要点左边的 2-12、右边的 2-10、上面的 2-5 或 2-6，也不要点「扫荡」。"
        "看不见小屋时，即使旗帜分很高也不点。划过仍同时看不到小屋和带对话圈的 2-11，就停下。"
        "进 2-11 选关页后点左下「温泉」（不要点气泡、进入、扫荡或战阵），跳过剧情后进入战斗。"
        "进战斗后再跳过一次剧情；表格里这场大约 10 秒后会出现跳过，只针对这条委托，不会把 10 秒套到其他委托上。"
        "仍等到「战斗胜利」；战斗结束后还要再跳过一次剧情。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和酒馆入口来自表格裁切并按实机尺寸估了缩放；独眼猎人、温泉、2-11 旗帜和小屋来自用户提供的酒吧、选关页和莉安湖地区图。"
        "这条原本就在高级名单里，没有改成低级。"
    ),
    tier=CommissionTier.HIGH,
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
    # 没有任务日志的标题裁切，和处理毒桶一样复用卡片标题。
    log_template="commission_road_blocker",
    objective_template=None,
    npc_template="npc_road_blocker",
    objective_text="纳尔本接取后在城里和「年轻的冒险者」对话，再打 7-5-1",
    location=NAR,
    stage_flag_template="stage_flag_7_5",
    stage_node="basic",
    stage_label="7-5-1",
    awaiting_crops=frozenset(),
    flow="narben_type1",
    steps=(
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "explore",
        "fight_7_5_1",
        "battle",
        "leave_stage",
        "claim",
    ),
    summary=(
        "阻碍道路的家伙：克里斯汀的纳尔本。协会接取后离开协会，城里画面左下角附近会出现"
        "「冒险者 / 年轻的冒险者」（红发、绿围巾），点他的头像（不点气泡、不点名字牌）对话，"
        "不用先进探险。跳过剧情后稍微按住「探险」进纳尔本地区。7-5 在地图中下，"
        "看不见就把右边拉进画面（手指左滑，屏幕内容往右），每滑一次先找旗帜，"
        "画面不再移动或到安全次数就停下。点 7-5 的旗帜和编号，不点气泡。"
        "选关页点「初步探索」的星星（7-5-1）：若直接开打就打，若只是选中就再点「进入」，"
        "绝不点「扫荡」。战斗后离开选关，不回去找冒险者，单条不点「完成」，"
        "六次都做完后用 --claim 一起领。标题、头像、7-5 旗帜和初步探索节点来自表格裁切，"
        "按实机尺寸估了缩放，还没有用实机截图核对。"
    ),
)

TRAPPED_COMPANION = CommissionRecipe(
    quest_id="trapped_companion",
    name="受困的同伴",
    kind=CommissionKind.BATTLE,
    card_template="commission_trapped_companion",
    log_template="commission_trapped_companion",
    objective_template=None,
    npc_template="npc_trapped_companion",
    objective_text="离开利特利尔协会后，在城里协会外与冒险者对话，再清 8-B4 初步探索",
    location=LITRILE,
    stage_flag_template="stage_flag_8_b4",
    stage_node="basic",
    stage_label="8-B4",
    awaiting_crops=frozenset(),
    flow="litrile_trapped_companion",
    steps=(
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "explore",
        "find_8_b4",
        "enter_8_b4_basic",
        "battle",
        "skip_story",
        "claim",
    ),
    summary=(
        "受困的同伴：利特利尔大区接取的高级战斗委托。"
        "协会接取后离开，在城里协会外点「冒险者 / 年轻的冒险者」头像（不点气泡），"
        "跳过剧情，再点「探险」。8-B4 在地区图中下、河岸边；必须先认出它左上方的木瞭望塔，"
        "再点塔下方带任务对话圈的 8-B4 旗帜。不点瞭望塔、气泡、8-D5、8-D4、8-C1，"
        "也不要点底部「矿洞」「回程」「探索队」或「扫荡」。看不见就往右轻轻划一下"
        "（手指从屏幕右边缘滑到左边缘，屏幕内容往右），只划这一次，还没有就停。"
        "进 8-B4 点「初步探索」的星星，战斗自己开始就进入战斗，"
        "出现「进入」再点「进入」，不点扫荡。战斗胜利并领取战斗奖励之后会出现对话，"
        "再点「跳过剧情」。不点「完成」，六次后用 --live --claim 一起领。"
        "这条原本就在高级名单里，不要改成中级或低级。"
        "标题、冒险者头像和初步探索来自表格裁切，并按实机尺寸估了缩放；"
        "8-B4 旗帜和木瞭望塔来自用户 2026-11-20 提供的利特利尔大区地区图。"
    ),
    tier=CommissionTier.HIGH,
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
        "fight_5_5",
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
        "离开协会后点城里「探险」进浪人岬地区。5-5 在地区图右下角偏左，紧挨在「恶骸之狱」右边，默认常常看不见；"
        "先往南再往东平移（看画面还动不动判断到边），必须同时看到「恶骸之狱」、它右边的 5-5 旗帜和旁边的任务对话圈才点旗帜。看不见恶骸之狱时，即使旗帜分很高也不点，以免再把 5-9 当成 5-5。"
        "5-A5、5-A2 这类旗长得很像，不能因为像 5-A2 或过了阈值就点。不要点「恶骸之狱」，不要点气泡，也不要点「扫荡」。"
        "进 5-5 选关页后点左下「奇怪的蝙蝠」的头像（不要点气泡），再跳过剧情即可上交。"
        "单条跑完不点「完成」，六次都做完后用 --claim 一起领。"
    ),
    tier=CommissionTier.MEDIUM,
    required_item_template="item_suspicious_juice",
    required_item_name="可疑的果汁",
)

MAKE_MEDICINE = CommissionRecipe(
    quest_id="make_medicine",
    name="制作药物",
    kind=CommissionKind.TURN_IN,
    card_template="commission_make_medicine",
    log_template="commission_make_medicine",
    objective_template=None,
    npc_template="npc_make_medicine",
    objective_text="离开利特利尔协会后，在城里左下角与冒险者对话",
    location=LITRILE,
    awaiting_crops=frozenset(),
    flow="litrile_make_medicine",
    steps=(
        "accept_board",
        "leave_association",
        "city_talk",
        "skip_story",
        "claim",
    ),
    summary=(
        "制作药物：利特利尔大区协会接取的中级交物品委托。"
        "接取后离开协会，城里左下角就会看到「冒险者 / 年轻的冒险者」。"
        "点头像，不要点旁边的气泡。跳过剧情后这条就结束了，不打关，也不用再去探险。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和冒险者头像来自用户提供的裁切，并按实机尺寸估了缩放，还没有用 1080×1920 实机截图核对。"
    ),
    tier=CommissionTier.MEDIUM,
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

_ROAD_SAFE_LANGREN_STEPS = (
    "accept_board",
    "leave_association",
    "enter_shop",
    "talk_metaya",
    "skip_story",
    "leave_shop",
    "explore",
    "fight_5_a2",
    "enter_5_a2_basic",
    "battle",
    "leave_stage",
    "claim",
)

ROAD_SAFE_LANGREN = CommissionRecipe(
    quest_id="road_safe_langren",
    name="保证商路畅通",
    kind=CommissionKind.BATTLE,
    card_template="commission_road_safe_langren",
    log_template="commission_road_safe_langren",
    objective_template=None,
    npc_template="npc_metaya",
    objective_text="在浪人岬商店与梅塔娅对话，再通关 5-A2 初步探索",
    location=LANGREN,
    stage_flag_template="stage_flag_5_a2",
    stage_node="basic",
    stage_label="5-A2",
    awaiting_crops=frozenset(),
    flow="langren_road_safe",
    steps=_ROAD_SAFE_LANGREN_STEPS,
    summary=(
        "保证商路畅通（浪人岬）：浪人岬协会接取后离开，先在城里点「商店」建筑"
        "（不是右上背包），进店后点左下老板娘「梅塔娅」的头像，不要点她旁边的气泡，"
        "也不要点「购买」或任何商品。跳过剧情后点商店左下「离开」回城，再点「探险」"
        "进浪人岬地区。5-A2 在地图中上部，默认常常看不见；看不见时从屏幕中间往左边缘"
        "轻轻滑（手指往左，屏幕内容往右），每滑一次先找旗帜，看见就点，不要固定只滑两下。"
        "若滑了两下还没有，画面还在动就再试几次，到边还没有就停下说明。点 5-A2 的旗帜"
        "和编号，不要点旁边的对话气泡，也不要点「扫荡」。进选关页后点「初步探索」的星星；"
        "若点星星直接开打就进战斗，若出现「进入」再点「进入」，绝不点「扫荡」。"
        "战斗结束后离开选关。单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "和南赛拉姆那条同名委托不是同一条。标题、梅塔娅头像、5-A2 旗帜和初步探索节点"
        "来自表格裁切并按实机尺寸估了缩放，还没有用 1080×1920 实机截图核对。"
    ),
    tier=CommissionTier.LOW,
)


QUAKE_PROOF = CommissionRecipe(
    quest_id="quake_proof",
    name="地震防范改造",
    kind=CommissionKind.TURN_IN,
    card_template="commission_quake_proof",
    log_template="commission_quake_proof",
    objective_template=None,
    npc_template="npc_dama",
    objective_text="在南赛拉姆 4-7 与大妈对话两次",
    location=NAN_SERAM,
    stage_flag_template="stage_flag_4_7",
    stage_label="4-7",
    awaiting_crops=frozenset(),
    flow="nan_seram_quake_proof",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "find_4_7",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "claim",
    ),
    summary=(
        "地震防范改造：南赛拉姆协会接取的低级委托。"
        "离开协会后点城里「探险」进南赛拉姆地区。4-7 在地区图最左边、结晶矿洞正上方偏左，"
        "进入后无需滑动就能看到。必须先认出地标「结晶矿洞」，再点它上方带任务对话圈的 4-7 旗帜。"
        "不要点「结晶矿洞」，不要点右边的 4-6，不要点气泡，也不要点「扫荡」。"
        "看不见结晶矿洞时，即使旗帜分很高也不点。默认视角下如果同时看不到矿洞和 4-7，就停下，不要自己编滑动方向。"
        "进 4-7 选关页后点左下「大妈」的头像（不要点气泡、进入或扫荡），跳过剧情；"
        "然后再点一次大妈的头像并再跳过一次剧情。这条要对话两次，不是一次。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和大妈头像来自表格裁切并按实机尺寸估了缩放，结晶矿洞和 4-7、4-6 来自用户提供的实机地标图。"
    ),
    tier=CommissionTier.LOW,
)

COLLECT_REPAIR = CommissionRecipe(
    quest_id="collect_repair",
    name="收集维修材料",
    kind=CommissionKind.TURN_IN,
    card_template="commission_collect_repair",
    log_template="commission_collect_repair",
    objective_template=None,
    npc_template="npc_repair_worker",
    objective_text="在南赛拉姆 4-2 与维修工人对话两次",
    location=NAN_SERAM,
    stage_flag_template="stage_flag_4_2",
    stage_label="4-2",
    awaiting_crops=frozenset(),
    flow="nan_seram_collect_repair",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "find_4_2",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "claim",
    ),
    summary=(
        "收集维修材料：南赛拉姆协会接取的低级委托。"
        "离开协会后点城里「探险」进南赛拉姆地区。4-2 在地区图最右边、地下遗迹左边，"
        "进探索后如果看不见，就往右大划（手指左滑，划到底），把右边拉进画面。"
        "到边靠画面还动不动判断，到了右边界还没有就停下，不要自己编别的滑动方向。"
        "必须先认出地标「地下遗迹」，再点它左边带任务对话圈的 4-2 旗帜。"
        "不要点「地下遗迹」，不要点气泡，不要点下方的 4-1、左边的 4-3 或中间的 4-Z，也不要点「扫荡」。"
        "看不见地下遗迹时，即使旗帜分很高也不点。"
        "进 4-2 选关页后点左下「维修工人 / 维修升降机的大叔」的头像（不要点气泡、进入或扫荡），跳过剧情；"
        "然后再点一次维修工人的头像并再跳过一次剧情。这条要对话两次，不是一次。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和维修工人头像来自表格裁切并按实机尺寸估了缩放，地下遗迹和 4-2、4-1、4-3 来自用户提供的南赛拉姆地区图。"
    ),
    tier=CommissionTier.LOW,
)



SLIME_INVASION = CommissionRecipe(
    quest_id="slime_invasion",
    name="史莱姆入侵",
    kind=CommissionKind.BATTLE,
    card_template="commission_slime_invasion",
    log_template="commission_slime_invasion",
    objective_template=None,
    npc_template="npc_slime_youth",
    objective_text="在莉莉托斯 1-3 与青年对话两次后战斗",
    location=LILITOS,
    stage_flag_template="stage_flag_1_3",
    stage_label="1-3",
    awaiting_crops=frozenset(),
    flow="lilitos_slime_invasion",
    steps=(
        "accept_board",
        "leave_association",
        "explore",
        "find_1_3",
        "talk_on_stage",
        "skip_story",
        "talk_on_stage",
        "skip_story",
        "battle",
        "claim",
    ),
    summary=(
        "史莱姆入侵：莉莉托斯协会接取的低级战斗委托。"
        "离开协会后点城里「探险」进莉莉托斯地区。1-3 在甜蜜幻窟上面，进入探索后无需滑动就能看到。"
        "必须先认出地标「甜蜜幻窟」，再点它上面带任务对话圈的 1-3 旗帜。"
        "不要点「甜蜜幻窟」，不要点气泡，不要点左边的 1-2、右边的 1-4 或其他 1-1，也不要点「扫荡」。"
        "看不见甜蜜幻窟时，即使旗帜分很高也不点。默认视角下如果同时看不到甜蜜幻窟和带对话圈的 1-3，就停下，不要自己编滑动方向。"
        "进 1-3 选关页后点左下「青年 / 年轻的小哥」的头像（不要点气泡、进入或扫荡），跳过剧情；"
        "然后再点一次青年的头像并再跳过一次剧情。这条要对话两次，第二次对话后进入战斗。"
        "这场战斗大约 12 秒，只针对这条委托；仍等到「战斗胜利」再点继续，不会把 12 秒套到其他委托上。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和青年头像来自表格裁切并按实机尺寸估了缩放；1-3 旗帜和甜蜜幻窟沿用已有模板，1-2、1-4 来自用户提供的莉莉托斯地区图。"
    ),
    tier=CommissionTier.LOW,
)


PROTECT_REPAIRMAN = CommissionRecipe(
    quest_id="protect_repairman",
    name="保护维修工",
    kind=CommissionKind.BATTLE,
    card_template="commission_protect_repairman",
    log_template="commission_protect_repairman",
    objective_template=None,
    npc_template="npc_repair_worker",
    objective_text="在南赛拉姆 4-2 与维修工人对话两次后战斗",
    location=NAN_SERAM,
    stage_flag_template="stage_flag_4_2",
    stage_label="4-2",
    awaiting_crops=frozenset(),
    flow="nan_seram_protect_repairman",
    steps=(
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
    ),
    summary=(
        "保护维修工：南赛拉姆协会接取的低级战斗委托，和「收集维修材料」不是同一条，但都在 4-2 找维修工人。"
        "离开协会后点城里「探险」进南赛拉姆地区。4-2 在地区图最右边、地下遗迹左边，"
        "进探索后如果看不见，就往右大划（手指左滑，划到底），把右边拉进画面。"
        "到边靠画面还动不动判断，到了右边界还没有就停下，不要自己编别的滑动方向。"
        "必须先认出地标「地下遗迹」，再点它左边带任务对话圈的 4-2 旗帜。"
        "不要点「地下遗迹」，不要点气泡，不要点下方的 4-1、左边的 4-3 或中间的 4-Z，也不要点「扫荡」。"
        "看不见地下遗迹时，即使旗帜分很高也不点。"
        "进 4-2 选关页后点左下「维修工人 / 维修升降机的大叔」的头像（不要点气泡、进入或扫荡），跳过剧情；"
        "然后再点一次维修工人的头像并再跳过一次剧情。二次对话后进入战斗。"
        "先打完并在胜利页点「触摸继续」，再领取战斗奖励（「获得物品」上点「触摸继续」）。领取战斗奖励之后才会出现对话，这时再点「跳过剧情」。不是看见胜利就点跳过，也不会在战斗中途或领奖前点跳过。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题来自表格裁切并按实机尺寸估了缩放；4-2 旗帜、地下遗迹和维修工人头像沿用前面「收集维修材料」已有的裁切。"
        "这条原本就是低级，没有改成中级或高级。"
    ),
    tier=CommissionTier.LOW,
)

ROAD_SAFE_NAN_SERAM = CommissionRecipe(
    quest_id="road_safe_nan_seram",
    name="保证商路畅通",
    kind=CommissionKind.BATTLE,
    card_template="commission_road_safe_nan_seram",
    log_template="commission_road_safe_nan_seram",
    objective_template=None,
    npc_template="npc_mejita",
    objective_text="在南赛拉姆商店与梅姬塔对话，再通关 4-21 初步探索",
    location=NAN_SERAM,
    stage_flag_template="stage_flag_4_21",
    stage_node="basic",
    stage_label="4-21",
    awaiting_crops=frozenset(),
    flow="nan_seram_road_safe",
    steps=(
        "accept_board",
        "leave_association",
        "enter_shop",
        "talk_mejita",
        "skip_story",
        "leave_shop",
        "explore",
        "find_4_21",
        "enter_4_21_basic",
        "battle",
        "claim",
    ),
    summary=(
        "保证商路畅通（南赛拉姆）：南赛拉姆协会接取的低级战斗委托，"
        "和浪人岬那条同名委托不是同一条。单独跑时必须加 --location 南赛拉姆，"
        "例如 .\\.venv\\Scripts\\python.exe main.py --live --quest 保证商路畅通 --location 南赛拉姆。"
        "协会接取后离开，点城里「商店」（不点气泡、协会、酒馆或探险），"
        "进店后点「梅姬塔 / 商店的老板娘」的头像（不点气泡，也不点「购买全部」「购买」「离开」「时装」「兑换」或「氪金」），"
        "跳过剧情，再点「离开」回城。"
        "然后点「探险」进南赛拉姆地区。进入探索后不用滑动就能看到 4-21，它在画面右下。"
        "必须先认出 4-C1 左边的青顶小屋，再点它右上方带任务对话圈的 4-21 旗帜。"
        "不要点小屋，不要点气泡，不要点左边的 4-22、更左边的 4-23、下面的 4-C1，"
        "也不要点底部「矿洞」「回程」「探索队」，更不要点「扫荡」或「结晶矿洞」。"
        "看不见小屋和带对话圈的 4-21 时不要自行滑动，即使旗帜分很高也不点，停下即可。"
        "进 4-21 选关页后点「初步探索」的星星；战斗自己开始就进入战斗，出现「进入」再点「进入」。不要点「扫荡」，也不要点深入或完全探索。"
        "单条跑完不点「完成」，六次都做完后用 --live --claim 一起领。"
        "标题和初步探索来自表格裁切并按实机尺寸估了缩放；梅姬塔、4-21 旗帜和 4-C1 旁小屋来自用户 2026-11-20 提供的金币商店和南赛拉姆地区图。"
        "这条原本就是低级，没有改成中级或高级。"
    ),
    tier=CommissionTier.LOW,
)

# 高、中、低各按从图1到图9的地区顺序。同地区里保持表中的先后。
ALL_RECIPES: tuple[CommissionRecipe, ...] = (
    ZHAZHA_BULIN,
    SLIME_INVASION,
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
    QUAKE_PROOF,
    COLLECT_REPAIR,
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
