# -*- coding: utf-8 -*-
"""曲谱练习：生成三份真的 .gp4 并登记成作业。

  ① 小星星 · 高音版 —— 1 把位，主旋律落在 1/2 弦（C4~A4）
  ② 小星星 · 低音版 —— 低一个八度，落在 3/4/5 弦（C3~A3）
  ③ 爬格子 1234   —— 6 弦→1 弦每根弦 1-2-3-4 品，再 1 弦→6 弦 4-3-2-1 品

用法：
  E:\\Python\\python.exe -X utf8 homework\\make_songs.py                    :: 三份都生成
  E:\\Python\\python.exe -X utf8 homework\\make_songs.py --tempo 70
  E:\\Python\\python.exe -X utf8 homework\\make_songs.py --only twinkle-low

产物（和 make_assignments.py progressions 同一套）：
  scores/practice/<id>.gp4           —— 能用 Guitar Pro 打开
  data/assignments/<id>/             —— 作业档案 + 参考时间轴（页面的作业选择器里会出现）

几个坑（照 make_assignments.build_practice_gp 抄的，别改）：
  * Song() 自带 1 个 title / 1 条轨，加小节要用 song.newMeasure()；
  * Note.type 默认是 rest，必须显式设成 normal，否则写出去一个音都没有；
  * GP3/4/5 的标题按 cp1252 写，中文会炸 —— 所以 .gp 里的标题一律 ASCII，
    中文名只放在作业档案（assignment.json）里。
  * 一小节的容量是 3840 tick（4/4）；Duration(value=v).time = 3840 // v，
    所以 4 分音符 = 960、8 分音符 = 480、2 分音符（半音符）= 1920。
"""

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import make_assignments as MA                              # noqa: E402

sys.path.insert(0, MA.LIB)
import guitarpro as gp                                     # noqa: E402

MEASURE_TICKS = 3840          # 4/4


# ── ① 小星星 ────────────────────────────────────────────────────────────
# 旋律：(音名, 几拍)。1 = 4 分音符，2 = 半音符。
TWINKLE = [
    ("C", 1), ("C", 1), ("G", 1), ("G", 1),
    ("A", 1), ("A", 1), ("G", 2),
    ("F", 1), ("F", 1), ("E", 1), ("E", 1),
    ("D", 1), ("D", 1), ("C", 2),
    ("G", 1), ("G", 1), ("F", 1), ("F", 1),
    ("E", 1), ("E", 1), ("D", 2),
    ("G", 1), ("G", 1), ("F", 1), ("F", 1),
    ("E", 1), ("E", 1), ("D", 2),
    ("C", 1), ("C", 1), ("G", 1), ("G", 1),
    ("A", 1), ("A", 1), ("G", 2),
    ("F", 1), ("F", 1), ("E", 1), ("E", 1),
    ("D", 1), ("D", 1), ("C", 2),
]

# 两套把位（弦, 品）。高音版在 1 把位，低音版整段低一个八度、用 3/4/5 弦
FINGER_HIGH = {"C": (2, 1), "D": (2, 3), "E": (1, 0), "F": (1, 1), "G": (1, 3), "A": (1, 5)}
FINGER_LOW = {"C": (5, 3), "D": (4, 0), "E": (4, 2), "F": (4, 3), "G": (3, 0), "A": (3, 2)}


def twinkle_notes(finger):
    """小星星 → [(弦, 品, Duration.value), ...]（4 分音符 = 4，半音符 = 2）"""
    out = []
    for name, beats in TWINKLE:
        string, fret = finger[name]
        out.append((string, fret, 4 if beats == 1 else 2))
    return out


# ── ② C 大调音阶（两个八度，上下行）────────────────────────────────────
# 第一把位为主，1 弦上走到 8 品（B4=1弦7品、C5=1弦8品）。
SCALE_FINGER = [(5, 3), (4, 0), (4, 2), (4, 3), (3, 0), (3, 2), (2, 0), (2, 1),
                (2, 3), (1, 0), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8)]


