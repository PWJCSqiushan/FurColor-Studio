#!/usr/bin/env python3
"""FurColor CLI MVP.

Privacy-first batch assistant for fursuit event photography.
It never changes source files or a Lightroom catalog. It uses companion JPEGs
for speed, predicts a Lightroom-style global recipe from edited anchors,
creates private blurred previews, and flags possible human faces for review.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import rawpy
except Exception:  # pragma: no cover - JPEG companion mode still works.
    rawpy = None


SUPPORTED = {".jpg", ".jpeg", ".arw"}
XMP_KEYS = [
    "Temperature", "Tint", "Exposure2012", "Contrast2012",
    "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation",
    "SharpenAmount", "LuminanceSmoothing", "ColorNoiseReduction",
    "PostCropVignetteAmount", "LensProfileEnable", "RemoveChromaticAberration",
]


@dataclass
class Anchor:
    stem: str
    original_feature: np.ndarray
    original_lab_mean: np.ndarray
    original_lab_std: np.ndarray
    edited_lab_mean: np.ndarray
    edited_lab_std: np.ndarray
    settings: dict[str, Any]
    number: int


def parse_number(stem: str) -> int:
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else 0


def companion_jpeg(path: Path) -> Path | None:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return path
    for ext in (".JPG", ".jpg", ".JPEG", ".jpeg"):
        candidate = path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def load_rgb(path: Path, max_side: int = 1600) -> np.ndarray:
    jpeg = companion_jpeg(path)
    if jpeg is not None:
        with Image.open(jpeg) as im:
            im.draft("RGB", (max_side, max_side))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            return np.asarray(im).copy()
    if path.suffix.lower() == ".arw" and rawpy is not None:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,
                no_auto_bright=False,
                output_bps=8,
            )
        h, w = rgb.shape[:2]
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            rgb = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        return rgb
    raise RuntimeError(f"No readable JPEG companion or RAW decoder for {path}")


def color_feature(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    small = cv2.resize(rgb, (160, 160), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    mean = lab.reshape(-1, 3).mean(axis=0)
    std = lab.reshape(-1, 3).std(axis=0) + 1e-6
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    hist = cv2.normalize(hist, None).flatten().astype(np.float32)
    feature = np.concatenate([mean / 255.0, std / 128.0, hist])
    return feature, mean, std


def feature_distance(a: np.ndarray, b: np.ndarray, num_a: int, num_b: int) -> float:
    global_distance = float(np.linalg.norm(a[:6] - b[:6]))
    hist_a, hist_b = a[6:].astype(np.float32), b[6:].astype(np.float32)
    histogram_distance = float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_BHATTACHARYYA))
    temporal_distance = min(abs(num_a - num_b) / 450.0, 1.0)
    return 0.55 * global_distance + 0.30 * histogram_distance + 0.15 * temporal_distance


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data if isinstance(data, list) else [])
    return {Path(item["file"]).stem: item for item in items}


def build_anchors(source: Path, edited: Path, manifest_path: Path) -> list[Anchor]:
    manifest = load_manifest(manifest_path)
    anchors: list[Anchor] = []
    for stem, item in sorted(manifest.items()):
        original_candidates = [source / str(item.get("file", ""))]
        original_candidates.extend(source / f"{stem}{ext}" for ext in (".JPG", ".jpg", ".JPEG", ".jpeg", ".ARW", ".arw"))
        edited_candidates = [edited / str(item.get("edited_jpeg", ""))]
        edited_candidates.extend(edited / f"{stem}{ext}" for ext in (".jpg", ".JPG", ".jpeg", ".JPEG"))
        original = next((path for path in original_candidates if path.name and path.is_file()), None)
        edited_file = next((path for path in edited_candidates if path.name and path.is_file()), None)
        if original is None or edited_file is None:
            continue
        orig_rgb = load_rgb(original, 1000)
        edit_rgb = load_rgb(edited_file, 1000)
        feature, om, os = color_feature(orig_rgb)
        _, em, es = color_feature(edit_rgb)
        anchors.append(Anchor(
            stem=stem,
            original_feature=feature,
            original_lab_mean=om,
            original_lab_std=os,
            edited_lab_mean=em,
            edited_lab_std=es,
            settings=item.get("settings", {}),
            number=parse_number(stem),
        ))
    if not anchors:
        raise RuntimeError("No valid original/edited anchor pairs were found.")
    return anchors


def find_anchor(rgb: np.ndarray, stem: str, anchors: list[Anchor]) -> tuple[Anchor, float]:
    feature, _, _ = color_feature(rgb)
    number = parse_number(stem)
    ranked = sorted((feature_distance(feature, a.original_feature, number, a.number), a) for a in anchors)
    return ranked[0][1], ranked[0][0]


def apply_anchor_style(rgb: np.ndarray, anchor: Anchor, strength: float) -> np.ndarray:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    scale = np.clip(anchor.edited_lab_std / anchor.original_lab_std, 0.72, 1.38)
    mapped = (lab - anchor.original_lab_mean) * scale + anchor.edited_lab_mean
    mixed = lab * (1.0 - strength) + mapped * strength
    mixed = np.clip(mixed, 0, 255).astype(np.uint8)
    return cv2.cvtColor(mixed, cv2.COLOR_LAB2RGB)


class FacePresenceDetector:
    def __init__(self, model: Path, threshold: float = 0.66, max_side: int = 960):
        self.threshold = threshold
        self.max_side = max_side
        self.detector = cv2.FaceDetectorYN.create(
            str(model), "", (320, 320), threshold, 0.3, 5000
        )

    def detect(self, rgb: np.ndarray, image_id: str | None = None) -> list[dict[str, Any]]:
        h, w = rgb.shape[:2]
        scale = min(1.0, self.max_side / max(h, w))
        small = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        self.detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, faces = self.detector.detect(bgr)
        results: list[dict[str, Any]] = []
        if faces is None:
            return results
        for f in faces:
            x, y, fw, fh = [float(v) for v in f[:4]]
            score = float(f[-1])
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(bgr.shape[1], int(x + fw)), min(bgr.shape[0], int(y + fh))
            crop = bgr[y1:y2, x1:x2]
            skin_ratio = 0.0
            if crop.size:
                ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
                mask = cv2.inRange(ycrcb, np.array([0, 125, 70]), np.array([255, 180, 140]))
                skin_ratio = float((mask > 0).mean())
            severity = "high" if score >= 0.76 and skin_ratio >= 0.045 else "review"
            results.append({
                "x": round(x / scale), "y": round(y / scale),
                "w": round(fw / scale), "h": round(fh / scale),
                "score": round(score, 4), "skin_ratio": round(skin_ratio, 4),
                "severity": severity,
            })
        return results


def blur_regions(rgb: np.ndarray, faces: list[dict[str, Any]]) -> np.ndarray:
    out = rgb.copy()
    h, w = out.shape[:2]
    for face in faces:
        pad = int(0.12 * max(face["w"], face["h"]))
        x1, y1 = max(0, face["x"] - pad), max(0, face["y"] - pad)
        x2, y2 = min(w, face["x"] + face["w"] + pad), min(h, face["y"] + face["h"] + pad)
        roi = out[y1:y2, x1:x2]
        if roi.size:
            k = max(15, (min(roi.shape[:2]) // 4) | 1)
            out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
    return out


def add_footer(rgb: np.ndarray, text: str, risk: str) -> np.ndarray:
    im = Image.fromarray(rgb)
    footer_h = 42
    canvas = Image.new("RGB", (im.width, im.height + footer_h), "#161a20")
    canvas.paste(im, (0, 0))
    draw = ImageDraw.Draw(canvas)
    color = "#ff6b6b" if risk == "high" else ("#ffd166" if risk == "review" else "#9be564")
    draw.text((12, im.height + 12), text, fill=color, font=ImageFont.load_default())
    return np.asarray(canvas)


def xmp_text(settings: dict[str, Any], source_stem: str, anchor_stem: str) -> str:
    attrs = {
        "crs:Version": "15.4",
        "crs:ProcessVersion": "15.4",
        "crs:WhiteBalance": "Custom" if "Temperature" in settings else "As Shot",
    }
    for key in XMP_KEYS:
        if key in settings:
            attrs[f"crs:{key}"] = str(settings[key])
    attr_text = "\n      ".join(f'{k}="{escape(v)}"' for k, v in attrs.items())
    return f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
      xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      {attr_text}>
   <dc:description><rdf:Alt><rdf:li xml:lang="x-default">FurColor MVP suggestion for {escape(source_stem)}, anchor {escape(anchor_stem)}. Review before applying.</rdf:li></rdf:Alt></dc:description>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
'''


def risk_level(faces: list[dict[str, Any]]) -> str:
    if any(f["severity"] == "high" for f in faces):
        return "high"
    if faces:
        return "review"
    return "none"


def make_contact_sheets(records: list[dict[str, Any]], preview_dir: Path, out_dir: Path, per_page: int = 20) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    tile_w, tile_h, cols = 300, 245, 5
    pages = math.ceil(len(records) / per_page) if records else 0
    for page in range(pages):
        batch = records[page * per_page:(page + 1) * per_page]
        rows = math.ceil(len(batch) / cols)
        sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), "#252a30")
        draw = ImageDraw.Draw(sheet)
        for i, rec in enumerate(batch):
            path = preview_dir / f'{Path(rec["file"]).stem}.jpg'
            if not path.exists():
                continue
            with Image.open(path) as im0:
                im = im0.convert("RGB")
                im.thumbnail((tile_w - 12, tile_h - 34), Image.Resampling.LANCZOS)
                x, y = (i % cols) * tile_w, (i // cols) * tile_h
                sheet.paste(im, (x + (tile_w - im.width)//2, y + 4))
                risk = rec["face_risk"]
                color = "#ff5d5d" if risk == "high" else ("#ffc857" if risk == "review" else "#a7e36b")
                draw.rectangle((x + 2, y + 2, x + tile_w - 3, y + tile_h - 3), outline=color, width=3)
                label = f'{Path(rec["file"]).stem}  A:{rec["anchor"]}  F:{len(rec["faces"])}'
                draw.text((x + 8, y + tile_h - 23), label, fill=color, font=ImageFont.load_default())
        sheet.save(out_dir / f"contact_{page+1:02d}.jpg", quality=84, optimize=True)
    return pages


def scan_source(source: Path, edited_stems: set[str], include_edited: bool) -> list[Path]:
    # Prefer one JPEG companion per capture for fast analysis; use ARW only if JPEG is absent.
    files: dict[str, Path] = {}
    for p in source.iterdir():
        if not p.is_file() or p.suffix.lower() not in SUPPORTED:
            continue
        stem = p.stem
        if not include_edited and stem in edited_stems:
            continue
        existing = files.get(stem)
        if existing is None or (p.suffix.lower() in {".jpg", ".jpeg"} and existing.suffix.lower() == ".arw"):
            files[stem] = p
    return sorted(files.values(), key=lambda p: (parse_number(p.stem), p.name.lower()))


def batch(args: argparse.Namespace) -> int:
    source, edited, output = Path(args.source), Path(args.edited), Path(args.output)
    manifest, model = Path(args.manifest), Path(args.face_model)
    for p, label in ((source, "source"), (edited, "edited"), (manifest, "manifest"), (model, "face model")):
        if not p.exists():
            raise FileNotFoundError(f"Missing {label}: {p}")
    output.mkdir(parents=True, exist_ok=True)
    preview_dir = output / "previews_private"
    recipe_dir = output / "recipes"
    xmp_dir = output / "xmp_review_only"
    for d in (preview_dir, recipe_dir, xmp_dir): d.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading edited anchors...", flush=True)
    anchors = build_anchors(source, edited, manifest)
    edited_stems = {p.stem for p in edited.iterdir() if p.is_file()}
    files = scan_source(source, edited_stems, args.include_edited)
    if args.single:
        wanted = Path(args.single).stem
        files = [p for p in files if p.stem == wanted]
    if args.limit > 0:
        files = files[:args.limit]
    print(f"anchors={len(anchors)} targets={len(files)}", flush=True)

    detector = FacePresenceDetector(model, args.face_threshold)
    records: list[dict[str, Any]] = []
    started = time.time()
    print("[2/4] Analyzing, privacy-checking and rendering previews...", flush=True)
    for idx, path in enumerate(files, 1):
        try:
            rgb = load_rgb(path, args.max_side)
            anchor, distance = find_anchor(rgb, path.stem, anchors)
            faces = detector.detect(rgb, path.stem)
            risk = risk_level(faces)
            styled = apply_anchor_style(rgb, anchor, args.style_strength)
            private = blur_regions(styled, faces)
            private = add_footer(private, f"AI PREVIEW | {path.stem} | anchor {anchor.stem} | face {risk}", risk)
            Image.fromarray(private).save(preview_dir / f"{path.stem}.jpg", quality=args.jpeg_quality, optimize=True)

            recipe = {
                "file": path.name,
                "source_path": str(path),
                "anchor": anchor.stem,
                "anchor_distance": round(distance, 5),
                "face_risk": risk,
                "faces": faces,
                "suggested_global_settings": anchor.settings,
                "warnings": [
                    "Face detection is conservative and not proof that an image is safe to publish.",
                    "The preview is an approximate color transfer, not an Adobe Lightroom render.",
                    "Review crop, human faces, badges, QR codes, room numbers and screens manually.",
                ],
            }
            (recipe_dir / f"{path.stem}.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
            (xmp_dir / f"{path.stem}.xmp").write_text(xmp_text(anchor.settings, path.stem, anchor.stem), encoding="utf-8")
            records.append(recipe)
        except Exception as exc:
            records.append({"file": path.name, "error": str(exc), "anchor": "", "anchor_distance": "", "face_risk": "error", "faces": [], "suggested_global_settings": {}})
        if idx == 1 or idx % 25 == 0 or idx == len(files):
            elapsed = max(time.time() - started, 0.001)
            print(f"  {idx}/{len(files)} ({idx/elapsed:.2f} images/s)", flush=True)

    print("[3/4] Writing reports...", flush=True)
    csv_path = output / "lightroom_import_plan.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["file", "anchor", "anchor_distance", "face_risk", "face_count"] + XMP_KEYS
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            row = {
                "file": rec.get("file", ""), "anchor": rec.get("anchor", ""),
                "anchor_distance": rec.get("anchor_distance", ""),
                "face_risk": rec.get("face_risk", ""), "face_count": len(rec.get("faces", [])),
            }
            for key in XMP_KEYS:
                row[key] = rec.get("suggested_global_settings", {}).get(key, "")
            writer.writerow(row)

    good = [r for r in records if "error" not in r]
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(source), "edited": str(edited),
        "target_count": len(records), "success_count": len(good),
        "errors": len(records) - len(good),
        "face_high": sum(r.get("face_risk") == "high" for r in good),
        "face_review": sum(r.get("face_risk") == "review" for r in good),
        "face_none": sum(r.get("face_risk") == "none" for r in good),
        "privacy": "Local face-presence detection only; no identity recognition or embeddings.",
        "limitations": [
            "A missed face remains possible; every commercial/public output requires human review.",
            "Fursuit faces can cause false positives until a domain-specific two-class detector is added.",
            "Generated XMP files are suggestions kept outside the source folder; test on copies before use.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pages = make_contact_sheets(good, preview_dir, output / "contact_sheets")
    print("[4/4] Done.", flush=True)
    print(json.dumps({**summary, "contact_pages": pages, "output": str(output)}, ensure_ascii=False, indent=2))
    return 0 if summary["errors"] == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Privacy-first fursuit event photo preprocessing MVP")
    p.add_argument("--source", required=True, help="Folder containing ARW/JPG source pairs")
    p.add_argument("--edited", required=True, help="Folder containing edited anchor JPEGs")
    p.add_argument("--manifest", required=True, help="JSON manifest exported from Lightroom read-only analysis")
    p.add_argument("--face-model", required=True, help="YuNet ONNX face detector path")
    p.add_argument("--output", required=True, help="New derived-output folder; sources are never modified")
    p.add_argument("--limit", type=int, default=0, help="Process only the first N targets; 0 means all")
    p.add_argument("--single", default="", help="Process one stem, e.g. DSC01207")
    p.add_argument("--include-edited", action="store_true", help="Include the 32 edited anchors for testing")
    p.add_argument("--style-strength", type=float, default=0.72, help="Approximate preview style strength, 0..1")
    p.add_argument("--face-threshold", type=float, default=0.66, help="Conservative YuNet detection threshold")
    p.add_argument("--max-side", type=int, default=1400, help="Maximum preview side length")
    p.add_argument("--jpeg-quality", type=int, default=80, help="Private preview JPEG quality")
    return p


if __name__ == "__main__":
    try:
        sys.exit(batch(build_parser().parse_args()))
    except KeyboardInterrupt:
        print("Interrupted. Source files were not modified.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
