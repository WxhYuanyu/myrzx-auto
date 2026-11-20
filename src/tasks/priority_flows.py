"""按高 / 中 / 低分档的每日委托步骤。

区域地图上的开头仍走 daily_commission._plan_region_to_place（图谱里的地点）。
这里只接「已经要去哪座城」之后的差别：重进协会、关卡上对话、
3-20 去而复返、9-7 深入而不是 9-7-1。缺裁切就停，不造点击。
"""

from __future__ import annotations

import logging

from src.tasks.base import PlannedAction, StepResult
from src.tasks.phase import Phase
from src.tasks import navigation, verbs
from src.tasks.scroll import BAG_ITEM_REGION, ListScroll, cell_signature
from src import config
from src.vision.match import find_template
from src.vision.types import Scene

logger = logging.getLogger("myrzx.task.daily_commission")


class _Advance:
    """这一步已经完成，同一帧接着看下一步。"""


ADVANCE = _Advance()

_TALK_STEPS = frozenset(
    {
        "talk_dashu",
        "talk_youth",
        "talk_on_stage",
        "talk_task_npc",
        "city_talk",
        "talk_metaya",
        "talk_hunter",
        "talk_mejita",
    }
)

_SHARED_ASSOCIATION = ("city_turandon_association", "city_association")
_KNOWN_HEADERS = (
    ("association_lilitos_header", "王城莉莉托斯"),
    ("association_turandon_header", "图兰顿沙漠"),
)


def plan_priority(task, image, clf) -> StepResult:
    if task.step_armed:
        task.step_index += 1
        task.step_armed = False
    steps = task.recipe.steps
    if not steps:
        return _halt(task, clf, clf.scene, "没有步骤", f"「{task.recipe.name}」没有写下步骤。")
    for _ in range(8):
        if task.step_index >= len(steps):
            task.step_index = len(steps) - 1
        step = steps[task.step_index]
        if _bag_open(task, image) and step != "check_item":
            closed = close_open_bag(
                task,
                image,
                clf,
                "先关掉背包，再继续当前步骤。不要点格子里的物品。",
            )
            if closed is not None:
                return closed
        if clf.scene is Scene.STORY_DIALOG:
            return _on_story(task, image, clf)
        handler = _HANDLERS.get(step)
        if handler is None:
            return _halt(
                task,
                clf,
                clf.scene,
                "未知步骤",
                f"「{task.recipe.name}」的步骤「{step}」没有对应处理。",
            )
        result = handler(task, image, clf)
        if result is ADVANCE:
            task.step_index += 1
            continue
        return result
    return _halt(task, clf, clf.scene, "步骤空转", f"「{task.recipe.name}」的步骤没有推进，已停止。")


def _on_story(task, image, clf) -> StepResult:
    steps = task.recipe.steps
    current = steps[task.step_index]
    if current == "skip_in_battle":
        return step_skip_in_battle(task, image, clf)
    if current in _TALK_STEPS:
        nxt = task.step_index + 1
        if nxt < len(steps) and steps[nxt] == "skip_story":
            task.step_index = nxt
            current = "skip_story"
    if current == "skip_story":
        task.step_armed = True
    return verbs.skip_story(
        task,
        image,
        clf,
        "点击右上角「跳过剧情」。不要点对话框里的其他地方。",
    )


def _awaiting(task, template_id: str | None) -> bool:
    return bool(template_id) and template_id in task.recipe.awaiting_crops


def _place_name(task) -> str:
    place = task.recipe.location
    if place is not None:
        return place.name
    return task.recipe.unmapped_place or "目标地点"


def _halt(task, clf, scene, label: str, message: str) -> StepResult:
    return StepResult(
        scene=scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(kind="halt", label=label, message=message),
        status="halt_missing",
        message=message,
    )


def _wait(task, clf, scene, label: str, message: str, status: str = "skip_unknown") -> StepResult:
    return StepResult(
        scene=scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(kind="wait", label=label, message=message),
        status=status,
        message=message,
    )


def _association_ids(task) -> tuple[str, ...]:
    place = task.recipe.location
    if place is not None and place.association_templates:
        return place.association_templates
    return _SHARED_ASSOCIATION


def _foreign_association(task, image, clf):
    """走进了另一座已走过的城的协会时，离开，不要在那里接这条委托。"""
    place = task.recipe.location
    own = place.association_header if place is not None else None
    for header_id, city_name in _KNOWN_HEADERS:
        if header_id == own:
            continue
        if task._require(image, header_id) is None:
            continue
        return verbs.leave_room(
            task,
            image,
            clf,
            Scene.ASSOCIATION,
            f"当前是「{city_name}」的协会，不是「{_place_name(task)}」。"
            "点击「离开」回城，再经大地图过去。不会在这里接委托。",
        )
    return None


def _wrong_city(task, image, clf) -> bool:
    """只有高分或读出来的标题明确是另一座城时，才认定走错城。

    不靠刚过线的城市场景。浪人岬城里 city_capital_subtitle 曾经只有 0.756，
    若据此当成王城莉莉托斯，离开协会后就会去点「大地图」。
    """
    place = task.recipe.location
    if place is None:
        return False
    confident = navigation._confident_city_name(task, image)
    return bool(confident and confident != place.name)


def _click_association(task, image, clf):
    if _wrong_city(task, image, clf):
        return task._plan_open_world_map(image, clf, clf.scene)
    match = verbs.best_of(task, image, _association_ids(task))
    if match is not None:
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"进入「{_place_name(task)}」的协会。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到协会",
        f"「{_place_name(task)}」城内没有匹配到「协会」。"
        "这座城的室内路线还没走完，不会猜测建筑坐标。",
    )


def _pending_stage_message(task) -> str:
    label = task.recipe.stage_label or (task.recipe.stage_flag_template or "")
    node = task.recipe.stage_node
    if node == "basic":
        extra = "进关后走「初步探索」，不是深入或完全。"
    elif node == "deep":
        extra = "进关后走「深入探索」，不是初步探索。"
    else:
        extra = "没有写初步、深入或完全，不会默认点初步探索。"
    return (
        f"「{task.recipe.name}」要去打「{label}」，但关卡旗帜裁切还没有。"
        f"{extra}不会改点其他旗帜，也不会点「扫荡」。"
    )



def _card_ready_for_sweep(task, recipe) -> bool:
    """扫城时只能点已经有标题裁切、而且流程已经走查过的卡。"""
    card = recipe.card_template
    if not card or card not in task.by_id:
        return False
    if card in recipe.awaiting_crops:
        return False
    if recipe.flow == "pending":
        return False
    return True


def _pick_sweep_card(task, image, clf):
    """扫城时只接当前档、当前城里还没做的卡。有更高等级的也不会在中、低档去点。"""
    sweep = task.sweep
    candidates = sweep.candidates_here()
    if not candidates:
        return None
    for recipe in candidates:
        if not _card_ready_for_sweep(task, recipe):
            # 缺裁切或还没走查：跳过这条，不占用次数，继续看本城其他卡。
            sweep.skip(recipe)
            continue
        card = recipe.card_template
        match = verbs.match_commission_card(task, image, card)
        if match is None:
            continue
        changed = task.recipe.quest_id != recipe.quest_id
        task.recipe = recipe
        if changed:
            reset_item_check(task)
        task.phase = Phase.ACCEPT
        task.step_index = 0
        task.step_armed = False
        task.node_selected = False
        if recipe.required_item_template and getattr(task, "item_ready", None) is not True:
            return step_check_item(task, image, clf)
        return verbs.accept_listed_card(task, image, clf)
    return None


def _sweep_leave_board(task, image, clf, scene):
    if task.sweep is not None:
        for leftover in list(task.sweep.candidates_here()):
            task.sweep.skip(leftover)
    closed = verbs.close_with_back(
        task,
        image,
        clf,
        scene,
        "这一档在这座城里已经没有还能认出的委托。用右上返回关掉列表，换下一站。"
        "不要点屏幕底部「离开」。",
    )
    if closed is not None:
        task.sweep_move_next = True
        return closed
    return _wait(task, clf, scene, "等待返回", "这一页还没有返回箭头。先等下一帧，不点别的。")


def _finish_sweep_quest(task, clf):
    sweep = task.sweep
    sweep.mark_done(task.recipe)
    done_name = task.recipe.name
    cap = config.DAILY_COMMISSION_CAP
    if sweep.cap_reached():
        task.phase = Phase.DONE
        message = (
            f"「{done_name}」已做完，今天的 {cap} 次每日委托已经满了。"
            "先不点「完成」。六次都做完后用 --live --claim 一起领。"
        )
        return StepResult(
            scene=clf.scene,
            reason=clf.reason,
            matches=list(clf.matches),
            action=PlannedAction(kind="halt", label="先不领奖", message=message),
            status="done",
            message=message,
        )
    if not sweep.candidates_here():
        if not sweep.advance_place_or_tier():
            task.phase = Phase.DONE
            message = (
                f"「{done_name}」已做完。高、中、低三档都看过了，共做了 {sweep.completed} 次。"
                "先不点「完成」。可用 --live --claim 一起领。"
            )
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="先不领奖", message=message),
                status="done",
                message=message,
            )
        task.sweep_advance = True
    task.recipe = sweep.travel_recipe()
    task.phase = Phase.ACCEPT
    task.step_index = 0
    task.step_armed = False
    task.node_selected = False
    reset_item_check(task)
    place = task.recipe.location.name if task.recipe.location is not None else "下一站"
    message = (
        f"「{done_name}」已做完，先不领奖（{sweep.completed}/{cap}）。"
        f"接着看{sweep.tier.zh_name}级：去「{place}」的「{task.recipe.name}」。"
    )
    return _wait(task, clf, clf.scene, "下一条委托", message, status="continue")


def step_pending(task, image, clf):
    return _halt(
        task,
        clf,
        clf.scene,
        "流程还没走查",
        f"「{task.recipe.name}」是{task.recipe.tier.zh_name}级委托，流程还没实机走查。"
        "不会编造点击，也不会点「扫荡」。",
    )


# 安全上限。约 75 行只是观察到的数量，停不停看物品区有没有还在变。
BAG_SWIPE_CAP = 120


def reset_item_check(task) -> None:
    task.item_ready = None
    task.bag_swipes = 0
    task.bag_tab_ready = False
    task.bag_scroll = None


def _bag_scroll(task) -> ListScroll:
    scroll = getattr(task, "bag_scroll", None)
    if scroll is None:
        scroll = ListScroll(region=BAG_ITEM_REGION, max_swipes=BAG_SWIPE_CAP)
        task.bag_scroll = scroll
    return scroll


def _bag_precise(task, image, box):
    x1, y1, x2, y2 = box
    region = image[y1:y2, x1:x2]
    cells = cell_signature(region)
    anchor = None
    item_id = getattr(task.recipe, "required_item_template", None)
    if item_id:
        found = task._require(image, item_id)
        if found is not None:
            cx, cy = found.box.center
            if x1 <= cx < x2 and y1 <= cy < y2:
                anchor = (cy // 8, cx // 8)
    if cells is None and anchor is None:
        return None
    return (anchor, cells)


def _bag_open(task, image) -> bool:
    return task._require(image, "ui_bag_title") is not None


def close_open_bag(task, image, clf, message: str | None = None) -> StepResult | None:
    """背包还开着时先用右上返回关上，不要点格子里的物品，也不要点任务卷轴。"""
    if not _bag_open(task, image):
        return None
    text = message or "先关掉背包，不要点格子里的物品。"
    back = task._require(image, "ui_bag_back")
    if back is None:
        back = task._require(image, "quest_detail_back")
    if back is not None:
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [back],
            back,
            text,
            delay_sec=config.CLOSE_ANIMATION_SEC,
        )
    return _wait(
        task,
        clf,
        clf.scene,
        "等待关闭背包",
        "背包还开着，但没认到返回箭头。先等下一帧，不点物品。",
    )


def _item_name(task) -> str:
    return task.recipe.required_item_name or "所需物品"


# 背包一格大约 180 像素。一次只滑一行，避免可见的物品被整页划走。
BAG_ROW_SWIPE_PX = 180


def _swipe_bag(task, image, clf, message: str) -> StepResult:
    height, width = image.shape[:2]
    # 只在道具格子上滑，避开顶上的分页和返回。
    x = width // 2
    row = int(round(BAG_ROW_SWIPE_PX * height / 1920))
    y1 = int(height * 0.72)
    y2 = y1 - row
    action = PlannedAction(
        kind="swipe",
        label="下翻背包",
        x=x,
        y=y1,
        x2=x,
        y2=y2,
        message=message,
        delay_sec=0.6,
    )
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=action,
        status="continue",
        message=action.brief(),
    )



def _with_bag_scan(task, message: str) -> str:
    report = getattr(task, "bag_scan_report", None)
    if report:
        return f"背包识别：{report}。{message}"
    return message


def _skip_missing_item(task, image, clf) -> StepResult:
    name = task.recipe.name
    item = _item_name(task)
    scene = clf.scene
    if scene in {Scene.COMMISSION_LIST, Scene.QUEST_DETAIL}:
        closed = verbs.close_with_back(
            task,
            image,
            clf,
            scene,
            _with_bag_scan(task, f"背包里没有「{item}」，不接取「{name}」。用右上返回关掉列表。不要点屏幕底部「离开」。"),
        )
        if closed is not None:
            return closed
    if task.auto_sweep and task.sweep is not None:
        skipped = name
        task.sweep.skip(task.recipe)
        if task.sweep.candidates_here():
            reset_item_check(task)
            task.recipe = task.sweep.travel_recipe()
            task.phase = Phase.ACCEPT
            task.step_index = 0
            task.step_armed = False
            task.node_selected = False
            return _wait(
                task,
                clf,
                scene,
                "跳过缺物品的委托",
                _with_bag_scan(
                    task,
                    f"背包里没有「{item}」，不接取「{skipped}」，也不占用每日次数。"
                    f"接着看本城的「{task.recipe.name}」。",
                ),
                status="continue",
            )
        if not task.sweep.advance_place_or_tier():
            task.phase = Phase.DONE
            message = _with_bag_scan(
                task,
                f"背包里没有「{item}」，不接取「{skipped}」。"
                f"高、中、低三档都看过了，共做了 {task.sweep.completed} 次。"
                "先不点「完成」。可用 --live --claim 一起领。",
            )
            return StepResult(
                scene=scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=PlannedAction(kind="halt", label="扫城结束", message=message),
                status="done",
                message=message,
            )
        reset_item_check(task)
        task.recipe = task.sweep.travel_recipe()
        task.phase = Phase.ACCEPT
        task.step_index = 0
        task.step_armed = False
        task.node_selected = False
        place = task.recipe.location.name if task.recipe.location is not None else "下一站"
        return _wait(
            task,
            clf,
            scene,
            "跳过缺物品的委托",
            _with_bag_scan(
                task,
                f"背包里没有「{item}」，不接取「{skipped}」，也不占用每日次数。"
                f"接着看{task.sweep.tier.zh_name}级：去「{place}」的「{task.recipe.name}」。",
            ),
            status="continue",
        )
    return _halt(
        task,
        clf,
        scene,
        "没有所需物品",
        _with_bag_scan(task, f"背包里没有「{item}」，不接取「{name}」。这条单跑到此结束，不会占用每日次数。"),
    )



def _scan_bag_item(task, image, template_ids: tuple[str, ...]):
    """检查背包物品时，低于阈值的最高分也记下来，好让日志看得出这一帧有没有识别。"""
    parts: list[str] = []
    best = None
    for template_id in template_ids:
        spec = task.by_id.get(template_id)
        if spec is None:
            parts.append(f"{template_id}缺少模板")
            continue
        threshold = spec.threshold if spec.threshold is not None else config.MATCH_THRESHOLD
        peeked = find_template(image, spec, threshold=0.0, ocr=None)
        label = spec.label or template_id
        if peeked is None:
            parts.append(f"「{label}」没有匹配结果")
            continue
        x, y = peeked.box.center
        hit = peeked.score >= threshold
        parts.append(
            f"「{label}」最高分{peeked.score:.3f}@尺度{peeked.scale:.2f}"
            f"位置({int(x)},{int(y)})（阈值{threshold:.2f}）"
            + ("，已过阈值" if hit else "，未过阈值")
        )
        if hit and (best is None or peeked.score > best.score):
            best = peeked
    return best, "；".join(parts) if parts else "没有可识别的物品模板"


