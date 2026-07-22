import hashlib
import json
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "engine" / "src"
sys.path.insert(0, str(SRC))

from fursee_assets import REQUIRED_FILES, inspect_assets, require_verified_assets


def write_package(root: Path):
    model = root / "fursee_models"
    model.mkdir(parents=True)
    files = {}
    for index, name in enumerate(REQUIRED_FILES, 1):
        data = (name.encode("utf-8") + bytes([index])) * 3
        (model / name).write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"model": "test", "upstream_commit": "abc", "files": files}), encoding="utf-8")
    return model, manifest


def test_nested_model_directory_and_hash_verification(tmp_path):
    model, manifest = write_package(tmp_path)
    status = inspect_assets(tmp_path, manifest, verify_hashes=True)
    assert status["ready"] is True
    assert status["verified"] is True
    assert Path(status["model_dir"]) == model.resolve()
    assert require_verified_assets(tmp_path, manifest)["model"] == "test"


def test_hash_mismatch_is_rejected(tmp_path):
    model, manifest = write_package(tmp_path)
    original = (model / "cut.pt").read_bytes()
    (model / "cut.pt").write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
    status = inspect_assets(tmp_path, manifest, verify_hashes=True)
    assert status["ready"] is False