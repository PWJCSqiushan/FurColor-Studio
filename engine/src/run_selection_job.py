from __future__ import annotations
import argparse, subprocess, sys, threading, webbrowser
from pathlib import Path

def main():
    p=argparse.ArgumentParser(); p.add_argument("--config",required=True); p.add_argument("--port",type=int,default=8766); a=p.parse_args()
    url=f"http://127.0.0.1:{a.port}/"; threading.Timer(1.0,lambda:webbrowser.open(url)).start()
    return subprocess.call([sys.executable,str(Path(__file__).with_name("selection_cli.py")),"--config",a.config,"--port",str(a.port)])
if __name__=="__main__": raise SystemExit(main())
