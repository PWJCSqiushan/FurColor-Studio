from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "engine" / "src"
sys.path.insert(0, str(SRC))

from selection_cli import selected_stems


def test_selection_accepts_windows_utf8_bom(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text('{"version":1,"mode":"negative","choices":{"reject":"reject"}}', encoding="utf-8-sig")
    assert selected_stems(path, ["keep", "reject"]) == {"keep"}