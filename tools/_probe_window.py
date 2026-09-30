# -*- coding: utf-8 -*-
"""临时探针：把某个作业里一段时间窗内的**候选配对判定**全列出来（按起音时刻分组）。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_window.py <jobdir> <t_from> <t_to>
"""
import io
import json
import os
import sys


def main():
    jobdir, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    path = os.path.join(jobdir, "judged_win.json")
    if not os.path.exists(path):
        path = os.path.join(jobdir, "judged.json")
    judged = json.load(io.open(path, encoding="utf-8"))["judged"]
    sel = [x for x in judged if t0 <= float(x["t"]) <= t1]
    sel.sort(key=lambda x: (round(float(x["t"]), 3), x["expectedMidi"]))
    cur = None
    for x in sel:
        t = round(float(x["t"]), 3)
        if t != cur:
            print("起音 %.3fs" % t)
            cur = t
        print("    要 %-4s s%sf%s  pass=%-5s heard=%-4s fit=%-4s margin=%s"
              % (x.get("expectedName"), x.get("string"), x.get("fret"),
                 x.get("pass"), x.get("heardName"), x.get("fit"), x.get("margin")))


if __name__ == "__main__":
    main()
