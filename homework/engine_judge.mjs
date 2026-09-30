// 作业检查 · 判定桥：给一批「配对好的 (起音时刻, 谱面音)」逐个跑跟弹的判定。
//
// 学的是**跟弹产品页的判定做法**（2026-09-29 对齐过代码，一行不改地照它来）：
//   · 用哪扇窗：**判定这一刻往回 170ms**（判定在起音后 90ms，所以窗 = [起音−80ms, 起音+90ms]）
//     8192 点 @48k = 170.67ms。产品页原话："spec 就是判定这一刻往回 170ms 那扇窗，
//     也就是 test/gt-notes.mjs 里验过的那扇"（judge-loop.js 判那段）。
//     ⚠ 以前这里用的是"以起音为中心、前后各 10~40ms 相减"的实验窗 —— 那是产品页里
//     默认**关着**的开关（__judgeAttackDiff），数字和产品对不上，2026-09-29 已改正。
//   · 传给 judgeNote 的 opts 也照抄：谱面给了弦品就把候选收到 ±2 品；按电平决定
//     "本音要领先多少"（≥0.10 要 1.05，轻音 0.90）；频带按该弦空弦音算。
//   · 判定算法本身是 engine/judger.js 的 judgeNote —— 不重写、不调参。
//
// 输入 JSON：
//   { "audio": "...f32", "pairs": [ { "t": 1.23, "expectedMidi": 48,
//                                    "string": 2, "fret": 1, "level": 0.17 }, ... ] }
// 输出 JSON：{ ..., "judged": [ { t, expectedMidi, expectedName, pass, heard, heardName, ... } ] }

import fs from 'node:fs';
import path from 'node:path';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { judgeNote } = await import(M + 'judger.js');
const { spectrumOf, midiToName } = await import(M + 'dsp.js');
const { strongestF0InBand } = await import(M + 'analysis.js');
// 诊断（HG_READ=1）：按"起音 → 读这一下期望音频带里最响的那条基频"的路子，多给一条正面证据
const READ = process.env.HG_READ === '1';

const SR = 48000;
const JUDGE_AT_MS = 90;          // 起音后 90ms 出结论（产品页同）
const WIN_MS = 8192 / SR * 1000; // 170.67ms
// 多音格（同一格≥2根弦）可以单独指定"起音后多久判"：小琶音三根弦相隔约 100ms，
// 只在 90ms 判会读到"第三根还没响"的谱（2026-09-30 实测：9 11 11 那条 8/12 → 170ms 12/12）。
// 单音格不给这个键，就是上面的 90ms，行为与以前一字不差。

// 六根弦的空弦音高（产品页 judge-loop.js 里的同一张表）
const OPEN = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };

// 扫阈值用（不设就是照抄产品页/引擎的默认值）
const RIVAL_MARGIN = process.env.HG_RIVAL_MARGIN ? Number(process.env.HG_RIVAL_MARGIN) : null;
const FIT_MAX = process.env.HG_FIT_MAX ? Number(process.env.HG_FIT_MAX) : null;
// 诊断用：判定窗长度（毫秒）。默认 8192/48k = 170.67ms。低音弦要更长的窗才分得出半音。
const WIN_OVERRIDE = process.env.HG_WIN_MS ? Number(process.env.HG_WIN_MS) : null;

const inPath = process.argv[2];
const outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error('用法：node homework/engine_judge.mjs <pairs.json> <out.json>');
  process.exit(2);
}

const job = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const raw = fs.readFileSync(job.audio);
const AUDIO = new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4);

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

