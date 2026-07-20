from __future__ import annotations

# The online model stays advisory while the labeled set is small. Auto privacy needs
# both strong geometric evidence and at least a moderate learned-human probability.
import face_memory

_original_apply_memory = face_memory.apply_memory


def safety_fused_memory(rgb, faces, model):
    learned = _original_apply_memory(rgb, faces, model)
    for face in learned:
        probability = face.get("memory_probability")
        learned_support = probability is None or float(probability) >= 0.45
        strong_human_evidence = (
            float(face.get("score", 0)) >= 0.76
            and float(face.get("skin_ratio", 0)) >= 0.045
            and float(face.get("landmark_geometry", 0)) >= 0.58
            and learned_support
        )
        if strong_human_evidence and not face.get("suppressed_by_memory", False):
            face["severity"] = "high"
            face["memory_role"] = "moderate_learned_support_plus_strong_human_geometry"
    return learned


face_memory.apply_memory = safety_fused_memory

import run_job

if __name__ == "__main__":
    raise SystemExit(run_job.main())
