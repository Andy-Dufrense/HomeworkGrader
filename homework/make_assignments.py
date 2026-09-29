# -*- coding: utf-8 -*-
"""作业登记：把一份谱子变成一次「作业」。

两种来源：

  ① 老师给的 .gp（就是 Q5 说的"后台上传"，这一版先用命令行）：
     E:\\Python\\python.exe -X utf8 homework\\make_assignments.py gp ^
        --gp E:\\HomeworkGrader\\data\\.gp\\queen-we_will_rock_you.gp4 ^
        --id we-will-rock-you-01 --title "We will rock you" --artist Queen

  ② 我们自己生成的练习谱（常见和弦走向 × 常见分解和弦指法）：
     E:\\Python\\python.exe -X utf8 homework\\make_assignments.py progressions

  看一眼现有的：   ... make_assignments.py list

产物
----
  data/assignments/<id>/assignment.json   作业档案（课程/作业名 + 标准说明）
  data/assignments/<id>/ref.json          从 .gp 生成的参考时间轴（跟弹链路读的那份）
  scores/practice/<id>.gp4                ② 生成的练习谱（真的 .gp，能用 Guitar Pro 打开）

铁律对上哪几条：Q5（课程/课时/作业三级归档，这里先按 <id> 目录归档）、
Q6（标准答案取吉他轨）、Q30（.gp → 时间轴 一律走跟弹的 gp_timeline.py）。
"""

import argparse
import datetime
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import reference                                    # noqa: E402

ASSIGNMENTS = os.path.join(ROOT, "data", "assignments")
PRACTICE_GP = os.path.join(ROOT, "scores", "practice")
GP_SOURCES = [os.path.join(ROOT, "data", ".gp"), os.path.join(ROOT, "scores"),
              r"E:\GuitarFollowLab\.gp"]
LIB = os.environ.get("GUITARFOLLOW_PYTHONPATH", r"E:\VirtuCoach-Lib")


# ── 常见和弦的标准按法（T3231323 里的 T = 低音弦，其余三下在 3/2/1 弦上）──
CHORDS = {
    "C":  {"bass": (5, 3), "3": (3, 0), "2": (2, 1), "1": (1, 0)},
    "Am": {"bass": (5, 0), "3": (3, 2), "2": (2, 1), "1": (1, 0)},
    "F":  {"bass": (6, 1), "3": (3, 2), "2": (2, 1), "1": (1, 0)},
    "G":  {"bass": (6, 3), "3": (3, 0), "2": (2, 0), "1": (1, 3)},
    "G7": {"bass": (6, 3), "3": (3, 0), "2": (2, 0), "1": (1, 1)},
    "Dm": {"bass": (4, 0), "3": (3, 2), "2": (2, 3), "1": (1, 1)},
    "Em": {"bass": (6, 0), "3": (3, 0), "2": (2, 0), "1": (1, 0)},
    "D":  {"bass": (4, 0), "3": (3, 2), "2": (2, 3), "1": (1, 2)},
}

# 常见分解和弦指法：T = 这个和弦的最低音（按和弦的标准按法），后面是 3/2/1 弦来回
PATTERNS = {
    "T3231323": ["T", "3", "2", "3", "1", "3", "2", "3"],   # 每拍 2 下，8 分音符
    # 双音（两根弦一起拨，每拍一下；仍是这些基础 C 调和弦的标准按法）
    "dyad-t3": [("T", "3")] * 4,        # 根音 + 3 弦那个音（多为五度／八度）
    "dyad-t2": [("T", "2")] * 4,        # 根音 + 2 弦那个音（多为三度／八度）
}
# 给报告/作业名用的中文说法（.gp 的标题必须是 ASCII，所以键用英文）
PATTERN_LABEL = {"T3231323": "分解和弦 T3231323",
                 "dyad-t3": "双音（根音＋三弦）",
                 "dyad-t2": "双音（根音＋二弦）"}

# 常见和弦走向（每个和弦一小节）
PROGRESSIONS = {
    "1645":     ["C", "Am", "F", "G"],
    "6415":     ["Am", "F", "C", "G"],
    "4536251":  ["F", "G", "Em", "Am", "Dm", "G", "C"],
    "15634145": ["C", "G", "Am", "Em", "F", "C", "F", "G"],   # 卡农进行
    "1625":     ["C", "Am", "Dm", "G"],
}


def slug(s):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(s or "")).strip("-")
    return s or "assignment"


