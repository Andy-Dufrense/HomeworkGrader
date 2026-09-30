# -*- coding: utf-8 -*-
"""临时探针：在某个时刻取一扇窗，列出 40~1200Hz 里最强的几根谱线（带音名）。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_peaks.py <f32> <t秒> <窗长ms> [向后/居中]
  向后（默认）= 窗从 t 开始往后取；居中 = 窗以 t 为中心。
"""
import io
import sys

import numpy as np

SR = 48000
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def name_of(hz):
    if hz <= 0:
        return "-"
    m = 69 + 12 * np.log2(hz / 440.0)
    mi = int(round(m))
    cents = int(round((m - mi) * 100))
    return "%s%d%+d" % (NAMES[mi % 12], mi // 12 - 1, cents)


def main():
    path, t, win_ms = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    mode = sys.argv[4] if len(sys.argv) > 4 else "after"
    x = np.frombuffer(io.open(path, "rb").read(), dtype=np.float32)
    n = int(SR * win_ms / 1000.0)
    start = int(t * SR) - (n // 2 if mode == "center" else 0)
    start = max(0, min(len(x) - n, start))
    seg = x[start:start + n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    band = (freqs >= 60) & (freqs <= 1200)
    idx = np.where(band)[0]
    order = idx[np.argsort(mag[idx])[::-1]]
    kept = []
    for i in order:
        f = freqs[i]
        if any(abs(f - g) < SR / n * 1.5 for g in kept):
            continue
        kept.append(f)
        if len(kept) >= 8:
            break
    print("t=%.3f 窗 %.0fms（%s，bin %.2fHz）最强谱线：" % (t, win_ms, mode, SR / float(n)))
    for f in kept:
        i = int(round(f / (SR / float(n))))
        db = 20 * np.log10(max(mag[i], 1e-9) / max(mag.max(), 1e-9))
        print("   %7.1fHz  %-8s %6.1f dB" % (f, name_of(f), db))


if __name__ == "__main__":
    main()
