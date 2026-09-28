# -*- coding: utf-8 -*-
"""作业检查 · 对齐：身份锚定 + 单调路径（纯标准库，不装依赖）。

为什么不能"只看时间"
--------------------
`实测-对齐-2026-09-24.md` 已经量过：这段谱面音间隔中位 395ms、最短 197ms，
窗口一放到 ±300ms，错的 offset 也能"蒙对"一大批音 —— 盲拟合给出 2.12s / 1.38s，
而用「音的身份（音名 + 弦 + 品）」独立验出来是 ≈2.50s，差了 0.4~1.1 秒。

所以这里的顺序是死的：
    ① 身份锚定：用「音名(+弦+品)」找候选，反推隐含 offset，取最大一致簇；
    ② 钉死 offset 之后再估 scale（两个参数一起解，短素材上解不稳，见实测②）；
    ③ 在候选上跑单调 DP（两条序列都允许跳过），保证"人不会倒着弹"；
    ④ 出置信度（锚点比例 / 身份一致率 / 残差中位数）——低的直接标
       `low_confidence`，**不许出结论**。

边界（铁律 Q15 / Q29）
----------------------
这里不判定音准、不重写 engine、不复制抖音检测；只回答一个问题：
**录音里第 i 个音，对应谱面第 j 个音。**

用法
----
    E:\\Python\\python.exe -X utf8 homework\\align.py ^
        --score E:\\GuitarFollowLab\\frontend\\data\\hey_jude.json ^
        --labels C:\\Users\\Administrator\\vc_gf\\heyjude-labels.json
"""

import argparse
import io
import json
import os
import random
import statistics
import sys
from dataclasses import dataclass, field

NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi):
    midi = int(round(float(midi)))
    return "%s%d" % (NOTE[midi % 12], midi // 12 - 1)


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 输入归一化 ────────────────────────────────────────────────────────────

def normalize_note(raw):
    """谱面音 / 事件都能吃：'str' 和 'string' 都认。"""
    return {
        "t": float(raw["t"]),
        "midi": None if raw.get("midi") is None else int(round(float(raw["midi"]))),
        "string": raw.get("string", raw.get("str")),
        "fret": raw.get("fret"),
        "measure": raw.get("measure"),
        "beat": raw.get("beat"),
        "dur": raw.get("dur"),
    }


def load_score(path):
    d = load_json(path)
    notes = [normalize_note(n) for n in d["notes"]]
    notes.sort(key=lambda n: n["t"])
    return d.get("meta", {}) or {}, notes


def load_events(path):
    """事件文件支持三种写法：
    {"events": [...]} / {"notes": [...]}（手标文件）/ 直接一个 list。
    """
    d = load_json(path)
    if isinstance(d, dict):
        raw = d.get("events") or d.get("notes") or []
    else:
        raw = d
    out = [normalize_note(e) for e in raw]
    out.sort(key=lambda e: e["t"])
    return out


def filter_score(notes, t_from=None, t_to=None):
    """把谱面裁到"这次作业那一段"。

    真正的产品里，作业的 .gp 上传的就是这一段，不需要裁；
    但我们现在借的是整首歌的时间轴（0.79~71s），而真机录音只有前 25 秒，
    不裁的话剩下 77 个音会被算成"漏弹"。裁完才算同一把尺子。
    """
    if t_from is None and t_to is None:
        return notes
    keep = [n for n in notes
            if (t_from is None or n["t"] >= t_from)
            and (t_to is None or n["t"] <= t_to)]
    return keep or notes


# ── 身份 ─────────────────────────────────────────────────────────────────

def identity(note, use_string=True):
    """能带上弦品就带上弦品；带不上就只按音名。

    弦品齐的才叫「强身份」——密集谱面上光靠音名会撞车（同一首歌一句里
    重复音很多），所以强身份锚点的比例直接进置信度。
    """
    midi = int(round(float(note["midi"])))
    if use_string and note.get("string") is not None and note.get("fret") is not None:
        return (midi, int(note["string"]), int(note["fret"]))
    return (midi,)


def is_strong_identity(note):
    return (note.get("midi") is not None
            and note.get("string") is not None
            and note.get("fret") is not None)


def same_pitch(a, b):
    if a.get("midi") is None or b.get("midi") is None:
        return None
    return int(round(float(a["midi"]))) == int(round(float(b["midi"])))


# ── ①② 身份锚定 + 速度比例：RANSAC 拟合仿射映射 ──────────────────────────

def candidate_pairs(score, events, use_string=True):
    """所有身份相同的 (事件, 谱面音) 配对 —— 只看身份，不看时间。

    实测里被否掉的是"时间最近的那个音"；身份配对是它的反面：
    哪怕时间差得远，只要身份一样就是候选，让后面的 RANSAC 去投票。
    """
    by_id = {}
    for j, sn in enumerate(score):
        if sn.get("midi") is None:
            continue
        by_id.setdefault(identity(sn, use_string), []).append(j)
    pairs = []
    for i, ev in enumerate(events):
        if ev.get("midi") is None:
            continue
        for j in by_id.get(identity(ev, use_string), ()):
            pairs.append((i, j))
    return pairs


def _inliers(pairs, score, events, offset, scale, tol):
    """每个事件最多算一个 inlier（取残差最小的那个身份配对）。"""
    best = {}
    for i, j in pairs:
        r = events[i]["t"] - (offset + scale * score[j]["t"])
        if abs(r) <= tol and (i not in best or abs(r) < abs(best[i][2])):
            best[i] = (i, j, r)
    return list(best.values())


def _scale_one_ballot(pairs, score, events, tol):
    """scale = 1 的位移假设：把隐含 offset 投进票箱，取最大簇的中位数。"""
    vals = sorted((events[i]["t"] - score[j]["t"], i, j) for i, j in pairs)
    if not vals:
        return None, []
    best, lo = (-1, 0, 0), 0
    for hi in range(len(vals)):
        while vals[hi][0] - vals[lo][0] > tol:
            lo += 1
        hits = len({v[1] for v in vals[lo:hi + 1]})
        if hits > best[0]:
            best = (hits, lo, hi)
    _, blo, bhi = best
    offset = statistics.median([v[0] for v in vals[blo:bhi + 1]])
    return offset, _inliers(pairs, score, events, offset, 1.0, tol)


def _least_squares(inliers, score, events):
    """在 inlier 上做最小二乘 —— "票数最多"只是初值，"残差最小"才是真值。"""
    xs = [score[j]["t"] for _, j, _ in inliers]
    ys = [events[i]["t"] for i, _, _ in inliers]
    k = len(xs)
    mx = sum(xs) / k
    my = sum(ys) / k
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 1e-9:
        return my - mx, 1.0
    scale = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return my - scale * mx, scale


def _hypothesis(pairs, score, events, offset, scale, tol, start_window):
    """给一条候选线打分：(inlier 数, 是否从作业开头开始, -残差中位, ...)。

    为什么要有"从作业开头开始"这一票：一首歌里同一个乐句会重复，光看
    "身份对得上"分不出"第一遍"和"第二遍"（Hey Jude 实测就是这样：
    +2.5s 和 -22.7s 两条线的 inlier 一样多）。铁律 Q19 说的是"允许学员
    **前面空着**"，不是"允许从曲子中间任意位置开始" —— 所以学员的第一个音
    应该落在谱面开头的一段里。这条只当**同分时的第二个判据**，不影响
    inlier 更多的候选（比如整段开头都漏掉的极端情况）。
    """
    inl = _inliers(pairs, score, events, offset, scale, tol)
    if not inl:
        return None
    med = statistics.median([abs(x[2]) for x in inl])
    if start_window is None:
        starts_at_head = 1
    else:
        starts_at_head = 1 if min(score[j]["t"] for _, j, _ in inl) <= start_window else 0
    return (len(inl), starts_at_head, -med, offset, scale, inl)


def fit_affine(score, events, tol=0.20, use_string=True, scale_lo=0.75,
               scale_hi=1.35, iters=4000, seed=20260924, min_anchor_events=8,
               start_window=6.0):
    """用身份锚点拟合 `t_event = offset + scale * t_score`。

    两个假设都试，谁的 inlier 多谁赢：
      * scale = 1：Q19 的"整体位移"（实测证明这条最稳，先给它一票）；
      * 两点定斜率的任意变速：Q21 的"允许整体变速"，RANSAC 抗异常。
    锚点太少 → 不敢信斜率，退回纯位移并把 `scale_estimated` 标 False。

    返回 (offset, scale, inlier_pairs, scale_estimated, anchor_events)。
    """
    pairs = candidate_pairs(score, events, use_string)
    if not pairs:
        return 0.0, 1.0, [], False, 0

    offset1, inl1 = _scale_one_ballot(pairs, score, events, tol)
    best = None
    if inl1:
        cand = _hypothesis(pairs, score, events, offset1, 1.0, tol, start_window)
        if cand is not None:
            best = cand + (True,)

    by_event = {}
    for i, j in pairs:
        by_event.setdefault(i, []).append(j)
    evs = sorted(by_event)
    if len(evs) >= 2:
        rnd = random.Random(seed)
        for _ in range(iters):
            i1, i2 = rnd.sample(evs, 2)
            j1 = rnd.choice(by_event[i1])
            j2 = rnd.choice(by_event[i2])
            dt = score[j1]["t"] - score[j2]["t"]
            if abs(dt) < 2.0:
                continue
            scale = (events[i1]["t"] - events[i2]["t"]) / dt
            if not (scale_lo <= scale <= scale_hi):
                continue
            offset = events[i1]["t"] - scale * score[j1]["t"]
            cand = _hypothesis(pairs, score, events, offset, scale, tol, start_window)
            if cand is None:
                continue
            if best is None or cand[:3] > best[:3]:
                best = cand + (False,)

    if best is None:
        return 0.0, 1.0, [], False, 0
    _, _, _, offset, scale, inliers, from_unit = best

    # 精修：RANSAC 只挑了"票数最多"的线，抖动会把它挑偏几十毫秒；
    # 在 inlier 上做最小二乘，再重算 inlier，两轮就收敛。
    for _ in range(2):
        if len(inliers) < 3:
            break
        noff, nscale = _least_squares(inliers, score, events)
        if not (scale_lo <= nscale <= scale_hi):
            break
        ninl = _inliers(pairs, score, events, noff, nscale, tol)
        if len(ninl) < len(inliers):
            break
        scale, offset, inliers = nscale, noff, ninl

    n_inl = len(inliers)
    if n_inl < min_anchor_events:
        if inl1:
            return offset1, 1.0, inl1, False, len(inl1)
        return offset, 1.0, inliers, False, n_inl
    return offset, scale, inliers, abs(scale - 1.0) > 0.005, n_inl


# ── ③ 单调路径（DP）────────────────────────────────────────────────────────

def monotonic_path(score, events, offset, scale, window=0.30, use_string=True,
                   match_bonus=1.0, pitch_only_weight=0.70,
                   mismatch_weight=0.30, gap=-0.75):
    """在候选上找最大权重的单调路径。

    两条序列都允许跳过：跳过事件 = 多弹/杂音，跳过谱面音 = 漏弹。
    权重里"身份一致"最重、"音名同按法不同"次之、"音名都不同（可能真弹错了）"最轻，
    再减去时间残差 —— 这样才不会为了迁就一个错音把后面整段带歪。
    """
    n, m = len(events), len(score)
    NEG = float("-inf")
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    def weight(i, j):
        ev, sn = events[i], score[j]
        r = ev["t"] - (offset + scale * sn["t"])
        if abs(r) > window:
            return None
        if ev.get("midi") is None:
            w = match_bonus * 0.60
        else:
            ev_key, sn_key = identity(ev, use_string), identity(sn, use_string)
            if ev_key == sn_key:
                w = match_bonus
            elif ev_key[0] == sn_key[0]:
                w = match_bonus * pitch_only_weight
            else:
                w = mismatch_weight
        w -= 0.5 * abs(r) / window
        return w

    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == NEG:
                continue
            if i < n and cur + gap > dp[i + 1][j]:
                dp[i + 1][j] = cur + gap
                back[i + 1][j] = ("skip_event", i, j)
            if j < m and cur + gap > dp[i][j + 1]:
                dp[i][j + 1] = cur + gap
                back[i][j + 1] = ("skip_note", i, j)
            if i < n and j < m:
                w = weight(i, j)
                if w is not None and cur + w > dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = cur + w
                    back[i + 1][j + 1] = ("match", i, j)

    matches = []
    i, j = n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if b is None:
            break
        kind, pi, pj = b
        if kind == "match":
            matches.append((pi, pj))
        i, j = pi, pj
    matches.reverse()
    return matches


# ── ④ 置信度 ─────────────────────────────────────────────────────────────

@dataclass
class AlignResult:
    offset: float
    scale: float
    matches: list = field(default_factory=list)        # [(event_idx, score_idx)]
    unmatched_events: list = field(default_factory=list)
    unmatched_notes: list = field(default_factory=list)
    residual_median: float = 0.0                       # 秒
    residual_p90: float = 0.0
    identity_agreement: float = 0.0
    anchor_events: int = 0
    anchor_ratio: float = 0.0
    strong_anchor_ratio: float = 0.0
    scale_estimated: bool = False
    coverage: float = 0.0                              # 谱面音被对上的比例
    confidence: float = 0.0
    low_confidence: bool = False
    window: float = 0.30
    warnings: list = field(default_factory=list)

    def summary(self):
        return ("offset %+.3fs ｜ scale %.4f ｜ 对上 %d/%d 谱面音 ｜ 事件 %d 里用到 %d\n"
                "身份一致率 %.0f%% ｜ 强锚点 %d 个（%.0f%% 事件）｜ 残差中位 %.0fms p90 %.0fms\n"
                "置信度 %.2f%s"
                % (self.offset, self.scale, len(self.matches),
                   len(self.matches) + len(self.unmatched_notes),
                   len(self.matches) + len(self.unmatched_events), len(self.matches),
                   self.identity_agreement * 100, self.anchor_events,
                   self.strong_anchor_ratio * 100,
                   self.residual_median * 1000, self.residual_p90 * 1000,
                   self.confidence,
                   "  ⚠ 低置信度，不出结论" if self.low_confidence else ""))


def _pct(vals, p):
    if not vals:
        return 0.0
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round((len(vals) - 1) * p)))]


