# -*- coding: utf-8 -*-
"""作业检查 · 一次完整批改（命令行版）

这是**产品链路的骨架**，按思路 §3 的顺序走：
    参考谱面(.gp→时间轴)  →  引擎桥：找出每一次起音（Node，复用跟弹 engine）
                          →  对齐（身份锚定优先，读不出音高时退回按时间对齐）
                          →  判定桥：逐音问"我要的这个音在不在这一下"（Node，复用跟弹 engine）
                          →  逐音对错 → 按 Q17 聚合 → 按 Q24 打分 → result.json

Python 只做编排（铁律 Q15 / Q29）；起音与判定都在 Node 侧的 engine 里，只有一份代码。

用法：
    E:\\Python\\python.exe -X utf8 homework\\run_assignment.py ^
        --ref   C:\\Users\\Administrator\\vc_gf\\tl-6415.json ^
        --audio E:\\GuitarFollowLab\\sound_data\\f32\\6415\\6415慢速.f32 ^
        --job   6415 --engine follow --ref-slice 1:32

    --ref-slice A:B   把参考裁到"这次作业那一段"（1 起、含两端，A/B 可留空）
    --ref-bars  A:B   同上，按小节裁（只有 .gp 生成的时间轴才有 measure 字段）
    --assignment <id> 直接用 data/assignments/<id> 里登记好的作业当参考（推荐）
"""

import argparse
import io
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from align import align, align_by_time, load_score, note_name   # noqa: E402
from grade import aggregate, describe                          # noqa: E402
from reference import build_timeline, crop_notes, write_ref    # noqa: E402
import issue_types as IT                                       # noqa: E402

JOBS = os.path.join(ROOT, "data", "jobs")

# 报告层：只展开前几条"最值得先改"的问题（Q17「有限度」在报告里的体现）
KEY_ISSUES = 3
# 作业批改自己的配对（对齐）参数 —— 见 pair_pipeline()
PAIR_RANK_WIN = 12          # 候选：按"第几个音"的窗口（容忍整体位移）
PAIR_TIME_WIN = 2.0         # 候选：按时间就近（秒）
PAIR_MATCH_WIN = 0.8        # 单调 DP 里允许的时间残差（秒）
# 多音格的判定时刻（试两个，有一个过就算过）：
#   * 小琶音三根弦相隔约 100ms —— 只在 90ms 判会读到"最后一根还没响"的谱
#     （实测 `9 11 11`：90ms 过 8/12，170ms 过 12/12）；
#   * 同时响的双音反过来 —— 170ms 时两根弦衰减不一样，读数变坏
#     （1645 那条真录音：只判 90ms 是 88 分，只判 170ms 掉到 82 分）。
# 170ms 不是随手挑的：判定窗本身 8192/48k = 170.67ms，所以 170 时窗 = [起音, 起音+170ms]。
# **单音格不带这个键**，还是产品页的 90ms，单音作业行为一字不变。
JUDGE_AT_MULTI_MS = [90, 170]
# ── 判定窗：**窗长 = min(分辨这个音需要的长度, 这个音自己的时间片)** ──────────────
# （2026-09-30 用户点破的方向：跟弹是**实时**的，只能一扇固定窗 —— 产品页
#   8192 点 @12kHz = 683ms；密的地方就装进前一个音，六弦那种半音只有 5Hz 的
#   低音就分不出来。我们是**后台批改**：可以用未来、可以按音换窗。）
#   2026-09-30 起**默认开**（扫表见 思路.md §11.11）；不要就设 HG_WIN_AUTO=0
#   （关掉 = 产品页那扇 170.67ms，行为与以前一字不变）。
#   档位：HG_WIN_KAPPA（默认 0.5 = 每半音 2 个 bin）/ HG_WIN_MAX / HG_WIN_MIN。
#   * "分辨需要的长度"：bin ≤ κ × 这个音的半音间隔。bin = SR/N，时长 = N/SR，
#     所以时长 = 1/(κ·f0·(2^(1/12)−1)) —— **和采样率无关**。
#     六弦 E2/F2 (82~87Hz)：κ=0.5 → 0.39~0.41s；五弦 A2 → 0.31s；三弦 G3 → 0.17s。
#   * "这个音自己的时间片"：**这个音到下一个音**的间隔（乘整体速度比）。
#     ⚠ 长窗**必须贴在音符自己的时间片里、从起音后 30ms 往正方向量**（wins 那套）；
#     往回伸长就会把上一个音（更响的那一段）装进来 —— 09-30 实测：往回伸的长窗
#     读六弦一律低半音，单音旋律（Hey Jude）也从 95 掉到 84。
WIN_AUTO = os.environ.get("HG_WIN_AUTO", "1") == "1"
WIN_KAPPA = float(os.environ.get("HG_WIN_KAPPA", "0.25"))
WIN_MIN_MS = float(os.environ.get("HG_WIN_MIN", "170.67"))   # 产品页那扇窗（8192/48k）
WIN_MAX_MS = float(os.environ.get("HG_WIN_MAX", "683"))      # 12k 下 8192 点
JUDGE_AT_MS = 90.0          # 产品页：起音后 90ms 出结论
WIN_START_MS = 30.0         # 长窗从起音后 30ms 开始（跟弹那边"稳定段 30~170ms"）
SEMITONE = 2 ** (1 / 12.0) - 1
#   0.5 会把"学员局部慢了一下"的音错判成漏（Hey Jude 上实测：漏 3 → 真漏只有 2）；
#   1.2 又太宽，会把真的漏弹硬配到隔壁起音上（真漏从 2 变 1）。0.8 刚好。
# 及格线（用户 2026-09-29 定：90 分；要临时改可以设 HOMEWORK_PASS_LINE）
PASS_LINE = int(os.environ.get("HOMEWORK_PASS_LINE", "90"))
# 过程提醒的"明显"门槛（Q9 / Q18 的建议值，用户说改就改）
TEMPO_TOL = 0.30          # 整体速度差超过 ±30% 才提（用户 2026-09-29 定）
PAUSE_OVER_SEC = 1.0      # 比谱面多停 1 秒以上，且
PAUSE_RATIO = 1.8         # 超过谱面间隔的 1.8 倍，才算"明显停顿"
DRIFT_RATIO = 1.25        # 后半段比前半段慢/快 25% 以上才算"一会快一会慢"
# 节拍网格的容忍度 —— **照抄跟弹的规则**（judge-loop.js 224 行，用户 2026-09-23 定的）：
#   容许偏差 = clamp(到下一个音的间隔 × 45%, 100ms, 350ms)，**第一个音翻倍**
#   "跟得上比掐得准重要"。作业这边不再自造"200ms / 1/4 拍"那套。
# 单个音的抢拍/拖拍：**要有容忍度，但不能完全不报**（用户 2026-09-29 原话：
#   "抢了 1.几秒或者慢了 1.几秒都是很明显的，应该报"）。所以门槛定 1.0 秒：
#   零点几秒（含跟弹那条 100~350ms 的容忍度）一律不报，≥1 秒才当一处"节奏"报出来。
TIMING_ABS_SEC = 1.0
# 跟弹那条逐音容忍度（judge-loop.js 224 行，用户 2026-09-23 定的）：
#   容许偏差 = clamp(到下一个音的间隔 × 45%, 100ms, 350ms)，第一个音翻倍
TIMING_FRAC = 0.45
TIMING_MIN_MS = 100.0
TIMING_MAX_MS = 350.0
# "节奏不稳"（这一段 70、那一段 90 那种）：按局部 BPM 漂移判，不是看相邻间隔抖动。
UNSTABLE_WIN = 6          # 局部 BPM 用连续 6 个音的跨度算（≈7 个音，够稳又不笨）
UNSTABLE_RATIO = 1.30     # 最快段 / 最慢段 超过 30% 才算"明显不一致"（待实测标定）

# 跟弹仓库（判定引擎的家）——铁律 Q15/Q29：起音与判定只有那一份代码
FOLLOW_REPO = os.environ.get("GUITARFOLLOW_REPO", r"E:\GuitarFollowLab")


def run_node(script, *args):
    cmd = ["node", os.path.join(HERE, script)] + [str(a) for a in args]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError("%s 跑失败：\n%s\n%s" % (script, p.stdout, p.stderr))
    return p.stdout


