# HomeworkGrader · 作业检查

VirtuCoach 的「作业检查」模块：课程 → 每节课一份作业（**Guitar Pro 谱面当标准答案**）→
学员交音频 → 对着标准答案批改 → 出**总体评价 + 打分 + 完成度**。
学员从 VirtuCoach 点「📝 作业检查」按钮跳过来（独立服务、独立端口）。

## 怎么跑

```bat
start.bat              :: 起服务（默认 1310），自己把地址打给你；不会自动开浏览器
start.bat 1311         :: 换端口
start.bat -o           :: 可选：用 Edge/Chrome 打开（绝不会走 IE）
```

打开 `http://localhost:1310`。

> 默认**不自动开浏览器**：这台机器的系统 http handler 是 Internet Explorer，打不开这个页面。

## 跑一次真正的批改（命令行）

```bat
E:\Python\python.exe -X utf8 homework\run_assignment.py ^
  --ref   C:\Users\Administrator\vc_gf\tl-6415.json ^
  --audio E:\GuitarFollowLab\sound_data\f32\6415\6415慢速.f32 ^
  --job   6415 --engine follow --ref-slice 1:32
```

作业的参考谱面是**老师上传的那份 .gp**（Q5/Q30）时，直接给它小节范围：

```bat
E:\Python\python.exe -X utf8 homework\run_assignment.py ^
  --ref-gp E:\GuitarFollowLab\.gp\the-beatles-hey_jude.gp3 --ref-track 0 --ref-bars 1:8 ^
  --audio  E:\GuitarFollowLab\sound_data\f32\hey_jude.f32 ^
  --job    heyjude-b1-8 --engine follow
```

只看参考谱面（`.gp → 这次作业那一段`）：

```bat
E:\Python\python.exe -X utf8 homework\reference.py ^
  --gp E:\GuitarFollowLab\.gp\the-beatles-hey_jude.gp3 --track 0 --bars 1:8 ^
  --out scores\hey-jude\lesson06\assignment.json
```

## 作业库（每份谱 = 一次作业）

```bat
:: 老师给的 .gp 登记成作业
E:\Python\python.exe -X utf8 homework\make_assignments.py gp ^
  --gp queen-we_will_rock_you.gp4 --id we-will-rock-you-01 --title "We will rock you"

:: 生成常见和弦走向的练习谱（真的 .gp4）+ 一起登记
E:\Python\python.exe -X utf8 homework\make_assignments.py progressions

:: 看现有作业
E:\Python\python.exe -X utf8 homework\make_assignments.py list

:: 拿登记好的作业直接批一条录音
E:\Python\python.exe -X utf8 homework\run_assignment.py ^
  --assignment 6415-T3231323 --audio <录音.f32> --engine follow
```

产物：`data/assignments/<id>/assignment.json`（作业档案）+ `ref.json`（参考时间轴）；
生成的练习谱在 `scores/practice/*.gp4`。页面上顶栏右侧的**作业选择器**列的就是这些作业。

链路（铁律 Q15 / Q29）：

```
参考谱面(.gp → 时间轴，按这次作业的小节/音序号裁段)
  → 起音           Node 子进程，跑跟弹产品页自己的链路（引擎只有那一份代码）
  → 对齐           身份锚定优先；读不出音高时退回按时间对齐（并标低置信度）
  → 判定           Node 子进程，逐音问"我要的这个音在不在这一下"
  → 逐音对错 → 按 Q17 聚合 → 按 Q24 打分 → data/jobs/<id>/result.json
```

**注意**：`--engine follow` 会调用隔壁的 `E:\GuitarFollowLab`（路径可用环境变量
`GUITARFOLLOW_REPO` 覆盖）；`.gp` 的解析也走它（`backend\tools\gp_timeline.py`，
`PYTHONPATH` 用 `E:\VirtuCoach-Lib`，可用 `GUITARFOLLOW_PYTHONPATH` 覆盖）。

## 现在到哪儿了