def find_gp(name):
    """按文件名（可带相对路径）在几个谱面目录里找 .gp。"""
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for d in GP_SOURCES:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise SystemExit("找不到这份谱：%s\n找过的目录：%s" % (name, GP_SOURCES))


# ── 生成练习谱（真的 .gp4）──────────────────────────────────────────────

def build_practice_gp(path, title, chords, pattern_name, tempo=80):
    """把「和弦走向 + 分解指法」写成一份真的 .gp4。

    几个坑（都是实测撞出来的）：
      * Song() 自带 1 个 title/1 条轨，加小节要用 song.newMeasure()；
      * Note.type 默认是 rest，必须显式设成 normal，否则写出去一个音都没有；
      * GP3/4/5 的标题按 cp1252 写，中文会炸 —— 所以练习谱的标题用 ASCII。
    """
    sys.path.insert(0, LIB)
    import guitarpro as gp

    pattern = PATTERNS[pattern_name]
    song = gp.Song()
    song.title, song.artist = title, "HomeworkGrader"
    song.tempo = int(tempo)
    song.tracks[0].name = "Guitar"

    for _ in range(len(chords) - 1):
        song.newMeasure()

    for m_index, chord in enumerate(chords):
        shape = CHORDS[chord]
        measure = song.tracks[0].measures[m_index]
        voice = measure.voices[0]
        start = 0
        for step in pattern:
            beat = gp.Beat(voice)
            beat.duration = gp.Duration(value=8)
            beat.status = gp.BeatStatus.normal
            beat.start = start
            # 一步一个音；写成 ("T","3") 这种元组就是**双音**（同一拍里两根弦一起响）
            for part in (step if isinstance(step, (tuple, list)) else (step,)):
                note = gp.Note(beat)
                note.string, note.value = (shape["bass"] if part == "T" else shape[part])
                note.velocity = 95
                note.type = gp.NoteType.normal
                beat.notes.append(note)
            voice.beats.append(beat)
            start += gp.Duration(value=8).time

    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "wb") as f:
        gp.write(song, f, version=(4, 0, 0))
    return path


# ── 登记一次作业 ────────────────────────────────────────────────────────

