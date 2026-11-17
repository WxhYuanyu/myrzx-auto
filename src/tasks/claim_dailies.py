"""六次每日委托都做完后，一起点「完成」领奖。

单条委托的流程结束时不会点完成。这里打开带绿勾的任务卷轴，
对日志里每一条已经打上绿色「完成」印章的委托：点标题（不点印章），
再在详情页中下部点米色「完成」，然后在「获得物品」点触摸继续。
没有印章的未完成委托不会去点。
"""

from __future__ import annotations

import logging

import numpy as np

from src.tasks.base import PlannedAction, StepResult, TaskBase
from src.tasks.phase import Phase
from src.tasks.recipes import ZHAZHA_BULIN
from src.tasks import verbs
from src.vision.classify import Classification, classify_scene
from src.vision.templates import load_templates, templates_by_id
from src.vision.types import Scene

logger = logging.getLogger("myrzx.task.claim_dailies")

_DONE_MESSAGE = "已经把任务日志里所有带绿色「完成」印章的每日委托都领完了。"
_WAIT_SCROLL = (
    "还没看到带绿勾的任务卷轴，也不在任务日志或详情页。"
    "先停在能看见绿勾卷轴的画面，不点「扫荡」。"
)


class ClaimDailiesTask(TaskBase):
    """把已完成的每日委托一并领取。不跑导航，也不接取新委托。"""

    name = "claim_dailies"

    def __init__(self) -> None:
        super().__init__()
        self.specs = load_templates()
        self.by_id = templates_by_id(self.specs)
        self.ocr = None
        self.recipe = ZHAZHA_BULIN
        self.phase = Phase.CLAIM
        self.loot_claimed = False
        self._match_cache: dict = {}
        self.claimed = 0

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        self._match_cache = {}
        clf = classify_scene(image_bgr, self.specs, ocr=self.ocr)
        for match in clf.matches:
            self._match_cache.setdefault(match.template_id, match)
        self.log.info("识别结果: %s", clf.brief())
        scene = clf.scene

        if scene is Scene.LOOT_REWARD:
            return verbs.dismiss_loot(
                self,
                image_bgr,
                clf,
                finishes_quest=False,
                message="关掉「获得物品」。若日志里还有带印章的委托，会继续领取。",
            )
        if scene is Scene.QUEST_DETAIL:
            tapped = verbs.tap_finish(self, image_bgr, clf, list(clf.matches))
            if tapped is not None:
                self.claimed += 1
                return tapped
            closed = verbs.close_with_back(
                self,
                image_bgr,
                clf,
                scene,
                "详情页没有米色「完成」，用右上返回回到列表。不要点印章。",
            )
            if closed is not None:
                return closed
            return self._wait(clf, "等待完成按钮", "详情页还没有米色「完成」。先等下一帧。")
        if scene is Scene.QUEST_LOG:
            return self._plan_log(image_bgr, clf)
        opened = verbs.open_quest_scroll(
            self,
            image_bgr,
            clf,
            scene,
            "点击带绿勾的任务卷轴，打开任务日志。不要点邮件或背包。",
        )
        if opened is not None:
            return opened
        return self._wait(clf, "等待绿勾卷轴", _WAIT_SCROLL)

    def _plan_log(self, image, clf) -> StepResult:
        stamp = self._require(image, "quest_complete_stamp")
        if stamp is None:
            message = _DONE_MESSAGE
            if self.claimed:
                message = f"一共领取了 {self.claimed} 条。" + _DONE_MESSAGE
            self.phase = Phase.DONE
            return StepResult(
                scene=Scene.QUEST_LOG,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="领奖结束", message=message),
                status="done",
                message=message,
            )
        # 点同一行左侧的任务标题，不点右侧绿色「完成」印章。
        _, cy = stamp.box.center
        x = min(max(180, stamp.box.x - 500), 360)
        y = cy
        action = PlannedAction(
            kind="click",
            label="已完成的委托标题",
            x=x,
            y=y,
            match=stamp,
            message="点击带绿色「完成」印章的那一行标题，打开详情。不要点印章本身。",
        )
        return StepResult(
            scene=Scene.QUEST_LOG,
            reason=clf.reason,
            matches=list(clf.matches) + [stamp],
            action=action,
            status="continue",
            message=action.brief(),
        )

    def _wait(self, clf: Classification, label: str, message: str) -> StepResult:
        return StepResult(
            scene=clf.scene,
            reason=clf.reason,
            matches=list(clf.matches),
            action=PlannedAction(kind="wait", label=label, message=message),
            status="skip_unknown",
            message=message,
        )

    def _require(self, image, template_id: str):
        if template_id in self._match_cache:
            return self._match_cache[template_id]
        from src.vision.match import find_template

        spec = self.by_id.get(template_id)
        if spec is None:
            self._match_cache[template_id] = None
            return None
        match = find_template(image, spec)
        self._match_cache[template_id] = match
        return match

    def _click_result(self, scene, clf, matches, match, click_message, *, delay_sec=None, status="continue"):
        x, y = match.box.center
        spec = self.by_id.get(match.template_id)
        if spec is not None:
            ox, oy = spec.click_offset
            x += int(round(ox * match.scale))
            y += int(round(oy * match.scale))
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
