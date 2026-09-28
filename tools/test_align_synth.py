# -*- coding: utf-8 -*-
"""对齐的合成回归：拿真实谱面造出「已知答案」的录音事件，验 `homework/align.py`。

为什么要这一步：真机素材只有一条（24 个手标音），而且手标本身也是对齐出来的
（`实测-对齐-2026-09-24.md` §4.3 说的局限）。要有可复现的尺子，就得先能造题。
这也是思路第 8 节第 4 步「合成错误回归集」的雏形 —— 跟弹那边 `maketempo.mjs`
的思路一样，先搬过来扩。

跑法：
    cd /d E:\\HomeworkGrader
    E:\\Python\\python.exe -X utf8 tools\\test_align_synth.py
"""

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "homework"))

from align import align, load_score                      # noqa: E402
from grade import aggregate, compare, counts             # noqa: E402

SCORE = os.environ.get(
    "HOMEWORK_SCORE", r"E:\GuitarFollowLab\frontend\data\hey_jude.json")


def make_events(score, offset=0.0, scale=1.0, jitter=0.0, drop=(),
                shift=None, extra=(), strip_identity=False, seed=7):
    """按已知的 (offset, scale) 造事件；shift=错音，drop=漏弹，extra=多弹。"""
    rnd = random.Random(seed)
    events = []
    for j, sn in enumerate(score):
        if j in drop:
            continue
        ev = {
            "t": offset + scale * sn["t"] + rnd.uniform(-jitter, jitter),
            "midi": int(round(sn["midi"])),
            "string": None if strip_identity else sn.get("string"),
            "fret": None if strip_identity else sn.get("fret"),
        }
        if shift and j in shift:
            ev["midi"] = ev["midi"] + shift[j]
        events.append(ev)
    for t, midi in extra:
        events.append({"t": t, "midi": midi, "string": None, "fret": None})
    events.sort(key=lambda e: e["t"])
    return events


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("   " + detail) if detail else ""))


def run_case(title, events, **kw):
    print("")
    print("── %s ──" % title)
    r = align(GLOBAL_SCORE, events, **kw)
    rows = compare(GLOBAL_SCORE, events, r)
    c = counts(rows)
    print("  %s" % r.summary().replace("\n", "\n  "))
    return r, rows, c


