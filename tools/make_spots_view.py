# -*- coding: utf-8 -*-
"""把「报告里出问题的那几处」画成声谱图，标出来给用户看。

用法：E:\\Python\\python.exe -X utf8 tools\\make_spots_view.py <jobdir> <输出.png>

图上三样东西：
  · 上半：声谱图（60~800Hz，低音弦半音只差 5~12Hz，看这个频段才看得清）
  · 横线：那一处谱面**期望音**的基频（同色对应同一条竖线）
  · 竖线：报告里报出来的那几处（红虚线，编号①）
  · 下半：60~800Hz 的能量包络 + 绿色三角 = 引擎自己报出来的起音
    （所以"红虚线那里没有绿三角"= 起音层漏检，一眼可见）
"""
import io
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

SR = 48000
F_LO, F_HI = 60, 800
WIN, HOP = 2048, 512
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 手工补的说明（jobdir 名 → [(秒, midi, 说明)]）
EXTRA = {
    "F-6415": [(9.94, 64, "机器在这里量到 E4 抬头（实际起音）")],
    "F-6415f": [(13.78, 55, "流水线实际用的那个起音")],
}


def name_of(midi):
    return "%s%d" % (NAMES[int(midi) % 12], int(midi) // 12 - 1)


def main():
    jobdir, out = sys.argv[1], sys.argv[2]
    res = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
    ev = json.load(io.open(os.path.join(jobdir, "events.json"), encoding="utf-8"))["events"]
    scale, offset = float(res["align"]["scale"]), float(res["align"]["offset"])
    audio = res["audio"]
    x = np.frombuffer(io.open(audio, "rb").read(), dtype=np.float32)
    dur = len(x) / float(SR)

    n = (len(x) - WIN) // HOP
    freqs = np.fft.rfftfreq(WIN, 1.0 / SR)
    band = (freqs >= F_LO) & (freqs <= F_HI)
    spec = np.zeros((band.sum(), n), dtype=np.float32)
    hann = np.hanning(WIN)
    for k in range(n):
        mag = np.abs(np.fft.rfft(x[k * HOP:k * HOP + WIN] * hann))[band]
        spec[:, k] = mag
    times = (np.arange(n) * HOP + WIN / 2) / float(SR)
    db = 20 * np.log10(np.maximum(spec, 1e-7))
    db -= db.max()
    env = spec.mean(axis=0)
    env /= max(env.max(), 1e-9)

    marks = []
    for it in res.get("issues", []):
        if it.get("kind") not in ("missing_note", "wrong_note"):
            continue
        inner = (it.get("items") or [{}])[0]
        if it.get("t_score") is None or inner.get("want_midi") is None:
            continue
        marks.append((float(it["t_score"]) * scale + offset, int(inner["want_midi"]),
                      "%s · 谱面 %.2fs · 要 %s" % (it["detail"], it["t_score"],
                                                name_of(inner["want_midi"]))))
    marks += EXTRA.get(os.path.basename(jobdir), [])

    fig = plt.figure(figsize=(17, 8.5), dpi=110)
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.12)
    ax = fig.add_subplot(gs[0])
    ax.imshow(db, origin="lower", aspect="auto", cmap="magma",
              extent=[0, dur, F_LO, F_HI], vmin=-60, vmax=0)
    ax.set_ylabel("频率 Hz")
    ax.set_title("%s ｜ %s ｜ 报告 %s 分（对%d 错%d 漏%d 多弹%d）"
                 % (os.path.basename(audio), os.path.basename(jobdir), res.get("score"),
                    res["counts"]["ok"], res["counts"]["wrong_note"],
                    res["counts"]["missing"], res["counts"]["extra"]))
    ax.set_xlim(0, dur)

    colors = ["#ff3b30", "#00d0ff", "#ffe000", "#7dff6b"]
    for idx, (t, midi, label) in enumerate(marks):
        c = colors[idx % len(colors)]
        f0 = 440.0 * 2 ** ((midi - 69) / 12.0)
        ax.axvline(t, color=c, ls="--", lw=1.6)
        ax.text(t, F_HI * 0.93, "%d) %.2fs" % (idx + 1, t), color=c, fontsize=11,
                ha="left", va="top", bbox=dict(fc="black", alpha=0.55, ec="none"))
        if F_LO < f0 < F_HI:
            ax.axhline(f0, color=c, ls=":", lw=1.2, alpha=0.85)
            ax.text(dur * 0.995, f0, " %s(%.0fHz) " % (name_of(midi), f0), color=c,
                    fontsize=10, ha="right", va="bottom",
                    bbox=dict(fc="black", alpha=0.55, ec="none"))

    ax2 = fig.add_subplot(gs[1], sharex=ax)
    ax2.plot(times, env, color="#8ad", lw=1.0)
    on = [float(e["t"]) for e in ev]
    ax2.plot(on, [env[min(n - 1, int(t / dur * n))] for t in on], "g^", ms=7,
             label="引擎报出来的起音")
    for idx, (t, midi, label) in enumerate(marks):
        ax2.axvline(t, color=colors[idx % len(colors)], ls="--", lw=1.6)
    ax2.set_ylabel("60~800Hz 能量")
    ax2.set_xlabel("时间 秒")
    ax2.legend(loc="upper right", fontsize=9)
    plt.setp(ax.get_xticklabels(), visible=False)

    txt = "   ".join("%d) %.2fs %s" % (i + 1, m[0], m[2]) for i, m in enumerate(marks))
    fig.text(0.01, 0.012, txt, fontsize=10.5, color="#222", wrap=True)
    fig.subplots_adjust(bottom=0.13)
    fig.savefig(out)
    print("写出 %s（%d 处标记）" % (out, len(marks)))
    for i, m in enumerate(marks):
        print("  %d) %.2fs  期望 %s" % (i + 1, m[0], name_of(m[1])))


if __name__ == "__main__":
    main()
