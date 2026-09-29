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


def pick_test_audio():
    """自检要交一份真音频（提交会真的解码 + 跑判定）。

    优先用跟弹那边的真机素材；没有就合成一段 3 秒、很轻的正弦波 wav ——
    链路跑得通就行，自检只看界面（结果数字是多少不重要）。
    """
    for p in (os.environ.get("HOMEWORK_TEST_AUDIO"),
              r"E:\GuitarFollowLab\sound_data\6415慢速.m4a",
              r"E:\GuitarFollowLab\sound_data\hey jude.m4a"):
        if p and os.path.isfile(p):
            return p
    import math
    import struct
    import wave
    path = os.path.join(OUT, "hg_selftest_tone.wav")
    sr, secs, amp = 48000, 3, 0.05
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 220 * i / sr)))
                          for i in range(sr * secs))
        w.writeframes(frames)
    return path


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
        # 现在提交是真批改（会解码 + 跑跟弹判定链路），所以必须交一份**真音频**：
        # 优先用跟弹那边的真机素材，找不到就现场合成一段 3 秒的 wav（够跑通链路就行）。
        demo_audio = pick_test_audio()
        # 挑一条"已知会挑出错音"的组合来跑，界面上的几块才有东西可查
        try:
            ids = page.eval_on_selector_all("#pick option", "els => els.map(e => e.value)")
            if "6415-T3231323" in ids:
                page.select_option("#pick", "6415-T3231323")
                page.wait_for_timeout(600)
                checks.append(("能切到指定作业（6415）",
                               page.input_value("#pick") == "6415-T3231323"))
        except Exception:
            pass
        page.set_input_files("#file", demo_audio)
        checks.append(("选好文件后提交键变亮",
                       page.eval_on_selector('#submit', 'el => el.disabled') is False))
        page.click("#submit")
        # 真批改要跑判定链路：30 秒录音大约十几秒，留足时间
        page.wait_for_selector("#resultCard:not(.hidden)", timeout=180000)
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
        # 学隔壁那条教训：**报告说几处 == 真摆出来几张卡**（不许数了却没渲染）
        cards = page.evaluate("""() => {
          const n = document.querySelectorAll('#issues .issue').length
                  + document.querySelectorAll('#moreIssues .issue').length;
          const total = Number(document.getElementById('resultCard').dataset.issueTotal || -1);
          return {n: n, total: total};
        }""")
        checks.append(("结果页：卡片数 == 报告的处数（%d/%d）"
                       % (cards["n"], cards["total"]), cards["n"] == cards["total"]))
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
        try:
            ids = desk.eval_on_selector_all("#pick option", "els => els.map(e => e.value)")
            if "6415-T3231323" in ids:
                desk.select_option("#pick", "6415-T3231323")
                desk.wait_for_timeout(400)
        except Exception:
            pass
        desk.set_input_files("#file", demo_audio)
        desk.click("#submit")
        desk.wait_for_selector("#resultCard:not(.hidden)", timeout=180000)
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
