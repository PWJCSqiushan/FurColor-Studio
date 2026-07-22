import json
from pathlib import Path

from app import services_core
from engine.src.run_subject_job import project_private_target


def test_subject_summary_crop_and_cluster_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(services_core.settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(services_core, "project", lambda project_id: {"id": project_id})
    runtime = tmp_path / "projects" / "7"
    crops = runtime / "subject_crops"
    crops.mkdir(parents=True)
    (crops / "A_0.jpg").write_bytes(b"jpeg")
    report = {
        "version": 1,
        "images": {"A": {"fursuits": [{"index": 0, "cluster_id": "C001"}]}},
        "clusters": [{
            "id": "C001", "image_stems": ["A", "B", "A"],
            "representative": {"stem": "A", "index": 0},
        }],
    }
    (runtime / "subject_analysis.json").write_text(json.dumps(report), encoding="utf-8")
    updates = []
    audits = []
    monkeypatch.setattr(services_core.db, "run", lambda sql, params=(): updates.append((sql, params)) or 1)
    monkeypatch.setattr(services_core.db, "audit", lambda *args: audits.append(args))

    summary = services_core.subject_summary(7)
    assert summary["ready"] is True
    assert services_core.subject_crop(7, "A", 0) == crops / "A_0.jpg"
    assert services_core.set_cluster_selection(7, "C001", "reject") == 2
    assert [entry[1][0] for entry in updates] == ["reject", "reject"]
    assert {entry[1][2] for entry in updates} == {"A", "B"}
    assert audits and audits[0][1] == "selection.cluster_changed"

def test_subject_private_outputs_cannot_escape_project_runtime(tmp_path):
    runtime = tmp_path / "project"
    runtime.mkdir()
    assert project_private_target(runtime / "subject_analysis.json", runtime) == (runtime / "subject_analysis.json").resolve()
    assert project_private_target(runtime / "subject_crops", runtime, directory=True) == (runtime / "subject_crops").resolve()
    import pytest
    with pytest.raises(ValueError):
        project_private_target(tmp_path / "outside.json", runtime)
    with pytest.raises(ValueError):
        project_private_target(runtime / "nested" / "subject_embeddings.npz", runtime)
