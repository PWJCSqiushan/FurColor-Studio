from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _luma(rgb01: np.ndarray) -> np.ndarray:
    return 0.2126 * rgb01[:, :, 0] + 0.7152 * rgb01[:, :, 1] + 0.0722 * rgb01[:, :, 2]


def _sample(rgb: np.ndarray, max_side: int = 900) -> np.ndarray:
    h, w = rgb.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        return cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return rgb


def _percentiles(y: np.ndarray) -> dict[str, float]:
    values = np.percentile(y, [1, 5, 25, 50, 75, 95, 99])
    return {f"p{p:02d}": round(float(v), 4) for p, v in zip((1, 5, 25, 50, 75, 95, 99), values)}


def estimate_neutral_white(rgb: np.ndarray) -> dict[str, Any]:
    small = _sample(rgb).astype(np.float32) / 255.0
    y = _luma(small)
    mx, mn = small.max(axis=2), small.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)

    # Bright, non-clipped and low-chroma surfaces are the safest available neutral references.
    base = (y >= 0.48) & (y <= 0.90) & (mx < 0.965) & (mn > 0.10)
    mask = base & (sat <= 0.105)
    if int(mask.sum()) < 350:
        mask = base & (sat <= 0.155)
    count = int(mask.sum())
    ratio = count / max(mask.size, 1)
    if count < 120:
        return {
            "found": False, "confidence": 0.0, "pixel_ratio": round(ratio, 6),
            "reason": "not_enough_nonclipped_neutral_pixels", "gains": [1.0, 1.0, 1.0],
        }

    pixels = small[mask]
    # Trim color-channel outliers so colored LEDs and specular points contribute less.
    med = np.median(pixels, axis=0)
    dist = np.linalg.norm(pixels - med, axis=1)
    keep = dist <= np.percentile(dist, 72)
    neutral = np.median(pixels[keep], axis=0)
    target = float(np.mean(neutral))
    gains = np.clip(target / np.maximum(neutral, 1e-4), 0.78, 1.28)
    gains /= gains[1]  # express correction relative to green
    cast = float((neutral.max() - neutral.min()) / max(target, 1e-4))
    spread = float(np.mean(np.std(pixels[keep], axis=0)))
    confidence = np.clip(
        0.18 + min(ratio / 0.025, 1.0) * 0.48 + min(cast / 0.16, 1.0) * 0.22
        - max(spread - 0.12, 0.0), 0.0, 0.92
    )
    # Do not force a correction when the candidate is already neutral.
    if cast < 0.018:
        confidence *= 0.45
    return {
        "found": True, "confidence": round(float(confidence), 4),
        "pixel_ratio": round(ratio, 6), "neutral_rgb": [round(float(x), 4) for x in neutral],
        "gains": [round(float(x), 4) for x in gains], "cast_strength": round(cast, 4),
    }


def apply_white_balance(rgb: np.ndarray, estimate: dict[str, Any], strength: float = 1.0) -> np.ndarray:
    if not estimate.get("found"):
        return rgb.copy()
    confidence = float(estimate.get("confidence", 0.0))
    effective = np.clip(confidence * strength, 0.0, 0.88)
    gains = np.asarray(estimate["gains"], dtype=np.float32)
    gains = 1.0 + (gains - 1.0) * effective
    out = rgb.astype(np.float32) / 255.0
    out *= gains[None, None, :]
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def analyze_exposure(rgb: np.ndarray) -> dict[str, Any]:
    small = _sample(rgb).astype(np.float32) / 255.0
    y = _luma(small)
    mx, mn = small.max(axis=2), small.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    q = _percentiles(y)
    clipped = float((mx >= 0.992).mean())
    near_clip = float((y >= 0.965).mean())
    crushed = float((y <= 0.012).mean())
    deep_shadow = float((y <= 0.055).mean())
    white_area = float(((y >= 0.62) & (sat <= 0.16) & (mx < 0.99)).mean())
    black_area = float((y <= 0.17).mean())

    if white_area >= 0.18 and white_area > black_area * 0.75:
        scene = "white_dominant"
        target_p95 = 0.91
    elif black_area >= 0.35 and black_area > white_area * 2.0:
        scene = "black_dominant"
        target_p95 = 0.82
    else:
        scene = "mixed"
        target_p95 = 0.87

    ev = math.log2(target_p95 / max(q["p95"], 0.06))
    # Existing clipped highlights take priority over lifting the whole image.
    if clipped > 0.002 or near_clip > 0.012:
        ev -= min(0.48, clipped * 8.0 + near_clip * 2.2)
    ev = float(np.clip(ev, -0.72, 0.65))

    highlight = float(np.clip((q["p99"] - 0.90) * 2.8 + near_clip * 4.5 + max(ev, 0) * 0.18, 0, 0.72))
    # Recover only enough shadow separation to retain fur detail. Black-dominant scenes stay dark.
    shadow_need = max(0.0, 0.075 - q["p05"])
    shadow_lift = float(np.clip(shadow_need * (0.78 if scene == "black_dominant" else 1.35) + crushed * 0.35, 0, 0.105))
    risk = "high" if clipped > 0.012 or crushed > 0.05 or q["p99"] > 0.985 else (
        "review" if clipped > 0.0025 or deep_shadow > 0.32 or abs(ev) > 0.42 else "normal"
    )
    return {
        **q, "scene_tonality": scene,
        "highlight_clipped_ratio": round(clipped, 6), "near_clip_ratio": round(near_clip, 6),
        "shadow_crushed_ratio": round(crushed, 6), "deep_shadow_ratio": round(deep_shadow, 6),
        "neutral_white_area_ratio": round(white_area, 6), "black_area_ratio": round(black_area, 6),
        "recommended_ev": round(ev, 4), "highlight_compression": round(highlight, 4),
        "shadow_lift": round(shadow_lift, 4), "exposure_risk": risk,
        "lightroom_equivalent": {
            "Exposure": round(ev, 2), "Highlights": round(-100 * highlight, 0),
            "Shadows": round(min(55.0, shadow_lift * 430), 0),
            "Whites": round(-min(35.0, clipped * 900 + near_clip * 120), 0),
            "Blacks": round(-8 if scene == "black_dominant" and crushed < 0.01 else min(18.0, shadow_lift * 150), 0),
        },
    }


