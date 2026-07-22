from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from subject_intelligence import FurseeRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Fursee detector and embedding smoke test")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    with Image.open(args.image) as image:
        rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB")).copy()
    runtime = FurseeRuntime(args.model_dir, args.manifest, image_size=640)
    detected = runtime.detect(rgb)
    boxes = detected["fursuits"][:1]
    used_detector_box = bool(boxes)
    if not boxes:
        height, width = rgb.shape[:2]
        boxes = [{"x": 0, "y": 0, "w": width, "h": height, "score": 0.0}]
    vectors = runtime.embeddings(rgb, boxes, batch_size=1)
    if vectors.shape != (1, 512) or not np.isfinite(vectors).all():
        raise RuntimeError(f"Invalid embedding result: {vectors.shape}")
    norm = float(np.linalg.norm(vectors[0]))
    if not 0.99 <= norm <= 1.01:
        raise RuntimeError(f"Embedding was not normalized: {norm}")
    print(json.dumps({
        "device": runtime.device,
        "fursuit_detections": len(detected["fursuits"]),
        "face_candidates": len(detected["faces"]),
        "used_detector_box_for_embedding": used_detector_box,
        "embedding_shape": list(vectors.shape),
        "embedding_norm": round(norm, 6),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())