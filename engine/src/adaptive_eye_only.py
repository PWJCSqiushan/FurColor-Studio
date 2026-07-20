from __future__ import annotations

import cv2
import numpy as np


def _legacy(item):
    if item.get("type"): return item
    radius=float(item.get("radius",.018))
    return {"type":"ellipse","x":item["x"],"y":item["y"],"major":radius*1.05,"minor":radius*.78,"angle":0,"feather":.42}


def _mask(item,h,w):
    if item.get("type")=="polygon":
        pts=np.asarray([[float(p["x"])*w,float(p["y"])*h] for p in item.get("points",[])],np.float32)
        if len(pts)<3:return None
        lo,hi=pts.min(0),pts.max(0);base=max(3.,min(hi[0]-lo[0],hi[1]-lo[1]));f=float(item.get("feather",.42));pad=max(6,round(base*(.2+f*.35)))
        x1,y1=max(0,int(np.floor(lo[0]))-pad),max(0,int(np.floor(lo[1]))-pad);x2,y2=min(w,int(np.ceil(hi[0]))+pad+1),min(h,int(np.ceil(hi[1]))+pad+1)
        local=np.round(pts-np.array([x1,y1],np.float32)).astype(np.int32);m=np.zeros((y2-y1,x2-x1),np.uint8);cv2.fillPoly(m,[local],255);sigma=max(.8,base*f*.1)
    else:
        short=min(h,w);cx,cy=round(float(item["x"])*w),round(float(item["y"])*h);rx=max(3,round(float(item.get("major",.018))*short));ry=max(2,round(float(item.get("minor",.012))*short));f=float(item.get("feather",.42));pad=max(6,round(min(rx,ry)*(.6+f)));reach=max(rx,ry)+pad
        x1,y1,x2,y2=max(0,cx-reach),max(0,cy-reach),min(w,cx+reach+1),min(h,cy+reach+1);m=np.zeros((y2-y1,x2-x1),np.uint8);cv2.ellipse(m,(cx-x1,cy-y1),(rx,ry),float(item.get("angle",0)),0,360,255,-1);sigma=max(.8,min(rx,ry)*f*.38)
    m=cv2.GaussianBlur(m,(0,0),sigmaX=sigma,sigmaY=sigma)
    return (x1,y1,x2,y2),m.astype(np.float32)[:,:,None]/255


def enhance_adaptive_eyes(rgb:np.ndarray,annotations:list[dict],exposure_ev:float=.18,saturation:float=25)->np.ndarray:
    out=rgb.copy();h,w=out.shape[:2]
    for raw in annotations:
        item=_legacy(raw);result=_mask(item,h,w)
        if result is None:continue
        (x1,y1,x2,y2),alpha=result;roi=out[y1:y2,x1:x2]
        if not roi.size:continue
        hsv=cv2.cvtColor(roi,cv2.COLOR_RGB2HSV).astype(np.float32);sat=float(item.get("saturation",saturation));hsv[:,:,1]=np.clip(hsv[:,:,1]*(1+sat/100),0,255)
        boosted=cv2.cvtColor(hsv.astype(np.uint8),cv2.COLOR_HSV2RGB).astype(np.float32)*(2**float(item.get("exposure_ev",exposure_ev)))
        out[y1:y2,x1:x2]=np.clip(boosted*alpha+roi.astype(np.float32)*(1-alpha),0,255).astype(np.uint8)
    return out
