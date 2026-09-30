// 临时探针：拿跟弹那边**手标真值**（vc_gf/tl-heyjude-label.json，24 个音）比两种 fftSize 约定。
//
// 用法：node tools/_probe_label.mjs <label.json> <audio.f32> [scale] [offsetMs]
// 打印：读数正确的个数、判过的个数、失配中位数。

import fs from 'node:fs';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { judgeNote } = await import(M + 'judger.js');
const { spectrumOf, midiToName } = await import(M + 'dsp.js');

const SR = 48000;
const WIN_MS = (8192 / SR) * 1000;
const OPEN = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };

const [labelPath, audioPath, scaleArg, offArg] = process.argv.slice(2);
const scale = scaleArg ? Number(scaleArg) : 1.0;
const offMs = offArg ? Number(offArg) : 0;

const lab = JSON.parse(fs.readFileSync(labelPath, 'utf8'));
const raw = fs.readFileSync(audioPath);
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

const res = { half: [], full: [] };
for (const n of lab.notes) {
  const tMs = n.t * scale * 1000 + offMs;
  const spec = spectrumOf(absWindow(tMs + 90 - WIN_MS, WIN_MS));
  for (const [k, mult] of [['half', 1], ['full', 2]]) {
    const r = judgeNote({ spec, sampleRate: SR, fftSize: spec.length * mult,
      expectedMidi: n.midi, opts: optsFor(n.string, n.fret, null) });
    res[k].push({ want: n.midi, heard: r.heard, pass: r.pass, fit: r.fit,
      wantName: midiToName(n.midi), heardName: r.heard == null ? null : midiToName(r.heard) });
  }
}
for (const k of ['half', 'full']) {
  const arr = res[k];
  const readOk = arr.filter((x) => x.heard === x.want).length;
  const pass = arr.filter((x) => x.pass).length;
  const fits = arr.map((x) => x.fit).filter((v) => v != null).sort((a, b) => a - b);
  const med = fits.length ? fits[Math.floor(fits.length / 2)] : null;
  console.log(`fftSize=${k === 'half' ? 'mags(4096)' : 'full(8192)'}：`
    + `读数对 ${readOk}/${arr.length} ｜ 判过 ${pass}/${arr.length} ｜ 失配中位 ${med == null ? '-' : Math.round(med)}`);
  const bad = arr.filter((x) => x.heard !== x.want);
  for (const b of bad.slice(0, 8)) {
    console.log(`    want=${b.wantName}(${b.want}) heard=${b.heardName}(${b.heard}) pass=${b.pass} fit=${Math.round(b.fit)}`);
  }
}