def run_follow_harness(ref_path, audio_path):
    """跑跟弹**产品页自己的那条链路**（test-follow-real.mjs），拿逐音判定。

    为什么不在作业检查里自己拼引擎调用：2026-09-28 试过 —— 照 onset.js + judger.js
    的函数自己接，读数窗、帧状态、谱的取样方式只要有一处和页面不一样，结果就完全不同
    （同一条录音：页面 对30/错3，自己拼出来的只有 对5/错23）。所以正确做法是
    **让页面那份代码自己跑**，作业检查只做编排（铁律 Q29 说的"Node 子进程"就是这个意思）。
    """
    env = dict(os.environ)
    env["VC_TIMELINE"] = ref_path
    env["VC_JSON"] = "1"
    cmd = ["node", os.path.join(FOLLOW_REPO, "test", "test-follow-real.mjs"), audio_path]
    p = subprocess.run(cmd, cwd=FOLLOW_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        raise RuntimeError("跟弹链路跑失败：\n%s\n%s" % (p.stdout[-2000:], p.stderr[-2000:]))
    line = None
    for ln in (p.stdout or "").splitlines():
        if ln.startswith("RESULT "):
            line = ln[len("RESULT "):]
    if not line:
        raise RuntimeError("跟弹链路没吐出 RESULT 行：\n%s" % p.stdout[-2000:])
    return json.loads(line), p.stdout


def beat_index_map(score, tempo):
    """给每个音算「这是这一小节的第几拍」。

    为什么不能直接用谱面里的 `beat` 字段：那是 PyGuitarPro 的"第几个音符组"，
    一小节 8 个八分音符会数出 8 个 —— 拿它当"第几拍"就是错的。
    这里的做法：同一小节里，把比它早的那些独立时刻的**时值**累加起来除以一拍长度，
    八分音符两个算一拍，跟人嘴里的数法一致。
    """
    beat_sec = 60.0 / float(tempo or 80)
    by_measure = {}
    for i, n in enumerate(score):
        by_measure.setdefault(n.get("measure"), []).append(i)
    out = {}
    for _m, idxs in by_measure.items():
        idxs.sort(key=lambda i: (score[i]["t"], i))
        acc, total = {}, 0.0
        for i in idxs:
            t = round(float(score[i]["t"]), 4)
            if t not in acc:
                acc[t] = total
                total += float(score[i].get("dur") or beat_sec)
        for i in idxs:
            t = round(float(score[i]["t"]), 4)
            out[i] = int(acc[t] / beat_sec) + 1
    return out


def issues_from_log(log, score, tempo=None):
    """用**跟弹导出记录**（RESULT 里的 log）定位错音 —— 不再猜"第几小节第几拍"。

    记录里每一行是一次判定：`no` = 谱面第几个音（1 起）、`t` = 这一下的录音时刻、
    `exp/expName` = 谱面要的音、`cand` = 判定挑成的音、`result` = ok/bad。

    一次起音会被反复重判（页面上那个"卡在某一格"的老毛病），所以：
      * 判定结果按**这个 no 出现过 bad 就算错**（和页面上"错 N 个"同一套口径）；
      * 报告用的时刻取**第一次判 bad 的那一下**（那才是学员真正弹出来的那一下）。
    """
    beats = beat_index_map(score, tempo) if tempo else {}
    first_bad = {}
    ever_bad = set()
    for row in log or []:
        try:
            no = int(row.get("no"))
        except (TypeError, ValueError):
            continue
        if row.get("result") == "bad":
            ever_bad.add(no)
            first_bad.setdefault(no, row)

    issues = []
    for no in sorted(ever_bad):
        row = first_bad[no]
        idx = no - 1
        sn = score[idx] if 0 <= idx < len(score) else None
        if (sn is not None and sn.get("midi") is not None and row.get("exp") is not None
                and int(round(float(sn["midi"]))) != int(round(float(row["exp"])))):
            sn = None            # 对不上号就别硬套小节，宁可不给
        want = row.get("expName") or (note_name(row["exp"]) if row.get("exp") is not None else None)
        got = row.get("cand") or row.get("measured")
        t_audio = row.get("t")
        measure = beat = None
        if sn is not None and sn.get("measure") is not None:
            measure = int(sn["measure"]) + 1
            beat = beats.get(idx) or (int(sn.get("beat") or 0) + 1)
            title = "第 %d 小节 · 第 %d 拍" % (measure, beat)
        else:
            title = "本段第 %d 个音" % no
        t_audio = round(float(t_audio), 2) if t_audio is not None else None
        t_score = round(float(sn["t"]), 2) if sn is not None else None
        item = {"want": want, "got": got, "kind": "wrong_note",
                "string": (sn or {}).get("string"), "fret": (sn or {}).get("fret"),
                "want_midi": int(sn["midi"]) if sn is not None else None,
                "got_midi": row.get("heard"), "measure": measure, "beat": beat,
                "t_audio": t_audio}
        issues.append({
            "title": title,
            "measure": measure, "beat": beat,
            "note_index": no,
            "t_audio": t_audio, "t_score": t_score,
            "kind": "wrong_note",
            "string": (sn or {}).get("string"), "fret": (sn or {}).get("fret"),
            "want_midi": item["want_midi"], "got_midi": item["got_midi"],
            "detail": single_detail(item),
            "fix": "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。",
            "items": [item],
        })
    return issues


def judged_slots(log):
    """逐音记录里一共判过几个**不同的**谱面音（完成度的分母用这个更实在）。"""
    out = set()
    for row in log or []:
        try:
            out.add(int(row.get("no")))
        except (TypeError, ValueError):
            continue
    return len(out)


# ── 报告层：把逐音问题聚成"练习单位"、排影响、给总评和过程提醒 ────────────

def group_issues(issues):
    """把逐音的问题聚成"一句"。

    学员看报告不该看到"第 12 个音错了、第 13 个音错了、第 14 个音错了"三条，
    他应该看到"第 2 小节第 1~3 拍连着没对上"一条 —— 这才是他一次要练的东西。
    规则：同一个格/相邻 2 格以内，或者同一小节里连着的，合成一条。
    """
    groups = []
    for it in sorted(issues, key=lambda x: (x.get("note_index") or 0)):
        no = it.get("note_index")
        kind = it.get("kind")
        # 只有"逐音对错"这一类才合并成句子；节奏/多弹各自成条（说法不一样，不能混）
        mergeable = kind in ("wrong_note", "missing")
        cur = groups[-1] if groups else None
        if (cur is not None and mergeable and cur.get("mergeable")
                and no is not None and cur["to_note"] is not None):
            same_bar = (it.get("measure") is not None
                        and it.get("measure") == cur["measure"])
            if (no - cur["to_note"] <= 2) or same_bar:
                cur["items"].append(it)
                cur["to_note"] = no
                continue
        groups.append({"items": [it], "from_note": no, "to_note": no,
                       "measure": it.get("measure"), "beat": it.get("beat"),
                       "raw": it, "kind": kind, "mergeable": mergeable})
    for g in groups:
        # 节奏/多弹这类，标题和说法都用它自己的（别套单音那套）
        g["title"] = (g["raw"].get("title") if g["kind"] not in ("missing_note", "wrong_note")
                      else group_title(g))
        g["detail"] = group_detail(g)
        g["fix"] = group_fix(g)
        first = g["items"][0]
        g["t_audio"] = first.get("t_audio")
        g["t_score"] = first.get("t_score")
    return groups


def group_title(g):
    """一条问题叫什么名字：有小节拍号就给小节拍号，没有就说"本段第几个音"。"""
    items = g["items"]
    if g["measure"] is not None:
        bar = int(g["measure"])
        beats = [int(i["beat"]) for i in items if i.get("beat") is not None]
        if beats and len(set(beats)) > 1:
            return "第 %d 小节 · 第 %d~%d 拍" % (bar, min(beats), max(beats))
        if beats:
            return "第 %d 小节 · 第 %d 拍" % (bar, beats[0])
        return "第 %d 小节" % bar
    if g["from_note"] is None:
        return "录音里多出来的音"
    if g["from_note"] == g["to_note"]:
        return "本段第 %d 个音" % g["from_note"]
    return "本段第 %d~%d 个音" % (g["from_note"], g["to_note"])


def group_detail(g):
    items = g["items"]
    # 只有"漏 / 错"这两类是逐音对错，其余（多弹、抢、拖、停、节奏不稳）
    # 都是**手写好的整条问题**，别拿单音那套说法去套
    if g.get("kind") not in ("missing_note", "wrong_note"):
        return (g.get("raw") or items[0]).get("detail") or "录音里有对不上谱面的音。"
    if len(items) == 1:
        return single_detail(items[0])
    parts = [detail_one(i) for i in items[:4]]
    tail = "等 %d 处" % len(items) if len(items) > 4 else ""
    return "这一句连着 %d 个音没对上：%s%s。" % (len(items), "、".join(parts), tail)


CN_NUM = "一二三四五六七八九"


def pos_text(it, score_note=None):
    """把谱面位置说成人话：**三弦二品** / 二弦空弦。

    ⚠ 用户口径（2026-09-29）：报告里**不出现 A3、B4 这种音名**（太专业），
    我们有标准谱，指位置就够了。
    """
    src = score_note or it or {}
    s, f = src.get("string"), src.get("fret")
    if s is None or f is None or not (1 <= int(s) <= 6):
        return None
    s, f = int(s), int(f)
    fret = "空弦" if f == 0 else ("%s品" % (CN_NUM[f - 1] if 1 <= f <= 9 else f))
    return "%s弦%s" % (CN_NUM[s - 1], fret)


def midi_gap(it):
    """"听着弹成的音"和"谱面这个音"差几个半音（差一品 = 1 个半音）。"""
    d = it.get("got_midi") if isinstance(it, dict) else None
    w = it.get("want_midi") if isinstance(it, dict) else None
    if d is None or w is None:
        return None
    return int(d) - int(w)


def detail_one(it):
    """一处问题的说法：漏弹 / 漏判定 / 按错。

    ⚠ 用户口径（2026-09-29）：**不出现 A3、B4 这种音名**（太专业），
    要说"三弦二品"这种位置话 —— 我们有标准谱，指位置就够了。
    """
    it = it or {}
    want, got = note_pair(it)
    subject = pos_text(it) or want or "这一处"
    if it.get("kind") == "missing_note":
        return "%s漏了" % (subject or "这一处")
    if not got or got == want:
        return "%s没弹实" % subject
    d = midi_gap(it)
    if d is None:
        return "%s听着不是谱面这个音" % subject
    if d == 1:
        return "%s按高了一品" % subject
    if d == -1:
        return "%s按低了一品" % subject
    if d in (2, -2):
        return "%s按%s了两品" % (subject, "高" if d > 0 else "低")
    if d in (12, -12):
        return "%s差了八度（多半碰到别的弦了）" % subject
    return "%s听着不是谱面这个音" % subject


def single_detail(it):
    """一条问题单独成句时的说法（和 detail_one 同一套口径，只是句子更顺）。"""
    it = it or {}
    want, got = note_pair(it)
    subject = pos_text(it) or want or "这一处"
    if it.get("kind") == "missing_note":
        return "这里%s漏了一下。" % subject
    if not got or got == want:
        return "这里%s没弹实（或者被上一个音盖住了）。" % subject
    d = midi_gap(it)
    if d is None:
        return "这里%s，听着不是谱面这个音。" % subject
    if d == 1:
        return "这里%s，听着按高了一品。" % subject
    if d == -1:
        return "这里%s，听着按低了一品。" % subject
    if d in (2, -2):
        return "这里%s，听着%s了两品。" % (subject, "高" if d > 0 else "低")
    if d in (12, -12):
        return "这里%s，听着差了八度（多半碰到别的弦了）。" % subject
    return "这里%s，听着不是谱面这个音。" % subject


def note_pair(it):
    """一条问题的"要什么 / 弹成了什么"。

    逐音问题有兩種形状：issues_from_log() 把它们放在 items[0] 里，
    issues_from_wrongs() 直接放在顶层 —— 两种都认。
    """
    inner = (it.get("items") or [{}])[0]
    want = it.get("want") or inner.get("want")
    got = it.get("got") or inner.get("got")
    return want, got


def group_fix(g):
    if len(g["items"]) >= 3:
        return ("这一句连着没对上，先把手的位置提前摆好：慢到一半速度一小节一小节过，"
                "每个音按实了再往下。")
    return "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。"


def rank_groups(groups):
    """按"先改哪个更值"排序：成片的 > 孤立的；低音弦/根音 > 内声部；靠前的稍微优先。"""
    def weight(g):
        w = 2.0 * len(g["items"])
        if any(str(note_pair(i)[0] or "")[-1:] in ("2", "3") for i in g["items"]):
            w += 0.8                      # 低音弦（6/5 弦上的音，音名尾数是 2/3）
        no = g.get("from_note") or 40
        w += 0.4 * (1.0 - min(no, 40) / 40.0)
        return w
    return sorted(groups, key=weight, reverse=True)


def process_notes(onsets, score, pauses=None):
    """过程提醒：整体快慢、明显停顿、一会儿快一会儿慢。

    数据只用**跟弹自己检出的起音表**（onsets）和谱面的时间，不另做判定；
    只报明显的（阈值就是上面那几个常量），没超过就报"稳"。
    注意别用"判定记录"算这个 —— 引擎卡在某一格时，那一格的时刻会拖得很长，
    看起来像停顿，其实是引擎的账（2026-09-29 在 6415 上验证过）。
    """
    ts = sorted(float(o["t"]) for o in (onsets or []) if o.get("t") is not None)
    st = sorted(float(n["t"]) for n in score if n.get("t") is not None)
    if len(ts) < 6 or len(st) < 3:
        return []
    gaps_s = [b - a for a, b in zip(st, st[1:]) if b - a > 0.01]
    if len(ts) < 2 or not gaps_s:
        return []
    gaps_a = [b - a for a, b in zip(ts, ts[1:]) if b - a > 0.01]
    if not gaps_a:
        return []
    med_a, med_s = statistics.median(gaps_a), statistics.median(gaps_s)
    out = []

    # ① 整体速度（Q9：允许整体变化，但不能差太多）
    if med_s > 0.01:
        ratio = med_a / med_s
        if ratio > 1 + TEMPO_TOL:
            out.append("整段比谱面慢约 %d%%，速度上可以再跟一跟谱面。"
                       % round((ratio - 1) * 100))
        elif ratio < 1 - TEMPO_TOL:
            out.append("整段比谱面快约 %d%%，别抢，稳住更稳。"
                       % round((1 - ratio) * 100))

    # ② 明显停顿（Q20：中途停下不算合格，这里只提醒）
    if pauses is None:                     # 没有配对信息时退回"跟全体间隔中位数比"
        pauses = find_pauses(ts, med_s)
    worst = max(pauses, key=lambda p: p[1]) if pauses else None
    if worst:
        out.append("录音 %.1f 秒那里停了一下（约 %.1f 秒），弹错了也接着弹完更稳。"
                   % (worst[0], worst[1]))

    # ③ 一会儿快一会儿慢（Q9）
    half = len(ts) // 2
    first = [b - a for a, b in zip(ts[:half], ts[1:half + 1]) if b - a > 0.01]
    second = [b - a for a, b in zip(ts[half:], ts[half + 1:]) if b - a > 0.01]
    if first and second:
        m1, m2 = statistics.median(first), statistics.median(second)
        if m1 > 0.01 and m2 / m1 > DRIFT_RATIO:
            out.append("前半段和后半段速度不太一样，后半段慢了一些（约 %d%%）。"
                       % round((m2 / m1 - 1) * 100))
        elif m2 > 0.01 and m1 / m2 > DRIFT_RATIO:
            out.append("前半段和后半段速度不太一样，后半段快了一些（约 %d%%）。"
                       % round((1 - m2 / m1) * 100))

    if not out:
        out.append("整段速度和节奏是稳的，没听出明显停顿。")
    return out[:3]


def find_pauses(ts, med_score_gap):
    """明显停顿：相邻起音的间隔比谱面间隔大很多（Q20 的"停下重来"就是这种）。"""
    out = []
    for a, b in zip(ts, ts[1:]):
        gap = b - a
        if med_score_gap > 0.01 and gap > med_score_gap * PAUSE_RATIO \
                and gap - med_score_gap > PAUSE_OVER_SEC:
            out.append((a, gap))
    return out


def timing_tolerance_ms(score, j):
    """这个音容许早/晚多少毫秒 —— 照跟弹的规则（judge-loop.js 224 行）。

    时值优先取"到下一个音的间隔"，最后一个音用它自己的时值；
    夹在 100~350ms 之间，**第一个音宽容一倍**（起手那一下最难卡）。
    """
    cur = score[j]
    nxt = score[j + 1] if j + 1 < len(score) else None
    if nxt is not None:
        ioi_ms = max(60.0, (nxt["t"] - cur["t"]) * 1000.0)
    else:
        ioi_ms = max(60.0, float(cur.get("dur") or 0.25) * 1000.0)
    base = min(TIMING_MAX_MS, max(TIMING_MIN_MS, ioi_ms * TIMING_FRAC))
    return base * 2 if j == 0 else base


def unstable_spans(match, events, score, scale, tempo, win=None, ratio=None):
    """找出"这一段 70、那一段 90"那种节奏不稳（用户 2026-09-29 给的判据）。

    口径：
      * **单个音的抢/拖**：≥1 秒才报（timing_marks），零点几秒不报；
      * **节奏不稳**：局部 BPM 这一段和那一段明显不一样才算 —— 不是看相邻两个音抖没抖。

    做法：在连续 win 个音的跨度上算**局部 BPM**（= 谱面速度 ÷ 该段的实际速度比），
    然后把最快的段和最慢的段比一下；超过 ratio 就报"这一带多少拍/分、那一带多少拍/分"。
    """
    win = win or UNSTABLE_WIN
    ratio = ratio or UNSTABLE_RATIO
    ordered = sorted(match.items(), key=lambda kv: kv[1])      # 按起音时间
    if len(ordered) < win:
        return []
    wins = []
    for s in range(len(ordered) - win + 1):
        w = ordered[s:s + win]
        # 用窗内**每个间隔的中位数**估这一带的实际速度 ——
        # 拿首尾跨度算的话，"中间某一下慢了"会把整段算成慢速段（实测过）。
        ratios = []
        for (j1, i1), (j2, i2) in zip(w, w[1:]):
            dt_s = score[j2]["t"] - score[j1]["t"]
            dt_a = events[i2]["t"] - events[i1]["t"]
            if dt_s > 0.05 and dt_a > 0.05:
                ratios.append(dt_a / dt_s)
        if not ratios:
            continue
        ratios.sort()
        med = ratios[len(ratios) // 2]                 # 局部速度比（中位数）
        bpm = float(tempo) / med if med > 0 else 0.0   # 这一带学员实际弹出来的速度
        wins.append({"from": w[0][0], "to": w[-1][0], "bpm": bpm})
    if len(wins) < 2:
        return []
    slow = min(wins, key=lambda x: x["bpm"])
    fast = max(wins, key=lambda x: x["bpm"])
    if slow["bpm"] <= 0 or fast["bpm"] / slow["bpm"] < ratio:
        return []
    return [{"from": slow["from"], "to": slow["to"], "bpm": round(slow["bpm"]),
             "fast_from": fast["from"], "fast_to": fast["to"], "fast_bpm": round(fast["bpm"]),
             "ratio": round(fast["bpm"] / slow["bpm"], 2)}]


def timing_marks(match, events, score, scale, offset, tempo=None):
    """节拍网格：把每个音放进"谱面拍子 × 学员速度"的网格里，看它早了多少、晚了多少。

    Q18（用户口径）：在正常演奏段用节拍网格看节奏准不准，**只报用户能明显感觉到的**
    （BPM 差一点点不报）。门槛直接用**跟弹那条容忍度规则**（timing_tolerance_ms）：

        dev = 这一下的实际时刻 − （谱面这一拍的时刻 × 学员速度 + 整体位移）

    dev 为正 = 拖拍，为负 = 抢拍。整体快慢（scale）已经在模型里扣掉了，
    所以这里报的是"相对于他自己的速度，这一下早了/晚了"。
    节奏**不吃分**（Q9/Q18：整体变速允许、抢拖只提示），只标在谱面上、列进清单。
    """
    beat = 60.0 / float(tempo or 80)
    out = []
    for j, i in sorted(match.items()):
        want = scale * score[j]["t"] + offset
        dev = events[i]["t"] - want
        tol_ms = timing_tolerance_ms(score, j)
        # 门槛：**1.0 秒**（用户口径：零点几秒可以容忍，1 秒以上就是明显了）；
        # 跟弹那条逐音容忍度（100~350ms）比它小，所以取两者更大的那个。
        if abs(dev) < max(TIMING_ABS_SEC, tol_ms / 1000.0):
            continue
        out.append({"kind": "timing", "sub": "late" if dev > 0 else "early",
                    "note_index": j + 1, "t_audio": round(events[i]["t"], 2),
                    "t_score": round(float(score[j]["t"]), 2),
                    "dev": round(dev, 2), "dev_beats": round(dev / beat, 2),
                    "beat_sec": round(beat, 3), "tol_ms": round(tol_ms)})
    return out


def verdict_text(score, pass_line, key_groups, process, total_issues):
    """一句话总评（老师口吻，Q26 的雏形：先说结论，再指一处最值得改的）。"""
    if total_issues == 0:
        return "这一遍跟谱子一样，一个音都没挑出来。"
    if score >= pass_line:
        head = "这次 %d 分，过了。" % score
        if key_groups:
            return (head + "整段是稳的，只有 %d 处小问题（最明显的是%s），"
                           "不拦你过，下次注意就好。"
                    % (total_issues, key_groups[0]["title"]))
        return head + "整段是稳的。"
    head = "这次 %d 分，没到及格线 %d 分，差得不远。" % (score, pass_line)
    if total_issues:
        head = ("这次 %d 分，没到及格线 %d 分；挑出 %d 处要改的地方，差得不远。"
                % (score, pass_line, total_issues))
    if key_groups:
        head += "最要紧的是%s——%s" % (key_groups[0]["title"],
                                   key_groups[0]["detail"])
    return head


# ── 作业批改自己的那条链路：起音 → 配对（我们的对齐）→ 判定（引擎的判定方式）──
#
# 为什么不再借跟弹产品页那条链路（2026-09-29 用户点破）：
#   产品页是**练习**用的 —— 开始要数四拍、判错就停下重弹、按"第几次起音对第几个音"
#   顺序走。学员只要漏一个音，后面就整体错位，报告变成"前几个音全错"。
#   作业批改要的是"对着谱子检查成果"：从那一声明显的音开始，允许漏、允许整体快慢，
#   配对错了不许一路怪学员。
#   所以这里自己走三步，判定仍然只用 engine/judger.js 的 judgeNote，
#   而且窗口/opts 严格照产品页那一处调用（见 engine_judge.mjs 的注释）。

def build_slots(score, eps=0.02):
    """谱面 → 「格」：**同一时刻响的几根弦算一格**（跟弹那边叫 slot / 多音格）。

    为什么要有这一层（用户 Q1 / Q16）：
      单音作业里一格就是一个音，行为和以前逐字一样；
      双音/柱式和弦作业里一格两根弦（同一时刻），一个起音该判这一格里的所有弦。
      以前的配对是"一个起音对一个音"，双音谱判下去会说"漏了一半" —— 那不是学员漏了，
      是我们的格子没建对。第一版按 Q1 的口径只判"这几根弦是不是都在响"（和弦+节奏），
      逐音精度等跟弹那边 Q16 的多音定版再对齐。

    eps 是"算不算同一时刻"的容差：.gp 里同一柱音的时刻是一样的（浮点尾数可能差一点点），
    0.02 秒远小于最快相邻音（200 BPM 的 32 分音符也有 0.037 秒），不会把先后音并到一起。
    """
    order = sorted(range(len(score)), key=lambda j: (float(score[j]["t"]), j))
    slots = []
    for j in order:
        t = float(score[j]["t"])
        if slots and abs(t - slots[-1]["t"]) <= eps:
            slots[-1]["notes"].append(j)
        else:
            slots.append({"t": t, "notes": [j]})
    return slots


def slot_slices(slots, scale=1.0):
    """每一格"自己的时间片"（秒，学员时间）：**这个音到下一个音**的间隔（最后一个音取上一个）。

    为什么是"到下一个音"：低音弦要更长的窗才分得出半音，但那扇长窗必须
    **贴在音符自己的时间片里、从起音后 30ms 往正方向量**；往回伸长就会把上一个音
    （更响的那一段）装进来 —— 09-30 实测：往回伸的长窗读六弦一律低半音。
    所以"这个音自己的时间片" = 这个音自己有多长。
    """
    out = []
    for s, sl in enumerate(slots):
        if s + 1 < len(slots):
            g = float(slots[s + 1]["t"]) - float(sl["t"])
        elif s > 0:
            g = float(sl["t"]) - float(slots[s - 1]["t"])
        else:
            g = 5.0
        out.append(max(0.05, g) * scale)
    return out


def win_ms_for(midi, slice_sec):
    """这一格的判定窗长（毫秒）：min(分辨需要的长度, 时间片)，夹在 [WIN_MIN, WIN_MAX]。"""
    f0 = 440.0 * (2 ** ((int(midi) - 69) / 12.0))
    need_ms = 1000.0 / (WIN_KAPPA * f0 * SEMITONE)
    win = min(need_ms, max(0.0, slice_sec) * 1000.0)
    return round(min(max(win, WIN_MIN_MS), WIN_MAX_MS), 1)


def wins_for(midi, slice_sec, multi=False):
    """这一条配对要试哪几扇窗（判定桥的 wins 键）。

    默认是产品页那一扇（多音格再等一格：90ms 和 170ms）；
    这个音需要更长的窗（低音弦）时，再加一扇"贴在它自己时间片里"的长窗。
    """
    wins = [{"atMs": a, "winMs": WIN_MIN_MS}
            for a in (JUDGE_AT_MULTI_MS if multi else [JUDGE_AT_MS])]
    w = win_ms_for(midi, slice_sec)
    if w > WIN_MIN_MS + 1:
        wins.append({"atMs": WIN_START_MS + w, "winMs": w})
    return wins


def _pair_candidates(events, slots, score, scale=1.0, windows=False):
    """候选配对：按「第几格」的窗口 ∪ 按时间就近的窗口。

    一格给出（可能不止一条）配对：格里有几根弦就给几条，判定桥逐条判，
    DP 再按"这一格整体得的平均分"决定配不配 —— 单音格就是一条，和以前完全一样。

    2026-09-30：windows=True（且 HG_WIN_AUTO=1）时，每条配对按"判定窗"那条规则带一个
    winMs（窗长 = min(分辨需要的长度, 这个音自己的时间片)）。
    **第一遍（估对齐）必须用 windows=False** —— 粗扫是靠"窗内判过几个"投票选速度比的，
    窗口一长，低音弦多出来的通过票会把速度比投歪（实测 6415 的 scale 1.104 → 0.939）。
    不带这个键时判定桥用产品页那扇 170.67ms，行为与以前一字不变。
    """
    pairs, index = [], []
    n, m = len(events), len(slots)
    slices = slot_slices(slots, scale) if (WIN_AUTO and windows) else None
    for i, e in enumerate(events):
        base = int(round(i * m / float(max(1, n))))
        cand = set(range(max(0, base - PAIR_RANK_WIN), min(m, base + PAIR_RANK_WIN + 1)))
        cand |= {s for s, sl in enumerate(slots) if abs(e["t"] - sl["t"]) <= PAIR_TIME_WIN}
        for s in sorted(cand):
            # 多音格：等这一格的弦都响起来再判（小琶音；单音格不带这个键 = 还是 90ms）
            multi = len(slots[s]["notes"]) > 1
            for k, j in enumerate(slots[s]["notes"]):
                sn = score[j]
                if slices is None:
                    at = {"atMsList": JUDGE_AT_MULTI_MS} if multi else {}
                else:
                    at = {"wins": wins_for(sn["midi"], slices[s], multi)}
                pairs.append({"t": e["t"], "expectedMidi": int(sn["midi"]),
                              "string": sn.get("string"), "fret": sn.get("fret"),
                              "level": e.get("lv"), **at})
                index.append((i, s, k))
    return pairs, index


def _dp_match_units(index, judged, events, slots, score, scale, offset):
    """单调 DP（按**格**配对）：两条序列都允许跳过。

    跳起音 = 多弹（extra）；跳一格 = 漏弹（这一格里的音全算漏）。
    一格的分数 = 格里每个音各自"过/不过"的**总和**，跳一格的代价也按格里的音数放大：

      * 单音格（n=1）：和 / 平均 / 代价跟以前**完全一样**，单音作业的数字不会动；
      * 双音格（n=2）：全过 4.0、只过一根 1.7、全不过 -0.6，跳一格是 -1.2。

    为什么不能取平均（2026-09-30 实测）：取平均 + 固定 -0.6 的跳过代价，
    等于"丢一格双音"和"丢一格单音"代价一样，而双音格的收益又只有单音的一半 ——
    优化器会去牺牲双音格。1645 那条真录音上，8 个双音格有 3 个被丢成"漏"，
    还留了 2 个起音没配上。改成按音数算之后，这个问题没了。
    """
    per = {}
    for (i, s, _k), jd in zip(index, judged):
        dt = abs(events[i]["t"] - (slots[s]["t"] * scale + offset))
        if dt > PAIR_MATCH_WIN:
            continue
        per.setdefault((i, s), []).append(jd)
    W = {}
    for (i, s), jds in per.items():
        dt = abs(events[i]["t"] - (slots[s]["t"] * scale + offset))
        k = float(len(jds))
        total = sum(2.0 if jd["pass"] else -0.30 for jd in jds)
        W[(i, s)] = total - dt * 0.5 * k
    n, m = len(events), len(slots)
    SKIP_E = -0.25
    # 跳过一格的代价按格里的音数算：单音格还是 -0.6（和以前一模一样）
    SKIP_S = [-0.6 * len(sl["notes"]) for sl in slots]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(n, -1, -1):
        for s in range(m, -1, -1):
            if i == n and s == m:
                continue
            best, arg = -1e9, None
            if i < n and SKIP_E + dp[i + 1][s] > best:
                best, arg = SKIP_E + dp[i + 1][s], ("skip_e", i + 1, s)
            if s < m and SKIP_S[s] + dp[i][s + 1] > best:
                best, arg = SKIP_S[s] + dp[i][s + 1], ("skip_s", i, s + 1)
            if i < n and s < m and (i, s) in W and W[(i, s)] + dp[i + 1][s + 1] > best:
                best, arg = W[(i, s)] + dp[i + 1][s + 1], ("pair", i + 1, s + 1)
            dp[i][s], back[i][s] = best, arg
    match, extra = {}, set()
    i = s = 0
    while not (i == n and s == m):
        kind, ni, ns = back[i][s]
        if kind == "pair":
            match[s] = i
        elif kind == "skip_e":
            extra.add(i)
        i, s = ni, ns
    return match, extra


def _dp_match(index, judged, events, score, scale, offset):
    """单调 DP：两条序列都允许跳过（跳起音 = 多弹，跳谱面音 = 漏弹）。"""
    W = {}
    for (i, j), jd in zip(index, judged):
        dt = abs(events[i]["t"] - (score[j]["t"] * scale + offset))
        if dt > PAIR_MATCH_WIN:
            continue
        W[(i, j)] = (2.0 if jd["pass"] else -0.30) - dt * 0.5
    n, m = len(events), len(score)
    SKIP_E, SKIP_S = -0.25, -0.6
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n and j == m:
                continue
            best, arg = -1e9, None
            if i < n and SKIP_E + dp[i + 1][j] > best:
                best, arg = SKIP_E + dp[i + 1][j], ("skip_e", i + 1, j)
            if j < m and SKIP_S + dp[i][j + 1] > best:
                best, arg = SKIP_S + dp[i][j + 1], ("skip_s", i, j + 1)
            if i < n and j < m and (i, j) in W and W[(i, j)] + dp[i + 1][j + 1] > best:
                best, arg = W[(i, j)] + dp[i + 1][j + 1], ("pair", i + 1, j + 1)
            dp[i][j], back[i][j] = best, arg
    match, extra = {}, set()
    i = j = 0
    while not (i == n and j == m):
        kind, ni, nj = back[i][j]
        if kind == "pair":
            match[j] = i
        elif kind == "skip_e":
            extra.add(i)
        i, j = ni, nj
    return match, extra


def _judge_pairs(pairs, index, audio, jobdir, band, tag=""):
    """跑一次判定桥，返回和 index 一一对应的 judged 列表。"""
    pairs_path = os.path.join(jobdir, "pairs%s.json" % tag)
    judged_path = os.path.join(jobdir, "judged%s.json" % tag)
    with io.open(pairs_path, "w", encoding="utf-8") as f:
        json.dump({"audio": audio, "band": list(band), "pairs": pairs}, f,
                  ensure_ascii=False, indent=1)
    print(run_node("engine_judge.mjs", pairs_path, judged_path).strip())
    return load_json(judged_path)["judged"]


def check_repeat(events, extras, score, scale, offset, audio, jobdir, band):
    """多弹里到底有没有"整段又弹了一遍"—— 拿证据说话，不靠猜。

    做法：把没配上的那些起音，按"下一遍"的假设再去和整份谱面对一次
    （offset + 一遍的长度）。只有这一遍能**独立**把谱面大部分音都对上，
    才算"重复弹了一遍"；否则只报"有 N 个音没对上谱面"，不说是多弹。
    """
    if len(extras) < 6:
        return {"repeat": False, "count": len(extras)}
    pass_len = (score[-1]["t"] - score[0]["t"]) * scale if len(score) > 1 else 0.0
    off2 = offset + pass_len
    ev = [events[i] for i in sorted(extras)]
    pairs, index = [], []
    for k, e in enumerate(ev):
        for j, s in enumerate(score):
            if abs(e["t"] - (s["t"] * scale + off2)) <= 0.6:
                at = {}
                if WIN_AUTO:
                    # 和第一遍同一条规则（低音弦要长窗）—— 不然"第二遍"那句在低音弦上
                    # 会按产品页那扇短窗判，和前面判过的结果对不上。
                    if j + 1 < len(score):
                        g = float(score[j + 1]["t"]) - float(s["t"])
                    elif j > 0:
                        g = float(s["t"]) - float(score[j - 1]["t"])
                    else:
                        g = 5.0
                    at = {"wins": wins_for(s["midi"], g * scale)}
                pairs.append({"t": e["t"], "expectedMidi": int(s["midi"]),
                              "string": s.get("string"), "fret": s.get("fret"),
                              "level": e.get("lv"), **at})
                index.append((k, j))
    if not pairs:
        return {"repeat": False, "count": len(extras)}
    judged = _judge_pairs(pairs, index, audio, jobdir, band, tag="_repeat")
    match, _ = _dp_match(index, judged, ev, score, scale, off2)
    coverage = len(match) / float(max(1, len(score)))
    return {"repeat": coverage >= 0.6 and len(match) >= 8,
            "count": len(extras), "matched": len(match),
            "score_notes": len(score), "coverage": round(coverage, 3),
            "offset": round(off2, 3)}


def pair_pipeline(audio, score, jobdir, band=(70.0, 1200.0), tempo=None):
    """起音（引擎）→ 配对（我们自己：模型 + 单调 DP）→ 判定（引擎的判定方式）。

    返回 (rows, info)：rows 和 bridge 那条路同一个形状，好直接喂报告层；
    info 里有估出来的整体位移/速度比/置信度，报告和排查都用得上。
    """
    events_path = os.path.join(jobdir, "events.json")
    print(run_node("engine_bridge.mjs", audio, events_path, band[0], band[1]).strip())
    events = load_json(events_path)["events"]
    if not events:
        raise SystemExit("这一段录音里一个起音都没检出来")

    # 谱面 → 「格」：同一时刻响的几根弦算一格（单音作业里一格就是一个音）
    slots = build_slots(score)
    multi = sum(1 for sl in slots if len(sl["notes"]) > 1)
    if multi:
        print("谱面里有 %d 处是好几个音一起响（多音格）：一个起音判这一格里的所有弦。"
              % multi)

    pairs, index = _pair_candidates(events, slots, score)
    judged = _judge_pairs(pairs, index, audio, jobdir, band)

    # ① 整体模型：以"第一声"为锚（用户口径：从第一个明显的音开始算第一个音），
    #    速度比粗扫，挑窗内判过最多的那一档
    passed = {(i, s) for (i, s, _k), jd in zip(index, judged) if jd["pass"]}
    t0_e, t0_s = events[0]["t"], slots[0]["t"]
    best = (-1, 1.0, t0_e - t0_s)
    sc = 0.80
    while sc <= 1.6001:
        off = t0_e - t0_s * sc
        n = sum(1 for (i, s) in passed
                if abs(events[i]["t"] - (slots[s]["t"] * sc + off)) <= 0.35)
        if n > best[0]:
            best = (n, sc, off)
        sc += 0.02
    hits, scale, offset = best

    # ② DP → 用配对结果重拟合"位移+速度比" → 再 DP（两轮就收敛）
    match, extra = _dp_match_units(index, judged, events, slots, score, scale, offset)
    for _ in range(2):
        pts = [(slots[s]["t"], events[i]["t"]) for s, i in match.items()]
        if len(pts) >= 6:
            a = [[t_s, 1.0] for t_s, _ in pts]
            y = [t_e for _, t_e in pts]
            scale, offset = _fit_affine(a, y)
            resid = [abs(y[k] - (a[k][0] * scale + offset)) for k in range(len(y))]
            med = sorted(resid)[len(resid) // 2]
            keep = [k for k in range(len(y)) if resid[k] <= max(0.30, med * 2.5)]
            if len(keep) >= 6:
                scale, offset = _fit_affine([a[k] for k in keep], [y[k] for k in keep])
        match, extra = _dp_match_units(index, judged, events, slots, score, scale, offset)

    # ③ 判定窗（HG_WIN_AUTO=1 才走）：**对齐已经定下来了**，现在才按
    #    "窗长 = min(分辨这个音需要的长度, 这个音自己的时间片)" 重配一次、重判一次，
    #    然后**冻住 scale/offset** 再跑一遍 DP。
    #    为什么不放到前面对齐之前：粗扫是靠"窗内判过几个"投票选速度比的，
    #    窗口一长、低音弦多出来的通过票会把速度比投歪（2026-09-30 实测：6415 那条
    #    的 scale 从 1.104 投成 0.939，分数反而掉到 78）。对齐归对齐、窗口归窗口。
    #    默认**关**：不开就还是产品页那扇 170.67ms，单音作业数字一字不变。
    if WIN_AUTO:
        pairs, index = _pair_candidates(events, slots, score, scale=scale, windows=True)
        judged = _judge_pairs(pairs, index, audio, jobdir, band, tag="_win")
        match, extra = _dp_match_units(index, judged, events, slots, score, scale, offset)

    jd_of = {}
    for (i, s, k), jd in zip(index, judged):
        jd_of[(i, s, k)] = jd
    beats = beat_index_map(score, None)
    rows = []
    weak = 0        # 判定没过、但引擎自己量到的音名就是谱面那个音（见下）
    matched_notes = 0
    for s, sl in enumerate(slots):
        if s not in match:                      # 这一格整格没配上 → 格里的音全算漏
            for j in sl["notes"]:
                sn = score[j]
                rows.append({"score_idx": j, "t_score": sn["t"],
                             "want": note_name(sn["midi"]),
                             "string": sn.get("string"), "fret": sn.get("fret"),
                             "want_midi": int(sn["midi"]),
                             "measure": sn.get("measure"), "beat": sn.get("beat"),
                             "kind": "missing", "t_audio": None, "got": None})
            continue
        i = match[s]
        for k, j in enumerate(sl["notes"]):     # 格里的每根弦各判一次
            sn = score[j]
            base = {"score_idx": j, "t_score": sn["t"], "want": note_name(sn["midi"]),
                    "string": sn.get("string"), "fret": sn.get("fret"),
                    "want_midi": int(sn["midi"]),
                    "measure": sn.get("measure"), "beat": sn.get("beat")}
            jd = jd_of.get((i, s, k))
            if jd is None:                      # 候选窗没罩住这根弦（极少数）：当没判出来
                rows.append(dict(base, kind="missing", t_audio=None, got=None))
                continue
            matched_notes += 1
            base["t_audio"] = events[i]["t"]
            want = note_name(sn["midi"])
            # 收下"判定没通过、但引擎的读数就是谱面这个音"的情况（2026-09-29）：
            #   用户定的 Q13 是"检测到的音名 == 谱面音名就算过"，而这正是引擎自己的读数；
            #   判定没过多半是"这一下不够实/上一个音还在响"（实测 1/38：Hey Jude 第 5 个音
            #   heard=C4 但 fit 221、margin 1.007，卡在候选判据上）。
            #   这类**算过**，但会在过程提醒里说明白，不让它变成一个看不见的宽容。
            rc = jd.get("readCents") if os.environ.get("HG_READ") == "1" else None
            # 用户的思路：起音这一下，在期望音的频带里读最响的那条基频；差在 50 音分内就是过
            if (not jd["pass"]) and rc is not None and abs(rc) <= 50:
                weak += 1
                rows.append(dict(base, kind="ok", got=want, got_midi=jd.get("heard"),
                                 weak=True))
                continue
            if (not jd["pass"]) and jd.get("heardName") == want:
                weak += 1
                rows.append(dict(base, kind="ok", got=want, got_midi=jd.get("heard"),
                                 weak=True))
                continue
            rows.append(dict(base, kind="ok" if jd["pass"] else "wrong_note",
                             got=jd.get("heardName"), got_midi=jd.get("heard")))
    for i in sorted(extra):
        rows.append({"score_idx": None, "kind": "extra", "t_audio": events[i]["t"],
                     "want": None, "got": None, "measure": None, "beat": None})
    # 节奏那几样（停顿 / 抢拖 / 一会儿快一会儿慢）按**格**看，一格取一格的代表音，
    # 免得双音格把同一下算两遍。
    match_notes = {}
    for s, i in match.items():
        for j in slots[s]["notes"]:
            match_notes[j] = i
    info = {"mode": "作业批改自己的配对（引擎判定）", "offset": offset, "scale": scale,
            "onsets": len(events), "matched": matched_notes, "slots_matched": len(match),
            "slots": len(slots), "multi_slots": multi,
            "extra": len(extra), "hit_window": hits, "candidates": len(pairs),
            "onsets_list": events, "weak_confirmed": weak,
            "repeat": check_repeat(events, extra, score, scale, offset,
                                   audio, jobdir, band)}
    # 明显停顿：相邻两个"配上的"音，学员这边的间隔比**谱面这一处该有的间隔**长很多。
    # ⚠ 不能拿"全体间隔中位数"当参照 —— 谱面里本来就有长音符（Hey Jude 有 1.58 秒的长音），
    #   那样会把长音全报成停顿（第一版就是这么错的）。
    marks = []
    ordered = sorted(match_notes.items(), key=lambda kv: kv[1])     # [(谱面 j, 起音 i)] 按时间
    for (j1, i1), (j2, i2) in zip(ordered, ordered[1:]):
        exp = (score[j2]["t"] - score[j1]["t"]) * scale
        got = events[i2]["t"] - events[i1]["t"]
        if exp > 0.05 and got > exp * PAUSE_RATIO and got - exp > PAUSE_OVER_SEC:
            marks.append({"kind": "timing", "note_index": j2 + 1,
                          "t_audio": round(events[i2]["t"], 2),
                          "t_score": round(float(score[j2]["t"]), 2),
                          "seconds": round(got - exp, 2)})
    info["timing_marks"] = marks
    # 节拍网格：抢拍 / 拖拍（和上面的停顿合并成同一份"节奏标记"）
    info["timing_marks"] += timing_marks(match_notes, events, score, scale, offset, tempo)
    info["unstable_spans"] = unstable_spans(match_notes, events, score, scale, tempo)
    return rows, info


def _fit_affine(a, y):
    """最小二乘拟合 t_起音 = scale × t_谱面 + offset（不引第三方库）。"""
    n = len(a)
    sx = sum(r[0] for r in a)
    sy = sum(y)
    sxx = sum(r[0] * r[0] for r in a)
    sxy = sum(r[0] * y[k] for k, r in enumerate(a))
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return 1.0, (sy / n) - (sx / n)
    scale = (n * sxy - sx * sy) / den
    return scale, (sy - scale * sx) / n


def issues_from_rows(rows, score, tempo=None):
    """把逐音结果（rows）里"错 / 漏"的整理成问题卡（和 issues_from_log 同一个形状）。"""
    beats = beat_index_map(score, tempo) if tempo else {}
    out = []
    for r in rows:
        if r["kind"] not in ("wrong_note", "missing"):
            continue
        j = r.get("score_idx")
        sn = score[j] if j is not None else None
        want = r.get("want") or (note_name(sn["midi"]) if sn is not None else None)
        got = r.get("got")
        measure = beat = None
        if sn is not None and sn.get("measure") is not None:
            measure = int(sn["measure"]) + 1
            beat = beats.get(j) or (int(sn.get("beat") or 0) + 1)
        if measure is not None:
            title = "第 %d 小节 · 第 %d 拍" % (measure, beat or 1)
        elif j is not None:
            title = "本段第 %d 个音" % (j + 1)
        else:
            title = "录音里多出来的音"
        t_audio = r.get("t_audio")
        item = {"want": want, "got": got, "kind": IT.normalize(r["kind"]),
                "string": r.get("string"), "fret": r.get("fret"),
                "want_midi": r.get("want_midi"), "got_midi": r.get("got_midi"),
                "measure": measure, "beat": beat,
                "t_audio": round(float(t_audio), 2) if t_audio is not None else None}
        detail = single_detail(item)
        out.append({
            "title": title, "measure": measure, "beat": beat,
            "note_index": (j + 1) if j is not None else None,
            "t_audio": round(float(t_audio), 2) if t_audio is not None else None,
            "t_score": round(float(sn["t"]), 2) if sn is not None else None,
            "kind": IT.normalize(r["kind"]), "string": r.get("string"), "fret": r.get("fret"),
            "want_midi": r.get("want_midi"), "got_midi": r.get("got_midi"),
            "detail": detail,
            "fix": ("先单独把这一处补上，确认按实了再往下连。" if r["kind"] == "missing"
                    else "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。"),
            "items": [item],
        })
    return out


def issues_from_wrongs(wrongs, score):
    """把跟弹错音清单（"第1小节 弹成约G3（要A3）"）翻成问题卡。"""
    note_at = {}
    for sn in score:
        note_at.setdefault((note_name(sn["midi"]), sn.get("string"), sn.get("fret")), sn)
    out = []
    for m in re.finditer(r"第(\d+)小节\s*弹成约([A-G][#b]?\d)（要([A-G][#b]?\d)）", wrongs or ""):
        measure, got, want = int(m.group(1)), m.group(2), m.group(3)
        sn = None
        for sn2 in score:
            if note_name(sn2["midi"]) == want and (int(sn2.get("measure") or 0) + 1) == measure:
                sn = sn2
                break
        out.append({
            "title": "第 %d 小节 · 第 %d 拍" % (measure, int((sn or {}).get("beat") or 0) + 1),
            "measure": measure, "beat": int((sn or {}).get("beat") or 0) + 1,
            "t_audio": round(float(sn["t"]), 2) if sn else None,
            "kind": "wrong_note",
            "detail": "这一处要 %s，听着弹成了约 %s" % (want, got),
            "fix": "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。",
            "items": [{"want": want, "got": got, "kind": "wrong_note",
                       "measure": measure, "beat": int((sn or {}).get("beat") or 0) + 1,
                       "t_audio": round(float(sn["t"]), 2) if sn else None}],
        })
    return out


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def score_of(counts, notes_total):
    """得分口径（2026-09-29 用户同意改版）：**得分 = 弹对的音 ÷ 本次作业的音数 × 100**。

    为什么换掉"干净 96、每处扣 8.5"（Q24 原口径）：那个口径是给"视频分析挑问题"用的，
    放在逐音批改上不好解释 —— 38 个音对 34 个却只有 70 分，学员会问"这 4 个音值 30 分？"。
    现在这条一眼能算：对 34 / 共 38 → 89 分；全对 → 100。漏和错一样算"没拿到"。
    （多弹不进分数：Q17 说多弹要报但有限度，不该因为多弹一遍把分扣没。）
    """
    ok = counts.get("ok", 0)
    return float(int(round(100.0 * ok / max(1, notes_total))))


def build(rows, score_notes):
    """把逐音结果拼成页面要的东西（问题卡 + 谱面图数据）。"""
    issues = []
    for it in aggregate(rows):
        items = it["items"]
        first = items[0]
        measure = first.get("measure")
        if measure is None:
            title = "录音里多出来的音"
        else:
            title = "第 %d 小节 · 第 %d 拍" % (int(measure) + 1, int(first.get("beat") or 0) + 1)
        issues.append({
            "title": title,
            "measure": (int(measure) + 1) if measure is not None else None,
            "beat": (int(first.get("beat") or 0) + 1) if measure is not None else None,
            "t_audio": round(float(first["t_audio"]), 2) if first.get("t_audio") else None,
            "kind": it["kind"],
            "detail": describe(it),
            "fix": "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。",
            "items": [{
                "want": x.get("want"), "got": x.get("got"), "kind": x["kind"],
                "measure": (int(x["measure"]) + 1) if x.get("measure") is not None else None,
                "beat": (int(x.get("beat") or 0) + 1) if x.get("measure") is not None else None,
                "t_audio": round(float(x["t_audio"]), 2) if x.get("t_audio") else None,
            } for x in items],
        })
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="跑一次完整批改")
    ap.add_argument("--ref", default="", help="参考时间轴 JSON（.gp 生成的那份，或借来的练习时间轴）")
    ap.add_argument("--assignment", default="",
                    help="用 data/assignments/<id> 里登记好的作业当参考（连作业档案一起带上）")
    ap.add_argument("--ref-gp", default="",
                    help="参考谱面：老师上传的 .gp —— 走 homework/reference.py（Q5/Q6/Q30）")
    ap.add_argument("--ref-track", type=int, default=None,
                    help=".gp 取第几轨（默认第一条非打击轨，也就是吉他那条）")
    ap.add_argument("--audio", required=True, help="录音（f32，48k 单声道）")
    ap.add_argument("--job", default="",
                    help="中间产物目录名；默认用作业 id（--assignment 给了的话），否则 job")
    ap.add_argument("--band", default="75,450", help="读数频带 Hz，如 75,450")
    ap.add_argument("--engine", choices=["pair", "follow", "bridge"], default="pair",
                    help="pair=作业批改自己的链路（默认）：我们的起音+配对 + 引擎的判定；"
                         "follow=跑跟弹产品页自己的链路（练习语义：四拍倒数、判错停下重弹）；"
                         "bridge=旧的自接引擎桥（实验用）")
    ap.add_argument("--ref-slice", default="",
                    help="把参考裁到这次作业那一段：\"A:B\"（1 起、含两端，可只写一侧）")
    ap.add_argument("--ref-bars", default="",
                    help="同上，按小节裁：\"A:B\"（只有 .gp 生成的时间轴才有 measure 字段）")
    args = ap.parse_args(argv)
    job = args.job or args.assignment or "job"

    jobdir = os.path.join(JOBS, job)
    os.makedirs(jobdir, exist_ok=True)
    lo, hi = [float(x) for x in args.band.split(",")]

    # 参考谱面：优先用老师上传的 .gp（走跟弹的 gp_timeline.py），其次用现成的时间轴 JSON
    if args.assignment:
        adir = os.path.join(ROOT, "data", "assignments", args.assignment)
        aj_path = os.path.join(adir, "assignment.json")
        if not os.path.exists(aj_path):
            raise SystemExit("没有这份作业：%s\n（先跑 homework\\make_assignments.py gp/progressions 登记）"
                             % aj_path)
        with io.open(aj_path, encoding="utf-8") as f:
            aj = json.load(f)
        ref_path = os.path.join(adir, "ref.json")
        meta, score = load_score(ref_path)
        score_all = score
        crop_desc = (aj.get("standard") or {}).get("crop") or ""
        standard = dict(aj.get("standard") or {})
        standard["source_kind"] = "老师上传的 .gp"
        label = "已登记作业 %s" % args.assignment
        ref_src = aj.get("gp") or ref_path
    elif args.ref_gp:
        meta, score_all, _log = build_timeline(args.ref_gp, args.ref_track)
        ref_src = args.ref_gp
        label = "老师上传的 .gp"
    elif args.ref:
        meta, score_all = load_score(args.ref)
        ref_src = args.ref
        label = "现成时间轴"
    else:
        ap.error("至少给一个 --ref（现成时间轴）或 --ref-gp（老师上传的 .gp）")
    if not score_all:
        raise SystemExit("这份参考里没有音")
    if not args.assignment:
        score, crop_desc = crop_notes(score_all, args.ref_slice, args.ref_bars)
        ref_path = write_ref(os.path.join(jobdir, "ref.json"), meta, score, crop_desc)
        # 这次作业的"标准"是什么 —— 报告和页面都要写清楚（以吉他为准、弹得跟谱子一样就行）
        tr = meta.get("track") or {}
        standard = {
            "title": meta.get("title"), "artist": meta.get("artist"),
            "tempo": meta.get("tempo"), "measures": meta.get("measures"),
            "track_index": meta.get("_track_index"), "track_name": tr.get("name"),
            "track_tuning": tr.get("tuning"),
            "track_confident": meta.get("_track_confident"),
            "track_why": meta.get("_track_why"),
            "notes": len(score), "notes_all": len(score_all), "crop": crop_desc,
            "source": ref_src, "source_kind": label,
        }
        bars = [int(n["measure"]) + 1 for n in score if n.get("measure") is not None]
        if bars:
            standard["bar_from"], standard["bar_to"] = min(bars), max(bars)
    print("参考谱面（%s）%s：%d 个音，%.2f~%.2f s，音高 %s~%s"
          % (label, os.path.basename(ref_src), len(score_all),
             score_all[0]["t"], score_all[-1]["t"],
             note_name(min(n["midi"] for n in score_all)),
             note_name(max(n["midi"] for n in score_all))))
    if crop_desc:
        where = ("用 %s 的参考" % os.path.relpath(os.path.dirname(ref_path), ROOT)
                 if args.assignment else "已写 " + os.path.relpath(ref_path, ROOT))
        print("作业那一段：%s → %d 个音（%s）" % (crop_desc, len(score), where))

    # ── 路线 A：跑跟弹产品页自己的链路（推荐） ────────────────────────────
    # ── 路线 0（默认）：作业批改自己的链路 —— 我们的起音+配对，引擎的判定 ──
    if args.engine == "pair":
        rows, pinfo = pair_pipeline(args.audio, score, jobdir, (lo, hi),
                                    tempo=standard.get("tempo"))
        counts = {"ok": 0, "wrong_note": 0, "missing": 0, "extra": 0}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        # 多弹：只有"能再独立对齐上谱面大部分音"的那一遍才算重复弹，否则只当中性提示
        rep = pinfo.get("repeat") or {}
        issues = issues_from_rows(rows, score, standard.get("tempo"))
        # 单个音的抢/拖：≥1 秒才报（用户口径），标"节奏"、进清单，但**不吃分**
        beats = beat_index_map(score, standard.get("tempo"))
        for m in pinfo.get("timing_marks") or []:
            j = (m.get("note_index") or 0) - 1
            sn = score[j] if 0 <= j < len(score) else None
            if sn is not None and sn.get("measure") is not None:
                title = "第 %d 小节 · 第 %d 拍" % (int(sn["measure"]) + 1,
                                                beats.get(j) or (int(sn.get("beat") or 0) + 1))
            else:
                title = "本段第 %d 个音" % (j + 1)
            sub = m.get("sub")
            if sub in ("early", "late"):
                detail = ("这里%s了 %.1f 秒 —— 这一下跟节拍器单独走一遍。"
                          % ("抢" if sub == "early" else "拖", abs(m.get("dev") or 0)))
            else:
                detail = ("这里谱面本来要接着弹，你停了约 %.1f 秒 —— 弹错了也接着往下，别停。"
                          % (m.get("seconds") or 0))
            issues.append({
                "title": title,
                "measure": (int(sn["measure"]) + 1) if sn is not None
                           and sn.get("measure") is not None else None,
                "beat": (beats.get(j) if sn is not None else None),
                "note_index": j + 1, "t_audio": m.get("t_audio"),
                "t_score": m.get("t_score"), "kind": IT.normalize("timing", sub),
                "detail": detail, "fix": "开着节拍器，从慢速把这一句走顺。",
                "items": [{"want": None, "got": None,
                           "kind": IT.normalize("timing", sub),
                           "measure": None, "beat": None, "t_audio": m.get("t_audio")}],
            })
        if rep.get("repeat"):
            pass  # 重复的那一遍不当作问题（下面写进"过程提醒"）
        elif rep.get("count", 0) >= 3:
            issues.append({
                "title": "有 %d 个音没对上谱面" % rep["count"],
                "measure": None, "beat": None, "note_index": None,
                "t_audio": None, "t_score": None, "kind": "extra_note",
                "detail": ("录音里有 %d 个音对不上谱面 —— 可能是多弹，也可能是杂音，"
                           "这一段没算进分数。" % rep["count"]),
                "fix": "对着谱子再走一遍，只弹谱面上的音。",
                "items": [{"want": None, "got": None, "kind": "extra_note",
                           "measure": None, "beat": None, "t_audio": None}],
            })
        # ── 节奏不稳：一段一张卡（"这一段 70、那一段 90"那种）──
        # ⚠ 顺序要紧：**先把所有问题都生成出来，再分组/排序** ——
        #   不然会出现"报告说 3 处、却摆了 4 张卡"（学隔壁那条事故的教训）。
        spans = pinfo.get("unstable_spans") or []
        if spans:
            sp = spans[0]

            def _where(a, b):
                sa = score[a] if 0 <= a < len(score) else None
                sb = score[b] if 0 <= b < len(score) else None
                if sa is not None and sa.get("measure") is not None and sb is not None:
                    if int(sa["measure"]) == int(sb["measure"]):
                        return "第 %d 小节" % (int(sa["measure"]) + 1)
                    return "第 %d~%d 小节" % (int(sa["measure"]) + 1, int(sb["measure"]) + 1)
                return "第 %d~%d 个音" % (a + 1, b + 1)

            # 按小节先后说（老师说话的顺序：先说早的那段，再说后面变成多少）
            if sp["from"] <= sp["fast_from"]:
                first, first_bpm, later, later_bpm = (
                    _where(sp["from"], sp["to"]), sp["bpm"],
                    _where(sp["fast_from"], sp["fast_to"]), sp["fast_bpm"])
                how = "快了"
            else:
                first, first_bpm, later, later_bpm = (
                    _where(sp["fast_from"], sp["fast_to"]), sp["fast_bpm"],
                    _where(sp["from"], sp["to"]), sp["bpm"])
                how = "慢了"
            issues.append({
                "title": "节奏不稳（%s → %s）" % (first, later),
                "measure": None, "beat": None, "note_index": None,
                "t_audio": None, "t_score": None, "kind": "rhythm_unstable",
                "detail": ("%s大概 %d 拍/分，到了%s变成 %d 左右（%s约 %d%%）—— "
                           "这一遍一会儿快一会儿慢，跟着节拍器再走两遍。"
                           % (first, first_bpm, later, later_bpm, how,
                              int(round((sp["ratio"] - 1) * 100)))),
                "fix": "开着节拍器，整段慢速走两遍。",
                "items": [{"want": None, "got": None, "kind": "rhythm_unstable",
                           "measure": None, "beat": None, "t_audio": None}],
            })

        sc = score_of(counts, len(score))
        groups = rank_groups(group_issues(issues))
        key_groups = groups[:KEY_ISSUES]
        rest_groups = groups[KEY_ISSUES:]
        pauses = [(m["t_audio"], m["seconds"]) for m in pinfo.get("timing_marks", [])
                  if m.get("seconds") is not None]
        process = process_notes([{"t": e["t"]} for e in pinfo.get("onsets_list", [])],
                                score, pauses=pauses)
        if spans:
            process = [p for p in process if not p.startswith("整段速度和节奏是稳的")]
        if pinfo.get("weak_confirmed"):
            process.insert(0, "有 %d 处听着就是谱面那个位置，只是这一下不够实"
                              "（多半是上一个音还在响）—— 这几处算过。"
                           % pinfo["weak_confirmed"])
        if rep.get("repeat"):
            process.insert(0, "你把作业弹了两遍：第二遍有 %d/%d 个音也对上了。"
                              "作业只需要一遍，多出来的第二遍没算进分数。"
                           % (rep.get("matched", 0), rep.get("score_notes", len(score))))
        # ⚠ "报告里说几处" 必须等于 "界面上摆出来的卡片数"（学隔壁那次事故的教训）：
        #   卡片 = 合并后的组（一句连着 3 个音算 1 处），所以这里数**组数**，
        #   而页面渲染的正好是 key_issues(前 3 张) + more_issues(其余)。
        n_problems = len(groups)
        assert len(key_groups) + len(rest_groups) == n_problems, "卡片数和处数对不上"
        vtext = verdict_text(sc, PASS_LINE, key_groups, process, n_problems)
        print("")
        print("=" * 70)
        print("逐音：对 %d ｜ 错 %d ｜ 漏 %d ｜ 多弹 %d ｜ 得分 %.0f"
              % (counts["ok"], counts["wrong_note"], counts["missing"],
                 counts["extra"], sc))
        print("总评：%s" % vtext)
        for i, g in enumerate(groups):
            print("  [%s] %s ｜ %s" % ("重点" if i < KEY_ISSUES else "其余",
                                       g["title"], g["detail"]))
        for line in process:
            print("  过程：%s" % line)
        standard = dict(standard)
        standard["align_offset"] = round(pinfo["offset"], 3)
        standard["align_scale"] = round(pinfo["scale"], 4)
        result = {
            "job": job, "ref": ref_src, "audio": args.audio,
            "ref_used": ref_path, "ref_crop": crop_desc, "ref_notes": len(score),
            "standard": standard,
            "engine": "作业批改自己的链路（我们的配对 + GuitarFollow 的 judgeNote）",
            "align": {"mode": pinfo["mode"], "low_confidence": False,
                      "offset": round(pinfo["offset"], 3),
                      "scale": round(pinfo["scale"], 4),
                      "matched": pinfo["matched"], "onsets": pinfo["onsets"],
                      "slots": pinfo["slots"], "multi_slots": pinfo["multi_slots"],
                      "slots_matched": pinfo["slots_matched"]},
            "counts": counts, "judged_slots": pinfo["matched"],
            "verdict_text": vtext, "groups": groups, "key_issues": key_groups,
            "process": process, "score": sc, "issues": groups,
            # 节奏的原始数据留着（界面上不逐音报，但调门槛时要看）
            "timing": {"marks": pinfo.get("timing_marks") or [],
                       "unstable_spans": pinfo.get("unstable_spans") or [],
                       "tol_rule": "clamp(到下一个音的间隔 × 45%, 100ms, 350ms)，第一个音 ×2",
                       "unstable_rule": "滑窗 %d 个间隔内 最快/最慢 > %.1f 倍"
                                         % (UNSTABLE_WIN, UNSTABLE_RATIO)},
        }
        with io.open(os.path.join(jobdir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        page = {
            "score": sc, "pass_line": PASS_LINE, "passed": sc >= PASS_LINE,
            "coverage": int(round(100.0 * pinfo["matched"] / max(1, len(score)))),
            "accuracy": int(round(100.0 * counts["ok"]
                                  / max(1, counts["ok"] + counts["wrong_note"]))),
            "counts": {"right": counts["ok"], "wrong": counts["wrong_note"],
                       "missing": counts["missing"], "extra": counts["extra"]},
            "summary": vtext, "verdict_text": vtext,
            "issues": [{"title": g["title"], "t_audio": g["t_audio"],
                        "t_score": g.get("t_score"), "kind": g["items"][0].get("kind"),
                        "detail": g["detail"],
                        "fix": g["fix"]} for g in groups],
            "key_issues": [{"title": g["title"], "t_audio": g["t_audio"],
                            "t_score": g.get("t_score"), "note_index": g.get("from_note"),
                            "measure": g.get("measure"), "beat": g.get("beat"),
                            "kind": g["items"][0].get("kind"),
                            "detail": g["detail"], "fix": g["fix"],
                            "note_count": len(g["items"])} for g in key_groups],
            "more_issues": [{"title": g["title"], "t_audio": g["t_audio"],
                             "t_score": g.get("t_score"),
                             "kind": g["items"][0].get("kind"),
                             "note_count": len(g["items"])} for g in rest_groups],
            "error_notes": [{"t_score": it.get("t_score"), "t_audio": it.get("t_audio"),
                             "note_index": it.get("note_index"),
                             "measure": it.get("measure"), "beat": it.get("beat"),
                             "kind": it.get("kind"),
                             "want": note_pair(it)[0], "got": note_pair(it)[1]}
                            for it in issues if it.get("kind") != "timing"]
                           + [dict(m, kind="timing")
                              for m in pinfo.get("timing_marks") or []],
            "process": process,
            "issue_labels": IT.LABELS,          # 前端的类型标签只认这一份（别两边各写一套）
            "issue_total": n_problems,
            "score_notes": [{"t": round(n["t"], 3), "string": n.get("string"),
                             "midi": int(n["midi"])} for n in score],
            "error_marks": [],
            "ref_crop": crop_desc, "ref_notes": len(score),
            "standard": standard,
            "note": (("谱面里有 %d 处是好几个音一起响，按「一个起音判这一格"
                      "里的所有弦」算。" % pinfo["multi_slots"])
                     if pinfo["multi_slots"] else "")
                    + "数字来自「作业批改自己的链路」：起音和判定都是 GuitarFollow engine 的代码"
                    "（判定窗口/opts 照产品页那一处调用），配对（对齐）由作业检查自己做"
                    "——所以漏一个音只会报一处漏，不会一路错位。"
                    "得分 = 弹对的音 ÷ 本次作业的音数（%d/%d）。" % (counts["ok"], len(score)),
        }
        with io.open(os.path.join(jobdir, "page.json"), "w", encoding="utf-8") as f:
            json.dump(page, f, ensure_ascii=False, indent=1)
        print("结果已写到 %s" % os.path.join(jobdir, "result.json"))
        return 0

    if args.engine == "follow":
        res, out = run_follow_harness(ref_path, args.audio)
        good, bad = int(res.get("good") or 0), int(res.get("bad") or 0)
        missed = int(res.get("missed") or 0)
        unclear = int(res.get("unclear") or 0)
        wrongs = res.get("wrongs") or ""
        print("起音 %d 次 ｜ 对 %d ｜ 错 %d ｜ 漏 %d ｜ 测不准 %d"
              % (res.get("onsets") or 0, good, bad, missed, unclear))
        log = res.get("log") or []
        # 位置从**跟弹导出记录**里取（哪一下、什么时刻），不再猜"第几小节第几拍"
        issues = (issues_from_log(log, score, standard.get("tempo")) if log
                  else issues_from_wrongs(wrongs, score))
        if log and len(issues) != bad:
            print("⚠ 逐音记录里挑出 %d 处错音，页面计数 %d —— 报告以逐音记录为准"
                  % (len(issues), bad))
        counts = {"ok": good, "wrong_note": bad, "missing": missed, "extra": 0}
        sc = score_of(counts, len(score))
        judged = judged_slots(log) or (good + bad)
        # 报告层：聚成"一句"、排影响、只展开前几条；再给总评和过程提醒
        groups = rank_groups(group_issues(issues))
        key_groups = groups[:KEY_ISSUES]
        rest_groups = groups[KEY_ISSUES:]
        process = process_notes(res.get("onsets2") or [], score)
        vtext = verdict_text(sc, PASS_LINE, key_groups, process, len(issues))
        # 跟弹页面的"对/错"是**每次判定都算一次**（一格被反复重判时会重复计），
        # 所以"对+错"可能大于"判过的谱面格数"。这里如实记下来，别让页面上两个数打架。
        tally_note = ""
        if judged:
            tally_note = ("（完成度 = 引擎判读过的谱面音 ÷ 本次作业的音数 = %d/%d；"
                          "跟弹页面的对/错按「判定次数」计，同一格被反复重判时会重复计，"
                          "所以「对＋错」不一定等于判读过的格数）" % (judged, len(score)))
        result = {
            "job": job, "ref": ref_src, "audio": args.audio,
            "ref_used": ref_path, "ref_crop": crop_desc, "ref_notes": len(score),
            "standard": standard,
            "engine": "GuitarFollow 产品页链路（test-follow-real.mjs）",
            "align": {"mode": "跟弹链路自带（按播放位置）", "low_confidence": False,
                      "confidence": None},
            "counts": {"ok": good, "wrong_note": bad, "missing": missed,
                       "unclear": unclear, "extra": 0},
            "judged_slots": judged,
            "tally_note": tally_note,
            "judge_log": log,
            "groups": groups,
            "key_issues": key_groups,
            "process": process,
            "verdict_text": vtext,
            "score": sc,
            "issues": issues,
            "wrongs": wrongs,
            "score_notes": [{"idx": i, "t": round(n["t"], 3), "string": n.get("string"),
                             "midi": int(n["midi"])} for i, n in enumerate(score)],
            "error_marks": [{"t": it["t_audio"], "idx": (it["note_index"] - 1)
                             if it.get("note_index") else None}
                            for it in issues if it["t_audio"]],
        }
        with io.open(os.path.join(jobdir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        # 页面要的那份（server.py 直接读）
        page = {
            "score": sc, "pass_line": PASS_LINE, "passed": sc >= PASS_LINE,
            "coverage": int(round(100.0 * judged / max(1, len(score)))),
            "accuracy": int(round(100.0 * good / max(1, good + bad))),
            "counts": {"right": good, "wrong": bad, "missing": missed},
            "summary": vtext,
            "verdict_text": vtext,
            "issues": [{"title": it["title"], "t_audio": it["t_audio"],
                        "t_score": it.get("t_score"), "note_index": it.get("note_index"),
                        "measure": it.get("measure"), "beat": it.get("beat"),
                        "detail": it["detail"], "fix": it["fix"]} for it in groups],
            "key_issues": [{"title": it["title"], "t_audio": it["t_audio"],
                            "t_score": it.get("t_score"), "note_index": it.get("note_index"),
                            "measure": it.get("measure"), "beat": it.get("beat"),
                            "detail": it["detail"], "fix": it["fix"],
                            "note_count": len(it["items"])} for it in key_groups],
            "more_issues": [{"title": it["title"], "t_audio": it["t_audio"],
                             "t_score": it.get("t_score"),
                             "note_count": len(it["items"])} for it in rest_groups],
            # 逐个错音（给报告里"谱面上标红"用）：位置、要的音、听到的音
            "error_notes": [{"t_score": it.get("t_score"), "t_audio": it.get("t_audio"),
                             "note_index": it.get("note_index"),
                             "measure": it.get("measure"), "beat": it.get("beat"),
                             "want": note_pair(it)[0], "got": note_pair(it)[1]}
                            for it in issues],
            "process": process,
            "score_notes": result["score_notes"],
            "error_marks": result["error_marks"],
            "ref_crop": crop_desc, "ref_notes": len(score), "judged_slots": judged,
            "standard": standard,
            "note": "数字来自跟弹产品页那条链路（同一份判定代码），用的是你这次交的录音。"
                    + tally_note,
        }
        with io.open(os.path.join(jobdir, "page.json"), "w", encoding="utf-8") as f:
            json.dump(page, f, ensure_ascii=False, indent=1)
        print("")
        print("=" * 70)
        print("逐音：对 %d ｜ 错 %d ｜ 漏 %d ｜ 得分 %.0f" % (good, bad, missed, sc))
        print("总评：%s" % vtext)
        for i, g in enumerate(groups):
            print("  [%s] %s ｜ %s" % ("重点" if i < KEY_ISSUES else "其余",
                                       g["title"], g["detail"]))
        for line in process:
            print("  过程：%s" % line)
        print("结果已写到 %s" % os.path.join(jobdir, "result.json"))
        return 0

    # ① 起音（Node，跟弹 engine）
    events_path = os.path.join(jobdir, "events.json")
    print(run_node("engine_bridge.mjs", args.audio, events_path, lo, hi).strip())
    events = load_json(events_path)["events"]

    # ② 对齐：有身份就身份锚定，没有就退回按时间（并打低置信度）
    with_id = sum(1 for e in events if e.get("midi") is not None)
    if with_id >= 8:
        result = align(score, events, window=0.30)
        mode = "身份锚定"
    else:
        result = align_by_time(score, events, window=0.30)
        mode = "按时间（退路）"
    print("\n对齐方式：%s" % mode)
    print("  " + result.summary().replace("\n", "\n  "))
    for w in result.warnings:
        print("  ⚠ " + w)

    # ③ 判定（Node，跟弹 engine）：给对齐好的 (时刻, 期望音) 逐个判
    pairs = [{"t": events[i]["t"], "expectedMidi": int(score[j]["midi"])}
             for i, j in result.matches]
    pairs_path = os.path.join(jobdir, "pairs.json")
    judged_path = os.path.join(jobdir, "judged.json")
    with io.open(pairs_path, "w", encoding="utf-8") as f:
        json.dump({"audio": args.audio, "band": [lo, hi], "pairs": pairs}, f,
                  ensure_ascii=False, indent=1)
    print("")
    print(run_node("engine_judge.mjs", pairs_path, judged_path).strip())
    judged = load_json(judged_path)["judged"]

    # ④ 逐音对错 → 聚合 → 打分
    by_note = {j: k for k, (_, j) in enumerate(result.matches)}
    rows = []
    for j, sn in enumerate(score):
        base = {"score_idx": j, "t_score": sn["t"], "want": note_name(sn["midi"]),
                "string": sn.get("string"), "fret": sn.get("fret"),
                "measure": sn.get("measure"), "beat": sn.get("beat")}
        if j in by_note:
            k = by_note[j]
            jd = judged[k]
            i = result.matches[k][0]
            base["t_audio"] = events[i]["t"]
            if jd["pass"]:
                rows.append(dict(base, kind="ok", got=base["want"]))
            else:
                rows.append(dict(base, kind="wrong_note", got=jd.get("heardName")))
        else:
            rows.append(dict(base, kind="missing", t_audio=None, got=None))
    for i in result.unmatched_events:
        rows.append({"score_idx": None, "kind": "extra", "t_audio": events[i]["t"],
                     "want": None, "got": None, "measure": None, "beat": None})

    counts = {"ok": 0, "wrong_note": 0, "missing": 0, "extra": 0}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    issues = build(rows, score)
    sc = score_of(counts, len(score))

    out = {
        "job": args.job,
        "ref": args.ref,
        "audio": args.audio,
        "align": {"mode": mode, "offset": round(result.offset, 3),
                  "scale": round(result.scale, 4),
                  "confidence": round(result.confidence, 3),
                  "low_confidence": result.low_confidence,
                  "residual_median_ms": round(result.residual_median * 1000),
                  "coverage": round(result.coverage * 100)},
        "counts": counts,
        "score": sc,
        "issues": issues,
        "score_notes": [{"t": round(n["t"], 3), "string": n.get("string"),
                         "midi": int(n["midi"])} for n in score],
        "error_marks": [{"t": round(judged[k]["t"], 3)}
                        for k in range(len(judged)) if not judged[k]["pass"]],
        "rows": rows,
    }
    out_path = os.path.join(jobdir, "result.json")
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("")
    print("=" * 70)
    print("逐音：对 %d ｜ 错 %d ｜ 漏 %d ｜ 多弹 %d ｜ 得分 %.0f"
          % (counts["ok"], counts["wrong_note"], counts["missing"], counts["extra"], sc))
    print("聚合后的问题 %d 条：" % len(issues))
    for it in issues:
        print("  · " + it["detail"])
    print("结果已写到 %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
