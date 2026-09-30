// 临时探针：核对"喂给 judgeNote 的 fftSize 该是多少"。
//
// spectrumOf() 返回的是 mags（长度 = N/2），而 analysis.js 里 binHz = sr / fftSize、
// 峰频率 = pk.bin * binHz —— 也就是说 **fftSize 必须是真正做 FFT 的点数（N）**，
// 传 mags.length（N/2）会让 bin 宽翻倍。
//
// 用法：node tools/_probe_fft.mjs <jobdir>
// 拿该 job 的 pairs.json + judged.json，按同一扇窗重算两遍，对比 pass / heard / fit。

import fs from 'node:fs';
import path from 'node:path';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { judgeNote } = await import(M + 'judger.js');
const { spectrumOf } = await import(M + 'dsp.js');

const SR = 48000;
const WIN_MS = (8192 / SR) * 1000;
const OPEN = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };

const jobdir = process.argv[2];
const job = JSON.parse(fs.readFileSync(path.join(jobdir, 'pairs.json'), 'utf8'));
const judged = JSON.parse(fs.readFileSync(path.join(jobdir, 'judged.json'), 'utf8')).judged;
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

function optsFor(string, fret, level) {
  const lv = level == null ? 0.12 : level;
  if (string == null) return { maxOffset: null, bandLo: 0, bandHi: 0 };
  const open = OPEN[string];
  if (!open) return { maxOffset: 2, bandLo: 0, bandHi: 0 };
  const o = 440 * Math.pow(2, (open - 69) / 12);
  return { maxOffset: 2, rivalMargin: lv >= 0.10 ? 0.95 : 0.90,
    bandLo: o * Math.pow(2, -1 / 12), bandHi: o * Math.pow(2, 25 / 12) };
}

let both = 0, onlyHalf = 0, onlyFull = 0, n = 0;
let sameHeard = 0, halfMatchRec = 0, fullMatchRec = 0;
const detail = [];
for (let i = 0; i < job.pairs.length; i++) {
  const p = job.pairs[i], jd = judged[i];
  if (!jd) continue;
  const winMs = p.winMs != null ? Number(p.winMs) : WIN_MS;
  const atMs = p.atMs != null ? Number(p.atMs) : 90;
  const spec = spectrumOf(absWindow(p.t * 1000 + atMs - winMs, winMs));
  const opts = optsFor(p.string, p.fret, p.level);
  const half = judgeNote({ spec, sampleRate: SR, fftSize: spec.length, expectedMidi: p.expectedMidi, opts });
  const full = judgeNote({ spec, sampleRate: SR, fftSize: spec.length * 2, expectedMidi: p.expectedMidi, opts });
  n++;
  if (half.pass && full.pass) both++;
  else if (half.pass) onlyHalf++;
  else if (full.pass) onlyFull++;
  if (half.heard === full.heard) sameHeard++;
  if (half.pass === jd.pass) halfMatchRec++;
  if (full.pass === jd.pass) fullMatchRec++;
  if (detail.length < 12 && p.expectedMidi <= 48) {
    detail.push(`midi=${p.expectedMidi} s${p.string}f${p.fret} 记录pass=${jd.pass}`
      + ` ｜ half(fftSize=${spec.length}): pass=${half.pass} heard=${half.heard} fit=${Math.round(half.fit)}`
      + ` ｜ full(fftSize=${spec.length * 2}): pass=${full.pass} heard=${full.heard} fit=${Math.round(full.fit)}`);
  }
}
console.log(`配对数 ${n}`);
console.log(`两边都过 ${both} ｜ 只有 half 过 ${onlyHalf} ｜ 只有 full 过 ${onlyFull}`);
console.log(`heard 相同 ${sameHeard} ｜ 与记录一致：half ${halfMatchRec} / full ${fullMatchRec}`);
console.log('低音弦（midi≤48）样例：');
for (const d of detail) console.log('  ' + d);
