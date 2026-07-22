from __future__ import annotations

import argparse
import base64
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
import furcolor_cli as core


def load_selection(path: Path, default_mode: str = "negative") -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        data = {"version": 1, "mode": default_mode, "choices": {}}
    data.setdefault("mode", default_mode)
    data.setdefault("choices", {})
    return data


def selected_stems(path: Path, all_stems: list[str], default_mode: str = "negative") -> set[str]:
    data = load_selection(path, default_mode)
    choices = data["choices"]
    if data["mode"] == "positive":
        return {s for s in all_stems if choices.get(s) == "keep"}
    return {s for s in all_stems if choices.get(s) != "reject"}


class SelectionStore:
    def __init__(self, source: Path, edited: Path, path: Path, include_edited: bool, default_mode: str):
        self.source, self.path = source, path
        edited_stems = {p.stem for p in edited.iterdir() if p.is_file()} if edited.exists() else set()
        self.files = core.scan_source(source, edited_stems, include_edited)
        self.by_stem = {p.stem: p for p in self.files}
        self.data = load_selection(path, default_mode)

    def save(self):
        self.data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def choose(self, stem: str, choice: str):
        if stem not in self.by_stem or choice not in {"keep", "reject", "unset"}:
            raise ValueError("invalid selection")
        if choice == "unset":
            self.data["choices"].pop(stem, None)
        else:
            self.data["choices"][stem] = choice
        self.save()

    def set_mode(self, mode: str):
        if mode not in {"positive", "negative"}:
            raise ValueError("invalid mode")
        self.data["mode"] = mode
        self.save()

    def thumb(self, stem: str) -> bytes:
        path = self.by_stem[stem]
        rgb = core.load_rgb(path, 720)
        image = Image.fromarray(rgb)
        image.thumbnail((640, 480), Image.Resampling.LANCZOS)
        bio = BytesIO()
        image.save(bio, "JPEG", quality=76)
        return bio.getvalue()


def make_handler(store: SelectionStore, page_size: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/thumb":
                stem = query.get("stem", [""])[0]
                try:
                    data = store.thumb(stem)
                except Exception as exc:
                    self.send_error(404, str(exc)); return
                self.send_response(200); self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
            page = max(0, int(query.get("page", ["0"])[0]))
            state_filter = query.get("state", ["all"])[0]
            items = store.files
            if state_filter in {"keep", "reject", "unset"}:
                items = [p for p in items if store.data["choices"].get(p.stem, "unset") == state_filter]
            pages = max(1, (len(items)+page_size-1)//page_size)
            page = min(page, pages-1)
            items = items[page*page_size:(page+1)*page_size]
            cards=[]
            for path in items:
                stem=path.stem; state=store.data["choices"].get(stem,"unset")
                cards.append(f'''<article class="card {state}"><img loading="lazy" src="/thumb?stem={html.escape(stem)}">
<div><b>{html.escape(stem)}</b><span>{state}</span></div><form method="post" action="/choose">
<input type="hidden" name="stem" value="{html.escape(stem)}"><input type="hidden" name="page" value="{page}">
<input type="hidden" name="state_filter" value="{state_filter}">
<button name="choice" value="keep" class="keep">保留</button><button name="choice" value="reject" class="reject">废片</button>
<button name="choice" value="unset" class="unset">恢复默认</button></form></article>''')
            counts={k:sum(store.data["choices"].get(p.stem,"unset")==k for p in store.files) for k in ("keep","reject","unset")}
            mode=store.data["mode"]
            effective = counts["keep"] if mode=="positive" else len(store.files)-counts["reject"]
            body=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>FurColor 选片</title><style>
body{{font-family:system-ui;background:#11151a;color:#eee;margin:20px}}a{{color:#8ecbff}}nav{{position:sticky;top:0;background:#11151aee;padding:12px 0;z-index:2}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}}.card{{background:#242a31;padding:10px;border:3px solid #555;border-radius:10px}}
.card.keep{{border-color:#63d984}}.card.reject{{border-color:#f05d68;opacity:.72}}img{{width:100%;height:220px;object-fit:contain;background:#080a0d}}
button{{padding:8px 12px;border:0;border-radius:6px;margin:5px 3px;cursor:pointer}}.keep{{background:#63d984}}.reject{{background:#f05d68}}.unset{{background:#b8bec7}}span{{float:right;color:#aaa}}
</style></head><body><h1>活动照片选片</h1><p>正选＝只处理明确“保留”的照片；反选＝默认全处理，只排除“废片”。当前：<b>{'正选' if mode=='positive' else '反选'}</b>，最终处理 {effective}/{len(store.files)} 张。</p>
<form method="post" action="/mode"><button name="mode" value="positive">切换正选</button><button name="mode" value="negative">切换反选</button></form>
<nav>保留 {counts['keep']}｜废片 {counts['reject']}｜未定 {counts['unset']}　<a href="/?page={max(0,page-1)}&state={state_filter}">上一页</a>　{page+1}/{pages}　<a href="/?page={min(pages-1,page+1)}&state={state_filter}">下一页</a>　
<a href="/?state=all">全部</a> <a href="/?state=unset">未定</a> <a href="/?state=keep">保留</a> <a href="/?state=reject">废片</a></nav><div class="grid">{''.join(cards)}</div></body></html>'''
            data=body.encode("utf-8"); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_POST(self):
            length=int(self.headers.get("Content-Length","0")); form=parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                if self.path=="/choose": store.choose(form.get("stem",[""])[0],form.get("choice",[""])[0])
                elif self.path=="/mode": store.set_mode(form.get("mode",[""])[0])
                else: self.send_error(404); return
            except Exception as exc: self.send_error(400,str(exc)); return
            page=form.get("page",["0"])[0]; filt=form.get("state_filter",["all"])[0]
            self.send_response(303); self.send_header("Location",f"/?page={page}&state={filt}"); self.end_headers()
        def log_message(self, format, *args): return
    return Handler


def main():
    p=argparse.ArgumentParser(); p.add_argument("--config",required=True); p.add_argument("--port",type=int,default=8766); args=p.parse_args()
    config=Path(args.config).resolve(); root=config.parent.parent; cfg=json.loads(config.read_text(encoding="utf-8"))
    path=root/cfg.get("selection_file","feedback/selection.json")
    store=SelectionStore(Path(cfg["source"]),Path(cfg["edited"]),path,bool(cfg.get("include_edited",False)),cfg.get("selection_mode","negative"))
    print(f"Open http://127.0.0.1:{args.port}/ . Ctrl+C stops the server.")
    ThreadingHTTPServer(("127.0.0.1",args.port),make_handler(store,24)).serve_forever()

if __name__=="__main__": main()
