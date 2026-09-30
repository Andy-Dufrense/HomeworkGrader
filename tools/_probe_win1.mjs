// 临时探针：同一个起音上，换几扇窗各判一次，看低音弦到底被哪扇窗读对/读错。
// 用法：node tools/_probe_win1.mjs <f32> <t> <expectedMidi> <string> <fret> [atMs]

import fs from 'node:fs';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { judgeNote } = await import(M + 'judger.js');
const { spectrumOf, midiToName } = await import(M + 'dsp.js');

const SR = 48000;
const OPEN = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };
const [file, tArg, midiArg, strArg, fretArg, atArg, prevArg] = process.argv.slice(2);
const t = Number(tArg), expectedMidi = Number(midiArg);
const string = Number(strArg), fret = Number(fretArg);
const atMs = atArg ? Number(atArg) : 90;
const prevMidi = prevArg ? Number(prevArg) : null;

const raw = fs.readFileSync(file);
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
  const open = OPEN[string];
  if (!open) return { maxOffset: 2, bandLo: 0, bandHi: 0 };
  const o = 440 * Math.pow(2, (open - 69) / 12);
  return { maxOffset: 2, rivalMargin: lv >= 0.10 ? 0.95 : 0.90,
    prevMidi: prevMidi == null ? undefined : prevMidi,
    bandLo: o * Math.pow(2, -1 / 12), bandHi: o * Math.pow(2, 25 / 12) };
}

console.log(`起音 ${t}s ｜ 期望 ${midiToName(expectedMidi)}(${expectedMidi}) s${string}f${fret} ｜ 判定时刻 +${atMs}ms`);
for (const w of [80, 170.67, 250, 341, 450, 550, 683]) {
  const from = t * 1000 + atMs - w;
  const spec = spectrumOf(absWindow(from, w));
  let r = null;
  try {
    r = judgeNote({ spec, sampleRate: SR, fftSize: spec.length * 2,
      expectedMidi, opts: optsFor(string, fret, 0.12) });
  } catch (e) { r = null; }
  if (!r) { console.log(`  窗 ${w}ms → 判不了`); continue; }
  console.log(`  窗 ${String(w).padEnd(7)}ms（bin ${(SR / (spec.length * 2)).toFixed(2)}Hz）`
    + ` → pass=${r.pass} heard=${r.heard == null ? '-' : midiToName(r.heard)}`
    + ` fit=${r.fit == null ? '-' : Math.round(r.fit)}`
    + ` margin=${r.margin == null ? '-' : r.margin.toFixed(3)}`);
}
