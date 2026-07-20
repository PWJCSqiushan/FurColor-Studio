from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BAD_SUFFIX={".arw",".jpg",".jpeg",".png",".zip",".pem",".key",".sqlite",".db",".onnx"}
TEXT_SUFFIX={".py",".js",".css",".html",".md",".txt",".json",".yml",".yaml",".toml",".ps1",".sh",".example"}
patterns={
  "private key":re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
  "Windows user path":re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+",re.I),
  "private photo root":re.compile(r"[A-Za-z]:\\[^\r\n]*丘山",re.I),
  "Tencent instance id":re.compile(r"lhins-[a-z0-9]+",re.I),
  "credential assignment":re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"](?!\{\{)[^'\"]{8,}"),
}
def candidates():
    try:
        out=subprocess.check_output(["git","ls-files","--cached","--others","--exclude-standard","-z"],cwd=ROOT)
        return [ROOT/x.decode("utf-8") for x in out.split(b"\0") if x]
    except Exception:
        skip={".git",".venv","__pycache__","runtime","data","deliveries"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not any(x in skip for x in p.parts)]
issues=[]
for path in candidates():
    if not path.exists() or not path.is_file():continue
    rel=path.relative_to(ROOT)
    if path.suffix.lower() in BAD_SUFFIX:issues.append(f"binary/private artifact would be published: {rel}")
    if path.suffix.lower() not in TEXT_SUFFIX and path.name not in {"Dockerfile.demo",".gitignore",".dockerignore"}:continue
    try:text=path.read_text(encoding="utf-8")
    except UnicodeDecodeError:issues.append(f"non-UTF8 file: {rel}");continue
    for label,pattern in patterns.items():
        if pattern.search(text):issues.append(f"{label}: {rel}")
if issues:
    print("FAIL — sensitive or non-source artifacts detected:")
    for issue in sorted(set(issues)):print(f" - {issue}")
    sys.exit(1)
print("PASS — Git publication candidates contain no known photos, credentials, private paths, model weights, or instance identifiers.")
