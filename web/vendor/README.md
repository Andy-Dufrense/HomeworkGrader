# vendor（第三方运行文件，不要手改）

前端要**把老师上传的谱面画出来**，用的是 GuitarFollowLab 那边同一份 alphaTab
（`E:\GuitarFollowLab\frontend\vendor\`），直接复制过来的，版本见文件里的
`alphaTab.meta.version`（当前 1.8.4）。

| 文件 | 干什么 | 来源 / 许可 |
|---|---|---|
| `alphaTab.min.js` | 解析 .gp3/.gp4/.gp5/.gp7 并渲染成五线谱 + 六线谱 | alphaTab, MPL-2.0 |
| `font/Bravura.woff2` | 乐谱字体（音符、谱号那些符号） | Bravura, SIL Open Font License 1.1 |
| `font/bravura_metadata.json` | 上面那套字体的字形度量（alphaTab 排版要用） | 同上 |

**没搬过来的**：`sonivox.sf2`（音色库）—— 那是播放用的，作业检查只看谱面不播放。

为什么要搬：这台机器上 jsdelivr/CDN 是挡的，字体和库都必须本地提供；
`web/` 是本服务的静态目录，前端只能从这里取。

升级办法：从 GuitarFollowLab 的 `frontend/vendor/` 再复制一次同名文件。