// 和产品页同一套 opts（见 judge-loop.js 里 judgeNote 的调用处）
function optsFor(string, fret, level) {
  const lv = level == null ? 0.12 : level;
  if (string == null) return { maxOffset: null, bandLo: 0, bandHi: 0,
    fitMax: FIT_MAX != null ? FIT_MAX : undefined };
  const open = OPEN[string];
  if (!open) return { maxOffset: 2, bandLo: 0, bandHi: 0 };
  const o = 440 * Math.pow(2, (open - 69) / 12);
  return {
    maxOffset: 2,
    // 响的那一档 1.05 → **0.95**（2026-09-30 扫表定的，见本文件开头注释与 思路.md §11.10）：
    //   1.05 时低音弦（F2/G2/A2）"本音只领先邻居一点点"就被判错；0.95 仍然要求
    //   本音领先对手，且**故意写错一个音的靶子照样报错**（75 分）。
    //   轻的那一档是产品页的 0.90，不动。
    rivalMargin: RIVAL_MARGIN != null ? RIVAL_MARGIN : (lv >= 0.10 ? 0.95 : 0.90),
    fitMax: FIT_MAX != null ? FIT_MAX : undefined,
    bandLo: o * Math.pow(2, -1 / 12),
    bandHi: o * Math.pow(2, 25 / 12),
  };
}

const judged = [];
for (const p of job.pairs) {
  // 判定用哪几扇窗：**默认就是产品页那一扇**（起音后 90ms、往回 170.67ms）。
  //   * p.atMsList 给了就逐个试，**有一个过就算过**（多音格用：小琶音要等到弦都响起来，
  //     同时响的双音反而 90ms 更准）；
  //   * p.wins 给了就按 [{atMs, winMs}] 逐扇试（作业检查自己的"按音换窗"用：低音弦要更长的
  //     窗才分得出半音，但**长窗贴在音符自己的时间片里、从起音后 30ms 往后量**，
  //     不许往回伸长 —— 往回伸长就把上一个音（更响的那一段）装进来了）。
  const defWinMs = p.winMs != null ? Number(p.winMs)
    : (WIN_OVERRIDE != null ? WIN_OVERRIDE : WIN_MS);
  const wins = (p.wins && p.wins.length)
    ? p.wins.map((x) => ({ atMs: Number(x.atMs), winMs: Number(x.winMs) }))
    : ((p.atMsList && p.atMsList.length)
      ? p.atMsList.map((a) => ({ atMs: Number(a), winMs: defWinMs }))
      : [{ atMs: p.atMs != null ? Number(p.atMs) : JUDGE_AT_MS, winMs: defWinMs }]);
  let r = null, usedAt = wins[0].atMs;
  let lastSpec = null;          // 诊断（HG_READ）用：最后一扇窗的频谱
  for (const w of wins) {
    const atMs = w.atMs, winMs = w.winMs;
    const spec = spectrumOf(absWindow(p.t * 1000 + atMs - winMs, winMs));
    lastSpec = spec;
    let res = null;
    try {
      res = judgeNote({
        spec, sampleRate: SR, fftSize: spec.length,
        expectedMidi: p.expectedMidi,
        opts: optsFor(p.string, p.fret, p.level),
      });
    } catch (e) {
      res = null;
    }
    if (r === null) { r = res; usedAt = atMs; }
    if (res && res.pass) { r = res; usedAt = atMs; break; }
  }
  let readHz = null, readCents = null;
  if (READ) {
    const f0 = 440 * Math.pow(2, (p.expectedMidi - 69) / 12);
    const rr = strongestF0InBand(lastSpec, SR, lastSpec.length,
      f0 * Math.pow(2, -2 / 12), f0 * Math.pow(2, 2 / 12));
    if (rr && rr.hz > 0) { readHz = rr.hz; readCents = 1200 * Math.log2(rr.hz / f0); }
  }
  const heard = r && r.heard != null ? r.heard : null;
  judged.push({
    t: p.t,
    expectedMidi: p.expectedMidi,
    expectedName: midiToName(p.expectedMidi),
    string: p.string == null ? null : p.string,
    fret: p.fret == null ? null : p.fret,
    pass: !!(r && r.pass),
    heard,
    heardName: heard == null ? null : midiToName(heard),
    fit: r && r.fit != null ? Number(r.fit.toFixed(0)) : null,
    margin: r && r.margin != null ? Number(r.margin.toFixed(3)) : null,
    atMs: usedAt, readHz, readCents,
  });
}

const out = { ...job, judged };
fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out, null, 1), 'utf8');

const ok = judged.filter((x) => x.pass).length;
console.log(`判定 ${judged.length} 个配对：过 ${ok} ｜ 没过 ${judged.length - ok}`);
console.log(`结果已写到 ${outPath}`);
