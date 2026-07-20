from __future__ import annotations
import argparse,subprocess,sys,threading,webbrowser
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--port",type=int,default=8767);a=p.parse_args()
    threading.Timer(1,lambda:webbrowser.open(f"http://127.0.0.1:{a.port}/")).start()
    return subprocess.call([sys.executable,str(Path(__file__).with_name("eye_annotation_cli.py")),"--config",a.config,"--port",str(a.port)])
if __name__=="__main__":raise SystemExit(main())
