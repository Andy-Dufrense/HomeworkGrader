# -*- coding: utf-8 -*-
"""HomeworkGrader 需求问答：每一题先摆调研到的事实、再给我的推荐，你点头或给自己的想法。

为什么这么写：光给选项等于把判断推给你。所以每题都是三段——
    ① 我调研到的（有出处：哪份文件、哪条记忆）
    ② 我的推荐 + 为什么（回车就是采纳它）
    ③ 你的回答：采纳推荐 / 选别的选项 / 直接写你的思路（原话进铁律）

答完以后：
    tools/answers.json   机器可读的答案（后续开发唯一的依据）
    IRON-RULES.md        给人看的铁律（本脚本生成，别手改）

用法：

    E:\Python\python.exe -X utf8 E:\HomeworkGrader\tools\ask.py

命令（每一题都能用）：

    回车             采纳我的推荐（这一题会记成「采纳推荐」）
    A / B / 1,3      选别的选项（多选题可以一次选几个）
    一整句话         直接说你的想法 / 思路 / 结论，原样进铁律
    s                跳过（记成「待定」，开发前必须回来定）
    b                回到上一题重答
    ?                看每个选项到底意味着什么
    l                看总进度
    q                存盘退出，下次接着答
"""

import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QFILE = os.path.join(HERE, "questions.json")
AFILE = os.path.join(HERE, "answers.json")
RFILE = os.path.join(os.path.dirname(HERE), "IRON-RULES.md")


def _force_utf8_when_redirected():
    """输出被重定向到文件时用 UTF-8；控制台里不动（交给 Python 自己处理代码页）。"""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if not s or not hasattr(s, "buffer"):
            continue
        enc = (getattr(s, "encoding", "") or "").lower()
        try:
            if "utf" not in enc and not s.isatty():
                setattr(sys, name, io.TextIOWrapper(s.buffer, encoding="utf-8", errors="replace"))
        except Exception:
            pass


_force_utf8_when_redirected()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def module_name(bank, mid):
    for m in bank.get("modules", []):
        if m.get("id") == mid:
            return m.get("name") or mid
    return mid


def option_by_key(q, key):
    for o in q.get("options") or []:
        if str(o.get("key", "")).strip().lower() == str(key).strip().lower():
            return o
    return None


def recommend_keys(q):
    """推荐可能是一个（A）或几个（A,C）。"""
    raw = str(q.get("recommend") or "").strip().lower()
    return [k for k in re.split(r"[,，、/\s]+", raw) if k]


def recommend_text(q):
    keys = recommend_keys(q)
    if not keys:
        return ""
    texts = []
    for k in keys:
        o = option_by_key(q, k)
        texts.append("%s. %s" % (k.upper(), (o or {}).get("text") or "?"))
    return "　".join(texts)


def parse_reply(raw, q):
    """把一行输入拆成 (choices, free_text)。选项字母/序号/整句都能收。"""
    text = (raw or "").strip()
    if not text:
        return [], ""
    keys = [str(o.get("key", "")).lower() for o in (q.get("options") or [])]
    parts = [p for p in re.split(r"[,，、/\s]+", text.lower()) if p]
    picked, rest = [], []
    for p in parts:
        token = p.strip().rstrip(".").rstrip("，")
        if token in keys:
            picked.append(token)
            continue
        if token.isdigit() and 1 <= int(token) <= len(keys):     # 用序号回答
            picked.append(keys[int(token) - 1])
            continue
        rest.append(p)
    if not q.get("multi") and len(picked) > 1:
        picked = picked[:1]
    free = " ".join(rest).strip()
    if not picked:                                              # 直接打选项原文也算
        for o in q.get("options") or []:
            opt_text = str(o.get("text", ""))
            if opt_text and opt_text in text:
                picked.append(str(o.get("key", "")).lower())
        if picked:
            free = ""
    return picked, free


def build_rule(q, entry):
    """把一条答案翻译成铁律里的一句话。"""
    if not entry or entry.get("skipped"):
        return "（待定）" + str(q.get("title", "")) + "：这题还没定，开发前必须先问用户。"
    parts = []
    for k in entry.get("choices") or []:
        o = option_by_key(q, k)
        parts.append((o.get("rule") or o.get("text") or str(k)) if o else str(k))
    free = str(entry.get("free") or "").strip()
    if free:
        parts.append(free if not parts else "补充：" + free)
    return "；".join(parts) if parts else "（没有答案）"


