"""图像读写与色彩约定：对内统一为 OpenCV BGR uint8。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def load_bgr(source: str | Path | Image.Image | np.ndarray) -> np.ndarray:
    """把路径、PIL 图或 ndarray 转成 BGR uint8（HxWx3）。"""
    if isinstance(source, (str, Path)):
        data = np.fromfile(str(source), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"无法读取图像: {source}")
        return _to_bgr(image)
    if isinstance(source, Image.Image):
        rgb = np.array(source.convert("RGB"), dtype=np.uint8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if isinstance(source, np.ndarray):
        return _to_bgr(source)
    raise TypeError(f"不支持的图像类型: {type(source)!r}")


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3:
        raise ValueError(f"意外的图像维度: {image.shape}")
    channels = image.shape[2]
    if channels == 3:
        return np.ascontiguousarray(image)
    if channels == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    raise ValueError(f"意外的通道数: {channels}")