def c_major_notes():
    """C3→C5 上行、再回到 C3（最高那个 C5 不重复弹）。

    ⚠ 时值必须凑满整小节（2026-10-08 踩过）：一开始把首音/最高音/末音都写成二分音符，
    结果末尾那个二分音符塞不进当前小节 → 谱面**多出一拍空拍、变成 9 小节**。
    现在：前面 28 个音都是四分音符，最后一个低音 C3 用**全音符**停住 →
    28 + 4 = 32 拍 = 8 小节，末音正好占满最后一小节，一拍不剩。
    """
    seq = SCALE_FINGER + list(reversed(SCALE_FINGER[:-1]))
    last = len(seq) - 1
    return [(string, fret, 1 if i == last else 4)
            for i, (string, fret) in enumerate(seq)]


# ── ②b C 大调音阶 · 前三品（E2 → G4）────────────────────────────────────
# 全程 0~3 品（第一把位），从 6 弦空弦 E2 一路到 1 弦 3 品 G4 —— 新手最常用的那条。
#   E2=6弦空弦 F2=6弦1品 G2=6弦3品 | A2=5弦空弦 B2=5弦2品 C3=5弦3品 |
#   D3=4弦空弦 E3=4弦2品 F3=4弦3品 | G3=3弦空弦 A3=3弦2品 |
#   B3=2弦空弦 C4=2弦1品 D4=2弦3品 | E4=1弦空弦 F4=1弦1品 G4=1弦3品
SCALE_1ST_FINGER = [(6, 0), (6, 1), (6, 3), (5, 0), (5, 2), (5, 3), (4, 0), (4, 2), (4, 3),
                    (3, 0), (3, 2), (2, 0), (2, 1), (2, 3), (1, 0), (1, 1), (1, 3)]


def c_major_1st_notes():
    """E2→G4 上行、再回到 E2（最高那个 G4 不重复弹）。

    17 + 16 = 33 个音，都是四分音符；最后一个低音 E2 用**全音符**停住 →
    32 + 4 = 36 拍 = 9 小节，正好占满（和两个八度那条同一个道理：
    末音时值必须凑满小节，不然谱面会多出一拍空拍）。
    """
    seq = SCALE_1ST_FINGER + list(reversed(SCALE_1ST_FINGER[:-1]))
    last = len(seq) - 1
    return [(string, fret, 1 if i == last else 4)
            for i, (string, fret) in enumerate(seq)]


# ── ③ 爬格子 1234 ───────────────────────────────────────────────────────

def chromatic_notes():
    """6 弦→1 弦，每根弦 1-2-3-4 品（上行）；再 1 弦→6 弦，每根弦 4-3-2-1 品（下行）。"""
    out = []
    for string in (6, 5, 4, 3, 2, 1):
        for fret in (1, 2, 3, 4):
            out.append((string, fret, 8))
    for string in (1, 2, 3, 4, 5, 6):
        for fret in (4, 3, 2, 1):
            out.append((string, fret, 8))
    return out


# ── 写 .gp4（和 build_practice_gp 同一套写法）───────────────────────────

def build_gp(path, title, notes, tempo=80):
    """把 [(弦, 品, Duration.value), ...] 顺次铺成 4/4 小节，写成真的 .gp4。"""
    # 先按小节切好（一行音符装不下 4 拍就换下一小节）
    measures, cur, used = [], [], 0
    for string, fret, value in notes:
        t = gp.Duration(value=value).time
        if used + t > MEASURE_TICKS:
            measures.append(cur)
            cur, used = [], 0
        cur.append((string, fret, value, used))
        used += t
    if cur:
        measures.append(cur)

    song = gp.Song()
    song.title, song.artist = title, "HomeworkGrader"
    song.tempo = int(tempo)
    song.tracks[0].name = "Guitar"
    for _ in range(len(measures) - 1):
        song.newMeasure()

    for i, beats in enumerate(measures):
        voice = song.tracks[0].measures[i].voices[0]
        for string, fret, value, start in beats:
            beat = gp.Beat(voice)
            beat.duration = gp.Duration(value=value)
            beat.status = gp.BeatStatus.normal
            beat.start = start
            note = gp.Note(beat)
            note.string, note.value = string, fret
            note.velocity = 95
            note.type = gp.NoteType.normal
            beat.notes.append(note)
            voice.beats.append(beat)

    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "wb") as f:
        gp.write(song, f, version=(4, 0, 0))
    return path


# ── 三份谱子的定义 ──────────────────────────────────────────────────────

