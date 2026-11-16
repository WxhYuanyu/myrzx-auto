"""多尺度模板匹配。纯函数：图像 + 模板 → 框与分数。"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from src import config
from src.vision.ocr import OcrProvider, merge_matches
from src.vision.templates import TemplateSpec
from src.vision.types import Box, Match

# 同一张图会被 classify / plan 反复匹配，缓存灰度图和缩小图。
_IMAGE_CACHE: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray | None, int]] = {}
_CACHE_CAP = 8


def match_template(
    image_bgr: np.ndarray,
    template_bgr: np.ndarray,
    *,
    threshold: float | None = None,
    scales: Sequence[float] | None = None,
    max_results: int = 1,
) -> list[tuple[Box, float, float]]:
    """在 image 中用多尺度模板匹配。

    返回 (box, score, scale) 列表，按分数降序。
    不依赖 Windows，可直接对 fixture PNG 单测。
    """
    threshold = config.MATCH_THRESHOLD if threshold is None else threshold
    use_default_scales = scales is None
    requested = tuple(config.TEMPLATE_SCALES if scales is None else scales)

    image_gray = _as_gray(image_bgr)
    template_gray = _as_gray(template_bgr)
    img_h, img_w = image_gray.shape[:2]
    tmpl_h, tmpl_w = template_gray.shape[:2]

    if use_default_scales:
        fast = tuple(dict.fromkeys(config.FAST_SCALES))
        # 1080x1920 实走图上，旧的小裁切模板只需要约 2.2 倍；
        # 不再扫 1.0 和 0.4–0.7，以免每张全屏图浪费大量匹配时间。
        if min(img_w, img_h) >= 900 and max(tmpl_w, tmpl_h) < 400:
            fast = tuple(s for s in fast if s >= 1.75)
            if not fast:
                fast = (2.20, 2.25, 2.00)
        rest = tuple(
            s
            for s in requested
            if s not in fast
            and not (
                min(img_w, img_h) >= 900 and max(tmpl_w, tmpl_h) < 400 and s < 1.75
            )
        )
        phases: tuple[tuple[float, ...], ...] = (fast, rest) if rest else (fast,)
    else:
        # 调用方指定尺度时仍把 1.0 提前，同源裁切可尽早命中。
        phases = (tuple(dict.fromkeys((1.0,) + requested)),)

    # 大图先在半分辨率上搜索，再回到原图精修，避免每档尺度都做 1080x1920 的彩色匹配。
    use_coarse = min(img_w, img_h) >= 900
    search_gray = image_gray
    shrink = 1.0
    if use_coarse:
        search_gray = _as_half(image_bgr)
        shrink = 2.0

    candidates: list[tuple[Box, float, float]] = []
    best_score = 0.0
    done = False
    for phase_index, phase in enumerate(phases):
        for scale in phase:
            tw = max(1, int(round(tmpl_w * scale / shrink)))
            th = max(1, int(round(tmpl_h * scale / shrink)))
            if tw < 8 or th < 8:
                continue
            if tw >= search_gray.shape[1] or th >= search_gray.shape[0]:
                continue
            interpolation = cv2.INTER_AREA if (scale / shrink) < 1.0 else cv2.INTER_CUBIC
            resized = cv2.resize(template_gray, (tw, th), interpolation=interpolation)
            result = cv2.matchTemplate(search_gray, resized, cv2.TM_CCOEFF_NORMED)
            if max_results == 1:
                _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
                if max_val >= (threshold - 0.12 if use_coarse else threshold):
                    if max_val > best_score:
                        best_score = float(max_val)
                    box, score = _refine_or_map(
                        image_gray,
                        template_gray,
                        scale,
                        int(max_loc[0]),
                        int(max_loc[1]),
                        tw,
                        th,
                        shrink,
                        float(max_val),
                    )
                    if score >= threshold:
                        candidates.append((box, score, float(scale)))
                        if score > best_score:
                            best_score = score
                        if score >= 0.98:
                            done = True
                            break
                elif max_val > best_score:
                    best_score = float(max_val)
                continue
            locations = np.where(
                result >= (threshold - 0.12 if use_coarse else threshold)
            )
            for y, x in zip(locations[0], locations[1], strict=False):
                box, score = _refine_or_map(
                    image_gray,
                    template_gray,
                    scale,
                    int(x),
                    int(y),
                    tw,
                    th,
                    shrink,
                    float(result[y, x]),
                )
                if score >= threshold:
                    candidates.append((box, score, float(scale)))
                    if score > best_score:
                        best_score = score
        if done:
            break
        # 默认尺度：快速档已经有足够好的命中，不再扫冷门尺度。
        if use_default_scales and phase_index == 0 and max_results == 1 and best_score >= 0.90:
            break

    candidates.sort(key=lambda item: item[1], reverse=True)
    if max_results == 1:
        return candidates[:1]
    return _nms(candidates, iou_threshold=0.4)[:max_results]


def find_template(
    image_bgr: np.ndarray,
    spec: TemplateSpec,
    *,
    threshold: float | None = None,
    scales: Sequence[float] | None = None,
    ocr: OcrProvider | None = None,
) -> Match | None:
    """查找单个已命名模板，可选地与 OCR 结果合并后取最高分。"""
    eff_threshold = threshold if threshold is not None else spec.threshold
    eff_scales = scales if scales is not None else spec.scales
    raw = match_template(
        image_bgr,
        spec.image_bgr,
        threshold=eff_threshold,
        scales=eff_scales,
        max_results=1,
    )
    template_matches = [_to_match(spec, box, score, scale) for box, score, scale in raw]
    ocr_matches: list[Match] = []
    if ocr is not None:
        ocr_matches = ocr.find_text(image_bgr, spec.label)
    merged = merge_matches(template_matches, ocr_matches)
    return merged[0] if merged else None


def find_all_templates(
    image_bgr: np.ndarray,
    specs: Sequence[TemplateSpec],
    *,
    threshold: float | None = None,
    scales: Sequence[float] | None = None,
    ocr: OcrProvider | None = None,
) -> list[Match]:
    """对一组模板逐个取最佳匹配（未过阈值的不返回）。"""
    found: list[Match] = []
    for spec in specs:
        match = find_template(
            image_bgr,
            spec,
            threshold=threshold,
            scales=scales,
            ocr=ocr,
        )
        if match is not None:
            found.append(match)
    found.sort(key=lambda m: m.score, reverse=True)
    return found


def _refine_or_map(
    image_gray: np.ndarray,
    template_gray: np.ndarray,
    scale: float,
    coarse_x: int,
    coarse_y: int,
    coarse_w: int,
    coarse_h: int,
    shrink: float,
    coarse_score: float,
) -> tuple[Box, float]:
    """把半分辨率命中映射回原图，并在邻域精修。"""
    full_w = max(1, int(round(template_gray.shape[1] * scale)))
    full_h = max(1, int(round(template_gray.shape[0] * scale)))
    img_h, img_w = image_gray.shape[:2]
    if shrink <= 1.0:
        return Box(coarse_x, coarse_y, coarse_w, coarse_h), coarse_score
    if full_w >= img_w or full_h >= img_h:
        x = int(round(coarse_x * shrink))
        y = int(round(coarse_y * shrink))
        return Box(x, y, full_w, full_h), coarse_score

    x0 = int(round(coarse_x * shrink))
    y0 = int(round(coarse_y * shrink))
    margin = max(8, int(round(4 * shrink)))
    rx1 = max(0, x0 - margin)
    ry1 = max(0, y0 - margin)
    rx2 = min(img_w, x0 + full_w + margin)
    ry2 = min(img_h, y0 + full_h + margin)
    if rx2 - rx1 <= full_w or ry2 - ry1 <= full_h:
        return Box(x0, y0, full_w, full_h), 0.0
    roi = image_gray[ry1:ry2, rx1:rx2]
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(template_gray, (full_w, full_h), interpolation=interpolation)
    result = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    box = Box(rx1 + int(max_loc[0]), ry1 + int(max_loc[1]), full_w, full_h)
    return box, float(max_val)


def _as_gray(image: np.ndarray) -> np.ndarray:
    color, gray, _half, _ = _cached_views(image)
    return gray if gray is not None else color


def _as_half(image: np.ndarray) -> np.ndarray:
    _color, _gray, half, _ = _cached_views(image)
    assert half is not None
    return half


def _cached_views(
    image: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, int]:
    key = id(image)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None and cached[0] is image:
        return cached
    gray = _to_gray(image)
    half = None
    if min(gray.shape[:2]) >= 900:
        half = cv2.resize(
            gray,
            (gray.shape[1] // 2, gray.shape[0] // 2),
            interpolation=cv2.INTER_AREA,
        )
    entry = (image, gray, half, key)
    if len(_IMAGE_CACHE) >= _CACHE_CAP:
        _IMAGE_CACHE.clear()
    _IMAGE_CACHE[key] = entry
    return entry


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _to_match(spec: TemplateSpec, box: Box, score: float, scale: float) -> Match:
    return Match(
        template_id=spec.id,
        label=spec.label,
        scene=spec.scene,
        role=spec.role,
        box=box,
        score=score,
        scale=scale,
    )


def _ensure_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _nms(
    candidates: list[tuple[Box, float, float]],
    iou_threshold: float,
) -> list[tuple[Box, float, float]]:
    kept: list[tuple[Box, float, float]] = []
    for cand in candidates:
        if all(cand[0].iou(existing[0]) < iou_threshold for existing in kept):
            kept.append(cand)
    return kept
