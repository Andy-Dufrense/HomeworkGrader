# 曲谱库（和 GuitarFollow 共用）

铁律 Q30：**作业检查的曲谱库和 Guitar Follow Lab 共用同一份源**——
同一首歌在「跟练」和「作业批改」里必须是同一份谱面，否则判定口径会分叉。

现状：还是"按绝对路径借读跟弹已经生成的时间轴"（`homework/server.py` 的 `HOMEWORK_SCORE`
默认指向 `E:\GuitarFollowLab\frontend\data\hey_jude.json`），**还没正式化成一个共享目录**。
这件事列在 `思路.md` 的待办里，没定之前不要再加第三个读法。

本目录里的 `.gp` **不进 git**（版权），只在本机放。
