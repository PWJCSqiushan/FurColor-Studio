import json
from pathlib import Path

import numpy as np

from engine.src import furcolor_cli


def test_build_anchors_accepts_arw_originals(tmp_path, monkeypatch):
    source = tmp_path / "source"
    edited = tmp_path / "edited"
    source.mkdir()
    edited.mkdir()
    (source / "DSC02010.ARW").write_bytes(b"raw")
    (edited / "DSC02010.jpg").write_bytes(b"jpeg")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "file": "DSC02010.ARW",
                        "edited_jpeg": "DSC02010.jpg",
                        "settings": {"Temperature": 4300},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seen: list[Path] = []

    def fake_load(path: Path, max_side: int = 1600):
        seen.append(path)
        return np.full((16, 16, 3), 128, dtype=np.uint8)

    monkeypatch.setattr(furcolor_cli, "load_rgb", fake_load)
    anchors = furcolor_cli.build_anchors(source, edited, manifest)

    assert [anchor.stem for anchor in anchors] == ["DSC02010"]
    assert seen == [source / "DSC02010.ARW", edited / "DSC02010.jpg"]
