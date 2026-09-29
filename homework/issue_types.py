# -*- coding: utf-8 -*-
"""作业检查自己的「问题类型」表 —— **单一来源**。

学的是隔壁（VirtuCoach `services/issue_types.py`）的**做法**，不是照搬它那张表：

* 他们的表是"视频分析能挑出来的 10 类"（含 `dead_note` 闷音、`buzz` 杂音、
  `overlap` 叠音这些**音色类**）。作业检查现在只做"对着谱面逐音批改"，
  产得出的是下面这几类 —— 硬套他们那 10 类，一半会是永远不出现的空壳。
* 他们那份文档开头记的**真正教训**才是要学的：
  ① 类型表只有一份；
  ② **报告里说"有几处"，必须等于界面上真摆出来的卡片数**（不许"后端数了、前端不渲染"）；
  ③ 用测试盯着这条（他们那边是 `test_issue_type_sync.py`）。

所以这里定义：kind → 界面上叫什么、要不要标在谱面上、算不算"几处"。
前端（`web/app.js`）**不再自己写一份标签**，而是读 page.json 里的 `issue_labels`
（服务端从这张表生成）；`tools/shot_web.py` 会核对"卡片数 == 报的处数"。
"""

#: 类型表：kind -> {label 界面上的字, on_score 要不要标在谱面上, counts 算不算"几处"}
ISSUE_TYPES = {
    # 逐音对错（作业检查的主力，都是"和谱面这一格比"）
    "missing_note": {"label": "漏", "on_score": True, "counts": True,
                     "why": "谱面这一格没听到（或是漏了、或是没弹响）"},
    "wrong_note": {"label": "错", "on_score": True, "counts": True,
                   "why": "这一下听到了，但不是谱面这一格要求的音"},
    "extra_note": {"label": "多弹", "on_score": False, "counts": True,
                   "why": "录音里有对不上谱面的音（可能是多弹、重复弹、杂音）"},
    # 节奏：作业检查只报"用户能明显感觉到的"（Q18）
    "rush": {"label": "抢", "on_score": True, "counts": True,
             "why": "这一下比他自己该有的速度早了很多（≥1 秒）"},
    "drag": {"label": "拖", "on_score": True, "counts": True,
             "why": "这一下拖了很多（≥1 秒）"},
    "pause": {"label": "停", "on_score": True, "counts": True,
              "why": "谱面这儿本来要接着弹，却停了一下（Q20：不许停下重来）"},
    "rhythm_unstable": {"label": "节奏不稳", "on_score": False, "counts": True,
                        "why": "这一带和那一带的速度明显不一样（局部 BPM 漂移）"},
}

#: 给前端的标签表（page.json 的 issue_labels 就是它）
LABELS = {k: v["label"] for k, v in ISSUE_TYPES.items()}


def normalize(kind, sub=None):
    """把内部的粗分类换成表里的 kind（抢/拖/停都归到自己的名字下）。"""
    if kind == "timing":
        return {"early": "rush", "late": "drag"}.get(sub, "pause")
    return {"missing": "missing_note", "extra": "extra"}.get(kind, kind)


def counts(kind):
    return bool(ISSUE_TYPES.get(kind, {}).get("counts", True))
