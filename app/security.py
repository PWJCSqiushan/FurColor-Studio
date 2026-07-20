import re
from pathlib import Path
from . import settings
SENSITIVE={".ssh",".aws",".git","appdata","secrets","credentials"}
def safe_path(raw,must_exist=False):
    if settings.DEMO:raise PermissionError("Cloud demo mode cannot access the user filesystem")
    if not raw or "\x00" in raw:raise ValueError("Path cannot be empty")
    p=Path(raw).expanduser().resolve(strict=False)
    if {x.lower() for x in p.parts}&SENSITIVE:raise PermissionError("Sensitive directory access denied")
    roots=(*settings.ALLOWED_ROOTS,settings.DATA_DIR)
    if not any(p==r or r in p.parents for r in roots):raise PermissionError("Path is outside FURCOLOR_ALLOWED_ROOTS")
    if must_exist and not p.exists():raise FileNotFoundError(p)
    return p
def safe_stem(stem):
    if not re.fullmatch(r"[\w.-]{1,180}",stem,flags=re.UNICODE):raise ValueError("Invalid filename")
    return stem
def public_project(p):
    x=dict(p)
    if settings.DEMO:
        for k in ("source_dir","edited_dir","analysis_dir","output_dir","watermark_path","manifest_path"):x[k]=""
    return x
