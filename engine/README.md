# Engine packaging notice

`src/` contains the FurColor 4.0 local processing engine. The original FurColor core remains usable with the lightweight `.venv`; the optional Fursee subject job runs through `.venv-fursee` as a separate process.

Runtime assets are intentionally excluded:

- `models/*.onnx` — pinned YuNet is downloaded and verified locally;
- Fursee `cut.pt`, `model.safetensors` and configuration files — referenced from an external local directory, never copied into Git;
- `config/face_memory.json` — private learned feedback;
- `subject_analysis.json`, subject crops and `subject_embeddings.npz` — project-private derived data;
- event manifests, photos, annotations, analysis reports and delivery files.

Run `install_local.ps1` for the base engine. Run `install_fursee.ps1 -ModelDirectory <path>` only after obtaining and reviewing the Fursee model package and its licenses. The adapter performs fixed size/SHA-256 verification before inference.