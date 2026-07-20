from __future__ import annotations
import argparse, json, subprocess, sys, threading, webbrowser
from pathlib import Path
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--config",required=True);parser.add_argument("--port",type=int,default=8765);args=parser.parse_args()
    config_path=Path(args.config).resolve();cfg=json.loads(config_path.read_text(encoding="utf-8"));runtime=config_path.parent
    feedback=runtime/"face_labels.jsonl";cli=Path(__file__).with_name("feedback_cli_auto.py");url=f"http://127.0.0.1:{args.port}/"
    threading.Timer(1.0,lambda:webbrowser.open(url)).start()
    return subprocess.call([sys.executable,str(cli),"serve","--analysis-output",cfg["analysis_output"],"--feedback",str(feedback),"--port",str(args.port),"--max-side",str(cfg.get("max_side",1400))])
if __name__=="__main__":raise SystemExit(main())
