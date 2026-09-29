# -*- coding: utf-8 -*-
"""作业检查 · 参考谱面：.gp → **这次作业那一段**的时间轴。

一条命令：

    E:\\Python\\python.exe -X utf8 homework\\reference.py ^
        --gp E:\\GuitarFollowLab\\.gp\\the-beatles-hey_jude.gp3 --track 0 --bars 1:8 ^
        --out scores\\hey-jude\\lesson06\\assignment.json

对得上哪几条铁律
----------------
* Q5  .gp 由后台上传，按 课程/课时/作业 三级归档 —— 这里只负责「一份 .gp → 一份时间轴
  （可以只取其中几小节）」，归档（放哪个目录）交给后台；--out 就是这个交接点。
* Q6  以吉他为准 —— 默认取第一条非打击轨，--track 可以显式指定；轨道清单会打出来。
* Q7  反复记号按实际弹奏顺序 —— gp_timeline.py 还没展开反复，这里把 meta.repeats
  原样带出来并打印提醒，不假装已经处理。
* Q8  按实际音高判 —— gp_timeline.py 的 note.realValue 已经折算过变调夹，
  调弦也来自谱面本身（meta.track.tuning）。
* Q30 曲谱库和 GuitarFollow 共用 —— 所以解析调用跟弹的
  backend/tools/gp_timeline.py，不另写一份解析器（那边是「唯一的生产者」）。

这个文件只做两件事：解析（转手给跟弹）和裁段（这次作业是哪几小节 / 哪几个音）。
判定、打分、报告都不在这里。
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile

FOLLOW_REPO = os.environ.get("GUITARFOLLOW_REPO", r"E:\GuitarFollowLab")
# gp_timeline.py 要 PyGuitarPro，装在跟 VirtuCoach 共用的那个运行库目录里
FOLLOW_LIB = os.environ.get("GUITARFOLLOW_PYTHONPATH", r"E:\VirtuCoach-Lib")

# Q6「以吉他为准」：轨名里带这些词的就当吉他
GUITAR_HINTS = ("guitar", "gtr", "吉他", "吉它", "acoustic", "electric")

# gp_timeline.py 打的轨道行：  [2] Guitar                 6 弦  调弦 E4 B3 G3 D3 A2 E2          音符  285
TRACK_RE = re.compile(r"^\s*\[(\d+)\]\s+(.*?)\s+(\d+)\s*弦\s+调弦\s+(.*?)\s+音符\s+(\d+)(.*)$")


def list_tracks(log):
    """从 gp_timeline.py 的输出里把轨道清单读出来（它就打这一行一行，不用另写解析器）。"""
    out = []
    for line in (log or "").splitlines():
        m = TRACK_RE.match(line)
        if not m:
            continue
        name = m.group(2).strip()
        out.append({
            "index": int(m.group(1)),
            "name": name,
            "strings": int(m.group(3)),
            "tuning": m.group(4).split(),
            "notes": int(m.group(5)),
            "percussion": "打击轨" in (m.group(6) or ""),
        })
    return out


def pick_track(tracks):
    """Q6「以吉他为准」——返回 (选中的轨道, 为什么选它, 有没有把握)。

    先按轨名认吉他；认不出来就退回第 0 条非打击轨（跟弹那边 gp_timeline.py 的默认），
    并且**把理由打出来**，让人一眼能看见"标准答案取的是哪条线"。

    为什么不用"音最多的那条"当兜底：Hey Jude 那份 .gp3 里 0 轨叫 Voice（就是学员要弹的
    旋律，118 个音）、1 轨叫 Piano（伴奏，622 个音）——按"音最多"会挑到钢琴轨，直接错。
    """
    named = [t for t in tracks
             if not t["percussion"]
             and any(h in t["name"].lower() for h in GUITAR_HINTS)]
    if len(named) == 1:
        return named[0], "轨名里认出来是吉他", True
    if len(named) > 1:
        best = max(named, key=lambda t: t["notes"])
        return best, ("有 %d 条轨的名字像吉他，取音最多的那条（不对就 --track N）" % len(named)), False
    rest = [t for t in tracks if not t["percussion"]]
    if rest:
        return rest[0], "轨名里没有吉他，退回第 0 条非打击轨（不是这条就 --track N）", False
    return None, "没有非打击轨", False


def _run_timeline(gp_path, track):
    """跑一次 gp_timeline.py，返回 (meta, notes, 它的原话)。"""
    script = os.path.join(FOLLOW_REPO, "backend", "tools", "gp_timeline.py")
    if not os.path.exists(script):
        raise SystemExit("找不到跟弹的时间轴脚本：%s\n（GUITARFOLLOW_REPO 指错了？）" % script)
    tmpdir = tempfile.mkdtemp(prefix="hg_ref_")
    out = os.path.join(tmpdir, "timeline.json")
    env = dict(os.environ)
    env["PYTHONPATH"] = FOLLOW_LIB + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-X", "utf8", script, gp_path, "--json", out, "--notes", "0"]
    if track is not None:
        cmd += ["--track", str(track)]
    p = subprocess.run(cmd, cwd=FOLLOW_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        raise SystemExit("gp_timeline.py 跑失败：\n%s\n%s" % (p.stdout[-2000:], p.stderr[-2000:]))
    with io.open(out, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("meta", {}), d.get("notes", []), p.stdout


def build_timeline(gp_path, track=None):
    """跑跟弹的 gp_timeline.py，拿回整首时间轴。返回 (meta, notes, 它的原话)。

    为什么必须借它的：.gp → 时间轴 只允许有一个生产者（三个项目的关系 §2/§4）。
    作业检查自己再写一份解析器，两边迟早会不一样，判定口径就分叉了。

    `--track` 不给的时候按 Q6 选吉他轨（见 pick_track），并把"选了哪条、为什么"写进
    meta（`_track_why` / `_tracks`），报告和参考 json 里都能查到。
    """
    meta, notes, log = _run_timeline(gp_path, track)      # 先跑一次，既拿清单也拿默认那轨
    tracks = list_tracks(log)
    used = (meta.get("track") or {}).get("index")
    why = ""
    confident = False
    if track is None:
        want, why, confident = pick_track(tracks)
        if want is not None and want["index"] != used:
            meta, notes, log2 = _run_timeline(gp_path, want["index"])
            log = log + "\n" + log2
            used = want["index"]
    else:
        why = "命令行指定 --track %d" % track
        confident = True
    meta["_track_why"] = why
    meta["_track_confident"] = confident
    meta["_tracks"] = tracks
    meta["_track_index"] = used
    return meta, notes, log


def crop_notes(notes, spec_slice="", spec_bars=""):
    """把参考裁到这次作业那一段，返回 (裁剪后的音表, 说明文字)。

    两种写法，够用第一版：

    * --slice A:B  第几个音（1 起、含两端），借来的练习时间轴没有小节号时用它；
    * --bars  A:B  第几小节（1 起、含两端），.gp 生成的时间轴才有 measure 字段。

    why：借来的时间轴常常是整首 / 整段练习（tl-6415.json 是同一段 ×3 遍、96 个音），
    而这次作业只要求弹一遍。不裁的话多出来的音会被算成「漏弹」，完成度也被拉低
    （6415 那次是 33/96 = 34%）。真做起来这里是 --bars —— 后台存的作业本来就带小节范围。
    """
    if spec_slice.strip():
        a, _, b = spec_slice.partition(":")
        i = int(a) - 1 if a.strip() else 0
        j = int(b) if b.strip() else len(notes)
        i = max(0, min(i, len(notes)))
        j = max(i, min(j, len(notes)))
        keep = notes[i:j]
        if not keep:
            raise SystemExit("--ref-slice %s 没裁出任何音（参考一共 %d 个）"
                             % (spec_slice, len(notes)))
        return keep, "第 %d~%d 个音" % (i + 1, j)
    if spec_bars.strip():
        a, _, b = spec_bars.partition(":")
        lo = int(a) if a.strip() else None
        hi = int(b) if b.strip() else None
        keep = [n for n in notes if n.get("measure") is not None
                and (lo is None or int(n["measure"]) + 1 >= lo)
                and (hi is None or int(n["measure"]) + 1 <= hi)]
        if not keep:
            raise SystemExit("--ref-bars %s 没裁出任何音 —— 这份时间轴没有 measure 字段？"
                             % spec_bars)
        return keep, "第 %s~%s 小节" % (lo if lo else "首", hi if hi else "末")
    return list(notes), ""


def write_ref(path, meta, notes, crop_desc=""):
    """把这次作业要用的参考写成一份时间轴 JSON（跟弹链路读的就是这个格式）。"""
    out = {"meta": dict(meta or {}), "notes": [
        {k: n[k] for k in ("t", "midi", "string", "fret", "measure", "beat", "dur")
         if n.get(k) is not None}
        for n in notes]}
    if crop_desc:
        out["meta"]["crop"] = crop_desc
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=".gp → 这次作业那一段的时间轴")
    ap.add_argument("--gp", required=True, help="老师上传的 .gp（gp3/gp4/gp5）")
    ap.add_argument("--track", type=int, default=None,
                    help="取第几轨（默认第一条非打击轨）——Q6 以吉他为准")
    ap.add_argument("--bars", default="", help="只取第 A~B 小节（1 起、含两端），如 1:8")
    ap.add_argument("--slice", default="", help="只取第 A~B 个音（1 起、含两端），如 1:32")
    ap.add_argument("--out", default="", help="写到哪个 json；不给就只打屏幕")
    args = ap.parse_args(argv)

    meta, notes, log = build_timeline(args.gp, args.track)
    tracks = meta.get("_tracks") or []
    used = meta.get("_track_index")
    seen_head = set()
    for line in log.splitlines():
        if "拍号" in line or "变速" in line:
            if line not in seen_head:      # 选轨时跑了两次，表头去重
                seen_head.add(line)
                print(line)
    if not notes:
        raise SystemExit("这条轨上没解析出音")

    print("--- 轨道（Q6：以吉他为准）---")
    for t in tracks:
        print("  [%d] %-22s %s 弦  调弦 %-26s 音符 %4d%s%s"
              % (t["index"], t["name"], t["strings"], " ".join(t["tuning"]), t["notes"],
                 "（打击轨）" if t["percussion"] else "",
                 "  ← 用这条当标准答案" if t["index"] == used else ""))
    if meta.get("_track_why"):
        print("  选轨理由：%s" % meta["_track_why"])
    used_name = next((t["name"] for t in tracks if t["index"] == used), "")
    if not meta.get("_track_confident"):
        print("  ⚠ 这条轨是不是吉他**没把握**（名字叫「%s」）—— 用 --track N 换一条再跑一遍（Q6）"
              % used_name)

    keep, desc = crop_notes(notes, args.slice, args.bars)
    tr = (meta.get("track") or {})
    print("")
    print("参考谱面：%s" % meta.get("title"))
    print("  轨      [%s] %s（%s 弦，调弦 %s）"
          % (tr.get("index"), tr.get("name"), tr.get("strings"),
             " ".join(tr.get("tuning") or [])))
    print("  速度    %g BPM ｜ 全曲 %s 小节 ｜ 拍号 %s"
          % (meta.get("tempo") or 0, meta.get("measures"),
             ", ".join("%s(第%d小节起)" % (t["sig"], t["measure"])
                       for t in meta.get("timeSignatures") or [])))
    # 注意：PyGuitarPro 里"没有反复"时 repeatClose = -1，而 gp_timeline.py 的 repeats()
    # 把它当成"有反复"报了（-1 在 Python 里是真值）—— 所以这里自己再筛一遍。
    # （那是跟弹的文件，按边界规矩不在这里改；已经记进本项目文档，回头给他们。）
    real_repeats = [r for r in (meta.get("repeats") or [])
                    if r.get("open") or (r.get("close") or 0) > 0]
    if real_repeats:
        print("  ⚠ 有反复记号 %s —— gp_timeline.py 还没展开，实际弹奏顺序要人工确认（Q7）"
              % real_repeats)
    print("  取段    %s → %d 个音（全曲 %d 个）" % (desc or "整首", len(keep), len(notes)))
    print("  首个音  %.2fs，末个音 %.2fs" % (keep[0]["t"], keep[-1]["t"]))

    if args.out:
        path = write_ref(args.out, meta, keep, desc)
        print("  已写出  %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