def step_check_item(task, image, clf):
    """接取前先开背包「道具」页，确认有所需物品才继续；没有就不接。"""
    item_id = task.recipe.required_item_template
    if not item_id:
        return ADVANCE
    item = _item_name(task)
    name = task.recipe.name

    if getattr(task, "item_ready", None) is not None:
        if _bag_open(task, image):
            if task.item_ready:
                text = (
                    f"背包里有「{item}」，关上背包后再接取「{name}」。不要点这件物品。"
                )
            else:
                text = (
                    f"翻完「道具」页也没有「{item}」，关上背包，不接取「{name}」。"
                    "不要点格子里的物品。"
                )
            closed = close_open_bag(task, image, clf, text)
            if closed is not None:
                return closed
        if task.item_ready:
            return ADVANCE
        return _skip_missing_item(task, image, clf)

    if not _bag_open(task, image):
        icon = task._require(image, "ui_bag_icon")
        if icon is None:
            return _wait(
                task,
                clf,
                clf.scene,
                "等待打开背包",
                f"还没看到背包入口，先等下一帧。打开后查看是否有「{item}」。"
                "不要点任务卷轴或邮件。",
            )
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [icon],
            icon,
            f"打开背包，查看是否有「{item}」。有才接取「{name}」，没有就不接。"
            "不要点右侧任务卷轴或邮件。",
            delay_sec=config.CLOSE_ANIMATION_SEC,
        )

    if not getattr(task, "bag_tab_ready", False):
        task.bag_tab_ready = True
        tab = task._require(image, "ui_bag_tab_items")
        if tab is not None:
            return task._click_result(
                clf.scene,
                clf,
                list(clf.matches) + [tab],
                tab,
                f"点「道具」页，再找「{item}」。不要点格子里的物品。",
            )
        back = task._require(image, "ui_bag_back")
        if back is not None:
            x = back.box.x + back.box.w // 2 - 20
            y = back.box.y + back.box.h + 80
            action = PlannedAction(
                kind="click",
                label="道具",
                x=int(x),
                y=int(y),
                message=f"点「道具」页，再找「{item}」。不要点格子里的物品。",
            )
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches) + [back],
                action=action,
                status="continue",
                message=action.brief(),
            )
        return _wait(
            task,
            clf,
            clf.scene,
            "等待道具页",
            f"背包已打开，但还没认到「道具」页。先等下一帧，不点物品。",
        )

    # 果汁同时用背包裁切和商店清单图标。无论有没有过阈值，都把识别分数写进日志。
    ids = (item_id, "shop_item_juice") if item_id == "item_suspicious_juice" else (item_id,)
    found, report = _scan_bag_item(task, image, ids)
    task.bag_scan_report = report
    logger.info("背包识别：%s", report)
    if found is not None:
        task.item_ready = True
        closed = close_open_bag(
            task,
            image,
            clf,
            f"背包识别：{report}。背包里有「{item}」，关上背包后再接取「{name}」。不要点这件物品。",
        )
        if closed is not None:
            return closed
        return ADVANCE

    scroll = _bag_scroll(task)
    decision = scroll.observe(image, precise=lambda frame, box: _bag_precise(task, frame, box))
    task.bag_swipes = scroll.swipes
    if decision in {"swipe", "inconclusive"}:
        note = (
            "这一帧物品区认不稳，不把它当成已经到底。"
            if decision == "inconclusive"
            else "物品区还在变化。"
        )
        return _swipe_bag(
            task,
            image,
            clf,
            f"在「道具」页往下翻，找「{item}」。识别：{report}。{note}"
            f"第 {task.bag_swipes}/{BAG_SWIPE_CAP} 次。不要点格子里的物品。",
        )
    if decision == "cap":
        task.item_ready = False
        closed = close_open_bag(
            task,
            image,
            clf,
            f"背包识别：{report}。背包滑到安全次数，还不能确认已经到底，先停下。"
            f"没有确认「{item}」，不接取「{name}」。不要点格子里的物品。",
        )
        if closed is not None:
            return closed
        return _halt(
            task,
            clf,
            clf.scene,
            "背包没有滑到底",
            f"背包识别：{report}。背包滑到安全次数，还不能确认已经到底。"
            f"不把这一帧当成没有「{item}」，也不接取「{name}」。",
        )

    task.item_ready = False
    task.bag_scan_report = report
    closed = close_open_bag(
        task,
        image,
        clf,
        f"背包识别：{report}。「道具」页已经滑到底，没有「{item}」，关上背包，不接取「{name}」。不要点格子里的物品。",
    )
    if closed is not None:
        return closed
    return _skip_missing_item(task, image, clf)


def step_accept_board(task, image, clf):
    # 详情上「接收」还在，说明没接上。即使阶段已经标成 GO_STAGE，也要再点一次，
    # 不能改去关详情或离开。查背包发生在这一步之前。
    if clf.scene is Scene.QUEST_DETAIL:
        return task._plan_quest_detail(image, clf)
    if task.phase is not Phase.ACCEPT:
        return ADVANCE
    if task.recipe.unmapped_place and clf.scene is Scene.UNKNOWN:
        return _halt(
            task,
            clf,
            clf.scene,
            "区域不在地图册",
            f"「{task.recipe.name}」在「{task.recipe.unmapped_place}」。"
            "这片区域还不在地图册里，不会编造坐标。",
        )
    card = task.recipe.card_template
    scene = clf.scene
    sweeping = bool(getattr(task, "auto_sweep", False) and getattr(task, "sweep", None) is not None)
    if scene is Scene.COMMISSION_LIST and sweeping:
        picked = _pick_sweep_card(task, image, clf)
        if picked is not None:
            return picked
        # 这一档在这座城已经没有还能认出来的卡，关列表，换下一站。
        return _sweep_leave_board(task, image, clf, scene)
    if _awaiting(task, card) and scene is Scene.COMMISSION_LIST:
        return _halt(
            task,
            clf,
            scene,
            "标题裁切还没有",
            f"「{task.recipe.name}」的标题裁切还没有，不会在委托板上改点别的卡。",
        )
    if scene is Scene.COMMISSION_LIST:
        card = task.recipe.card_template
        if card and card in task.by_id and verbs.match_commission_card(task, image, card) is not None:
            return verbs.accept_listed_card(task, image, clf)
        # 列表里没有这张卡，当作已经接过：关列表，再按后续步骤离开、重进、对话。
        task.phase = Phase.GO_STAGE
        return ADVANCE
    foreign = _foreign_association(task, image, clf)
    if foreign is not None:
        return foreign
    # 协会室内必须先点右下「委托」打开面板，才能认卡片。
    # 缺标题裁切、或这一页被判成 UNKNOWN（利特利尔等城的「委托」木牌
    # 可能不是场景标记）时，也不能跳过这一步直接去认委托板。
    # 若已确认走进了另一座城的协会，上面已经离开，不会在这里点「委托」。
    board = verbs.best_of(
        task,
        image,
        ("association_commission", "association_commission_turandon"),
    )
    if board is not None:
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [board],
            board,
            "打开协会右下角的委托中心。",
        )
    if scene is Scene.UNKNOWN and card in task.by_id:
        match = task._require(image, card)
        if match is not None:
            return task._click_result(
                scene,
                clf,
                list(clf.matches) + [match],
                match,
                f"打开委托「{task.recipe.name}」的任务详情。",
            )
    if scene is Scene.ASSOCIATION or navigation._in_target_association_room(task, image):
        # 「委托」已经在上面找过。走进了目标协会却对不上木牌，就停，不要改去认委托板。
        return _halt(
            task,
            clf,
            scene,
            "未找到委托",
            f"「{_place_name(task)}」的协会里没有匹配到「委托」。"
            "城内路线还没走完，不会猜测木牌的位置。",
        )
    if scene in {Scene.CITY_LILITOS, Scene.CITY_TURANDON}:
        return _click_association(task, image, clf)
    if scene is Scene.UNKNOWN:
        match = verbs.best_of(task, image, _association_ids(task))
        if match is not None and navigation.city_is_target(task, image, clf):
            return task._click_result(
                scene,
                clf,
                list(clf.matches) + [match],
                match,
                f"进入「{_place_name(task)}」的协会。",
            )
        if match is not None:
            return _halt(
                task,
                clf,
                scene,
                "不能凭协会认城",
                f"看到共用建筑「协会」，但左上角标题不能确认是「{_place_name(task)}」。"
                "不会把别的城当成王城莉莉托斯，也不会点进去。",
            )
        board = verbs.best_of(
            task,
            image,
            ("association_commission", "association_commission_turandon"),
        )
        if board is not None:
            return task._click_result(
                scene,
                clf,
                list(clf.matches) + [board],
                board,
                "打开协会右下角的委托中心。",
            )
        return _halt(
            task,
            clf,
            scene,
            "城内路线未走查",
            f"还不能在这一页接「{task.recipe.name}」。"
            f"「{_place_name(task)}」的城内路线尚未走查，共用的「协会」和「委托」也对不上。"
            "不会猜测点击。",
        )
    return _halt(
        task,
        clf,
        scene,
        "还不能接取",
        f"当前画面还不能接「{task.recipe.name}」。不会猜测点击。",
    )


def step_leave_association(task, image, clf):
    scene = clf.scene
    if scene in {Scene.QUEST_DETAIL, Scene.COMMISSION_LIST}:
        closed = verbs.close_with_back(
            task,
            image,
            clf,
            scene,
            "用卡片右上返回关闭这一页，等动画。不要点屏幕底部「离开」。",
        )
        if closed is not None:
            return closed
        return _wait(task, clf, scene, "等待返回", "这一页还没有返回箭头。先等下一帧，不点别的。")
    if scene is Scene.ASSOCIATION:
        return verbs.leave_room(
            task,
            image,
            clf,
            scene,
            "从协会「离开」，回到城内。",
        )
    if scene in {
        Scene.CITY_LILITOS,
        Scene.CITY_TURANDON,
        Scene.WORLD_MAP,
        Scene.REGION_CRYSTIA,
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    }:
        return ADVANCE
    # 莉安湖等城还没有专属场景名，但「协会」「大地图」已经在城里。
    if navigation.in_city(task, image) or navigation.city_is_target(task, image, clf):
        return ADVANCE
    if navigation.find_city_world_map(task, image) is not None:
        return ADVANCE
    if navigation.recognize_region(task, image) is not None:
        return ADVANCE
    return _wait(task, clf, scene, "等待离开协会", "还在离开协会的过渡画面，先等下一帧。")


def step_reenter_association(task, image, clf):
    if clf.scene is Scene.ASSOCIATION:
        foreign = _foreign_association(task, image, clf)
        if foreign is not None:
            return foreign
        return ADVANCE
    if _wrong_city(task, image, clf):
        return task._plan_open_world_map(image, clf, clf.scene, here=clf.scene.zh_name)
    if not navigation.city_is_target(task, image, clf):
        if verbs.best_of(task, image, _association_ids(task)) is not None:
            return _halt(
                task,
                clf,
                clf.scene,
                "不能凭协会认城",
                f"要重新进入「{_place_name(task)}」的协会，但左上角标题对不上这座城。"
                "不会因为看到共用的「协会」就点进去。",
            )
    match = verbs.best_of(task, image, _association_ids(task))
    if match is not None:
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "再次进入协会，去找「协会大叔」。点的是协会入口，不是气泡。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未能重进协会",
        f"要重新进入「{_place_name(task)}」的协会，但没有匹配到「协会」。"
        "城内路线还没走完，不会猜测建筑坐标。",
    )


def _talk_templates(task) -> tuple[str, ...]:
    ids: list[str] = []
    for template_id in (task.recipe.npc_template, *task.recipe.npc_templates):
        if not template_id or template_id in ids:
            continue
        if _awaiting(task, template_id) or template_id not in task.by_id:
            continue
        ids.append(template_id)
    return tuple(ids)


def step_talk_dashu(task, image, clf):
    match = verbs.best_of(task, image, _talk_templates(task))
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击「协会大叔」的脸。不要点旁边的三点气泡，也不要点名字牌。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到协会大叔",
        "协会里没有匹配到「协会大叔」的脸。不会点对话气泡，也不会改点「委托」。",
    )


def step_talk_youth(task, image, clf):
    # 处理毒桶在 2-9 选关页、奇怪的魔物在 3-20，都是「青年 / 年轻的小哥」。
    match = verbs.best_of(task, image, ("npc_qingnian_29", "npc_qingnian"))
    if match is not None:
        task.step_armed = True
        where = task.recipe.stage_label or "关卡页"
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"在 {where} 点击「青年 / 年轻的小哥」的脸，不要点气泡，"
            "也不要点「进入」或「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到青年",
        f"在「{task.recipe.name}」要对话的关卡页上没有匹配到「青年」的脸。"
        "不会点对话气泡，也不会点「进入」或「扫荡」。",
    )


def step_talk_on_stage(task, image, clf):
    npc = task.recipe.npc_template
    where = task.recipe.stage_label or "关卡页"
    if _awaiting(task, npc) or not npc or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡 NPC 裁切还没有",
            f"「{task.recipe.name}」要在关卡 {where} 上点任务 NPC 的脸，这张裁切还没有。"
            "人在关卡上，不在协会里。不会点「协会大叔」，也不会猜一张脸，"
            "也不要点「进入」或「扫荡」。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"在 {where} 点击任务 NPC 的脸，不要点气泡，也不要点「进入」或「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        f"未找到 {where} 的 NPC",
        f"已在关卡页，但没有匹配到「{task.recipe.name}」的任务 NPC。"
        "不会点协会大叔，也不会猜一张脸，也不要点「进入」或「扫荡」。",
    )


def step_talk_task_npc(task, image, clf):
    npc = task.recipe.npc_template
    if _awaiting(task, npc) or not npc or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "任务 NPC 裁切还没有",
            f"「{task.recipe.name}」的任务 NPC 脸部裁切还没有。"
            "不会点「小孩」或其他人的脸，也不会编造坐标。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"点击「{task.recipe.name}」任务 NPC 的脸，不要点气泡。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到任务 NPC",
        f"没有匹配到「{task.recipe.name}」的任务 NPC。不会改点别人的脸。",
    )


def step_city_talk(task, image, clf):
    """请让他们安息：协会门口的城内头像。裁切已经有了；这帧对不上就等，不改点别人。"""
    npc = task.recipe.npc_template or ""
    if _awaiting(task, npc) or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "城内头像裁切还没有",
            f"「{task.recipe.name}」的城内头像裁切还没有，不会编造一张脸去点。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击城内协会门口这个人的脸，不要点旁边的气泡，也不要点「紧急」角标。",
        )
    return _wait(
        task,
        clf,
        clf.scene,
        "等待城内头像",
        f"这帧没有匹配到「{task.recipe.name}」的城内头像。"
        "不会改点别人的脸，也不会因为没有另一张实拍就停。",
    )


def step_skip_story(task, image, clf):
    match = verbs.best_of(task, image, ("skip_story", "skip_story_tight"))
    if match is not None or clf.scene is Scene.STORY_DIALOG:
        task.step_armed = True
        return verbs.skip_story(
            task,
            image,
            clf,
            "点击右上角「跳过剧情」。",
        )
    steps = task.recipe.steps
    nxt = task.step_index + 1
    if nxt < len(steps) and steps[nxt] == "leave_shop" and _in_shop(task, image):
        # 对话已经结束，商店界面还在，不必空等「跳过剧情」。
        return ADVANCE
    if nxt < len(steps) and steps[nxt] == "battle" and clf.scene in {
        Scene.BATTLE,
        Scene.VICTORY,
        Scene.LOOT_REWARD,
    }:
        # 第二次对话后战斗可能已经开始，不必再空等「跳过剧情」。
        return ADVANCE
    return _wait(
        task,
        clf,
        clf.scene,
        "等待剧情",
        "还没看到右上「跳过剧情」。先等对话框，不点别的。",
    )


