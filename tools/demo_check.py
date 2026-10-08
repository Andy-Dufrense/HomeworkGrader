# -*- coding: utf-8 -*-
"""按"预想结果"核对用户的 demo 录音（学跟弹那边"导出 JSON 对照预想"的做法）。

用户的说明文档（demo/demo说明.md）就是**预想结果**——他说了算。这个工具做三件事：
  1) 每条录音跑一遍批改（run_assignment.py）
  2) 每条写一份明细 JSON：期望 / 实际（分、对错漏多、逐条问题、对齐参数）
  3) 打一张总表：一眼看出哪几条跟预想不一样

用法：
    E:\\Python\\python.exe -X utf8 tools\\demo_check.py            :: 全部
    E:\\Python\\python.exe -X utf8 tools\\demo_check.py 音阶 小星星  :: 只跑名字里带这些字的

产物： data/demo_report/<录音名>.json  + data/demo_report/_summary.json
"""

import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.join(ROOT, "demo", "1弦0品-很轻等31项文件")
F32 = os.path.join(ROOT, "data", "audio", "demo-f32")
OUT = os.path.join(ROOT, "data", "demo_report")
PY = r"E:\Python\python.exe"

# 录音 → (批哪份作业, 预想结果——照 demo说明.md 抄的)
CASES = {
    # ── B 类：整段演奏 ─────────────────────────────────────────────
    "1645-T3231323（有错音）": ("1645-T3231323", "错音 2 处：C 和弦第 2 次 2弦1品→0品；Am 和弦最后一次 3弦2品→0品"),
    "1645-T4231323": ("1645-T3231323", "弹 4 弦不弹 3 弦 → 应报出这个位置的错"),
    "C调音阶E2-G4-正常": ("c-major-scale-1st", "正常（无错无漏）"),
    "C调音阶E2-G4-漏音": ("c-major-scale-1st", "只漏 1 个音：第一遍的 4弦3品 F3"),
    "爬格子-正常": ("chromatic-1234", "正常 + 只弹了前半段（应报没弹完 + 弹过那段的对错）"),
    "爬格子-磕巴": ("chromatic-1234", "磕巴 + 只弹了前半段（应报没弹完 + 弹过那段的对错）"),
    "hey jude-错误": ("hey-jude-full", "没弹完（用户确认）；第 11 小节拖拍、第 16 小节抢拍"),
    "小星星-低音-正常": ("twinkle-low", "正常（无错无漏）"),
    "小星星-低音-错误": ("twinkle-low", "第 2 小节开头弹成 3弦3品又改；后面越弹越快 + 明显空拍"),
    "小星星-低音-节奏忽快忽慢": ("twinkle-low", "无错音无漏音，只报节奏不稳"),
    "15634125-正常": ("15634125-T3231323", "正常"),
    "15634125-快速": ("15634125-T3231323", "无错、速度较快"),
    "15634125-双音正常": ("15634125-dyad", "正常（双音 T3〔12〕3，每和弦两遍）"),
    "15634125-双音快速": ("15634125-dyad", "无错、快速"),
    "4536251-正常-分解": ("4536251-T3231323", "正常"),
    "4536251-正常-双音": ("4536251-dyad-once", "正常（双音，每和弦一遍）"),
    "4536251-错误-分解": ("4536251-T3231323", "3 处指定错：Em7 2弦3品 / Am7 3弦0品 / Dm7 2弦1品；2 级还有 1 个没弹响"),
}


def run_one(name, aid, want):
    job = "dc-" + name.replace("/", "_").replace("（", "(").replace("）", ")")
    audio = os.path.join(F32, name + ".f32")
    if not os.path.exists(audio):
        return {"name": name, "aid": aid, "want": want, "error": "没有解码好的 f32"}
    p = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "homework", "run_assignment.py"),
                        "--assignment", aid, "--audio", audio, "--job", job],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    jobdir = os.path.join(ROOT, "data", "jobs", job)
    page = json.load(io.open(os.path.join(jobdir, "page.json"), encoding="utf-8"))
    rich = json.load(io.open(os.path.join(jobdir, "result.json"), encoding="utf-8"))
    rec = {"name": name, "aid": aid, "want": want, "job": job,
           "rc": p.returncode,
           "gate": (page.get("gate") or {}).get("kind"),
           "played": (page.get("gate") or {}).get("played"),
           "score": page.get("score"), "counts": page.get("counts"),
           "align": rich.get("align"), "process": page.get("process"),
           "issues": [{"title": it.get("title"), "kind": it.get("kind"), "detail": it.get("detail")}
                      for it in (page.get("issues") or [])]}
    with io.open(os.path.join(OUT, (name.replace("/", "_") + ".json")), "w",
                 encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return rec


def main(argv):
    want_filters = argv or []
    os.makedirs(OUT, exist_ok=True)
    out = []
    for name, (aid, exp) in CASES.items():
        if want_filters and not any(w in name for w in want_filters):
            continue
        r = run_one(name, aid, exp)
        out.append(r)
        if r.get("error"):
            print("  %-26s !! %s" % (name, r["error"]))
        elif r.get("gate"):
            pl = r.get("played") or {}
            print("  %-26s 闸门 %-12s %s" % (
                name, r["gate"],
                ("弹过: 对%s 错%s 到第%s小节" % (pl.get("ok"), pl.get("wrong"), pl.get("at_bar")))
                if pl else ""))
        else:
            c = r["counts"] or {}
            print("  %-26s %5s 分 scale=%-6s 对%-3s 错%-2s 漏%-3s 多%-3s | 预想：%s" % (
                name, r["score"], (r["align"] or {}).get("scale"),
                c.get("right"), c.get("wrong"), c.get("missing"), c.get("extra"), r["want"]))
    with io.open(os.path.join(OUT, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n明细已写到 %s（每条一份 + _summary.json）" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
