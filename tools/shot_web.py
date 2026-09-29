# -*- coding: utf-8 -*-
"""作业检查前端的**自检**：跑一遍"提交 → 批改 → 出报告"，顺手抓 JS 报错 / 4xx。

跑法（要先在另一个窗口把 `start.bat` 起起来）：
    E:\\Python\\python.exe -X utf8 tools\\shot_web.py

默认**不存截图**（用户 2026-09-29：不用每次截图）。真要出图加 --shots，
写到 %TEMP%\\hg_shot_*.png。
"""

import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:1310/"
OUT = tempfile.gettempdir()
SHOTS = "--shots" in sys.argv


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 430, "height": 940},
                                device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.on("console", lambda m: m.type == "error" and errors.append("console: %s" % m.text))
        page.on("response", lambda r: r.status >= 400 and errors.append(
            "http %d %s" % (r.status, r.url)))

        page.goto(URL, wait_until="load", timeout=20000)
        page.wait_for_timeout(600)
        if SHOTS:
            first = os.path.join(OUT, "hg_shot_upload.png")
            page.screenshot(path=first, full_page=True)
            print("交作业 ->", first)

        # 第一屏自检：三步条在第 1 步、作业信息填好、提交键还是灰的
        checks = []
        checks.append(("第一屏：步骤条在第 1 步",
                       page.eval_on_selector('.step.is-on', 'el => el.dataset.step') == '1'))
        checks.append(("第一屏：作业标题出来了",
                       (page.inner_text('#title') or '').strip() not in ('', '—')))
        checks.append(("第一屏：提交键是灰的（还没给东西）",
                       page.eval_on_selector('#submit', 'el => el.disabled') is True))
        checks.append(("第一屏：没横向溢出",
                       page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")))
        # 页面现在只收文件（2026-09-29 撤掉了直链入口），用一份假音频触发流程
        demo_audio = os.path.join(OUT, "hg_demo_take.m4a")
        with open(demo_audio, "wb") as f:
            f.write(b"\x00" * 4096)
        page.set_input_files("#file", demo_audio)
        checks.append(("选好文件后提交键变亮",
                       page.eval_on_selector('#submit', 'el => el.disabled') is False))
        page.click("#submit")
        page.wait_for_selector("#resultCard:not(.hidden)", timeout=20000)
        page.wait_for_timeout(500)
        if SHOTS:
            second = os.path.join(OUT, "hg_shot_result.png")
            page.screenshot(path=second, full_page=True)
            print("出结果 ->", second)

        checks.append(("结果页：步骤条走到第 3 步",
                       page.eval_on_selector('.step.is-on', 'el => el.dataset.step') == '3'))
        checks.append(("结果页：分数不是空的",
                       (page.inner_text('#score') or '').strip() not in ('', '—')))
        checks.append(("结果页：进度条收起来了",
                       page.eval_on_selector('#progressCard', 'el => el.hidden') is True))
        checks.append(("结果页：问题卡有内容",
                       page.eval_on_selector('#issues', 'el => el.children.length') >= 1))
        checks.append(("结果页：谱面图画出来了",
                       page.eval_on_selector('#chart', 'el => el.children.length') >= 20))
        # 出结果后：标准谱面画出来 + 错音被框红（最多等 15 秒）
        try:
            page.wait_for_selector("#scoreView svg", timeout=15000)
            score_ok = True
        except Exception:
            score_ok = False
        checks.append(("结果页：标准谱面画出来了", score_ok))
        try:
            page.wait_for_selector("#scoreMarks .mk", timeout=8000)
            marks_ok = True
        except Exception:
            marks_ok = False
        checks.append(("结果页：错音在谱面上框出来了", marks_ok))
        checks.append(("结果页：没横向溢出",
                       page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")))

        # 汇报用：桌面/投屏宽度再来一张（只出图，不加断言）
        desk = browser.new_page(viewport={"width": 1280, "height": 900})
        desk.goto(URL, wait_until="load", timeout=20000)
        desk.wait_for_timeout(400)
        desk.set_input_files("#file", demo_audio)
        desk.click("#submit")
        desk.wait_for_selector("#resultCard:not(.hidden)", timeout=20000)
        desk.wait_for_timeout(500)
        if SHOTS:
            third = os.path.join(OUT, "hg_shot_desktop.png")
            desk.screenshot(path=third, full_page=True)
            print("报告（投屏）->", third)
        desk.close()

        browser.close()

    failed = [c for c in checks if not c[1]]
    for name, ok in checks:
        print("  %s %s" % ("PASS" if ok else "FAIL", name))
    if failed:
        errors.append("页面自检 %d 项没过" % len(failed))

    if errors:
        print("发现 %d 条错误：" % len(errors))
        for e in errors:
            print("   " + e)
        return 1
    print("没有 pageerror / console error / 4xx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
