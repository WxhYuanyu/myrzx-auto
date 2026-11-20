"""各条每日委托共用的动词。

接取（协会里的「委托」、列表上的卡片、「接收」）、离开、
点 NPC 的脸而不是三点气泡、跳过剧情、打开带绿勾的任务卷轴、
点日志里的任务标题而不是「完成」印章、点详情中下部的米色「完成」、
关掉「获得物品」。

配方只决定卡片、标题、NPC、地图入口和要打几场。这些动词不点「扫荡」。
"""

from __future__ import annotations

from typing import Any

from src import config
from src.tasks.base import PlannedAction, StepResult
from src.tasks.phase import Phase
from src.vision.match import find_template
from src.vision.types import Box, Match, Scene

# 「“热情”的冒险者」标题是主信号。分数略低时，用这张卡上的头像、紧急、
# 说明和奖励确认，确认不了就不点别的卡。阈值只对这一张卡，不改全局。
_EAGER_CARD = "commission_eager_adventurer"
_EAGER_AUX = (
    "commission_eager_portrait",
    "commission_eager_badge",
    "commission_eager_desc",
    "commission_eager_gold",
    "commission_eager_gem",
)
_EAGER_TITLE_FLOOR = 0.75


def card_missing_message(name: str) -> str:
    return (
        f"当前委托列表中没有找到「{name}」。可能今日尚未刷新、已被接取/完成，"
        "或列表被裁切/分辨率导致标题未匹配。工具在此停止，不会改点其他委托。"
    )


def claim_done_message(name: str) -> str:
    return f"「{name}」已领取完毕，任务日志中不再显示这条委托。"


def work_done_without_claim_message(name: str) -> str:
    return (
        f"「{name}」的流程已经跑完，先不点「完成」。"
        "六次每日委托都做完后再一起领奖。"
    )


def best_of(task: Any, image: Any, template_ids: tuple[str, ...]) -> Match | None:
    """在若干模板里取分数最高的命中。manifest 里没有的 id 会跳过。"""
    found: list[Match] = []
    for template_id in template_ids:
        if template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is not None:
            found.append(match)
    if not found:
        return None
    return max(found, key=lambda item: item.score)


def _with(matches: list[Match], new: Match | None) -> list[Match]:
    if new is None:
        return matches
    if any(item.template_id == new.template_id for item in matches):
        return matches
    return list(matches) + [new]


def open_commission_board(task: Any, image: Any, clf: Any) -> StepResult:
    """协会室内点右下角「委托」。莉莉托斯和图兰顿的木牌都认。"""
    match = best_of(
        task,
        image,
        ("association_commission", "association_commission_turandon"),
    )
    matches = _with(list(clf.matches), match)
    if match is None:
        return StepResult(
            scene=Scene.ASSOCIATION,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(
                kind="halt",
                label="未找到委托按钮",
                message="已识别为协会室内，但没有匹配到右下角「委托」。",
            ),
            status="halt_missing",
            message="已识别为协会室内，但没有匹配到右下角「委托」。",
        )
    return task._click_result(
        Scene.ASSOCIATION,
        clf,
        matches,
        match,
        "打开协会右下角的委托中心。",
    )


def match_commission_card(task: Any, image: Any, card_id: str | None = None) -> Match | None:
    """按卡片 id 找委托。热情这张会用辅助特征，其他卡仍只认自己的标题。"""
    card_id = card_id or task.recipe.card_template
    if card_id == _EAGER_CARD:
        return _find_eager_card(task, image)
    return task._require(image, card_id)


def _find_eager_card(task: Any, image: Any) -> Match | None:
    spec = task.by_id.get(_EAGER_CARD)
    if spec is None:
        return None
    title = task._require(image, _EAGER_CARD)
    aux = _eager_aux(task, image)
    if title is not None:
        return title
    # 标题差一点时，再按这张卡自己的下限看一眼，并要求旁边的特征对得上。
    weak = find_template(image, spec, threshold=_EAGER_TITLE_FLOOR)
    if weak is not None and _aux_near(weak.box, aux) >= 2:
        return weak
    confirmed = _eager_cluster(image, aux)
    if confirmed is None:
        return None
    return confirmed