def main():
    global GLOBAL_SCORE
    _, GLOBAL_SCORE = load_score(SCORE)
    n = len(GLOBAL_SCORE)
    print("合成回归：谱面 %d 个音（%s）" % (n, os.path.basename(SCORE)))

    # ① 原样：offset 0 / scale 1 / 身份齐全
    ev = make_events(GLOBAL_SCORE)
    r, _, c = run_case("① 原样（offset 0, scale 1）", ev)
    check("① offset≈0", abs(r.offset) <= 0.02, "offset=%+.3f" % r.offset)
    check("① scale≈1", abs(r.scale - 1.0) <= 0.01, "scale=%.4f" % r.scale)
    check("① 全对", c["ok"] == n and c["missing"] == 0 and c["wrong_note"] == 0,
          "ok=%d missing=%d wrong=%d" % (c["ok"], c["missing"], c["wrong_note"]))
    check("① 不该低置信", not r.low_confidence, ",".join(r.warnings))

    # ② 前面空着 2.5s（Q19）
    ev = make_events(GLOBAL_SCORE, offset=2.5)
    r, _, c = run_case("② 晚进 2.5s", ev)
    check("② offset≈2.5", abs(r.offset - 2.5) <= 0.05, "offset=%+.3f" % r.offset)
    check("② 全对", c["ok"] == n, "ok=%d" % c["ok"])

    # ③ 整体放慢 10%（Q21）
    ev = make_events(GLOBAL_SCORE, offset=2.0, scale=1.10)
    r, _, c = run_case("③ 整体放慢 10%", ev)
    check("③ scale≈1.10", abs(r.scale - 1.10) <= 0.02, "scale=%.4f" % r.scale)
    check("③ offset≈2.0", abs(r.offset - 2.0) <= 0.15, "offset=%+.3f" % r.offset)
    check("③ 全对", c["ok"] == n, "ok=%d" % c["ok"])

    # ④ 人弹琴本来就有的抖动（±80ms）
    ev = make_events(GLOBAL_SCORE, offset=2.5, jitter=0.08)
    r, _, c = run_case("④ 抖动 ±80ms", ev)
    check("④ offset≈2.5", abs(r.offset - 2.5) <= 0.05, "offset=%+.3f" % r.offset)
    check("④ 基本全对", c["ok"] >= int(n * 0.95),
          "ok=%d/%d 残差中位 %.0fms" % (c["ok"], n, r.residual_median * 1000))

    # ⑤ 前面空着（漏掉开头 30 个音）—— 谱面覆盖率该掉下来，但不该把后面的音带歪
    ev = make_events(GLOBAL_SCORE, offset=2.5, drop=set(range(30)))
    r, _, c = run_case("⑤ 前面空着（漏掉开头 30 个）", ev)
    check("⑤ 开头 30 个判漏", c["missing"] >= 28, "missing=%d" % c["missing"])
    check("⑤ 后面基本全对", c["ok"] >= (n - 30) - 2, "ok=%d" % c["ok"])
    check("⑤ offset 没被带歪", abs(r.offset - 2.5) <= 0.05, "offset=%+.3f" % r.offset)

    # ⑥ 中间漏 5 个 —— Q17 的"成片要报"
    drop = set(range(40, 45))
    ev = make_events(GLOBAL_SCORE, offset=2.5, drop=drop)
    r, rows, c = run_case("⑥ 中间漏 5 个", ev)
    issues = aggregate(rows)
    check("⑥ 漏弹被认出来", c["missing"] >= 4, "missing=%d" % c["missing"])
    check("⑥ 其余基本全对", c["ok"] >= n - 7, "ok=%d" % c["ok"])
    check("⑥ 成片漏要报", len(issues) >= 1, "issues=%d" % len(issues))

    # ⑦ 多弹（多出来的事件落在没有谱面音的空档里）
    extra = [(2.5 + GLOBAL_SCORE[0]["t"] - 1.2, 64),
             (2.5 + GLOBAL_SCORE[-1]["t"] + 1.2, 67)]
    ev = make_events(GLOBAL_SCORE, offset=2.5, extra=extra)
    r, rows, c = run_case("⑦ 多弹 2 个", ev)
    check("⑦ 多弹被认出来", c["extra"] >= 2, "extra=%d" % c["extra"])
    check("⑦ 谱面全对", c["ok"] == n, "ok=%d" % c["ok"])

    # ⑧ 弹错音（连着 3 个升半音）—— 错音不许把后面的对齐带歪
    shift = {10: 1, 11: 1, 12: 1}
    ev = make_events(GLOBAL_SCORE, offset=2.5, shift=shift)
    r, rows, c = run_case("⑧ 连着 3 个错音", ev)
    check("⑧ 错音被认出来", c["wrong_note"] >= 3, "wrong=%d" % c["wrong_note"])
    check("⑧ 其余全对", c["ok"] >= n - 4, "ok=%d" % c["ok"])
    check("⑧ 错音没有带歪 offset", abs(r.offset - 2.5) <= 0.05,
          "offset=%+.3f" % r.offset)

    # ⑨ 没有身份（只有音名）—— 置信度必须报警，不许硬出结论
    ev = make_events(GLOBAL_SCORE, offset=2.5, strip_identity=True)
    r, _, c = run_case("⑨ 只有音名、没有弦品", ev)
    check("⑨ 低置信度警报", r.low_confidence, ",".join(r.warnings) or "（没报警）")

    # ⑩ 同一乐句在歌里重复（Hey Jude 真实存在的坑）：只弹开头 24 个音，
    #    不能被"第二遍"抢走（实测里 +2.5s 和 -22.7s 两条线 inlier 一样多）。
    ev = make_events(GLOBAL_SCORE, offset=2.5, drop=set(range(24, n)))
    r, _, c = run_case("⑩ 只弹开头 24 个音（防重复乐句抢位）", ev)
    t0 = min(GLOBAL_SCORE[j]["t"] for _, j in r.matches) if r.matches else 99
    check("⑩ 钉在开头那一遍", abs(r.offset - 2.5) <= 0.10, "offset=%+.3f" % r.offset)
    check("⑩ 最早命中在谱面开头", t0 <= 6.0, "最早谱面 %.2fs" % t0)
    check("⑩ 全对", c["ok"] == 24, "ok=%d" % c["ok"])

    bad = [x for x in RESULTS if not x[1]]
    print("")
    print("=" * 66)
    print("合成回归：%d 项通过 / %d 项失败" % (len(RESULTS) - len(bad), len(bad)))
    for name, _, detail in bad:
        print("  FAIL %s   %s" % (name, detail))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
