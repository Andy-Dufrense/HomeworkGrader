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
// ── fftSize 必须是"真正做 FFT 的点数"，不是 mags 的个数 ─────────────────────────
// spectrumOf(buf) 返回的是 mags（长度 = N/2）；analysis.js 里 binHz = sr / fftSize、
// 峰频率 = pk.bin * binHz。产品页那处调用（judge-loop.js:996）传的正是 PEAK_N = 8192
// （spec 也是 spectrumOf 出来的、长度 4096）。
// 我们原来传的是 spec.length（4096）→ bin 宽翻倍成 11.72Hz（product 5.86Hz），
// 六弦一个半音只有 5Hz，于是低音弦被读成邻居 —— 这就是"隔壁实时都没有、我们有"的真因。
// 诊断开关：HG_FFT_MAGS=1 退回老写法（复现问题用）。
const FFT_MAGS = process.env.HG_FFT_MAGS === '1';
// 判定时要不要多试一档"只判新起来的那部分"（用户的起音思路，见 risingSpec）。
// ⚠ 默认**关**：实测它当"判定输入"会把负面证据也一起压小 ——
//   错谱靶子 75 → 92、六弦写高1品 90 → 92/95（两种写法都试过），
//   跟隔壁 9-24 记的"差分谱当判定输入 → 错音过得更松"是同一个机制。
//   它只适合当"这一下有没有新拨"的**证据**（起音层做的就是这个），不能替代判定。
//   要看数字：HG_RISING=1（可选 HG_RISING_MODE=mask|diff，默认 mask）。
const RISING_ON = process.env.HG_RISING === '1';
const RISING_MODE = process.env.HG_RISING_MODE || 'mask';
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

function padTo(buf, n) {
  const o = new Float32Array(n);
  o.set(buf.subarray(0, Math.min(buf.length, n)));
  return o;
}

// ── 只判"这一下新起来的"那部分（用户的起音思路，2026-09-30 用户重申）─────────
// 用户原话：「上一个音此时在减弱，新起的音正在长到峰值并开始减弱，我们只对这个新起音判断」。
// 做法：pre = [起音−40ms, 起音−10ms]、post = [起音+10ms, 起音+40ms]（中间留 10ms 空档避开
// 起音瞬态那一下的宽带噪声），两边都**零填充到 8192** 保证低音弦的分辨率，
// 逐频点相减、**只留正的那部分**（在减弱的余响永远是负的 → 被抹掉）。
// 于是判定输入里"只剩这一下新加进来的东西"：上一个音的和弦余响不再参与候选比较。
const DIFF_PRE_FROM = -40, DIFF_PRE_LEN = 30;
const DIFF_POST_FROM = 10, DIFF_POST_LEN = 30;
function risingSpec(tMs) {
  const post = spectrumOf(padTo(absWindow(tMs + DIFF_POST_FROM, DIFF_POST_LEN), 8192));
  const pre = spectrumOf(padTo(absWindow(tMs + DIFF_PRE_FROM, DIFF_PRE_LEN), 8192));
  const out = new Float32Array(post.length);
  for (let i = 0; i < post.length; i++) {
    // 两种写法（HG_RISING_MODE）：
    //   "diff" = 只留增量（post−pre）；
    //   "mask" = 在涨的那些频点留**完整的 post 值**（结构不被压扁）——
    //            用户的"只判新起音那部分"更贴近这个：减弱的（post<pre）一律抹掉。
    //            实测 "diff" 会把负证据也一起压小（六弦写高1品那个负面靶子从 错3 掉到 错1），
    //            跟隔壁 9-24 记的"差分谱当判定输入 → 错音过得更松"是同一个机制。
    out[i] = RISING_MODE === 'mask'
      ? (post[i] > pre[i] ? post[i] : 0)
      : (post[i] - pre[i] > 0 ? post[i] - pre[i] : 0);
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
  // "只判新起来的那部分"那一档（用户的起音思路）：放在最后再试一次
  const attempts = wins.map((w) => ({ atMs: w.atMs, winMs: w.winMs, rising: false }));
  if (RISING_ON && p.rising !== false && p.t != null) {
    attempts.push({ atMs: JUDGE_AT_MS, winMs: 0, rising: true });
  }
  let r = null, usedAt = attempts[0].atMs;
  let lastSpec = null;          // 诊断（HG_READ）用：最后一扇窗的频谱
  for (const w of attempts) {
    const atMs = w.atMs, winMs = w.winMs;
    const spec = w.rising
      ? risingSpec(p.t * 1000)
      : spectrumOf(absWindow(p.t * 1000 + atMs - winMs, winMs));
    lastSpec = spec;
    let res = null;
    try {
      res = judgeNote({
        spec, sampleRate: SR, fftSize: FFT_MAGS ? spec.length : spec.length * 2,
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
