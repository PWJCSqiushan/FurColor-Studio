from __future__ import annotations

import quality_engine

_base_analyze = quality_engine.analyze_exposure


def analyze_exposure_conservative(rgb):
    result = _base_analyze(rgb)
    # Global shadow lifting is deliberately conservative: without fur segmentation,
    # a stronger value would turn intentional black backgrounds and black suits gray.
    cap = 0.045 if result["scene_tonality"] == "black_dominant" else 0.065
    result["shadow_lift"] = round(min(float(result["shadow_lift"]), cap), 4)
    result["lightroom_equivalent"]["Shadows"] = round(min(32.0, result["shadow_lift"] * 430), 0)
    result["lightroom_equivalent"]["Blacks"] = (
        -8.0 if result["scene_tonality"] == "black_dominant" and result["shadow_crushed_ratio"] < 0.01
        else round(min(12.0, result["shadow_lift"] * 150), 0)
    )
    return result


quality_engine.analyze_exposure = analyze_exposure_conservative

import render_drafts

if __name__ == "__main__":
    raise SystemExit(render_drafts.main())
