import re
from pathlib import Path
from . import settings
SENSITIVE={".ssh",".aws",".git","appdata","secrets","credentials"}
def safe_path(raw,must_exist=False):
    if settings.DEMO:raise PermissionError("云端演示模式禁止访问用户文件系统")
    if not raw or "\x00" in raw:raise ValueError("路径不能为空")
    p=Path(raw).expanduser().resolve(strict=False)
    if {x.lower() for x in p.parts}&SENSITIVE:raise PermissionError("该路径属于敏感目录，已拒绝访问")
    if not any(p==r or r in p.parents for r in settings.ALLOWED_ROOTS):raise PermissionError("路径不在白名单内")
    if must_exist and not p.exists():raise FileNotFoundError(p)
    return p
def safe_stem(stem):
    if not re.fullmatch(r"[\w.-]{1,180}",stem,flags=re.UNICODE):raise ValueError("非法文件名")
    return stem
def public_project(p):
    x=dict(p)
    if settings.DEMO:
        for k in ("source_dir","edited_dir","analysis_dir","output_dir","watermark_path","manifest_path"):x[k]=""
    return x
