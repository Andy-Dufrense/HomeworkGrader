# data 目录（不进 git）

```
data/
├── audio/        本项目自己的音频库（学员交上来的录音）—— 涉及隐私，绝不入库
├── jobs/         每次批改的中间产物与结果 —— 随时能重跑，不入库
│   └── <作业id>/
│       ├── events.json   引擎桥的起音+读数
│       ├── pairs.json    对齐后给判定桥的 (时刻, 期望音)
│       ├── judged.json   判定桥的逐音结论
│       ├── result.json   逐音对错 + 聚合后的问题 + 分数
│       └── page.json     页面要的那份（server.py 直接读）
└── homework.db   本项目自己的库（还没建）
```

要重新生成 `jobs/<id>/`，跑：

```bat
E:\Python\python.exe -X utf8 homework\run_assignment.py ^
  --ref <参考时间轴.json> --audio <录音.f32> --job <作业id> --engine follow
```