def apply_exposure_tone(rgb: np.ndarray, analysis: dict[str, Any]) -> np.ndarray:
    arr = rgb.astype(np.float32) / 255.0
    old_y = _luma(arr)
    y = old_y * (2.0 ** float(analysis["recommended_ev"]))
    compression = float(analysis["highlight_compression"])
    if compression > 0:
        shoulder = 0.68
        above = np.maximum(y - shoulder, 0.0)
        # Smooth shoulder; it preserves relative texture better than hard clipping.
        compressed = shoulder + above / (1.0 + compression * 3.2 * above)
        y = np.where(y > shoulder, compressed, y)
    lift = float(analysis["shadow_lift"])
    if lift > 0:
        y += lift * np.square(np.clip(1.0 - y / 0.42, 0.0, 1.0))
    y = np.clip(y, 0.0, 1.0)
    scale = y / np.maximum(old_y, 0.012)
    # Luminance scaling can over-saturate near the gamut boundary; cap channel scale safely.
    out = arr * np.clip(scale[:, :, None], 0.45, 3.2)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def enhance_eyes(rgb: np.ndarray, points: list[dict[str, float]], exposure_ev: float = 0.18,
                 saturation: float = 25.0) -> np.ndarray:
    out = rgb.copy()
    h, w = out.shape[:2]
    short = min(h, w)
    for point in points:
        cx, cy = int(point["x"] * w), int(point["y"] * h)
        radius = max(4, int(point.get("radius", 0.018) * short))
        x1, y1, x2, y2 = max(0, cx-radius*2), max(0, cy-radius*2), min(w, cx+radius*2+1), min(h, cy+radius*2+1)
        roi = out[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        yy, xx = np.mgrid[y1:y2, x1:x2]
        d2 = ((xx-cx)/(radius*1.05))**2 + ((yy-cy)/(radius*0.78))**2
        mask = np.exp(-2.15*d2).astype(np.float32)[:, :, None]
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + saturation/100.0), 0, 255)
        boosted = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)
        boosted *= 2.0 ** exposure_ev
        out[y1:y2, x1:x2] = np.clip(boosted*mask + roi.astype(np.float32)*(1-mask), 0, 255).astype(np.uint8)
    return out


def save_waveform(rgb: np.ndarray, path: Path, title: str = "") -> None:
    small = _sample(rgb, 768).astype(np.float32) / 255.0
    # Fixed 512x256 waveform. Log density makes both sparse highlights and dense midtones visible.
    width, height = 512, 256
    resized = cv2.resize(small, (width, max(64, round(small.shape[0] * width / small.shape[1]))), interpolation=cv2.INTER_AREA)
    canvas = np.full((height, width, 3), 12, dtype=np.uint8)
    for level, color in ((0.90, (75, 75, 75)), (0.50, (45, 45, 45)), (0.10, (55, 55, 55))):
        yline = height - 1 - round(level * (height-1))
        cv2.line(canvas, (0, yline), (width-1, yline), color, 1)
    for channel, color in ((0, (255, 70, 70)), (1, (70, 255, 70)), (2, (70, 110, 255))):
        vals = np.clip((resized[:, :, channel] * (height-1)).astype(np.int32), 0, height-1)
        density = np.zeros((height, width), dtype=np.float32)
        for x in range(width):
            bins = np.bincount(vals[:, x], minlength=height).astype(np.float32)
            density[:, x] = np.log1p(bins)
        density /= max(float(density.max()), 1e-6)
        for c in range(3):
            canvas[:, :, c] = np.maximum(canvas[:, :, c], (np.flipud(density) * color[c]).astype(np.uint8))
    if title:
        cv2.putText(canvas, title[:58], (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))


def load_eye_annotations(path: Path) -> dict[str, list[dict[str, float]]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("images", data)


def write_metrics(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
