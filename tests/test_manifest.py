import importlib,json,shutil,uuid
from pathlib import Path

def test_automatic_reference_manifest(monkeypatch):
    root=Path.cwd()/"runtime"/f"manifest-test-{uuid.uuid4().hex}"
    try:
        source=root/"source";edited=root/"edited";analysis=root/"analysis";output=root/"output"
        for path in (source,edited,analysis,output):path.mkdir(parents=True)
        (source/"DSC0001.ARW").write_bytes(b"raw-placeholder")
        (edited/"DSC0001.jpg").write_bytes(b"jpg-placeholder")
        monkeypatch.setenv("FURCOLOR_MODE","local");monkeypatch.setenv("FURCOLOR_ALLOWED_ROOTS",str(root));monkeypatch.setenv("FURCOLOR_DATA_DIR",str(root/"private_runtime"))
        from app import settings,db,services
        importlib.reload(settings);importlib.reload(db)
        import app.security as security;importlib.reload(security)
        import app.services_core as services_core;importlib.reload(services_core);importlib.reload(services)
        db.init()
        pid=services.create_project({"name":"auto manifest","source_dir":str(source),"edited_dir":str(edited),"analysis_dir":str(analysis),"output_dir":str(output),"watermark_path":"","manifest_path":"","selection_mode":"negative"})
        project=db.one("SELECT * FROM projects WHERE id=?",(pid,));manifest=Path(project["manifest_path"])
        data=json.loads(manifest.read_text(encoding="utf-8"))
        assert data["count"]==1
        assert data["items"][0]["file"]=="DSC0001.ARW"
        assert data["items"][0]["edited_jpeg"]=="DSC0001.jpg"
    finally:
        shutil.rmtree(root,ignore_errors=True)
