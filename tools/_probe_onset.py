# -*- coding: utf-8 -*-
"""临时探针：在某个时间窗里自己数一遍"有几次拨弦"（能量抬头），看起音层有没有漏。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_onset.py <f32> <t0> <t1>
输出：每一处能量抬头（时间 / 强度），和 engine_bridge 给的起音对照（人工看）。
做法：20ms 窗、5ms 步长的低频带（80~1200Hz）能量，抬头超过中位数的 3 倍就算一次。
"""
import io
import json
import os
import sys

import numpy as np

SR = 48000


def main():
    path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    raw = io.open(path, "rb").read()
    x = np.frombuffer(raw, dtype=np.float32)
    a, b = int(t0 * SR), min(len(x), int(t1 * SR))
    seg = x[a:b]
    win, hop = 960, 240          # 20ms / 5ms
    n = max(1, (len(seg) - win) // hop)
    env = np.zeros(n)
    freqs = np.fft.rfftfreq(win, 1.0 / SR)
    band = (freqs >= 80) & (freqs <= 1200)
    hann = np.hanning(win)
    for k in range(n):
        s = seg[k * hop:k * hop + win] * hann
        mag = np.abs(np.fft.rfft(s))[band]
        env[k] = float(np.sqrt((mag ** 2).sum()))
    flux = np.diff(env, prepend=env[0])
    med = float(np.median(np.abs(flux))) + 1e-9
    times = t0 + (np.arange(n) * hop + win) / float(SR)
    print("窗 %s~%s s：%d 帧，flux 中位 %.3g" % (t0, t1, n, med))
    picks = []
    for k in range(1, n - 1):
        if flux[k] > 3.0 * med and flux[k] >= flux[k - 1] and flux[k] > flux[k + 1]:
            picks.append((times[k], flux[k] / med))
    for t, s in picks:
        print("  抬头 t=%.3f  强度 %.1f×中位" % (t, s))
    print("共 %d 处" % len(picks))


if __name__ == "__main__":
    main()
