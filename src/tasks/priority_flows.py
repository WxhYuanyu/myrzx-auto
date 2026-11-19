"""按高 / 中 / 低分档的每日委托步骤。

区域地图上的开头仍走 daily_commission._plan_region_to_place（图谱里的地点）。
这里只接「已经要去哪座城」之后的差别：重进协会、关卡上对话、
3-20 去而复返、9-7 深入而不是 9-7-1。缺裁切就停，不造点击。
"""

from __future__ import annotations

from src.tasks.base import PlannedAction, StepResult
from src.tasks.phase import Phase
from src.tasks import navigation, verbs
from src.tasks.scroll import BAG_ITEM_REGION, ListScroll, cell_signature
from src import config
from src.vision.types import Scene


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


def _wrong_city(task, scene: Scene) -> bool:
    """已确认的城市场景如果不是目标城，就要回大地图。不靠「协会」猜城。"""
    place = task.recipe.location
    if place is None:
        return False
    if scene is Scene.CITY_LILITOS and place.name != "王城莉莉托斯":
        return True
    if scene is Scene.CITY_TURANDON and place.name != "图兰顿沙漠":
        return True
    return False


def _click_association(task, image, clf):
    if _wrong_city(task, clf.scene):
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


def _swipe_bag(task, image, clf, message: str) -> StepResult:
    height, width = image.shape[:2]
    # 只在道具格子上滑，避开顶上的分页和返回。
    x = width // 2
    y1 = int(height * 0.72)
    y2 = int(height * 0.42)
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
            f"背包里没有「{item}」，不接取「{name}」。用右上返回关掉列表。不要点屏幕底部「离开」。",
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
                f"背包里没有「{item}」，不接取「{skipped}」，也不占用每日次数。"
                f"接着看本城的「{task.recipe.name}」。",
                status="continue",
            )
        if not task.sweep.advance_place_or_tier():
            task.phase = Phase.DONE
            message = (
                f"背包里没有「{item}」，不接取「{skipped}」。"
                f"高、中、低三档都看过了，共做了 {task.sweep.completed} 次。"
                "先不点「完成」。可用 --live --claim 一起领。"
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
            f"背包里没有「{item}」，不接取「{skipped}」，也不占用每日次数。"
            f"接着看{task.sweep.tier.zh_name}级：去「{place}」的「{task.recipe.name}」。",
            status="continue",
        )
    return _halt(
        task,
        clf,
        scene,
        "没有所需物品",
        f"背包里没有「{item}」，不接取「{name}」。这条单跑到此结束，不会占用每日次数。",
    )


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

    found = task._require(image, item_id)
    if found is not None:
        task.item_ready = True
        closed = close_open_bag(
            task,
            image,
            clf,
            f"背包里有「{item}」，关上背包后再接取「{name}」。不要点这件物品。",
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
            f"在「道具」页往下翻，找「{item}」。{note}"
            f"第 {task.bag_swipes}/{BAG_SWIPE_CAP} 次。不要点格子里的物品。",
        )
    if decision == "cap":
        task.item_ready = False
        closed = close_open_bag(
            task,
            image,
            clf,
            f"背包滑到安全次数，还不能确认已经到底，先停下。没有确认「{item}」，不接取「{name}」。"
            "不要点格子里的物品。",
        )
        if closed is not None:
            return closed
        return _halt(
            task,
            clf,
            clf.scene,
            "背包没有滑到底",
            f"背包滑到安全次数，还不能确认已经到底。不把这一帧当成没有「{item}」，也不接取「{name}」。",
        )

    task.item_ready = False
    closed = close_open_bag(
        task,
        image,
        clf,
        f"「道具」页已经滑到底，没有「{item}」，关上背包，不接取「{name}」。不要点格子里的物品。",
    )
    if closed is not None:
        return closed
    return _skip_missing_item(task, image, clf)


def step_accept_board(task, image, clf):


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
    if _awaiting(task, card) and scene in {Scene.COMMISSION_LIST, Scene.UNKNOWN}:
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
    if scene is Scene.QUEST_DETAIL:
        return task._plan_quest_detail(image, clf)
    if scene is Scene.ASSOCIATION:
        foreign = _foreign_association(task, image, clf)
        if foreign is not None:
            return foreign
        match = verbs.best_of(
            task,
            image,
            ("association_commission", "association_commission_turandon"),
        )
        if match is not None:
            return task._click_result(
                scene,
                clf,
                list(clf.matches) + [match],
                match,
                "打开协会右下角的委托中心。",
            )
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
    if _wrong_city(task, clf.scene):
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
    if _wrong_city(task, clf.scene):
        return task._plan_open_world_map(image, clf, clf.scene, here=clf.scene.zh_name)
    name = navigation.confirmed_city_name(task, image, clf)
    place = task.recipe.location
    if name and place and name != place.name:
        return task._plan_open_world_map(image, clf, clf.scene, here=name)
    match = verbs.best_of(task, image, ("city_explore_label", "city_explore"))
    if (
        match is not None
        and place is not None
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
            f"从「{_place_name(task)}」城内右下「探险」去关卡。不点「扫荡」。",
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


def step_enter_3_20(task, image, clf):
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    clicked = _click_first(
        task,
        image,
        clf,
        ("stage_flag_3_20", "stage_node_3_20"),
        "点击关卡 3-20 的旗帜（爪印旗、三星和「3-20」）。不要点旁边的对话气泡，也不要改点 3-23。",
        arm=True,
    )
    if clicked is not None:
        return clicked
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 3-20",
        "北赛拉姆地区没有匹配到 3-20。不会改点 3-23 或其他旗帜。",
    )


def step_return_3_20(task, image, clf):
    if verbs.best_of(task, image, ("stage_enter_gold", "stage_enter")) is not None:
        return ADVANCE
    clicked = _click_first(
        task,
        image,
        clf,
        ("stage_flag_3_20", "stage_node_3_20"),
        "打完 3-23-2 后回到 3-20，再和青年对话交任务。点击 3-20 的旗帜，不要点气泡。",
        arm=True,
    )
    if clicked is not None:
        return clicked
    return _halt(
        task,
        clf,
        clf.scene,
        "未能回到 3-20",
        "要回到 3-20 交任务，但没有匹配到 3-20。不会改点 3-23，也不会编造坐标。",
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


def step_fight_7_5_1(task, image, clf):
    if _awaiting(task, "stage_flag_7_5") or "stage_flag_7_5" not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "7-5 裁切还没有",
            "「阻碍道路的家伙」要打纳尔本 7-5-1（初步探索）。关卡裁切还没有。"
            "不会编造点击，也不会点「扫荡」。",
        )
    return step_fight_stage(task, image, clf)


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
        return verbs.dismiss_loot(
            task,
            image,
            clf,
            finishes_quest=False,
            message="关掉这页掉落。委托奖励还没到领取那一步。",
        )
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
    "fight_9_7_deep": step_fight_9_7_deep,
    "battle": step_battle,
    "claim": step_claim,
    "pending": step_pending,
}
