from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

FEATURE_NAMES = [
    "base_score", "skin_ratio", "box_area_ratio", "box_aspect",
    "mean_h", "mean_s", "mean_v", "std_s", "std_v",
    "edge_density", "white_ratio", "dark_ratio",
]


def extract_features(rgb: np.ndarray, face: dict[str, Any]) -> np.ndarray:
    h, w = rgb.shape[:2]
    x1 = max(0, int(face["x"]))
    y1 = max(0, int(face["y"]))
    x2 = min(w, x1 + max(1, int(face["w"])))
    y2 = min(h, y1 + max(1, int(face["h"])))
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        crop = np.zeros((8, 8, 3), dtype=np.uint8)
    crop = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV).astype(np.float32)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 70, 150)
    value = hsv[:, :, 2] / 255.0
    return np.array([
        float(face.get("score", 0.0)),
        float(face.get("skin_ratio", 0.0)),
        float((face.get("w", 0) * face.get("h", 0)) / max(w * h, 1)),
        float(face.get("w", 1) / max(face.get("h", 1), 1)),
        float(hsv[:, :, 0].mean() / 180.0),
        float(hsv[:, :, 1].mean() / 255.0),
        float(value.mean()),
        float(hsv[:, :, 1].std() / 255.0),
        float(value.std()),
        float((edges > 0).mean()),
        float((value >= 0.86).mean()),
        float((value <= 0.14).mean()),
    ], dtype=np.float64)


def sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def train_from_jsonl(feedback_path: Path, model_path: Path) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for line in feedback_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("label") not in {"human", "fursuit"}:
            continue
        latest[item["key"]] = item
    items = list(latest.values())
    human = sum(i["label"] == "human" for i in items)
    fursuit = sum(i["label"] == "fursuit" for i in items)
    if human < 2 or fursuit < 2:
        raise RuntimeError("At least 2 human and 2 fursuit labels are required.")
    X = np.asarray([i["features"] for i in items], dtype=np.float64)
    y = np.asarray([1.0 if i["label"] == "human" else 0.0 for i in items])
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-6
    Z = (X - mean) / std
    weights = np.zeros(Z.shape[1], dtype=np.float64)
    bias = 0.0
    pos_weight = len(y) / (2.0 * max(y.sum(), 1.0))
    neg_weight = len(y) / (2.0 * max((1.0 - y).sum(), 1.0))
    sample_weight = np.where(y == 1, pos_weight, neg_weight)
    lr, l2 = 0.045, 0.025
    for _ in range(2200):
        pred = sigmoid(Z @ weights + bias)
        err = (pred - y) * sample_weight
        weights -= lr * ((Z.T @ err) / len(y) + l2 * weights)
        bias -= lr * float(err.mean())
    prob = sigmoid(Z @ weights + bias)
    pred_label = (prob >= 0.5).astype(float)
    accuracy = float((pred_label == y).mean())
    model = {
        "version": 1,
        "kind": "online_logistic_calibrator_over_yunet",
        "feature_names": FEATURE_NAMES,
        "mean": mean.tolist(), "std": std.tolist(),
        "weights": weights.tolist(), "bias": bias,
        "human_threshold": 0.66,
        "fursuit_threshold": 0.24,
        "samples": len(items), "human_samples": human, "fursuit_samples": fursuit,
        "training_accuracy": accuracy,
        "note": "Training accuracy is not validation accuracy. Continue labeling diverse scenes.",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    return model


def load_model(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def predict_probability(features: np.ndarray, model: dict[str, Any]) -> float:
    mean = np.asarray(model["mean"], dtype=np.float64)
    std = np.asarray(model["std"], dtype=np.float64)
    weights = np.asarray(model["weights"], dtype=np.float64)
    z = (features - mean) / std
    return float(sigmoid(z @ weights + float(model["bias"])))


def apply_memory(rgb: np.ndarray, faces: list[dict[str, Any]], model: dict[str, Any] | None) -> list[dict[str, Any]]:
    if model is None:
        for face in faces:
            face["memory_probability"] = None
            face["suppressed_by_memory"] = False
        return faces
    high = float(model.get("human_threshold", 0.66))
    low = float(model.get("fursuit_threshold", 0.24))
    for face in faces:
        features = extract_features(rgb, face)
        probability = predict_probability(features, model)
        face["memory_probability"] = round(probability, 4)
        face["suppressed_by_memory"] = probability <= low
        if probability >= high:
            face["severity"] = "high"
        elif probability <= low:
            face["severity"] = "likely_fursuit"
        else:
            face["severity"] = "review"
    return faces
