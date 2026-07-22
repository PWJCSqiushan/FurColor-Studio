import importlib,json,shutil,uuid
from pathlib import Path
import pytest
def test_selection_semantics_delivery_gate_and_path_isolation(monkeypatch):
    root=Path.cwd()/"runtime"/f"test-{uuid.uuid4().hex}"
    try:
        source=root/"source";edited=root/"edited";analysis=root/"analysis";output=root/"output"
        for path in (source,edited,analysis,output):path.mkdir(parents=True)
        manifest=root/"manifest.json";manifest.write_text(json.dumps({"items":[{"file":"keep_me.jpg"}]}),encoding="utf-8")
        monkeypatch.setenv("FURCOLOR_MODE","local");monkeypatch.setenv("FURCOLOR_ALLOWED_ROOTS",str(root));monkeypatch.setenv("FURCOLOR_DATA_DIR",str(root/"private_runtime"))
        from app import settings,db,services
        importlib.reload(settings);importlib.reload(db)
        import app.security as security;importlib.reload(security)
        import app.services_core as services_core;importlib.reload(services_core);importlib.reload(services)
        db.init();pid=services.create_project({"name":"test","source_dir":str(source),"edited_dir":str(edited),"analysis_dir":str(analysis),"output_dir":str(output),"watermark_path":"","manifest_path":str(manifest),"selection_mode":"positive"})
        for stem,state in (("keep_me","keep"),("default_me","unset"),("reject_me","reject")):
            db.run("INSERT INTO photos(project_id,stem,source_path,selection) VALUES(?,?,?,?)",(pid,stem,str(source/f"{stem}.jpg"),state));(output/f"{stem}.jpg").write_bytes(stem.encode())
        assert services.selected_stems(pid)=={"keep_me"}
        with pytest.raises(PermissionError):services.deliver(pid,["privacy"])
        db.run("UPDATE projects SET selection_mode='negative' WHERE id=?",(pid,));assert services.selected_stems(pid)=={"keep_me","default_me"}
        result=services.deliver(pid,["privacy","mask","exposure","watermark"],"delivery_test")
        assert result["count"]==2;assert {x["file"] for x in result["files"]}=={"keep_me.jpg","default_me.jpg"}
        with pytest.raises(ValueError):services.delivery_destination(services.project(pid),"..")
        with pytest.raises(ValueError):services.delivery_destination(services.project(pid),output.name)
        with pytest.raises(PermissionError):security.safe_path(str(Path.cwd().parent/"outside"),False)
    finally:shutil.rmtree(root,ignore_errors=True)
