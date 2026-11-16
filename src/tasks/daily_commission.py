"""每日委托：共用动词 + 每条委托一份短配方。

类型1「喳喳布林入侵」（战斗，画面原文是「喳喳」）：
  世界地图（若停在南赛拉姆则下滑露出王城莉莉托斯）→ 城内协会
  → 右下角「委托」→ 委托中心点卡片 → 任务详情点「接收」
  → 用卡片右上返回关闭详情和列表（等关窗动画）→ 协会「离开」
  → 城内右下「探险」→ 关卡图点带「1-3」字样的旗帜
  → 点左下角小孩头像（不要点边缘气泡）→ 右上「跳过剧情」，直接进入战斗
  → 战斗中不操作，等到「战斗胜利」再点「触摸继续」
  → 若有战后剧情再跳过 → 回到 1-3 后点右上带绿勾的任务卷轴
  → 在任务日志点该委托标题打开详情 → 点详情中下部「完成」
  → 在「获得物品」上点「触摸继续」。

类型2「仇恨会令我成长」（交物品）：
  阿格莱恩区域地图左下「离开」→ 克里斯汀 → 点「图兰顿沙漠」进城
  → 协会「委托」→ 点这张卡 → 「接收」
  → 返回并离开，回到城内点冒险者的脸（不要点三点气泡）
  → 「跳过剧情」。圣遗物已在背包时就此上交，不必去要塞或战斗
  → 卷轴绿勾 → 点标题 → 米色「完成」→ 「获得物品」。

未收录的中间页会先跳过，等到能识别的画面再继续。任何阶段都不点「扫荡」。
类型3的走查还在进行，这里不实现。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import numpy as np

from src import config
from src.tasks.base import PlannedAction, StepResult, TaskBase
from src.tasks.phase import Phase
from src.tasks.recipes import CommissionKind, CommissionRecipe, ZHAZHA_BULIN
from src.tasks import verbs
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
        self.battle_started_at: float | None = None
        self.loot_claimed = False
        self._match_cache: dict[str, Match | None] = {}

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        self._match_cache = {}
        classification = classify_scene(image_bgr, self.specs, ocr=self.ocr)
        for match in classification.matches:
            self._match_cache.setdefault(match.template_id, match)
        self.log.info("识别结果: %s", classification.brief())
        scene = classification.scene
        if self.recipe.kind is CommissionKind.TURN_IN and scene in {
            Scene.WORLD_MAP,
            Scene.REGION_CRYSTIA,
        }:
            return self._plan_turn_in_region(image_bgr, classification)
        if self.recipe.kind is CommissionKind.TURN_IN and scene in {
            Scene.CITY_LILITOS,
            Scene.CITY_TURANDON,
        }:
            return self._plan_turn_in_city(image_bgr, classification)
        if scene is Scene.WORLD_MAP:
            return self._plan_world(image_bgr, classification)
        if scene is Scene.CITY_LILITOS:
            return self._plan_city(image_bgr, classification)
        if scene is Scene.ASSOCIATION:
            return self._plan_association(image_bgr, classification)
        if scene is Scene.COMMISSION_LIST:
            return self._plan_commission_list(image_bgr, classification)
        if scene is Scene.QUEST_DETAIL:
            return self._plan_quest_detail(image_bgr, classification)
        if scene is Scene.STAGE_MAP and self.recipe.kind is CommissionKind.BATTLE:
            return self._plan_stage_map(image_bgr, classification)
        if scene is Scene.STAGE_1_3 and self.recipe.kind is CommissionKind.BATTLE:
            return self._plan_stage_1_3(image_bgr, classification)
        if scene is Scene.STORY_DIALOG:
            return self._plan_story_dialog(image_bgr, classification)
        if scene is Scene.BATTLE and self.recipe.kind is CommissionKind.BATTLE:
            return self._plan_battle(image_bgr, classification)
        if scene is Scene.VICTORY and self.recipe.kind is CommissionKind.BATTLE:
            return self._plan_victory(image_bgr, classification)
        if scene is Scene.QUEST_LOG:
            return self._plan_quest_log(image_bgr, classification)
        if scene is Scene.LOOT_REWARD:
            return self._plan_loot(image_bgr, classification)
        if self.phase is Phase.DONE:
            return self._done(classification)
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

    def _plan_turn_in_region(
        self, image_bgr: np.ndarray, clf: Classification
    ) -> StepResult:
        """交物品：先看左上角地名。阿格莱恩点「离开」，克里斯汀点「图兰顿沙漠」。"""
        matches = list(clf.matches)
        crystia = self._require(image_bgr, "world_crystia")
        if crystia is not None:
            matches = _merge_match(matches, crystia)
            label = self._require(image_bgr, "region_turandon")
            if label is None:
                missing = "左上角已确认是「克里斯汀」，但没有匹配到「图兰顿沙漠」，不会改点别的地名。"
                return StepResult(
                    scene=Scene.REGION_CRYSTIA,
                    reason=clf.reason,
                    matches=matches,
                    action=PlannedAction(
                        kind="halt",
                        label="未找到图兰顿沙漠",
                        message=missing,
                    ),
                    status="halt_missing",
                    message=missing,
                )
            matches = _merge_match(matches, label)
            return self._click_result(
                Scene.REGION_CRYSTIA,
                clf,
                matches,
                label,
                "左上角是「克里斯汀」。点击「图兰顿沙漠」进入城市。",
            )

        aglaen = self._require(image_bgr, "world_aglaen")
        if aglaen is not None:
            matches = _merge_match(matches, aglaen)
        return verbs.leave_room(
            self,
            image_bgr,
            clf,
            Scene.WORLD_MAP,
            "左上角是「阿格莱恩」。点击左下「离开」，进入克里斯汀区域地图。",
            matches=matches,
        )

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
            return StepResult(
                scene=Scene.COMMISSION_LIST,
                reason=clf.reason,
                matches=matches,
                action=PlannedAction(
                    kind="wait",
                    label="委托已接取",
                    message=(
                    "已接取委托，不再点击列表里的卡片。请离开本页后返回城内。"
                    if self.recipe.kind is CommissionKind.TURN_IN
                    else "已接取委托，不再点击列表里的卡片。请离开本页后前往城内「探险」。"
                ),
                ),
                status="skip_unknown",
                message="已接取委托，当前仍停在委托列表。跳过本帧，等待城内或关卡画面。",
            )
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
    ) -> StepResult:
        self.phase = Phase.DONE
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
