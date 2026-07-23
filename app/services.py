import json,re,uuid
from pathlib import Path
from . import db,settings
from .security import safe_path
from . import services_core as core
from .services_core import *

DEFAULT_SETTINGS={"CameraProfile":"Adobe Standard","Temperature":4300,"Tint":5,"Exposure2012":0.0,"Highlights2012":-30,"Shadows2012":10,"Whites2012":5,"Blacks2012":-5,"Texture":10,"Clarity2012":3,"Dehaze":2,"Vibrance":5,"Saturation":0}
def _source_for_stem(source:Path,stem:str):
    for ext in (".ARW",".arw",".JPG",".jpg",".JPEG",".jpeg"):
        candidate=source/f"{stem}{ext}"
        if candidate.exists():return candidate
    return None
def build_reference_manifest(source:Path,edited:Path,target:Path)->Path:
    items=[]
    references=sorted(p for p in edited.iterdir() if p.is_file() and p.suffix.lower() in {".jpg",".jpeg"})
    for jpg in references:
        original=_source_for_stem(source,jpg.stem)
        if original:items.append({"file":original.name,"edited_jpeg":jpg.name,"has_masks":False,"has_ai_masks":False,"has_retouch":False,"settings":dict(DEFAULT_SETTINGS)})
    if not items:raise ValueError("No matching reference pair found. Edited JPG and source photo must share the same filename stem.")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({"version":1,"generated_by":"FurColor Studio","count":len(items),"items":items},ensure_ascii=False,indent=2),encoding="utf-8")
    return target
def _validate_manifest(path:Path)->None:
    data=json.loads(path.read_text(encoding="utf-8"));items=data.get("items",data if isinstance(data,list) else [])
    if not items:raise ValueError("Reference manifest contains no items")
    if any("file" not in item for item in items):raise ValueError("Every reference manifest item needs a file field")
def create_project(data:dict)->int:
    required=("source_dir","edited_dir","analysis_dir","output_dir")
    missing=[key for key in required if not str(data.get(key,"" )).strip()]
    if missing:raise ValueError("Missing required fields: "+", ".join(missing))
    source=safe_path(data["source_dir"],True);edited=safe_path(data["edited_dir"],True)
    analysis=safe_path(data["analysis_dir"],False);output=safe_path(data["output_dir"],False)
    if not source.is_dir() or not edited.is_dir():raise ValueError("Source and edited reference paths must be folders")
    if any(path==source or source in path.parents or path in source.parents for path in (analysis,output)):raise ValueError("Analysis/output folders must be separate from the source folder")
    prepared=dict(data);manifest_raw=str(data.get("manifest_path","")).strip()
    if manifest_raw:
        manifest=safe_path(manifest_raw,True)
        if manifest.suffix.lower()!=".json":raise ValueError("Reference manifest must be a JSON file")
        _validate_manifest(manifest)
    else:
        slug=re.sub(r"[^\w.-]+","-",str(data.get("name","project")),flags=re.UNICODE).strip("-") or "project"
        manifest=settings.DATA_DIR/"generated_manifests"/f"{slug}-{uuid.uuid4().hex[:8]}.json"
        build_reference_manifest(source,edited,manifest);prepared["manifest_path"]=str(manifest)
    watermark=str(data.get("watermark_path","")).strip()
    if watermark and safe_path(watermark,True).suffix.lower()!=".png":raise ValueError("Watermark must be a PNG file")
    return core.create_project(prepared)
def start_job(project_id:int,kind:str)->int:
    if not selected_stems(project_id):raise ValueError("No selected photos are available for processing")
    running=db.one("SELECT id FROM jobs WHERE project_id=? AND kind=? AND status IN ('queued','running')",(project_id,kind))
    if running:raise RuntimeError(f"Job #{running['id']} of this type is still running")
    p=project(project_id)
    if kind=="subject":
        status=core.subject_status()
        if not status.get("ready"):
            raise FileNotFoundError(status.get("error") or "Fursee model files are missing or incomplete")
        if not status.get("python_ready"):
            raise FileNotFoundError("Fursee Python environment is missing. Run install_fursee.ps1 first.")
    if kind=="analyze":
        model=settings.ENGINE_ROOT/"models"/"face_detection_yunet_2023mar.onnx"
        if not model.exists():raise FileNotFoundError(f"Face model missing: {model}")
        if not Path(p["manifest_path"]).exists():raise FileNotFoundError("Reference manifest is missing")
    if kind in {"face-review","eye-review","render"}:
        recipes=Path(p["analysis_dir"])/"recipes"
        if not recipes.exists() or not any(recipes.glob("*.json")):raise FileNotFoundError("No analysis recipes found. Complete step 01 first.")
    return core.start_job(project_id,kind)
