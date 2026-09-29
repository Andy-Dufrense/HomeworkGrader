# -*- coding: utf-8 -*-
"""作业检查 · 最小可看 demo 的服务端（只用标准库，不装任何依赖）。

这一版**不跑真正的批改**，它做的是把「产品形态」摆出来：
   作业卡（Hey Jude）→ 上传音频文件 → 异步批改（进度）→ 结果页
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
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")

PORT = int(os.environ.get("HOMEWORK_PORT", "1310"))

# 曲谱库：铁律 Q30 说「和 GuitarFollow 共用」，所以先按路径读它那份时间轴。
SCORE_TIMELINE = os.environ.get(
    "HOMEWORK_SCORE", r"E:\GuitarFollowLab\frontend\data\hey_jude.json")

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
        ".woff2": "font/woff2", ".otf": "font/otf", ".ttf": "font/ttf",
        ".gp": "application/octet-stream", ".gp3": "application/octet-stream",
        ".gp4": "application/octet-stream", ".gp5": "application/octet-stream",
        ".gp7": "application/octet-stream"}

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

# 作业库：每次作业一个目录（homework/make_assignments.py 生成）
ASSIGN_DIR = os.path.join(ROOT, "data", "assignments")

RECORD_TIPS = [
    "戴耳机，别让伴奏被麦克风收进去",
    "环境安静一点，手机离琴半米左右",
    "弹错了也继续弹完，别停下来重来",
]

# 及格线（用户 2026-09-29 定：90 分）
PASS_LINE = int(os.environ.get("HOMEWORK_PASS_LINE", "90"))

# "去跟练"的地址：本机用 http，手机要用 https（不然麦克风不给）——
# 和 VirtuCoach 的跟练入口同一条规矩（VIRTUCOACH_FOLLOW_*）。
FOLLOW_URL = os.environ.get("HOMEWORK_FOLLOW_URL", "")
FOLLOW_HTTP_PORT = os.environ.get("HOMEWORK_FOLLOW_HTTP_PORT", "1209")
FOLLOW_HTTPS_PORT = os.environ.get("HOMEWORK_FOLLOW_HTTPS_PORT", "1210")


def follow_url_for(host):
    """按访问本页用的主机名推跟练地址（localhost 走 http，其它走 https）。"""
    if FOLLOW_URL:
        return FOLLOW_URL
    host = (host or "").split(":")[0]
    if host in ("localhost", "127.0.0.1", ""):
        return "http://localhost:%s/" % FOLLOW_HTTP_PORT
    return "https://%s:%s/" % (host, FOLLOW_HTTPS_PORT)

REAL_ASSIGNMENT = {
    "id": JOB,
    "course": "一对一 · 课后作业",
    "title": "Am–F–C–G（6415）· T3231323",
    "artist": "练习样例 · 真机录音",
    "bpm": 76,
    "measures": 12,
    "track": "吉他（单音分解和弦）",
    "source": "标准答案：老师上传的 Guitar Pro 谱面（.gp → 时间轴）",
    "pass_line": PASS_LINE,
    "record_tips": RECORD_TIPS,
}


def assignment_from_standard(page, base=None):
    """作业卡用**这份参考谱面自己的信息**。

    用户口径（2026-09-29）：不管多少轨，目标就是吉他；只要弹得跟谱子上一样就行。
    所以卡片上要写清"标准答案是哪份谱、哪条轨、这次要弹多少个音"，
    而不是写死一个作业名。
    """
    std = page.get("standard") or {}
    a = dict(base or REAL_ASSIGNMENT)               # 课程/课时这类后台才知道的先用默认
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
    kind = std.get("source_kind") or ""
    if kind == "老师上传的 .gp":
        head = "标准答案：老师上传的 Guitar Pro 谱面（.gp → 时间轴）"
    elif kind == "本机生成的练习谱":
        head = "标准答案：本机生成的练习谱（.gp4 → 时间轴）"
    elif kind:
        head = "标准答案：%s（不是 .gp，只是随手借的练习素材）" % kind
    else:
        head = "标准答案：老师上传的 Guitar Pro 谱面（.gp → 时间轴）"
    bits = [head]
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


# ── 作业库（data/assignments/<id>，由 homework/make_assignments.py 生成）──────

def load_assignments():
    out = []
    if not os.path.isdir(ASSIGN_DIR):
        return out
    for name in sorted(os.listdir(ASSIGN_DIR)):
        p = os.path.join(ASSIGN_DIR, name, "assignment.json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def load_assignment(aid):
    for a in load_assignments():
        if a.get("id") == aid:
            return a
    return None


def card_for(aid):
    """作业卡：课程/作业名来自作业档案，谱面信息来自它的 standard。"""
    a = load_assignment(aid)
    if a is None:
        return None
    base = {
        "id": aid,
        "course": a.get("course") or "一对一 · 课后作业",
        "title": a.get("title"), "artist": a.get("artist") or "—",
        "bpm": None, "measures": None, "track": "吉他（老师上传的谱面）",
        "pass_line": PASS_LINE, "record_tips": RECORD_TIPS,
    }
    card = assignment_from_standard({"standard": a.get("standard") or {}}, base)
    # 作业名以作业档案为准（谱面自己的标题只作参考）
    card["title"] = a.get("title") or card["title"]
    card["artist"] = a.get("artist") or card["artist"]
    card["course"] = a.get("course") or card["course"]
    card["lesson"] = a.get("lesson") or ""
    card["note"] = a.get("note") or ""
    return card


def job_page(aid):
    """这一次批改的结果（run_assignment.py 写出来的 page.json）；没有就 None。"""
    path = os.path.join(ROOT, "data", "jobs", aid, "page.json")
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as f:
        page = json.load(f)
    card = card_for(aid)
    if card is not None:
        page["assignment"] = card
    a = load_assignment(aid)
    if a is not None:
        page["standard"] = a.get("standard") or page.get("standard")
    page["real"] = True
    rich_path = os.path.join(ROOT, "data", "jobs", aid, "result.json")
    if os.path.exists(rich_path):
        with io.open(rich_path, encoding="utf-8") as f:
            rich = json.load(f)
        page["align"] = rich.get("align")
        page["engine"] = rich.get("engine")
        if rich.get("align") and rich["align"].get("offset") is not None:
            page["offset"] = float(rich["align"]["offset"])
    return page


def build_result_for(aid):
    """给页面用的结果：有批改记录就给真报告，没有就说"这条还没收到录音"。"""
    page = job_page(aid)
    if page is not None:
        return page
    card = card_for(aid)
    if card is None:
        return build_sample_result()
    return {
        "no_audio": True,
        "assignment": card,
        "standard": (load_assignment(aid) or {}).get("standard") or {},
        "note": "标准答案已经按老师那份 .gp 生成好了；这条作业还没有录音样例，"
                "等真实录音进来就能批。",
    }


def load_real():
    """默认那一份（HOMEWORK_JOB）的批改结果；没有就 None。"""
    return job_page(JOB)

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


def build_sample_result():
    """没有任何已登记作业时的兜底：把 9-24 那次实测数字拼成结果页。"""
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


def run_task(task_id, aid):
    total = sum(s[0] for s in STAGES)
    waited = 0.0
    try:
        for idx, (dur, text) in enumerate(STAGES):
            time.sleep(dur)
            waited += dur
            TASKS[task_id].update({"stage": text, "stage_index": idx,
                                   "progress": int(waited / total * 100)})
        TASKS[task_id].update({"status": "completed", "progress": 100,
                               "stage": "批改完成", "result": build_result_for(aid)})
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
        u = urlparse(self.path)
        path = u.path
        aid = (parse_qs(u.query).get("id") or [JOB])[0]
        if path == "/api/assignments":
            rows = []
            for a in load_assignments():
                std = a.get("standard") or {}
                rows.append({"id": a["id"], "title": a.get("title"),
                             "artist": a.get("artist"), "course": a.get("course"),
                             "lesson": a.get("lesson"), "notes": std.get("notes"),
                             "track": std.get("track_name") or "—",
                             "crop": std.get("crop") or "",
                             "has_report": job_page(a["id"]) is not None})
            return self._send(200, {"assignments": rows, "current": aid})
        if path == "/api/score":
            # 把这次作业的 .gp 原文给前端（alphaTab 直接读它画谱）
            a = load_assignment(aid)
            gp = (a or {}).get("gp")
            if not gp or not os.path.isfile(gp):
                return self._send(404, "no score", "text/plain; charset=utf-8")
            with open(gp, "rb") as f:
                body = f.read()
            return self._send(200, body, "application/octet-stream")
        if path == "/api/assignment":
            card = card_for(aid)
            if card is None:
                return self._send(200, {"assignment": ASSIGNMENT, "standard": None,
                                        "id": aid, "demo": True, "real": False,
                                        "follow_url": follow_url_for(self.headers.get("Host")),
                                        "has_report": False})
            a = load_assignment(aid) or {}
            return self._send(200, {"assignment": card, "standard": a.get("standard"),
                                    "id": aid, "note": a.get("note") or "",
                                    "follow_url": follow_url_for(self.headers.get("Host")),
                                    "demo": False, "has_report": job_page(aid) is not None})
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
        u = urlparse(self.path)
        path = u.path
        if path != "/api/submit":
            return self._send(404, {"error": "404"})
        aid = (parse_qs(u.query).get("id") or [JOB])[0]
        if load_assignment(aid) is None:
            aid = JOB
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        # demo：不存文件，只记下「收到多大一坨」
        ctype = self.headers.get("Content-Type") or ""
        info = {"bytes": len(raw), "kind": "link" if "json" in ctype else "file"}
        tid = uuid.uuid4().hex[:12]
        TASKS[tid] = {"status": "running", "progress": 0, "stage": "已收到，排队中…",
                      "submitted": info, "assignment": aid}
        import threading
        threading.Thread(target=run_task, args=(tid, aid), daemon=True).start()
        return self._send(200, {"task_id": tid, "received": info})


def main():
    print("=" * 66)
    print("  HomeworkGrader · 作业检查")
    print("=" * 66)
    rows = load_assignments()
    if rows:
        print("  作业库   data/assignments 下 %d 份；默认展示 %s" % (len(rows), JOB))
        for a in rows:
            std = a.get("standard") or {}
            print("    %-22s %-30s %4s 个音  %s"
                  % (a["id"], (a.get("title") or "")[:30], std.get("notes"),
                     "（已批改）" if job_page(a["id"]) else ""))
        page = load_real()
        if page is not None:
            print("  批改结果 data\\jobs\\%s\\page.json（%s 分 ｜ 及格线 %s）"
                  % (JOB, page.get("score"), page.get("pass_line")))
        else:
            print("  ⚠ data\\jobs\\%s\\ 里还没有 page.json —— 默认那份只显示标准答案" % JOB)
    else:
        meta, notes = load_score()
        print("  （data/assignments 还是空的，先用样例数字）")
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
