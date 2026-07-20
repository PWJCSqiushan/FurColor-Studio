# Engine packaging notice

`src/` contains the FurColor V3.3 local processing engine. Runtime assets are intentionally excluded:

- `models/*.onnx` — obtain and review the model/license separately;
- `config/face_memory.json` — private learned feedback;
- event manifests — may reveal file names and editing history;
- photos, annotations, analysis reports and delivery files.

Copy a compatible YuNet face detector to `models/face_detection_yunet_2023mar.onnx` before local analysis. Replace `config/manifest.example.json` with a project-specific manifest selected in the UI.
