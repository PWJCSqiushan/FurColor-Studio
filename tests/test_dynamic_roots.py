import importlib
import shutil
import uuid
from pathlib import Path

import pytest


def test_native_picker_authorization_is_persistent_and_limited(monkeypatch):
    base = Path.cwd() / "runtime" / f"roots-test-{uuid.uuid4().hex}"
    configured = base / "configured"
    external = base / "external-drive" / "event"
    sensitive = base / ".ssh"
    data_dir = base / "private-runtime"
    for path in (configured, external, sensitive, data_dir):
        path.mkdir(parents=True)
    try:
        monkeypatch.setenv("FURCOLOR_MODE", "local")
        monkeypatch.setenv("FURCOLOR_ALLOWED_ROOTS", str(configured))
        monkeypatch.setenv("FURCOLOR_DATA_DIR", str(data_dir))
        from app import settings

        importlib.reload(settings)
        import app.security as security

        importlib.reload(security)
        with pytest.raises(PermissionError):
            security.safe_path(str(external), must_exist=True)
        assert security.authorize_picker_path(str(external), "directory") == external.resolve()
        assert security.safe_path(str(external), must_exist=True) == external.resolve()
        security._RUNTIME_ROOTS = None
        assert external.resolve() in security.authorized_roots()
        with pytest.raises(PermissionError):
            security.authorize_picker_path(str(sensitive), "directory")
    finally:
        shutil.rmtree(base, ignore_errors=True)
