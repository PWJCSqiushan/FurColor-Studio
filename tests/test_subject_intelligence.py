from pathlib import Path
import sys

import numpy as np

SRC = Path(__file__).resolve().parents[1] / "engine" / "src"
sys.path.insert(0, str(SRC))

from quality_engine import analyze_exposure, analyze_subject_exposure, apply_subject_exposure_tone
from subject_intelligence import (
    box_intersection_fraction, cluster_embeddings, fuse_subject_face_evidence, scale_detections,
)


def test_box_scaling_and_containment_fraction():
    box = {"x": 10, "y": 20, "w": 30, "h": 40, "score": 0.9}
    scaled = scale_detections([box], [100, 100], (200, 300, 3))[0]
    assert (scaled["x"], scaled["y"], scaled["w"], scaled["h"]) == (30, 40, 90, 80)
    assert box_intersection_fraction({"x": 20, "y": 30, "w": 5, "h": 5}, box) == 1.0


def test_embedding_clusters_are_anonymous_and_stable():
    vectors = np.asarray([
        [1.0, 0.0, 0.0], [0.999, 0.02, 0.0],
        [0.0, 1.0, 0.0], [0.02, 0.999, 0.0],
    ], dtype=np.float32)
    result = cluster_embeddings(["b:0", "a:0", "d:0", "c:0"], vectors)
    assert result["labels"] == ["C001", "C001", "C002", "C002"]
    assert [cluster["id"] for cluster in result["clusters"]] == ["C001", "C002"]


def test_subject_exposure_lifts_dark_head_conservatively():
    rgb = np.full((160, 220, 3), 125, dtype=np.uint8)
    rgb[45:115, 75:145] = 32
    boxes = [{"x": 75, "y": 45, "w": 70, "h": 70, "score": 0.95, "index": 0}]
    global_analysis = analyze_exposure(rgb)
    subjects = analyze_subject_exposure(rgb, boxes, global_analysis)
    assert subjects and 0 < subjects[0]["recommended_delta_ev"] <= 0.38
    corrected = apply_subject_exposure_tone(rgb, subjects)
    assert corrected[65:95, 95:125].mean() > rgb[65:95, 95:125].mean()
    assert abs(float(corrected[:20, :20].mean()) - float(rgb[:20, :20].mean())) < 1.0

def test_subject_evidence_suppresses_ear_false_positive_only_with_strong_agreement():
    yunet = [{
        "x": 20, "y": 20, "w": 12, "h": 12, "score": 0.9,
        "severity": "review", "landmark_geometry": 0.30, "memory_probability": 0.20,
    }]
    fursuits = [{"x": 0, "y": 0, "w": 100, "h": 100, "score": 0.92}]
    result = fuse_subject_face_evidence(yunet, fursuits, [])
    assert result[0]["suppressed_by_subject"] is True
    assert result[0]["auto_privacy_allowed"] is False


def test_fursee_face_corroboration_restores_manual_review_but_never_auto_blur():
    yunet = [{
        "x": 20, "y": 20, "w": 12, "h": 12, "score": 0.7,
        "severity": "review", "landmark_geometry": 0.30, "memory_probability": 0.20,
    }]
    fursuits = [{"x": 0, "y": 0, "w": 100, "h": 100, "score": 0.92}]
    fursee_face = [{"x": 19, "y": 19, "w": 14, "h": 14, "score": 0.88}]
    result = fuse_subject_face_evidence(yunet, fursuits, fursee_face)
    assert len(result) == 1
    assert result[0]["suppressed_by_geometry"] is False
    assert result[0]["suppressed_by_subject"] is False
    assert result[0]["severity"] == "review"
    assert result[0]["auto_privacy_allowed"] is False


def test_fursee_only_face_is_a_non_blurring_review_candidate():
    result = fuse_subject_face_evidence([], [], [{"x": 2, "y": 3, "w": 8, "h": 9, "score": 0.81}])
    assert result[0]["source"] == "fursee_face"
    assert result[0]["severity"] == "review"
    assert result[0]["auto_privacy_allowed"] is False

def test_subject_exposure_protects_near_clipped_white_fur():
    rgb = np.full((160, 220, 3), 120, dtype=np.uint8)
    rgb[45:115, 75:145] = 252
    boxes = [{"x": 75, "y": 45, "w": 70, "h": 70, "score": 0.96, "index": 0}]
    global_analysis = analyze_exposure(rgb)
    subjects = analyze_subject_exposure(rgb, boxes, global_analysis)
    assert subjects[0]["recommended_delta_ev"] <= -0.10
    corrected = apply_subject_exposure_tone(rgb, subjects)
    assert corrected[65:95, 95:125].mean() < rgb[65:95, 95:125].mean()
    assert abs(float(corrected[:20, :20].mean()) - float(rgb[:20, :20].mean())) < 1.0
