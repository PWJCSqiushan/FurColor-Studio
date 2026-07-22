from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import furcolor_cli as core
from quality_engine import (analyze_exposure,analyze_subject_exposure,apply_exposure_tone,
    apply_subject_exposure_tone,apply_white_balance,enhance_eyes,estimate_neutral_white,
    load_eye_annotations,save_waveform,write_metrics)
from selection_cli import selected_stems
from subject_intelligence import detections_for_image,load_subject_analysis


def privacy_process(rgb:np.ndarray,faces:list[dict],include_review:bool)->np.ndarray:
    out=rgb.copy();h,w=out.shape[:2]
    for face in faces:
        if face.get("suppressed_by_memory",False) or face.get("suppressed_by_geometry",False) or face.get("suppressed_by_subject",False):continue
        if not face.get("auto_privacy_allowed",face.get("severity")=="high"):continue
        if face.get("severity")!="high" and not include_review:continue
        pad=round(.28*max(face["w"],face["h"]));x1,y1=max(0,face["x"]-pad),max(0,face["y"]-pad);x2,y2=min(w,face["x"]+face["w"]+pad),min(h,face["y"]+face["h"]+pad)
        roi=out[y1:y2,x1:x2]
        if not roi.size:continue
        k=max(21,(min(roi.shape[:2])//3)|1);blurred=cv2.GaussianBlur(roi,(k,k),0);processed=np.clip(blurred.astype(np.float32)*.34,0,255).astype(np.uint8)
        mask=np.zeros(roi.shape[:2],dtype=np.uint8);cv2.ellipse(mask,(mask.shape[1]//2,mask.shape[0]//2),(max(1,mask.shape[1]//2-2),max(1,mask.shape[0]//2-2)),0,0,360,255,-1)
        bk=max(9,(min(mask.shape)//5)|1);alpha=cv2.GaussianBlur(mask,(bk,bk),0).astype(np.float32)[:,:,None]/255
        out[y1:y2,x1:x2]=(processed*alpha+roi*(1-alpha)).astype(np.uint8)
    return out


def scaled_faces(recipe:dict,analysis_rgb:np.ndarray,render_rgb:np.ndarray)->list[dict]:
    sx=render_rgb.shape[1]/analysis_rgb.shape[1];sy=render_rgb.shape[0]/analysis_rgb.shape[0];result=[]
    for face in recipe.get("faces",[]):
        f=dict(face);f["x"],f["w"]=round(face["x"]*sx),round(face["w"]*sx);f["y"],f["h"]=round(face["y"]*sy),round(face["h"]*sy);result.append(f)
    return result


def apply_watermark(rgb:np.ndarray,path:Path,opacity:float,width_ratio:float,margin_ratio:float)->np.ndarray:
    if not path.exists():raise FileNotFoundError(f"Watermark not found: {path}")
    base=Image.fromarray(rgb).convert("RGBA");mark=Image.open(path).convert("RGBA")
    bbox=mark.getchannel("A").getbbox()
    if bbox:mark=mark.crop(bbox)
    target_w=max(24,round(base.width*width_ratio));target_h=max(1,round(mark.height*target_w/mark.width))
    max_h=round(base.height*.15)
    if target_h>max_h:target_h=max_h;target_w=round(mark.width*target_h/mark.height)
    mark=mark.resize((target_w,target_h),Image.Resampling.LANCZOS)
    alpha=mark.getchannel("A").point(lambda v:round(v*max(0,min(opacity,1))))
    mark.putalpha(alpha);margin=round(min(base.size)*margin_ratio);pos=(base.width-target_w-margin,base.height-target_h-margin)
    base.alpha_composite(mark,pos);return np.asarray(base.convert("RGB"))


def main()->int:
    p=argparse.ArgumentParser(description="Render FurColor V3 one-click JPEG drafts");p.add_argument("--config",required=True);p.add_argument("--limit",type=int,default=-1);a=p.parse_args()
    config=Path(a.config).resolve();root=config.parent.parent;cfg=json.loads(config.read_text(encoding="utf-8"))
    source,edited=Path(cfg["source"]),Path(cfg["edited"]);analysis=Path(cfg["analysis_output"]);manifest=root/cfg.get("manifest","config/starfestival_lightroom_manifest.json")
    output=Path(cfg.get("draft_output_v3",cfg.get("draft_output",str(analysis/"auto_jpeg_drafts_v3"))))
    analysis_side=int(cfg.get("max_side",1400));max_side=int(cfg.get("delivery_max_side",3200));quality=int(cfg.get("delivery_jpeg_quality",91));include_review=bool(cfg.get("privacy_process_review",False));strength=float(cfg.get("style_strength",.72));limit=int(cfg.get("render_limit",0)) if a.limit<0 else a.limit
    selection_path=root/cfg.get("selection_file","feedback/selection.json");eye_path=root/cfg.get("eye_annotations","feedback/eye_annotations.json");eyes=load_eye_annotations(eye_path)
    watermark=Path(cfg["watermark_path"]) if cfg.get("watermark_path") else None
    subject_analysis=load_subject_analysis(cfg.get("subject_analysis"))
    for d in (output/"face_high",output/"manual_review",output/"no_face_detected",output/"quality_metrics",output/"waveforms"):d.mkdir(parents=True,exist_ok=True)
    anchors={x.stem:x for x in core.build_anchors(source,edited,manifest)};recipes=sorted((analysis/"recipes").glob("*.json"))
    stems=[p.stem for p in recipes];allowed=selected_stems(selection_path,stems,cfg.get("selection_mode","negative"));recipes=[p for p in recipes if p.stem in allowed]
    if limit>0:recipes=recipes[:limit]
    counts={"face_high":0,"manual_review":0,"no_face_detected":0,"errors":0,"waveforms":0,"eye_enhanced_images":0};started=time.time()
    for i,rp in enumerate(recipes,1):
        try:
            recipe=json.loads(rp.read_text(encoding="utf-8"));src=Path(recipe["source_path"]);rgb=core.load_rgb(src,max_side);analysis_rgb=core.load_rgb(src,analysis_side);faces=scaled_faces(recipe,analysis_rgb,rgb)
            subject_boxes=detections_for_image(subject_analysis,src.stem,rgb.shape,"fursuits")
            # Anchor transfer approximates the learned personal look; neutral-WB and exposure then act as final technical guards.
            styled=core.apply_anchor_style(rgb,anchors[recipe["anchor"]],strength)
            wb=estimate_neutral_white(styled);balanced=apply_white_balance(styled,wb,float(cfg.get("neutral_wb_strength",1.0)))
            exposure=analyze_exposure(balanced);subjects=analyze_subject_exposure(balanced,subject_boxes,exposure)
            global_toned=apply_exposure_tone(balanced,exposure);toned=apply_subject_exposure_tone(global_toned,subjects,float(cfg.get("subject_exposure_strength",.65)))
            points=eyes.get(src.stem,[]);enhanced=enhance_eyes(toned,points,float(cfg.get("eye_exposure_ev",.18)),float(cfg.get("eye_saturation",25)))
            risk=recipe.get("face_risk","review");folder="face_high" if risk=="high" else ("manual_review" if risk=="review" else "no_face_detected")
            rendered=privacy_process(enhanced,faces,include_review)
            if watermark:rendered=apply_watermark(rendered,watermark,float(cfg.get("watermark_opacity",.8)),float(cfg.get("watermark_width_ratio",.06)),float(cfg.get("watermark_margin_ratio",.015)))
            Image.fromarray(rendered).save(output/folder/f"{src.stem}.jpg",quality=quality,optimize=True)
            metrics={"file":src.name,"anchor":recipe["anchor"],"white_balance":wb,"exposure":exposure,"subjects":subjects,"eye_masks":len(points),"watermark":str(watermark) if watermark else None}
            write_metrics(output/"quality_metrics"/f"{src.stem}.json",metrics)
            if exposure["exposure_risk"]!="normal":save_waveform(balanced,output/"waveforms"/f"{src.stem}.png",f"{src.stem} | {exposure['exposure_risk']}");counts["waveforms"]+=1
            counts[folder]+=1;counts["eye_enhanced_images"]+=bool(points)
        except Exception as exc:
            counts["errors"]+=1
            with (output/"errors.log").open("a",encoding="utf-8") as f:f.write(f"{rp.name}\t{exc}\n")
        if i==1 or i%25==0 or i==len(recipes):
            elapsed=max(time.time()-started,.001);print(f"{i}/{len(recipes)} {i/elapsed:.2f} images/s",flush=True)
    summary={"version":4,"generated_at":time.strftime("%Y-%m-%d %H:%M:%S"),"count":len(recipes),"output":str(output),"max_side":max_side,"jpeg_quality":quality,
             "pipeline":["anchor_style","neutral_white_balance","global_exposure_tone","fursuit_subject_exposure","eye_local_mask","human_face_privacy","watermark"],"selection":str(selection_path),"eye_annotations":str(eye_path),"counts":counts,
             "warning":"Automated commercial drafts still require final human review for faces, eyes, crop and exposure."}
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(summary,ensure_ascii=False,indent=2));return 0 if counts["errors"]==0 else 2

if __name__=="__main__":raise SystemExit(main())
