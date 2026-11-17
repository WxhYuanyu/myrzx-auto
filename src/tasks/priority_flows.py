"""七条优先委托各自的步骤。

区域地图上的开头仍走 daily_commission._plan_region_to_place（图谱里的地点）。
这里只接「已经要去哪座城」之后的差别：重进协会、关卡上对话、
3-20 去而复返、9-7 深入而不是 9-7-1。缺裁切就停，不造点击。
"""

from __future__ import annotations

from src.tasks.base import PlannedAction, StepResult
from src.tasks.phase import Phase
from src.tasks import verbs
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
    place = task.recipe.location
    if place is None:
        return False
    if scene is Scene.CITY_TURANDON and place.city_scene is not Scene.CITY_TURANDON:
        return True
    if scene is Scene.CITY_LILITOS and place.city_scene is Scene.CITY_TURANDON:
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
    if _awaiting(task, card) and scene in {Scene.COMMISSION_LIST, Scene.UNKNOWN}:
        return _halt(
            task,
            clf,
            scene,
            "标题裁切还没有",
            f"「{task.recipe.name}」的标题裁切还没有，不会在委托板上改点别的卡。",
        )
    if scene is Scene.COMMISSION_LIST:
        return verbs.accept_listed_card(task, image, clf)
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
        if match is not None:
            return task._click_result(
                scene,
                clf,
                list(clf.matches) + [match],
                match,
                f"进入「{_place_name(task)}」的协会。",
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
    return _wait(task, clf, scene, "等待离开协会", "还在离开协会的过渡画面，先等下一帧。")


def step_reenter_association(task, image, clf):
    if clf.scene is Scene.ASSOCIATION:
        foreign = _foreign_association(task, image, clf)
        if foreign is not None:
            return foreign
        return ADVANCE
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
    match = task._require(image, "npc_qingnian") if "npc_qingnian" in task.by_id else None
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击「青年 / 年轻的小哥」的脸，不要点气泡。"
            "奇怪的魔物卡片上的铠甲骑士不是这个人。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到青年",
        "3-20 上没有匹配到「青年」的脸。不会点对话气泡，"
        "也不会把卡片上的铠甲骑士当成这个 NPC。",
    )


def step_talk_on_stage(task, image, clf):
    npc = task.recipe.npc_template
    if _awaiting(task, npc) or not npc or npc not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "关卡 NPC 裁切还没有",
            "「温泉治疗」要在关卡 2-11 上点任务 NPC 的脸，这张裁切还没有。"
            "人在关卡上，不在协会里。不会点「协会大叔」，也不会猜一张脸。",
        )
    match = task._require(image, npc)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "在 2-11 上点击任务 NPC 的脸，不要点气泡。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 2-11 的 NPC",
        "已在关卡页，但没有匹配到温泉治疗的任务 NPC。不会点协会大叔，也不会猜一张脸。",
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
    if _wrong_city(task, clf.scene):
        return task._plan_open_world_map(image, clf, clf.scene)
    match = task._require(image, "city_explore") if "city_explore" in task.by_id else None
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


def step_fight_stage(task, image, clf):
    flag = task.recipe.stage_flag_template
    if _awaiting(task, flag) or not flag or flag not in task.by_id:
        return _halt(task, clf, clf.scene, "关卡裁切还没有", _pending_stage_message(task))
    match = task._require(image, flag)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            f"点击关卡「{task.recipe.stage_label}」。不点旁边的旗帜，也不点「扫荡」。",
        )
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到关卡",
        f"没有匹配到「{task.recipe.stage_label}」。不会改点其他旗帜，也不会点「扫荡」。",
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


def step_enter_3_20(task, image, clf):
    clicked = _click_node(
        task,
        image,
        clf,
        "stage_node_3_20",
        "点击关卡 3-20 的旗帜（三星和「3-20」）。不要点旁边的对话气泡，也不要改点 1-3。",
        arm=True,
    )
    if clicked is not None:
        return clicked
    return _halt(
        task,
        clf,
        clf.scene,
        "未找到 3-20",
        "没有匹配到 3-20。不会改点 1-3 或其他旗帜。",
    )


def step_return_3_20(task, image, clf):
    clicked = _click_node(
        task,
        image,
        clf,
        "stage_node_3_20",
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


def step_fight_3_23_2(task, image, clf):
    flag = "stage_flag_3_23"
    if _awaiting(task, flag) or flag not in task.by_id:
        return _halt(
            task,
            clf,
            clf.scene,
            "3-23 裁切还没有",
            "要去打 3-23-2（深入探索）。3-23 的旗帜裁切还没有。"
            "不会再点 3-20，也不会编造坐标，不会点「扫荡」。",
        )
    match = task._require(image, flag)
    if match is not None:
        task.step_armed = True
        return task._click_result(
            clf.scene,
            clf,
            list(clf.matches) + [match],
            match,
            "点击 3-23，然后进入深入探索（3-23-2）。不要点 3-20，也不要点「扫荡」。",
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
    opened = verbs.open_quest_scroll(
        task,
        image,
        clf,
        scene,
        "战斗已经结束，点击带绿勾的任务卷轴。不要点邮件或背包。",
    )
    if opened is not None:
        if "claim" in task.recipe.steps:
            task.step_index = task.recipe.steps.index("claim")
            task.step_armed = False
        return opened
    return _wait(
        task,
        clf,
        scene,
        "等待战斗",
        "战斗还没结束，也还没看到胜利或绿勾卷轴。先等下一帧，不点「扫荡」。",
        status="waiting_battle" if scene is Scene.BATTLE else "skip_unknown",
    )


def step_claim(task, image, clf):
    task.phase = Phase.CLAIM
    scene = clf.scene
    log_id = task.recipe.log_template
    opened = verbs.open_quest_scroll(
        task,
        image,
        clf,
        scene,
        "点击带绿勾的任务卷轴，打开任务日志。不要点邮件或背包。",
    )
    if opened is not None:
        return opened
    if scene is Scene.QUEST_LOG:
        if _awaiting(task, log_id) or log_id not in task.by_id:
            return _halt(
                task,
                clf,
                scene,
                "日志标题裁切还没有",
                f"「{task.recipe.name}」的日志标题裁切还没有。"
                "不会点绿色「完成」印章，也不会点别的委托。",
            )
        opened_row = task._plan_quest_log(image, clf)
        return opened_row
    if scene is Scene.QUEST_DETAIL:
        return task._plan_quest_detail(image, clf)
    if scene is Scene.LOOT_REWARD:
        return task._plan_loot(image, clf)
    return _wait(
        task,
        clf,
        scene,
        "等待领取",
        f"还没看到「{task.recipe.name}」的绿勾卷轴或任务日志。先等下一帧，不点印章。",
    )


_HANDLERS = {
    "accept_board": step_accept_board,
    "leave_association": step_leave_association,
    "reenter_association": step_reenter_association,
    "talk_dashu": step_talk_dashu,
    "talk_youth": step_talk_youth,
    "talk_on_stage": step_talk_on_stage,
    "talk_task_npc": step_talk_task_npc,
    "city_talk": step_city_talk,
    "skip_story": step_skip_story,
    "explore": step_explore,
    "fight_stage": step_fight_stage,
    "enter_3_20": step_enter_3_20,
    "return_3_20": step_return_3_20,
    "fight_3_23_2": step_fight_3_23_2,
    "fight_7_5_1": step_fight_7_5_1,
    "fight_8_b4_basic": step_fight_8_b4_basic,
    "fight_9_7_deep": step_fight_9_7_deep,
    "battle": step_battle,
    "claim": step_claim,
}
