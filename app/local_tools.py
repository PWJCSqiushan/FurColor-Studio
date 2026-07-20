from __future__ import annotations
from . import settings
def pick(kind: str) -> str:
    if settings.DEMO: raise PermissionError("演示模式不提供文件选择器")
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw();root.attributes("-topmost",True)
    try:
        if kind in {"watermark","manifest"}:
            types=[("PNG 水印","*.png")] if kind=="watermark" else [("JSON 配置","*.json")]
            result=filedialog.askopenfilename(filetypes=types)
        else: result=filedialog.askdirectory(mustexist=False)
        return result or ""
    finally: root.destroy()
