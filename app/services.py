from pathlib import Path
from . import db, settings
from .security import safe_path
from . import services_core as core
from .services_core import *

def create_project(data: dict) -> int:
    required=("source_dir","edited_dir","analysis_dir","output_dir","manifest_path")
    missing=[key for key in required if not str(data.get(key,"" )).strip()]
    if missing: raise ValueError("缺少必要字段："+", ".join(missing))
    source=safe_path(data["source_dir"],True);edited=safe_path(data["edited_dir"],True)
    analysis=safe_path(data["analysis_dir"],False);output=safe_path(data["output_dir"],False)
    manifest=safe_path(data["manifest_path"],True)
    if not source.is_dir() or not edited.is_dir(): raise ValueError("原片目录和手修参考目录必须是文件夹")
    if manifest.suffix.lower()!=".json": raise ValueError("参考样片清单必须是 JSON 文件")
    if any(path==source or source in path.parents or path in source.parents for path in (analysis,output)):
        raise ValueError("分析/输出目录必须与原片目录完全分离，防止覆盖或重复扫描")
    watermark=str(data.get("watermark_path","")).strip()
    if watermark and safe_path(watermark,True).suffix.lower()!=".png": raise ValueError("水印必须是 PNG 文件")
    return core.create_project(data)

def start_job(project_id: int, kind: str) -> int:
    if not selected_stems(project_id): raise ValueError("当前没有有效选片，不能启动处理")
    running=db.one("SELECT id FROM jobs WHERE project_id=? AND kind=? AND status IN ('queued','running')",(project_id,kind))
    if running: raise RuntimeError(f"同类任务 #{running['id']} 仍在运行")
    p=project(project_id)
    if kind=="analyze":
        model=settings.ENGINE_ROOT/"models"/"face_detection_yunet_2023mar.onnx"
        if not model.exists(): raise FileNotFoundError(f"缺少人脸模型：{model}")
        if not Path(p["manifest_path"]).exists(): raise FileNotFoundError("参考样片清单不存在")
    if kind in {"face-review","eye-review","render"}:
        recipes=Path(p["analysis_dir"])/"recipes"
        if not recipes.exists() or not any(recipes.glob("*.json")): raise FileNotFoundError("尚无分析配方，请先完成步骤 01")
    return core.start_job(project_id,kind)
