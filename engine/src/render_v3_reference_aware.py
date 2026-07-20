from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import furcolor_cli as core
import quality_engine
from adaptive_eye_only import enhance_adaptive_eyes


def _config_from_argv():
    try:path=Path(sys.argv[sys.argv.index("--config")+1]).resolve()
    except (ValueError,IndexError):return None,None,None
    cfg=json.loads(path.read_text(encoding="utf-8"));return path,cfg,path.parent.parent


CONFIG_PATH,CFG,ROOT=_config_from_argv()
STATE={"target":None,"anchor":None}
_load_rgb=core.load_rgb
_apply_style=core.apply_anchor_style
_estimate=quality_engine.estimate_neutral_white
_apply_wb=quality_engine.apply_white_balance
_analyze=quality_engine.analyze_exposure
_manual_cache={}


def tracking_load(path,max_side=1600):
    result=_load_rgb(path,max_side)
    STATE["target"]=Path(path).stem
    return result


def sequence_style(rgb,anchor,strength):
    STATE["anchor"]=anchor.stem
    try:gap=abs(core.parse_number(STATE["target"])-core.parse_number(anchor.stem))
    except Exception:gap=999
    effective=max(strength,.94) if gap<=2 else (max(strength,.84) if gap<=5 else strength)
    STATE["sequence_gap"]=gap;STATE["style_strength_used"]=round(effective,3)
    return _apply_style(rgb,anchor,effective)


def _manual_path(stem):
    if not CFG:return None
    folder=Path(CFG["edited"])
    for ext in (".jpg",".JPG",".jpeg",".JPEG"):
        p=folder/f"{stem}{ext}"
        if p.exists():return p
    return None


def reference_estimate(rgb):
    current=_estimate(rgb);anchor=STATE.get("anchor");gap=STATE.get("sequence_gap",999)
    if not anchor or gap>3 or not current.get("found"):return current
    if anchor not in _manual_cache:
        p=_manual_path(anchor)
        _manual_cache[anchor]=_estimate(_load_rgb(p,1200)) if p else None
    desired=_manual_cache.get(anchor)
    if not desired or not desired.get("found"):return current
    c=np.asarray(current["neutral_rgb"],np.float32);d=np.asarray(desired["neutral_rgb"],np.float32)
    cr=c/max(float(c[1]),1e-4);dr=d/max(float(d[1]),1e-4);gains=np.clip(dr/np.maximum(cr,1e-4),.82,1.22)
    return {**current,"method":"adjacent_manual_reference_chroma","reference_anchor":anchor,"sequence_gap":gap,
            "reference_neutral_rgb":[round(float(x),4) for x in d],"gains":[round(float(x),4) for x in gains],
            "confidence":round(max(float(current.get("confidence",0)),.88),4),"style_strength_used":STATE.get("style_strength_used")}


def reference_white_balance(rgb,estimate,strength=1.0):
    if estimate.get("method")!="adjacent_manual_reference_chroma":return _apply_wb(rgb,estimate,strength)
    gains=np.asarray(estimate["gains"],np.float32);effective=min(.95,max(.65,float(CFG.get("reference_wb_strength",.9)) if CFG else .9))*strength
    gains=1+(gains-1)*effective;out=rgb.astype(np.float32)/255;out*=gains[None,None,:]
    return np.clip(out*255,0,255).astype(np.uint8)


def subject_safe_exposure(rgb):
    result=_analyze(rgb);scene=result["scene_tonality"];target=.91 if scene=="white_dominant" else (.82 if scene=="black_dominant" else .87)
    ev=math.log2(target/max(float(result["p95"]),.06))
    if float(result["p99"])>.975:ev-=min(.14,(float(result["p99"])-.975)*2.0)
    # Channel clipping is handled by the highlight shoulder, never by darkening the whole subject.
    if scene=="white_dominant" and float(result["p95"])<=target:ev=max(0.,ev)
    ev=float(np.clip(ev,-.48,.58));clip=float(result["highlight_clipped_ratio"]);near=float(result["near_clip_ratio"]);p99=float(result["p99"])
    highlight=max(float(result["highlight_compression"]),min(.30,clip*1.6+near*2.0+max(0.,p99-.94)*1.5))
    shadow=min(float(result["shadow_lift"]),.045 if scene=="black_dominant" else .065)
    result["recommended_ev"]=round(ev,4);result["highlight_compression"]=round(highlight,4);result["shadow_lift"]=round(shadow,4)
    result["exposure_method"]="subject_safe_p95_plus_highlight_shoulder"
    result["lightroom_equivalent"]["Exposure"]=round(ev,2);result["lightroom_equivalent"]["Highlights"]=round(-100*highlight,0);result["lightroom_equivalent"]["Shadows"]=round(min(32.,shadow*430),0)
    return result


core.load_rgb=tracking_load
core.apply_anchor_style=sequence_style
quality_engine.estimate_neutral_white=reference_estimate
quality_engine.apply_white_balance=reference_white_balance
quality_engine.analyze_exposure=subject_safe_exposure
quality_engine.enhance_eyes=enhance_adaptive_eyes

import render_drafts

if __name__=="__main__":raise SystemExit(render_drafts.main())
