# -*- coding: utf-8 -*-
"""临时探针：把"漏"的那几格，**在它自己该响的时刻**直接判一次，看能不能分辨
"真漏（学员没弹）"和"起音层漏检（弹了没检出来）"。

做法：不经过起音层，直接拿 pairs.json 喂 engine_judge.mjs：
  * 时刻 = 该格的局部预测（用 match.json 里已配上的邻居插值；没有就退回全局直线）
  * 再试 ±40ms / ±80ms 三个位置，看最好的那个

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_rescue.py <jobdir> [<jobdir2> ...]
"""
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "homework")


def predict(match, slots, t_score, scale, offset):
    if match:
        xs = [p["slot_t"] for p in match]
        ys = [p["onset_t"] for p in match]
        i = 0
        while i < len(xs) and xs[i] < t_score:
            i += 1
        if i == 0:
            return ys[0]
        if i >= len(xs):
            return ys[-1]
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (t_score - x0) / max(1e-6, x1 - x0)
    return t_score * scale + offset


def main():
    for jobdir in sys.argv[1:]:
        res = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
        score = json.load(io.open(res["ref_used"], encoding="utf-8"))["notes"]
        scale = float(res["align"]["scale"])
        offset = float(res["align"]["offset"])
        mp = os.path.join(jobdir, "match.json")
        match = json.load(io.open(mp, encoding="utf-8"))["match"] if os.path.exists(mp) else None
        audio = res["audio"]
        pairs = []
        for it in res.get("issues", []):
            if it.get("kind") != "missing_note":
                continue
            inner = (it.get("items") or [{}])[0]
            t_score = it.get("t_score")
            t0 = predict(match, score, float(t_score), scale, offset)
            for d in (-0.08, -0.04, 0.0, 0.04, 0.08):
                pairs.append({"t": round(t0 + d, 4), "expectedMidi": inner.get("want_midi"),
                              "string": inner.get("string"), "fret": inner.get("fret"),
                              "level": 0.12, "_probe": round(d, 3)})
        pf = os.path.join(jobdir, "pairs_rescue.json")
        with io.open(pf, "w", encoding="utf-8") as f:
            json.dump({"audio": audio, "band": [70, 1200], "pairs": pairs}, f,
                      ensure_ascii=False, indent=1)
        of = os.path.join(jobdir, "judged_rescue.json")
        subprocess.run(["node", os.path.join(HERE, "engine_judge.mjs"), pf, of],
                       check=True, capture_output=True)
        judged = json.load(io.open(of, encoding="utf-8"))["judged"]
        print("== %s" % os.path.basename(jobdir))
        for x, p in zip(judged, pairs):
            print("   要 %-4s s%sf%s  偏移 %+5.0fms  pass=%-5s heard=%-4s fit=%-4s margin=%s"
                  % (x["expectedName"], x["string"], x["fret"], p["_probe"] * 1000,
                     x["pass"], x["heardName"], x["fit"], x["margin"]))


if __name__ == "__main__":
    main()
