from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import furcolor_cli as core
from selection_cli import selected_stems
from subject_intelligence import FurseeRuntime, cluster_embeddings


def project_private_target(path: Path, runtime_root: Path, *, directory: bool = False) -> Path:
    target = path.expanduser().resolve(strict=False)
    root = runtime_root.expanduser().resolve(strict=False)
    if target.parent != root:
        kind = "directory" if directory else "file"
        raise ValueError(f"Subject private {kind} must be a direct child of the project runtime directory")
    return target

def save_crop(rgb: np.ndarray, box: dict, target: Path) -> None:
    height, width = rgb.shape[:2]
    pad = round(0.05 * max(int(box["w"]), int(box["h"])))
    x1 = max(0, int(box["x"]) - pad)
    y1 = max(0, int(box["y"]) - pad)
    x2 = min(width, int(box["x"] + box["w"]) + pad)
    y2 = min(height, int(box["y"] + box["h"]) + pad)
    crop = rgb[y1:y2, x1:x2]
    if not crop.size:
        return
    image = Image.fromarray(crop)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=88, optimize=True)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="FurColor 4.0 local fursuit subject analysis")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    model_root = cfg.get("fursee_model_dir", "")
    manifest = Path(cfg["fursee_model_manifest"])
    runtime_root = config_path.parent.resolve()
    output = project_private_target(Path(cfg["subject_analysis"]), runtime_root)
    embeddings_path = project_private_target(Path(cfg["subject_embeddings"]), runtime_root)
    crops_dir = project_private_target(Path(cfg["subject_crops"]), runtime_root, directory=True)
    source = Path(cfg["source"])
    edited = Path(cfg["edited"])
    selection_path = Path(cfg["selection_file"])

    print("[1/4] Verifying Fursee model package...", flush=True)
    runtime = FurseeRuntime(
        model_root,
        manifest,
        fursuit_confidence=float(cfg.get("fursee_fursuit_confidence", 0.45)),
        face_confidence=float(cfg.get("fursee_face_confidence", 0.45)),
        image_size=int(cfg.get("fursee_image_size", 1280)),
    )
    print(f"device={runtime.device} model={runtime.status['model']}", flush=True)

    edited_stems = {path.stem for path in edited.iterdir() if path.is_file()}
    files = core.scan_source(source, edited_stems, bool(cfg.get("include_edited", False)))
    allowed = selected_stems(selection_path, [path.stem for path in files], cfg.get("selection_mode", "negative"))
    files = [path for path in files if path.stem in allowed]
    limit = int(cfg.get("subject_limit", 0))
    if limit > 0:
        files = files[:limit]
    if not files:
        raise ValueError("No selected photos are available for subject analysis")

    if crops_dir.exists():
        for item in crops_dir.iterdir():
            if not item.is_file() or item.suffix.lower() not in {".jpg", ".jpeg"}:
                raise RuntimeError(f"Unexpected entry in subject crop directory; refusing cleanup: {item.name}")
            item.unlink()
    crops_dir.mkdir(parents=True, exist_ok=True)

    print(f"[2/4] Detecting fursuit heads and human-face candidates in {len(files)} photos...", flush=True)
    images: dict[str, dict] = {}
    embedding_keys: list[str] = []
    embedding_vectors: list[np.ndarray] = []
    started = time.time()
    max_side = int(cfg.get("subject_max_side", 2400))
    batch_size = int(cfg.get("fursee_embedding_batch_size", 2))
    for number, path in enumerate(files, 1):
        rgb = core.load_rgb(path, max_side)
        detected = runtime.detect(rgb)
        fursuits = detected["fursuits"]
        faces = detected["faces"]
        for index, item in enumerate(fursuits):
            item["index"] = index
            item["key"] = f"{path.stem}:{index}"
            save_crop(rgb, item, crops_dir / f"{path.stem}_{index}.jpg")
        if fursuits:
            vectors = runtime.embeddings(rgb, fursuits, batch_size=batch_size)
            embedding_keys.extend(item["key"] for item in fursuits)
            embedding_vectors.extend(vector for vector in vectors)
        images[path.stem] = {
            "analysis_size": [int(rgb.shape[1]), int(rgb.shape[0])],
            "fursuits": fursuits,
            "faces": faces,
            "fursuit_count": len(fursuits),
            "face_candidate_count": len(faces),
        }
        if number == 1 or number % 10 == 0 or number == len(files):
            elapsed = max(time.time() - started, 0.001)
            print(f"  {number}/{len(files)} ({number / elapsed:.2f} images/s)", flush=True)

    print(f"[3/4] Clustering {len(embedding_keys)} detected fursuit heads...", flush=True)
    matrix = (
        np.asarray(embedding_vectors, dtype=np.float32)
        if embedding_vectors
        else np.empty((0, 512), dtype=np.float32)
    )
    clustered = cluster_embeddings(embedding_keys, matrix)
    labels = dict(zip(embedding_keys, clustered["labels"]))
    detection_lookup = {}
    for stem, record in images.items():
        for item in record["fursuits"]:
            item["cluster_id"] = labels.get(item["key"])
            detection_lookup[item["key"]] = {"stem": stem, "index": item["index"]}

    clusters = []
    for item in clustered["clusters"]:
        representative = detection_lookup[item["representative"]]
        stems = sorted({detection_lookup[key]["stem"] for key in item["members"]})
        clusters.append(
            {
                "id": item["id"],
                "detection_count": len(item["members"]),
                "photo_count": len(stems),
                "image_stems": stems,
                "representative": representative,
            }
        )

    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_embeddings = embeddings_path.with_suffix(".tmp.npz")
    np.savez_compressed(
        temporary_embeddings,
        keys=np.asarray(embedding_keys, dtype="U220"),
        vectors=matrix,
    )
    temporary_embeddings.replace(embeddings_path)

    report = {
        "version": 1,
        "pipeline": "furcolor_subject_intelligence_v4",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": {
            "name": runtime.status["model"],
            "upstream_commit": runtime.status["upstream_commit"],
            "verified": runtime.status["verified"],
            "device": runtime.device,
        },
        "privacy": {
            "scope": "single_project",
            "cross_project_linking": False,
            "real_person_linking": False,
            "embeddings_file": embeddings_path.name,
        },
        "selected_photo_count": len(files),
        "fursuit_detection_count": len(embedding_keys),
        "face_candidate_count": sum(record["face_candidate_count"] for record in images.values()),
        "cluster_count": len(clusters),
        "noise_count": clustered["noise_count"],
        "clustering": {"score": clustered["score"], "eps": clustered["eps"]},
        "images": images,
        "clusters": clusters,
    }
    atomic_json(output, report)
    print("[4/4] Subject analysis complete.", flush=True)
    print(
        json.dumps(
            {
                "photos": len(files),
                "fursuits": len(embedding_keys),
                "face_candidates": report["face_candidate_count"],
                "clusters": len(clusters),
                "unclustered": clustered["noise_count"],
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