SONGS = {
    "twinkle-high": {
        "gp_title": "Twinkle Twinkle Little Star (high)",
        "title": "小星星 · 高音版",
        "artist": "练习谱 · 儿歌",
        "course": "练习 · 曲目",
        "notes": lambda: twinkle_notes(FINGER_HIGH),
        "note": "小星星高音版：1 把位，主旋律在 1/2 弦（C4~A4）。"
                "C=2弦1品 D=2弦3品 E=1弦空弦 F=1弦1品 G=1弦3品 A=1弦5品。",
    },
    "twinkle-low": {
        "gp_title": "Twinkle Twinkle Little Star (low)",
        "title": "小星星 · 低音版",
        "artist": "练习谱 · 儿歌",
        "course": "练习 · 曲目",
        "notes": lambda: twinkle_notes(FINGER_LOW),
        "note": "小星星低音版：整段低一个八度，用 3/4/5 弦（C3~A3）。"
                "C=5弦3品 D=4弦空弦 E=4弦2品 F=4弦3品 G=3弦空弦 A=3弦2品。",
    },
    "chromatic-1234": {
        "gp_title": "Chromatic 1234",
        "title": "爬格子 · 1234",
        "artist": "练习谱 · 手指练习",
        "course": "练习 · 基本功",
        "notes": chromatic_notes,
        "note": "爬格子：6 弦到 1 弦，每根弦按 1-2-3-4 品上行；再 1 弦到 6 弦，"
                "每根弦 4-3-2-1 品下行。全程 8 分音符，右手交替拨弦。",
    },
    "c-major-scale": {
        "gp_title": "C Major Scale (2 octaves)",
        "title": "C 大调音阶 · 两个八度",
        "artist": "练习谱 · 基本功",
        "course": "练习 · 基本功",
        "notes": c_major_notes,
        "note": "C 大调音阶两个八度上下行（C3~C5）。指法："
                "C=5弦3品 D=4弦空弦 E=4弦2品 F=4弦3品 G=3弦空弦 A=3弦2品 B=2弦空弦 "
                "C=2弦1品 D=2弦3品 E=1弦空弦 F=1弦1品 G=1弦3品 A=1弦5品 B=1弦7品 C=1弦8品。"
                "首音、最高音、末音各停一拍再走。",
    },
    "c-major-scale-1st": {
        "gp_title": "C Major Scale (open position, E2-G4)",
        "title": "C 大调音阶 · 前三品（E2→G4）",
        "artist": "练习谱 · 基本功",
        "course": "练习 · 基本功",
        "notes": c_major_1st_notes,
        "note": "C 大调音阶第一把位上下行，全程 0~3 品，从 6 弦空弦 E2 到 1 弦 3 品 G4。"
                "指法：E2=6弦空弦 F2=6弦1品 G2=6弦3品 A2=5弦空弦 B2=5弦2品 C3=5弦3品 "
                "D3=4弦空弦 E3=4弦2品 F3=4弦3品 G3=3弦空弦 A3=3弦2品 B3=2弦空弦 "
                "C4=2弦1品 D4=2弦3品 E4=1弦空弦 F4=1弦1品 G4=1弦3品。末音停住再松手。",
    },
}


def make_song(aid, spec, tempo):
    gp_path = os.path.join(MA.PRACTICE_GP, aid + ".gp4")
    build_gp(gp_path, spec["gp_title"], spec["notes"](), tempo=tempo)
    a = MA.register(gp_path, aid, title=spec["title"], artist=spec["artist"],
                    course=spec["course"], source_kind="本机生成的练习谱",
                    note=spec["note"] + "（%d BPM）" % tempo)
    return a


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成曲谱练习并登记成作业")
    ap.add_argument("--tempo", type=int, default=80)
    ap.add_argument("--only", default="", help="只生成某一份，如 twinkle-low")
    args = ap.parse_args(argv)

    ids = [args.only] if args.only else list(SONGS)
    for aid in ids:
        if aid not in SONGS:
            raise SystemExit("没有这份谱：%s\n可选：%s" % (aid, " / ".join(SONGS)))
        MA.report(make_song(aid, SONGS[aid], args.tempo))

    print("\n谱面在 %s" % MA.PRACTICE_GP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