def _eager_aux(task: Any, image: Any) -> list[Match]:
    found: list[Match] = []
    for template_id in _EAGER_AUX:
        if template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is not None:
            found.append(match)
    return found


def _aux_near(box: Box, aux: list[Match]) -> int:
    cx, cy = box.center
    span = max(box.w, box.h, 80) * 4
    count = 0
    for item in aux:
        ix, iy = item.box.center
        if abs(ix - cx) <= span and abs(iy - cy) <= span:
            count += 1
    return count


def _eager_cluster(image: Any, aux: list[Match]) -> Match | None:
    """没有可靠标题时，说明句加上头像和奖励必须挤在同一张卡上才点。"""
    by_id = {item.template_id: item for item in aux}
    desc = by_id.get("commission_eager_desc")
    portrait = by_id.get("commission_eager_portrait")
    if desc is None or portrait is None:
        return None
    if portrait.box.center[0] > desc.box.center[0] + 40:
        return None
    extras = [
        by_id[key]
        for key in (
            "commission_eager_badge",
            "commission_eager_gold",
            "commission_eager_gem",
        )
        if key in by_id
    ]
    near = [item for item in extras if _aux_near(desc.box, [item]) >= 1]
    if len(near) < 2:
        return None
    height, width = image.shape[:2]
    points = [desc.box.center, portrait.box.center] + [item.box.center for item in near]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    if max(xs) - min(xs) > width * 0.55 or max(ys) - min(ys) > height * 0.45:
        return None
    # 点说明文字，它在这张卡上，不会落到旁边另一张标题上。
    return Match(
        template_id=desc.template_id,
        label="“热情”的冒险者",
        scene=Scene.COMMISSION_LIST,
        role="click_only",
        box=desc.box,
        score=min(item.score for item in [desc, portrait, *near]),
        scale=desc.scale,
    )


def accept_listed_card(task: Any, image: Any, clf: Any) -> StepResult:
    """只点配方指定的那张卡片。列表里没有它就停，不改点别的委托。"""
    name = task.recipe.name
    match = match_commission_card(task, image)
    matches = _with(list(clf.matches), match)
    if match is None:
        message = card_missing_message(name)
        return StepResult(
            scene=Scene.COMMISSION_LIST,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label=name, message=message),
            status="halt_missing",
            message=message,
        )
    return task._click_result(
        Scene.COMMISSION_LIST,
        clf,
        matches,
        match,
        f"打开委托「{name}」的任务详情。",
    )


def press_receive(task: Any, image: Any, clf: Any, matches: list[Match]) -> StepResult | None:
    """任务详情上的「接收」。按钮还在就点，不论这一轮是不是已经点过。

    上一帧点过「接收」会把阶段改成已接取；如果详情还在、按钮也还在，
    说明没有接上，必须再点，不能去点返回离开。
    """
    accept = task._require(image, "quest_accept")
    if accept is None:
        return None
    if task.phase is Phase.ACCEPT:
        task.phase = Phase.GO_STAGE
    return task._click_result(
        Scene.QUEST_DETAIL,
        clf,
        _with(matches, accept),
        accept,
        f"接取委托「{task.recipe.name}」。看见「接收」还在就再点，确认接上后再返回。",
    )


def close_with_back(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    message: str,
    matches: list[Match] | None = None,
) -> StepResult | None:
    """点右上的返回箭头，并等关窗动画。不要点屏幕底部的「离开」。"""
    back = task._require(image, "quest_detail_back")
    base = list(clf.matches if matches is None else matches)
    if back is not None:
        return task._click_result(
            scene,
            clf,
            _with(base, back),
            back,
            message,
            delay_sec=config.CLOSE_ANIMATION_SEC,
        )
    # 箭头周围是协会场景，灯光一变大图就对不上。标题栏右侧仍是返回。
    title = None
    for template_id in ("commission_adventurer_title", "commission_center_title"):
        title = task._require(image, template_id)
        if title is not None:
            break
    if title is None:
        return None
    height, width = image.shape[:2]
    x = min(width - 50, title.box.x + title.box.w + 40)
    y = title.box.y + title.box.h // 2
    action = PlannedAction(
        kind="click",
        label="返回",
        x=int(x),
        y=int(y),
        message=message,
        delay_sec=config.CLOSE_ANIMATION_SEC,
    )
    return StepResult(
        scene=scene,
        reason=clf.reason,
        matches=_with(base, title),
        action=action,
        status="continue",
        message=action.brief(),
    )


