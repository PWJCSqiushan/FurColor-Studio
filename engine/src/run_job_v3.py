from __future__ import annotations

# Keep the tiny online calibrator advisory until it has enough diverse labels.
# Strong YuNet + skin + landmark evidence still wins for privacy safety.
import face_memory

_original_apply_memory = face_memory.apply_memory


def safety_fused_memory(rgb, faces, model):
    learned = _original_apply_memory(rgb, faces, model)
    for face in learned:
        strong_human_evidence = (
            float(face.get("score", 0)) >= 0.76
            and float(face.get("skin_ratio", 0)) >= 0.045
            and float(face.get("landmark_geometry", 0)) >= 0.58
        )
        if strong_human_evidence and not face.get("suppressed_by_memory", False):
            face["severity"] = "high"
            face["memory_role"] = "advisory_overridden_by_strong_human_geometry"
    return learned


face_memory.apply_memory = safety_fused_memory

import run_job

if __name__ == "__main__":
    raise SystemExit(run_job.main())
