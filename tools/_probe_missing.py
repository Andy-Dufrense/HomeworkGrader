# -*- coding: utf-8 -*-
"""临时探针：把"漏"的那几个谱面音，和录音里真正的起音时刻对一下 ——
到底是学员没弹（附近没有起音），还是我们没配上（附近有起音却没配）。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_missing.py <jobdir>
"""
import io
import json
import os
import sys


def main():
    jobdir = sys.argv[1]
    res = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
    ev = json.load(io.open(os.path.join(jobdir, "events.json"), encoding="utf-8"))["events"]
    jd_path = os.path.join(jobdir, "judged_win.json")
    if not os.path.exists(jd_path):
        jd_path = os.path.join(jobdir, "judged.json")
    judged = json.load(io.open(jd_path, encoding="utf-8"))["judged"]
    scale = float(res["align"]["scale"])
    offset = float(res["align"]["offset"])
    ts = sorted(float(e["t"]) for e in ev)
    print("job=%s  scale=%.4f offset=%.4f  起音 %d 个"
          % (os.path.basename(jobdir), scale, offset, len(ts)))
    for it in res.get("issues", []):
        if it.get("kind") not in ("missing_note", "wrong_note"):
            continue
        t_score = it.get("t_score")
        if t_score is None:
            continue
        want = t_score * scale + offset
        near = sorted(ts, key=lambda t: abs(t - want))[:3]
        print("  [%s] 谱面 %.2fs（%s）→ 预期录音 %.2fs ｜ 最近的起音：%s"
              % (it["kind"], t_score, it.get("detail", ""), want,
                 "、".join("%.2f(%+.0fms)" % (t, (t - want) * 1000) for t in near)))
        # 这一格的候选配对上，判定到底说了什么（有读数就是"弹了但我们没配上"）
        inner = (it.get("items") or [{}])[0]
        midi = it.get("want_midi", inner.get("want_midi"))
        nearj = [x for x in judged
                 if x.get("expectedMidi") == midi and abs(x["t"] - want) <= 0.8]
        nearj.sort(key=lambda x: abs(x["t"] - want))
        for x in nearj[:3]:
            print("       候选配对 t=%.2f(%+.0fms) pass=%s heard=%s fit=%s margin=%s"
                  % (x["t"], (x["t"] - want) * 1000, x["pass"],
                     x.get("heardName"), x.get("fit"), x.get("margin")))


if __name__ == "__main__":
    main()
