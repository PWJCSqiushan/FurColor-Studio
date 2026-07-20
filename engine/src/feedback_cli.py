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
from face_memory import extract_features, train_from_jsonl


class ReviewStore:
    def __init__(self, analysis_output: Path, feedback_path: Path, max_side: int = 1400):
        self.analysis_output = analysis_output
        self.feedback_path = feedback_path
        self.max_side = max_side
        self.items = []
        for recipe_path in sorted((analysis_output / "recipes").glob("*.json")):
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            for index, face in enumerate(recipe.get("faces", [])):
                self.items.append({"recipe": recipe, "face": face, "index": index, "key": f'{Path(recipe["file"]).stem}:{index}'})
        self.labels = self._load_labels()

    def _load_labels(self):
        labels = {}
        if self.feedback_path.exists():
            for line in self.feedback_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    labels[item["key"]] = item["label"]
        return labels

    def image_and_features(self, item):
        recipe, face = item["recipe"], item["face"]
        rgb = core.load_rgb(Path(recipe["source_path"]), self.max_side)
        features = extract_features(rgb, face)
        h, w = rgb.shape[:2]
        pad = round(0.65 * max(face["w"], face["h"]))
        x1, y1 = max(0, face["x"] - pad), max(0, face["y"] - pad)
        x2, y2 = min(w, face["x"] + face["w"] + pad), min(h, face["y"] + face["h"] + pad)
        crop = Image.fromarray(rgb[y1:y2, x1:x2])
        crop.thumbnail((360, 280), Image.Resampling.LANCZOS)
        bio = BytesIO()
        crop.save(bio, format="JPEG", quality=76)
        return "data:image/jpeg;base64," + base64.b64encode(bio.getvalue()).decode("ascii"), features

    def label(self, key: str, label: str):
        item = next((x for x in self.items if x["key"] == key), None)
        if item is None:
            raise KeyError(key)
        _, features = self.image_and_features(item)
        record = {
            "key": key, "file": item["recipe"]["file"], "face_index": item["index"],
            "label": label, "features": features.tolist(),
            "base_score": item["face"].get("score"),
            "skin_ratio": item["face"].get("skin_ratio"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with self.feedback_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.labels[key] = label


def make_handler(store: ReviewStore, page_size: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            page = max(0, int(query.get("page", ["0"])[0]))
            only_unlabeled = query.get("unlabeled", ["1"])[0] == "1"
            pool = [i for i in store.items if not only_unlabeled or i["key"] not in store.labels]
            pages = max(1, (len(pool) + page_size - 1)//page_size)
            page = min(page, pages-1)
            batch = pool[page*page_size:(page+1)*page_size]
            cards = []
            for item in batch:
                try:
                    image_url, _ = store.image_and_features(item)
                except Exception as exc:
                    image_url = ""
                    error = html.escape(str(exc))
                else:
                    error = ""
                face = item["face"]
                old = store.labels.get(item["key"], "unlabeled")
                cards.append(f'''<article class="card">
<h3>{html.escape(item["key"])} <span>{old}</span></h3>
<img src="{image_url}" alt="local crop">
<p>YuNet={face.get("score")} skin={face.get("skin_ratio")} severity={face.get("severity")}</p>
<p class="error">{error}</p>
<form method="post" action="/label">
<input type="hidden" name="key" value="{html.escape(item["key"])}">
<input type="hidden" name="page" value="{page}">
<button name="label" value="human" class="human">真人脸</button>
<button name="label" value="fursuit" class="fursuit">兽头误报</button>
<button name="label" value="unsure" class="unsure">不确定</button>
</form></article>''')
            labeled = len(store.labels)
            body = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>FurColor 人脸反馈</title><style>
body{{font-family:system-ui;background:#15181d;color:#eee;margin:24px}} a{{color:#8ac7ff}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:18px}}
.card{{background:#242a31;padding:14px;border-radius:12px}} img{{width:100%;height:260px;object-fit:contain;background:#111}}
button{{padding:10px 14px;border:0;border-radius:7px;margin:4px;cursor:pointer}} .human{{background:#ff6464}} .fursuit{{background:#73d68b}} .unsure{{background:#f3c969}}
span{{font-size:12px;color:#aaa}} .error{{color:#ff7777}} nav{{margin:16px 0}}
</style></head><body>
<h1>FurColor 本地反馈</h1>
<p>候选框 {len(store.items)}，已标注 {labeled}。只在本机显示和保存，不做人脸身份识别。</p>
<nav><a href="/?page={max(0,page-1)}&unlabeled={1 if only_unlabeled else 0}">上一页</a> ｜ 第 {page+1}/{pages} 页 ｜ <a href="/?page={min(pages-1,page+1)}&unlabeled={1 if only_unlabeled else 0}">下一页</a> ｜ <a href="/?page=0&unlabeled={0 if only_unlabeled else 1}">{'查看全部' if only_unlabeled else '只看未标注'}</a></nav>
<div class="grid">{''.join(cards)}</div></body></html>'''
            data = body.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_POST(self):
            if self.path != "/label":
                self.send_error(404); return
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            key, label = form.get("key", [""])[0], form.get("label", [""])[0]
            page = form.get("page", ["0"])[0]
            try:
                store.label(key, label)
            except Exception as exc:
                self.send_error(400, str(exc)); return
            self.send_response(303); self.send_header("Location", f"/?page={page}&unlabeled=1"); self.end_headers()

        def log_message(self, format, *args):
            return
    return Handler


def main():
    p = argparse.ArgumentParser(description="Human feedback and online memory for FurColor face-presence detection")
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--analysis-output", required=True)
    serve.add_argument("--feedback", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--page-size", type=int, default=16)
    serve.add_argument("--max-side", type=int, default=1400)
    train = sub.add_parser("train")
    train.add_argument("--feedback", required=True)
    train.add_argument("--model", required=True)
    args = p.parse_args()
    if args.command == "serve":
        store = ReviewStore(Path(args.analysis_output), Path(args.feedback), args.max_side)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.page_size))
        print(f"Open http://{args.host}:{args.port}/ in your browser. Ctrl+C stops the server.")
        server.serve_forever()
    else:
        model = train_from_jsonl(Path(args.feedback), Path(args.model))
        print(json.dumps(model, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