# ── 没有身份可用时的退路：只用起音时刻 ────────────────────────────────────

def align_by_time(score, events, window=0.25, scale=1.0, lo=0.0, hi=8.0,
                  coarse=0.05, fine=0.01):
    """只用起音时刻做单调对齐 —— **明知道它不如身份锚定，是退路**。

    什么时候会用到：这段材料上"每响读一个音名"读不出来（本机实测：60 个起音里
    54 个没有成串基频；跟弹那边也量到"琶音 0/52"）。这时候唯一还能用的信息就是
    "他在哪儿拨的"。做法是在 offset 网格上各跑一遍单调 DP，取"对上的最多、
    残差中位最小"的那个，先粗搜再精搜。

    产出的结果**一律标 low_confidence**：实测已经证明盲拟合会被密集谱面蒙过去，
    所以这份对齐只能当"参考"，报告层必须说明它是建立在时间对齐上的。
    """
    def score_of(offset):
        m = monotonic_path(score, events, offset, scale, window=window)
        res = [abs(events[i]["t"] - (offset + scale * score[j]["t"])) for i, j in m]
        med = statistics.median(res) if res else 9.9
        return m, med

    best = None
    o = lo
    while o <= hi:
        m, med = score_of(o)
        key = (len(m), -med)
        if best is None or key > best[0]:
            best = (key, o, m, med)
        o += coarse
    if best is None:
        best = (((0, 0.0)), lo, [], 9.9)
    _, o0, _, _ = best
    o = o0 - coarse
    while o <= o0 + coarse:
        m, med = score_of(o)
        key = (len(m), -med)
        if key > best[0]:
            best = (key, o, m, med)
        o += fine

    (_, neg_med), offset, matches, med = best
    matched_notes = {j for _, j in matches}
    matched_events = {i for i, _ in matches}
    res = [abs(events[i]["t"] - (offset + scale * score[j]["t"])) for i, j in matches]
    return AlignResult(
        offset=offset, scale=scale, matches=matches,
        unmatched_events=sorted(set(range(len(events))) - matched_events),
        unmatched_notes=sorted(set(range(len(score))) - matched_notes),
        residual_median=med, residual_p90=_pct(sorted(res), 0.90),
        identity_agreement=0.0, anchor_events=0, anchor_ratio=0.0,
        strong_anchor_ratio=0.0, scale_estimated=False,
        coverage=len(matched_notes) / float(max(1, len(score))),
        confidence=0.35, low_confidence=True, window=window,
        warnings=["没有可用的音高身份，这次是**按时间对齐**的（退路，不是默认路径）"])


