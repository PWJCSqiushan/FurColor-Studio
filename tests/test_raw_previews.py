from pathlib import Path

import numpy as np
from PIL import Image

from app import services_core


def test_thumbnail_uses_shared_decoder_for_arw(tmp_path, monkeypatch):
    source = tmp_path / "DSC01963.ARW"
    source.write_bytes(b"raw-placeholder")
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(services_core.settings, "DATA_DIR", runtime)
    monkeypatch.setattr(services_core, "safe_path", lambda raw, must_exist=False: Path(raw))
    monkeypatch.setattr(
        services_core.db,
        "one",
        lambda sql, params=(): {"source_path": str(source)},
    )
    seen = []

    def fake_load(path: Path, max_side: int):
        seen.append((path, max_side))
        return np.full((40, 60, 3), 127, dtype=np.uint8)

    monkeypatch.setattr(services_core.image_core, "load_rgb", fake_load)
    result = services_core.thumbnail(12, "DSC01963")

    assert seen == [(source, 640)]
    assert result.is_file()
    with Image.open(result) as preview:
        assert preview.format == "JPEG"
        assert preview.size == (60, 40)
