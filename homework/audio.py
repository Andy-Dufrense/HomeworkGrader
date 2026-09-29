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


def lead_in_seconds(tempo):
    """跟弹开始时要数**四拍**才开始判（`phase='countin'`）。

    学员自己在家录的音频往往一点就弹，开头那几秒会被这四拍吃掉 —— 表现就是
    "我就少弹了一个音，前几个音却全说我错"（2026-09-29 在 Hey Jude 那条录音上量到：
    不补前导 → 判错 9 处、其中 1/2/3 号格是假的；补 4 拍 → 判错 6 处，前三个不报了）。
    所以解码时**统一在前面补够四拍静音**，后面判定就不受"学员留了多长前奏"影响。
    """
    return 4.0 * 60.0 / float(tempo or 76)


def first_attack_seconds(audio, sr=SR, win_sec=0.05):
    """粗略找"第一声真的开始弹"的时刻 —— 只看能量，不做任何判定。

    用法：判定要数四拍才开工，学员如果一点就弹，开头会被吃掉；我们按这个时刻
    决定要不要在前面补静音（补到"第一声刚好落在倒数之后"）。
    """
    import numpy as np

    win = int(sr * win_sec)
    if win <= 0 or len(audio) < win:
        return 0.0
    rms = np.sqrt(np.mean(audio[:len(audio) // win * win].reshape(-1, win) ** 2, axis=1))
    peak = float(rms.max()) if len(rms) else 0.0
    if peak <= 0:
        return 0.0
    thr = max(0.02, 0.25 * peak)
    idx = np.argmax(rms >= thr)
    return float(idx) * win_sec if rms[idx] >= thr else 0.0


def decode_to_f32(src, dst, sr=SR, lead_in=0.0):
    """解码成 48k 单声道 f32（可选在前面补 lead_in 秒静音）；返回时长（秒）。

    lead_in=None 表示**按需补**：只把"第一声"补到倒数之后，不多补。
    """
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
    if lead_in is None:
        lead_in = 0.0
    if lead_in > 0:
        audio = np.concatenate([np.zeros(int(sr * lead_in), dtype="<f4"), audio])
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
    lead = 0.0
    if "--lead-in" in argv:
        i = argv.index("--lead-in")
        v = argv[i + 1]
        if v == "auto":
            tempo = 76.0
            if "--tempo" in argv:
                tempo = float(argv[argv.index("--tempo") + 1])
            need = lead_in_seconds(tempo) + 0.4          # 四拍 + 一点余量
            probe = decode_to_f32(src, dst, lead_in=0.0)  # 先解出来量第一声
            import numpy as np
            first = first_attack_seconds(np.fromfile(dst, dtype="<f4"))
            lead = max(0.0, need - first)
        else:
            lead = float(v)
    secs = decode_to_f32(src, dst, lead_in=lead)
    print("解码完成：%s → %s（%.1f 秒，48000Hz 单声道 f32%s）"
          % (src, dst, secs, "，前面补了 %.2f 秒静音" % lead if lead else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
