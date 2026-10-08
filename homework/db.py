# -*- coding: utf-8 -*-
"""作业检查 · 本项目自己的库（铁律 Q30：自己要一个库，不塞进 VirtuCoach 的 feedbacks.db）。

只存"批改这件事"的东西，两不借：
  assignments   登记过的作业（id / 名称 / 课程 / 参考谱面 / 多少音）
  submissions   每一次提交与批改结果（哪份作业、交的什么文件、多少分、对错漏多少、什么时候）

明细（逐音记录、中间产物）仍然在 data/jobs/<job>/ 里，库里只放"要查要统计"的字段。
批改**不依赖**这个库：写库失败只打一行日志，不影响出报告。

用法：
    E:\\Python\\python.exe -X utf8 homework\\db.py init      # 建库/建表
    E:\\Python\\python.exe -X utf8 homework\\db.py list      # 看最近的提交
    E:\\Python\\python.exe -X utf8 homework\\db.py sync      # 把 data/assignments 同步进来
"""

import datetime
import io
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(ROOT, "data", "homework.db")
ASSIGN_DIR = os.path.join(ROOT, "data", "assignments")

SCHEMA = """
create table if not exists assignments (
  id text primary key,
  title text, course text, lesson text,
  notes integer, track text, gp text, updated_at text
);
create table if not exists submissions (
  id integer primary key autoincrement,
  aid text, file text, seconds real, job text,
  score real, passed integer,
  ok integer, wrong integer, missing integer, extra integer,
  verdict text, created_at text,
  -- graded = 正常批改过；invalid_upload = 上传跟作业对不上（传错文件/没录到吉他），
  -- 不出报告也不计分，只在这儿留一笔（用户 2026-10-08 定）
  status text
);
create index if not exists idx_sub_aid on submissions(aid, created_at);
"""


def connect(path=None):
    p = path or os.environ.get("HOMEWORK_DB") or DEFAULT_DB
    d = os.path.dirname(os.path.abspath(p))
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    return con


def init(con):
    con.executescript(SCHEMA)
    # 老库升级：submissions 原来没有 status 这一列（2026-10-08 加）
    cols = [r[1] for r in con.execute("pragma table_info(submissions)").fetchall()]
    if "status" not in cols:
        con.execute("alter table submissions add column status text")
    con.commit()
    return con


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert_assignment(con, a):
    if not a:
        return
    std = a.get("standard") or {}
    con.execute(
        "insert into assignments(id,title,course,lesson,notes,track,gp,updated_at) "
        "values(?,?,?,?,?,?,?,?) on conflict(id) do update set "
        "title=excluded.title, course=excluded.course, lesson=excluded.lesson, "
        "notes=excluded.notes, track=excluded.track, gp=excluded.gp, updated_at=excluded.updated_at",
        (a.get("id"), a.get("title"), a.get("course"), a.get("lesson"),
         std.get("notes"), std.get("track_name"), a.get("gp"), _now()))
    con.commit()


def record_submission(con, aid, file, seconds, job, page, status=None):
    c = page.get("counts") or {}
    if status is None:
        g = page.get("gate") or {}
        if not g:
            status = "graded"
        else:
            # 没弹完和传错文件分开记（用户 2026-10-08：没弹完要有单独的提示）
            status = "incomplete" if g.get("kind") == "unfinished" else "invalid_upload"
    con.execute(
        "insert into submissions(aid,file,seconds,job,score,passed,ok,wrong,missing,extra,"
        "verdict,created_at,status) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, file, seconds, job, page.get("score"), 1 if page.get("passed") else 0,
         c.get("right"), c.get("wrong"), c.get("missing"), c.get("extra"),
         page.get("verdict_text"), _now(), status))
    con.commit()


def sync_assignments(con):
    n = 0
    if os.path.isdir(ASSIGN_DIR):
        for name in sorted(os.listdir(ASSIGN_DIR)):
            p = os.path.join(ASSIGN_DIR, name, "assignment.json")
            if os.path.exists(p):
                with io.open(p, encoding="utf-8") as f:
                    upsert_assignment(con, json.load(f))
                n += 1
    return n


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "list"
    con = init(connect())
    if cmd == "init":
        print("库已就绪：%s" % (os.environ.get("HOMEWORK_DB") or DEFAULT_DB))
        return 0
    if cmd == "sync":
        print("同步了 %d 份作业到库里" % sync_assignments(con))
        return 0
    if cmd == "list":
        rows = con.execute(
            "select * from submissions order by id desc limit 20").fetchall()
        print("最近 %d 次提交：" % len(rows))
        for r in rows:
            keys = r.keys()
            flag = (r["status"] if "status" in keys else None) or "graded"
            if flag != "graded":
                label = "没弹完" if flag == "incomplete" else "上传不对"
                print("  %-18s %-22s   ——   %s（%s），不计分 ｜ %s"
                      % (r["created_at"], (r["file"] or "")[:22], label, flag, r["aid"]))
                continue
            print("  %-18s %-22s %5s 分 %s ｜ 对%s 错%s 漏%s 多弹%s ｜ %s"
                  % (r["created_at"], (r["file"] or "")[:22], r["score"],
                     "过" if r["passed"] else "没过",
                     r["ok"], r["wrong"], r["missing"], r["extra"], r["aid"]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
