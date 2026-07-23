from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image

from fursee_assets import require_verified_assets


FURSUIT_NAMES = {"furry", "fursuit", "fursuit_head", "fur"}
FACE_NAMES = {"face", "human", "human_face", "person"}


def clamp_box(box: Iterable[float], width: int, height: int) -> dict[str, int]:
    x1, y1, x2, y2 = (float(value) for value in box)
    x1 = max(0, min(int(round(x1)), max(width - 1, 0)))
    y1 = max(0, min(int(round(y1)), max(height - 1, 0)))
    x2 = max(x1 + 1, min(int(round(x2)), width))
    y2 = max(y1 + 1, min(int(round(y2)), height))
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def box_intersection_fraction(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    ax1, ay1 = float(inner["x"]), float(inner["y"])
    ax2, ay2 = ax1 + float(inner["w"]), ay1 + float(inner["h"])
    bx1, by1 = float(outer["x"]), float(outer["y"])
    bx2, by2 = bx1 + float(outer["w"]), by1 + float(outer["h"])
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    return float(width * height / max((ax2 - ax1) * (ay2 - ay1), 1.0))


def scale_detections(
    detections: Iterable[dict[str, Any]],
    source_size: Iterable[int],
    target_shape: tuple[int, int] | tuple[int, int, int],
) -> list[dict[str, Any]]:
    source_width, source_height = (int(value) for value in source_size)
    target_height, target_width = target_shape[:2]
    sx = target_width / max(source_width, 1)
    sy = target_height / max(source_height, 1)
    result = []
    for item in detections:
        scaled = dict(item)
        scaled.update(
            {
                "x": round(float(item["x"]) * sx),
                "y": round(float(item["y"]) * sy),
                "w": max(1, round(float(item["w"]) * sx)),
                "h": max(1, round(float(item["h"]) * sy)),
            }
        )
        result.append(scaled)
    return result


def load_subject_analysis(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"version": 1, "images": {}, "clusters": []}
    target = Path(path)
    if not target.exists():
        return {"version": 1, "images": {}, "clusters": []}
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value.get("images"), dict):
        raise ValueError("Invalid subject analysis file")
    return value


def detections_for_image(
    analysis: dict[str, Any],
    stem: str,
    target_shape: tuple[int, int] | tuple[int, int, int],
    kind: str,
) -> list[dict[str, Any]]:
    record = analysis.get("images", {}).get(stem, {})
    source_size = record.get("analysis_size", [target_shape[1], target_shape[0]])
    return scale_detections(record.get(kind, []), source_size, target_shape)


def box_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    return max(box_intersection_fraction(a, b), box_intersection_fraction(b, a))