def step_explore(task, image, clf):
    if clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    }:
        return ADVANCE
    region_marks = ["stage_flag_3_20", "stage_node_3_20", "stage_flag_3_23", "stage_return"]
    flag = task.recipe.stage_flag_template
    if flag:
        region_marks.append(flag)
    if verbs.best_of(task, image, tuple(region_marks)) is not None:
        # 已经在地区图上（例如北赛拉姆、浪人岬地区），不必再点城里的「探险」。
        return ADVANCE
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "stage_leave", "stage_return")) is not None:
        # 已经在选关页或地区图，不必再点城里的「探险」。
        flag = task.recipe.stage_flag_template
        if flag and flag in task.by_id and task._require(image, flag) is not None:
            return ADVANCE
        if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
            return ADVANCE
    if _wrong_city(task, image, clf):
        return task._plan_open_world_map(image, clf, clf.scene, here=clf.scene.zh_name)
    name = navigation.confirmed_city_name(task, image, clf)
    place = task.recipe.location
    if name and place and name != place.name:
        return task._plan_open_world_map(image, clf, clf.scene, here=name)
    match = verbs.best_of(task, image, ("city_explore_label", "city_explore"))
    # 标题认不出来（name 为 None）不能当成走错城。刚离开浪人岬协会时
    # 常常没有高分招牌，但城里已有「协会 / 大地图 / 探险」，应点「探险」。
    if (
        match is not None
        and place is not None
        and name
        and name != place.name
        and place.city_scene is not clf.scene
    ):
        return _halt(
            task,
            clf,
            clf.scene,
            "认不出当前城市",
            f"要在「{_place_name(task)}」点「探险」，但左上角标题认不出这座城。"
            "不会把别的城的「探险」当成目标。",
        )
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"从「{_place_name(task)}」城内右下稍微按住「探险」进入地区。不点「扫荡」。避免点太短进不去。",
            hold_ms=navigation.REGION_HOLD_MS,
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到探险",
        f"「{_place_name(task)}」城内没有匹配到「探险」。不会猜测按钮位置，也不会点「扫荡」。",
    )


_REGION_PAN_MAX = 24
_REGION_PAN_ORDER = ("east", "south", "west", "north")


def _region_map_markers(task) -> tuple[str, ...]:
    ids = ["stage_return", "stage_flag_3_20", "stage_node_3_20", "stage_flag_3_23"]
    flag = task.recipe.stage_flag_template
    if flag and flag not in ids:
        ids.append(flag)
    return tuple(ids)


def _on_region_map(task, image) -> bool:
    return verbs.best_of(task, image, _region_map_markers(task)) is not None


def _pan_region_for_flag(task, image, clf) -> StepResult:
    """地区图上还看不到目标旗帜时换方向平移，直到看见再点，不猜坐标。"""
    label = task.recipe.stage_label or "目标关卡"
    place = _place_name(task)
    key = f"region-flag:{task.recipe.quest_id}:{label}"
    navigation._arm_pan(task, key)
    if task.map_swipes >= _REGION_PAN_MAX:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到关卡",
            f"在「{place}」地区图上平移了 {_REGION_PAN_MAX} 次，还是没有匹配到「{label}」。"
            "不会改点其他旗帜，也不会编造坐标，不会点「扫荡」。",
        )
    direction = _REGION_PAN_ORDER[task.map_swipes % len(_REGION_PAN_ORDER)]
    task.map_swipes += 1
    action = navigation._swipe(image, direction)
    side = {"east": "东侧", "south": "南边", "west": "西侧", "north": "北边"}[direction]
    action = PlannedAction(
        kind="swipe",
        label=action.label,
        x=action.x,
        y=action.y,
        x2=action.x2,
        y2=action.y2,
        message=(
            f"「{place}」地区图上还看不到「{label}」。先往{side}平移，"
            "直到看见旗帜再点。不要点旁边的对话气泡，也不要点「扫荡」，"
            f"更不要按固定坐标猜点。第 {task.map_swipes}/{_REGION_PAN_MAX} 次滑动。"
        ),
    )
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=action,
        status="continue",
        message=action.message,
    )


def step_fight_stage(task, image, clf):
    flag = task.recipe.stage_flag_template
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    if _awaiting(task, flag) or not flag or flag not in task.by_id:
        return _halt(task, clf, clf.scene, "关卡裁切还没有", _pending_stage_message(task))
    match = task._require(image, flag)
    if match is not None:
        task.map_swipes = 0
        task._pan_key = None
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"点击关卡「{task.recipe.stage_label}」的旗帜和编号，不要点旁边的气泡，也不要点「扫荡」。",
        )
    if _on_region_map(task, image):
        return _pan_region_for_flag(task, image, clf)
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到关卡",
        f"没有匹配到「{task.recipe.stage_label}」，而且现在也不像在地区图上。"
        "不会改点其他旗帜，也不会点「扫荡」。",
    )


def step_enter_basic_starts_battle(task, image, clf):
    """讨伐食人花：在 2-20 选关页点「初步探索」的星星，战斗自己开始。不要点「进入」。"""
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD, Scene.STORY_DIALOG}:
        return ADVANCE
    node = "stage_2_20_basic"
    if _awaiting(task, node) or node not in task.by_id:
        return _halt(
            task,
            clf,
            scene,
            "初步探索裁切还没有",
            "「讨伐食人花」要在 2-20 点「初步探索」的星星才能开打。"
            "这张裁切还没有。不会点「进入」或「扫荡」，也不会只点四个字。",
        )
    match = task._require(image, node)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击 2-20「初步探索」的星星（2-20-1）。不要只点「初步探索」四个字，"
            "也不要点岛上的气泡、「进入」或「扫荡」。点星星后战斗会自己开始。",
        )
    return _halt(
        task,
        clf,
        scene,
        "未找到初步探索",
        "已在 2-20 选关页，但没有匹配到「初步探索」的星星。"
        "不会点「进入」或「扫荡」，也不会改点深入或完全探索。",
    )


def _click_node(task, image, clf, template_id: str, message: str, *, arm: bool):
    if template_id not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "节点裁切还没有",
            f"「{template_id}」还没有裁切，不会编造点击。",
        )
    match = task._require(image, template_id)
    if match is None:
        return None
    if arm:
        task.step_armed = True
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [match],
        match,
        message,
    )


def _click_first(task, image, clf, template_ids: tuple[str, ...], message: str, *, arm: bool):
    available = tuple(template_id for template_id in template_ids if template_id in task.by_id)
    if not available:
        missing = "、".join(template_ids)
        return _halt(
            task,
            clf,
            clf.scene,
            "节点裁切还没有",
            f"「{missing}」还没有裁切，不会编造点击。",
        )
    match = verbs.best_of(task, image, available)
    if match is None:
        return None
    if arm:
        task.step_armed = True
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [match],
        match,
        message,
    )


def step_leave_stage(task, image, clf):
    """选关页点左下「离开」回到地区图。不要点「进入」「扫荡」或「下关卡」。"""
    on_select = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "stage_leave")) is not None
    on_region = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or verbs.best_of(
        task,
        image,
        ("stage_flag_3_20", "stage_node_3_20", "stage_flag_3_23", "stage_return"),
    ) is not None
    if on_region and not on_select:
        return ADVANCE
    if on_select:
        result = verbs.leave_stage_select(
            task,
            image,
            clf,
            clf.scene,
            "点左下「离开」回到地区图。不要点「进入」「扫荡」或「下关卡」。",
        )
        if result.action is not None and result.action.kind == "click":
            task.step_armed = True
        return result
    return _wait(
        task,
        clf,
        clf.scene,
        "等待离开选关",
        "还没回到地区图，也还没看到左下「离开」。先等下一帧，不点「扫荡」。",
    )


_BEISA_SWIPE_CAP = 20


def _reset_beisa_search(task) -> None:
    task._beisa_phase = "up"
    task._beisa_prev = None
    task._beisa_swipes = 0


def _on_beisa_region_map(task, image, clf) -> bool:
    if clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    }:
        return True
    return _on_region_map(task, image)


_THREE_20_IDS = ("stage_flag_3_20", "stage_node_3_20")
_QUEST_BUBBLE_IDS = ("quest_bubble_map", "quest_bubble")
# 对话圈一般在旗帜右侧。只有靠得够近时，才把稍低的旗帜分当成 3-20。
_BUBBLE_HELP_SCORE = 0.70
_BUBBLE_MAX_DX = 280
_BUBBLE_MAX_DY = 220


def _find_quest_bubbles(task, image) -> list:
    found = []
    seen = set()
    for template_id in _QUEST_BUBBLE_IDS:
        if template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is None:
            continue
        key = (int(match.box.x), int(match.box.y))
        if key in seen:
            continue
        seen.add(key)
        found.append(match)
    return found


def _near_quest_bubble(match, bubble) -> bool:
    mx, my = match.box.center
    bx, by = bubble.box.center
    # 气泡在旗帜右侧或略重叠，纵向大致同一带。
    return -40 <= (bx - mx) <= _BUBBLE_MAX_DX and abs(by - my) <= _BUBBLE_MAX_DY


def _click_3_20_near_bubble(task, image, clf, message: str):
    """旗帜没直接过阈值时，用旁边的任务对话圈辅助确认 3-20。只点旗帜，不点气泡。"""
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    best = None
    for template_id in _THREE_20_IDS:
        spec = task.by_id.get(template_id)
        if spec is None:
            continue
        match = find_template(image, spec, threshold=0.0, ocr=getattr(task, "ocr", None))
        if match is None:
            continue
        if best is None or match.score > best.score:
            best = match
    if best is None or best.score < _BUBBLE_HELP_SCORE:
        return None
    if not any(_near_quest_bubble(best, bubble) for bubble in bubbles):
        return None
    task.step_armed = True
    helped = (
        f"{message} 旗帜分 {best.score:.3f}，已用旁边的任务对话圈确认是 3-20。"
        "只点旗帜，不点对话圈。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [best] + bubbles,
        best,
        helped,
    )


def _click_3_20(task, image, clf, message: str):
    clicked = _click_first(
        task,
        image,
        clf,
        _THREE_20_IDS,
        message,
        arm=True,
    )
    if clicked is not None:
        return clicked
    return _click_3_20_near_bubble(task, image, clf, message)


def _search_3_20_corner(task, image, clf, *, click_message: str, halt_reason: str) -> StepResult:
    """北赛拉姆地区找 3-20：先把北边拉到上沿，再把东边拉到右沿。看见旗帜再点，不猜坐标。"""
    clicked = _click_3_20(task, image, clf, click_message)
    if clicked is not None:
        _reset_beisa_search(task)
        return clicked
    if not _on_beisa_region_map(task, image, clf):
        return _halt(
            task,
            clf,
            clf.scene,
            halt_reason,
            "还不像在北赛拉姆地区图上，也没有匹配到 3-20。"
            "不会改点 3-23 或其他旗帜，也不会编造坐标。",
        )

    phase = getattr(task, "_beisa_phase", "up")
    if phase == "look":
        return _halt(
            task,
            clf,
            clf.scene,
            halt_reason,
            "已到达北赛拉姆地区右上角，仍然没有看到 3-20，已停止。"
            "不会改点 3-23 或其他旗帜，也不会编造坐标。",
        )

    signature = navigation._map_signature(image)
    previous = getattr(task, "_beisa_prev", None)
    swipes = int(getattr(task, "_beisa_swipes", 0))
    if signature is None:
        if swipes >= _BEISA_SWIPE_CAP:
            return _halt(
                task,
                clf,
                clf.scene,
                halt_reason,
                "寻找 3-20 时没法判断地区图有没有移动，已停止。"
                "不会改点 3-23 或其他旗帜，也不会编造坐标。",
            )
        task._beisa_swipes = swipes + 1
        action = _beisa_3_20_swipe(image, phase, task._beisa_swipes)
        action.message = "这一帧没法判断地区图有没有移动，不把它当成边界。" + action.message
        return _swipe_step(clf, action)

    moved = None if previous is None else navigation._map_moved(previous, signature)
    task._beisa_prev = signature
    if previous is not None and moved is False:
        if phase == "up":
            task._beisa_phase = "right"
            task._beisa_swipes = 1
            action = _beisa_3_20_swipe(image, "right", 1)
            action.message = (
                "地图已经到上边界（画面不再移动）。3-20 在右上角，"
                "接下来只把右边拉进画面（手指左滑），直到右边界。不再上下滑动。"
            )
            return _swipe_step(clf, action)
        task._beisa_phase = "look"
        return _halt(
            task,
            clf,
            clf.scene,
            halt_reason,
            "已到达北赛拉姆地区右上角，仍然没有看到 3-20，已停止。"
            "不会改点 3-23 或其他旗帜，也不会编造坐标。",
        )

    if swipes >= _BEISA_SWIPE_CAP:
        side = "上" if phase == "up" else "右"
        return _halt(
            task,
            clf,
            clf.scene,
            halt_reason,
            f"向{side}滑动已经达到安全次数，仍不能确认地图的{side}边界，已停止。"
            "不会改点 3-23 或其他旗帜，也不会编造坐标。",
        )
    task._beisa_swipes = swipes + 1
    action = _beisa_3_20_swipe(image, phase, task._beisa_swipes)
    return _swipe_step(clf, action)


def _beisa_3_20_swipe(image, phase: str, index: int) -> PlannedAction:
    if phase == "right":
        action = navigation._swipe(image, "east")
        action.message = (
            "已经到了地图上沿。3-20 在北赛拉姆地区右上角，接下来只把右边拉进画面（手指左滑），"
            f"直到右边界。第 {index} 次。不要再上下滑动，也不要点 3-23 或其他旗帜。"
        )
        return action
    action = navigation._swipe(image, "north")
    action.message = (
        "3-20 在北赛拉姆地区右上角。先把北边拉进画面（手指下滑），直到地图到达上边界。"
        "这一帧地图还在移动，继续向北，不同时左右滑动。"
        f"第 {index} 次向北。不要改点 3-23 或其他旗帜。"
    )
    return action


def _swipe_step(clf, action: PlannedAction) -> StepResult:
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=action,
        status="continue",
        message=action.message,
    )


def step_enter_3_20(task, image, clf):
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    return _search_3_20_corner(
        task,
        image,
        clf,
        click_message="点击关卡 3-20 的旗帜（爪印旗、三星和「3-20」）。不要点旁边的对话气泡，也不要改点 3-23。",
        halt_reason="未找到 3-20",
    )


def step_return_3_20(task, image, clf):
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    return _search_3_20_corner(
        task,
        image,
        clf,
        click_message="打完 3-23-2 后回到 3-20，再和青年对话交任务。点击 3-20 的旗帜，不要点气泡。",
        halt_reason="未能回到 3-20",
    )


def _enter_3_23_2(task, image, clf):
    chosen = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter"))
    template_id = chosen.template_id if chosen is not None else "stage_enter_gold"
    entered = verbs.press_stage_enter(
        task,
        image,
        clf,
        clf.scene,
        template_id,
        "「深入探索」已选中。点中下部金色「进入」（约 y=1600）。不要点更下面的「扫荡」。",
    )
    if entered.action is not None and entered.action.kind == "click":
        task.step_armed = True
    return entered


