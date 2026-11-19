"""每日委托：共用动词 + 每条委托一份短配方。

类型1「喳喳布林入侵」（战斗，画面原文是「喳喳」）：
  世界地图（若停在南赛拉姆则下滑露出王城莉莉托斯）→ 城内协会
  → 右下角「委托」→ 委托中心点卡片 → 任务详情点「接收」
  → 用卡片右上返回关闭详情和列表（等关窗动画）→ 协会「离开」
  → 城内右下「探险」→ 关卡图点带「1-3」字样的旗帜
  → 点左下角小孩头像（不要点边缘气泡）→ 右上「跳过剧情」，直接进入战斗
  → 战斗中不操作；只有中途出现「跳过剧情」才点右上角。等到「战斗胜利」再点「触摸继续」
  → 若有战后剧情再跳过 → 回到 1-3 后点右上带绿勾的任务卷轴
  → 在任务日志点该委托标题打开详情 → 点详情中下部「完成」
  → 在「获得物品」上点「触摸继续」。

类型2「仇恨会令我成长」（交物品；通用开头，从哪座城开始都可以）：
  若不在图兰顿沙漠：城内点「大地图」，协会则「离开」，委托列表则返回
  → 阿格莱恩上若看不见「前往克里斯汀」，先上滑露出南边页签，再点它
  → 克里斯汀点「图兰顿沙漠」进城（位置已记在图谱里）
  → 协会「委托」→ 点这张卡 → 「接收」
  → 返回并离开，回到城内点冒险者的脸（不要点三点气泡）
  → 「跳过剧情」。圣遗物已在背包时就此上交，不必去要塞或战斗
  → 卷轴绿勾 → 点标题 → 米色「完成」→ 「获得物品」。

类型3「“热情”的冒险者」（多场战斗，只打图九 9-7-1 三次；开头同样走图谱）：
  阿格莱恩点「前往克里斯汀」页签（看不见就先上滑，不点左下「离开」）→ 图兰顿沙漠
  → 协会「委托」→ 紫色卡片 → 「接收」→ 返回并离开
  → 城内「探险」→ 图兰顿沙漠地区点 9-7 → 初步探索已选中时点金色「进入」
  → 「事件」弹窗点「确定」再关掉掉落，不计数，然后重新进入
  → 「战斗即将开始」后不点击；「战斗胜利」才算 1 次，再关掉掉落
  → 三次后选关页「离开」，关卡图「回程」
  → 点城内冒险者的脸 → 「跳过剧情」→ 卷轴绿勾 → 标题 → 米色「完成」→ 「获得物品」。

未收录的中间页会先跳过，等到能识别的画面再继续。任何阶段都不点「扫荡」。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import numpy as np

from src import config
from src.tasks.base import PlannedAction, StepResult, TaskBase
from src.tasks.phase import Phase
from src.tasks.priority_flows import (
    _pick_sweep_card,
    _sweep_leave_board,
    close_open_bag,
    plan_priority,
    reset_item_check,
)
from src.tasks.recipes import CommissionKind, CommissionRecipe, ZHAZHA_BULIN
from src.tasks import navigation, verbs
from src.vision.bubble import find_explore_nodes, select_node_by_bubble
from src.vision.classify import Classification, classify_scene
from src.vision.match import find_template
from src.vision.ocr import OcrProvider
from src.vision.templates import TemplateSpec, load_templates, templates_by_id
from src.vision.types import Match, Scene

logger = logging.getLogger("myrzx.task.daily_commission")

# 旧测试和外部代码仍从本模块引用这两段文案。
CARD_MISSING_MESSAGE = verbs.card_missing_message(config.PRIORITY_COMMISSION)
CLAIM_DONE_MESSAGE = verbs.claim_done_message(config.PRIORITY_COMMISSION)

NPC_OR_BUBBLE_MISSING_MESSAGE = (
    "已进入莉莉托斯近郊 1-3。这条委托需要先点击左下角小孩头像对话"
    "（不要点边缘的对话气泡），再点右上「跳过剧情」直接进入战斗。"
    "本帧没有匹配到小孩，也没有任务气泡。不会点击「进入」或「扫荡」。"
)

BATTLE_WAIT_MESSAGE = (
    "已进入战斗，自动战斗开启，不要点击。轮询截图直到出现「战斗胜利」。"
    "若中途弹出剧情，再点右上「跳过剧情」。不会点「扫荡」。"
)

SKIP_UNKNOWN_MESSAGE = (
    "出现了尚未收录的中间页。先跳过这一帧，等到能识别的画面再继续，"
    "而不是臆造点击。"
)

_SCROLL_MESSAGE = (
    "战斗已结束，点击右上带绿勾的任务卷轴打开任务日志（不要点邮件或背包）。"
)
_TURN_IN_SCROLL_MESSAGE = (
    "任务卷轴已出现绿色完成勾。点击卷轴本体打开任务日志，不要点旁边的邮件或背包。"
)
_CHILD_MESSAGE = (
    "点击左下角小孩头像（不要点边缘对话气泡）。对话出现后点右上「跳过剧情」，会直接进入战斗。"
)
_ADVENTURER_MESSAGE = (
    "点击城内左下角「冒险者」的脸，不要点脸右侧的三点气泡。"
    "对话出现后点右上「跳过剧情」。"
)


class DailyCommissionTask(TaskBase):
    name = "daily_commission"

    def __init__(
        self,
        specs: Sequence[TemplateSpec] | None = None,
        ocr: OcrProvider | None = None,
        recipe: CommissionRecipe | None = None,
    ) -> None:
        super().__init__()
        self.specs = list(specs) if specs is not None else load_templates()
        self.by_id = templates_by_id(self.specs)
        self.ocr = ocr
        self.recipe = recipe if recipe is not None else ZHAZHA_BULIN
        self.phase = Phase.ACCEPT
        self.awaiting_enter = False
        self.map_swipes = 0
        self.crystia_reveal_swipes = 0
        self.battle_started_at: float | None = None
        self.loot_claimed = False
        self.fights_done = 0
        self.victory_counted = False
        self.loot_kind: str | None = None
        self.step_index = 0
        self.step_armed = False
        self.node_selected = False
        self.title_reader = None
        self.saw_continent = False
        self.pending_city = None
        self._pan_key: str | None = None
        self._match_cache: dict[str, Match | None] = {}
        self.auto_sweep = False
        self.sweep = None
        self.sweep_move_next = False
        self.item_ready = None
        self.bag_swipes = 0
        self.bag_tab_ready = False

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        self._match_cache = {}
        classification = classify_scene(image_bgr, self.specs, ocr=self.ocr)
        for match in classification.matches:
            self._match_cache.setdefault(match.template_id, match)
        self.log.info("识别结果: %s", classification.brief())
        scene = classification.scene
        kind = self.recipe.kind
        multi = kind is CommissionKind.MULTI_BATTLE
        if scene is not Scene.VICTORY:
            self.victory_counted = False
        skip = verbs.best_of(self, image_bgr, ("skip_story", "skip_story_tight"))
        if skip is not None or scene is Scene.STORY_DIALOG:
            steps = self.recipe.steps
            if steps and "skip_story" in steps and self.recipe.flow:
                current = steps[self.step_index] if self.step_index < len(steps) else ""
                if current != "skip_story" and self.phase is Phase.ACCEPT:
                    # 协会对话已经开始，不能再把阶段留在 ACCEPT，否则导航会重新点协会。
                    self.phase = Phase.GO_STAGE
                    self.step_index = steps.index("skip_story")
                    current = "skip_story"
                if current == "skip_story":
                    self.step_armed = True
            return verbs.skip_story(
                self,
                image_bgr,
                classification,
                "点击右上角「跳过剧情」。不要点对话框里的其他地方。",
            )
        if self._require(image_bgr, "ui_bag_title") is not None:
            # 背包开着时不要当未知页去点回程或乱滑。
            if self.recipe.flow:
                return plan_priority(self, image_bgr, classification)
            closed = close_open_bag(self, image_bgr, classification)
            if closed is not None:
                return closed
        if (
            self.auto_sweep
            and self.sweep is not None
            and self.sweep_move_next
            and scene not in {Scene.COMMISSION_LIST, Scene.QUEST_DETAIL}
        ):
            stopped = self._advance_sweep(classification)
            if stopped is not None:
                return stopped
            if scene is Scene.ASSOCIATION:
                # 刚看完这座城的列表，先离开协会再去下一站，不要又把「委托」点开。
                place = self._place()
                dest = place.name if place is not None else "下一站"
                return verbs.leave_room(
                    self,
                    image_bgr,
                    classification,
                    Scene.ASSOCIATION,
                    f"这一档在这座城已经看完。点击「离开」回城，再去「{dest}」。"
                    "不要再点「委托」。",
                )
        if (
            self.phase is Phase.IN_BATTLE
            and kind in {CommissionKind.BATTLE, CommissionKind.MULTI_BATTLE}
            and scene in {Scene.UNKNOWN, Scene.BATTLE}
        ):
            # 进战之后即使暂时认不出画面，也继续等胜利，不要先走大地图导航。
            return self._plan_battle(image_bgr, classification)
        nav = navigation.step(self, image_bgr, classification)
        if nav is not None:
            return nav
        if self.recipe.flow:
            return plan_priority(self, image_bgr, classification)
        if scene in {Scene.CITY_LILITOS, Scene.CITY_TURANDON}:
            place = self._place()
            if place and place.city_scene is not None and scene is not place.city_scene:
                return self._plan_open_world_map(image_bgr, classification, scene)
            if multi:
                return self._plan_multi_city(image_bgr, classification)
            if kind is CommissionKind.TURN_IN:
                return self._plan_turn_in_city(image_bgr, classification)
            return self._plan_city(image_bgr, classification)
        if scene is Scene.ASSOCIATION:
            return self._plan_association(image_bgr, classification)
        if scene is Scene.COMMISSION_LIST:
            return self._plan_commission_list(image_bgr, classification)
        if scene is Scene.QUEST_DETAIL:
            return self._plan_quest_detail(image_bgr, classification)
        if scene is Scene.STAGE_MAP and kind is CommissionKind.BATTLE:
            return self._plan_stage_map(image_bgr, classification)
        if scene is Scene.STAGE_DESERT and multi:
            return self._plan_desert_map(image_bgr, classification)
        if scene in {Scene.STAGE_9_7, Scene.STAGE_1_3} and multi:
            return self._plan_stage_9_7(image_bgr, classification)
        if scene is Scene.STAGE_1_3 and kind is CommissionKind.BATTLE:
            return self._plan_stage_1_3(image_bgr, classification)
        if scene is Scene.STAGE_EVENT and multi:
            return self._plan_stage_event(image_bgr, classification)
        if scene is Scene.STORY_DIALOG:
            return self._plan_story_dialog(image_bgr, classification)
        if scene is Scene.BATTLE and kind in {CommissionKind.BATTLE, CommissionKind.MULTI_BATTLE}:
            return self._plan_battle(image_bgr, classification)
        if scene is Scene.VICTORY and kind is CommissionKind.BATTLE:
            return self._plan_victory(image_bgr, classification)
        if scene is Scene.VICTORY and multi:
            return self._plan_multi_victory(image_bgr, classification)
        if scene is Scene.QUEST_LOG:
            return self._plan_quest_log(image_bgr, classification)
        if scene is Scene.LOOT_REWARD and multi:
            return self._plan_multi_loot(image_bgr, classification)
        if scene is Scene.LOOT_REWARD:
            return self._plan_loot(image_bgr, classification)
        if self.phase is Phase.DONE:
            return self._done(classification)
        if self.phase is Phase.IN_BATTLE and kind in {
            CommissionKind.BATTLE,
            CommissionKind.MULTI_BATTLE,
        }:
            return self._plan_battle(image_bgr, classification)
        if self.phase in {Phase.GO_STAGE, Phase.IN_BATTLE, Phase.CLAIM}:
            return StepResult(
                scene=Scene.UNKNOWN,
                reason=classification.reason,
                matches=classification.matches,
                action=PlannedAction(
                    kind="wait",
                    label="跳过未收录的中间页",
                    message=SKIP_UNKNOWN_MESSAGE,
                ),
                status="skip_unknown",
                message=SKIP_UNKNOWN_MESSAGE,
            )
        return StepResult(
            scene=Scene.UNKNOWN,
            reason=classification.reason,
            matches=classification.matches,
            action=PlannedAction(
                kind="halt",
                label="无法识别页面",
                message="请确认模拟器窗口画面，或补充新的截图与模板。",
            ),
            status="unknown",
            message="未能识别当前页面，停止以免误点。",
        )

    def _advance_sweep(self, clf) -> StepResult | None:
        """当前档在这座城已经看完，换下一张图；这一档没了就换下一档，从第1图再来。"""
        self.sweep_move_next = False
        if self.sweep is None:
            return None
        if not self.sweep.advance_place_or_tier():
            self.phase = Phase.DONE
            message = (
                f"高、中、低三档都看过了，共做了 {self.sweep.completed} 次。"
                "先不点「完成」。可用 --live --claim 一起领。"
            )
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="扫城结束", message=message),
                status="done",
                message=message,
            )
        self.recipe = self.sweep.travel_recipe()
        self.phase = Phase.ACCEPT
        self.step_index = 0
        self.step_armed = False
        self.node_selected = False
        reset_item_check(self)
        return None

    def _place(self):
        """这条委托要去的地点。没有图谱记录时返回 None。"""
        return getattr(self.recipe, "location", None)

    def _plan_region_to_place(
        self, image_bgr: np.ndarray, clf: Classification
    ) -> StepResult:
        """在区域地图上走到配方记录的那座城。标题、页签或地名都能确认是哪一片。"""
        unmapped = self.recipe.unmapped_place
        if unmapped:
            missing = (
                f"「{self.recipe.name}」在「{unmapped}」。这片区域还不在地图册里，"
                "没有地名模板，也不会编造地图坐标或城市点击。补上图谱之后再走。"
            )
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="区域不在地图册", message=missing),
                status="halt_missing",
                message=missing,
            )
        place = self._place()
        if place is None:
            if clf.scene is Scene.WORLD_MAP:
                return self._plan_world(image_bgr, clf)
            missing = "当前在区域地图上，但这条委托还没有记录所属地区，停止以免误点。"
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="未记录地区", message=missing),
                status="halt_missing",
                message=missing,
            )

        matches = list(clf.matches)
        sight = navigation.recognize_region(self, image_bgr)
        if sight is not None and sight.region.id == place.region.id:
            matches = _merge_match(matches, sight.match)
            return self._plan_click_place(image_bgr, clf, matches, place)

        other_name = sight.region.name if sight is not None else None
        tab_id = place.region.inbound_tab_template
        tab = self._require(image_bgr, tab_id) if tab_id else None
        if tab is not None:
            matches = _merge_match(matches, tab)
            here = other_name or "另一片区域"
            message = (
                f"当前在「{here}」地图。点击「{place.region.inbound_tab_label}」前往「{place.region.name}」，"
                f"再进入「{place.name}」。不要点「离开」。"
            )
            return self._click_result(clf.scene, clf, matches, tab, message)

        # 阿格莱恩上整块「前往克里斯汀」还没出现：先上滑到「浪人岬」，再手指从左向右把旗帜拉全。
        on_aglaen = sight is not None and sight.region.id == "aglaen"
        if place.region.inbound_tab_template == "region_tab_crystia" and (
            on_aglaen or other_name == "阿格莱恩"
        ):
            return self._plan_swipe_toward_crystia_tab(image_bgr, clf, matches, place)

        label = place.region.inbound_tab_label or "区域页签"
        missing = (
            f"要去「{place.region.name}」的「{place.name}」，"
            f"但当前地图上没有「{label}」。不会改点「离开」或其他地名。"
        )
        return StepResult(
            scene=clf.scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到区域页签", message=missing),
            status="halt_missing",
            message=missing,
        )

    def _plan_swipe_toward_crystia_tab(
        self,
        image_bgr: np.ndarray,
        clf: Classification,
        matches: list[Match],
        place,
    ) -> StepResult:
        """整块「前往克里斯汀」还没对上。

        先手指上划到南边的「浪人岬」。旗帜往往只在左边缘露出右半截，
        这时手指从左向右滑，把屏外的左边拉进画面，整块对上再点。
        """
        if self._require(image_bgr, "world_langren") is not None:
            return self._swipe_right_to_reveal_crystia_tab(
                image_bgr, clf, matches, place
            )
        if self.map_swipes < config.MAP_SWIPE_MAX:
            self.map_swipes += 1
            height, width = image_bgr.shape[:2]
            x1, y1 = width // 2, int(height * 0.62)
            x2, y2 = width // 2, int(height * 0.32)
            action = PlannedAction(
                kind="swipe",
                label="向上滑动地图",
                x=x1,
                y=y1,
                x2=x2,
                y2=y2,
                message=(
                    "当前是阿格莱恩大地图。停在最上侧时看不到南边的「浪人岬」和「前往克里斯汀」，"
                    "不要假设旗帜已经在画面上。手指上划，把视野往南边海边拉。"
                    "看到「浪人岬」之后，手指再从左向右滑，把被切在左边缘的「前往克里斯汀」整块拉出来再点。"
                    f"然后前往「{place.region.name}」的「{place.name}」。"
                    f"第 {self.map_swipes}/{config.MAP_SWIPE_MAX} 次南滑。"
                    "不要点左下「离开」，也不要进王城莉莉托斯。"
                ),
            )
            return StepResult(
                scene=Scene.WORLD_MAP,
                reason=clf.reason,
                matches=matches,
                action=action,
                status="continue",
                message=action.message,
            )
        missing = (
            f"已向上滑动地图 {config.MAP_SWIPE_MAX} 次，还没看到「浪人岬」，"
            "也没有整块「前往克里斯汀」。不会改点「离开」或「王城莉莉托斯」。"
        )
        return StepResult(
            scene=Scene.WORLD_MAP,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到前往克里斯汀", message=missing),
            status="halt_missing",
            message=missing,
        )

    def _swipe_right_to_reveal_crystia_tab(
        self,
        image_bgr: np.ndarray,
        clf: Classification,
        matches: list[Match],
        place,
    ) -> StepResult:
        """南边已经有「浪人岬」。旗帜被切在左边缘时，手指从左向右滑。"""
        if self.crystia_reveal_swipes < config.MAP_SWIPE_MAX:
            self.crystia_reveal_swipes += 1
            height, width = image_bgr.shape[:2]
            y = int(height * 0.72)
            # 手指从左往右。内容跟着向右移，左边被切掉的旗帜才进画面。
            x1, x2 = int(width * 0.22), int(width * 0.78)
            action = PlannedAction(
                kind="swipe",
                label="向右滑动地图",
                x=x1,
                y=y,
                x2=x2,
                y2=y,
                message=(
                    "南边已经能看到「浪人岬」。「前往克里斯汀」还被切在左边缘，"
                    "只露出右半截时不能点。手指从左向右滑，把左边的内容拉进画面，"
                    "直到「前」「往」和两侧箭头整块对上再点，"
                    f"然后进入「{place.name}」。"
                    f"第 {self.crystia_reveal_swipes}/{config.MAP_SWIPE_MAX} 次向右滑动。"
                    "不要点左下「离开」，也不要再往左推。"
                ),
            )
            return StepResult(
                scene=Scene.WORLD_MAP,
                reason=clf.reason,
                matches=matches,
                action=action,
                status="continue",
                message=action.message,
            )
        missing = (
            f"已经看到「浪人岬」，并手指从左向右滑动 {config.MAP_SWIPE_MAX} 次，"
            "仍然没有整块「前往克里斯汀」。不会点露出来的半截，也不会点左下「离开」。"
        )
        return StepResult(
            scene=Scene.WORLD_MAP,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到前往克里斯汀", message=missing),
            status="halt_missing",
            message=missing,
        )

    def _plan_click_place(
        self,
        image_bgr: np.ndarray,
        clf: Classification,
        matches: list[Match],
        place,
    ) -> StepResult:
        del matches
        return navigation.click_or_pan_to_place(self, image_bgr, clf, place)

    def _plan_open_world_map(
        self,
        image_bgr: np.ndarray,
        clf: Classification,
        scene: Scene,
        *,
        here: str | None = None,
        returning: bool = False,
    ) -> StepResult:
        place = self._place()
        target = f"「{place.name}」" if place else "目标城市"
        current = f"「{here}」" if here else "城内"
        match = navigation.find_city_world_map(self, image_bgr)
        matches = list(clf.matches)
        if returning:
            click_message = (
                "先退回大地图，直到看见「阿格莱恩」或「克里斯汀」。"
                f"当前在{current}，点「大地图」三个字。"
                "不点本城的「协会」「探险」「农场」「商店」「酒馆」「挑战任务」或对话气泡。"
            )
            missing = (
                f"要先从{current}退回大地图，但没有匹配到「大地图」三个字。"
                "不会点本城的「协会」「探险」「农场」「商店」「酒馆」，也不会编造点击。"
            )
        else:
            click_message = (
                f"当前在{current}，目标是{target}。"
                "点击「大地图」回到所属大区地图。"
                "不会点本城的「协会」「探险」「农场」「商店」「酒馆」。"
            )
            missing = (
                f"当前在{current}，目标是{target}，但没有匹配到「大地图」。"
                "不会改点本城的「协会」或「探险」。"
            )
        if match is not None:
            matches = _merge_match(matches, match)
            return self._click_result(
                scene,
                clf,
                matches,
                match,
                click_message,
            )
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到大地图", message=missing),
            status="halt_missing",
            message=missing,
        )

    def _plan_turn_in_region(
        self, image_bgr: np.ndarray, clf: Classification
    ) -> StepResult:
        """兼容旧名字：区域地图一律按图谱走到目标城市。"""
        return self._plan_region_to_place(image_bgr, clf)

    def _plan_turn_in_city(
        self, image_bgr: np.ndarray, clf: Classification
    ) -> StepResult:
        """图兰顿城内：接取前点协会；之后点脸或带绿勾的卷轴。不点「探险」。"""
        scene = clf.scene
        if self.phase is Phase.ACCEPT:
            match = verbs.best_of(
                self,
                image_bgr,
                ("city_turandon_association", "city_association"),
            )
            matches = list(clf.matches)
            if match is not None:
                matches = _merge_match(matches, match)
                return self._click_result(scene, clf, matches, match, "进入协会。")
            missing = "已识别为图兰顿沙漠城内，但没有匹配到「协会」。"
            return StepResult(
                scene=scene,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(kind="halt", label="未找到协会", message=missing),
                status="halt_missing",
                message=missing,
            )

        opened = verbs.open_quest_scroll(
            self,
            image_bgr,
            clf,
            scene,
            _TURN_IN_SCROLL_MESSAGE,
        )
        if opened is not None:
            return opened
        talked = verbs.talk_portrait(
            self,
            image_bgr,
            clf,
            scene,
            self.recipe.npc_template,
            _ADVENTURER_MESSAGE,
        )
        if talked is not None:
            return talked
        waiting = (
            "城内还没有可对话的冒险者，卷轴上也没有完成勾。"
            "先等下一帧，不点「探险」，也不点「扫荡」。"
        )
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=list(clf.matches),
            action=PlannedAction(kind="wait", label="等待冒险者", message=waiting),
            status="skip_unknown",
            message=waiting,
        )

    def _plan_multi_city(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """图兰顿城内：接取前点协会；没打完点「探险」；打完点脸或绿勾卷轴。"""
        scene = clf.scene
        required = self.recipe.fights_required
        if self.fights_done >= required:
            opened = verbs.open_quest_scroll(
                self,
                image_bgr,
                clf,
                scene,
                "三次正式战斗已经打完。点击带绿勾的任务卷轴，不要点旁边的邮件或背包。",
            )
            if opened is not None:
                return opened
            talked = verbs.talk_portrait(
                self,
                image_bgr,
                clf,
                scene,
                self.recipe.npc_template,
                "点击左下角冒险者的脸，不要点右侧三点气泡。对话后再点「跳过剧情」。",
            )
            if talked is not None:
                return talked
            waiting = (
                "三次战斗已经打完。城内还没有冒险者的脸，卷轴上也没有完成勾。"
                "先等下一帧，不点「探险」，也不点「扫荡」。"
            )
            return StepResult(
                scene=scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="wait", label="等待冒险者", message=waiting),
                status="skip_unknown",
                message=waiting,
            )
        if self.phase is Phase.ACCEPT:
            match = verbs.best_of(
                self,
                image_bgr,
                ("city_turandon_association", "city_association"),
            )
            matches = list(clf.matches)
            if match is not None:
                matches = _merge_match(matches, match)
                return self._click_result(scene, clf, matches, match, "进入协会。")
            missing = "已在图兰顿沙漠城内，但没有匹配到「协会」。"
            return StepResult(
                scene=scene,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(kind="halt", label="未找到协会", message=missing),
                status="halt_missing",
                message=missing,
            )
        return self._click_or_missing(
            image_bgr,
            clf,
            scene,
            "city_explore",
            click_message="接取后从城内右下「探险」进入图兰顿沙漠地区，去打 9-7。不点「扫荡」。",
            missing_label="未找到探险",
            missing_message="已在城内，但没有匹配到右下「探险」。不会改点别的建筑。",
        )

    def _plan_desert_map(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """图兰顿沙漠地区：没打完点 9-7；打完点「回程」。"""
        required = self.recipe.fights_required
        if self.fights_done >= required:
            return self._click_or_missing(
                image_bgr,
                clf,
                Scene.STAGE_DESERT,
                "stage_return",
                click_message="三次正式战斗已完成。点左下「回程」回到图兰顿沙漠城内。",
                missing_label="未找到回程",
                missing_message="要回城，但没有匹配到「回程」。不会改点「矿洞」或「探索队」。",
            )
        flag = self.recipe.stage_flag_template or "stage_flag_9_7"
        return self._click_or_missing(
            image_bgr,
            clf,
            Scene.STAGE_DESERT,
            flag,
            click_message="在图兰顿沙漠地区点击 9-7。这条委托只打这一关。",
            missing_label="未找到 9-7",
            missing_message="已在图兰顿沙漠地区，但没有匹配到 9-7，不会改点其他旗帜。",
        )

    def _plan_stage_9_7(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """巡逻走廊 9-7：左侧「初步探索」时点「进入」；满三次后点左下「离开」。"""
        matches = list(clf.matches)
        title = self._require(image_bgr, "stage_9_7_title")
        if title is not None:
            matches = _merge_match(matches, title)
        if title is None:
            missing = "这不是巡逻走廊 9-7。不会在这里点「进入」或「扫荡」。"
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(kind="halt", label="不是 9-7", message=missing),
                status="halt_missing",
                message=missing,
            )
        required = self.recipe.fights_required
        if self.fights_done >= required:
            return verbs.leave_stage_select(
                self,
                image_bgr,
                clf,
                Scene.STAGE_9_7,
                f"已完成 {self.fights_done}/{required} 次正式战斗。点左下「离开」，不要点「扫荡」。",
            )
        basic = verbs.best_of(self, image_bgr, ("stage_node_basic", "stage_node_basic_09"))
        if basic is not None:
            matches = _merge_match(matches, basic)
        width = image_bgr.shape[1]
        if basic is None or basic.box.center[0] > width * 0.45:
            missing = "9-7 上没有在左侧看到「初步探索」。不会改点深入或完全，也不会点「扫荡」。"
            return StepResult(
                scene=Scene.STAGE_9_7,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(kind="halt", label="未选初步探索", message=missing),
                status="halt_missing",
                message=missing,
            )
        return verbs.press_stage_enter(
            self,
            image_bgr,
            clf,
            Scene.STAGE_9_7,
            "stage_enter_gold",
            f"9-7-1「初步探索」已在左侧。点金色「进入」。"
            f"当前 {self.fights_done}/{required} 次正式战斗。不要点「扫荡」。",
            matches=matches,
        )

    def _plan_stage_event(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """特殊事件不算次数。点「确定」正中，随后的掉落页也不计数。"""
        self.loot_kind = "event"
        return verbs.confirm_dialog(
            self,
            image_bgr,
            clf,
            "stage_event_ok",
            "这是特殊事件，不计入三次战斗。点「确定」正中，关掉掉落后再点「进入」。",
            Scene.STAGE_EVENT,
        )

    def _plan_multi_victory(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """「战斗胜利」才算一次。同一张胜利页重复规划不重复计数。"""
        required = self.recipe.fights_required
        if not self.victory_counted:
            self.fights_done += 1
            self.victory_counted = True
        self.loot_kind = "victory"
        self.battle_started_at = None
        if self.phase in {Phase.ACCEPT, Phase.GO_STAGE}:
            self.phase = Phase.IN_BATTLE
        matches = list(clf.matches)
        touch = self._require(image_bgr, "touch_continue")
        message = (
            f"正式战斗胜利，记为第 {self.fights_done}/{required} 次。"
            "点「触摸继续」。事件弹窗不会计入。"
        )
        if touch:
            matches = _merge_match(matches, touch)
            return self._click_result(Scene.VICTORY, clf, matches, touch, message)
        height, width = image_bgr.shape[:2]
        x, y = width // 2, int(round(height * 1295 / 1920))
        action = PlannedAction(
            kind="click",
            label="触摸继续",
            x=x,
            y=y,
            message=message,
        )
        return StepResult(
            scene=Scene.VICTORY,
            reason=clf.reason,
            matches=matches,
            action=action,
            status="continue",
            message=action.brief(),
        )

    def _plan_multi_loot(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        """事件掉落和战斗掉落都只关掉。任务结算只在领取阶段。"""
        kind = self.loot_kind
        self.loot_kind = None
        required = self.recipe.fights_required
        if kind == "event":
            return verbs.dismiss_loot(
                self,
                image_bgr,
                clf,
                finishes_quest=False,
                message="事件掉落，不增加战斗次数。关掉后回到选关，再点「进入」。",
            )
        if kind == "victory":
            return verbs.dismiss_loot(
                self,
                image_bgr,
                clf,
                finishes_quest=False,
                message=(
                    f"战斗掉落。当前已完成 {self.fights_done}/{required} 次正式战斗。"
                    "关掉后回到 9-7。"
                ),
            )
        if self.phase is Phase.CLAIM:
            return verbs.dismiss_loot(self, image_bgr, clf)
        return verbs.dismiss_loot(
            self,
            image_bgr,
            clf,
            finishes_quest=False,
            message="这不是任务结算。关掉后继续，不增加战斗次数。",
        )

    def _plan_world(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        matches = list(clf.matches)
        lilitos = self._require_best(image_bgr, "world_lilitos_full", "world_lilitos")
        if lilitos:
            matches = _merge_match(matches, lilitos)
            self.map_swipes = 0
            return self._click_result(
                Scene.WORLD_MAP,
                clf,
                matches,
                lilitos,
                "从阿格莱恩大地图进入王城莉莉托斯。",
            )
        south = self._require(image_bgr, "world_nan_seram")
        if south:
            matches = _merge_match(matches, south)
        if self.map_swipes < config.MAP_SWIPE_MAX:
            self.map_swipes += 1
            h, w = image_bgr.shape[:2]
            x1, y1 = w // 2, int(h * 0.42)
            x2, y2 = w // 2, int(h * 0.73)
            action = PlannedAction(
                kind="swipe",
                label="向下滑动地图",
                x=x1,
                y=y1,
                x2=x2,
                y2=y2,
                message=(
                    "当前大地图偏南，还看不到「王城莉莉托斯」。"
                    "手指下拖以露出北边的王城"
                    + ("（已看到「南赛拉姆」）。" if south else "。")
                    + f"第 {self.map_swipes}/{config.MAP_SWIPE_MAX} 次滑动。"
                ),
            )
            return StepResult(
                scene=Scene.WORLD_MAP,
                reason=clf.reason,
                matches=matches,
                action=action,
                status="continue",
                message=action.message,
            )
        return StepResult(
            scene=Scene.WORLD_MAP,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="halt",
                label="未找到王城莉莉托斯",
                message=(
                    f"已向下滑动地图 {config.MAP_SWIPE_MAX} 次，仍没有匹配到「王城莉莉托斯」。"
                ),
            ),
            status="halt_missing",
            message=f"已识别为大地图，滑动 {config.MAP_SWIPE_MAX} 次后仍未找到王城莉莉托斯。",
        )

    def _plan_city(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        if self.phase in {Phase.GO_STAGE, Phase.IN_BATTLE, Phase.CLAIM}:
            return self._click_or_missing(
                image_bgr,
                clf,
                Scene.CITY_LILITOS,
                "city_explore",
                click_message="接取后从城内右下角「探险」进入关卡图。",
                missing_label="未找到探险",
                missing_message=(
                    "已识别为城内，但本帧没有匹配到右下角「探险」。"
                    "若这是一张裁掉底栏的局部图，请换用完整城内画面。"
                ),
            )
        return self._click_or_missing(
            image_bgr,
            clf,
            Scene.CITY_LILITOS,
            "city_association",
            click_message="进入协会。",
            missing_label="未找到协会",
            missing_message="已识别为城内节点图，但没有匹配到「协会」。",
        )

    def _plan_association(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        place = self._place()
        if place and place.association_header:
            own = self._require(image_bgr, place.association_header)
            if own is None:
                other_headers = (
                    "association_lilitos_header",
                    "association_turandon_header",
                )
                for header_id in other_headers:
                    if header_id == place.association_header:
                        continue
                    other = self._require(image_bgr, header_id)
                    if other is not None:
                        return verbs.leave_room(
                            self,
                            image_bgr,
                            clf,
                            Scene.ASSOCIATION,
                            f"当前不是「{place.name}」的协会。点击「离开」回城，再经大地图前往。",
                        )
                        break
        if self.phase in {Phase.GO_STAGE, Phase.IN_BATTLE, Phase.CLAIM}:
            if self.recipe.kind is CommissionKind.TURN_IN:
                message = "委托已接取，从协会「离开」返回图兰顿沙漠城内，再去点冒险者的脸。"
            else:
                message = "委托已接取，从协会室内「离开」返回城内，再去点「探险」。"
            return verbs.leave_room(self, image_bgr, clf, Scene.ASSOCIATION, message)
        return verbs.open_commission_board(self, image_bgr, clf)

    def _plan_commission_list(
        self, image_bgr: np.ndarray, clf: Classification
    ) -> StepResult:
        matches = list(clf.matches)
        if self.phase in {Phase.GO_STAGE, Phase.IN_BATTLE, Phase.CLAIM}:
            closed = verbs.close_with_back(
                self,
                image_bgr,
                clf,
                Scene.COMMISSION_LIST,
                "委托已接取，用右上返回关闭列表，等动画后再点协会「离开」。",
            )
            if closed is not None:
                return closed
            missing = (
                "委托已接取，但没有匹配到列表右上的返回箭头，已停止以免误点其他卡片。"
            )
            return StepResult(
                scene=Scene.COMMISSION_LIST,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(kind="halt", label="未找到返回", message=missing),
                status="halt_missing",
                message=missing,
            )
        place = self._place()
        card = verbs.match_commission_card(self, image_bgr)
        if card is None and place and place.board_title:
            board = self._require(image_bgr, place.board_title)
            if board is None:
                closed = verbs.close_with_back(
                    self,
                    image_bgr,
                    clf,
                    Scene.COMMISSION_LIST,
                    f"这不是「{place.name}」协会的委托列表。点右上返回，再离开协会经大地图前往。",
                )
                if closed is not None:
                    return closed
        if self.auto_sweep and self.sweep is not None:
            # 扫城：本城当前档没有认出的卡，就关列表去下一站，不改点别的委托。
            # 单独 --quest 仍走下面的停止，避免误点其他卡片。
            picked = _pick_sweep_card(self, image_bgr, clf)
            if picked is not None:
                return picked
            return _sweep_leave_board(self, image_bgr, clf, Scene.COMMISSION_LIST)
        return verbs.accept_listed_card(self, image_bgr, clf)

    def _plan_quest_detail(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        matches = list(clf.matches)
        status_match = self._require(image_bgr, "quest_not_accepted")
        if status_match:
            matches = _merge_match(matches, status_match)
        objective_id = self.recipe.objective_template
        accepted = self._require(image_bgr, objective_id) if objective_id else None
        if accepted:
            matches = _merge_match(matches, accepted)
        finish = self._require(image_bgr, "quest_finish")
        if finish:
            matches = _merge_match(matches, finish)

        if self.phase in {Phase.CLAIM, Phase.IN_BATTLE, Phase.DONE} or finish:
            tapped = verbs.tap_finish(self, image_bgr, clf, matches)
            if tapped is not None:
                return tapped
            return StepResult(
                scene=Scene.QUEST_DETAIL,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(
                    kind="halt",
                    label="未找到完成",
                    message="已打开完成后的任务详情，但没有匹配到中下部的「完成」按钮。",
                ),
                status="halt_missing",
                message="任务详情页未找到「完成」按钮，停止以免点到返回或屏幕底部。",
            )

        received = verbs.press_receive(self, image_bgr, clf, matches)
        if received is not None:
            return received

        # 已经接过（没有「接收」，或本会话已点过接收）：关详情。
        accept = self._require(image_bgr, "quest_accept")
        if self.phase is Phase.ACCEPT and (accepted or accept is None):
            self.phase = Phase.GO_STAGE
        if self.phase is Phase.GO_STAGE:
            closed = verbs.close_with_back(
                self,
                image_bgr,
                clf,
                Scene.QUEST_DETAIL,
                "委托已接取，用卡片右上返回关闭详情（不要点屏幕底部「离开」），等动画后再关列表。",
                matches=matches,
            )
            if closed is not None:
                return closed
        if self.phase is Phase.GO_STAGE:
            return StepResult(
                scene=Scene.QUEST_DETAIL,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(
                    kind="wait",
                    label="委托已接取",
                    message="已经点过「接收」，请关闭详情后前往城内「探险」。",
                ),
                status="skip_unknown",
                message="任务详情已接取，跳过本帧，等待关卡或城内画面。",
            )
        return StepResult(
            scene=Scene.QUEST_DETAIL,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="halt",
                label="未找到接收",
                message="已识别为任务详情，但没有匹配到右下角「接收」。",
            ),
            status="halt_missing",
            message="任务详情页未找到「接收」按钮，停止。",
        )

    def _plan_stage_map(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        # 关卡图属于接取后的路径；即便本会话还没点过「接收」，只要认出这一页就继续。
        return self._click_or_missing(
            image_bgr,
            clf,
            Scene.STAGE_MAP,
            "stage_flag_1_3",
            click_message="在关卡选择图上点击带「1-3」字样的旗帜，避免点到 1-2 或 1-4。",
            missing_label="未找到 1-3",
            missing_message="已识别为关卡选择图，但没有匹配到 1-3 旗帜，不会改点其他关卡。",
        )

    def _plan_stage_1_3(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        matches = list(clf.matches)
        npc = self._require(image_bgr, "npc_child")
        if npc:
            matches = _merge_match(matches, npc)
        check = self._require(image_bgr, "quest_scroll_check")
        if check:
            matches = _merge_match(matches, check)
        scroll = self._require(image_bgr, "quest_scroll_done")
        if scroll:
            matches = _merge_match(matches, scroll)

        # 战后回到 1-3：小孩已消失，右上卷轴带绿勾。点卷轴本体，不要点邮件/背包。
        if check or scroll:
            opened = verbs.open_quest_scroll(
                self, image_bgr, clf, Scene.STAGE_1_3, _SCROLL_MESSAGE
            )
            if opened is not None:
                return opened

        # 本委托：先与小孩对话，不要先点「进入」。
        if npc:
            talked = verbs.talk_portrait(
                self,
                image_bgr,
                clf,
                Scene.STAGE_1_3,
                self.recipe.npc_template,
                _CHILD_MESSAGE,
            )
            if talked is not None:
                if self.phase in {Phase.ACCEPT, Phase.GO_STAGE}:
                    self.phase = Phase.IN_BATTLE
                return talked

        nodes = find_explore_nodes(image_bgr, self.specs, ocr=self.ocr)
        for node in nodes:
            matches = _merge_match(matches, node)
        enter = self._require(image_bgr, "stage_enter")
        if enter:
            matches = _merge_match(matches, enter)

        # 没有小孩时，保留按气泡选节点再「进入」的旧路径，作为其他委托的回退。
        if self.awaiting_enter:
            if enter:
                if self.phase is Phase.GO_STAGE:
                    self.phase = Phase.IN_BATTLE
                return self._click_result(
                    Scene.STAGE_1_3,
                    clf,
                    matches,
                    enter,
                    "已按气泡选好探索节点，点击「进入」后等待战斗，不要点「扫荡」。",
                )
            return StepResult(
                scene=Scene.STAGE_1_3,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(
                    kind="halt",
                    label="等待进入",
                    message=(
                        "已经按气泡选好探索节点，但本帧没有「进入」按钮"
                        "（可能是局部裁切）。请提供带「进入」的 1-3 全屏再继续。"
                    ),
                ),
                status="halt_need_next_screen",
                message="已按气泡选好节点，下一步应点击「进入」，但本帧找不到该按钮。",
            )

        selection = select_node_by_bubble(image_bgr, self.specs, ocr=self.ocr)
        if selection is not None:
            matches = _merge_match(matches, selection.bubble)
            if selection.node is not None:
                matches = _merge_match(matches, selection.node)
                self.awaiting_enter = True
                follow = "下一步应点击「进入」，不要点「扫荡」。进入后等待战斗。"
                if enter is None:
                    follow += "本帧是局部图，没有「进入」按钮，需要再提供带该按钮的 1-3 画面。"
                x, y = self._click_point(selection.node)
                action = PlannedAction(
                    kind="click",
                    label=selection.node.label,
                    x=x,
                    y=y,
                    match=selection.node,
                    message=f"{selection.brief()} {follow}",
                )
                status = "continue" if enter is not None else "halt_need_next_screen"
                return StepResult(
                    scene=Scene.STAGE_1_3,
                    reason=clf.reason,
                    matches=matches,
                    action=action,
                    status=status,
                    message=action.message,
                )
            return StepResult(
                scene=Scene.STAGE_1_3,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(
                    kind="halt",
                    label="气泡未能对应节点",
                    message="找到了任务气泡，但本帧没有匹配到初步 / 深入 / 完全，不会随便点气泡附近。",
                ),
                status="halt_missing",
                message="找到任务气泡，但无法对应到探索节点，停止以免误点。",
            )

        visible = [m.label for m in nodes]
        if enter:
            visible.append(enter.label)
        visible_text = "、".join(f"「{name}」" for name in visible) if visible else "尚未匹配到节点或进入"
        return StepResult(
            scene=Scene.STAGE_1_3,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="halt",
                label="缺少小孩或任务气泡",
                message=NPC_OR_BUBBLE_MISSING_MESSAGE,
            ),
            status="halt_need_next_screen",
            message=f"{NPC_OR_BUBBLE_MISSING_MESSAGE}本帧可见：{visible_text}。",
        )

    def _plan_story_dialog(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        if self.recipe.kind is CommissionKind.TURN_IN:
            self.phase = Phase.CLAIM
            message = (
                "点击右上角「跳过剧情」。失落的圣遗物已在背包时，跳过即完成上交，"
                "不必再去图兰顿要塞，也不进入战斗。"
            )
        elif self.recipe.kind is CommissionKind.MULTI_BATTLE:
            if self.fights_done >= self.recipe.fights_required:
                self.phase = Phase.CLAIM
            message = "点击右上角「跳过剧情」。跳过之后冒险者消失，右上卷轴出现绿勾。"
        else:
            if self.phase in {Phase.ACCEPT, Phase.GO_STAGE}:
                self.phase = Phase.IN_BATTLE
            message = "点击右上角「跳过剧情」。战前对话跳过会直接进入战斗。"
        return verbs.skip_story(self, image_bgr, clf, message)

    def _plan_battle(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        if self.phase in {Phase.ACCEPT, Phase.GO_STAGE}:
            self.phase = Phase.IN_BATTLE
        now = time.monotonic()
        if self.battle_started_at is None:
            self.battle_started_at = now
        elapsed = now - self.battle_started_at
        skip = verbs.best_of(self, image_bgr, ("skip_story", "skip_story_tight"))
        if skip is not None:
            return self._click_result(
                Scene.BATTLE,
                clf,
                _merge_match(list(clf.matches), skip),
                skip,
                "战斗中出现剧情，点击右上「跳过剧情」。除此之外不点击，也不点「扫荡」。",
            )
        if elapsed >= config.BATTLE_TIMEOUT_SEC:
            return StepResult(
                scene=Scene.BATTLE,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(
                    kind="halt",
                    label="战斗超时",
                    message=f"战斗已等待 {elapsed:.0f} 秒仍未见「战斗胜利」，停止以免误点。",
                ),
                status="halt_missing",
                message=f"战斗超时（{config.BATTLE_TIMEOUT_SEC:.0f} 秒），未见胜利结算。",
            )
        action = PlannedAction(
            kind="wait",
            label="等待战斗结束",
            message=BATTLE_WAIT_MESSAGE,
        )
        return StepResult(
            scene=Scene.BATTLE,
            reason=clf.reason,
            matches=list(clf.matches),
            action=action,
            status="waiting_battle",
            message=BATTLE_WAIT_MESSAGE,
        )

    def _plan_victory(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        if self.phase is not Phase.CLAIM:
            self.phase = Phase.IN_BATTLE
        self.battle_started_at = None
        matches = list(clf.matches)
        touch = self._require(image_bgr, "touch_continue")
        if touch:
            matches = _merge_match(matches, touch)
            return self._click_result(
                Scene.VICTORY,
                clf,
                matches,
                touch,
                "战斗胜利，点击「触摸继续」。若随后出现战后剧情，再跳过。",
            )
        h, w = image_bgr.shape[:2]
        x, y = w // 2, int(round(h * 1100 / 1920))
        action = PlannedAction(
            kind="click",
            label="触摸继续",
            x=x,
            y=y,
            message="未单独匹配到「触摸继续」文案，点击屏幕中部关闭战斗胜利画面。",
        )
        return StepResult(
            scene=Scene.VICTORY,
            reason=clf.reason,
            matches=matches,
            action=action,
            status="continue",
            message=action.message,
        )

    def _plan_quest_log(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        opened = verbs.click_quest_title(self, image_bgr, clf)
        if opened is not None:
            return opened

        matches = list(clf.matches)
        if self.phase in {Phase.CLAIM, Phase.DONE} or self.loot_claimed:
            self.phase = Phase.DONE
            return self._done(clf, matches=matches)

        missing = (
            f"任务日志已打开，但没有看到「{self.recipe.name}」。可能尚未完成或已领取。"
        )
        return StepResult(
            scene=Scene.QUEST_LOG,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="wait",
                label="任务日志中没有该委托",
                message=missing,
            ),
            status="skip_unknown",
            message=missing,
        )

    def _plan_loot(self, image_bgr: np.ndarray, clf: Classification) -> StepResult:
        return verbs.dismiss_loot(self, image_bgr, clf)

    def _done(
        self,
        clf: Classification,
        *,
        matches: list[Match] | None = None,
        message: str | None = None,
    ) -> StepResult:
        self.phase = Phase.DONE
        if message is None:
            # 走到这里通常是领奖页已经点过「完成」。单条委托的战斗结束不会走这里。
            message = verbs.claim_done_message(self.recipe.name)
        return StepResult(
            scene=clf.scene,
            reason=clf.reason,
            matches=list(clf.matches if matches is None else matches),
            action=PlannedAction(
                kind="halt",
                label="委托完成",
                message=message,
            ),
            status="done",
            message=message,
        )

    def _click_or_missing(
        self,
        image_bgr: np.ndarray,
        clf: Classification,
        scene: Scene,
        template_id: str,
        *,
        click_message: str,
        missing_label: str,
        missing_message: str,
        delay_sec: float | None = None,
    ) -> StepResult:
        match = self._require(image_bgr, template_id)
        matches = list(clf.matches)
        if match:
            matches = _merge_match(matches, match)
            return self._click_result(
                scene, clf, matches, match, click_message, delay_sec=delay_sec
            )
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="halt",
                label=missing_label,
                message=missing_message,
            ),
            status="halt_missing",
            message=missing_message,
        )

    def _click_result(
        self,
        scene: Scene,
        clf: Classification,
        matches: list[Match],
        match: Match,
        click_message: str,
        *,
        delay_sec: float | None = None,
        status: str = "continue",
    ) -> StepResult:
        x, y = self._click_point(match)
        action = PlannedAction(
            kind="click",
            label=match.label,
            x=x,
            y=y,
            match=match,
            message=click_message,
            delay_sec=delay_sec,
        )
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=action,
            status=status,
            message=action.brief(),
        )

    def _click_point(self, match: Match) -> tuple[int, int]:
        spec = self.by_id.get(match.template_id)
        ox, oy = (0, 0)
        if spec is not None:
            ox, oy = spec.click_offset
        x, y = match.box.center
        return (x + int(round(ox * match.scale)), y + int(round(oy * match.scale)))

    def _require(self, image_bgr: np.ndarray, template_id: str) -> Match | None:
        if template_id in self._match_cache:
            return self._match_cache[template_id]
        spec = self.by_id.get(template_id)
        if spec is None:
            self.log.error("manifest 中缺少模板 %s", template_id)
            return None
        match = find_template(image_bgr, spec, ocr=self.ocr)
        self._match_cache[template_id] = match
        return match

    def _require_best(self, image_bgr: np.ndarray, *template_ids: str) -> Match | None:
        found: list[Match] = []
        for template_id in template_ids:
            match = self._require(image_bgr, template_id)
            if match is not None:
                found.append(match)
        if not found:
            return None
        return max(found, key=lambda m: m.score)


def _merge_match(matches: list[Match], new: Match) -> list[Match]:
    ids = {m.template_id for m in matches}
    if new.template_id in ids:
        return matches
    return list(matches) + [new]
