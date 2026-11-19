"""商店和背包共用的「滚到列表底部」。

只比较调用方给出的物品区域，不看整帧，免得金币数字、按钮和背景动画
被当成清单还在动。滚动过程用缩小后的灰度图；看起来停住之后，再用
更细的格子签名，以及调用方提供的图标 / 名称 / 位置。连续两次对比
都没有变化，才认定到底。识别失败或区域异常不算到底。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

# 1080×1920 上的物品区。调用时按当前画面等比缩放到截图里。
SHOP_LIST_REGION = (40, 680, 1040, 1620)
BAG_ITEM_REGION = (40, 460, 1040, 1760)

# 缩小灰度图的平均绝对差。大于它说明物品区还在动。
_CHEAP_DIFF = 6.0

Precise = Callable[[np.ndarray, tuple[int, int, int, int]], object]


@dataclass
class ListScroll:
    """一次清单的滚动状态。商店、背包各持有一份。"""

    region: tuple[int, int, int, int]
    max_swipes: int
    swipes: int = 0
    unchanged: int = 0
    reached_bottom: bool = False
    hit_cap: bool = False
    _prev_cheap: np.ndarray | None = field(default=None, repr=False)
    _prev_precise: object = field(default=None, repr=False)

    def observe(self, image: np.ndarray, precise: Precise) -> str:
        """看当前这一帧。

        返回：
        - ``swipe``：还要再向下滑一截
        - ``inconclusive``：这一帧不能用来判断，也要再滑，但不能当成到底
        - ``bottom``：连续两次对比都没变化
        - ``cap``：碰到安全次数，不是确认到底
        """
        if self.reached_bottom:
            return "bottom"
        if self.hit_cap:
            return "cap"

        box = self.box_on(image)
        if box is None:
            return self._not_bottom()
        region = image[box[1] : box[3], box[0] : box[2]]
        cheap = _cheap(region)
        if cheap is None:
            return self._not_bottom()

        if self._prev_cheap is None:
            self._prev_cheap = cheap
            return self._ask_swipe()

        moved = _moved(self._prev_cheap, cheap)
        self._prev_cheap = cheap
        if moved:
            self.unchanged = 0
            self._prev_precise = None
            return self._ask_swipe()

        try:
            signature = precise(image, box)
        except Exception:
            signature = None
        if signature is None:
            return self._not_bottom()
        # 第一次细看只记下基准，还不算「没变化」。
        # 之后要连续两次细看都一样，才认定到底。
        if self._prev_precise is None or signature != self._prev_precise:
            self._prev_precise = signature
            self.unchanged = 0
            return self._ask_swipe()
        self.unchanged += 1
        if self.unchanged >= 2:
            self.reached_bottom = True
            return "bottom"
        return self._ask_swipe()

    def box_on(self, image: np.ndarray) -> tuple[int, int, int, int] | None:
        height, width = image.shape[:2]
        if height < 32 or width < 32:
            return None
        x1, y1, x2, y2 = self.region
        sx = width / 1080.0
        sy = height / 1920.0
        left = max(0, min(width - 1, int(round(x1 * sx))))
        top = max(0, min(height - 1, int(round(y1 * sy))))
        right = max(0, min(width, int(round(x2 * sx))))
        bottom = max(0, min(height, int(round(y2 * sy))))
        if right - left < 16 or bottom - top < 16:
            return None
        return (left, top, right, bottom)

    def _ask_swipe(self) -> str:
        if self.swipes >= self.max_swipes:
            self.hit_cap = True
            return "cap"
        self.swipes += 1
        return "swipe"

    def _not_bottom(self) -> str:
        """区域读不出来。清掉「没变化」的计数，绝不当成到底。"""
        self.unchanged = 0
        self._prev_precise = None
        if self.swipes >= self.max_swipes:
            self.hit_cap = True
            return "cap"
        self.swipes += 1
        return "inconclusive"


def cell_signature(region: np.ndarray, *, rows: int = 6, cols: int = 4) -> tuple[int, ...] | None:
    """把物品区切成格子，记下每格亮度。空白或几乎纯色的区域返回 None。"""
    if region.size == 0:
        return None
    gray = _gray(region)
    if float(gray.std()) < 2.0:
        return None
    height, width = gray.shape[:2]
    cells: list[int] = []
    for row in range(rows):
        y1 = row * height // rows
        y2 = (row + 1) * height // rows
        for col in range(cols):
            x1 = col * width // cols
            x2 = (col + 1) * width // cols
            patch = gray[y1:y2, x1:x2]
            if patch.size == 0:
                return None
            cells.append(int(patch.mean()) // 4)
    return tuple(cells)


def _cheap(region: np.ndarray) -> np.ndarray | None:
    gray = _gray(region)
    if gray.size == 0:
        return None
    return cv2.resize(gray, (32, 48), interpolation=cv2.INTER_AREA)


def _moved(previous: np.ndarray, current: np.ndarray) -> bool:
    if previous.shape != current.shape:
        return True
    diff = float(np.mean(np.abs(previous.astype(np.int16) - current.astype(np.int16))))
    return diff >= _CHEAP_DIFF


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
