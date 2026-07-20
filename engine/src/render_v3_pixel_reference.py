from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

import render_v3_reference_final as final

reference=final.reference
_cache={}


def _source_path(stem):
    folder=Path(reference.CFG["source"])
    for ext in (".JPG",".jpg",".JPEG",".jpeg",".ARW",".arw"):
        path=folder/f"{stem}{ext}"
        if path.exists():return path
    return None


def _features(x):
    r,g,b=x[:,0],x[:,1],x[:,2]
    return np.column_stack((np.ones(len(x)),r,g,b,r*r,g*g,b*b,r*g,r*b,g*b,r*r*r,g*g*g,b*b*b))


def _fit_transform(original,edited):
    portrait=original.shape[0]>original.shape[1];size=(300,450) if portrait else (450,300)
    a=cv2.resize(original,size,interpolation=cv2.INTER_AREA).astype(np.float64)/255
    e=cv2.resize(edited,size,interpolation=cv2.INTER_AREA).astype(np.float64)/255
    gray_a=.2126*a[:,:,0]+.7152*a[:,:,1]+.0722*a[:,:,2];gray_e=.2126*e[:,:,0]+.7152*e[:,:,1]+.0722*e[:,:,2]
    correlation=float(np.corrcoef(gray_a.ravel(),gray_e.ravel())[0,1])
    x=a.reshape(-1,3);y=e.reshape(-1,3);X=_features(x);weights=np.ones(len(x));ridge=np.eye(X.shape[1])*2e-3;ridge[0,0]=1e-6
    coef=np.zeros((X.shape[1],3))
    for _ in range(4):
        WX=X*weights[:,None];coef=np.linalg.solve(X.T@WX+ridge,X.T@(y*weights[:,None]));res=np.linalg.norm(np.clip(X@coef,0,1)-y,axis=1);delta=max(float(np.percentile(res,62)),.015);weights=np.minimum(1.,delta/np.maximum(res,1e-6))
    residual=np.linalg.norm(np.clip(X@coef,0,1)-y,axis=1)
    return {"coef":coef,"correlation":correlation,"median_error":float(np.median(residual)),"p90_error":float(np.percentile(residual,90))}


def _profile(stem):
    if stem in _cache:return _cache[stem]
    op=_source_path(stem);ep=reference._manual_path(stem)
    if not op or not ep:_cache[stem]=None;return None
    original=reference._load_rgb(op,1400);edited=reference._load_rgb(ep,1400);fit=_fit_transform(original,edited);exposure=reference._analyze(edited)
    fit.update({"edited_p50":float(exposure["p50"]),"edited_p95":float(exposure["p95"]),"edited_p99":float(exposure["p99"])})
    fit["valid"]=fit["correlation"]>=.72 and fit["median_error"]<=.13
    _cache[stem]=fit;return fit


def _apply_polynomial(rgb,coef):
    h,w=rgb.shape[:2];out=np.empty_like(rgb);chunk=320
    for y0 in range(0,h,chunk):
        block=rgb[y0:y0+chunk].astype(np.float64).reshape(-1,3)/255;pred=np.clip(_features(block)@coef,0,1)
        out[y0:y0+chunk]=np.round(pred.reshape(min(chunk,h-y0),w,3)*255).astype(np.uint8)
    return out


def pixel_reference_style(rgb,anchor,strength):
    reference.STATE["anchor"]=anchor.stem
    try:gap=abs(reference.core.parse_number(reference.STATE["target"])-reference.core.parse_number(anchor.stem))
    except Exception:gap=999
    reference.STATE["sequence_gap"]=gap;profile=_profile(anchor.stem) if gap<=3 else None
    if not profile or not profile["valid"]:
        reference.STATE["style_strength_used"]=round(strength,3);reference.STATE["pixel_reference_valid"]=False
        return reference._apply_style(rgb,anchor,strength)
    mapped=_apply_polynomial(rgb,profile["coef"]);blend=.94
    reference.STATE["style_strength_used"]=blend;reference.STATE["pixel_reference_valid"]=True;reference.STATE["pixel_reference_correlation"]=round(profile["correlation"],4);reference.STATE["pixel_reference_median_error"]=round(profile["median_error"],4)
    return np.clip(mapped.astype(np.float32)*blend+rgb.astype(np.float32)*(1-blend),0,255).astype(np.uint8)


def manual_target_exposure(rgb):
    result=reference.subject_safe_exposure(rgb);anchor=reference.STATE.get("anchor");gap=reference.STATE.get("sequence_gap",999);profile=_profile(anchor) if anchor and gap<=3 else None
    if not profile or not profile["valid"]:return result
    ev=math.log2(profile["edited_p95"]/max(float(result["p95"]),.06))
    if float(result["p99"])>.985:ev-=min(.08,(float(result["p99"])-.985)*1.2)
    ev=float(np.clip(ev,-.32,.40));result["recommended_ev"]=round(ev,4);result["reference_target_p50"]=round(profile["edited_p50"],4);result["reference_target_p95"]=round(profile["edited_p95"],4);result["reference_target_p99"]=round(profile["edited_p99"],4)
    result["exposure_method"]="aligned_manual_pixel_model_plus_p95_target";result["reference_fit_correlation"]=round(profile["correlation"],4);result["reference_fit_median_error"]=round(profile["median_error"],4);result["lightroom_equivalent"]["Exposure"]=round(ev,2)
    return result


reference.core.apply_anchor_style=pixel_reference_style
reference.render_drafts.analyze_exposure=manual_target_exposure

if __name__=="__main__":raise SystemExit(reference.render_drafts.main())
