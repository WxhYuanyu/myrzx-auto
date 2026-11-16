"""视觉模块：模板匹配、场景分类。函数均为纯函数（图入，框/标签出）。"""

from src.vision.bubble import (
    BubbleSelection,
    associate_bubble_with_node,
    find_explore_nodes,
    find_quest_bubble,
    select_node_by_bubble,
)
from src.vision.classify import classify_scene
from src.vision.match import find_template, match_template
from src.vision.ocr import NullOcrProvider, OcrProvider
from src.vision.templates import TemplateSpec, load_manifest, load_templates
from src.vision.types import Box, Match, Scene

__all__ = [
    "Box",
    "BubbleSelection",
    "Match",
    "Scene",
    "TemplateSpec",
    "OcrProvider",
    "NullOcrProvider",
    "associate_bubble_with_node",
    "classify_scene",
    "find_explore_nodes",
    "find_quest_bubble",
    "find_template",
    "match_template",
    "select_node_by_bubble",
    "load_manifest",
    "load_templates",
]