def step_fight_3_23_2(task, image, clf):
    """3-23 深入探索：先点旗帜，再点星星选中节点，然后点「进入」。点星星不会自己开打。"""
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD, Scene.STORY_DIALOG}:
        return ADVANCE
    on_select = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "stage_leave")) is not None
    if on_select:
        if task.node_selected:
            return _enter_3_23_2(task, image, clf)
        deep = "stage_3_23_deep"
        if deep not in task.by_id:
            return _halt(
                task,
                clf,
                scene,
                "深入探索裁切还没有",
                "「奇怪的魔物」要在 3-23 点「深入探索」的星星选中节点，再点「进入」。"
                "这张裁切还没有。不会只点四个字，也不会点树上的气泡或「扫荡」。",
            )
        match = task._require(image, deep)
        if match is None:
            return _halt(
                task,
                clf,
                scene,
                "未找到深入探索",
                "已在 3-23 选关页，但没有匹配到「深入探索」的星星。"
                "不要只点「深入探索」四个字，也不要点树上的气泡、「进入」或「扫荡」。",
            )
        task.node_selected = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击 3-23「深入探索」的星星（3-23-2）。这只会选中节点，不会自己开打。"
            "不要只点「深入探索」四个字，也不要点树上的气泡。选中后再点「进入」，不要点「扫荡」。",
        )
    flag = "stage_flag_3_23"
    if flag not in task.by_id:
        return _halt(
            task,
            clf,
            scene,
            "3-23 裁切还没有",
            "要去打 3-23-2（深入探索）。3-23 的旗帜裁切还没有。"
            "不会再点 3-20，也不会编造坐标，不会点「扫荡」。",
        )
    match = task._require(image, flag)
    if match is not None:
        task.node_selected = False
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "在北赛拉姆地区点击 3-23 的旗帜和编号。不要点 3-20，也不要点「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 3-23",
        "没有匹配到 3-23。不会改点 3-20，也不会点「扫荡」。",
    )


# 7-5：找旗沿用北赛拉姆 3-20 已实机走通的做法（每帧重新认旗、旗帜分不够时用旁边的
# 任务对话圈辅助、按画面是否还在移动判断到边、只点旗帜不点气泡）。7-5 在地图中下，
# 只需要把右边拉进画面（手指左滑），所以只有一段，不先上下滑。
_SEVEN_5_IDS = ("stage_flag_7_5",)
# 7-5-1 的星星。stage_2_20_basic 是讨伐食人花已实机用过的「初步探索」星星，作备用。
_SEVEN_5_BASIC_IDS = ("stage_7_5_basic", "stage_2_20_basic")
_SEVEN_5_SWIPE_CAP = 10


def _reset_7_5_search(task) -> None:
    task._nar75_prev = None
    task._nar75_swipes = 0


def _click_7_5_near_bubble(task, image, clf, message: str):
    """同 3-20：旗帜没直接过阈值时，用旁边的任务对话圈辅助确认 7-5。只点旗帜，不点气泡。"""
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    best = None
    for template_id in _SEVEN_5_IDS:
        spec = task.by_id.get(template_id)
        if spec is None:
            continue
        match = find_template(image, spec, threshold=0.0, ocr=getattr(task, "ocr", None))
        if match is not None and (best is None or match.score > best.score):
            best = match
    if best is None or best.score < _BUBBLE_HELP_SCORE:
        return None
    if not any(_near_quest_bubble(best, bubble) for bubble in bubbles):
        return None
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [best] + bubbles,
        best,
        f"{message} 旗帜分 {best.score:.3f}，已用旁边的任务对话圈确认是 7-5。只点旗帜，不点对话圈。",
    )


def _search_7_5(task, image, clf) -> StepResult:
    msg = (
        "在纳尔本地区点击 7-5 的旗帜和编号（爪印旗、星星和「7-5」）。"
        "不要点旁边的对话气泡，也不要点「扫荡」。"
    )
    clicked = _click_first(task, image, clf, _SEVEN_5_IDS, msg, arm=False)
    if clicked is None:
        clicked = _click_7_5_near_bubble(task, image, clf, msg)
    if clicked is not None:
        # 和 3-23 一样：点旗帜后进选关页，这一步还要接着选「初步探索」。
        task.node_selected = False
        _reset_7_5_search(task)
        return clicked
    if not _on_beisa_region_map(task, image, clf):
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 7-5",
            "要去打 7-5-1（初步探索），但现在不像在纳尔本地区图上，也没有匹配到 7-5。"
            "不会改点其他旗帜，也不会编造坐标，不会点「扫荡」。",
        )
    signature = navigation._map_signature(image)
    previous = getattr(task, "_nar75_prev", None)
    swipes = int(getattr(task, "_nar75_swipes", 0))
    if signature is not None:
        moved = None if previous is None else navigation._map_moved(previous, signature)
        task._nar75_prev = signature
        if previous is not None and moved is False:
            return _halt(
                task,
                clf,
                clf.scene,
                "未找到 7-5",
                f"已经把纳尔本地区往右拉了 {swipes} 次，画面不再移动，仍然没有看到 7-5（7-5-1），"
                "已停止。不会改点其他旗帜，也不会编造坐标，不会点「扫荡」，不会点「初步探索」以外的节点。",
            )
    if swipes >= _SEVEN_5_SWIPE_CAP:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 7-5",
            f"向右拉了 {swipes} 次已经达到安全次数，仍然没有看到 7-5（7-5-1），已停止。"
            "不会继续无限滑动，也不会编造坐标，不会点「扫荡」，不会改点「初步探索」以外的节点。",
        )
    task._nar75_swipes = swipes + 1
    action = navigation._swipe(image, "east")
    action.message = (
        ("这一帧没法判断地区图有没有移动，不把它当成边界。" if signature is None else "")
        + "7-5 在纳尔本地区中下，还看不到。把右边拉进画面（手指左滑，屏幕内容往右），"
        f"滑完先找旗帜再点。第 {task._nar75_swipes} 次。不要点气泡或其他旗帜，也不要点「扫荡」。"
    )
    return _swipe_step(clf, action)


def step_fight_7_5_1(task, image, clf):
    """7-5-1：点 7-5 旗帜，再点「初步探索」的星星。

    点星星有两种已见过的结果：讨伐食人花那样直接开打；或 3-23-2 那样只是选中，
    还要点「进入」。两种都处理，绝不点「扫荡」。
    """
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD, Scene.STORY_DIALOG}:
        return ADVANCE
    missing = [
        template_id
        for template_id in ("stage_flag_7_5", "stage_7_5_basic")
        if _awaiting(task, template_id) or template_id not in task.by_id
    ]
    if missing:
        return _halt(
            task,
            clf,
            scene,
            "7-5 裁切还没有",
            "「阻碍道路的家伙」要打纳尔本 7-5-1（初步探索）。"
            f"「{'、'.join(missing)}」裁切还没有。不会编造点击，也不会点「扫荡」。",
        )
    on_select = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "stage_leave")) is not None
    if on_select:
        if task.node_selected:
            chosen = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter"))
            if chosen is None:
                return _wait(
                    task,
                    clf,
                    scene,
                    "等待开打或进入",
                    "已点过 7-5-1「初步探索」的星星。若直接开打就等战斗；"
                    "若出现「进入」再点「进入」。不要点「扫荡」。",
                )
            entered = verbs.press_stage_enter(
                task,
                image,
                clf,
                scene,
                chosen.template_id,
                "7-5「初步探索」已选中。点「进入」开战（7-5-1）。不要点更下面的「扫荡」。",
            )
            if entered.action is not None and entered.action.kind == "click":
                task.step_armed = True
            return entered
        node = verbs.best_of(task, image, _SEVEN_5_BASIC_IDS)
        if node is None:
            return _halt(
                task,
                clf,
                scene,
                "未找到初步探索",
                "已在 7-5 选关页，但没有匹配到「初步探索」的星星（7-5-1）。"
                "不会改点深入或完全探索，也不会点气泡、「进入」或「扫荡」。",
            )
        task.node_selected = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [node],
            node,
            "点击 7-5「初步探索」的星星（7-5-1）。若直接开打就进入战斗；若只是选中，再点「进入」。"
            "不要只点四个字，也不要点岛上的气泡或「扫荡」。",
        )
    if task.node_selected:
        # 点了星星后的过场帧：可能马上开打，不要回头再找旗帜。
        return _wait(
            task,
            clf,
            scene,
            "等待开打或进入",
            "已点过 7-5-1「初步探索」的星星，等战斗开始或「进入」出现。不要点「扫荡」。",
        )
    return _search_7_5(task, image, clf)


def step_fight_8_b4_basic(task, image, clf):
    if _awaiting(task, "stage_flag_8_b4") or "stage_flag_8_b4" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "8-B4 裁切还没有",
            "「受困的同伴」要清利特利尔大区 8-B4 的初步探索，不是深入或完全。"
            "关卡裁切还没有。不会编造点击，也不会点「扫荡」。",
        )
    return step_fight_stage(task, image, clf)


def step_fight_9_7_deep(task, image, clf):
    """9-7 的深入探索。不走「热情」的冒险者那条 9-7-1 初步探索。"""
    title = task._require(image, "stage_9_7_title") if "stage_9_7_title" in task.by_id else None
    on_stage = title is not None or clf.scene is Scene.STAGE_9_7
    if on_stage:
        if title is None:
            return _halt(
                task,
                clf,
                clf.scene,
                "不是 9-7",
                "这不是巡逻走廊 9-7。不会在这里点「进入」或「扫荡」。",
            )
        if task.node_selected:
            entered = verbs.press_stage_enter(
                task,
                image,
                clf,
                Scene.STAGE_9_7,
                "stage_enter_gold",
                "9-7 的「深入探索」已点过。点金色「进入」。"
                "不要点「初步探索」（那是 9-7-1），也不要点「扫荡」。",
            )
            if entered.action is not None and entered.action.kind == "click":
                task.step_armed = True
            return entered
        deep = task._require(image, "stage_node_deep") if "stage_node_deep" in task.by_id else None
        if deep is None:
            return _halt(
                task,
                clf,
                Scene.STAGE_9_7,
                "未找到深入探索",
                "9-7 上没有匹配到「深入探索」。不会改点左侧「初步探索」"
                "（那是 9-7-1，「热情」的冒险者），也不会点「扫荡」。",
            )
        center_x = deep.box.center[0]
        if center_x < image.shape[1] * 0.38:
            return _halt(
                task,
                clf,
                Scene.STAGE_9_7,
                "深入探索位置不对",
                "匹配到的「深入探索」太靠左，像是初步探索那一档。"
                "不会点它，也不会点「扫荡」。",
            )
        task.node_selected = True
        return task._click_result(
            Scene.STAGE_9_7,
            clf,
            list(clf.matches) + [deep],
            deep,
            "点击 9-7 的「深入探索」。不要点「初步探索」，也不要点「扫荡」。",
        )
    flag = task._require(image, "stage_flag_9_7") if "stage_flag_9_7" in task.by_id else None
    if flag is not None:
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [flag],
            flag,
            "在图兰顿沙漠地区点击 9-7。这条委托进深入探索，不是 9-7-1 初步探索。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 9-7",
        "要去打 9-7 深入探索，但没有匹配到 9-7。不会改点其他旗帜，也不会点「扫荡」。",
    )


def step_battle(task, image, clf):
    scene = clf.scene
    if scene is Scene.BATTLE:
        return task._plan_battle(image, clf)
    if scene is Scene.VICTORY:
        task.battle_reward_seen = True
        task.step_armed = True
        return task._plan_victory(image, clf)
    if scene is Scene.STAGE_EVENT:
        return verbs.confirm_dialog(
            task,
            image,
            clf,
            "stage_event_ok",
            "这是关卡事件，不把这一页当成战斗胜利。点「确定」，不要点「扫荡」。",
            Scene.STAGE_EVENT,
        )
    if scene is Scene.LOOT_REWARD:
        task.battle_reward_seen = True
        return verbs.dismiss_loot(
            task,
            image,
            clf,
            finishes_quest=False,
            message="领取战斗奖励，在「获得物品」上点击「触摸继续」。委托奖励还没到领取那一步。",
        )
    steps = task.recipe.steps
    nxt = task.step_index + 1
    if (
        nxt < len(steps)
        and steps[nxt] == "skip_story"
        and getattr(task, "battle_reward_seen", False)
        and (
            scene is Scene.STORY_DIALOG
            or verbs.best_of(task, image, ("skip_story", "skip_story_tight")) is not None
        )
    ):
        # 对话出现在战斗胜利并领取战斗奖励之后，这时才交给下一步去点「跳过剧情」。
        # 看见胜利或领奖页时不能提前点跳过。
        return ADVANCE
    required = getattr(task.recipe, "fights_required", 1) or 1
    fights_done = getattr(task, "fights_done", 0)
    back_on_stage = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "stage_leave")) is not None
    if task.phase is Phase.IN_BATTLE and not back_on_stage:
        # 开场横幅没了之后画面常是 UNKNOWN，继续等「战斗胜利」，不要当未知页或大地图。
        return task._plan_battle(image, clf)
    # 回到选关页（还能看到进入/离开）才算这一场打完。单场流程的 fights_done 往往仍是 0，
    # 不能只看次数，否则「奇怪的魔物」打完不会离开、也不会回 3-20。
    if (fights_done >= required or task.phase is Phase.IN_BATTLE) and back_on_stage:
        rest = task.recipe.steps[task.step_index + 1 :]
        if any(step != "claim" for step in rest):
            # 例如「奇怪的魔物」打完还要离开、回 3-20 交任务，不能在这里结束。
            return ADVANCE
        return _finish_without_claim(task, clf)
    return _wait(
        task,
        clf,
        scene,
        "等待战斗",
        "战斗还没结束。先等下一帧，不点「扫荡」，也不要点「完成」。",
        status="waiting_battle" if (scene is Scene.BATTLE or task.phase is Phase.IN_BATTLE) else "skip_unknown",
    )


def _finish_without_claim(task, clf):
    if getattr(task, "auto_sweep", False) and getattr(task, "sweep", None) is not None:
        return _finish_sweep_quest(task, clf)
    task.phase = Phase.DONE
    message = verbs.work_done_without_claim_message(task.recipe.name)
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=PlannedAction(
            kind="halt",
            label="先不领奖",
            message=message,
        ),
        status="done",
        message=message,
    )


def step_claim(task, image, clf):
    # 单条委托跑完先不点「完成」。六次都做完后用 --claim 一起领。
    return _finish_without_claim(task, clf)



_SHOP_MARKERS = ("shop_leave", "shop_tab_gold", "shop_buy", "shop_buy_disabled")
_CITY_MARKERS = (
    "city_explore_label",
    "city_explore",
    "city_association",
    "city_world_map",
    "city_world_map_text",
    "city_world_map_text_alt",
)
_A2_LIGHT_SWIPE_CAP = 8


def _in_shop(task, image) -> bool:
    return verbs.best_of(task, image, _SHOP_MARKERS) is not None


def _in_city_map(task, image) -> bool:
    return verbs.best_of(task, image, _CITY_MARKERS) is not None


def step_enter_shop(task, image, clf):
    """浪人岬城里点「商店」建筑。不要点右上背包，也不要点商品。"""
    if _in_shop(task, image):
        return ADVANCE
    if _wrong_city(task, image, clf):
        return task._plan_open_world_map(image, clf, clf.scene, here=clf.scene.zh_name)
    name = navigation.confirmed_city_name(task, image, clf)
    place = task.recipe.location
    if name and place and name != place.name:
        return task._plan_open_world_map(image, clf, clf.scene, here=name)
    if "city_shop" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "商店裁切还没有",
            f"「{task.recipe.name}」要在「{_place_name(task)}」城里点「商店」，"
            "但这块招牌的模板还没有。不会改点右上背包，也不会猜建筑坐标。",
        )
    match = task._require(image, "city_shop")
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"在「{_place_name(task)}」城里点击「商店」建筑，进入后再和老板娘对话。"
            "不要点右上背包，也不要点「购买」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到商店",
        f"「{_place_name(task)}」城里没有匹配到「商店」建筑。"
        "不会改点右上背包，也不会猜测建筑坐标。",
    )


