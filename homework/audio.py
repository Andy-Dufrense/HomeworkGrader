# -*- coding: utf-8 -*-
"""作业检查 · 音频解码：学员交上来的任何音频 → 跟弹链路要的 48k 单声道 f32。

为什么要有这一步：跟弹那一侧的判定链路（`test-follow-real.mjs`）读的是**裸 f32**
（48000Hz、单声道、小端 float32，没有文件头）。学员交上来的是 mp3/m4a/wav 甚至手机视频，
得先解码成同一种格式，判定才不会拿到一坨噪声。

用 PyAV（E:\\Lib\\site-packages 里有，和 VirtuCoach 用同一套），所以跑之前要带 PYTHONPATH：

    set PYTHONPATH=E:\\Lib\\site-packages
    E:\\Python\\python.exe -X utf8 homework\\audio.py <输入> <输出.f32>

只做解码和重采样，不降噪、不分离音轨 —— 那些是 Q10/Q27 的事，还没做。
"""

import os
import sys

SR = 48000


def decode_to_f32(src, dst, sr=SR):
    """解码成 48k 单声道 f32；返回时长（秒）。"""
    import av                      # 只有带 PYTHONPATH 时才 import 得到
    import numpy as np

    container = av.open(src)
    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        raise SystemExit("这个文件里没有音频轨道：%s" % src)
    stream.rate = sr
    stream.layout = "mono"
    resampler = av.AudioResampler(format="flt", layout="mono", rate=sr)
    chunks = []
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):          # 把重采样器里的尾巴冲出来
        chunks.append(out.to_ndarray().reshape(-1))
    container.close()
    if not chunks:
        raise SystemExit("解码出来是空的：%s" % src)
    audio = np.concatenate(chunks).astype("<f4")
    d = os.path.dirname(os.path.abspath(dst))
    if d:
        os.makedirs(d, exist_ok=True)
    audio.tofile(dst)
    return len(audio) / float(sr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    secs = decode_to_f32(src, dst)
    print("解码完成：%s → %s（%.1f 秒，48000Hz 单声道 f32）" % (src, dst, secs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