def fuse_subject_face_evidence(
    faces: Iterable[dict[str, Any]],
    fursuits: Iterable[dict[str, Any]],
    fursee_faces: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fuse independent signals without allowing a Fursee-only face to auto-blur."""
    result = [dict(face) for face in faces]
    fursuit_items = list(fursuits)
    face_items = list(fursee_faces)
    for face in result:
        geometry = float(face.get("landmark_geometry", 0.0))
        probability = face.get("memory_probability")
        fursuit_hits = [
            (box_overlap(face, item), float(item.get("score", 0.0)))
            for item in fursuit_items
        ]
        face_hits = [box_overlap(face, item) for item in face_items]
        fursuit_overlap, fursuit_score = max(fursuit_hits, default=(0.0, 0.0))
        face_overlap = max(face_hits, default=0.0)
        allowed = geometry >= .58 or (geometry >= .52 and probability is not None and probability >= .82)
        subject_suppressed = (
            fursuit_overlap >= .80 and fursuit_score >= .75 and face_overlap < .20
            and geometry < .48 and (probability is None or probability <= .50)
        )
        face["fursee_fursuit_overlap"] = round(fursuit_overlap, 4)
        face["fursee_face_overlap"] = round(face_overlap, 4)
        geometry_suppressed = geometry < .48 and face_overlap < .45
        face["auto_privacy_allowed"] = bool(allowed and not subject_suppressed)
        face["suppressed_by_geometry"] = geometry_suppressed
        face["suppressed_by_subject"] = subject_suppressed
        if subject_suppressed or face["suppressed_by_geometry"]:
            face["severity"] = "likely_fursuit"
        elif not allowed:
            face["severity"] = "review"
    for candidate in face_items:
        if max((box_overlap(candidate, face) for face in result), default=0.0) >= .45:
            continue
        result.append({
            **candidate,
            "severity": "review",
            "source": "fursee_face",
            "auto_privacy_allowed": False,
            "suppressed_by_geometry": False,
            "suppressed_by_subject": False,
            "review_reason": "Fursee-only human-face candidate; manual confirmation required",
        })
    return result

def _normalized(vectors: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    return values / (np.linalg.norm(values, axis=1, keepdims=True) + 1e-8)


def _pairwise_euclidean(vectors: np.ndarray) -> np.ndarray:
    gram = np.clip(vectors @ vectors.T, -1.0, 1.0)
    return np.sqrt(np.maximum(0.0, 2.0 - 2.0 * gram))


def _dbscan(distance: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    count = distance.shape[0]
    labels = np.full(count, -1, dtype=np.int32)
    visited = np.zeros(count, dtype=bool)
    cluster = 0
    for index in range(count):
        if visited[index]:
            continue
        visited[index] = True
        neighbors = np.flatnonzero(distance[index] <= eps).tolist()
        if len(neighbors) < min_samples:
            continue
        labels[index] = cluster
        queue = list(neighbors)
        queued = set(queue)
        cursor = 0
        while cursor < len(queue):
            point = queue[cursor]
            cursor += 1
            if not visited[point]:
                visited[point] = True
                point_neighbors = np.flatnonzero(distance[point] <= eps).tolist()
                if len(point_neighbors) >= min_samples:
                    for candidate in point_neighbors:
                        if candidate not in queued:
                            queue.append(candidate)
                            queued.add(candidate)
            if labels[point] < 0:
                labels[point] = cluster
        cluster += 1
    return labels


def _silhouette_cosine(vectors: np.ndarray, labels: np.ndarray) -> float:
    included = labels >= 0
    vectors = vectors[included]
    labels = labels[included]
    unique = sorted(set(int(value) for value in labels))
    if len(unique) < 2 or len(vectors) <= len(unique):
        return -1.0
    cosine_distance = 1.0 - np.clip(vectors @ vectors.T, -1.0, 1.0)
    scores = []
    for index, label in enumerate(labels):
        same = np.flatnonzero(labels == label)
        same = same[same != index]
        a = float(cosine_distance[index, same].mean()) if len(same) else 0.0
        other_means = [
            float(cosine_distance[index, labels == other].mean())
            for other in unique
            if other != int(label)
        ]
        b = min(other_means)
        scores.append((b - a) / max(a, b, 1e-8))
    return float(np.mean(scores))


def cluster_embeddings(
    keys: list[str],
    vectors: np.ndarray,
    *,
    arcface_margin: float = 0.5,
    tolerances: Iterable[float] | None = None,
    min_samples: int = 2,
) -> dict[str, Any]:
    values = _normalized(vectors)
    if len(keys) != len(values):
        raise ValueError("Embedding keys and vectors have different lengths")
    if not keys:
        return {"labels": [], "clusters": [], "noise_count": 0, "score": -1.0, "eps": 0.0}
    if len(keys) == 1:
        return {
            "labels": ["C001"],
            "clusters": [{"id": "C001", "members": [keys[0]], "representative": keys[0]}],
            "noise_count": 0,
            "score": -1.0,
            "eps": 0.0,
        }

    distance = _pairwise_euclidean(values)
    base_eps = math.sqrt(2.0 - 2.0 * math.cos(arcface_margin))
    candidates = list(tolerances or np.arange(1.0, 2.001, 0.05))
    best_labels = None
    best_score = -1.0
    best_eps = base_eps * 1.35
    for tolerance in candidates:
        eps = base_eps * float(tolerance)
        labels = _dbscan(distance, eps, min_samples)
        score = _silhouette_cosine(values, labels)
        cluster_count = len(set(int(value) for value in labels if value >= 0))
        if cluster_count >= 2 and score > best_score:
            best_labels, best_score, best_eps = labels.copy(), score, eps
    if best_labels is None:
        best_labels = _dbscan(distance, best_eps, min_samples)

    raw_clusters: dict[int, list[int]] = {}
    for index, label in enumerate(best_labels):
        if label >= 0:
            raw_clusters.setdefault(int(label), []).append(index)
    ordered = sorted(raw_clusters.values(), key=lambda members: min(keys[index] for index in members))
    display_labels: list[str | None] = [None] * len(keys)
    clusters = []
    for number, members in enumerate(ordered, 1):
        cluster_id = f"C{number:03d}"
        centroid = _normalized(values[members].mean(axis=0))[0]
        similarities = values[members] @ centroid
        representative_index = members[int(np.argmax(similarities))]
        member_keys = [keys[index] for index in members]
        for index in members:
            display_labels[index] = cluster_id
        clusters.append(
            {
                "id": cluster_id,
                "members": member_keys,
                "representative": keys[representative_index],
            }
        )
    return {
        "labels": display_labels,
        "clusters": clusters,
        "noise_count": sum(label is None for label in display_labels),
        "score": round(best_score, 5),
        "eps": round(float(best_eps), 6),
    }


class FurseeEmbeddingModel:
    def __init__(self, model_dir: Path, device: str):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModel, DINOv3ViTImageProcessorFast

        class Network(torch.nn.Module):
            def __init__(self, backbone):
                super().__init__()
                self.backbone = backbone
                self.projection = torch.nn.Sequential(
                    torch.nn.LayerNorm(1024),
                    torch.nn.Linear(1024, 512),
                    torch.nn.GELU(),
                    torch.nn.Dropout(0.1),
                    torch.nn.LayerNorm(512),
                    torch.nn.Linear(512, 512),
                )

            def forward(self, pixel_values):
                output = self.backbone(
                    pixel_values=pixel_values,
                    output_attentions=False,
                    return_dict=True,
                )
                pooled = getattr(output, "pooler_output", None)
                if pooled is None:
                    pooled = output.last_hidden_state[:, 0, :]
                return torch.nn.functional.normalize(self.projection(pooled.float()), p=2, dim=1)

        self.torch = torch
        self.device = torch.device(device)
        config = AutoConfig.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
        backbone = AutoModel.from_config(config, trust_remote_code=False)
        self.processor = DINOv3ViTImageProcessorFast.from_pretrained(
            model_dir,
            local_files_only=True,
        )
        self.model = Network(backbone)
        state = load_file(str(model_dir / "model.safetensors"), device="cpu")
        if any(key.startswith("backbone.model.") for key in state):
            state = {
                ("backbone." + key[len("backbone.model."):]) if key.startswith("backbone.model.") else key: value
                for key, value in state.items()
            }
        expected = self.model.state_dict()
        missing = sorted(set(expected) - set(state))
        unexpected = sorted(set(state) - set(expected))
        shape_mismatches = sorted(
            key for key in set(expected) & set(state)
            if tuple(expected[key].shape) != tuple(state[key].shape)
        )
        if missing or unexpected or shape_mismatches:
            raise RuntimeError(
                "Incompatible Fursee embedding weights after deterministic key migration: "
                f"missing={len(missing)} unexpected={len(unexpected)} shape_mismatches={len(shape_mismatches)}"
            )
        self.model.load_state_dict(state, strict=True)
        self.model.to(self.device).eval()
        # Fursee's projection head intentionally consumes FP32 pooled features.
        # Keep the embedding network in FP32 to match the upstream inference path.
        self.use_half = False

    def extract(self, crops: list[np.ndarray], batch_size: int = 2) -> np.ndarray:
        vectors = []
        for start in range(0, len(crops), max(1, batch_size)):
            images = [Image.fromarray(crop).convert("RGB") for crop in crops[start : start + batch_size]]
            pixels = self.processor(images=images, return_tensors="pt")["pixel_values"].to(self.device)
            if self.use_half:
                pixels = pixels.half()
            with self.torch.inference_mode():
                output = self.model(pixels)
            vectors.append(output.float().cpu().numpy())
        return np.vstack(vectors) if vectors else np.empty((0, 512), dtype=np.float32)


class FurseeRuntime:
    def __init__(
        self,
        model_root: str | Path,
        manifest_path: str | Path,
        *,
        fursuit_confidence: float = 0.45,
        face_confidence: float = 0.45,
        image_size: int = 1280,
    ):
        status = require_verified_assets(model_root, manifest_path)
        self.status = status
        self.model_dir = Path(status["model_dir"])
        self.fursuit_confidence = float(fursuit_confidence)
        self.face_confidence = float(face_confidence)
        self.image_size = int(image_size)
        import torch
        from ultralytics import YOLO

        self.torch = torch
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.detector = YOLO(str(self.model_dir / "cut.pt"))
        self.embedder: FurseeEmbeddingModel | None = None

    def _class_name(self, result: Any, class_id: int) -> str:
        names = result.names
        value = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
        return str(value).strip().casefold()

    def detect(self, rgb: np.ndarray) -> dict[str, list[dict[str, Any]]]:
        height, width = rgb.shape[:2]
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        threshold = min(self.fursuit_confidence, self.face_confidence)
        prediction = self.detector.predict(
            source=bgr,
            device=self.device,
            half=self.device.startswith("cuda"),
            conf=threshold,
            iou=0.45,
            imgsz=self.image_size,
            verbose=False,
        )[0]
        output: dict[str, list[dict[str, Any]]] = {"fursuits": [], "faces": []}
        if prediction.boxes is None:
            return output
        for box in prediction.boxes:
            class_id = int(box.cls[0].detach().cpu().item())
            score = float(box.conf[0].detach().cpu().item())
            name = self._class_name(prediction, class_id)
            target = None
            if name in FURSUIT_NAMES and score >= self.fursuit_confidence:
                target = "fursuits"
            elif name in FACE_NAMES and score >= self.face_confidence:
                target = "faces"
            if target is None:
                continue
            coords = box.xyxy[0].detach().cpu().tolist()
            item = clamp_box(coords, width, height)
            item.update({"score": round(score, 5), "class_name": name})
            output[target].append(item)
        return output

    def ensure_embedder(self) -> FurseeEmbeddingModel:
        if self.embedder is None:
            self.embedder = FurseeEmbeddingModel(self.model_dir, self.device)
        return self.embedder

    def embeddings(self, rgb: np.ndarray, boxes: list[dict[str, Any]], batch_size: int = 2) -> np.ndarray:
        crops = []
        height, width = rgb.shape[:2]
        for box in boxes:
            pad = round(0.04 * max(int(box["w"]), int(box["h"])))
            x1 = max(0, int(box["x"]) - pad)
            y1 = max(0, int(box["y"]) - pad)
            x2 = min(width, int(box["x"] + box["w"]) + pad)
            y2 = min(height, int(box["y"] + box["h"]) + pad)
            crop = rgb[y1:y2, x1:x2]
            if not crop.size:
                raise ValueError("Fursee produced an empty fursuit crop")
            crops.append(crop)
        return self.ensure_embedder().extract(crops, batch_size=batch_size)