def open_region_tab(
    task: Any,
    image: Any,
    clf: Any,
    template_id: str,
    message: str,
    scene: Scene,
    matches: list[Match] | None = None,
) -> StepResult:
    """点区域页签切换地图。不点左下「离开」。"""
    match = task._require(image, template_id)
    base = list(clf.matches if matches is None else matches)
    matches = _with(base, match)
    if match is None:
        missing = "要切换区域，但没有匹配到左侧区域页签。不会改点「离开」。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到区域页签", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(scene, clf, matches, match, message)


def leave_room(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    message: str,
    matches: list[Match] | None = None,
) -> StepResult:
    """点「离开」。用于协会室内，也用于阿格莱恩区域地图左下角。"""
    match = task._require(image, "association_leave")
    base = list(clf.matches if matches is None else matches)
    matches = _with(base, match)
    if match is None:
        missing = "已识别为当前页面，但没有匹配到「离开」。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到离开", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(
        scene,
        clf,
        matches,
        match,
        message,
        delay_sec=config.CLOSE_ANIMATION_SEC,
    )


def press_stage_enter(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    template_id: str,
    message: str,
    matches: list[Match] | None = None,
) -> StepResult:
    """点金色「进入」。点击若落在「扫荡」那一排，就停。"""
    match = task._require(image, template_id)
    base = list(clf.matches if matches is None else matches)
    matches = _with(base, match)
    if match is None:
        missing = "选关页上没有「进入」。不会改点「扫荡」。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到进入", message=missing),
            status="halt_missing",
            message=missing,
        )
    x, y = task._click_point(match)
    height = image.shape[0]
    sweep_y = int(round(height * 1750 / 1920))
    if match.label == "扫荡" or y >= sweep_y:
        missing = (
            f"「进入」的点击落在 ({x}, {y})，已经到了「扫荡」那一排（约 y={sweep_y} 以下）。停止。"
        )
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="拒绝扫荡", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(scene, clf, matches, match, message)


def confirm_dialog(
    task: Any,
    image: Any,
    clf: Any,
    template_id: str,
    message: str,
    scene: Scene,
) -> StepResult:
    """点弹窗上的「确定」。点击取按钮中心，不点按钮上方的空处。"""
    match = task._require(image, template_id)
    matches = _with(list(clf.matches), match)
    if match is None:
        missing = "事件弹窗上没有「确定」。不会把这一页当成战斗胜利。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到确定", message=missing),
            status="halt_missing",
            message=missing,
        )
    x, y = task._click_point(match)
    height = image.shape[0]
    too_high = int(round(height * 1360 / 1920))
    if y < too_high:
        missing = f"「确定」的点击在 ({x}, {y})，偏上会点空。停止。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="确定偏上", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(scene, clf, matches, match, message)


