# -*- coding: utf-8 -*-
"""临时：造一个"低音弦故意写错"的负面靶子（把六弦的音整体抬 2 个品）。

用法：E:\\Python\\python.exe -X utf8 tools\\_neg_dyad.py
产物：data\\jobs\\neg-dyad6\\ref.json（不进 git）。跑完可以删。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "assignments", "1645-dyad", "ref.json")
DELTA = int(sys.argv[1]) if len(sys.argv) > 1 else 2
OUT = os.path.join(ROOT, "data", "jobs", "neg-dyad6-%d" % DELTA, "ref.json")

ref = json.load(io.open(SRC, encoding="utf-8"))
n = 0
for note in ref["notes"]:
    if note.get("string") == 6:
        note["fret"] = int(note.get("fret") or 0) + DELTA
        note["midi"] = int(note["midi"]) + DELTA
        n += 1
ref.setdefault("meta", {})["title"] = "1645 C-Am-F-G / dyad（六弦被故意写高 %d 品）" % DELTA
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump(ref, f, ensure_ascii=False, indent=1)
print("改了 %d 个六弦的音 → %s" % (n, OUT))