def step_talk_metaya(task, image, clf):
    """商店里点老板娘梅塔娅的头像，不点气泡，也不点商品。"""
    if clf.scene is Scene.STORY_DIALOG or verbs.best_of(task, image, ("skip_story", "skip_story_tight")):
        return ADVANCE
    npc = task.recipe.npc_template or "npc_metaya"
    if _awaiting(task, npc) or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "梅塔娅裁切还没有",
            "要在商店里点老板娘「梅塔娅」的头像，这张裁切还没有。"
            "不会点旁边的对话气泡，也不会点「购买」或任何商品。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击商店老板娘「梅塔娅」的头像，不要点旁边的对话气泡，"
            "也不要点「购买」或任何商品。",
        )
    if _in_shop(task, image):
        return _wait(
            task,
            clf,
            clf.scene,
            "等待梅塔娅",
            "已经在商店里，但这帧还没匹配到「梅塔娅」的头像。"
            "先等下一帧，不点气泡，也不要点「购买」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到梅塔娅",
        "要在商店里点「梅塔娅」的头像，但现在既不像在商店，也没有匹配到这张脸。"
        "不会点对话气泡，也不会点「购买」。",
    )


def step_leave_shop(task, image, clf):
    """对话结束后点商店左下「离开」回城。不要点「购买」。"""
    if _in_city_map(task, image) and not _in_shop(task, image):
        return ADVANCE
    if "shop_leave" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "商店离开裁切还没有",
            "对话完了，要点商店左下「离开」回城，但这块按钮的模板还没有。"
            "不会改点协会或选关的「离开」，也不会点「购买」。",
        )
    leave = task._require(image, "shop_leave")
    if leave is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [leave],
            leave,
            "对话完了。点商店左下「离开」回到城里。不要点「购买」。",
        )
    return _wait(
        task,
        clf,
        clf.scene,
        "等待离开商店",
        "还没回到城里，也还没看到商店左下「离开」。先等下一帧，不点「购买」。",
    )


def step_fight_5_a2(task, image, clf):
    """在浪人岬地区图上找 5-A2。看不见时从中间往左边缘轻轻滑，看见就点旗帜。"""
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    flag = task.recipe.stage_flag_template or "stage_flag_5_a2"
    if _awaiting(task, flag) or flag not in task.by_id:
        return _halt(task, clf, clf.scene, "关卡裁切还没有", _pending_stage_message(task))
    match = task._require(image, flag)
    if match is not None:
        task.map_swipes = 0
        task._pan_key = None
        task._a2_prev = None
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击关卡「5-A2」的旗帜和编号，不要点旁边的气泡，也不要点「扫荡」。",
        )
    if _on_region_map(task, image):
        return _pan_light_east_for_5_a2(task, image, clf)
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 5-A2",
        "没有匹配到 5-A2，而且现在也不像在浪人岬地区图上。"
        "不会改点其他旗帜，也不会点「扫荡」。",
    )


def _pan_light_east_for_5_a2(task, image, clf) -> StepResult:
    """看不见 5-A2 时轻轻往左滑（内容往右）。到边或达到安全次数就停下说明。"""
    key = "region-flag:road_safe_langren:5-A2"
    navigation._arm_pan(task, key)
    signature = navigation._map_signature(image)
    previous = getattr(task, "_a2_prev", None)
    moved = None if previous is None or signature is None else navigation._map_moved(previous, signature)
    if signature is not None:
        task._a2_prev = signature
    swipes = task.map_swipes
    if previous is not None and moved is False:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-A2",
            f"在浪人岬地区图上轻轻向左滑了 {swipes} 次，画面已经不再移动，"
            "还是没有匹配到 5-A2，已安全停下。不会继续滑，也不会改点其他旗帜，不会点「扫荡」。",
        )
    if swipes >= _A2_LIGHT_SWIPE_CAP:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-A2",
            f"在浪人岬地区图上轻轻向左滑了 {swipes} 次，仍没有匹配到 5-A2，已安全停下。"
            "不会无限滑动，也不会改点其他旗帜，不会点「扫荡」。",
        )
    task.map_swipes = swipes + 1
    action = navigation._light_swipe(image, "east")
    action.message = (
        "浪人岬地区图上还看不到 5-A2（在地图中上部）。"
        "从屏幕中间往左边缘轻轻滑，让屏幕内容往右移；这是手指往左，不是往右。"
        "滑完先找旗帜，看见就点旗帜和「5-A2」，不要点旁边的对话气泡，也不要点「扫荡」。"
        f"第 {task.map_swipes} 次轻轻滑"
        + (f"，已经超过常见的两下，画面还在动就再试。" if task.map_swipes > 2 else "。")
    )
    return StepResult(
        scene=clf.scene,
        reason=clf.reason,
        matches=list(clf.matches),
        action=action,
        status="continue",
        message=action.message,
    )


def step_enter_5_a2_basic(task, image, clf):
    """点 5-A2「初步探索」的星星。直接开打就进战斗；出现「进入」再点「进入」。不点扫荡。"""
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD, Scene.STORY_DIALOG}:
        return ADVANCE
    if task.node_selected:
        gold = task._require(image, "stage_enter_gold") if "stage_enter_gold" in task.by_id else None
        enter_id = "stage_enter_gold" if gold is not None else "stage_enter"
        entered = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter"))
        if entered is not None:
            result = verbs.press_stage_enter(
                task,
                image,
                clf,
                scene,
                enter_id,
                "5-A2 的「初步探索」已点过。点「进入」开战。不要点「扫荡」。",
            )
            if result.action is not None and result.action.kind == "click":
                task.step_armed = True
            return result
        return _wait(
            task,
            clf,
            scene,
            "等待进入或开打",
            "已经点过 5-A2「初步探索」的星星。若出现「进入」就点「进入」；"
            "若已经开打就等战斗。不要点「扫荡」。",
        )
    node = "stage_5_a2_basic"
    match = task._require(image, node) if node in task.by_id else None
    source = "5-A2「初步探索」的星星"
    if match is None and "stage_node_basic" in task.by_id:
        match = task._require(image, "stage_node_basic")
        source = "通用「初步探索」文字"
    if match is not None:
        task.node_selected = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"点击 {source}。不要只点别处，也不要点「扫荡」。"
            "若点星星后直接开打就进入战斗；若出现「进入」再点「进入」。",
        )
    if node not in task.by_id:
        return _halt(
            task,
            clf,
            scene,
            "初步探索裁切还没有",
            "要在 5-A2 点「初步探索」的星星。这张裁切还没有。"
            "不会点「扫荡」，也不会改点深入或完全探索。",
        )
    return _halt(
        task,
        clf,
        scene,
        "未找到初步探索",
        "已在 5-A2 选关页，但没有匹配到「初步探索」的星星。"
        "不会点「扫荡」，也不会改点深入或完全探索。",
    )




_FIVE_5_IDS = ("stage_flag_5_5",)
_FIVE_5_SWIPE_CAP = 20
_FLAG_CONFLICT_MARGIN = 0.03
_FLAG_CONFLICT_DIST = 80
_PRISON_ID = "langren_evil_prison"
# 5-5 紧挨在恶骸之狱右边，不能隔着半个屏幕（否则会把右侧的 5-9 当成 5-5）。
_PRISON_MAX_GAP = 160
_PRISON_VERT_TOL = 180


def _reset_5_5_search(task) -> None:
    task._taste_phase = "down"
    task._taste_prev = None
    task._taste_swipes = 0


def _find_evil_prison(task, image):
    """地区图上的「恶骸之狱」。只用来确认 5-5 的位置，不要点这个入口。"""
    if _PRISON_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _PRISON_ID)


def _flag_right_of_prison(flag, prison) -> bool:
    """5-5 必须紧挨在恶骸之狱的右边，并且大致同一高度。"""
    fx, fy = flag.box.center
    px, py = prison.box.center
    if fx <= px:
        return False
    gap = flag.box.x - prison.box.x2
    if gap < -30:
        return False
    if gap > _PRISON_MAX_GAP:
        return False
    if abs(fy - py) > _PRISON_VERT_TOL:
        return False
    return True


def _overlapping_other_flag(task, image, match, own_id: str):
    """同一位置如果被另一面关卡旗（尤其是 5-A2）认得相当或更高，就不能当成目标旗。"""
    mx, my = match.box.center
    conflict = None
    for template_id, spec in task.by_id.items():
        if not template_id.startswith("stage_flag_") or template_id == own_id:
            continue
        other = find_template(image, spec, threshold=0.0, ocr=getattr(task, "ocr", None))
        if other is None:
            continue
        ox, oy = other.box.center
        if abs(ox - mx) > _FLAG_CONFLICT_DIST or abs(oy - my) > _FLAG_CONFLICT_DIST:
            continue
        if other.score >= match.score - _FLAG_CONFLICT_MARGIN:
            if conflict is None or other.score > conflict.score:
                conflict = other
    return conflict


def _click_5_5(task, image, clf, message: str):
    """只有同时看到「恶骸之狱」、它右边的 5-5 旗帜、以及旁边的任务对话圈时才点旗帜。

    5-A5 曾被认成 5-A2，又被当成 5-5 点进去；后来 5-9 又以 0.899 的分数
    被当成 5-5。所以：必须先认出左侧的「恶骸之狱」；不点这个入口，不点气泡；
    没有对话圈就不点；同一位置若更像 5-A2 或其他旗，也不点。
    """
    prison = _find_evil_prison(task, image)
    if prison is None:
        return None
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if "stage_flag_5_5" in task.by_id:
        match = task._require(image, "stage_flag_5_5")
    if match is None and "stage_flag_5_5" in task.by_id:
        raw = find_template(
            image,
            task.by_id["stage_flag_5_5"],
            threshold=0.0,
            ocr=getattr(task, "ocr", None),
        )
        if raw is not None and raw.score >= _BUBBLE_HELP_SCORE:
            match = raw
    if match is None:
        return None
    if not _flag_right_of_prison(match, prison):
        logger.info(
            "看到「恶骸之狱」@%s，但 5-5 候选@%s 分 %.3f 不在它紧挨着的右边，不点，避免把 5-9 当成 5-5。",
            prison.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, "stage_flag_5_5")
    if conflict is not None:
        logger.info(
            "5-5 候选和「%s」重叠（5-5=%.3f，冲突=%.3f），不点，避免把 5-A5/5-A2 当成 5-5。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到左侧「恶骸之狱」（分 {prison.score:.3f}），"
        f"旗帜在它右边，分 {match.score:.3f}，并用旁边的任务对话圈确认是 5-5。"
        "只点旗帜，不点「恶骸之狱」，不点对话圈，也不点 5-A2、5-A5、5-9 或其他旗帜。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [prison, match] + bubbles,
        match,
        helped,
    )


def _search_5_5_corner(task, image, clf) -> StepResult:
    """浪人岬地区找 5-5：在右下角偏左。先把南边拉到下沿，再把东边拉到右沿。"""
    message = (
        "点击关卡 5-5 的旗帜和编号（爪印旗、三星和「5-5」）。"
        "必须先看到「恶骸之狱」，再点它右边带任务对话圈的 5-5 旗帜。不要点「恶骸之狱」，不要点气泡，不要点 5-A2、5-A5 或 5-9，也不要点「扫荡」。"
    )
    clicked = _click_5_5(task, image, clf, message)
    if clicked is not None:
        _reset_5_5_search(task)
        return clicked

    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image)
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-5",
            "要去浪人岬 5-5 交「换换口味」，但现在不像在地区图上，也没有同时看到「恶骸之狱」和它右边带对话圈的 5-5。"
            "不会把 5-A2、5-A5 或其他旗帜当成 5-5，也不会编造坐标，不会点「扫荡」。",
        )

    phase = getattr(task, "_taste_phase", "down")
    if phase == "look":
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-5",
            "已到达浪人岬地区右下角，仍然没有同时看到「恶骸之狱」和它右边带任务对话圈的 5-5，已停止。"
            "不会把 5-A2、5-A5 或其他旗帜当成 5-5，也不会编造坐标，不会点气泡或「扫荡」。",
        )

    signature = navigation._map_signature(image)
    previous = getattr(task, "_taste_prev", None)
    swipes = int(getattr(task, "_taste_swipes", 0))
    if signature is None:
        if swipes >= _FIVE_5_SWIPE_CAP:
            return _halt(
                task,
                clf,
                clf.scene,
                "未找到 5-5",
                "没法判断地区图有没有移动，滑动已到安全次数，仍然没有同时看到「恶骸之狱」和它右边带对话圈的 5-5，已停止。"
                "不会继续无限滑动，也不会把 5-A2 或 5-A5 当成 5-5。",
            )
        task._taste_swipes = swipes + 1
        direction = "south" if phase == "down" else "east"
        action = navigation._swipe(image, direction)
        action.message = (
            "这一帧没法判断浪人岬地区图有没有移动，不把它当成边界。"
            + _five_5_swipe_message(phase, task._taste_swipes)
        )
        return _swipe_step(clf, action)

    moved = None if previous is None else navigation._map_moved(previous, signature)
    task._taste_prev = signature
    if previous is not None and moved is False:
        if phase == "down":
            task._taste_phase = "right"
            task._taste_swipes = 1
            action = navigation._swipe(image, "east")
            action.message = (
                "地图已经到下边界（画面不再移动）。5-5 在右下角偏左，"
                "接下来只把右边拉进画面（手指左滑，屏幕内容往右），直到右边界。不再上下滑动。"
                "滑完先找「恶骸之狱」，再点它右边带对话圈的 5-5 旗帜。不要点这个入口，不要点 5-A2、5-A5 或 5-9，也不要点气泡或「扫荡」。"
            )
            return _swipe_step(clf, action)
        task._taste_phase = "look"
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-5",
            "已到达浪人岬地区右下角，画面不再移动，仍然没有同时看到「恶骸之狱」和它右边带任务对话圈的 5-5，已停止。"
            "不会把 5-A2、5-A5 或其他旗帜当成 5-5，也不会编造坐标，不会点气泡或「扫荡」。",
        )

    if swipes >= _FIVE_5_SWIPE_CAP:
        side = "下" if phase == "down" else "右"
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 5-5",
            f"向{side}滑动已经达到安全次数，仍不能确认地图的{side}边界，也还没看到带对话圈的 5-5，已停止。"
            "不会继续无限滑动，也不会把 5-A2 或 5-A5 当成 5-5。",
        )
    task._taste_swipes = swipes + 1
    direction = "south" if phase == "down" else "east"
    action = navigation._swipe(image, direction)
    action.message = _five_5_swipe_message(phase, task._taste_swipes)
    return _swipe_step(clf, action)


def _five_5_swipe_message(phase: str, index: int) -> str:
    if phase == "right":
        return (
            "已经到了地图下沿。5-5 在右下角偏左，接下来只把右边拉进画面（手指左滑，屏幕内容往右），"
            f"直到右边界。第 {index} 次。滑完先找「恶骸之狱」，再点它右边带对话圈的 5-5。"
            "不要点这个入口，不要点 5-A2、5-A5 或 5-9，也不要点气泡或「扫荡」。"
        )
    return (
        "5-5 在浪人岬地区右下角偏左，还看不到带对话圈的旗帜。"
        "先把南边拉进画面（手指上滑，屏幕内容往下），"
        f"第 {index} 次。滑完先找「恶骸之狱」，再点它右边的 5-5，不要点 5-A2、5-A5、5-9、气泡或「扫荡」。"
    )


def step_fight_5_5(task, image, clf):
    """换换口味：在浪人岬地区点 5-5 旗帜，再去选关页点奇怪的蝙蝠。

    5-A5 曾被认成 5-A2 并被当成 5-5 点进去。这里只点带任务对话圈的 5-5，
    找旗方式照已走通的 3-20 / 浪人岬：看画面还动不动判断到边。
    """
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "npc_strange_bat")) is not None:
        return ADVANCE
    if _awaiting(task, "stage_flag_5_5") or "stage_flag_5_5" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡裁切还没有",
            "「换换口味」要进浪人岬 5-5。5-5 旗帜裁切还没有。不会改点 5-A2 或 5-A5，也不会点「扫荡」。",
        )
    return _search_5_5_corner(task, image, clf)