def leave_stage_select(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    message: str,
) -> StepResult:
    """选关页点左下「离开」。中间偏下的是「扫荡」，不点。"""
    match = best_of(task, image, ("association_leave", "stage_leave"))
    matches = _with(list(clf.matches), match)
    if match is None:
        missing = "选关页上没有左下「离开」。不会改点「扫荡」或「下一关卡」。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到离开", message=missing),
            status="halt_missing",
            message=missing,
        )
    x, y = task._click_point(match)
    width, height = image.shape[1], image.shape[0]
    sweep_y = int(round(height * 1750 / 1920))
    if x > width * 0.4 or (y >= sweep_y and x > width * 0.3):
        missing = f"离开按钮应在左下，当前命中 ({x}, {y}) 太靠中间。停止，以免点到「扫荡」。"
        return StepResult(
            scene=scene,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="拒绝扫荡", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(scene, clf, matches, match, message)


def talk_portrait(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    template_id: str | None,
    message: str,
) -> StepResult | None:
    """点 NPC 头像。模板只含脸，不含旁边的三点气泡。"""
    if not template_id:
        return None
    npc = task._require(image, template_id)
    if npc is None:
        return None
    return task._click_result(
        scene,
        clf,
        _with(list(clf.matches), npc),
        npc,
        message,
    )


def skip_story(task: Any, image: Any, clf: Any, message: str) -> StepResult:
    """点右上角「跳过剧情」。"""
    match = best_of(task, image, ("skip_story", "skip_story_tight"))
    matches = _with(list(clf.matches), match)
    if match is None:
        missing = "已识别为剧情对话，但没有匹配到右上角「跳过剧情」。"
        return StepResult(
            scene=Scene.STORY_DIALOG,
            reason=clf.reason,
            matches=matches,
            action=PlannedAction(kind="halt", label="未找到跳过剧情", message=missing),
            status="halt_missing",
            message=missing,
        )
    return task._click_result(Scene.STORY_DIALOG, clf, matches, match, message)


def open_quest_scroll(
    task: Any,
    image: Any,
    clf: Any,
    scene: Scene,
    message: str,
) -> StepResult | None:
    """右上卷轴出现绿勾时，点卷轴本体。不点邮件，也不点背包。"""
    check = task._require(image, "quest_scroll_check")
    scroll = task._require(image, "quest_scroll_done")
    if check is None and scroll is None:
        return None
    task.phase = Phase.CLAIM
    target = scroll or check
    assert target is not None
    matches = _with(_with(list(clf.matches), check), scroll)
    return task._click_result(scene, clf, matches, target, message)


def click_quest_title(task: Any, image: Any, clf: Any) -> StepResult | None:
    """点日志里的任务标题。绿色「完成」印章只记录，不点。"""
    row = task._require(image, task.recipe.log_template)
    if row is None:
        return None
    matches = list(clf.matches)
    matches = _with(matches, row)
    matches = _with(matches, task._require(image, "quest_complete_stamp"))
    matches = _with(matches, task._require(image, "quest_complete_text"))
    if task.phase is not Phase.DONE:
        task.phase = Phase.CLAIM
    return task._click_result(
        Scene.QUEST_LOG,
        clf,
        matches,
        row,
        f"先点击任务标题「{task.recipe.name}」打开详情，不要点列表上的绿色「完成」印章。",
    )


def tap_finish(task: Any, image: Any, clf: Any, matches: list[Match]) -> StepResult | None:
    """点详情中下部、奖励图标下面的米色「完成」。不是屏幕最底部。"""
    finish = task._require(image, "quest_finish")
    if finish is None:
        return None
    task.phase = Phase.CLAIM
    return task._click_result(
        Scene.QUEST_DETAIL,
        clf,
        _with(matches, finish),
        finish,
        "在任务详情中下部点「完成」领取奖励，不要点屏幕最底部，也不要点返回箭头。",
    )


def dismiss_loot(
    task: Any,
    image: Any,
    clf: Any,
    *,
    finishes_quest: bool = True,
    message: str | None = None,
) -> StepResult:
    """「获得物品」上点「触摸继续」。

    finishes_quest 为假时只关掉这一页（事件掉落或战斗掉落），不把委托标成已领。
    """
    if finishes_quest:
        task.phase = Phase.CLAIM
        task.loot_claimed = True
    if message is None:
        message = (
            "领取奖励，在「获得物品」上点击「触摸继续」。"
            if finishes_quest
            else "关掉「获得物品」。这一页不是任务结算。"
        )
    touch = task._require(image, "loot_touch")
    matches = _with(list(clf.matches), touch)
    if touch is not None:
        return task._click_result(
            Scene.LOOT_REWARD,
            clf,
            matches,
            touch,
            message,
        )
    height, width = image.shape[:2]
    x, y = width // 2, int(round(height * 1212 / 1920))
    action = PlannedAction(
        kind="click",
        label="触摸继续",
        x=x,
        y=y,
        message=message,
    )
    return StepResult(
        scene=Scene.LOOT_REWARD,
        reason=clf.reason,
        matches=matches,
        action=action,
        status="continue",
        message=action.message,
    )
