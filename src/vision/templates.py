"""加载 assets/templates 下的模板和 manifest。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src import config
from src.vision.types import Scene


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    file: str
    scene: Scene | None
    role: str
    label: str
    image_bgr: np.ndarray
    notes: str = ""
    threshold: float | None = None
    click_offset: tuple[int, int] = (0, 0)
    scales: tuple[float, ...] | None = None

    @property
    def is_click_target(self) -> bool:
        return self.role in {"click_target", "click_only", "leave_button"}

    @property
    def is_scene_marker(self) -> bool:
        # click_only / leave_button / status / quest_bubble 不定义场景
        return self.role in {"scene_marker", "click_target"}


def load_manifest(path: Path | None = None) -> dict:
    manifest_path = path or config.TEMPLATE_MANIFEST
    with manifest_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _scene_from(value: str | None) -> Scene | None:
    if not value:
        return None
    # 城里「探险」木牌和背包按钮在清单里标成通用 CITY。
    # 它们的 role 是 click_only，不参与页面判断；Scene 没有这一项。
    if value == "CITY":
        return None
    return Scene(value)


def load_templates(
    templates_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> list[TemplateSpec]:
    templates_dir = templates_dir or config.TEMPLATES_DIR
    manifest = load_manifest(manifest_path)
    specs: list[TemplateSpec] = []
    for entry in manifest["templates"]:
        file_path = templates_dir / entry["file"]
        if not file_path.is_file():
            raise FileNotFoundError(f"模板文件不存在: {file_path}")
        image = _read_bgr(file_path)
        offset = entry.get("click_offset") or [0, 0]
        scales = entry.get("scales")
        specs.append(
            TemplateSpec(
                id=entry["id"],
                file=entry["file"],
                scene=_scene_from(entry.get("scene")),
                role=entry.get("role", "scene_marker"),
                label=entry["label"],
                image_bgr=image,
                notes=entry.get("notes", ""),
                threshold=entry.get("threshold"),
                click_offset=(int(offset[0]), int(offset[1])),
                scales=tuple(float(s) for s in scales) if scales else None,
            )
        )
    return specs


def templates_by_id(specs: list[TemplateSpec] | None = None) -> dict[str, TemplateSpec]:
    specs = specs if specs is not None else load_templates()
    return {s.id: s for s in specs}


def _read_bgr(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法解码模板图像: {path}")
    return image
