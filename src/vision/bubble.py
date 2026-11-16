"""在 1-3 关卡页上查找任务气泡，并把它对应到最近的探索节点。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from src.vision.match import find_template
from src.vision.ocr import OcrProvider
from src.vision.templates import TemplateSpec
from src.vision.types import Match

NODE_LABELS = ("初步探索", "深入探索", "完全探索")


@dataclass(frozen=True)
class BubbleSelection:
    bubble: Match
    node: Match | None

    @property
    def node_label(self) -> str | None:
        return self.node.label if self.node is not None else None

    def brief(self) -> str:
        if self.node is None:
            return f"找到气泡但未能对应到探索节点（{self.bubble.brief()}）"
        return f"气泡对应「{self.node.label}」（气泡 {self.bubble.brief()}；节点 {self.node.brief()}）"


def find_explore_nodes(
    image_bgr: np.ndarray,
    specs: Sequence[TemplateSpec],
    *,
    ocr: OcrProvider | None = None,
    threshold: float | None = None,
) -> list[Match]:
    """在画面上查找初步 / 深入 / 完全 三个节点标签。同名模板取最高分。"""
    best_by_label: dict[str, Match] = {}
    for spec in specs:
        if spec.label not in NODE_LABELS:
            continue
        match = find_template(image_bgr, spec, threshold=threshold, ocr=ocr)
        if match is None:
            continue
        current = best_by_label.get(spec.label)
        if current is None or match.score > current.score:
            best_by_label[spec.label] = match
    return [best_by_label[label] for label in NODE_LABELS if label in best_by_label]


def find_quest_bubble(
    image_bgr: np.ndarray,
    specs: Sequence[TemplateSpec],
    *,
    ocr: OcrProvider | None = None,
    threshold: float | None = None,
) -> Match | None:
    """只匹配任务气泡模板本身，不要把地图装饰（橙色箭头）当成气泡。"""
    best: Match | None = None
    for spec in specs:
        if spec.role != "quest_bubble" and spec.id != "quest_bubble":
            continue
        match = find_template(image_bgr, spec, threshold=threshold, ocr=ocr)
        if match is not None and (best is None or match.score > best.score):
            best = match
    return best


def associate_bubble_with_node(bubble: Match, nodes: Sequence[Match]) -> Match | None:
    """气泡通常在应进入的节点上方或略偏一侧，选水平距离近且位于节点之上的那个。"""
    if not nodes:
        return None
    bx, by = bubble.box.center

    def _key(node: Match) -> tuple[float, float, float]:
        nx, ny = node.box.center
        above = by <= ny + node.box.h * 0.25
        dx = abs(bx - nx)
        dy = ny - by
        penalty = 0.0 if above else 10_000.0
        return (penalty, dx, abs(dy))

    return min(nodes, key=_key)


def select_node_by_bubble(
    image_bgr: np.ndarray,
    specs: Sequence[TemplateSpec],
    *,
    ocr: OcrProvider | None = None,
    threshold: float | None = None,
) -> BubbleSelection | None:
    bubble = find_quest_bubble(image_bgr, specs, ocr=ocr, threshold=threshold)
    if bubble is None:
        return None
    nodes = find_explore_nodes(image_bgr, specs, ocr=ocr, threshold=threshold)
    node = associate_bubble_with_node(bubble, nodes)
    return BubbleSelection(bubble=bubble, node=node)
