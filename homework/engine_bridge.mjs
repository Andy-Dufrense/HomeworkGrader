// 作业检查 · 引擎桥：把一段录音喂进 GuitarFollow 的引擎，输出「每个起音 + 音高读数」。
//
// 为什么要有这个文件（铁律 Q15 / Q29）：
//   起音与读数**只有一份代码**，在跟弹的 backend/engine/ 里。作业检查这边只做编排：
//   把 f32 按帧喂进去、收结果、写成 JSON 交给 Python。不复制、不重写、不就地调参。
//
// 帧循环的写法照 `C:\Users\Administrator\vc_gf\voice-gate.mjs`（那份文件编码坏了、
// 跑不起来，这里是按同样顺序重写一份干净的：同样的 floor 更新、同样的 decideOnset 参数、
// 同样的 90ms 判定延迟）。
//
// 用法：
//   node homework/engine_bridge.mjs <录音.f32> <输出.json> [loHz] [hiHz]
//   loHz/hiHz = 读数频带。默认 70~1200；按作业谱面的音高范围收窄能显著减少读错
//   （跟弹的经验：不限定频带时，拨弦那一下的低频闷响会凑出假的成串线）。

import fs from 'node:fs';
import path from 'node:path';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { decideOnset } = await import(M + 'onset.js');
const {
  fluxRelOf, hfFluxRelOf, hfBandRiseOf, lowBandRiseOf, shapeFluxOf, resetAnalysis,
  diffMags, readPluckF0,
} = await import(M + 'analysis.js');
const { spectrumOf, hzToMidi } = await import(M + 'dsp.js');
const { CFG, CAPTURE } = await import(M + 'config.js');

const SR = 48000;
const HOP = 16;              // 帧步长（ms），和页面一致
// 读数窗**以起音采样点为中心**（用户 2026-09-24 收工状态 §3 第 1 条）：
//   pre = [起音−40ms, 起音−10ms]   post = [起音+10ms, 起音+40ms]
// 为什么不能像页面那样"起音后 90ms 再读"：那两段都落在余响里，相减等于把新音
// 自己减掉（实测：60 个起音里 56 个读不出来，正是这么来的）。
const PRE_FROM_MS = -40, PRE_LEN_MS = 30;
const POST_FROM_MS = 10, POST_LEN_MS = 30;

const file = process.argv[2];
const outPath = process.argv[3];
if (!file || !outPath) {
  console.error('用法：node homework/engine_bridge.mjs <录音.f32> <输出.json> [loHz] [hiHz]');
  process.exit(2);
}
const loHz = Number(process.argv[4] || 70);
const hiHz = Number(process.argv[5] || 1200);

const raw = fs.readFileSync(file);
const AUDIO = new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4);
const T_END = (AUDIO.length / SR) * 1000;

function absWindow(fromMs, lenMs) {
  const n = Math.max(64, Math.round((lenMs / 1000) * SR));
  const start = Math.round((fromMs / 1000) * SR);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const j = start + i;
    out[i] = (j >= 0 && j < AUDIO.length) ? AUDIO[j] : 0;
  }
  return out;
}

function frameAt(tMs, n) {           // 页面那套：取"最近 n 个采样"
  const end = Math.floor((tMs / 1000) * SR);
  const from = Math.max(0, end - n);
  const buf = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const j = from + i;
    buf[i] = (j >= 0 && j < AUDIO.length) ? AUDIO[j] : 0;
  }
  return buf;
}

function rms(a, from, n) {
  let s = 0;
  for (let i = 0; i < n; i++) { const v = a[from + i]; s += v * v; }
  return Math.sqrt(s / n);
}

resetAnalysis();

const events = [];
let floor = 0.001;
let frames = 0;
// 「有没有在弹」的粗量：整段里"电平超过噪声线"的帧占比。
// 为什么要有（2026-10-08，用户：9 11 11 是吉他，怎么能说"没听到吉他"）：
//   拿"起音数太少"当"没听到吉他"的判据是错的 —— 9 11 11（几声就完的小琶音）起音一样少。
//   实测"响帧占比"能干净分开：说话 17.8% / 咳嗽 13.6% / 别人在弹 12.1%
//   ↔ 真在弹 67.8%~95.1%（9 11 11 = 83.3%）。中间空着，40% 一刀。
const SOUND_MIN = 0.03;
let loudFrames = 0;
let lastOnsetMs = -1e9;
let refractoryUntilMs = -1e9;
const levelHist = [];
let peakLvRef = 0;
let unread = 0;

