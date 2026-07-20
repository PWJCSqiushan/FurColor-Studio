from __future__ import annotations

import numpy as np

import render_v3_reference_aware as reference


if reference.CFG is not None:
    # Close adjacent manual references are treated as the venue/scene white-balance ground truth.
    reference.CFG["reference_wb_strength"] = max(float(reference.CFG.get("reference_wb_strength", 0.9)), 1.0)

_tone = reference.render_drafts.apply_exposure_tone


def highlight_chroma_safe_tone(rgb, analysis):
    out = _tone(rgb, analysis)
    arr = out.astype(np.float32) / 255.0
    luma = 0.2126*arr[:, :, 0] + 0.7152*arr[:, :, 1] + 0.0722*arr[:, :, 2]
    peak = arr.max(axis=2)
    # Bright white fur often clips one warm channel before luminance itself is overexposed.
    # Desaturating only the near-white shoulder preserves luminance and texture without
    # darkening the head or affecting saturated blue eyes in the midtones.
    weight = np.clip((peak-0.94)/0.06, 0.0, 1.0) * np.clip((luma-0.62)/0.20, 0.0, 1.0) * 0.72
    arr = arr*(1.0-weight[:, :, None]) + luma[:, :, None]*weight[:, :, None]
    peak2 = arr.max(axis=2)
    scale = np.minimum(1.0, 0.988/np.maximum(peak2, 1e-6))
    arr *= scale[:, :, None]
    return np.clip(arr*255.0, 0, 255).astype(np.uint8)


reference.render_drafts.apply_exposure_tone = highlight_chroma_safe_tone

if __name__ == "__main__":
    raise SystemExit(reference.render_drafts.main())
