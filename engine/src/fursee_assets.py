from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = ("cut.pt", "model.safetensors", "config.json", "preprocessor_config.json")


def resolve_model_dir(raw: str | Path) -> Path:
    """Resolve either the model directory itself or a package containing it."""
    if not str(raw).strip():
        raise ValueError("FURCOLOR_FURSEE_MODEL_DIR is not configured")
    candidate = Path(raw).expanduser().resolve(strict=False)
    choices = [candidate, candidate / "fursee_models"]
    if candidate.is_dir():
        for marker in candidate.rglob("cut.pt"):
            try:
                depth = len(marker.parent.relative_to(candidate).parts)
            except ValueError:
                continue
            if depth <= 4:
                choices.append(marker.parent)
    unique = sorted(
        {choice.resolve(strict=False) for choice in choices},
        key=lambda path: (len(path.relative_to(candidate).parts) if path != candidate else 0, str(path).casefold()),
    )
    for choice in unique:
        if all((choice / name).is_file() for name in REQUIRED_FILES):
            return choice.resolve()
    raise FileNotFoundError(
        f"Fursee model files were not found under {candidate}. Expected: "
        + ", ".join(REQUIRED_FILES)
    )


def load_manifest(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value.get("files"), dict):
        raise ValueError("Invalid Fursee model manifest")
    return value


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_assets(
    model_root: str | Path,
    manifest_path: str | Path,
    *,
    verify_hashes: bool = False,
) -> dict[str, Any]:
    try:
        model_dir = resolve_model_dir(model_root)
        manifest = load_manifest(manifest_path)
        files: dict[str, dict[str, Any]] = {}
        for name, expected in manifest["files"].items():
            path = model_dir / name
            actual_size = path.stat().st_size if path.is_file() else None
            size_ok = actual_size == int(expected["bytes"])
            item: dict[str, Any] = {
                "path": str(path),
                "exists": path.is_file(),
                "bytes": actual_size,
                "size_ok": size_ok,
                "hash_ok": None,
            }
            if verify_hashes and size_ok:
                item["sha256"] = sha256_file(path)
                item["hash_ok"] = item["sha256"].casefold() == str(expected["sha256"]).casefold()
            files[name] = item
        ready = all(
            item["exists"] and item["size_ok"] and (item["hash_ok"] is not False)
            for item in files.values()
        )
        return {
            "configured": True,
            "ready": ready,
            "verified": verify_hashes and ready,
            "model_dir": str(model_dir),
            "model": manifest.get("model", "Fursee"),
            "upstream_commit": manifest.get("upstream_commit", ""),
            "files": files,
            "error": "",
        }
    except (OSError, ValueError, TypeError) as exc:
        return {
            "configured": bool(str(model_root).strip()),
            "ready": False,
            "verified": False,
            "model_dir": "",
            "files": {},
            "error": str(exc),
        }


def require_verified_assets(model_root: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    status = inspect_assets(model_root, manifest_path, verify_hashes=True)
    if not status["ready"]:
        raise RuntimeError(status["error"] or "Fursee model verification failed")
    failures = [name for name, item in status["files"].items() if item["hash_ok"] is not True]
    if failures:
        raise RuntimeError("Fursee SHA-256 verification failed: " + ", ".join(failures))
    return status