_CRYSTAL_CAVE_ID = "nan_seram_crystal_cave"
# 4-7 在结晶矿洞正上方偏左，不能隔到右边去点 4-6。
_CAVE_MAX_GAP = 160
_CAVE_HORIZ_LEFT = 40
_CAVE_HORIZ_RIGHT = 20


def _find_crystal_cave(task, image):
    """地区图上的「结晶矿洞」。只用来确认 4-7 的位置，不要点这个入口。"""
    if _CRYSTAL_CAVE_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _CRYSTAL_CAVE_ID)


def _flag_above_cave(flag, cave) -> bool:
    """4-7 必须在结晶矿洞的上方，并且大致落在矿洞的水平范围内。"""
    fx, fy = flag.box.center
    _cx, cy = cave.box.center
    if fy >= cy:
        return False
    if fx < cave.box.x - _CAVE_HORIZ_LEFT or fx > cave.box.x2 + _CAVE_HORIZ_RIGHT:
        return False
    gap = cave.box.y - flag.box.y2
    if gap < -30:
        return False
    if gap > _CAVE_MAX_GAP:
        return False
    return True


def _click_4_7(task, image, clf, message: str):
    """只有同时看到「结晶矿洞」、它上方的 4-7 旗帜、以及旁边的任务对话圈时才点旗帜。

    不要点矿洞本身，不要点右边的 4-6，不要点气泡，也不要点「扫荡」。
    看不见结晶矿洞时，即使旗帜分很高也不点。
    """
    cave = _find_crystal_cave(task, image)
    if cave is None:
        return None
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if "stage_flag_4_7" in task.by_id:
        match = task._require(image, "stage_flag_4_7")
    if match is None and "stage_flag_4_7" in task.by_id:
        raw = find_template(
            image,
            task.by_id["stage_flag_4_7"],
            threshold=0.0,
            ocr=getattr(task, "ocr", None),
        )
        if raw is not None and raw.score >= _BUBBLE_HELP_SCORE:
            match = raw
    if match is None:
        return None
    if not _flag_above_cave(match, cave):
        logger.info(
            "看到「结晶矿洞」@%s，但 4-7 候选@%s 分 %.3f 不在它上方，不点，避免把 4-6 当成 4-7。",
            cave.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, "stage_flag_4_7")
    if conflict is not None:
        logger.info(
            "4-7 候选和「%s」重叠（4-7=%.3f，冲突=%.3f），不点，避免把 4-6 当成 4-7。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到下方「结晶矿洞」（分 {cave.score:.3f}），"
        f"旗帜在它上方，分 {match.score:.3f}，并用旁边的任务对话圈确认是 4-7。"
        "只点旗帜，不点「结晶矿洞」，不点对话圈，也不点 4-6 或其他旗帜。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [cave, match] + bubbles,
        match,
        helped,
    )


def step_find_4_7(task, image, clf):
    """地震防范改造：在南赛拉姆地区点 4-7 旗帜，再去选关页与大妈对话两次。

    4-7 在结晶矿洞正上方偏左，进入地区后无需滑动就能看到。
    默认视角下如果同时看不到矿洞和带对话圈的 4-7，就停下，不编造滑动方向。
    """
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "npc_dama")) is not None:
        return ADVANCE
    if _awaiting(task, "stage_flag_4_7") or "stage_flag_4_7" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡裁切还没有",
            "「地震防范改造」要进南赛拉姆 4-7。4-7 旗帜裁切还没有。不会改点 4-6，也不会点「扫荡」。",
        )
    if _awaiting(task, _CRYSTAL_CAVE_ID) or _CRYSTAL_CAVE_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "地标裁切还没有",
            "「地震防范改造」要先认出「结晶矿洞」，再点它上方的 4-7。这个地标裁切还没有。不会猜测点击。",
        )
    message = (
        "点击关卡 4-7 的旗帜和编号（爪印旗、三星和「4-7」）。"
        "必须先看到「结晶矿洞」，再点它上方带任务对话圈的 4-7 旗帜。"
        "不要点「结晶矿洞」，不要点气泡，不要点右边的 4-6，也不要点「扫荡」。"
    )
    clicked = _click_4_7(task, image, clf, message)
    if clicked is not None:
        return clicked
    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image) or _find_crystal_cave(task, image) is not None
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-7",
            "要去南赛拉姆 4-7 做「地震防范改造」，但现在不像在地区图上，也没有同时看到「结晶矿洞」和它上方带对话圈的 4-7。"
            "不会把 4-6 或其他旗帜当成 4-7，也不会编造坐标或滑动，不会点「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 4-7",
        "南赛拉姆地区默认视角下，仍然没有同时看到「结晶矿洞」和它上方带任务对话圈的 4-7，已停止。"
        "这条进入后无需滑动就能看到，不会自己编滑动方向，也不会把 4-6 当成 4-7，不会点矿洞、气泡或「扫荡」。",
    )



_UNDERGROUND_RUINS_ID = "nan_seram_underground_ruins"
# 4-2 在地下遗迹左边、略偏下，不能点到下方的 4-1、更左边的 4-3 或中间的 4-Z。
# 数值按用户地区图放大到 1080 宽后的间距，留了余量。
_RUINS_HORIZ_MIN = -40
_RUINS_HORIZ_MAX = 175
_RUINS_VERT_MIN = -50
_RUINS_VERT_MAX = 120
_FOUR_2_SWIPE_CAP = 20


def _reset_4_2_search(task) -> None:
    task._repair_phase = "right"
    task._repair_prev = None
    task._repair_swipes = 0


def _find_underground_ruins(task, image):
    """地区图上的「地下遗迹」。只用来确认 4-2 的位置，不要点这个入口。"""
    if _UNDERGROUND_RUINS_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _UNDERGROUND_RUINS_ID)


def _flag_left_of_ruins(flag, ruins) -> bool:
    """4-2 必须在地下遗迹的左边，并且就在它左下方附近。"""
    fx, fy = flag.box.center
    if fx >= ruins.box.x:
        return False
    gap_h = ruins.box.x - flag.box.x2
    if gap_h < _RUINS_HORIZ_MIN or gap_h > _RUINS_HORIZ_MAX:
        return False
    gap_v = flag.box.y - ruins.box.y2
    if gap_v < _RUINS_VERT_MIN or gap_v > _RUINS_VERT_MAX:
        return False
    return True


def _click_4_2(task, image, clf, message: str):
    """只有同时看到「地下遗迹」、它左边的 4-2 旗帜、以及旁边的任务对话圈时才点旗帜。

    不要点遗迹本身，不要点下方的 4-1、左边的 4-3 或中间的 4-Z，不要点气泡，也不要点「扫荡」。
    看不见地下遗迹时，即使旗帜分很高也不点。
    """
    ruins = _find_underground_ruins(task, image)
    if ruins is None:
        return None
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if "stage_flag_4_2" in task.by_id:
        match = task._require(image, "stage_flag_4_2")
    if match is None and "stage_flag_4_2" in task.by_id:
        raw = find_template(
            image,
            task.by_id["stage_flag_4_2"],
            threshold=0.0,
            ocr=getattr(task, "ocr", None),
        )
        if raw is not None and raw.score >= _BUBBLE_HELP_SCORE:
            match = raw
    if match is None:
        return None
    if not _flag_left_of_ruins(match, ruins):
        logger.info(
            "看到「地下遗迹」@%s，但 4-2 候选@%s 分 %.3f 不在它左边附近，不点，避免把 4-1、4-3 或 4-Z 当成 4-2。",
            ruins.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, "stage_flag_4_2")
    if conflict is not None:
        logger.info(
            "4-2 候选和「%s」重叠（4-2=%.3f，冲突=%.3f），不点，避免把 4-1、4-3 或其他旗当成 4-2。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到右边「地下遗迹」（分 {ruins.score:.3f}），"
        f"旗帜在它左边，分 {match.score:.3f}，并用旁边的任务对话圈确认是 4-2。"
        "只点旗帜，不点「地下遗迹」，不点对话圈，也不点 4-1、4-3、4-Z 或其他旗帜。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [ruins, match] + bubbles,
        match,
        helped,
    )


def _pan_east_for_4_2(task, image, clf) -> StepResult:
    """4-2 在南赛拉姆最右边。看不见地下遗迹时，往右大划（手指左滑，划到底），靠画面还动不动判断到边。"""
    phase = getattr(task, "_repair_phase", "right")
    if phase == "look":
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-2",
            "已到达南赛拉姆地区右边界，仍然没有同时看到「地下遗迹」和它左边带任务对话圈的 4-2，已停止。"
            "不会把 4-1、4-3 或 4-Z 当成 4-2，也不会编造坐标，不会点气泡、地下遗迹或「扫荡」。",
        )

    signature = navigation._map_signature(image)
    previous = getattr(task, "_repair_prev", None)
    swipes = int(getattr(task, "_repair_swipes", 0))
    if signature is None:
        if swipes >= _FOUR_2_SWIPE_CAP:
            return _halt(
                task,
                clf,
                clf.scene,
                "未找到 4-2",
                "寻找 4-2 时没法判断地区图有没有移动，滑动已到安全次数，已停止。"
                "不会把 4-1、4-3 或 4-Z 当成 4-2，也不会编造坐标。",
            )
        task._repair_swipes = swipes + 1
        action = navigation._swipe(image, "east")
        action.message = (
            "这一帧没法判断南赛拉姆地区图有没有移动，不把它当成边界。"
            "4-2 在最右边、地下遗迹左边，把右边拉进画面（手指左滑，大划到底）。"
            f"第 {task._repair_swipes} 次。不要点地下遗迹、4-1、4-3、4-Z、气泡或「扫荡」。"
        )
        return _swipe_step(clf, action)

    moved = None if previous is None else navigation._map_moved(previous, signature)
    task._repair_prev = signature
    if previous is not None and moved is False:
        task._repair_phase = "look"
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-2",
            "已到达南赛拉姆地区右边界，画面不再移动，仍然没有同时看到「地下遗迹」和它左边带任务对话圈的 4-2，已停止。"
            "不会把 4-1、4-3 或 4-Z 当成 4-2，也不会编造坐标，不会点气泡、地下遗迹或「扫荡」。",
        )

    if swipes >= _FOUR_2_SWIPE_CAP:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-2",
            "向右滑动已经达到安全次数，仍不能确认地图的右边界，也还没看到带对话圈的 4-2，已停止。"
            "不会继续无限滑动，也不会把 4-1、4-3 或 4-Z 当成 4-2。",
        )
    task._repair_swipes = swipes + 1
    action = navigation._swipe(image, "east")
    action.message = (
        "4-2 在南赛拉姆地区最右边、地下遗迹左边，还看不到这个地标。"
        "往右大划，把右边拉进画面（手指左滑，划到底）。"
        f"第 {task._repair_swipes} 次。滑完先找「地下遗迹」，再点它左边带对话圈的 4-2。"
        "不要点这个入口，不要点 4-1、4-3 或 4-Z，也不要点气泡或「扫荡」。"
    )
    return _swipe_step(clf, action)


def step_find_4_2(task, image, clf):
    """收集维修材料：在南赛拉姆地区点 4-2 旗帜，再去选关页与维修工人对话两次。

    4-2 在地下遗迹左边，进探索后常常要往右大划才能看到。
    必须先认出「地下遗迹」，再点它左边带对话圈的 4-2。看不见地标就大划向东，到边还没有就停下。
    """
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "npc_repair_worker")) is not None:
        return ADVANCE
    if _awaiting(task, "stage_flag_4_2") or "stage_flag_4_2" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡裁切还没有",
            "「收集维修材料」要进南赛拉姆 4-2。4-2 旗帜裁切还没有。不会改点 4-1、4-3 或 4-Z，也不会点「扫荡」。",
        )
    if _awaiting(task, _UNDERGROUND_RUINS_ID) or _UNDERGROUND_RUINS_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "地标裁切还没有",
            "「收集维修材料」要先认出「地下遗迹」，再点它左边的 4-2。这个地标裁切还没有。不会猜测点击。",
        )
    message = (
        "点击关卡 4-2 的旗帜和编号（爪印旗、三星和「4-2」）。"
        "必须先看到「地下遗迹」，再点它左边带任务对话圈的 4-2 旗帜。"
        "不要点「地下遗迹」，不要点气泡，不要点 4-1、4-3 或 4-Z，也不要点「扫荡」。"
    )
    clicked = _click_4_2(task, image, clf, message)
    if clicked is not None:
        _reset_4_2_search(task)
        return clicked
    ruins = _find_underground_ruins(task, image)
    if ruins is not None:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-2",
            "已经看到「地下遗迹」，但没有同时看到它左边带任务对话圈的 4-2，已停止。"
            "不会把 4-1、4-3 或 4-Z 当成 4-2，也不会再往别处滑，不会点遗迹、气泡或「扫荡」。",
        )
    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image)
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 4-2",
            "要去南赛拉姆 4-2 做「收集维修材料」，但现在不像在地区图上，也没有同时看到「地下遗迹」和它左边带对话圈的 4-2。"
            "不会把 4-1、4-3 或 4-Z 当成 4-2，也不会编造坐标，不会点「扫荡」。",
        )
    return _pan_east_for_4_2(task, image, clf)




_SWEET_CAVE_ID = "stage_map_sweet_cave"
# 1-3 在甜蜜幻窟上方偏左。数值按用户地区图放大到 1080 宽后的间距，留了余量。
_SWEET_GAP_MIN = -40
_SWEET_GAP_MAX = 150
_SWEET_HORIZ_LEFT = 30
_SWEET_HORIZ_RIGHT = 20


def _find_sweet_cave(task, image):
    """地区图上的「甜蜜幻窟」。只用来确认 1-3 的位置，不要点这个入口。"""
    if _SWEET_CAVE_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _SWEET_CAVE_ID)


def _flag_above_sweet_cave(flag, cave) -> bool:
    """1-3 必须在甜蜜幻窟的上方偏左，不能偏到右边去点 1-4，也不能点到左边的 1-2。"""
    fx, fy = flag.box.center
    cx, cy = cave.box.center
    if fy >= cy:
        return False
    if fx < cave.box.x - _SWEET_HORIZ_LEFT or fx > cx + _SWEET_HORIZ_RIGHT:
        return False
    gap = cave.box.y - flag.box.y2
    if gap < _SWEET_GAP_MIN or gap > _SWEET_GAP_MAX:
        return False
    return True


def _click_1_3(task, image, clf, message: str):
    """只有同时看到「甜蜜幻窟」、它上方偏左的 1-3 旗帜、以及旁边的任务对话圈时才点旗帜。

    不要点帐篷本身，不要点左边的 1-2、右边的 1-4 或其他 1-1，不要点气泡，也不要点「扫荡」。
    看不见甜蜜幻窟时，即使旗帜分很高也不点。
    """
    cave = _find_sweet_cave(task, image)
    if cave is None:
        return None
    bubbles = _find_quest_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if "stage_flag_1_3" in task.by_id:
        match = task._require(image, "stage_flag_1_3")
    if match is None and "stage_flag_1_3" in task.by_id:
        raw = find_template(
            image,
            task.by_id["stage_flag_1_3"],
            threshold=0.0,
            ocr=getattr(task, "ocr", None),
        )
        if raw is not None and raw.score >= _BUBBLE_HELP_SCORE:
            match = raw
    if match is None:
        return None
    if not _flag_above_sweet_cave(match, cave):
        logger.info(
            "看到「甜蜜幻窟」@%s，但 1-3 候选@%s 分 %.3f 不在它上方偏左，不点，避免把 1-2 或 1-4 当成 1-3。",
            cave.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, "stage_flag_1_3")
    if conflict is not None:
        logger.info(
            "1-3 候选和「%s」重叠（1-3=%.3f，冲突=%.3f），不点，避免把 1-2、1-4 或其他旗当成 1-3。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到下方「甜蜜幻窟」（分 {cave.score:.3f}），"
        f"旗帜在它上方偏左，分 {match.score:.3f}，并用旁边的任务对话圈确认是 1-3。"
        "只点旗帜，不点「甜蜜幻窟」，不点对话圈，也不点 1-2、1-4 或其他旗帜。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [cave, match] + bubbles,
        match,
        helped,
    )


