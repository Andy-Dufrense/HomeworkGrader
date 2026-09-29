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

JOBS = os.path.join(ROOT, "data", "jobs")

# 报告层：只展开前几条"最值得先改"的问题（Q17「有限度」在报告里的体现）
KEY_ISSUES = 3
# 过程提醒的"明显"门槛（Q9 / Q18 的建议值，用户说改就改）
TEMPO_TOL = 0.40          # 整体速度差超过 ±40% 才提
PAUSE_OVER_SEC = 1.0      # 比谱面多停 1 秒以上，且
PAUSE_RATIO = 1.8         # 超过谱面间隔的 1.8 倍，才算"明显停顿"
DRIFT_RATIO = 1.25        # 后半段比前半段慢/快 25% 以上才算"一会快一会慢"

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
        issues.append({
            "title": title,
            "measure": measure, "beat": beat,
            "note_index": no,
            "t_audio": t_audio, "t_score": t_score,
            "kind": "wrong_note",
            "detail": "这一处要 %s，听着弹成了约 %s。" % (want, got),
            "fix": "把这一处单独拎出来，慢到一半速度，每个音都按实了再连起来。",
            "items": [{"want": want, "got": got, "kind": "wrong_note",
                       "measure": measure, "beat": beat, "note_index": no,
                       "t_audio": t_audio}],
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
        cur = groups[-1] if groups else None
        if cur is not None and no is not None and cur["to_note"] is not None:
            same_bar = (it.get("measure") is not None
                        and it.get("measure") == cur["measure"])
            if (no - cur["to_note"] <= 2) or same_bar:
                cur["items"].append(it)
                cur["to_note"] = no
                continue
        groups.append({"items": [it], "from_note": no, "to_note": no,
                       "measure": it.get("measure"), "beat": it.get("beat")})
    for g in groups:
        g["title"] = group_title(g)
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
    if len(items) == 1:
        it = items[0]
        want, got = note_pair(it)
        return "这一处要 %s，听着弹成了约 %s。" % (want, got)
    parts = ["%s→%s" % note_pair(i) for i in items[:4]]
    tail = "等 %d 处" % len(items) if len(items) > 4 else ""
    return "这一句连着 %d 个音没对上：%s%s。" % (len(items), "、".join(parts), tail)


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


def process_notes(onsets, score):
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
    gaps_a = [b - a for a, b in zip(ts, ts[1:]) if b - a > 0.01]
    gaps_s = [b - a for a, b in zip(st, st[1:]) if b - a > 0.01]
    if not gaps_a or not gaps_s:
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
    worst = None
    for a, b in zip(ts, ts[1:]):
        gap = b - a
        if gap > med_s * PAUSE_RATIO and gap - med_s > PAUSE_OVER_SEC:
            if worst is None or gap > worst[1]:
                worst = (a, gap)
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
    if key_groups:
        head += "最要紧的是%s——%s" % (key_groups[0]["title"],
                                   key_groups[0]["detail"])
    return head


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


def score_of(issues, notes_total):
    """Q24 的口径（第一版）：干净 96；每处问题按影响扣分；下限 60；一处问题都没有给 100。"""
    if not issues:
        return 100.0
    deducts = [8.5] + [8.5 * 0.6] * (len(issues) - 1)
    val = 96.0 - sum(deducts)
    if len(issues) >= 3:
        val -= 2
    return float(max(60, int(round(val))))


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
    ap.add_argument("--engine", choices=["follow", "bridge"], default="follow",
                    help="follow=跑跟弹产品页自己的链路（推荐，唯一一份判定代码）；"
                         "bridge=用本仓库自己接的引擎桥（实验用，数字还不可信）")
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
        sc = score_of(issues, len(score))
        judged = judged_slots(log) or (good + bad)
        # 报告层：聚成"一句"、排影响、只展开前几条；再给总评和过程提醒
        groups = rank_groups(group_issues(issues))
        key_groups = groups[:KEY_ISSUES]
        rest_groups = groups[KEY_ISSUES:]
        process = process_notes(res.get("onsets2") or [], score)
        vtext = verdict_text(sc, 80, key_groups, process, len(issues))
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
            "score": sc, "pass_line": 80, "passed": sc >= 80,
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
            "process": process,
            "score_notes": result["score_notes"],
            "error_marks": result["error_marks"],
            "ref_crop": crop_desc, "ref_notes": len(score), "judged_slots": judged,
            "standard": standard,
            "note": "数字来自跟弹产品页那条链路（同一份判定代码），用的是真实录音。"
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
    sc = score_of(issues, len(score))

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
