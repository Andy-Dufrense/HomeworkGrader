# -*- coding: utf-8 -*-
"""量「对齐」：把真机录音的起音对到 .gp 时间轴上，看误差有多大。

为什么先做这个：调研里 2025 年那篇 Polytune 点名批评「先对齐再比较」的路子会被
对齐误差带偏。所以动手写批改之前，先把「对齐到底差多少毫秒」量出来。

这一版量两件事：
  ① 只允许整体位移（offset）时的残差分布；
  ② 允许整体位移 + 整体速度比例（scale）时的残差分布。
  两者一比，就知道「允许放慢」这条铁律到底有没有必要（以及比例是不是 1.0）。

用法：
    E:\\Python\\python.exe -X utf8 tools\\probe_align.py
"""

import argparse
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "score": r"E:\GuitarFollowLab\frontend\data\hey_jude.json",
    "onsets": r"C:\Users\Administrator\vc_gf\onsets-heyjude.json",
    "labels": r"C:\Users\Administrator\vc_gf\heyjude-labels.json",
}

NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nm(midi):
    midi = int(round(midi))
    return "%s%d" % (NOTE[midi % 12], midi // 12 - 1)


def load(path):
    if not os.path.exists(path):
        sys.exit("找不到文件：%s" % path)
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def score_times(score):
    return sorted(float(n["t"]) for n in score["notes"])


def nearest_residual(t_audio, times, offset, scale):
    best, best_r = None, None
    for t in times:
        r = t_audio - (offset + scale * t)
        if best_r is None or abs(r) < abs(best_r):
            best, best_r = t, r
    return best, best_r


def evaluate(onsets, times, offset, scale, window=0.30):
    res = []
    for t in onsets:
        _, r = nearest_residual(t, times, offset, scale)
        if abs(r) <= window:
            res.append(r)
    return len(res), res


def pct(vals, p):
    if not vals:
        return float("nan")
    vals = sorted(vals)
    i = min(len(vals) - 1, int(round((len(vals) - 1) * p)))
    return vals[i]


def search_offset(onsets, times, scale, lo=-6.0, hi=8.0, step=0.002):
    """在 offset 上粗搜：匹配得多、中位残差小者胜。"""
    best_o, best_key = None, None
    o = lo
    while o <= hi:
        n, res = evaluate(onsets, times, o, scale)
        absr = sorted(abs(r) for r in res)
        med = absr[len(absr) // 2] if absr else 9.9
        key = (-n, med)
        if best_key is None or key < best_key:
            best_o, best_key = o, key
        o += step
    return best_o, best_key


def search_scale(onsets, times, around, lo=0.80, hi=1.25, step=0.002):
    """再在速度比例上搜：每个比例下先把 offset 精对一遍。"""
    best, best_key = None, None
    s = lo
    while s <= hi:
        o, _ = search_offset(onsets, times, s, lo=around - 0.8, hi=around + 0.8, step=0.004)
        n, res = evaluate(onsets, times, o, s)
        absr = sorted(abs(r) for r in res)
        med = absr[len(absr) // 2] if absr else 9.9
        key = (-n, med)
        if best_key is None or key < best_key:
            best, best_key = (o, s), key
        s += step
    return best, best_key


def show(title, onsets, times, offset, scale, matched, res, total_onsets):
    absr = [abs(r) * 1000 for r in res]
    print("")
    print("── %s ──" % title)
    print("  整体位移 offset = %+.3f s ｜ 速度比例 scale = %.4f" % (offset, scale))
    print("  起音 %d 个：对得上 %d，对不上 %d（窗口 ±300ms）"
          % (total_onsets, matched, total_onsets - matched))
    if not absr:
        print("  残差：没有可统计的样本")
        return
    print("  残差绝对值：中位 %.0f ms ｜ p90 %.0f ms ｜ 最大 %.0f ms ｜ 均值 %.0f ms"
          % (pct(absr, 0.5), pct(absr, 0.9), max(absr), statistics.mean(absr)))
    signed = [r * 1000 for r in res]
    print("  残差带符号：中位 %+.0f ms（正=弹晚）｜ 最早 %.0f ｜ 最晚 %+.0f"
          % (statistics.median(signed), min(signed), max(signed)))
    for w in (50, 100, 200):
        k = sum(1 for a in absr if a <= w)
        print("    在 ±%3dms 内：%3d/%d（%.0f%%）" % (w, k, matched, 100.0 * k / matched))
    half = len(res) // 2
    if half >= 4:
        head = statistics.median([abs(r) * 1000 for r in res[:half]])
        tail = statistics.median([abs(r) * 1000 for r in res[half:]])
        print("  漂移：前半段中位 %.0f ms ｜ 后半段中位 %.0f ms" % (head, tail))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", default=DEFAULTS["score"])
    ap.add_argument("--onsets", default=DEFAULTS["onsets"])
    ap.add_argument("--labels", default=DEFAULTS["labels"])
    args = ap.parse_args()

    score = load(args.score)
    times = score_times(score)
    on = load(args.onsets)
    onsets = [float(t) for t in (on["onsets"] if isinstance(on, dict) else on)]
    track = (score.get("meta", {}) or {}).get("track", {}) or {}

    print("=" * 72)
    print("对齐探针：录音起音 × .gp 时间轴")
    print("=" * 72)
    print("谱面  %s｜%d 个音｜%.2f~%.2f s｜轨 %s"
          % (os.path.basename(args.score), len(times), times[0], times[-1],
             track.get("name", "?")))
    print("起音  %s｜%d 个｜%.2f~%.2f s"
          % (os.path.basename(args.onsets), len(onsets), min(onsets), max(onsets)))

    o1, _ = search_offset(onsets, times, 1.0)
    n1, r1 = evaluate(onsets, times, o1, 1.0)
    show("① 只允许整体位移（scale 固定 1.0）", onsets, times, o1, 1.0, n1, r1, len(onsets))

    (o2, s2), _ = search_scale(onsets, times, o1)
    n2, r2 = evaluate(onsets, times, o2, s2)
    show("② 允许整体位移 + 速度比例", onsets, times, o2, s2, n2, r2, len(onsets))

    if os.path.exists(args.labels):
        lab = load(args.labels)
        notes = sorted(lab["notes"], key=lambda x: float(x["t"]))
        print("")
        print("── ③ 手标交叉验证：%s（%d 个音，offsetMs=%s）──"
              % (os.path.basename(args.labels), len(notes), lab.get("offsetMs")))
        same = diff = 0
        for n in notes:
            t_audio = float(n["t"])
            t_score, r = nearest_residual(t_audio, times, o2, s2)
            near = min(score["notes"], key=lambda x: abs(float(x["t"]) - t_score))
            exp = int(n["midi"])
            hit = int(round(near["midi"])) == exp
            if hit:
                same += 1
            else:
                diff += 1
            print("   音频 %6.2fs｜标注 %-4s｜最近谱面 %-4s（第%.2fs）｜残差 %+6.0f ms｜%s"
                  % (t_audio, nm(exp), nm(near["midi"]), t_score, r * 1000,
                     "一致" if hit else "★不一致"))
        print("   一致 %d ／ 不一致 %d" % (same, diff))

        # ④ 换个更硬的办法：不信"最近音"，改成按**音的身份**（弦+品+音名）反推 offset。
        #    每个标注音在谱面上可能有多个同身份的候选（同一个音反复出现），
        #    把所有候选的隐含 offset 都列出来，再看哪个 offset 能让最多标注音对上号。
        print("")
        print("── ④ 身份匹配诊断：按 弦/品/音名 反推 offset ──")
        cand_offsets = []
        for n in notes:
            t_audio = float(n["t"])
            same_note = [x for x in score["notes"]
                         if int(x.get("string") or 0) == int(n["str"])
                         and int(x.get("fret") or 0) == int(n["fret"])
                         and int(round(x["midi"])) == int(n["midi"])]
            offs = sorted(round(t_audio - float(x["t"]), 3) for x in same_note)
            cand_offsets.append((t_audio, nm(int(n["midi"])), offs))
            print("   音频 %6.2fs｜%s｜候选 offset: %s"
                  % (t_audio, nm(int(n["midi"])), ", ".join("%+.2f" % o for o in offs) or "（谱面没有同身份的音）"))

        # 在 offset 网格上数：多少个标注音能找到一个候选落在 ±120ms 内
        best_o, best_hits = None, -1
        o = -4.0
        while o <= 8.0:
            hits = sum(1 for _, _, offs in cand_offsets
                       if any(abs(o - x) <= 0.12 for x in offs))
            if hits > best_hits:
                best_o, best_hits = o, hits
            o += 0.01
        print("   最好的一致性：offset ≈ %+.2f s 时，%d/%d 个标注音能对上号"
              % (best_o, best_hits, len(cand_offsets)))
        for tol in (0.05, 0.12, 0.25):
            hits = sum(1 for _, _, offs in cand_offsets
                       if any(abs(best_o - x) <= tol for x in offs))
            print("     容差 ±%d ms：%d/%d" % (tol * 1000, hits, len(cand_offsets)))

        # ⑤ 在共识 offset 下，用身份锚定重算残差 —— 这才是可信的「对齐误差」。
        #    ① ② 两节是拿起音表盲拟合出来的 offset，已被 ④ 判为不可信（差 0.4~1.1 秒）。
        print("")
        print("── ⑤ 身份锚定后的残差（offset 固定 %.2f s）──" % best_o)
        rows = []
        for n in notes:
            t_audio = float(n["t"])
            same_note = [x for x in score["notes"]
                         if int(x.get("string") or 0) == int(n["str"])
                         and int(x.get("fret") or 0) == int(n["fret"])
                         and int(round(x["midi"])) == int(n["midi"])]
            if not same_note:
                continue
            pick = min(same_note, key=lambda x: abs((t_audio - float(x["t"])) - best_o))
            r = t_audio - (best_o + float(pick["t"]))
            rows.append((t_audio, float(pick["t"]), r))
        absr = sorted(abs(r) * 1000 for _, _, r in rows)
        if absr:
            print("   %d 个标注音，残差绝对值：中位 %.0f ms ｜ p90 %.0f ms ｜ 最大 %.0f ms"
                  % (len(absr), pct(absr, 0.5), pct(absr, 0.9), max(absr)))
            signed = [r * 1000 for _, _, r in rows]
            print("   带符号：中位 %+.0f ms（正=弹晚）｜ 最早 %.0f ｜ 最晚 %+.0f"
                  % (statistics.median(signed), min(signed), max(signed)))
            for w in (50, 100, 200):
                k = sum(1 for a in absr if a <= w)
                print("     在 ±%3dms 内：%2d/%d（%.0f%%）" % (w, k, len(absr), 100.0 * k / len(absr)))


if __name__ == "__main__":
    main()