def step_find_1_3(task, image, clf):
    """史莱姆入侵：在莉莉托斯地区点 1-3 旗帜，再去选关页与青年对话两次后战斗。

    1-3 在甜蜜幻窟上面，进入地区后无需滑动就能看到。
    默认视角下如果同时看不到甜蜜幻窟和带对话圈的 1-3，就停下，不编造滑动方向。
    不改「喳喳布林入侵」原来点 1-3 的方式。
    """
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "npc_slime_youth")) is not None:
        return ADVANCE
    if _awaiting(task, "stage_flag_1_3") or "stage_flag_1_3" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡裁切还没有",
            "「史莱姆入侵」要进莉莉托斯 1-3。1-3 旗帜裁切还没有。不会改点 1-2 或 1-4，也不会点「扫荡」。",
        )
    if _awaiting(task, _SWEET_CAVE_ID) or _SWEET_CAVE_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "地标裁切还没有",
            "「史莱姆入侵」要先认出「甜蜜幻窟」，再点它上面的 1-3。这个地标裁切还没有。不会猜测点击。",
        )
    message = (
        "点击关卡 1-3 的旗帜和编号（爪印旗、三星和「1-3」）。"
        "必须先看到「甜蜜幻窟」，再点它上面带任务对话圈的 1-3 旗帜。"
        "不要点「甜蜜幻窟」，不要点气泡，不要点左边的 1-2、右边的 1-4 或其他 1-1，也不要点「扫荡」。"
    )
    clicked = _click_1_3(task, image, clf, message)
    if clicked is not None:
        return clicked
    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image) or _find_sweet_cave(task, image) is not None
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 1-3",
            "要去莉莉托斯 1-3 做「史莱姆入侵」，但现在不像在地区图上，也没有同时看到「甜蜜幻窟」和它上面带对话圈的 1-3。"
            "不会把 1-2、1-4 或其他旗帜当成 1-3，也不会编造坐标或滑动，不会点「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 1-3",
        "莉莉托斯地区默认视角下，仍然没有同时看到「甜蜜幻窟」和它上面带任务对话圈的 1-3，已停止。"
        "这条进入后无需滑动就能看到，不会自己编滑动方向，也不会把 1-2 或 1-4 当成 1-3，不会点帐篷、气泡或「扫荡」。",
    )



_TAVERN_MARKERS = ("tavern_title", "tavern_leave", "npc_one_eyed_hunter")
_WAGON_HOUSE_ID = "lianhu_wagon_house"
_WAGON_HORIZ_LEFT = 180
_WAGON_HORIZ_RIGHT = 30
_WAGON_GAP_MIN = -20
_WAGON_GAP_MAX = 250
_SPRING_SWIPE_CAP = 3
_SPRING_BUBBLE_IDS = ("quest_bubble_map", "quest_bubble", "quest_bubble_2_11")


def _in_tavern(task, image) -> bool:
    if "tavern_title" in getattr(task, "by_id", {}) and task._require(image, "tavern_title") is not None:
        return True
    hunter = "npc_one_eyed_hunter" in getattr(task, "by_id", {}) and task._require(image, "npc_one_eyed_hunter") is not None
    leave = "tavern_leave" in getattr(task, "by_id", {}) and task._require(image, "tavern_leave") is not None
    return bool(hunter and leave)


def step_enter_tavern(task, image, clf):
    """莉安湖城里点「酒馆」。不要点商店、协会、探险、兑换或气泡。"""
    if _in_tavern(task, image):
        return ADVANCE
    if _wrong_city(task, image, clf):
        return task._plan_open_world_map(image, clf, clf.scene, here=clf.scene.zh_name)
    name = navigation.confirmed_city_name(task, image, clf)
    place = task.recipe.location
    if name and place and name != place.name:
        return task._plan_open_world_map(image, clf, clf.scene, here=name)
    if "city_tavern" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "酒馆裁切还没有",
            f"「{task.recipe.name}」要在「{_place_name(task)}」城里点「酒馆」，"
            "但这块招牌的模板还没有。不会改点「商店」或「探险」，也不会猜建筑坐标。",
        )
    match = task._require(image, "city_tavern")
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"在「{_place_name(task)}」城里点击「酒馆」建筑，进入后再和独眼猎人对话。"
            "不要点旁边的气泡，也不要点「商店」「协会」「探险」或「兑换」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到酒馆",
        f"「{_place_name(task)}」城里没有匹配到「酒馆」建筑。"
        "不会改点「商店」或「探险」，也不会猜测建筑坐标。",
    )


def step_talk_hunter(task, image, clf):
    """酒馆里点独眼猎人的头像，不点气泡，也不点驯养师、兑换或抽蛋。"""
    if clf.scene is Scene.STORY_DIALOG or verbs.best_of(task, image, ("skip_story", "skip_story_tight")):
        return ADVANCE
    npc = "npc_one_eyed_hunter"
    if _awaiting(task, npc) or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "独眼猎人裁切还没有",
            "要在酒馆里点「独眼猎人」的头像，这张裁切还没有。"
            "不会点「驯养师」，也不会点对话气泡、「兑换」或「抽蛋」。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击酒馆里「独眼猎人 / 强壮的雇佣猎人」的头像，不要点旁边的对话气泡，"
            "也不要点「驯养师」「兑换」「抽蛋」或「离开」。",
        )
    if _in_tavern(task, image):
        return _wait(
            task,
            clf,
            clf.scene,
            "等待独眼猎人",
            "已经在酒馆里，但这帧还没匹配到「独眼猎人」的头像。"
            "先等下一帧，不点「驯养师」，也不点气泡、「兑换」或「抽蛋」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到独眼猎人",
        "要在酒馆里点「独眼猎人」的头像，但现在既不像在酒馆，也没有匹配到这张脸。"
        "不会点「驯养师」，也不会点对话气泡、「兑换」或「抽蛋」。",
    )


def step_leave_tavern(task, image, clf):
    """对话结束后点酒馆左下「离开」回城。不要点兑换或抽蛋。"""
    if _in_city_map(task, image) and not _in_tavern(task, image):
        return ADVANCE
    if "tavern_leave" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "酒馆离开裁切还没有",
            "对话完了，要点酒馆左下「离开」回城，但这块按钮的模板还没有。"
            "不会改点协会或选关的「离开」，也不会点「兑换」或「抽蛋」。",
        )
    if not _in_tavern(task, image):
        return _wait(
            task,
            clf,
            clf.scene,
            "等待离开酒馆",
            "还没回到城里，也还没确认在酒馆里。先等下一帧，不点「兑换」或「抽蛋」。",
        )
    leave = task._require(image, "tavern_leave")
    if leave is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [leave],
            leave,
            "对话完了。点酒馆左下「离开」回到城里。不要点「兑换」或「抽蛋」。",
        )
    return _wait(
        task,
        clf,
        clf.scene,
        "等待离开酒馆",
        "还在酒馆里，但这帧没看到左下「离开」。先等下一帧，不点「兑换」或「抽蛋」。",
    )


def step_skip_in_battle(task, image, clf):
    """「温泉治疗」进战斗后再跳过一次剧情。看不到就等，已经胜利就进入下一步。

    只在已经进入战斗时才把这一步算完成。前面和温泉对话后的跳过若还没结束，
    可以先点掉，但不把战斗中的这一步提前结束。
    """
    in_battle = clf.scene is Scene.BATTLE or getattr(task, "phase", None) is Phase.IN_BATTLE
    match = verbs.best_of(task, image, ("skip_story", "skip_story_tight"))
    if match is not None or clf.scene is Scene.STORY_DIALOG:
        if in_battle:
            task.step_armed = True
        return verbs.skip_story(
            task,
            image,
            clf,
            "战斗中出现剧情了。点击右上角「跳过剧情」。这场大约 10 秒后会出现，只针对这条委托。",
        )
    if clf.scene in {Scene.VICTORY, Scene.LOOT_REWARD}:
        return ADVANCE
    return _wait(
        task,
        clf,
        clf.scene,
        "等待战斗中的剧情",
        "已经要进战斗或正在战斗，还没看到右上「跳过剧情」。先等，不点「扫荡」，也不要点「完成」。"
        "这场大约 10 秒后会再跳过一次，只针对这条委托。",
        status="waiting_battle" if in_battle else "skip_unknown",
    )


def _find_wagon_house(task, image):
    if _WAGON_HOUSE_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _WAGON_HOUSE_ID)


def _flag_below_wagon_house(match, house) -> bool:
    fx, fy = match.box.center
    hx, hy = house.box.center
    if fx < house.box.x - _WAGON_HORIZ_LEFT or fx > hx + _WAGON_HORIZ_RIGHT:
        return False
    gap = match.box.y - house.box.y2
    if gap < _WAGON_GAP_MIN or gap > _WAGON_GAP_MAX:
        return False
    return fy > hy


def _find_spring_bubbles(task, image) -> list:
    found = []
    seen = set()
    # 先用共用气泡，再用这条委托自己的 2-11 气泡。不改共用名单。
    for template_id in _SPRING_BUBBLE_IDS:
        if template_id not in getattr(task, "by_id", {}):
            continue
        match = task._require(image, template_id)
        if match is None:
            continue
        key = (int(match.box.center[0]) // 8, int(match.box.center[1]) // 8)
        if key in seen:
            continue
        seen.add(key)
        found.append(match)
    return found


def _click_2_11(task, image, clf, message: str):
    """只有同时看到小屋、它下方的 2-11 旗帜、以及旁边的任务对话圈时才点旗帜。"""
    house = _find_wagon_house(task, image)
    if house is None:
        return None
    bubbles = _find_spring_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if "stage_flag_2_11" in task.by_id:
        match = task._require(image, "stage_flag_2_11")
    if match is None:
        return None
    if not _flag_below_wagon_house(match, house):
        logger.info(
            "看到小屋@%s，但 2-11 候选@%s 分 %.3f 不在它下方，不点，避免把 2-10 / 2-12 当成 2-11。",
            house.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, "stage_flag_2_11")
    if conflict is not None:
        logger.info(
            "2-11 候选和「%s」重叠（2-11=%.3f，冲突=%.3f），不点。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到 2-5 右边的小屋（分 {house.score:.3f}），"
        f"旗帜在它下方，分 {match.score:.3f}，并用旁边的任务对话圈确认是 2-11。"
        "只点旗帜，不点小屋，不点对话圈，也不点 2-10、2-12、2-5 或 2-6。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [house, match] + bubbles,
        match,
        helped,
    )


def _reset_2_11_search(task) -> None:
    task.map_swipes = 0
    task._pan_key = None
    task._spring_prev = None


def step_find_2_11(task, image, clf):
    """在莉安湖地区图上找 2-11。看不见就从左边缘划到中间；看见小屋和带气泡的旗帜再点。"""
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter", "npc_hot_spring")) is not None:
        _reset_2_11_search(task)
        return ADVANCE
    flag = task.recipe.stage_flag_template or "stage_flag_2_11"
    if _awaiting(task, flag) or flag not in task.by_id:
        return _halt(task, clf, clf.scene, "关卡裁切还没有", "「温泉治疗」的 2-11 旗帜裁切还没有，不会编造坐标去点。")
    if _awaiting(task, _WAGON_HOUSE_ID) or _WAGON_HOUSE_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "小屋裁切还没有",
            "要先认出 2-5 右边的小屋再点 2-11，但这块辅助识别还没有。不会编造坐标，也不会点「扫荡」。",
        )
    message = (
        "点击关卡 2-11 的旗帜和编号（爪印旗、三星和「2-11」）。"
        "必须先看到 2-5 右边、2-6 左边的小屋，再点它下方带任务对话圈的 2-11 旗帜。"
        "不要点小屋，不要点气泡，不要点 2-10、2-12、2-5 或 2-6，也不要点「扫荡」。"
    )
    clicked = _click_2_11(task, image, clf, message)
    if clicked is not None:
        _reset_2_11_search(task)
        return clicked

    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image) or _find_wagon_house(task, image) is not None
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 2-11",
            "要去莉安湖 2-11 做「温泉治疗」，但现在不像在地区图上，也没有同时看到小屋和它下方带对话圈的 2-11。"
            "不会把 2-10、2-12 或其他旗帜当成 2-11，也不会编造坐标，不会点「扫荡」。",
        )

    swipes = int(getattr(task, "map_swipes", 0) or 0)
    signature = navigation._map_signature(image)
    previous = getattr(task, "_spring_prev", None)
    if previous is not None and not navigation._map_moved(previous, signature):
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 2-11",
            "已经从边缘划到中间，画面不再移动，仍然没有同时看到小屋和它下方带任务对话圈的 2-11，已停止。"
            "不会改用轻轻划或大划，也不会把 2-10、2-12 当成 2-11，不会点气泡或「扫荡」。",
        )
    if swipes >= _SPRING_SWIPE_CAP:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 2-11",
            "已经从左边缘向中间滑过几次，仍然没有同时看到小屋和它下方带任务对话圈的 2-11，已停止。"
            "不会继续大划，也不会编造坐标，不会点「扫荡」。",
        )
    task.map_swipes = swipes + 1
    task._spring_prev = signature
    action = navigation._edge_to_center_swipe(image, "west")
    action.message = (
        f"莉安湖地区还看不到位于中间的 2-11。按住左边缘划到中间（屏幕内容往右），"
        f"不要从中间划到边缘，也不要大划。第 {task.map_swipes}/{_SPRING_SWIPE_CAP} 次。"
        "看见小屋和它下方带对话圈的 2-11 再点旗帜，不要点气泡或「扫荡」。"
    )
    return _swipe_step(clf, action)


# 南赛拉姆「保证商路畅通」：4-C1 左边小屋只给这条找 4-21 用。
# 进入探索后不用滑动；默认视角看不到就停。不要改共用气泡名单。
_C1_HOUSE_ID = "nan_seram_c1_house"
_ROAD_NAN_BUBBLE_IDS = _QUEST_BUBBLE_IDS + ("quest_bubble_4_21",)
# 4-21 在小屋右上方。旗中心必须高于小屋顶，并且在小屋右缘附近以右，
# 这样才能排除正上方的 4-22，以及右边但更靠下的 4-C1。
_C1_HOUSE_RIGHT_SLACK = 20


def _find_c1_house(task, image):
    if _C1_HOUSE_ID not in task.by_id:
        return None
    return task._require(image, _C1_HOUSE_ID)


def _find_4_21_bubbles(task, image):
    found = []
    seen = set()
    for template_id in _ROAD_NAN_BUBBLE_IDS:
        if template_id not in task.by_id:
            continue
        match = task._require(image, template_id)
        if match is None:
            continue
        key = match.box.center
        if key in seen:
            continue
        seen.add(key)
        found.append(match)
    return found


def _flag_above_right_of_c1_house(flag, house) -> bool:
    fx, fy = flag.box.center
    if fy >= house.box.y:
        return False
    if fx <= house.box.x2 - _C1_HOUSE_RIGHT_SLACK:
        return False
    return True


