# -*- coding: utf-8 -*-
"""作业检查 · 逐音比对（第一版，坐在 `align.py` 上面）。

这一版只做三件事：
    ① 把对齐结果翻成逐音结论：ok / wrong_note / missing / unjudged / extra；
    ② 按 Q17「有限度」聚合：偶发一次且后面都对上 → **不报**；
    ③ 出一个能看的 CLI。

不做什么
--------
* 不判节奏（Q18 的节拍网格）、不算分（Q24 的 scoring.py 口径）、不生成报告话术
  —— 那些是 `report.py` / 后续的事。
* 读数不可信时**不硬判**：engine 没给音名的事件算 `unjudged`，不计错。
  （跟弹那边定版口径：读数不可信退回原链路，防误杀。）
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from align import align, filter_score, load_events, load_score, note_name   # noqa: E402


def compare(score, events, result):
    """逐音结论。返回的 list 按"谱面顺序在前、多出来的事件在后"排。"""
    rows = []
    event_of_note = {j: i for i, j in result.matches}
    note_of_event = {i: j for i, j in result.matches}

    for j, sn in enumerate(score):
        base = {
            "score_idx": j,
            "t_score": sn["t"],
            "want": note_name(sn["midi"]),
            "string": sn.get("string"),
            "fret": sn.get("fret"),
            "measure": sn.get("measure"),
            "beat": sn.get("beat"),
        }
        if j not in event_of_note:
            rows.append(dict(base, kind="missing", t_audio=None, got=None))
            continue
        i = event_of_note[j]
        ev = events[i]
        base["t_audio"] = ev["t"]
        base["event_idx"] = i
        if ev.get("midi") is None:
            rows.append(dict(base, kind="unjudged", got=None))
        elif int(round(ev["midi"])) == int(round(sn["midi"])):
            rows.append(dict(base, kind="ok", got=note_name(ev["midi"])))
        else:
            rows.append(dict(base, kind="wrong_note", got=note_name(ev["midi"])))

    for i in result.unmatched_events:
        ev = events[i]
        rows.append({
            "score_idx": None, "event_idx": i, "kind": "extra",
            "t_audio": ev["t"],
            "got": None if ev.get("midi") is None else note_name(ev["midi"]),
        })
    return rows


def counts(rows):
    c = {"ok": 0, "wrong_note": 0, "missing": 0, "unjudged": 0, "extra": 0}
    for r in rows:
        c[r["kind"]] = c.get(r["kind"], 0) + 1
    c["total_score_notes"] = c["ok"] + c["wrong_note"] + c["missing"] + c["unjudged"]
    return c


def aggregate(rows):
    """按 Q17 聚合"问题"。第一版规则，数值待标定：

    * 连续 >=2 个 problem（错音/漏弹）→ 报一条；
    * 孤立 1 个 problem，但后面连着 >=2 个 ok → 不报（"漏一次后面都对上"）；
    * 孤立 1 个 problem 且后面没接上 → 报；
    * unjudged 不进 problem（读数不可信不硬判）；
    * extra（多弹）同样聚合：孤立 1 个不报，成片才报。
    """
    problems = [r for r in rows if r["kind"] in ("wrong_note", "missing")]
    issues = []
    idx = 0
    while idx < len(problems):
        run = [problems[idx]]
        while (idx + len(run) < len(problems)
               and problems[idx + len(run)]["score_idx"]
               == problems[idx + len(run) - 1]["score_idx"] + 1):
            run.append(problems[idx + len(run)])
        reported = len(run) >= 2
        if not reported:
            # 孤立一次：看后面两个谱面音是不是都 ok
            last = run[-1]["score_idx"]
            after = [r for r in rows
                     if r["score_idx"] is not None and r["score_idx"] > last]
            reported = not (len(after) >= 2 and all(r["kind"] == "ok" for r in after[:2]))
        if reported:
            issues.append({
                "kind": "note_error",
                "from_score_idx": run[0]["score_idx"],
                "to_score_idx": run[-1]["score_idx"],
                "t_audio": run[0]["t_audio"],
                "items": run,
            })
        idx += len(run)

    extras = [r for r in rows if r["kind"] == "extra"]
    if len(extras) >= 2:
        issues.append({"kind": "extra_notes", "t_audio": extras[0]["t_audio"],
                       "items": extras})
    return issues


def describe(issue):
    items = issue["items"]
    first = items[0]
    where = ""
    if first.get("measure") is not None:
        where = "第 %d 小节 · 第 %d 拍" % (int(first["measure"]) + 1,
                                          int(first.get("beat") or 0) + 1)
    if issue["kind"] == "extra_notes":
        return "%s 多弹了 %d 个音（%s）" % (where or "录音里", len(items),
                                        "、".join(str(x.get("got")) for x in items[:5]))
    if len(items) == 1:
        it = items[0]
        if it["kind"] == "missing":
            return "%s 漏了 %s" % (where, it["want"])
        return "%s 要 %s，弹成了 %s" % (where, it["want"], it["got"])
    parts = []
    for it in items:
        parts.append("%s%s" % (it["want"], "（漏）" if it["kind"] == "missing"
                               else "→" + str(it["got"])))
    return "%s 连着 %d 个音没对上：%s" % (where, len(items), "、".join(parts))


def main(argv=None):
    ap = argparse.ArgumentParser(description="逐音比对（第一版）")
    ap.add_argument("--score", default=r"E:\GuitarFollowLab\frontend\data\hey_jude.json")
    ap.add_argument("--events", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--score-window", default="",
                    help="把谱面裁到这次作业那一段，写法 FROM:TO（秒），如 0:27")
    ap.add_argument("--list", type=int, default=0)
    args = ap.parse_args(argv)

    _, score = load_score(args.score)
    if args.score_window:
        lo, _, hi = args.score_window.partition(":")
        score = filter_score(score, float(lo) if lo.strip() else None,
                             float(hi) if hi.strip() else None)
    path = args.events or args.labels
    if not path:
        sys.exit("至少给一个 --events 或 --labels")
    events = load_events(path)

    r = align(score, events)
    rows = compare(score, events, r)
    c = counts(rows)
    issues = aggregate(rows)

    print("=" * 74)
    print("逐音比对：%s × %s"
          % (os.path.basename(args.score), os.path.basename(path)))
    print("=" * 74)
    print(r.summary())
    if r.low_confidence:
        print("  ⚠ 对齐置信度不够 → 逐音结论仅供参考，不许当报告出。")
    print("")
    print("谱面音 %d 个：对 %d ｜ 错 %d ｜ 漏 %d ｜ 读数不可信 %d"
          % (c["total_score_notes"], c["ok"], c["wrong_note"],
             c["missing"], c["unjudged"]))
    print("多出来的事件 %d 个" % c["extra"])
    print("聚合后的问题 %d 条：" % len(issues))
    for it in issues:
        print("  · " + describe(it))

    if args.list:
        print("")
        print("逐音明细（前 %d 条）" % args.list)
        for row in rows[:args.list]:
            if row["score_idx"] is None:
                print("  （多弹）录音 %6.2fs  %s" % (row["t_audio"], row["got"]))
                continue
            tag = {"ok": "✓", "wrong_note": "✗", "missing": "—", "unjudged": "?"}[row["kind"]]
            tail = ""
            if row["kind"] == "wrong_note":
                tail = "  弹成 %s" % row["got"]
            elif row["kind"] == "missing":
                tail = "  漏"
            elif row["kind"] == "unjudged":
                tail = "  读数不可信（不判）"
            print("  %s #%-3d 谱面 %6.2fs %-4s%s"
                  % (tag, row["score_idx"] + 1, row["t_score"], row["want"], tail))


if __name__ == "__main__":
    main()