def write_rules(bank, answers):
    qs = bank.get("questions") or []
    ans = (answers or {}).get("answers") or {}
    answered = [q for q in qs if ans.get(q["id"]) and not ans[q["id"]].get("skipped")]
    pending = [q for q in qs if not ans.get(q["id"]) or ans[q["id"]].get("skipped")]

    lines = []
    lines.append("# 作业检查 · 铁律（由 tools/ask.py 从 answers.json 生成，别手改）")
    lines.append("")
    lines.append("> 生成时间：" + time.strftime("%Y-%m-%d %H:%M") +
                 " ｜ 已答 " + str(len(answered)) + "/" + str(len(qs)) +
                 " ｜ 待定 " + str(len(pending)))
    lines.append("> ")
    lines.append("> **这些是用户定版的口径，开发 HomeworkGrader 时不得违反。**")
    lines.append("> 要改某一条，就重跑 `ask.py` 重答那一题；**不要直接改这份文件**。")
    lines.append("")

    for m in bank.get("modules", []):
        group = [q for q in qs
                 if q.get("module") == m.get("id") and ans.get(q["id"])
                 and not ans[q["id"]].get("skipped")]
        if not group:
            continue
        lines.append("## " + str(m.get("name") or m.get("id")))
        lines.append("")
        for q in group:
            lines.append("- **" + q["id"] + "** " + build_rule(q, ans[q["id"]]))
        lines.append("")

    lines.append("## 待定（开发前必须回来定）")
    lines.append("")
    if pending:
        for q in pending:
            lines.append("- **" + q["id"] + "** " + str(q.get("title") or "") +
                         "　（" + module_name(bank, q.get("module")) + "）")
    else:
        lines.append("- 无，全部定了。")
    lines.append("")

    lines.append("## 附：每题的原始回答")
    lines.append("")
    for q in qs:
        e = ans.get(q["id"]) or {}
        if not e:
            continue
        picked = "、".join(e.get("choices") or []) or "（无）"
        free = str(e.get("free") or "").strip()
        src = ""
        if e.get("accepted"):
            src = "（采纳了推荐 " + str(q.get("recommend") or "") + "）"
        elif q.get("recommend"):
            src = "（用户自定，推荐本来是 " + str(q.get("recommend") or "") + "）"
        lines.append("- **" + q["id"] + "** " + str(q.get("title") or "") + src)
        lines.append("  - 选项：" + picked)
        if free:
            lines.append("  - 原话：" + free)

    with open(RFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(answered), len(pending)


def show_question(bank, q, idx, total, answered_count, verbose=False):
    keys = recommend_keys(q)
    print("")
    print("─" * 70)
    print("【第 %d/%d 题 · %s】已答 %d 题" %
          (idx + 1, total, module_name(bank, q.get("module")), answered_count))
    print("")
    print("%s  %s" % (q.get("id"), q.get("title")))
    if q.get("why"):
        print("   为什么要定这条：%s" % q.get("why"))

    researched = q.get("researched") or []
    if researched:
        print("")
        print("   我调研到的：")
        for r in researched:
            print("     · %s" % r)

    if q.get("recommend"):
        print("")
        print("   ⭐ 我的推荐：%s" % recommend_text(q))
        if q.get("recommend_why"):
            print("      %s" % q.get("recommend_why"))
        print("      回车就是采纳它；不同意就直接说你的想法，我按你的原话记进铁律。")

    print("")
    print("   选项：")
    for o in q.get("options") or []:
        mark = "   ← 推荐" if str(o.get("key", "")).lower() in keys else ""
        print("     %s. %s%s" % (o.get("key"), o.get("text"), mark))

    print("")
    hint = "回车=采纳推荐" if keys else "打选项字母"
    print("   （%s；也可以打 A / 1,3 / 直接写一整句话；s=跳过 b=上一题 ?=选项含义 l=进度 q=存盘退出）" % hint)
    if verbose:
        print("")
        print("   ── 每个选项到底意味着什么（会写进铁律的原话）──")
        for o in q.get("options") or []:
            print("     %s. %s" % (o.get("key"), o.get("rule") or o.get("text")))


def main():
    if not os.path.exists(QFILE):
        sys.exit("找不到题库：%s" % QFILE)
    bank = load_json(QFILE)
    qs = bank.get("questions") or []
    if not qs:
        sys.exit("题库是空的：%s" % QFILE)

    answers = load_json(AFILE, {"answers": {}}) or {"answers": {}}
    answers.setdefault("answers", {})
    store = answers["answers"]
    answered_count = lambda: len([q for q in qs if store.get(q["id"]) and not store[q["id"]].get("skipped")])

    print("=" * 70)
    print("  HomeworkGrader · 作业检查口径问答")
    print("=" * 70)
    print("  每一题我都会先说我调研到什么、我推荐哪个（回车就是采纳），")
    print("  你有别的思路就直接写出来，那才算你的结论。")
    print("")
    print("  回答会落成：tools\\answers.json（开发的依据）和 IRON-RULES.md（铁律）")
    print("  一共 %d 题。随时打 q 存盘退出，下次接着答；拿不准打 s 保持待定。" % len(qs))
    if answered_count():
        print("  你已经答过 %d 题，这次从第一道没答的接着来。" % answered_count())

    i = 0
    while i < len(qs):
        q = qs[i]
        ent = store.get(q["id"])
        if ent and not ent.get("skipped"):
            i += 1
            continue
        show_question(bank, q, i, len(qs), answered_count())
        try:
            raw = input("   你的回答 > ")
        except (EOFError, KeyboardInterrupt):
            print("")
            n_ok, n_pending = write_rules(bank, answers)
            save_json(AFILE, answers)
            print("已存盘：%s" % AFILE)
            print("铁律已更新：%s（已答 %d，待定 %d）" % (RFILE, n_ok, n_pending))
            return

        stripped = raw.strip()
        cmd = stripped.lower()
        if cmd in ("q", "quit", "exit"):
            n_ok, n_pending = write_rules(bank, answers)
            save_json(AFILE, answers)
            print("")
            print("已存盘：%s" % AFILE)
            print("铁律已更新：%s（已答 %d 题，待定 %d 题）" % (RFILE, n_ok, n_pending))
            print("下次接着答： E:\\Python\\python.exe -X utf8 %s" % os.path.abspath(__file__))
            return
        if cmd in ("l", "ls", "list"):
            print("")
            for qq in qs:
                e = store.get(qq["id"])
                mark = "✅" if (e and not e.get("skipped")) else ("⏭" if e else "⬜")
                print("   %s %s %s" % (mark, qq["id"], qq.get("title")))
            continue
        if cmd in ("?", "h", "help"):
            show_question(bank, q, i, len(qs), answered_count(), verbose=True)
            continue
        if cmd in ("b", "back"):
            if i > 0:
                i -= 1
                prev = qs[i]
                store.pop(prev["id"], None)
                print("")
                print("   回到 %s，原来那个答案先撤掉了，重新答一遍。" % prev["id"])
            else:
                print("   已经是第一题了。")
            continue
        if cmd in ("s", "skip"):
            store[q["id"]] = {"skipped": True, "at": time.strftime("%Y-%m-%d %H:%M")}
            save_json(AFILE, answers)
            write_rules(bank, answers)
            print("   记成待定（开发前必须回来定）。")
            i += 1
            continue

        accepted = False
        if not stripped:
            keys = recommend_keys(q)
            if not keys:
                print("   这题我没给推荐，得你自己定（或者打 s 先放着）。")
                continue
            choices, free = keys, ""
            accepted = True
        else:
            choices, free = parse_reply(raw, q)
        if not choices and not free:
            print("   没读懂这条，重来一次（要跳过就打 s）。")
            continue

        store[q["id"]] = {
            "choices": choices,
            "free": free,
            "raw": stripped,
            "accepted": accepted,
            "recommend_at_answer_time": q.get("recommend") or "",
            "at": time.strftime("%Y-%m-%d %H:%M"),
        }
        save_json(AFILE, answers)
        write_rules(bank, answers)
        print("   ✔ 记下了：" + build_rule(q, store[q["id"]]))
        i += 1

    n_ok, n_pending = write_rules(bank, answers)
    save_json(AFILE, answers)
    print("")
    print("=" * 70)
    print("  全部答完了。已答 %d，待定 %d。" % (n_ok, n_pending))
    print("  铁律：%s" % RFILE)
    print("  待定的那几条开发前必须先定（重跑本脚本只问没答的）。")


if __name__ == "__main__":
    main()
