from __future__ import annotations

import cv2
import numpy as np

import quality_engine


_base_analyze = quality_engine.analyze_exposure


def conservative_exposure(rgb):
    result = _base_analyze(rgb)
    cap = 0.045 if result["scene_tonality"] == "black_dominant" else 0.065
    result["shadow_lift"] = round(min(float(result["shadow_lift"]), cap), 4)
    result["lightroom_equivalent"]["Shadows"] = round(min(32.0, result["shadow_lift"] * 430), 0)
    result["lightroom_equivalent"]["Blacks"] = (
        -8.0 if result["scene_tonality"] == "black_dominant" and result["shadow_crushed_ratio"] < 0.01
        else round(min(12.0, result["shadow_lift"] * 150), 0)
    )
    return result


def _legacy_to_ellipse(item: dict) -> dict:
    if item.get("type"):
        return item
    radius = float(item.get("radius", 0.018))
    return {"type": "ellipse", "x": item["x"], "y": item["y"],
            "major": radius * 1.05, "minor": radius * 0.78, "angle": 0,
            "feather": 0.42}


def _ellipse_mask(item: dict, h: int, w: int):
    short = min(h, w)
    cx, cy = round(float(item["x"]) * w), round(float(item["y"]) * h)
    rx = max(3, round(float(item.get("major", 0.018)) * short))
    ry = max(2, round(float(item.get("minor", 0.012)) * short))
    feather = float(item.get("feather", 0.42))
    pad = max(6, round(min(rx, ry) * (0.6 + feather)))
    reach = max(rx, ry) + pad
    x1, y1, x2, y2 = max(0, cx-reach), max(0, cy-reach), min(w, cx+reach+1), min(h, cy+reach+1)
    mask = np.zeros((y2-y1, x2-x1), dtype=np.uint8)
    cv2.ellipse(mask, (cx-x1, cy-y1), (rx, ry), float(item.get("angle", 0)), 0, 360, 255, -1)
    sigma = max(0.8, min(rx, ry) * feather * 0.38)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return (x1, y1, x2, y2), mask.astype(np.float32)[:, :, None] / 255.0


def _polygon_mask(item: dict, h: int, w: int):
    points = np.asarray([[float(p["x"])*w, float(p["y"])*h] for p in item.get("points", [])], dtype=np.float32)
    if len(points) < 3:
        return None
    minxy = points.min(axis=0); maxxy = points.max(axis=0)
    feather = float(item.get("feather", 0.42))
    base = max(3.0, min(maxxy[0]-minxy[0], maxxy[1]-minxy[1]))
    pad = max(6, round(base * (0.20 + feather * 0.35)))
    x1, y1 = max(0, int(np.floor(minxy[0]))-pad), max(0, int(np.floor(minxy[1]))-pad)
    x2, y2 = min(w, int(np.ceil(maxxy[0]))+pad+1), min(h, int(np.ceil(maxxy[1]))+pad+1)
    local = np.round(points - np.array([x1, y1], dtype=np.float32)).astype(np.int32)
    mask = np.zeros((y2-y1, x2-x1), dtype=np.uint8)
    cv2.fillPoly(mask, [local], 255)
    sigma = max(0.8, base * feather * 0.10)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return (x1, y1, x2, y2), mask.astype(np.float32)[:, :, None] / 255.0


def enhance_adaptive_eyes(rgb: np.ndarray, annotations: list[dict], exposure_ev: float = 0.18,
                          saturation: float = 25.0) -> np.ndarray:
    out = rgb.copy(); h, w = out.shape[:2]
    for raw in annotations:
        item = _legacy_to_ellipse(raw)
        result = _polygon_mask(item, h, w) if item.get("type") == "polygon" else _ellipse_mask(item, h, w)
        if result is None:
            continue
        (x1, y1, x2, y2), alpha = result
        roi = out[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        local_ev = float(item.get("exposure_ev", exposure_ev))
        local_sat = float(item.get("saturation", saturation))
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + local_sat/100.0), 0, 255)
        boosted = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)
        boosted *= 2.0 ** local_ev
        out[y1:y2, x1:x2] = np.clip(boosted*alpha + roi.astype(np.float32)*(1-alpha), 0, 255).astype(np.uint8)
    return out


quality_engine.analyze_exposure = conservative_exposure
quality_engine.enhance_eyes = enhance_adaptive_eyes

import render_drafts

if __name__ == "__main__":
    raise SystemExit(render_drafts.main())
