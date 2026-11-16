"""根据场景标记模板判断当前页面。"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence

import numpy as np

from src.vision.match import find_all_templates
from src.vision.ocr import OcrProvider
from src.vision.templates import TemplateSpec, load_templates
from src.vision.types import Match, Scene


# 更具体的页面 / 叠加层优先。任务详情或获得物品背后仍露出日志/列表标题，
# 分数接近时必须选更具体的一页。胜利结算时战斗 HUD 可能残留，故 VICTORY 高于 BATTLE。
_SCENE_PRIORITY = (
    Scene.LOOT_REWARD,
    Scene.VICTORY,
    Scene.STORY_DIALOG,
    Scene.QUEST_DETAIL,
    Scene.QUEST_LOG,
    Scene.BATTLE,
    Scene.STAGE_1_3,
    Scene.STAGE_MAP,
    Scene.COMMISSION_LIST,
    Scene.ASSOCIATION,
    Scene.CITY_LILITOS,
    Scene.WORLD_MAP,
)

# 最高分与次高分差距不超过该值时，按页面特异性打破平局。
_CLOSE_SCORE_GAP = 0.08


@dataclass
class Classification:
    scene: Scene
    reason: str
    matches: list[Match] = field(default_factory=list)
    best: Match | None = None

    def brief(self) -> str:
        if self.scene is Scene.UNKNOWN:
            return f"页面=UNKNOWN（{self.reason}）"
        extra = f"，依据 {self.best.brief()}" if self.best else ""
        return f"页面={self.scene.value}（{self.scene.zh_name}）{extra}；{self.reason}"


def classify_scene(
    image_bgr: np.ndarray,
    specs: Sequence[TemplateSpec] | None = None,
    *,
    threshold: float | None = None,
    ocr: OcrProvider | None = None,
) -> Classification:
    """识别已知页面之一。纯函数，可直接对 fixture 单测。"""
    specs = list(specs) if specs is not None else load_templates()
    markers = [s for s in specs if s.is_scene_marker]
    # 先扫更像页面标题/叠加层的标记；高置信命中后不再扫探索节点、进入等点击模板。
    primary_ids = {
        "world_aglaen",
        "world_lilitos",
        "world_lilitos_full",
        "city_association",
        "city_capital_subtitle",
        "association_commission",
        "commission_center_title",
        "quest_detail_title",
        "stage_map_sweet_cave",
        "stage_1_3_title",
        "skip_story",
        "battle_ap",
        "battle_victory",
        "quest_log_title",
        "loot_title",
    }
    primary = [s for s in markers if s.id in primary_ids]
    secondary = [s for s in markers if s.id not in primary_ids]
    matches = find_all_templates(image_bgr, primary or markers, threshold=threshold, ocr=ocr)
    if (not matches or max(m.score for m in matches) < 0.90) and secondary:
        extra = find_all_templates(image_bgr, secondary, threshold=threshold, ocr=ocr)
        # 合并去重
        by_id = {m.template_id: m for m in matches}
        for item in extra:
            prev = by_id.get(item.template_id)
            if prev is None or item.score > prev.score:
                by_id[item.template_id] = item
        matches = sorted(by_id.values(), key=lambda m: m.score, reverse=True)
    if not matches:
        return Classification(
            scene=Scene.UNKNOWN,
            reason="没有任何场景模板超过匹配阈值",
            matches=[],
        )

    best_by_scene: dict[Scene, Match] = {}
    for match in matches:
        if match.scene is None:
            continue
        current = best_by_scene.get(match.scene)
        if current is None or match.score > current.score:
            best_by_scene[match.scene] = match

    if not best_by_scene:
        return Classification(
            scene=Scene.UNKNOWN,
            reason="匹配到模板但没有关联场景",
            matches=matches,
        )

    max_score = max(item.score for item in best_by_scene.values())
    close = [
        scene
        for scene, match in best_by_scene.items()
        if max_score - match.score <= _CLOSE_SCORE_GAP
    ]

    def _prio(scene: Scene) -> int:
        try:
            return _SCENE_PRIORITY.index(scene)
        except ValueError:
            return 99

    scene = min(close, key=_prio)
    best = best_by_scene[scene]
    others = [
        f"{s.value}:{best_by_scene[s].score:.3f}"
        for s in best_by_scene
        if s is not scene
    ]
    reason = f"最高分场景标记为「{best.label}」score={best.score:.3f}"
    if len(close) > 1:
        close_desc = ", ".join(
            f"{s.value}:{best_by_scene[s].score:.3f}" for s in close if s is not scene
        )
        reason += f"；与最高分相差不超过 {_CLOSE_SCORE_GAP} 的场景按特异性优先选 {scene.value}（近并列：{close_desc}）"
    if others:
        reason += "；其他过阈场景 " + ", ".join(others)
    return Classification(scene=scene, reason=reason, matches=matches, best=best)
