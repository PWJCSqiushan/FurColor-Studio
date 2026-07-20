from __future__ import annotations

import argparse
from datetime import datetime
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from selection_cli import load_selection, selected_stems


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def clean_mask(item: dict) -> dict | None:
    kind = item.get("type", "legacy")
    exposure = round(_clamp(item.get("exposure_ev", 0.18), -0.5, 0.7), 3)
    saturation = round(_clamp(item.get("saturation", 25), -50, 80), 1)
    feather = round(_clamp(item.get("feather", 0.42), 0.05, 1.0), 3)
    if kind == "polygon":
        points = []
        for point in item.get("points", [])[:40]:
            x, y = float(point["x"]), float(point["y"])
            if 0 <= x <= 1 and 0 <= y <= 1:
                points.append({"x": round(x, 6), "y": round(y, 6)})
        if len(points) < 3:
            return None
        return {"type": "polygon", "points": points, "feather": feather,
                "exposure_ev": exposure, "saturation": saturation}

    # Backward compatibility: old annotations used x/y/radius only.
    x, y = float(item["x"]), float(item["y"])
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    if "major" in item:
        major = _clamp(item["major"], 0.003, 0.16)
        minor = _clamp(item.get("minor", major * 0.7), 0.002, 0.16)
        angle = float(item.get("angle", 0.0)) % 360.0
    else:
        radius = _clamp(item.get("radius", 0.018), 0.004, 0.08)
        major, minor, angle = radius * 1.05, radius * 0.78, 0.0
    return {"type": "ellipse", "x": round(x, 6), "y": round(y, 6),
            "major": round(major, 6), "minor": round(minor, 6),
            "angle": round(angle, 2), "feather": feather,
            "exposure_ev": exposure, "saturation": saturation}


class EyeStore:
    def __init__(self, analysis: Path, output: Path, selection_path: Path, default_mode: str):
        self.output, self.selection_path = output, selection_path
        recipes = {}
        for recipe_path in sorted((analysis / "recipes").glob("*.json")):
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            recipes[Path(recipe["file"]).stem] = recipe
        self.all_count = len(recipes)
        self.selection = load_selection(selection_path, default_mode)
        allowed = selected_stems(selection_path, list(recipes), default_mode)
        self.items = [stem for stem in recipes if stem in allowed]
        self.source = {stem: Path(recipes[stem]["source_path"]) for stem in self.items}
        self.data = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"version": 2, "images": {}}
        self.data["version"] = 2
        self.data.setdefault("images", {})

    @property
    def mode(self):
        return self.selection.get("mode", "negative")

    @property
    def annotated_count(self):
        return sum(bool(self.data["images"].get(stem)) for stem in self.items)

    def save_masks(self, stem: str, masks: list[dict]):
        if stem not in self.source:
            raise ValueError("This image is not in the current selected set.")
        cleaned = [result for item in masks[:20] if (result := clean_mask(item)) is not None]
        self.data["images"][stem] = cleaned
        self.data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.output.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.output)