def register(gp_path, aid, title=None, artist=None, course="一对一 · 课后作业",
             track=None, bars="", slice_="", note="", keep_gp=True,
             source_kind="老师上传的 .gp"):
    """从一份 .gp 生成参考时间轴并登记成作业；返回 assignment 字典。"""
    meta, notes, _log = reference.build_timeline(gp_path, track)
    tracks = meta.get("_tracks") or []
    used = meta.get("_track_index")
    if not notes:
        raise SystemExit("%s 这条轨上没有音" % gp_path)

    full_notes = len(notes)
    keep, desc = reference.crop_notes(notes, slice_, bars)
    bars_with_notes = [int(n["measure"]) + 1 for n in keep if n.get("measure") is not None]
    tr = meta.get("track") or {}

    adir = os.path.join(ASSIGNMENTS, aid)
    os.makedirs(adir, exist_ok=True)
    ref_path = os.path.join(adir, "ref.json")
    reference.write_ref(ref_path, meta, keep, desc)

    standard = {
        "title": meta.get("title") or title,
        "artist": meta.get("artist") or artist,
        "tempo": meta.get("tempo"),
        "measures": meta.get("measures"),
        "track_index": used,
        "track_name": tr.get("name"),
        "track_tuning": tr.get("tuning"),
        "track_confident": meta.get("_track_confident"),
        "track_why": meta.get("_track_why"),
        "notes": len(keep), "notes_all": full_notes, "crop": desc,
        "bar_from": min(bars_with_notes) if bars_with_notes else None,
        "bar_to": max(bars_with_notes) if bars_with_notes else None,
        "source": os.path.abspath(gp_path),
        "source_kind": source_kind,
    }
    a = {
        "id": aid,
        # 作业名：命令行给的优先（这是"这次作业"的名字），谱面自己的标题留在 standard 里
        "title": title or standard["title"], "artist": standard["artist"] or "—",
        "course": course, "lesson": title or standard["title"],
        "standard": standard,
        "gp": os.path.abspath(gp_path) if keep_gp else None,
        "ref": os.path.relpath(ref_path, ROOT).replace("\\", "/"),
        "note": note,
        "created": datetime.date.today().isoformat(),
    }
    with io.open(os.path.join(adir, "assignment.json"), "w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
    return a


def load_assignments():
    out = []
    if not os.path.isdir(ASSIGNMENTS):
        return out
    for name in sorted(os.listdir(ASSIGNMENTS)):
        p = os.path.join(ASSIGNMENTS, name, "assignment.json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def cmd_gp(args):
    gp_path = find_gp(args.gp)
    a = register(gp_path, args.id or slug(os.path.splitext(os.path.basename(gp_path))[0]),
                 title=args.title, artist=args.artist, course=args.course,
                 track=args.track, bars=args.bars, slice_=args.slice, note=args.note)
    report(a)
    return 0


def cmd_progressions(args):
    made = []
    combos = [(name, args.pattern) for name in PROGRESSIONS]
    # 双音：先用最常见的两个（1645 / 6415），还是这些基础 C 调和弦
    if not args.no_dyads:
        for name in ("1645", "6415"):
            for pat in ("dyad-t3", "dyad-t2"):
                combos.append((name, pat))
    for name, pat in combos:
        chords = PROGRESSIONS[name]
        aid = "%s-%s" % (name, slug(pat))
        gp_title = "%s %s / %s" % (name, "-".join(chords), pat)   # .gp 标题只能 ASCII
        gp_path = os.path.join(PRACTICE_GP, aid + ".gp4")
        build_practice_gp(gp_path, gp_title, chords, pat, tempo=args.tempo)
        a = register(gp_path, aid,
                     title="%s · %s（%s）" % (name, "–".join(chords),
                                             PATTERN_LABEL.get(pat, pat)),
                     artist="练习谱 · %s" % pat, course="练习 · 常见和弦走向",
                     source_kind="本机生成的练习谱",
                     note="常见和弦走向 %s，用%s弹（每和弦一小节，%d BPM）。"
                          % (name, PATTERN_LABEL.get(pat, pat), args.tempo))
        made.append(a)
        report(a)
    print("\n共生成 %d 份练习作业，谱面在 %s" % (len(made), PRACTICE_GP))
    return 0


def cmd_list(_args):
    rows = load_assignments()
    if not rows:
        print("还没有登记任何作业。")
        return 0
    print("data/assignments 下现在有 %d 份作业：" % len(rows))
    for a in rows:
        std = a.get("standard") or {}
        print("  %-22s %-28s %s | %s 个音 | 轨[%s] %s%s"
              % (a["id"], (a["title"] or "")[:28], a.get("course") or "",
                 std.get("notes"), std.get("track_index"), std.get("track_name") or "—",
                 (" | 取段 " + std["crop"]) if std.get("crop") else ""))
    return 0


def report(a):
    std = a["standard"]
    print("登记作业 %s" % a["id"])
    print("  作业     %s — %s（%s BPM，%s 小节）"
          % (a["title"], a["artist"], std.get("tempo"), std.get("measures")))
    print("  标准答案 %s" % std["source"])
    print("           轨 [%s] %s ｜ 本次要弹 %s 个音%s"
          % (std.get("track_index"), std.get("track_name") or "—", std.get("notes"),
             ("（取段 %s）" % std["crop"]) if std.get("crop") else ""))
    print("  参考     %s" % a["ref"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="把一份谱子登记成一次作业")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("gp", help="登记一份老师给的 .gp")
    g.add_argument("--gp", required=True, help=".gp 文件名或全路径")
    g.add_argument("--id", default="", help="作业 id（默认按文件名）")
    g.add_argument("--title", default=None)
    g.add_argument("--artist", default=None)
    g.add_argument("--course", default="一对一 · 课后作业")
    g.add_argument("--track", type=int, default=None, help="取第几轨（默认按 Q6 认吉他）")
    g.add_argument("--bars", default="", help="只取第 A~B 小节，如 1:8")
    g.add_argument("--slice", default="", help="只取第 A~B 个音")
    g.add_argument("--note", default="")
    g.set_defaults(func=cmd_gp)

    p = sub.add_parser("progressions", help="生成常见和弦走向的练习作业")
    p.add_argument("--pattern", default="T3231323", choices=sorted(PATTERNS))
    p.add_argument("--tempo", type=int, default=80)
    p.add_argument("--no-dyads", action="store_true", help="不生成双音那几条")
    p.set_defaults(func=cmd_progressions)

    l = sub.add_parser("list", help="列出已登记的作业")
    l.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