| 环节 | 状态 |
|---|---|
| 口径问答（32 题）／铁律 | ✅ `IRON-RULES.md`（32/32） |
| 竞品与论文调研 | ✅ `调研-作业检查-竞品与论文-2026-09-24.md` |
| 对齐（身份锚定 + 单调 DP + 置信度） | ✅ `homework/align.py`，合成回归 26 项全过 |
| 逐音比对 / 聚合 / 打分 | ✅ `homework/grade.py` + `run_assignment.py` |
| 前端（三步流程 + 报告页） | ✅ 2026-09-29 重做成对外汇报版（参数表 + 批改环节 + 报告表头 + 打印样式）；自检 13 项全过 |
| **提交 = 真批改** | ✅ 2026-09-29；上传 → 解码 48k 单声道（`homework/audio.py`）→ 跑跟弹判定链路 → 这一次的结果（不再是样例数字） |
| **批改链路 = 我们自己的一版** | ✅ 2026-09-29；起音 → 配对（允许漏弹/多弹/整体快慢）→ 判定（引擎 judgeNote，窗口照产品页）。漏一个音只报一处漏，不会一路错位。见 `思路.md` §11 |
| 交作业前不摆谱面，改「去跟练」入口 | ✅ 2026-09-29；练习交给跟练页（localhost:1209 / 手机 https:1210） |
| 结果里对着标准谱面标错音 | ✅ 2026-09-29；alphaTab 画这一段谱面 + 错音框红；自检 13 项全过 |
| 及格线 | ✅ **90 分**（2026-09-29 用户定） |
| 得分口径 | ✅ 2026-09-29 改版：**弹对的音 ÷ 本次作业的音数 × 100**（漏/错算没拿到，多弹不计分） |
| 「多弹」判定 | ✅ 2026-09-29；只有在"按下一遍假设能独立对上谱面 ≥60% 的音"时才叫重复弹了一遍 |
| 报告层（练习单位聚合 + 只展开 3 条 + 过程提醒） | ✅ 2026-09-29；跟练=练习/实时反馈、作业=成果检查，分工见 `思路.md` §10 |
| 首次真机实测 | ✅ 6415 分解和弦：起音 55 ｜ 对 30 / 错 3 / 漏 0 |
| 引擎接入方式 | ✅ 走跟弹产品页那条链路（自己拼 engine 调用数字对不上，已放弃） |
| 参考谱面（.gp → 作业那一段，`reference.py`） | ✅ 2026-09-29；Q6 选吉他轨（多轨谱别挑到人声/钢琴）；完成度从 34% 修到 94% |
| 问题卡定位（小节拍 + 录音秒 + 谱面秒） | ✅ 2026-09-29；定位改用跟弹的逐音导出记录 |
| 作业库（`make_assignments.py`） | ✅ 2026-09-29；老师给的 3 份 .gp + 5 份常见和弦走向（T3231323）= 8 份作业，页面可切换 |
| **双音 / 多音格（和弦）** | ✅ 2026-09-30；**一个起音判这一格里的所有弦**（同一时刻容差 0.02 秒）；小琶音（三根弦相隔约 100ms）判两次（起音后 90ms / 170ms），有一个过就算过。单音作业行为一字未变（Hey Jude 95 / 6415 81 前后一致）。见 `思路.md` §11.8 / §11.9 / §11.10 |
| **判定桥的领先要求 1.05 → 0.95** | ✅ 2026-09-30；只动响的那一档（轻的那档保持产品页的 0.90），`fitMax` 不动。扫表见 `思路.md` §11.10：双音真录音 88 → **92（过）**、6415 81 → **88**，而「故意写错一个音」的靶子照样报错（75 分） |
| **判定桥的 `fftSize` 抄对了（这一条是真因）** | ✅ 2026-09-30。`spectrumOf()` 返回的是 mags（长度 N/2），而引擎里 `binHz = sr / fftSize`；产品页那处调用传的是**真 FFT 点数 8192**（`judge-loop.js:996`），我们原来传了 `spec.length`（4096）→ bin 宽 11.72Hz（产品页 5.86Hz），**六弦一个半音只有 5Hz，所以低音弦被读成邻居** —— 这正是"隔壁实时没有、我们有"的原因。和页面自己的逐音导出对齐后：`candFit` 差**中位 1 音分**（原来 29）。见 `思路.md` §11.11 |
| **判定窗：窗长 = min(分辨需要的长度, 这个音自己的时间片)** | ✅ 2026-09-30（默认开，`HG_WIN_AUTO=0` 可关；κ 默认 0.25）。低音弦的窗要更长才分得开半音，**长窗贴在音符自己的时间片里、从起音后 30ms 往正方向量**（往回伸会把上一个音装进来）。⚠ 要和上面那条一起才有效：fftSize 抄错时这条怎么扫都没用。见 `思路.md` §11.11：双音真录音 **92 → 95**、6415 **88 → 91**、Hey Jude 保持 **95**、小琶音 100 / 错谱 75 不动；手标 24 音真值集 对22 错0 漏2（页面自己跑是 对14 错9） |
| **练习谱按真录音重做 + 修掉答案里的错音** | ✅ 2026-09-30；双音型改成 T／3／〔1+2〕／3 走两遍（8 下/小节 = 32 格 / 40 音）；F 和弦 1 弦原来是空弦 E4（不在 F 和弦里），改成 1 品 F4。6415 那条真录音 78 → 81。见 `思路.md` §11.9 |
| 音轨分离（自动判断）／降噪／报告话术（接 VirtuCoach playbook） | 🔜 还没做 |

## 文档在哪

| 文件 | 是什么 |
|---|---|
| `IRON-RULES.md` | **32 条铁律**（用户逐条定的口径，由 `tools/ask.py` 生成，别手改） |
| `思路.md` | 按铁律写的设计：产品形态、链路、目录、边界、开工顺序 |
| `三个项目的关系.md` | 它和 VirtuCoach / GuitarFollowLab 谁是谁、谁连谁、谁能改什么 |
| `实测-对齐-2026-09-24.md` | 第一次对齐实测（为什么不能"只看时间"） |
| `调研-作业检查-竞品与论文-2026-09-24.md` | SmartMusic / MatchMySound 等竞品 + 12 篇论文 |
| `记忆同步-2026-09-29-夜-收工状态.md` | **新窗口先读这份**：做到哪了、你要做什么、我要做什么（最新） |
| `记忆同步-2026-09-29-收工状态.md` | 白天那批的细节（§1.1~§1.16：作业库、看谱面、报告层、真批改、节奏口径…） |

要改口径：重跑 `tools/ask.py` 重答那一题，**不要直接改铁律文件**。

## 目录

```
homework/    服务端与算法（reference / align / grade / run_assignment / server / 两个 Node 引擎桥）
web/         前端（index.html / style.css / app.js）
web/vendor/  第三方运行文件（alphaTab + Bravura 字体，画谱面用；来源见里面的 README）
tools/       口径问答、对齐探针、合成回归、前端截图自检
data/        音频库、批改中间产物（不进 git）+ 作业库 data/assignments/（进 git）
scores/      与 GuitarFollow 共用的曲谱库；老师给的 .gp 不进 git，practice/ 生成的练习谱进 git
```

`data/assignments/` 是**作业库**（每次作业一个目录：档案 + 参考时间轴），
`scores/practice/` 是我们自己生成的练习谱（常见和弦走向），这两处是进 git 的。

`data/` 和 `scores/` 里的东西**都不进 git**（学员隐私 + 谱面版权），见 `.gitignore`。
