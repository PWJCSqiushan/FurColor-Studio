import json
import re
import threading
from pathlib import Path

from . import settings

SENSITIVE = {".ssh", ".aws", ".git", "appdata", "secrets", "credentials"}
_LOCK = threading.RLock()
_RUNTIME_ROOTS: set[Path] | None = None


def _is_sensitive(path: Path) -> bool:
    return bool({part.lower() for part in path.parts} & SENSITIVE)


def _store_path() -> Path:
    return settings.DATA_DIR / "authorized_roots.json"


def _load_runtime_roots() -> set[Path]:
    global _RUNTIME_ROOTS
    with _LOCK:
        if _RUNTIME_ROOTS is not None:
            return _RUNTIME_ROOTS
        roots: set[Path] = set()
        store = _store_path()
        try:
            values = json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
            for value in values:
                root = Path(value).expanduser().resolve(strict=False)
                if not _is_sensitive(root):
                    roots.add(root)
        except (OSError, ValueError, TypeError):
            roots = set()
        _RUNTIME_ROOTS = roots
        return roots


def authorized_roots() -> tuple[Path, ...]:
    values = (*settings.ALLOWED_ROOTS, settings.DATA_DIR, *_load_runtime_roots())
    unique: dict[str, Path] = {}
    for value in values:
        root = Path(value).expanduser().resolve(strict=False)
        unique[str(root).casefold()] = root
    return tuple(unique.values())


def authorize_picker_path(raw: str, kind: str, *, must_exist: bool = True) -> Path:
    if settings.DEMO:
        raise PermissionError("Cloud demo mode cannot authorize local paths")
    if kind not in {"directory", "watermark", "manifest"}:
        raise ValueError("Unknown picker type")
    if not raw or "\x00" in raw:
        raise ValueError("No path was selected")
    selected = Path(raw).expanduser().resolve(strict=must_exist)
    root = selected.parent if kind in {"watermark", "manifest"} else selected
    if _is_sensitive(root):
        raise PermissionError("Sensitive directory access denied")
    with _LOCK:
        roots = _load_runtime_roots()
        roots.add(root)
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        store = _store_path()
        temporary = store.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(sorted(str(path) for path in roots), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(store)
    return root


def authorize_project_paths(values: dict[str, str]) -> tuple[Path, ...]:
    """Authorize paths submitted by the trusted local UI."""
    if settings.DEMO:
        raise PermissionError("Cloud mode cannot authorize local paths")
    authorized: list[Path] = []
    for key in ("source_dir", "edited_dir", "analysis_dir", "output_dir"):
        raw = str(values.get(key, "")).strip()
        if raw:
            authorized.append(
                authorize_picker_path(
                    raw,
                    "directory",
                    must_exist=key in {"source_dir", "edited_dir"},
                )
            )
    for key, kind in (("watermark_path", "watermark"), ("manifest_path", "manifest")):
        raw = str(values.get(key, "")).strip()
        if raw:
            authorized.append(authorize_picker_path(raw, kind, must_exist=True))
    return tuple(authorized)


def safe_path(raw: str, must_exist: bool = False) -> Path:
    if settings.DEMO:
        raise PermissionError("Cloud demo mode cannot access the user filesystem")
    if not raw or "\x00" in raw:
        raise ValueError("Path cannot be empty")
    path = Path(raw).expanduser().resolve(strict=False)
    if _is_sensitive(path):
        raise PermissionError("Sensitive directory access denied")
    if not any(path == root or root in path.parents for root in authorized_roots()):
        raise PermissionError(
            "Path is not authorized. Use the Browse button once for this folder, "
            "or add its root to FURCOLOR_ALLOWED_ROOTS."
        )
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def safe_stem(stem: str) -> str:
    if not re.fullmatch(r"[\w.-]{1,180}", stem, flags=re.UNICODE):
        raise ValueError("Invalid filename")
    return stem


def public_project(project):
    value = dict(project)
    if settings.DEMO:
        for key in ("source_dir", "edited_dir", "analysis_dir", "output_dir", "watermark_path", "manifest_path"):
            value[key] = ""
    return value
