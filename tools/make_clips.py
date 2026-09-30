# -*- coding: utf-8 -*-
"""把"报告里出问题的那几处"剪成小段音频 + 生成一个能直接听的网页。

用法：E:\\Python\\python.exe -X utf8 tools\\make_clips.py <jobdir> [<jobdir2> ...]

产出：
  · data/clips/<job>/<编号>_<秒>s_<音名>[_对照].wav   —— 22.05kHz 单声道，任何播放器都能放
  · <项目>/web/listen.html                            —— 每段一个播放器（音频内嵌成 base64，
                                                        免得服务器 MIME 不给 wav）
每段剪的是 [该处 −0.9s, 该处 +1.7s]（2.6 秒），目标音在 0.9 秒处。
另外给每一处配 1~2 条**对照**：同一根弦同一个音、机器没报问题的那些 —— 好对比。
"""
import base64
import io
import json
import os
import struct
import sys
import wave

import numpy as np

SR = 48000
OUT_SR = 24000          # 48k 两两平均 → 24k；**必须按 24k 写头**，否则会变调
PRE, POST = 0.9, 1.7
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXTRA = {
    "F-6415": [(9.94, 64, 3, 0, "机器在这里量到 E4 抬头（疑似真正的起音）")],
    "F-6415f": [(13.78, 55, 3, 0, "流水线实际用的那个起音")],
}


def name_of(midi):
    return "%s%d" % (NAMES[int(midi) % 12], int(midi) // 12 - 1)


def wav_bytes(x):
    n = int(len(x) / 2)
    y = x[:n * 2].reshape(-1, 2).mean(axis=1)          # 简单降采样 48k → 24k（采样率按 24k 写头）
    pcm = np.clip(y, -1, 1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(OUT_SR)
        w.writeframes(b"".join(struct.pack("<h", int(v * 32767)) for v in pcm))
    return buf.getvalue()


def clip_from(x, t):
    a = max(0, int((t - PRE) * SR))
    b = min(len(x), int((t + POST) * SR))
    return x[a:b], a / float(SR)


def build(jobdir):
    res = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
    ref = json.load(io.open(res["ref_used"], encoding="utf-8"))["notes"]
    scale, offset = float(res["align"]["scale"]), float(res["align"]["offset"])
    x = np.frombuffer(io.open(res["audio"], "rb").read(), dtype=np.float32)
    job = os.path.basename(jobdir)

    items = []          # (秒, midi, 弦, 品, 说明, 是否对照)
    for it in res.get("issues", []):
        if it.get("kind") not in ("missing_note", "wrong_note"):
            continue
        inner = (it.get("items") or [{}])[0]
        if it.get("t_score") is None or inner.get("want_midi") is None:
            continue
        t = float(it["t_score"]) * scale + offset
        items.append((t, int(inner["want_midi"]), inner.get("string"), inner.get("fret"),
                      "%s（谱面 %.2fs · 要 %s）" % (
                          "机器报：漏" if it["kind"] == "missing_note"
                          else "机器报：" + (it.get("detail") or "错"),
                          it["t_score"], name_of(inner["want_midi"])), False))
    for t, midi, s, f, why in EXTRA.get(job, []):
        items.append((t, midi, s, f, why, False))

    # 对照：同一根弦同一个品、机器没报的其它位置（每处挑最近的 1~2 个）
    flagged = [it[0] for it in items]
    used_ctl = []
    for t, midi, s, f, why, _ in list(items):
        n = 0
        for note in ref:
            if note.get("string") != s or note.get("fret") != f:
                continue
            tt = float(note["t"]) * scale + offset
            if tt < 1.0 or any(abs(tt - g) < 0.6 for g in flagged + used_ctl):
                continue
            used_ctl.append(tt)
            items.append((tt, int(note["midi"]), s, f,
                          "对照：同一个音（%s，%d弦%d品），机器没报问题" % (
                              name_of(note["midi"]), s, f), True))
            n += 1
            if n >= 1:
                break

    out_dir = os.path.join(ROOT, "data", "clips", job)
    os.makedirs(out_dir, exist_ok=True)
    clips = []
    for i, (t, midi, s, f, why, is_ref) in enumerate(items, 1):
        seg, start = clip_from(x, t)
        data = wav_bytes(seg)
        nm = "%02d_%.2fs_%s%s.wav" % (i, t, name_of(midi), "_对照" if is_ref else "")
        with open(os.path.join(out_dir, nm), "wb") as fp:
            fp.write(data)
        clips.append({"t": t, "start": start, "name": name_of(midi), "why": why,
                      "ref": is_ref, "file": nm, "b64": base64.b64encode(data).decode()})
        print("  %s  (%.2fs, %s)" % (nm, t, name_of(midi)))
    return job, res, clips


def main():
    jobs = sys.argv[1:]
    blocks = []
    for jobdir in jobs:
        blocks.append(build(jobdir))

    html = ["""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>作业检查 · 听这几处</title><style>
body{margin:0;padding:22px 26px 70px;background:#14161a;color:#e9edf2;
     font:15px/1.7 "Microsoft YaHei",system-ui,sans-serif}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:30px 0 4px;color:#ffd479}
.sub{color:#9aa3ae;font-size:13.5px;margin:0 0 10px}
.clip{background:#1b2026;border:1px solid #2b323a;border-radius:10px;padding:10px 14px;margin:10px 0}
.clip.ref{border-color:#2e4a2e}
.ttl{font-weight:600;margin-bottom:6px}
.ref .ttl{color:#8fdd8f}
audio{width:100%;max-width:620px;height:34px}
a{color:#8ad}.note{color:#c7cdd6}
</style></head><body>
<h1>听这几处</h1>
<p class="sub">每段 2.6 秒，<b>目标音在 0.9 秒处</b>。绿色的那几条是<b>对照</b>：同一根弦同一个音、机器没报问题的。
   和频谱图对照着看：<a href="spectro.html">看频谱图</a></p>
"""]
    for job, res, clips in blocks:
        c = res["counts"]
        html.append('<h2>%s ｜ %s 分（对%d 错%d 漏%d 多弹%d）</h2>'
                    % (job, res.get("score"), c["ok"], c["wrong_note"],
                       c["missing"], c["extra"]))
        html.append('<p class="sub">%s</p>' % os.path.basename(res["audio"]))
        for k, cl in enumerate(clips, 1):
            html.append(
                '<div class="clip%s"><div class="ttl">%d) %.2fs ｜ 期望 %s</div>'
                '<div class="note">%s</div>'
                '<audio controls preload="none" src="data:audio/wav;base64,%s"></audio></div>'
                % (" ref" if cl["ref"] else "", k, cl["t"], cl["name"], cl["why"], cl["b64"]))
    html.append("</body></html>")
    out = os.path.join(ROOT, "web", "listen.html")
    with io.open(out, "w", encoding="utf-8") as fp:
        fp.write("".join(html))
    print("网页写到 %s（%.1f MB）" % (out, os.path.getsize(out) / 1048576.0))


if __name__ == "__main__":
    main()
