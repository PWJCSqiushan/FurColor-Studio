from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

from PIL import Image, ImageOps

from . import db, settings
from .security import safe_path, safe_stem

EXTENSIONS = {".jpg", ".jpeg", ".arw"}
QA_ITEMS = {"privacy", "mask", "exposure", "watermark"}


def project(project_id: int) -> dict:
    value = db.one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not value:
        raise LookupError("项目不存在")
    return value


def create_project(data: dict) -> int:
    if settings.DEMO:
        raise PermissionError("云端演示模式禁止创建项目")
    path_keys = ("source_dir", "edited_dir", "analysis_dir", "output_dir", "watermark_path", "manifest_path")
    required_existing = {"source_dir", "edited_dir", "watermark_path", "manifest_path"}
    paths: dict[str, str] = {}
    for key in path_keys:
        raw = (data.get(key) or "").strip()
        paths[key] = str(safe_path(raw, key in required_existing)) if raw else ""
    mode = data.get("selection_mode", "negative")
    if mode not in {"positive", "negative"}:
        raise ValueError("未知选片模式")
    stamp = db.now()
    project_id = db.run(
        """INSERT INTO projects(
        name,source_dir,edited_dir,analysis_dir,output_dir,watermark_path,manifest_path,
        selection_mode,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (data["name"].strip(), paths["source_dir"], paths["edited_dir"], paths["analysis_dir"],
         paths["output_dir"], paths["watermark_path"], paths["manifest_path"], mode,
         "configured", stamp, stamp),
    )
    db.audit(project_id, "project.created")
    return project_id


def scan(project_id: int) -> int:
    p = project(project_id)
    source = safe_path(p["source_dir"], True)
    found: dict[str, Path] = {}
    for item in source.iterdir():
        if item.is_file() and item.suffix.lower() in EXTENSIONS:
            current = found.get(item.stem)
            if current is None or item.suffix.lower() in {".jpg", ".jpeg"}:
                found[item.stem] = item
    for stem, item in found.items():
        db.run("""INSERT INTO photos(project_id,stem,source_path) VALUES(?,?,?)
        ON CONFLICT(project_id,stem) DO UPDATE SET source_path=excluded.source_path""", (project_id, stem, str(item)))
    db.audit(project_id, "source.scanned", {"count": len(found)})
    return len(found)


def set_selection(project_id: int, stem: str, value: str) -> None:
    safe_stem(stem)
    if value not in {"keep", "reject", "unset"}:
        raise ValueError("未知选片状态")
    db.run("UPDATE photos SET selection=? WHERE project_id=? AND stem=?", (value, project_id, stem))
    db.audit(project_id, "selection.changed", {"stem": stem, "value": value})


def selected_stems(project_id: int) -> set[str]:
    p = project(project_id)
    photos = db.rows("SELECT stem,selection FROM photos WHERE project_id=?", (project_id,))
    if p["selection_mode"] == "positive":
        return {x["stem"] for x in photos if x["selection"] == "keep"}
    return {x["stem"] for x in photos if x["selection"] != "reject"}


def thumbnail(project_id: int, stem: str) -> Path:
    safe_stem(stem)
    row = db.one("SELECT source_path FROM photos WHERE project_id=? AND stem=?", (project_id, stem))
    if not row:
        raise LookupError("照片不存在")
    source = safe_path(row["source_path"], True)
    target = settings.DATA_DIR / "thumbnails" / str(project_id) / f"{stem}.jpg"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((640, 640), Image.Resampling.LANCZOS)
        image.save(target, "JPEG", quality=82, optimize=True)
    return target


def _project_runtime(project_id: int) -> Path:
    path = settings.DATA_DIR / "projects" / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def engine_config(project_id: int) -> Path:
    p = project(project_id)
    root = _project_runtime(project_id)
    choices = {x["stem"]: x["selection"] for x in db.rows("SELECT stem,selection FROM photos WHERE project_id=?", (project_id,)) if x["selection"] != "unset"}
    selection_file = root / "selection.json"
    selection_file.write_text(json.dumps({"version": 1, "mode": p["selection_mode"], "choices": choices}, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = p["manifest_path"] or str(settings.ENGINE_ROOT / "config" / "manifest.example.json")
    config = {
        "source": p["source_dir"], "edited": p["edited_dir"], "analysis_output": p["analysis_dir"],
        "draft_output_v3": p["output_dir"], "manifest": manifest, "selection_file": str(selection_file),
        "selection_mode": p["selection_mode"], "eye_annotations": str(root / "eye_annotations.json"),
        "face_model": str(settings.ENGINE_ROOT / "models" / "face_detection_yunet_2023mar.onnx"),
        "face_memory": str(root / "face_memory.json"), "watermark_path": p["watermark_path"],
        "watermark_opacity": 0.8, "watermark_width_ratio": 0.06, "watermark_margin_ratio": 0.015,
        "style_strength": 0.72, "max_side": 1400, "delivery_max_side": 3200,
        "delivery_jpeg_quality": 91, "privacy_process_review": False, "include_edited": False,
    }
    target = root / "job.json"
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _engine_python() -> str:
    bundled = settings.ENGINE_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(bundled if bundled.exists() else Path(sys.executable))


def start_job(project_id: int, kind: str) -> int:
    if settings.DEMO:
        raise PermissionError("云端演示模式禁止处理照片")
    scripts = {"analyze": "run_job_v3_final.py", "render": "render_v3_pixel_reference.py",
               "face-review": "run_review_job.py", "eye-review": "run_eye_annotation_job.py"}
    if kind not in scripts:
        raise ValueError("未知任务类型")
    config = engine_config(project_id)
    script = settings.ENGINE_ROOT / "src" / scripts[kind]
    if not script.exists():
        raise FileNotFoundError(f"图像引擎脚本不存在：{script}")
    job_id = db.run("INSERT INTO jobs(project_id,kind,status,created_at,updated_at) VALUES(?,?,?,?,?)", (project_id, kind, "queued", db.now(), db.now()))

    def worker() -> None:
        db.run("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (db.now(), job_id))
        command = [_engine_python(), str(script), "--config", str(config)]
        try:
            result = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
            log = (result.stdout + "\n" + result.stderr)[-80000:]
            status = "complete" if result.returncode == 0 else "failed"
        except Exception as exc:
            log, status = str(exc), "failed"
        db.run("UPDATE jobs SET status=?,progress=1,log=?,updated_at=? WHERE id=?", (status, log, db.now(), job_id))
        db.audit(project_id, f"job.{status}", {"job_id": job_id, "kind": kind})

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def deliver(project_id: int, acknowledgements: list[str], name: str = "delivery", make_zip: bool = True) -> dict:
    if settings.DEMO:
        raise PermissionError("云端演示模式禁止生成交付包")
    if set(acknowledgements) != QA_ITEMS:
        raise PermissionError("必须完成全部四项人工质检，服务器才会生成交付包")
    p = project(project_id)
    source = safe_path(p["output_dir"], True)
    destination = safe_path(str(source.parent / name), False)
    destination.mkdir(parents=True, exist_ok=True)
    allowed = selected_stems(project_id)
    items: list[dict] = []
    for item in sorted(source.rglob("*.jpg")):
        if item.stem not in allowed:
            continue
        target = destination / item.name
        shutil.copy2(item, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        items.append({"file": item.name, "sha256": digest, "bytes": target.stat().st_size})
    if not items:
        raise ValueError("没有可交付成片：请检查选片状态与渲染输出")
    manifest = {"project": p["name"], "generated_at": db.now(), "count": len(items),
                "selection_mode": p["selection_mode"], "qa_acknowledgements": sorted(QA_ITEMS),
                "privacy_notice": "交付包已完成人工隐私、蒙版、曝光和水印复核。", "files": items}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = destination.with_suffix(".zip")
    if make_zip:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for item in sorted(destination.iterdir()):
                package.write(item, item.name)
    db.audit(project_id, "delivery.created", {"count": len(items), "path": str(destination)})
    return {**manifest, "delivery_dir": str(destination), "archive": str(archive) if make_zip else ""}
