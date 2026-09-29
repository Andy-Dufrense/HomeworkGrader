# -*- coding: utf-8 -*-
"""作业检查 · 最小可看 demo 的服务端（只用标准库，不装任何依赖）。

这一版**不跑真正的批改**，它做的是把「产品形态」摆出来：
    作业卡（Hey Jude）→ 上传音频/直链 → 异步批改（进度）→ 结果页
结果里的数字**不是编的**：来自 2026-09-24 那次真机录音的实测
（见 实测-对齐-2026-09-24.md、vc_gf/G-real-heyjude.txt：对 10 / 错 8）。

跑法：
    E:\\Python\\python.exe -X utf8 homework\\server.py
然后浏览器打开 http://localhost:1310
"""

import io
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")

PORT = int(os.environ.get("HOMEWORK_PORT", "1310"))

# 曲谱库：铁律 Q30 说「和 GuitarFollow 共用」，所以先按路径读它那份时间轴。
SCORE_TIMELINE = os.environ.get(
    "HOMEWORK_SCORE", r"E:\GuitarFollowLab\frontend\data\hey_jude.json")

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png"}

# ── 作业（第一版就一个，Q32：这节课作业是 Hey Jude）──────────────────────
ASSIGNMENT = {
    "id": "hey-jude-01",
    "course": "一对一 · 第 6 课",
    "title": "Hey Jude",
    "artist": "The Beatles",
    "bpm": 76,
    "measures": 24,
    "track": "Voice（旋律轨）",
    "source": "标准答案：老师上传的 Guitar Pro 谱面（.gp）",
    "pass_line": 80,
    "record_tips": [
        "戴耳机，别让伴奏被麦克风收进去",
        "环境安静一点，手机离琴半米左右",
        "弹错了也继续弹完，别停下来重来",
    ],
}

# ── 实测结果（G-real-heyjude.txt，2026-09-24 10:40）──────────────────────
# 谱面时间轴从 0 起算；这段录音整体晚 2.50s（实测），所以 音频时刻 = 谱面时刻 + 2.50
AUDIO_OFFSET = 2.50

# ── 真实批改结果（有的话优先用它）────────────────────────────────────────
# 链路：run_assignment.py --engine follow → data/jobs/<job>/page.json
# 给了就用真数字，没给就退回下面的 9-24 样例数字（页面会标明是 demo）。
# 默认给页面看的那次批改：Q32 说的 demo 就是「这节课作业是 Hey Jude」，
# 而且它走的是真产品那条路（老师上传的 .gp → 参考时间轴）。换别的就设 HOMEWORK_JOB。
JOB = os.environ.get("HOMEWORK_JOB", "hey-jude-01")
REAL_PAGE = os.path.join(ROOT, "data", "jobs", JOB, "page.json")
REAL_RESULT = os.path.join(ROOT, "data", "jobs", JOB, "result.json")

REAL_ASSIGNMENT = {
    "id": JOB,
    "course": "一对一 · 课后作业",
    "title": "Am–F–C–G（6415）· T3231323",
    "artist": "练习样例 · 真机录音",
    "bpm": 76,
    "measures": 12,
    "track": "吉他（单音分解和弦）",
    "source": "标准答案：老师上传的 Guitar Pro 谱面（.gp → 时间轴）",
    "pass_line": 80,
    "record_tips": [
        "戴耳机，别让伴奏被麦克风收进去",
        "环境安静一点，手机离琴半米左右",
        "弹错了也继续弹完，别停下来重来",
    ],
}


def assignment_from_standard(page):
    """作业卡用**这份参考谱面自己的信息**。

    用户口径（2026-09-29）：不管多少轨，目标就是吉他；只要弹得跟谱子上一样就行。
    所以卡片上要写清"标准答案是哪份谱、哪条轨、这次要弹多少个音"，
    而不是写死一个作业名。
    """
    std = page.get("standard") or {}
    a = dict(REAL_ASSIGNMENT)                       # 课程/课时这类后台才知道的先用默认
    if std.get("title"):
        a["title"] = std["title"]
    if std.get("artist"):
        a["artist"] = std["artist"]
    if std.get("tempo"):
        a["bpm"] = std["tempo"]
    a["measures"] = std.get("measures")
    if std.get("track_name"):
        a["track"] = "吉他轨 [%s] %s" % (std.get("track_index"), std["track_name"])
    elif std.get("track_index") is not None:
        a["track"] = "吉他轨 [%s]" % std["track_index"]
    else:
        a["track"] = "吉他（老师上传的谱面）"
    bits = ["标准答案：老师上传的 Guitar Pro 谱面（.gp → 时间轴）"]
    if std.get("notes"):
        bits.append("这次要弹 %d 个音" % std["notes"])
    if std.get("bar_from") and std.get("bar_to"):
        bits.append("有音的小节 %d~%d" % (std["bar_from"], std["bar_to"]))
    if std.get("crop"):
        bits.append("取段 %s" % std["crop"])
    if std.get("track_confident") is False:
        bits.append("⚠ 这条轨是不是吉他没把握，请跟老师核一下")
    a["source"] = " · ".join(bits)
    return a