for (let t = 0; t < T_END; t += HOP) {
  const buf = frameAt(t, CAPTURE);
  const lv = rms(buf, buf.length - 1024, 1024);
  frames++;
  if (lv >= SOUND_MIN) loudFrames++;

  // 环境地板：和页面 micTickBody 一样（前 30 帧建底，之后只降不升）
  if (frames <= 30) floor += (Math.min(lv, 0.05) * 0.9 - floor) * 0.3;
  else if (lv < floor) floor = floor * 0.9 + lv * 0.1;
  else floor = Math.min(floor * 1.0003 + 1e-7, 0.06);
  floor = Math.max(floor, 0.0005);
  const gate = Math.max(CFG.absFloor, floor * CFG.onsetSensitivity);
  peakLvRef = Math.max(lv, peakLvRef * 0.998);

  const flux = fluxRelOf(buf);
  const hfFlux = hfFluxRelOf(buf);
  const hfBandRise = hfBandRiseOf(buf);
  const lowBandRise = lowBandRiseOf(buf);
  const shapeFlux = shapeFluxOf(buf);
  const prevLv = levelHist.length ? levelHist[levelHist.length - 1] : 0;
  const lagged = levelHist.length >= 3 ? levelHist[levelHist.length - 3] : 0;

  const g = decideOnset({
    phase: 'waiting', now: t, refractoryUntilMs, lastOnsetMs,
    minGapCfg: CFG.minGapMs, lv, prevLv, lagged, gate, floor,
    flux, hfFlux, hfBandRise, lowBandRise, shapeFlux,
    // 页面是按**谱面**判断"这一个音和上一个音同音"的；离线没有谱面，这里一律 false，
    // 靠 hfBandOk 那条（冷却期放行）兜同样的情况。
    repeatSame: false,
  });

  levelHist.push(lv);
  if (levelHist.length > 10) levelHist.shift();
  if (!g.onset) continue;

  // 以起音为中心的短窗差分谱 = "这一下新加进来的谱"，在上面读基频
  const post = spectrumOf(absWindow(t + POST_FROM_MS, POST_LEN_MS));
  const pre = spectrumOf(absWindow(t + PRE_FROM_MS, PRE_LEN_MS));
  const diff = diffMags(post, pre);
  const r = readPluckF0(diff, SR, post.length, { loHz, hiHz });

  const ev = { t: Number((t / 1000).toFixed(4)), onsetMs: t, lv: Number(lv.toFixed(4)) };
  if (r && r.hz > 0) {
    ev.hz = Number(r.hz.toFixed(2));
    ev.midi = Math.round(hzToMidi(r.hz));
    ev.conf = Number((Math.min(r.h2, r.h3) * 10).toFixed(3));   // 只当"可不可信"的证据，不参与对错
  } else {
    ev.hz = 0;
    ev.midi = null;                                             // 读不出来 → 不硬判，当"没有身份"
    ev.conf = 0;
    unread++;
  }
  events.push(ev);

  refractoryUntilMs = t + 110;
  lastOnsetMs = t;
}

const out = {
  audio: file,
  engine: 'GuitarFollow backend/engine：onset.js decideOnset + analysis.js diffMags/readPluckF0',
  band: [loHz, hiHz],
  seconds: Number((T_END / 1000).toFixed(2)),
  onsets: events.length,
  unread,
  // 「有没有在弹」：响帧占比（阈值见上面的 SOUND_MIN）+ 原始计数，给闸门用
  loudFrames,
  frames,
  soundMin: SOUND_MIN,
  loudRatio: Number((loudFrames / Math.max(1, frames)).toFixed(4)),
  events,
};
fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out, null, 1), 'utf8');

console.log(`录音 ${file}`);
console.log(`  ${out.seconds}s ｜ 起音 ${out.onsets} 个 ｜ 其中读不出音高 ${unread} 个`);
console.log(`  读数频带 ${loHz}~${hiHz} Hz ｜ 事件已写到 ${outPath}`);
