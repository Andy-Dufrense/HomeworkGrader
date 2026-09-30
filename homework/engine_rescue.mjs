// 作业检查 · 「安静起音」兜底复核桥（后台批改独有的一步）
//
// 为什么有它：起音层（跟弹的 engine/onset.js）会漏掉**轻的**拨弦 ——
// 上一根弦还在响，整段混音的电平几乎不跳，而这一下 2kHz 的爆发又不够猛
// （实测 6415慢速 9.94s 那一下：总电平只涨 1.12 倍、2kHz 频带只涨 1.25~1.74 倍，
//  门槛是「陡 1.4」或「频带 2.5」→ 认不出来）。漏了之后，配对只能把后面错开一位，
// 报告上就会成对出现"漏一个 + 多弹一个"。
//
// 我们是**后台批改**：知道谱面、也知道已经对好的对齐，所以可以只在"那一格该响的时刻"
// 去找证据 —— 不需要改引擎、也不需要动跟练的阈值（Q15/Q29 不破）。
//
// 判据（两道，都要过）：
//   ① **期望音自己的**基频带（±50 音分）在那一处**冒了头**（40ms 窗 / 比 40ms 前）
//      —— 这是"新拨一下"的物理证据；上一根弦的余响只会往下走，不会在**它的**
//      基频上冒头。用真音验证过：真漏（学员没弹）那两处是一路衰减（0.0034→0.0008），
//      漏检（学员弹了）那处是 10 倍抬头。
//   ② 判定桥在那一刻**判过**（用的是和正常路径**完全相同**的窗与 opts）。
//
// 输入 JSON：{ "audio": "...f32", "rise": 2.5, "entries": [
//                { "t": 9.94, "expectedMidi": 64, "string": 1, "fret": 0,
//                  "wins": [{"atMs":90,"winMs":170.67}] }, ... ] }
// 输出 JSON：{ "results": [ { ..., "tStar":…, "rise":…, "pass":…, "heard":…, "fit":… } ] }
//
// 用法：node homework/engine_rescue.mjs <in.json> <out.json>

import fs from 'node:fs';
import path from 'node:path';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { judgeNote } = await import(M + 'judger.js');
const { spectrumOf, midiToName } = await import(M + 'dsp.js');

const SR = 48000;
const OPEN = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };

// 找位置用的窗：40ms（1920 点）。**不用 8192**：那扇窗会把"冒头"抹平（170ms 里
// 一半是上一根弦的余响），我们要的是"这 40ms 比 40ms 前多了多少该音的能量"。
const SCAN_WIN_MS = 40;
const SCAN_PRE_GAP_MS = 20;      // 往前再空 20ms 取参照
const SCAN_STEP_MS = 5;
const CENTS_TOL = 50;            // 基频带 ±50 音分（容一点走音）

const inPath = process.argv[2];
const outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error('用法：node homework/engine_rescue.mjs <in.json> <out.json>');
  process.exit(2);
}

const job = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const RISE = job.rise != null ? Number(job.rise) : 2.5;
// 在预测时刻 ±rangeMs 里找。为什么给到 250ms：起音层漏掉一下之后，**局部预测**是
// 用邻居插值出来的，那一小段又常常整体偏 200~400ms（学员局部抢/拖），
// ±90ms 会直接扫不到（实测 6415慢速 那处真音在预测 +310ms 上）。
// 扫得宽靠后面两道门兜住：① 只有"期望音自己的基频带冒头"才算；② 判定还得过。
const SCAN_RANGE_MS = job.rangeMs != null ? Number(job.rangeMs) : 250;
const raw = fs.readFileSync(job.audio);
const AUDIO = new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4);

function magAt(fromMs, lenMs, f0) {
  const n = Math.max(64, Math.round((lenMs / 1000) * SR));
  const start = Math.round((fromMs / 1000) * SR);
  if (start < 0 || start + n > AUDIO.length) return 0;
  let re = 0, im = 0;
  for (let i = 0; i < n; i++) {
    const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));   // Hann
    const v = AUDIO[start + i] * w;
    const ph = (2 * Math.PI * f0 * i) / SR;
    re += v * Math.cos(ph);
    im += v * Math.sin(ph);
  }
  return Math.hypot(re, im) / n;
}

function bandMag(fromMs, f0) {
  // 期望音的基频带：±50 音分取最大（走音也认）
  return Math.max(magAt(fromMs, SCAN_WIN_MS, f0 * Math.pow(2, -CENTS_TOL / 1200)),
    magAt(fromMs, SCAN_WIN_MS, f0),
    magAt(fromMs, SCAN_WIN_MS, f0 * Math.pow(2, CENTS_TOL / 1200)));
}

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