def load_real():
    """读真实批改结果（run_assignment.py 产出的 page.json）。"""
    if not os.path.exists(REAL_PAGE):
        return None
    with io.open(REAL_PAGE, encoding="utf-8") as f:
        page = json.load(f)
    page["assignment"] = assignment_from_standard(page)
    page["real"] = True
    if os.path.exists(REAL_RESULT):
        with io.open(REAL_RESULT, encoding="utf-8") as f:
            rich = json.load(f)
        page["align"] = rich.get("align")
        page["engine"] = rich.get("engine")
        if rich.get("align") and rich["align"].get("offset") is not None:
            page["offset"] = float(rich["align"]["offset"])
    return page

RUN = {"judged": 18, "right": 10, "wrong": 8, "missing": 0,
       "expected_in_excerpt": 24}

# 8 个错音（小节、谱面要的音、学员弹成什么）—— 按那次导出的错音清单顺序
RAW_ERRORS = [
    (1, "C4", "A#3"), (2, "A3", "D4"), (2, "A3", "A#3"), (2, "A3", "E3"),
    (3, "G3", "D3"), (3, "A3", "E3"), (4, "A#3", "D#4"), (4, "F4", "E4"),
]

FIX = {
    1: "第一个音别急着按，先在心里数「一」再下去；C4 用无名指提前摆好，落弦就是它。",
    2: "这一小节连着三个 A3，问题都是手上没提前到位。把这三个音单独拎出来，慢到一半速度，每个音都按实了再往下。",
    3: "G3 到 A3 这一下是换音，手指别一根一根挪，整只手一起过去。",
    4: "A#3 和 F4 之间是换弦，右手注意别碰到中间那根弦。",
}

NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nm(midi):
    midi = int(round(midi))
    return "%s%d" % (NOTE[midi % 12], midi // 12 - 1)


def load_score():
    with io.open(SCORE_TIMELINE, encoding="utf-8") as f:
        d = json.load(f)
    notes = sorted(d["notes"], key=lambda n: float(n["t"]))
    return d.get("meta", {}), notes


def build_result():
    """把实测数字拼成结果页要的东西（含每条错的定位与改法）。"""
    real = load_real()
    if real is not None:
        return real
    meta, notes = load_score()
    by_measure = {}
    for n in notes:
        by_measure.setdefault(int(n.get("measure", 0)), []).append(n)

    errors, used = [], {}
    for measure, want, got in RAW_ERRORS:
        cands = [n for n in by_measure.get(measure - 1, []) if nm(n["midi"]) == want]
        idx = used.get(measure, 0)
        note = cands[idx] if idx < len(cands) else (cands[0] if cands else None)
        used[measure] = idx + 1
        if not note:
            continue
        errors.append({
            "measure": measure,
            "beat": int(note.get("beat", 0)) + 1,
            "t_score": round(float(note["t"]), 2),
            "t_audio": round(float(note["t"]) + AUDIO_OFFSET, 2),
            "string": note.get("string"), "fret": note.get("fret"),
            "want": want, "got": got,
        })

    # 聚合成「问题」：同一小节相邻的错合成一条（沿用 VirtuCoach 现在的合并思路）
    issues = []
    for e in errors:
        if issues and issues[-1]["measure"] == e["measure"]:
            issues[-1]["items"].append(e)
        else:
            issues.append({"measure": e["measure"], "items": [e]})
    for it in issues:
        first = it["items"][0]
        it["t_audio"] = first["t_audio"]
        it["beat"] = first["beat"]
        it["title"] = "第 %d 小节 · 第 %d 拍" % (it["measure"], first["beat"])
        it["kind"] = "wrong_note"
        if len(it["items"]) == 1:
            it["detail"] = "这一小节要 %s，听着弹成了 %s" % (first["want"], first["got"])
        else:
            pos = "、".join("第%d拍%s" % (x["beat"], x["want"]) for x in it["items"])
            it["detail"] = "这一小节连着 %d 个音没对上：%s" % (len(it["items"]), pos)
        it["fix"] = FIX.get(it["measure"], "先用一半速度把这一小节单独过三遍，每个音都按实了再连起来。")

    # 分数：按 scoring.py 的口径（干净 96，第一处全额、其余 60%，同类 ≥3 再扣 2，下限 60）
    deducts = [8.5] + [8.5 * 0.6] * (len(issues) - 1)
    score = 96.0 - sum(deducts)
    if len(issues) >= 3:
        score -= 2
    score = max(60, int(round(score)))

    return {
        "assignment": ASSIGNMENT,
        "score": score,
        "pass_line": ASSIGNMENT["pass_line"],
        "passed": score >= ASSIGNMENT["pass_line"],
        "coverage": round(100.0 * RUN["judged"] / max(1, RUN["expected_in_excerpt"])),
        "accuracy": round(100.0 * RUN["right"] / max(1, RUN["judged"])),
        "counts": RUN,
        "summary": "整段节拍是稳的，问题都集中在每句开头那一下——左手还没到位右手就拨了。",
        "issues": issues,
        "score_notes": [{"t": round(float(n["t"]), 2), "string": n.get("string"),
                         "midi": int(n["midi"])}
                        for n in notes if float(n["t"]) <= 27.0],
        "error_marks": [{"t": e["t_score"]} for e in errors],
        "note": ("本页是 demo：数字来自 2026-09-24 那次真机录音（对 10 / 错 8），"
                 "批改引擎还没接上；秒数 = 谱面位置 + 实测整体偏移 2.50s。"),
    }


TASKS = {}
# 阶段名照着真实链路写（思路 §3）：判断要不要分离 → 找起音 → 对齐 → 逐音判定 → 报告
STAGES = [(0.8, "正在听：只有吉他，还是还有别的（决定要不要分离音轨）…"),
          (1.6, "正在找每一次拨弦（跟弹引擎）…"),
          (1.0, "正在把录音和谱面对齐…"),
          (1.4, "正在逐个音判定（跟弹引擎）…"),
          (0.6, "正在整理报告…")]


def run_task(task_id):
    total = sum(s[0] for s in STAGES)
    waited = 0.0
    try:
        for dur, text in STAGES:
            time.sleep(dur)
            waited += dur
            TASKS[task_id].update({"stage": text, "progress": int(waited / total * 100)})
        TASKS[task_id].update({"status": "completed", "progress": 100,
                               "stage": "批改完成", "result": build_result()})
    except Exception as e:                                   # 别把线程搞死
        TASKS[task_id].update({"status": "failed", "stage": "批改失败：%s" % e})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  [http] " + fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/assignment":
            real = load_real()
            if real is not None:
                return self._send(200, {"assignment": real["assignment"],
                                        "demo": False, "real": True})
            return self._send(200, {"assignment": ASSIGNMENT, "demo": True, "real": False})
        if path.startswith("/api/task/"):
            tid = path.rsplit("/", 1)[-1]
            t = TASKS.get(tid)
            if not t:
                return self._send(404, {"error": "没有这个任务"})
            return self._send(200, t)
        if path in ("/", "/index.html"):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not fp.startswith(os.path.normpath(WEB)) or not os.path.isfile(fp):
            return self._send(404, "404", "text/plain; charset=utf-8")
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/submit":
            return self._send(404, {"error": "404"})
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        # demo：不存文件，只记下「收到多大一坨」
        ctype = self.headers.get("Content-Type") or ""
        info = {"bytes": len(raw), "kind": "link" if "json" in ctype else "file"}
        tid = uuid.uuid4().hex[:12]
        TASKS[tid] = {"status": "running", "progress": 0, "stage": "已收到，排队中…",
                      "submitted": info}
        import threading
        threading.Thread(target=run_task, args=(tid,), daemon=True).start()
        return self._send(200, {"task_id": tid, "received": info})


def main():
    meta, notes = load_score()
    print("=" * 66)
    print("  HomeworkGrader · 作业检查 demo")
    print("=" * 66)
    print("  作业     %s — %s（%g BPM，%d 小节）"
          % (ASSIGNMENT["title"], ASSIGNMENT["artist"],
             ASSIGNMENT["bpm"], ASSIGNMENT["measures"]))
    print("  标准答案 %s" % SCORE_TIMELINE)
    print("           轨 %s，%d 个音，%.2f~%.2f s"
          % ((meta.get("track") or {}).get("name", "?"), len(notes),
             notes[0]["t"], notes[-1]["t"]))
    print("  打开     http://localhost:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
