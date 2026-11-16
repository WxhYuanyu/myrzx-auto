"""OCR 可插拔接口。当前不捆绑重型 OCR 引擎，默认空实现。

识别中文标签时，可在此接入 PaddleOCR / Tesseract 等，作为模板匹配的
并列或主路径。视觉层的其余函数只依赖本协议，不直接 import 具体引擎。
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from src.vision.types import Match


class OcrProvider(Protocol):
    def find_text(self, image_bgr: np.ndarray, text: str) -> list[Match]:
        """在图中查找给定文案，返回与模板匹配相同结构的 Match 列表。"""
        ...


class NullOcrProvider:
    """占位实现：什么都不找。用于测试和尚未安装 OCR 的环境。"""

    def find_text(self, image_bgr: np.ndarray, text: str) -> list[Match]:
        return []


def merge_matches(
    template_matches: list[Match],
    ocr_matches: list[Match],
    iou_threshold: float = 0.5,
) -> list[Match]:
    """合并模板与 OCR 结果；高度重叠时保留分数更高者。"""
    merged: list[Match] = list(template_matches)
    for cand in ocr_matches:
        replaced = False
        for i, existing in enumerate(merged):
            if existing.box.iou(cand.box) >= iou_threshold:
                if cand.score > existing.score:
                    merged[i] = cand
                replaced = True
                break
        if not replaced:
            merged.append(cand)
    merged.sort(key=lambda m: m.score, reverse=True)
    return merged

