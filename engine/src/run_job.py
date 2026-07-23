from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import furcolor_cli as core
from face_memory import apply_memory, load_model
from selection_cli import selected_stems
from subject_intelligence import (
    detections_for_image,
    fuse_subject_face_evidence,
    load_subject_analysis,
)


def opencv_safe_model_path(path: Path) -> Path:
    try:
        str(path).encode("ascii")
        return path
    except UnicodeEncodeError:
        cache = Path.home() / ".furcolor" / "models" / path.name
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists() or cache.stat().st_size != path.stat().st_size:
            shutil.copy2(path, cache)
        return cache


def landmark_geometry(face_row: np.ndarray) -> tuple[float, list[dict[str, float]]]:
    """Score whether YuNet's five landmarks form a plausible human face."""
    x, y, w, h = [float(v) for v in face_row[:4]]
    raw = np.asarray(face_row[4:14], dtype=float).reshape(5, 2)
    points = [{"x": round(float(px), 2), "y": round(float(py), 2)} for px, py in raw]
    if w <= 1 or h <= 1:
        return 0.0, points
    q = raw.copy()
    q[:, 0] = (q[:, 0] - x) / w
    q[:, 1] = (q[:, 1] - y) / h
    e1, e2, nose, m1, m2 = q
    eye_mid = (e1 + e2) / 2
    mouth_mid = (m1 + m2) / 2
    eye_dist = abs(e1[0] - e2[0])
    eye_level = abs(e1[1] - e2[1])
    mouth_level = abs(m1[1] - m2[1])
    inside = float(np.mean((q[:, 0] >= -.12) & (q[:, 0] <= 1.12) & (q[:, 1] >= -.12) & (q[:, 1] <= 1.15)))
    tests = [
        (0.16 <= eye_dist <= 0.78, 0.18), (eye_level <= 0.24, 0.12),
        (eye_mid[1] + 0.035 <= nose[1] <= mouth_mid[1] + 0.08, 0.18),
        (mouth_mid[1] >= eye_mid[1] + 0.15, 0.18), (mouth_level <= 0.24, 0.08),
        (min(e1[0], e2[0]) - .18 <= nose[0] <= max(e1[0], e2[0]) + .18, 0.10),
        (abs(nose[0] - mouth_mid[0]) <= 0.28, 0.08),
    ]
    return round(float(sum(weight for ok, weight in tests if ok) * inside), 4), points



def main() -> int:
    parser = argparse.ArgumentParser(description="Run FurColor V4 from a UTF-8 JSON job file")
    parser.add_argument("--config", required=True)
    cli = parser.parse_args()
    config_path = Path(cli.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    memory_path = root / cfg.get("face_memory", "config/face_memory.json")
    memory_model = load_model(memory_path)
    subject_analysis = load_subject_analysis(cfg.get("subject_analysis"))
    original_detector = core.FacePresenceDetector

    class LearnedDetector(original_detector):
        def detect(self, rgb, image_id=None):
            h, w = rgb.shape[:2]
            scale = min(1.0, self.max_side / max(h, w))
            small = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
            bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
            self.detector.setInputSize((bgr.shape[1], bgr.shape[0]))
            _, rows = self.detector.detect(bgr)
            faces = []
            if rows is not None:
                for row in rows:
                    x, y, fw, fh = [float(v) for v in row[:4]]
                    score = float(row[-1])
                    x1, y1 = max(0, int(x)), max(0, int(y))
                    x2, y2 = min(bgr.shape[1], int(x + fw)), min(bgr.shape[0], int(y + fh))
                    crop = bgr[y1:y2, x1:x2]
                    skin = 0.0
                    if crop.size:
                        yc = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
                        mask = cv2.inRange(yc, np.array([0, 125, 70]), np.array([255, 180, 140]))
                        skin = float((mask > 0).mean())
                    geometry, landmarks = landmark_geometry(row)
                    faces.append({
                        "x": round(x / scale), "y": round(y / scale),
                        "w": round(fw / scale), "h": round(fh / scale),
                        "score": round(score, 4), "skin_ratio": round(skin, 4),
                        "severity": "high" if score >= .76 and skin >= .045 else "review",
                        "source": "yunet",
                        "landmark_geometry": geometry,
                        "landmarks": [
                            {"x": round(point["x"] / scale, 2), "y": round(point["y"] / scale, 2)}
                            for point in landmarks
                        ],
                    })
            faces = apply_memory(rgb, faces, memory_model)
            fursuits = detections_for_image(subject_analysis, image_id, rgb.shape, "fursuits") if image_id else []
            fursee_faces = detections_for_image(subject_analysis, image_id, rgb.shape, "faces") if image_id else []
            return fuse_subject_face_evidence(faces, fursuits, fursee_faces)

    core.FacePresenceDetector = LearnedDetector

    def learned_risk(faces):
        active = [
            face for face in faces
            if not face.get("suppressed_by_memory", False)
            and not face.get("suppressed_by_geometry", False)
            and not face.get("suppressed_by_subject", False)
        ]
        if any(face.get("severity") == "high" and face.get("auto_privacy_allowed", False) for face in active):
            return "high"
        return "review" if active else "none"

    original_blur = core.blur_regions

    def learned_blur(rgb, faces):
        active = [
            face for face in faces
            if not face.get("suppressed_by_memory", False)
            and not face.get("suppressed_by_geometry", False)
            and not face.get("suppressed_by_subject", False)
            and face.get("auto_privacy_allowed", True)
        ]
        return original_blur(rgb, active)

    core.risk_level = learned_risk
    core.blur_regions = learned_blur

    original_scan = core.scan_source
    selection_path = root / cfg.get("selection_file", "feedback/selection.json")

    def selection_scan(source, edited_stems, include_edited):
        files = original_scan(source, edited_stems, include_edited)
        allowed = selected_stems(selection_path, [path.stem for path in files], cfg.get("selection_mode", "negative"))
        return [path for path in files if path.stem in allowed]

    core.scan_source = selection_scan

    raw_model_path = root / cfg.get("face_model", "models/face_detection_yunet_2023mar.onnx")
    safe_model_path = opencv_safe_model_path(raw_model_path)
    args = argparse.Namespace(
        source=cfg["source"], edited=cfg["edited"],
        manifest=str(root / cfg.get("manifest", "config/starfestival_lightroom_manifest.json")),
        face_model=str(safe_model_path), output=cfg["analysis_output"],
        limit=int(cfg.get("limit", 0)), single=cfg.get("single", ""),
        include_edited=bool(cfg.get("include_edited", False)),
        style_strength=float(cfg.get("style_strength", .72)),
        face_threshold=float(cfg.get("face_threshold", .50 if memory_model else .66)),
        max_side=int(cfg.get("max_side", 1400)), jpeg_quality=int(cfg.get("jpeg_quality", 80)),
    )
    print(f"face_memory={'loaded' if memory_model else 'not trained yet'}")
    print(f"subject_analysis={'loaded' if subject_analysis.get('images') else 'not available'}")
    print(f"selection={selection_path} mode={cfg.get('selection_mode', 'negative')}")
    print(f"opencv_model={safe_model_path}")
    return core.batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
