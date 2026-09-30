# -*- coding: utf-8 -*-
"""临时探针：按"窗长 = min(分辨需要的长度, 时间片)"算出每个谱面音会拿到多长的窗。

用法：E:\\Python\\python.exe -X utf8 tools\\_win_probe.py <ref.json> [scale]
只读，跑完可以删。
"""
import io
import json
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "homework"))

import run_assignment as RA   # noqa: E402


def main():
    ref = sys.argv[1]
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    notes = json.load(io.open(ref, encoding="utf-8"))["notes"]
    slots = RA.build_slots(notes)
    slices = RA.slot_slices(slots, scale)
    print("slots=%d  scale=%.3f  kappa=%s" % (len(slots), scale, RA.WIN_KAPPA))
    seen = {}
    for s, sl in enumerate(slots):
        for j in sl["notes"]:
            midi = int(notes[j]["midi"])
            w = RA.win_ms_for(midi, slices[s])
            name = RA.note_name(midi)
            key = (midi, round(w))
            seen.setdefault(key, [0, name, round(slices[s], 3)])
            seen[key][0] += 1
    for (midi, w), (n, name, sl) in sorted(seen.items(), key=lambda kv: kv[0][0]):
        print("  midi=%3d %-4s 窗=%6.1fms  时间片=%.3fs  出现 %d 次" % (midi, name, w, sl, n))


if __name__ == "__main__":
    main()