function optsFor(string, fret, level) {
  const lv = level == null ? 0.12 : level;
  if (string == null) return { maxOffset: null, bandLo: 0, bandHi: 0 };
  const open = OPEN[string];
  if (!open) return { maxOffset: 2, bandLo: 0, bandHi: 0 };
  const o = 440 * Math.pow(2, (open - 69) / 12);
  return {
    maxOffset: 2,
    rivalMargin: lv >= 0.10 ? 0.95 : 0.90,
    bandLo: o * Math.pow(2, -1 / 12),
    bandHi: o * Math.pow(2, 25 / 12),
  };
}

const results = [];
for (const e of (job.entries || [])) {
  const f0 = 440 * Math.pow(2, (Number(e.expectedMidi) - 69) / 12);
  let best = { t: e.t, rise: 0, pre: 0, post: 0 };
  for (let d = -SCAN_RANGE_MS; d <= SCAN_RANGE_MS; d += SCAN_STEP_MS) {
    const t = e.t * 1000 + d;                        // ms
    const post = bandMag(t, f0);
    const pre = bandMag(t - SCAN_WIN_MS - SCAN_PRE_GAP_MS, f0);
    const rise = post / Math.max(pre, 1e-9);
    if (rise > best.rise) best = { t: t / 1000, rise, pre, post };
  }
  const wins = (e.wins && e.wins.length)
    ? e.wins.map((x) => ({ atMs: Number(x.atMs), winMs: Number(x.winMs) }))
    : [{ atMs: 90, winMs: (8192 / SR) * 1000 }];
  let judged = null, usedAt = wins[0].atMs;
  if (best.rise >= RISE) {
    // 逐扇窗都判一遍，取**最有把握**的那一扇：先要"过"，同是"过"就取失配更小的。
    // （正常路径是"有一扇过就算过"—— 那是给实时/连续音用的；这里是**事后补判**，
    //   宁可挑证据最硬的那扇窗，也不要"碰巧过"。）
    for (const w of wins) {
      const spec = spectrumOf(absWindow(best.t * 1000 + w.atMs - w.winMs, w.winMs));
      let r = null;
      try {
        r = judgeNote({
          spec, sampleRate: SR, fftSize: spec.length * 2,   // 真 FFT 点数（产品页同）
          expectedMidi: e.expectedMidi, opts: optsFor(e.string, e.fret, e.level),
        });
      } catch (err) { r = null; }
      if (r == null) { if (judged == null) { judged = r; usedAt = w.atMs; } continue; }
      if (judged == null
          || (r.pass && !judged.pass)
          || (r.pass === judged.pass && r.fit != null && judged.fit != null
              && r.fit < judged.fit)) {
        judged = r;
        usedAt = w.atMs;
      }
    }
  }
  results.push({
    ...e,
    tStar: Number(best.t.toFixed(4)),
    rise: Number(best.rise.toFixed(2)),
    pre: Number(best.pre.toFixed(6)),
    post: Number(best.post.toFixed(6)),
    judged: best.rise >= RISE,
    // 「这一下算不算过」= 抬头够 + 判定过 + **置信度够**。
    // 为什么要多一道置信度：40ms 的 DFT 在低音弦上分不开半音（F2 87Hz vs F#2 92Hz 只差 5Hz，
    // 而 40ms 窗的主瓣有几十 Hz 宽），所以"期望音的基频带冒头"这条在低音上不特异 ——
    // 实测：六弦写高 1 品的负面靶子上，它把弹成 F2 的那一下判成了 F#2（fit 200 / margin 1.07）。
    // 引擎自己那本账写着"弹对的失配是 118~195"，所以这里给一道**绝对失配**上限；
    // 另给一道 margin 下限（两者都可从外面调，默认只在失配那道门上卡）。
    pass: !!(judged && judged.pass
      && (job.fitMax == null || (judged.fit != null && judged.fit <= Number(job.fitMax)))
      && (job.marginMin == null || (judged.margin != null
        && judged.margin >= Number(job.marginMin)))),
    heard: judged && judged.heard != null ? judged.heard : null,
    heardName: judged && judged.heard != null ? midiToName(judged.heard) : null,
    fit: judged && judged.fit != null ? Number(judged.fit.toFixed(0)) : null,
    margin: judged && judged.margin != null ? Number(judged.margin.toFixed(3)) : null,
    atMs: usedAt,
  });
}

fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify({ rise: RISE, results }, null, 1), 'utf8');
const hit = results.filter((x) => x.pass).length;
console.log(`兜底复核 ${results.length} 处：抬头够 ${results.filter((x) => x.judged).length}、判过 ${hit}（门限 ${RISE}×）`);
console.log(`结果已写到 ${outPath}`);
