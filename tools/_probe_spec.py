# -*- coding: utf-8 -*-
"""临时探针：在某段时间里逐 10ms 打印"高频瞬态 + 几个目标音的谐波能量"，
用来判断某个时刻到底有没有**新拨一下**（起音层漏检 vs 学员真没弹）。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_spec.py <f32> <t0> <t1> <f1,f2,...>
"""
import io
import sys

import numpy as np

SR = 48000


def main():
    path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    targets = [float(x) for x in sys.argv[4].split(",")]
    x = np.frombuffer(io.open(path, "rb").read(), dtype=np.float32)
    n = 2048
    hann = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    hi = (freqs >= 2000) & (freqs <= 6000)
    t = t0
    print("t      2-6kHz   " + "  ".join("%7.0fHz" % f for f in targets))
    while t <= t1:
        i = int(t * SR)
        seg = x[max(0, i - n // 2):max(0, i - n // 2) + n]
        if len(seg) < n:
            break
        mag = np.abs(np.fft.rfft(seg * hann))
        hf = float(np.sqrt((mag[hi] ** 2).sum()) / n)
        vals = []
        binHz = SR / float(n)
        for f in targets:
            k = int(round(f / binHz))
            k = max(1, min(len(mag) - 2, k))
            vals.append(float(max(mag[k - 1], mag[k], mag[k + 1])) / n)
        print("%.3f  %8.5f  " % (t, hf) + "  ".join("%9.5f" % v for v in vals))
        t += 0.01


if __name__ == "__main__":
    main()
