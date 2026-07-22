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


def test_trusted_project_submission_authorizes_multiple_drives(monkeypatch):
    base = Path.cwd() / "runtime" / f"roots-form-test-{uuid.uuid4().hex}"
    source = base / "source"
    edited = base / "edited"
    analysis = base / "analysis-not-created-yet"
    output = base / "output-not-created-yet"
    data_dir = base / "private-runtime"
    for path in (source, edited, data_dir):
        path.mkdir(parents=True)
    try:
        monkeypatch.setenv("FURCOLOR_MODE", "local")
        monkeypatch.setenv("FURCOLOR_ALLOWED_ROOTS", "")
        monkeypatch.setenv("FURCOLOR_DATA_DIR", str(data_dir))
        from app import settings

        importlib.reload(settings)
        import app.security as security

        importlib.reload(security)
        security.authorize_project_paths(
            {
                "source_dir": str(source),
                "edited_dir": str(edited),
                "analysis_dir": str(analysis),
                "output_dir": str(output),
            }
        )
        assert security.safe_path(str(source), must_exist=True) == source.resolve()
        assert security.safe_path(str(analysis), must_exist=False) == analysis.resolve()
        assert security.safe_path(str(output), must_exist=False) == output.resolve()
        assert (data_dir / "authorized_roots.json").exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)

def test_scoped_delivery_folder_authorization(monkeypatch):
    base = Path.cwd() / "runtime" / f"delivery-roots-test-{uuid.uuid4().hex}"
    output = base / "drafts"
    data_dir = base / "private-runtime"
    output.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    try:
        monkeypatch.setenv("FURCOLOR_MODE", "local")
        monkeypatch.setenv("FURCOLOR_ALLOWED_ROOTS", str(output))
        monkeypatch.setenv("FURCOLOR_DATA_DIR", str(data_dir))
        from app import settings

        importlib.reload(settings)
        import app.security as security
        import app.services_core as services_core

        importlib.reload(security)
        importlib.reload(services_core)
        project = {
            "source_dir": str(base / "source"),
            "edited_dir": str(base / "edited"),
            "analysis_dir": str(base / "analysis"),
            "output_dir": str(output),
        }
        destination = services_core.delivery_destination(project, "delivery")
        with pytest.raises(PermissionError):
            security.safe_path(str(destination), must_exist=False)
        security.authorize_picker_path(str(destination), "directory", must_exist=False)
        assert security.safe_path(str(destination), must_exist=False) == destination
        assert destination.parent == output.parent
    finally:
        shutil.rmtree(base, ignore_errors=True)