def make_handler(store: EyeStore):
    class Handler(BaseHTTPRequestHandler):
        def send_html(self, body: str):
            data = body.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            if parsed.path == "/image":
                stem = query.get("stem", [""])[0]
                if stem not in store.source:
                    self.send_error(404, "Image is not selected"); return
                try:
                    with Image.open(store.source[stem]) as original:
                        image = original.convert("RGB"); image.thumbnail((1800, 1200), Image.Resampling.LANCZOS)
                        bio = BytesIO(); image.save(bio, "JPEG", quality=86); data = bio.getvalue()
                except Exception as exc:
                    self.send_error(500, str(exc)); return
                self.send_response(200); self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return

            mode_cn = "正选" if store.mode == "positive" else "反选"
            if not store.items:
                self.send_html(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font-family:system-ui;margin:40px">
<h1>当前没有入选照片</h1><p>{mode_cn}模式；入选 0 / 分析目录 {store.all_count}。</p>
<p>请结束本程序，先运行 run_select.ps1，再运行 run_v3_analysis.ps1。</p></body></html>'''); return

            page = min(max(0, int(query.get("page", ["0"])[0])), len(store.items)-1)
            stem = store.items[page]
            masks = json.dumps(store.data["images"].get(stem, []), ensure_ascii=False)
            body = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>自适应兽装眼睛蒙版</title><style>
body{{font-family:system-ui;background:#111;color:#eee;margin:16px}}canvas{{max-width:100%;max-height:70vh;background:#050505;cursor:crosshair}}button,select{{padding:8px 12px;margin:5px;border:0;border-radius:6px}}a{{color:#8ecbff}}.bar{{background:#202730;border-radius:9px;padding:10px 14px;margin-bottom:10px}}.controls{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:#1b2027;padding:9px;border-radius:8px}}label{{white-space:nowrap}}.tip{{color:#c5cad1}}
</style></head><body>
<div class="bar">选片模式：<b>{mode_cn}</b>｜本轮入选：<b>{len(store.items)}</b> / 分析目录 {store.all_count}｜已标有眼睛：{store.annotated_count}</div>
<h2>{html.escape(stem)}　{page+1}/{len(store.items)}</h2>
<div class="controls"><label>形状 <select id="mode"><option value="ellipse">旋转椭圆</option><option value="polygon">不规则多边形</option></select></label>
<label>椭圆短轴比 <input id="aspect" type="range" min="0.25" max="1.20" value="0.68" step="0.05"><span id="av">0.68</span></label>
<label>羽化 <input id="feather" type="range" min="0.05" max="1.00" value="0.42" step="0.05"><span id="fv">0.42</span></label>
<label>曝光 EV <input id="ev" type="range" min="0.05" max="0.30" value="0.18" step="0.01"><span id="evv">0.18</span></label>
<label>饱和度 <input id="sat" type="range" min="10" max="40" value="25" step="1"><span id="sv">25</span></label></div>
<p class="tip"><b>旋转椭圆：</b>从眼睛中心向长轴方向拖拽，拖拽长度决定大小、方向决定角度，短轴比可单独调整。<b>不规则多边形：</b>沿眼睛边缘逐点单击，双击或点“完成多边形”。Shift+单击删除最近蒙版。</p>
<canvas id="c"></canvas><div><button id="finish">完成多边形</button><button id="clear">清空本张</button><button id="save">保存并下一张</button>
<a href="/?page={max(0,page-1)}">上一张</a>　<a href="/?page={min(len(store.items)-1,page+1)}">下一张</a></div>
<script>
const stem={json.dumps(stem)},page={page};let masks={masks},working=[],drag=null,preview=null;
const c=document.getElementById('c'),ctx=c.getContext('2d'),img=new Image(),short=()=>Math.min(c.width,c.height);
const mode=document.getElementById('mode'),aspect=document.getElementById('aspect'),feather=document.getElementById('feather'),ev=document.getElementById('ev'),sat=document.getElementById('sat');
for(const [el,label] of [[aspect,'av'],[feather,'fv'],[ev,'evv'],[sat,'sv']])el.oninput=()=>document.getElementById(label).textContent=el.value;
function normalized(m){{if(m.type)return m;let r=m.radius||.018;return{{type:'ellipse',x:m.x,y:m.y,major:r*1.05,minor:r*.78,angle:0,feather:.42,exposure_ev:.18,saturation:25}}}}masks=masks.map(normalized);
function xy(e){{const r=c.getBoundingClientRect();return{{x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height}}}}
function drawMask(m,color='#48ff78'){{ctx.save();ctx.strokeStyle=color;ctx.lineWidth=3;if(m.type==='polygon'){{ctx.beginPath();m.points.forEach((p,i)=>(i?ctx.lineTo(p.x*c.width,p.y*c.height):ctx.moveTo(p.x*c.width,p.y*c.height)));ctx.closePath();ctx.stroke()}}else{{ctx.beginPath();ctx.ellipse(m.x*c.width,m.y*c.height,m.major*short(),m.minor*short(),m.angle*Math.PI/180,0,Math.PI*2);ctx.stroke()}}ctx.restore()}}
function draw(){{ctx.drawImage(img,0,0,c.width,c.height);masks.forEach(m=>drawMask(m));if(preview)drawMask(preview,'#ffd44a');if(working.length)drawMask({{type:'polygon',points:working}},'#ffd44a')}}
function settings(){{return{{feather:+feather.value,exposure_ev:+ev.value,saturation:+sat.value}}}}
function finishPolygon(){{if(working.length>=3)masks.push({{type:'polygon',points:working,...settings()}});working=[];draw()}}
function center(m){{if(m.type!=='polygon')return{{x:m.x,y:m.y}};return{{x:m.points.reduce((a,p)=>a+p.x,0)/m.points.length,y:m.points.reduce((a,p)=>a+p.y,0)/m.points.length}}}}
function removeNearest(p){{if(!masks.length)return;let k=0,d=99;masks.forEach((m,i)=>{{let q=center(m),z=(q.x-p.x)**2+(q.y-p.y)**2;if(z<d){{d=z;k=i}}}});masks.splice(k,1);draw()}}
img.onload=()=>{{c.width=img.naturalWidth;c.height=img.naturalHeight;draw()}};img.src='/image?stem='+encodeURIComponent(stem);
c.onmousedown=e=>{{if(e.shiftKey){{removeNearest(xy(e));return}}if(mode.value!=='ellipse')return;drag=xy(e)}};
c.onmousemove=e=>{{if(!drag)return;let p=xy(e),dx=(p.x-drag.x)*c.width,dy=(p.y-drag.y)*c.height,major=Math.hypot(dx,dy)/short();preview={{type:'ellipse',x:drag.x,y:drag.y,major:Math.max(.003,major),minor:Math.max(.002,major*(+aspect.value)),angle:Math.atan2(dy,dx)*180/Math.PI,...settings()}};draw()}};
c.onmouseup=e=>{{if(e.shiftKey||!drag)return;if(preview&&preview.major>.004)masks.push(preview);drag=null;preview=null;draw()}};
c.onclick=e=>{{if(e.shiftKey||mode.value!=='polygon')return;working.push(xy(e));draw()}};c.ondblclick=e=>{{e.preventDefault();finishPolygon()}};
document.getElementById('finish').onclick=finishPolygon;document.getElementById('clear').onclick=()=>{{masks=[];working=[];draw()}};
document.getElementById('save').onclick=async()=>{{finishPolygon();const r=await fetch('/save',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{stem,masks}})}});if(!r.ok){{alert(await r.text());return}}location.href='/?page='+Math.min({len(store.items)-1},page+1)}};
</script></body></html>'''
            self.send_html(body)

        def do_POST(self):
            if self.path != "/save": self.send_error(404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                store.save_masks(data["stem"], data.get("masks", []))
            except Exception as exc:
                self.send_error(400, str(exc)); return
            self.send_response(204); self.end_headers()

        def log_message(self, format, *args): return
    return Handler


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--port", type=int, default=8767); args = parser.parse_args()
    config = Path(args.config).resolve(); root = config.parent.parent; cfg = json.loads(config.read_text(encoding="utf-8"))
    store = EyeStore(Path(cfg["analysis_output"]), root/cfg.get("eye_annotations", "feedback/eye_annotations.json"), root/cfg.get("selection_file", "feedback/selection.json"), cfg.get("selection_mode", "negative"))
    print(f"selection_mode={store.mode} selected={len(store.items)}/{store.all_count} annotation_schema=v2_adaptive")
    print(f"Open http://127.0.0.1:{args.port}/ . Ctrl+C stops the server.")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store)).serve_forever()


if __name__ == "__main__": main()