def align(score, events, window=0.30, use_string=True, tol=0.20, start_window=6.0):
    """一整套：身份锚定 + 估 scale（RANSAC）→ 单调 DP → 置信度。"""
    offset, scale, anchors, scale_estimated, anchor_events = fit_affine(
        score, events, tol=tol, use_string=use_string, start_window=start_window)
    anchor_ratio = anchor_events / float(max(1, len(events)))
    matches = monotonic_path(score, events, offset, scale,
                             window=window, use_string=use_string)

    res = [events[i]["t"] - (offset + scale * score[j]["t"]) for i, j in matches]
    absres = [abs(r) for r in res]

    has_id = [i for i, _ in matches if events[i].get("midi") is not None]
    agree = [i for i in has_id if same_pitch(events[i], score[dict(matches)[i]])]
    identity_agreement = (len(agree) / float(len(has_id))) if has_id else 0.0

    strong = sum(1 for e in events if is_strong_identity(e)) if use_string else 0
    strong_ratio = strong / float(max(1, len(events)))

    matched_notes = {j for _, j in matches}
    matched_events = {i for i, _ in matches}
    coverage = len(matched_notes) / float(max(1, len(score)))
    residual_median = statistics.median(absres) if absres else 9.9
    residual_p90 = _pct(absres, 0.90)

    quality = max(0.0, 1.0 - residual_median / max(1e-6, window))
    confidence = (0.35 * identity_agreement + 0.30 * coverage
                  + 0.20 * strong_ratio + 0.15 * quality)

    warnings = []
    if anchor_ratio < 0.35:
        warnings.append("身份锚点太少（%.0f%% 的事件能当锚）" % (anchor_ratio * 100))
    if strong_ratio < 0.30:
        warnings.append("大部分事件没有弦品身份，密集谱面上容易认错音")
    if identity_agreement < 0.60:
        warnings.append("身份一致率只有 %.0f%%" % (identity_agreement * 100))
    if residual_p90 > 0.25:
        warnings.append("残差 p90 %.0fms 太大" % (residual_p90 * 1000))
    if len(matches) < 8:
        warnings.append("对上的音太少（%d 个）" % len(matches))

    return AlignResult(
        offset=offset, scale=scale, matches=matches,
        unmatched_events=sorted(set(range(len(events))) - matched_events),
        unmatched_notes=sorted(set(range(len(score))) - matched_notes),
        residual_median=residual_median, residual_p90=residual_p90,
        identity_agreement=identity_agreement, anchor_events=anchor_events,
        anchor_ratio=anchor_ratio, strong_anchor_ratio=strong_ratio,
        scale_estimated=scale_estimated, coverage=coverage,
        confidence=confidence,
        low_confidence=(confidence < 0.60 or len(warnings) > 0),
        window=window, warnings=warnings)


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="身份锚定 + 单调路径对齐")
    ap.add_argument("--score", default=r"E:\GuitarFollowLab\frontend\data\hey_jude.json")
    ap.add_argument("--events", default=None, help="事件 JSON（t/midi/string/fret）")
    ap.add_argument("--labels", default=None, help="手标 JSON（t/midi/str/fret）")
    ap.add_argument("--window", type=float, default=0.30)
    ap.add_argument("--pitch-only", action="store_true",
                    help="故意只按音名对齐（复现实测里'只看时间/只看音名'的失败）")
    ap.add_argument("--start-window", type=float, default=6.0,
                    help="学员第一个音应落在谱面开头这几秒内（同分时的判据）；"
                         "给负数关掉这条先验")
    ap.add_argument("--score-window", default="",
                    help="把谱面裁到这次作业那一段，写法 FROM:TO（秒），如 0:27")
    ap.add_argument("--list", type=int, default=0, help="打印前 N 条的逐音结果")
    args = ap.parse_args(argv)

    score_meta, score = load_score(args.score)
    if args.score_window:
        lo, _, hi = args.score_window.partition(":")
        score = filter_score(score, float(lo) if lo.strip() else None,
                             float(hi) if hi.strip() else None)
    path = args.events or args.labels
    if not path:
        sys.exit("至少给一个 --events 或 --labels")
    events = load_events(path)

    print("=" * 74)
    print("对齐：%s（%d 个音）" % (os.path.basename(args.score), len(score)))
    print("事件：%s（%d 个）" % (os.path.basename(path), len(events)))
    print("模式：%s" % ("只按音名" if args.pitch_only else "音名 + 弦 + 品"))
    print("=" * 74)

    start_window = None if args.start_window < 0 else args.start_window
    r = align(score, events, window=args.window, use_string=not args.pitch_only,
              start_window=start_window)
    print(r.summary())
    for w in r.warnings:
        print("  ⚠ " + w)

    if args.list:
        want = {j: i for i, j in r.matches}
        print("")
        print("谱面音 → 录音事件（前 %d 条）" % args.list)
        for j, sn in enumerate(score[:args.list]):
            if j in want:
                ev = events[want[j]]
                res = ev["t"] - (r.offset + r.scale * sn["t"])
                got = note_name(ev["midi"]) if ev.get("midi") is not None else "?"
                print("  #%-3d %6.2fs  谱面 %-4s → 录音 %-4s（%6.2fs，残差 %+5.0fms）"
                      % (j + 1, sn["t"], note_name(sn["midi"]), got, ev["t"], res * 1000))
            else:
                print("  #%-3d %6.2fs  谱面 %-4s → （没有对上的事件）"
                      % (j + 1, sn["t"], note_name(sn["midi"])))


if __name__ == "__main__":
    main()
