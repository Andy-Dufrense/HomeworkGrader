# -*- coding: utf-8 -*-
"""临时探针：量"期望音**自己那条基频线**在不在、有多强"。

用法：E:\\Python\\python.exe -X utf8 tools\\_probe_line.py <f32> <t秒> <期望MIDI> [窗长ms] [atMs]
输出：那条线的 dB（相对窗内最强峰）、窗内最强 5 根线、判定窗的 bin 宽。

为什么用长窗：低音弦一个半音只差 5~12Hz，40ms 窗分不开；683ms 窗的 bin 是 1.46Hz。
"""
import io
import sys

import numpy as np

SR = 48000
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def name_of(hz):
    m = 69 + 12 * np.log2(max(hz, 1e-9) / 440.0)
    mi = int(round(m))
    return "%s%d%+d" % (NAMES[mi % 12], mi // 12 - 1, int(round((m - mi) * 100)))


def mag_at(freqs, mag, hz, bin_hz):
    i = int(round(hz / bin_hz))
    if i < 1 or i >= len(mag) - 1:
        return 0.0
    return float(max(mag[i - 1], mag[i], mag[i + 1]))


def main():
    path, t, midi = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
    win_ms = float(sys.argv[4]) if len(sys.argv) > 4 else 683.0
    at_ms = float(sys.argv[5]) if len(sys.argv) > 5 else 90.0
    x = np.frombuffer(io.open(path, "rb").read(), dtype=np.float32)
    n = int(SR * win_ms / 1000.0)
    end = int((t + at_ms / 1000.0) * SR)
    seg = x[max(0, end - n):end] * np.hanning(n)
    mag = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    bin_hz = SR / float(n)
    band = (freqs >= 60) & (freqs <= 1200)
    peak = float(mag[band].max())
    f0 = 440.0 * 2 ** ((midi - 69) / 12.0)
    score = 0.0
    for k in (1, 2, 3):
        score = max(score, mag_at(freqs, mag, f0 * k, bin_hz))
    db = 20 * np.log10(max(score, 1e-12) / max(peak, 1e-12))
    idx = np.where(band)[0]
    order = idx[np.argsort(mag[idx])[::-1]][:5]
    print("t=%.3fs(+%.0fms) 窗 %.0fms bin %.2fHz ｜ 期望 %s %.1fHz"
          % (t, at_ms, win_ms, bin_hz, name_of(f0), f0))
    print("   期望音那条线（1/2/3 次谐波取最大）：%.1f dB（相对窗内最强峰）" % db)
    print("   窗内最强五根：" + "、".join("%.1fHz(%s) %.1fdB"
          % (freqs[i], name_of(freqs[i]), 20 * np.log10(max(mag[i], 1e-12) / max(peak, 1e-12)))
          for i in order))


if __name__ == "__main__":
    main()
