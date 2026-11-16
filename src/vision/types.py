"""视觉结果的公共数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Scene(str, Enum):
    """当前能识别的页面。未知或需要下一张尚未收集的截图时用后两个值。"""

    WORLD_MAP = "WORLD_MAP"
    REGION_CRYSTIA = "REGION_CRYSTIA"
    CITY_LILITOS = "CITY_LILITOS"
    CITY_TURANDON = "CITY_TURANDON"
    ASSOCIATION = "ASSOCIATION"
    COMMISSION_LIST = "COMMISSION_LIST"
    QUEST_DETAIL = "QUEST_DETAIL"
    STAGE_MAP = "STAGE_MAP"
    STAGE_1_3 = "STAGE_1_3"
    STORY_DIALOG = "STORY_DIALOG"
    BATTLE = "BATTLE"
    VICTORY = "VICTORY"
    QUEST_LOG = "QUEST_LOG"
    LOOT_REWARD = "LOOT_REWARD"
    UNKNOWN = "UNKNOWN"
    NEED_NEXT_SCREEN = "NEED_NEXT_SCREEN"

    @property
    def zh_name(self) -> str:
        return {
            Scene.WORLD_MAP: "世界地图（阿格莱恩）",
            Scene.REGION_CRYSTIA: "克里斯汀（区域地图）",
            Scene.CITY_LILITOS: "王城莉莉托斯（城内节点）",
            Scene.CITY_TURANDON: "图兰顿沙漠（城内）",
            Scene.ASSOCIATION: "协会室内",
            Scene.COMMISSION_LIST: "协会委托中心",
            Scene.QUEST_DETAIL: "任务详情",
            Scene.STAGE_MAP: "关卡选择图（1-x）",
            Scene.STAGE_1_3: "莉莉托斯近郊 1-3",
            Scene.STORY_DIALOG: "剧情对话",
            Scene.BATTLE: "战斗中",
            Scene.VICTORY: "战斗胜利",
            Scene.QUEST_LOG: "任务日志",
            Scene.LOOT_REWARD: "获得物品",
            Scene.UNKNOWN: "未能识别的页面",
            Scene.NEED_NEXT_SCREEN: "需要下一张尚未收集的截图",
        }[self]


@dataclass(frozen=True)
class Box:
    """像素坐标系，原点在图像左上角，(x, y) 为左上角。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def as_xyxy(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x2, self.y2)

    def iou(self, other: "Box") -> float:
        ix1 = max(self.x, other.x)
        iy1 = max(self.y, other.y)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter = iw * ih
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union else 0.0


@dataclass(frozen=True)
class Match:
    template_id: str
    label: str
    scene: Scene | None
    role: str
    box: Box
    score: float
    scale: float

    def brief(self) -> str:
        x, y = self.box.center
        return (
            f"{self.label} id={self.template_id} "
            f"box=({self.box.x},{self.box.y},{self.box.w}x{self.box.h}) "
            f"center=({x},{y}) score={self.score:.3f} scale={self.scale:.2f}"
        )
