# -*- coding: utf-8 -*-
"""临时探针：把 DP 的"有哪些配对可选、各自多少分"打出来 —— 查"明明有能过的配对却没配上"。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_dp.py <jobdir> <slot_from> <slot_to>
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "homework"))

import run_assignment as RA   # noqa: E402


def main():
    jobdir, s0, s1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    res = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
    score = json.load(io.open(res["ref_used"], encoding="utf-8"))["notes"]
    events = json.load(io.open(os.path.join(jobdir, "events.json"), encoding="utf-8"))["events"]
    scale = float(res["align"]["scale"])
    offset = float(res["align"]["offset"])
    slots = RA.build_slots(score)

    pairs, index = RA._pair_candidates(events, slots, score, scale=scale, windows=True)
    judged = json.load(io.open(os.path.join(jobdir, "judged_win.json"),
                               encoding="utf-8"))["judged"]
    assert len(pairs) == len(judged), (len(pairs), len(judged))

    mp = os.path.join(jobdir, "match.json")
    preds = None
    if os.path.exists(mp):
        m = json.load(io.open(mp, encoding="utf-8"))
        preds = [None] * len(slots)
        for p in m["match"]:
            preds[p["slot"]] = p["pred_t"]
    per = {}
    for (i, s, k), jd in zip(index, judged):
        pred = preds[s] if (preds and preds[s] is not None) else (slots[s]["t"] * scale + offset)
        dt = abs(events[i]["t"] - pred)
        if dt > RA.PAIR_MATCH_WIN:
            continue
        per.setdefault((i, s), []).append((jd, dt))
    print("slot  t       midi  可选配对（起音时刻 / 判定 / 全局偏差）")
    for s in range(s0, min(s1 + 1, len(slots))):
        opts = []
        for (i, ss), v in per.items():
            if ss != s:
                continue
            pred = preds[s] if (preds and preds[s] is not None) else (slots[s]["t"] * scale + offset)
            dt = abs(events[i]["t"] - pred)
            npass = sum(1 for jd, _ in v if jd["pass"])
            opts.append((events[i]["t"], npass, len(v), dt, i))
        opts.sort()
        print("  %-4d %-7.3f %-5s" % (s, slots[s]["t"],
                                      ",".join(str(score[j]["midi"]) for j in slots[s]["notes"])))
        for t, npass, n, dt, i in opts:
            w = None
            if (i, s) in per:
                w = sum((2.0 if jd["pass"] else -0.30) for jd, _ in per[(i, s)]) - dt * 0.5 * n
            print("        起音 %.3f (i=%d)  过 %d/%d  局部偏差 %4.0fms  W=%s"
                  % (t, i, npass, n, dt * 1000, None if w is None else round(w, 2)))


if __name__ == "__main__":
    main()
