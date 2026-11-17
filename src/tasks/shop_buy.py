"""金币商店购买日常：在任意一座城进「商店」，把目标商品买空。

所有地区都是同一家商店，不必回到指定城市。进店后点右下「金币」，
在清单里拖动寻找目标，找到后只点同一行右侧的「购买」。
确认弹窗里的商品名对得上才点「是」，对不上就点「否」。
随后在「获得物品」点触摸继续，直到该行可购数量变为 0
（0/n，不一定是 0/2；有的商品只有 1 份，买空就是 0/1）
或「购买」按钮变灰。不要点「购买全部」「兑换」「时装」「氪金」。
清单翻到底还没有的商品就跳过并说明。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from src.tasks.base import PlannedAction, StepResult, TaskBase
from src.tasks import verbs
from src.vision.classify import Classification, classify_scene
from src.vision.match import find_template, match_template
from src.vision.templates import load_templates, templates_by_id
from src.vision.types import Box, Match, Scene

logger = logging.getLogger("myrzx.task.shop_buy")

SHOP_SWIPE_MAX = 12
_LIST_REGION = (40, 680, 1040, 1620)
_ROW_DY = 90
_SWIPE_END_DIFF = 6.0

# 大地图上可点进的城市（不要点「阿格莱恩」「克里斯汀」这两块区名）。
_WORLD_CITIES = (
    "world_bei_seram",
    "world_lilitos",
    "world_lilitos_full",
    "world_lianhu",
    "world_langren",
    "world_litrile",
    "world_nan_seram",
)


@dataclass(frozen=True)
class ShopItem:
    item_id: str
    name: str
    icon_id: str
    name_id: str = ""
    confirm_id: str = ""


SHOP_ITEMS: tuple[ShopItem, ...] = (
    ShopItem(
        item_id="juice",
        name="可疑的果汁",
        icon_id="shop_item_juice",
        name_id="shop_name_juice",
        confirm_id="shop_confirm_juice",
    ),
    ShopItem(
        item_id="magic_iron",
        name="魔铁矿",
        icon_id="shop_item_magic_iron",
        name_id="",
        confirm_id="",
    ),
)


@dataclass
class ShopBuyTask(TaskBase):
    """在任意一座城打开商店，把目标商品买空。"""

    name = "shop_buy"

    def __init__(self) -> None:
        super().__init__()
        self.specs = load_templates()
        self.by_id = templates_by_id(self.specs)
        self.ocr = None
        self._match_cache: dict = {}
        self.pending_confirm: ShopItem | None = None
        self.results: dict[str, str] = {item.item_id: "pending" for item in SHOP_ITEMS}
        self.bought_counts: dict[str, int] = {item.item_id: 0 for item in SHOP_ITEMS}
        self.swipes = 0
        self._last_list: np.ndarray | None = None
        self._leaving = False
        self._match_cache = {}

    def plan(self, image_bgr: np.ndarray) -> StepResult:
        self._match_cache = {}
        clf = classify_scene(image_bgr, self.specs, ocr=self.ocr)
        for match in clf.matches:
            self._match_cache.setdefault(match.template_id, match)
        self.log.info("识别结果: %s", clf.brief())

        if self._leaving and not self._in_shop(image_bgr) and not self._in_confirm(image_bgr):
            message = self._done_message()
            return StepResult(
                scene=clf.scene,
                reason=clf.reason,
                matches=list(clf.matches),
                action=None,
                status="done",
                message=message,
            )

        loot = self._require(image_bgr, "loot_title")
        if clf.scene is Scene.LOOT_REWARD or loot is not None:
            if self.pending_confirm is not None:
                self.bought_counts[self.pending_confirm.item_id] += 1
                self.pending_confirm = None
            return verbs.dismiss_loot(
                self,
                image_bgr,
                clf,
                finishes_quest=False,
                message="关掉商店购买后的「获得物品」，继续把这件商品买空。",
            )

        if self._in_confirm(image_bgr):
            return self._plan_confirm(image_bgr, clf)

        if self._in_gold_shop(image_bgr):
            return self._plan_gold_list(image_bgr, clf)

        if self._in_shop(image_bgr):
            tab = self._require(image_bgr, "shop_tab_gold")
            if tab is not None:
                return self._click_result(
                    clf.scene,
                    clf,
                    self._with(clf, tab),
                    tab,
                    "已经进了商店，但还不是「金币商店」。点右下「金币」。不要点「兑换」「时装」「氪金」。",
                )
            return self._halt(
                clf,
                "在商店里，但没有认到「金币商店」标题，也没有右下「金币」页签。"
                "不会改点「兑换」「时装」「氪金」或「购买全部」。",
            )

        shop = self._require(image_bgr, "city_shop")
        if shop is not None:
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, shop),
                shop,
                "已经在城里，点「商店」。所有地区都是同一家商店。",
            )

        return self._plan_recover(image_bgr, clf)

    def _in_confirm(self, image: np.ndarray) -> bool:
        return any(
            self._require(image, tid) is not None
            for tid in ("shop_confirm_title", "shop_confirm_prompt", "shop_yes")
        )

    def _in_gold_shop(self, image: np.ndarray) -> bool:
        return self._require(image, "shop_gold_title") is not None

    def _in_shop(self, image: np.ndarray) -> bool:
        return self._require(image, "shop_leave") is not None or self._in_gold_shop(image)

    def _plan_confirm(self, image: np.ndarray, clf: Classification) -> StepResult:
        yes = self._require(image, "shop_yes")
        no = self._require(image, "shop_no")
        pending = self.pending_confirm
        named_ok = False
        if pending is not None and pending.confirm_id:
            named_ok = self._require(image, pending.confirm_id) is not None
        elif pending is not None and not pending.confirm_id:
            # 还没有这件商品的确认文案模板（例如走查当天没见到魔铁矿）。
            # 只在刚刚点过该行「购买」时才点「是」；若弹窗里出现别的已知商品名就点「否」。
            other_named = False
            for item in SHOP_ITEMS:
                if item.confirm_id and self._require(image, item.confirm_id) is not None:
                    other_named = True
                    break
            named_ok = not other_named

        if pending is not None and named_ok and yes is not None:
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, yes),
                yes,
                f"确认弹窗里是「{pending.name}」，点「是」。",
            )

        if no is not None:
            why = (
                "确认弹窗和要点的商品对不上，点「否」。"
                if pending is not None
                else "弹出了购买确认，但不是刚才点的那一行，点「否」。"
            )
            self.pending_confirm = None
            return self._click_result(clf.scene, clf, self._with(clf, no), no, why)

        return self._halt(clf, "看到购买确认，但没有「是」也没有「否」。先停下来。")

    def _plan_gold_list(self, image: np.ndarray, clf: Classification) -> StepResult:
        if self._leaving:
            return self._leave_shop(image, clf)

        if all(status != "pending" for status in self.results.values()):
            return self._leave_shop(image, clf)

        for item in SHOP_ITEMS:
            if self.results[item.item_id] != "pending":
                continue
            loc = self._find_item(image, item)
            if loc is None:
                continue
            buy = self._row_button(image, loc, enabled=True)
            disabled = self._row_button(image, loc, enabled=False)
            if self._is_sold_out(buy, disabled):
                self.results[item.item_id] = "bought_out"
                self.log.info("「%s」已买空（可购数量为 0 或「购买」变灰）。", item.name)
                continue
            if buy is None:
                continue
            self.pending_confirm = item
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, loc, buy),
                buy,
                f"找到「{item.name}」，点同一行的「购买」。不会点「购买全部」。",
            )

        if all(status != "pending" for status in self.results.values()):
            return self._leave_shop(image, clf)

        if self._list_ended(image):
            for item in SHOP_ITEMS:
                if self.results[item.item_id] == "pending":
                    self.results[item.item_id] = "missing"
                    self.log.info("金币清单翻完，没有「%s」，跳过。", item.name)
            return self._leave_shop(image, clf)

        if self.swipes >= SHOP_SWIPE_MAX:
            for item in SHOP_ITEMS:
                if self.results[item.item_id] == "pending":
                    self.results[item.item_id] = "missing"
            return self._leave_shop(image, clf)

        self.swipes += 1
        height, width = image.shape[:2]
        action = PlannedAction(
            kind="swipe",
            label="向上滑动商店清单",
            x=width // 2,
            y=int(height * 0.72),
            x2=width // 2,
            y2=int(height * 0.42),
            message=(
                f"当前画面上还没有未买完的目标商品，向上拖动清单（第 {self.swipes}/{SHOP_SWIPE_MAX} 次）。"
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

    def _is_sold_out(self, buy: Match | None, disabled: Match | None) -> bool:
        """买空：这一行「购买」变灰，或找不到可点的「购买」。

        不把可购数量写死成 0/2；只有 1 份时买空就是 0/1。
        """
        if disabled is None:
            return False
        if buy is None:
            return True
        return disabled.score >= buy.score - 0.02

    def _find_item(self, image: np.ndarray, item: ShopItem) -> Match | None:
        found: list[Match] = []
        if item.name_id:
            name = self._require(image, item.name_id)
            if name is not None:
                found.append(name)
        icon = self._require(image, item.icon_id)
        if icon is not None:
            found.append(icon)
        if not found:
            return None
        return max(found, key=lambda m: m.score)

    def _row_button(self, image: np.ndarray, loc: Match, *, enabled: bool) -> Match | None:
        tid = "shop_buy" if enabled else "shop_buy_disabled"
        buttons = self._find_all(image, tid, max_results=8)
        same_row: list[Match] = []
        loc_cy = loc.box.center[1]
        loc_right = loc.box.x2
        for btn in buttons:
            cx, cy = btn.box.center
            if abs(cy - loc_cy) <= _ROW_DY and cx > loc_right:
                same_row.append(btn)
        if not same_row:
            return None
        return max(same_row, key=lambda m: m.score)

    def _list_ended(self, image: np.ndarray) -> bool:
        x1, y1, x2, y2 = _LIST_REGION
        h, w = image.shape[:2]
        x2, y2 = min(x2, w), min(y2, h)
        region = image[y1:y2, x1:x2]
        if region.size == 0:
            return False
        small = cv2.resize(region, (160, 220), interpolation=cv2.INTER_AREA)
        if self._last_list is None or self.swipes == 0:
            self._last_list = small
            return False
        diff = float(np.mean(np.abs(small.astype(np.int16) - self._last_list.astype(np.int16))))
        self._last_list = small
        self.log.info("商店清单变化量 %.2f（小于 %.1f 视为翻到底）", diff, _SWIPE_END_DIFF)
        return diff < _SWIPE_END_DIFF and self.swipes >= 1

    def _leave_shop(self, image: np.ndarray, clf: Classification) -> StepResult:
        self._leaving = True
        leave = self._require(image, "shop_leave")
        if leave is None:
            return self._halt(clf, "目标商品已经处理完，但没有找到商店左下角「离开」。")
        message = self._done_message()
        return self._click_result(
            clf.scene,
            clf,
            self._with(clf, leave),
            leave,
            message + "点左下「离开」回到城里。",
        )

    def _done_message(self) -> str:
        parts: list[str] = []
        for item in SHOP_ITEMS:
            status = self.results[item.item_id]
            n = self.bought_counts[item.item_id]
            if status == "bought_out":
                if n:
                    parts.append(f"「{item.name}」已买空（买了 {n} 份）")
                else:
                    parts.append(f"「{item.name}」已经是买空状态")
            elif status == "missing":
                parts.append(f"「{item.name}」今天金币清单里没有，已跳过")
            else:
                parts.append(f"「{item.name}」还没处理完")
        return "金币商店买完了：" + "；".join(parts) + "。"

    def _plan_recover(self, image: np.ndarray, clf: Classification) -> StepResult:
        bag_title = self._require(image, "ui_bag_title")
        bag_back = self._require(image, "ui_bag_back")
        if bag_title is not None and bag_back is not None:
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, bag_title, bag_back),
                bag_back,
                "先关掉背包，再去城里的「商店」。不要点格子里的物品。",
            )

        association_leave = self._require(image, "association_leave")
        if association_leave is not None:
            return verbs.leave_room(
                self,
                image,
                clf,
                clf.scene,
                "先离开协会，回到城里再进「商店」。",
            )

        stage_leave = self._require(image, "stage_leave")
        if stage_leave is not None:
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, stage_leave),
                stage_leave,
                "先点「离开」退出选关或类似页面，再回城里进「商店」。",
            )

        back = self._require(image, "stage_return")
        if back is not None:
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, back),
                back,
                "先点「回程」，回到城里再进「商店」。",
            )

        city_btns = []
        for tid in _WORLD_CITIES:
            match = self._require(image, tid)
            if match is not None:
                city_btns.append(match)
        world = self._require(image, "world_aglaen") or self._require(image, "world_crystia")
        if city_btns:
            target = max(city_btns, key=lambda m: m.score)
            return self._click_result(
                clf.scene,
                clf,
                self._with(clf, target),
                target,
                f"现在在大地图，点「{target.label}」进城。所有地区都是同一家商店。",
            )
        if world is not None:
            return self._halt(
                clf,
                "现在在大地图上，但画面里没有认出任何一座城。请把某一座城滑进画面后再跑 --live --shop。",
            )

        in_city = any(
            self._require(image, tid) is not None
            for tid in (
                "city_association",
                "city_world_map",
                "city_world_map_text",
                "city_world_map_text_alt",
                "city_explore",
                "city_explore_label",
            )
        )
        if in_city:
            return self._halt(
                clf,
                "已经在城里，但没有看到「商店」。不会在城里乱滑。请把「商店」露出来后再跑。",
            )

        return self._halt(
            clf,
            "还认不出当前页面，也不在商店或城里。请先停在任意一座城，能看见「商店」再跑 --live --shop。",
        )

    def _find_all(self, image: np.ndarray, template_id: str, max_results: int = 8) -> list[Match]:
        spec = self.by_id.get(template_id)
        if spec is None:
            return []
        threshold = spec.threshold
        scales = spec.scales
        raw = match_template(
            image,
            spec.image_bgr,
            threshold=threshold,
            scales=scales,
            max_results=max_results,
        )
        return [
            Match(
                template_id=spec.id,
                label=spec.label,
                scene=spec.scene,
                role=spec.role,
                box=box,
                score=score,
                scale=scale,
            )
            for box, score, scale in raw
        ]

    def _require(self, image, template_id: str):
        if template_id in self._match_cache:
            return self._match_cache[template_id]
        spec = self.by_id.get(template_id)
        if spec is None:
            self._match_cache[template_id] = None
            return None
        match = find_template(image, spec, ocr=self.ocr)
        self._match_cache[template_id] = match
        return match

    def _click_result(
        self,
        scene,
        clf,
        matches,
        match,
        click_message,
        *,
        delay_sec=None,
        status="continue",
    ):
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
            message=action.brief() if status != "done" else click_message,
        )

    def _halt(self, clf: Classification, message: str) -> StepResult:
        return StepResult(
            scene=clf.scene,
            reason=clf.reason,
            matches=list(clf.matches),
            action=PlannedAction(kind="halt", label="停止", message=message),
            status="halt_missing",
            message=message,
        )

    def _with(self, clf: Classification, *matches: Match | None) -> list[Match]:
        out = list(clf.matches)
        seen = {m.template_id for m in out}
        for match in matches:
            if match is not None and match.template_id not in seen:
                out.append(match)
                seen.add(match.template_id)
        return out