def _click_4_21(task, image, clf, message: str):
    """只有同时看到 4-C1 左边小屋、它右上方的 4-21 旗帜、以及旁边的任务对话圈时才点旗帜。"""
    house = _find_c1_house(task, image)
    if house is None:
        return None
    bubbles = _find_4_21_bubbles(task, image)
    if not bubbles:
        return None
    flag_id = task.recipe.stage_flag_template or "stage_flag_4_21"
    if flag_id not in task.by_id:
        return None
    match = task._require(image, flag_id)
    if match is None:
        return None
    if not _flag_above_right_of_c1_house(match, house):
        logger.info(
            "看到 4-C1 左边小屋 @%s，但 4-21 候选 @%s 分 %.3f 不在它右上方，不点，避免把 4-22 或 4-C1 当成 4-21。",
            house.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, flag_id)
    if conflict is not None:
        logger.info(
            "4-21 候选和「%s」重叠（4-21=%.3f，冲突=%.3f），不点，避免把 4-22 / 4-23 / 4-C1 当成 4-21。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到 4-C1 左边小屋（分 {house.score:.3f}），"
        f"旗帜在它右上方，分 {match.score:.3f}，并用旁边的任务对话圈确认是 4-21。"
        "只点旗帜，不点小屋，不点对话圈，也不点 4-22、4-23、4-C1、底部「矿洞」「回程」或「探索队」。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [house, match] + bubbles,
        match,
        helped,
    )


def step_talk_mejita(task, image, clf):
    """在南赛拉姆商店点梅姬塔的头像。不点气泡，也不点购买或底部按钮。"""
    if clf.scene is Scene.STORY_DIALOG:
        return ADVANCE
    npc = task.recipe.npc_template or "npc_mejita"
    if _awaiting(task, npc) or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "梅姬塔裁切还没有",
            "「保证商路畅通」（南赛拉姆）要在商店里点「梅姬塔 / 商店的老板娘」的头像。"
            "这张裁切还没有。不会猜一张脸，也不要点「购买全部」「购买」「离开」「时装」「兑换」或「氪金」。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "在商店点击「梅姬塔」的头像，不要点气泡，也不要点「购买全部」「购买」「离开」「时装」「兑换」或「氪金」。",
        )
    if _in_shop(task, image):
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到梅姬塔",
            "已经在商店里，但没有匹配到「梅姬塔 / 商店的老板娘」的头像。"
            "不会点「购买全部」「购买」「离开」「时装」「兑换」或「氪金」，也不会点底部名字牌。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "还没进商店",
        "「保证商路畅通」（南赛拉姆）要先在城里进「商店」，再和梅姬塔对话。"
        "现在还没看到她。不会点协会、酒馆或探险来代替。",
    )


def step_find_4_21(task, image, clf):
    """在南赛拉姆地区图上找 4-21。进入探索后不用滑动；默认视角看不到就停。"""
    if verbs.best_of(
        task,
        image,
        ("stage_enter_gold", "stage_enter", "stage_4_21_basic", "stage_2_20_basic"),
    ) is not None:
        return ADVANCE
    flag = task.recipe.stage_flag_template or "stage_flag_4_21"
    if _awaiting(task, flag) or flag not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "4-21 旗帜裁切还没有",
            "「保证商路畅通」（南赛拉姆）要在南赛拉姆地区右下点 4-21 旗帜。"
            "这张裁切还没有。不会猜位置，也不会滑动。",
        )
    if _awaiting(task, _C1_HOUSE_ID) or _C1_HOUSE_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "小屋裁切还没有",
            "「保证商路畅通」（南赛拉姆）要先认出 4-C1 左边的小屋，再点它右上方的 4-21。"
            "这张裁切还没有。不会把底部「矿洞」当成地标，也不会滑动。",
        )
    clicked = _click_4_21(
        task,
        image,
        clf,
        "在南赛拉姆地区右下点击 4-21 旗帜。",
    )
    if clicked is not None:
        return clicked
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 4-21",
        "进入探索后不用滑动就能看到 4-21，它在画面右下。"
        "必须同时看到 4-C1 左边的小屋和带任务对话圈的 4-21 旗帜才点旗帜。"
        "看不见小屋时，即使旗帜分很高也不点，以免把 4-22 或 4-C1 当成 4-21。"
        "默认视角同时看不到这两样就停下，不要自行滑动。"
        "不要点小屋，不要点气泡，不要点 4-22、4-23、4-C1，"
        "也不要点底部「矿洞」「回程」「探索队」，更不要点「扫荡」或「结晶矿洞」。",
    )


def step_enter_4_21_basic(task, image, clf):
    """在 4-21 选关页点「初步探索」的星星。战斗自己开始就进入战斗，出现「进入」再点「进入」。不要点「扫荡」。"""
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD, Scene.STORY_DIALOG}:
        return ADVANCE
    enter = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter"))
    if enter is not None:
        task.step_armed = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [enter],
            enter,
            "已选中 4-21「初步探索」，点击「进入」。不要点「扫荡」，也不要点深入或完全探索。",
        )
    if getattr(task, "node_selected", False):
        return None
    node_ids = ("stage_4_21_basic", "stage_2_20_basic", "stage_node_basic")
    match = verbs.best_of(task, image, node_ids)
    if match is not None:
        task.node_selected = True
        task.step_armed = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击 4-21「初步探索」的星星。不要点气泡或「扫荡」。"
            "战斗自己开始就进入战斗；出现「进入」再点「进入」。不要改点深入或完全探索。",
        )
    return _halt(
        task,
        clf,
        scene,
        "未找到初步探索",
        "已在 4-21 选关页，但没有匹配到「初步探索」的星星。"
        "不会点「扫荡」，也不会改点深入或完全探索。",
    )



_B4_TOWER_ID = "litril_b4_tower"
_B4_FLAG_ID = "stage_flag_8_b4"
_B4_BUBBLE_ID = "quest_bubble_8_b4"
_B4_TOWER_MAX_BELOW = 220
_B4_TOWER_MAX_RIGHT_GAP = 80


def _reset_8_b4_search(task) -> None:
    task._b4_swiped = False


def _find_8_b4_tower(task, image):
    """地区图上 8-B4 左上方的木瞭望塔。只用来确认位置，不要点这座塔。"""
    if _B4_TOWER_ID not in getattr(task, "by_id", {}):
        return None
    return task._require(image, _B4_TOWER_ID)


def _flag_below_tower(flag, tower) -> bool:
    """真 8-B4 在木瞭望塔下方、稍偏右，并且离得不远。"""
    fx, fy = flag.box.center
    if fy <= tower.box.y2 - 30:
        return False
    if flag.box.y < tower.box.y:
        return False
    if fx < tower.box.x - 20:
        return False
    gap = flag.box.x - tower.box.x2
    if gap > _B4_TOWER_MAX_RIGHT_GAP:
        return False
    if flag.box.y - tower.box.y2 > _B4_TOWER_MAX_BELOW:
        return False
    return True


def _find_8_b4_bubbles(task, image) -> list:
    """先用已有共用气泡，再试这条委托自己的 8-B4 气泡。不改共用名单。"""
    found = list(_find_quest_bubbles(task, image))
    seen = {(int(item.box.x), int(item.box.y)) for item in found}
    if _B4_BUBBLE_ID in getattr(task, "by_id", {}):
        match = task._require(image, _B4_BUBBLE_ID)
        if match is not None:
            key = (int(match.box.x), int(match.box.y))
            if key not in seen:
                found.append(match)
    return found


def _click_8_b4(task, image, clf, message: str):
    """只有同时看到木瞭望塔、它下方的 8-B4 旗帜、以及旁边的任务对话圈时才点旗帜。"""
    tower = _find_8_b4_tower(task, image)
    if tower is None:
        return None
    bubbles = _find_8_b4_bubbles(task, image)
    if not bubbles:
        return None
    match = None
    if _B4_FLAG_ID in task.by_id:
        match = task._require(image, _B4_FLAG_ID)
    if match is None and _B4_FLAG_ID in task.by_id:
        raw = find_template(
            image,
            task.by_id[_B4_FLAG_ID],
            threshold=0.0,
            ocr=getattr(task, "ocr", None),
        )
        if raw is not None and raw.score >= _BUBBLE_HELP_SCORE:
            match = raw
    if match is None:
        return None
    if not _flag_below_tower(match, tower):
        logger.info(
            "看到木瞭望塔@%s，但 8-B4 候选@%s 分 %.3f 不在它下方附近，不点，避免把 8-D5 或其他旗当成 8-B4。",
            tower.box.center,
            match.box.center,
            match.score,
        )
        return None
    if not any(_near_quest_bubble(match, bubble) for bubble in bubbles):
        return None
    conflict = _overlapping_other_flag(task, image, match, _B4_FLAG_ID)
    if conflict is not None:
        logger.info(
            "8-B4 候选和「%s」重叠（8-B4=%.3f，冲突=%.3f），不点。",
            conflict.template_id,
            match.score,
            conflict.score,
        )
        return None
    task.step_armed = True
    helped = (
        f"{message} 已看到左上方木瞭望塔（分 {tower.score:.3f}），"
        f"旗帜在它下方，分 {match.score:.3f}，并用旁边的任务对话圈确认是 8-B4。"
        "只点旗帜，不点瞭望塔，不点对话圈，也不点 8-D5、8-D4、8-C1 或其他旗帜。"
        "不要点底部「矿洞」「回程」或「探索队」，也不要点「扫荡」。"
    )
    return task._click_result(
        clf.scene,
        clf,
        list(clf.matches) + [tower, match] + bubbles,
        match,
        helped,
    )


def step_find_8_b4(task, image, clf):
    """在利特利尔大区地区图上找 8-B4。看不见就从右边缘向左边缘轻轻划一下，只划一次，还没有就停。"""
    if verbs.best_of(
        task,
        image,
        ("stage_enter_gold", "stage_enter", "stage_8_b4_basic", "stage_2_20_basic"),
    ) is not None:
        return ADVANCE
    flag = task.recipe.stage_flag_template or _B4_FLAG_ID
    if _awaiting(task, flag) or flag not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "8-B4 旗帜裁切还没有",
            "「受困的同伴」要在利特利尔大区点 8-B4 的初步探索，不是深入或完全。"
            "关卡裁切还没有。不会编造点击，也不会点「扫荡」。",
        )
    if _awaiting(task, _B4_TOWER_ID) or _B4_TOWER_ID not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "瞭望塔裁切还没有",
            "「受困的同伴」要先认出 8-B4 左上方的木瞭望塔，再点它下方的 8-B4。"
            "这张裁切还没有。不会把底部「矿洞」当成地标，也不会编造点击。",
        )
    message = (
        "点击关卡 8-B4 的旗帜和编号（爪印旗、三星和「8-B4」）。"
        "必须先看到左上方的木瞭望塔，再点它下方带任务对话圈的 8-B4 旗帜。"
        "不要点瞭望塔，不要点气泡，不要点 8-D5、8-D4 或 8-C1，"
        "也不要点底部「矿洞」「回程」「探索队」或「扫荡」。"
    )
    clicked = _click_8_b4(task, image, clf, message)
    if clicked is not None:
        _reset_8_b4_search(task)
        return clicked

    on_map = clf.scene in {
        Scene.STAGE_MAP,
        Scene.STAGE_DESERT,
        Scene.STAGE_1_3,
        Scene.STAGE_9_7,
    } or _on_region_map(task, image)
    if not on_map:
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 8-B4",
            "「受困的同伴」要去利特利尔大区 8-B4 打初步探索，不是深入或完全。"
            "现在不像在地区图上，也没有同时看到木瞭望塔和它下方带对话圈的 8-B4。"
            "不会改点 8-D5、8-D4 或 8-C1，也不会编造坐标，不会点「扫荡」。",
        )

    if getattr(task, "_b4_swiped", False):
        return _halt(
            task,
            clf,
            clf.scene,
            "未找到 8-B4",
            "已经从右边缘向左边缘轻轻划过一次，仍然没有同时看到木瞭望塔和它下方带任务对话圈的 8-B4，已停止。"
            "不会再划，不会改点 8-D5、8-D4、8-C1，也不会编造坐标，不会点气泡、瞭望塔、"
            "底部「矿洞」「回程」「探索队」或「扫荡」。",
        )

    task._b4_swiped = True
    action = navigation._right_to_left_edge_swipe(image)
    action.message = (
        "在利特利尔大区还没同时看到木瞭望塔和它下方带任务对话圈的 8-B4。"
        "往右轻轻划一下：手指从屏幕右边缘滑到左边缘，屏幕内容往右。只划这一次，不会再划，也不划到地图边界。"
        "不要用从中间划到边缘，也不要从左边缘划到中间，更不要用大划。"
        "滑完先找瞭望塔，再点它下方的 8-B4 旗帜。"
        "不要点瞭望塔、气泡、8-D5、8-D4、8-C1，也不要点底部「矿洞」「回程」「探索队」或「扫荡」。"
    )
    return _swipe_step(clf, action)


def step_enter_8_b4_basic(task, image, clf):
    """在 8-B4 选关页点「初步探索」的星星。战斗自己开始就进入战斗，出现「进入」再点「进入」。不要点「扫荡」。"""
    scene = clf.scene
    if scene in {Scene.BATTLE, Scene.VICTORY, Scene.LOOT_REWARD}:
        return ADVANCE
    enter = verbs.best_of(task, image, ("stage_enter_gold", "stage_enter"))
    if enter is not None:
        task.step_armed = True
        return verbs.press_stage_enter(
            task,
            image,
            clf,
            scene,
            enter.template_id,
            "已选中 8-B4「初步探索」，点击「进入」。不要点「扫荡」，也不要点深入或完全探索。",
        )
    if getattr(task, "node_selected", False):
        return None
    node_ids = ("stage_8_b4_basic", "stage_2_20_basic", "stage_node_basic")
    match = verbs.best_of(task, image, node_ids)
    if match is not None:
        task.node_selected = True
        task.step_armed = True
        return task._click_result(
            scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击 8-B4「初步探索」的星星。不要点气泡或「扫荡」。"
            "战斗自己开始就进入战斗；出现「进入」再点「进入」。不要改点深入或完全探索。",
        )
    return _halt(
        task,
        clf,
        scene,
        "未找到初步探索",
        "已在 8-B4 选关页，但没有匹配到「初步探索」的星星。"
        "不会点「扫荡」，也不会改点深入或完全探索。",
    )


_HANDLERS = {
    "check_item": step_check_item,
    "accept_board": step_accept_board,
    "leave_association": step_leave_association,
    "reenter_association": step_reenter_association,
    "talk_dashu": step_talk_dashu,
    "talk_youth": step_talk_youth,
    "talk_on_stage": step_talk_on_stage,
    "talk_task_npc": step_talk_task_npc,
    "city_talk": step_city_talk,
    "skip_story": step_skip_story,
    "leave_stage": step_leave_stage,
    "explore": step_explore,
    "fight_stage": step_fight_stage,
    "enter_basic_starts_battle": step_enter_basic_starts_battle,
    "enter_3_20": step_enter_3_20,
    "return_3_20": step_return_3_20,
    "fight_3_23_2": step_fight_3_23_2,
    "fight_7_5_1": step_fight_7_5_1,
    "fight_8_b4_basic": step_fight_8_b4_basic,
    "find_8_b4": step_find_8_b4,
    "enter_8_b4_basic": step_enter_8_b4_basic,
    "fight_9_7_deep": step_fight_9_7_deep,
    "battle": step_battle,
    "claim": step_claim,
    "pending": step_pending,
    "enter_shop": step_enter_shop,
    "talk_metaya": step_talk_metaya,
    "leave_shop": step_leave_shop,
    "fight_5_a2": step_fight_5_a2,
    "enter_5_a2_basic": step_enter_5_a2_basic,
    "fight_5_5": step_fight_5_5,
    "find_4_7": step_find_4_7,
    "find_4_2": step_find_4_2,
    "find_1_3": step_find_1_3,
    "enter_tavern": step_enter_tavern,
    "talk_hunter": step_talk_hunter,
    "leave_tavern": step_leave_tavern,
    "find_2_11": step_find_2_11,
    "skip_in_battle": step_skip_in_battle,
    "talk_mejita": step_talk_mejita,
    "find_4_21": step_find_4_21,
    "enter_4_21_basic": step_enter_4_21_basic,
}
