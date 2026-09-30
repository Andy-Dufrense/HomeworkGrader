// 临时探针：按 engine_bridge 的同一套帧循环跑一段，把 decideOnset 的**逐帧**输入与结论打出来。
// 目的：查"这一段为什么没被算成起音"。
//
// 用法：node tools/_probe_gate.mjs <f32> <t0> <t1>

import fs from 'node:fs';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { decideOnset } = await import(M + 'onset.js');
const { fluxRelOf, hfFluxRelOf, hfBandRiseOf, lowBandRiseOf, shapeFluxOf, resetAnalysis } =
  await import(M + 'analysis.js');
const { CFG, CAPTURE } = await import(M + 'config.js');

const SR = 48000, HOP = 16;
const [file, t0s, t1s] = process.argv.slice(2);
const t0 = Number(t0s), t1 = Number(t1s);

const raw = fs.readFileSync(file);
const AUDIO = new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4);
const T_END = (AUDIO.length / SR) * 1000;

function frameAt(tMs, n) {
  const end = Math.floor((tMs / 1000) * SR);
  const from = Math.max(0, end - n);
  const buf = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const j = from + i;
    buf[i] = (j >= 0 && j < AUDIO.length) ? AUDIO[j] : 0;
  }
  return buf;
}
const rms = (a, from, n) => {
  let s = 0;
  for (let i = 0; i < n; i++) { const v = a[from + i]; s += v * v; }
  return Math.sqrt(s / n);
};

resetAnalysis();
let floor = 0.001, frames = 0, lastOnsetMs = -1e9, refractoryUntilMs = -1e9;
const levelHist = [];
console.log('t       lv      gate    flux   hfFlux  hfBand  loBand  shape   上升   → 结论');
for (let t = 0; t < T_END; t += HOP) {
  const buf = frameAt(t, CAPTURE);
  const lv = rms(buf, buf.length - 1024, 1024);
  frames++;
  if (frames <= 30) floor += (Math.min(lv, 0.05) * 0.9 - floor) * 0.3;
  else if (lv < floor) floor = floor * 0.9 + lv * 0.1;
  else floor = Math.min(floor * 1.0003 + 1e-7, 0.06);
  floor = Math.max(floor, 0.0005);
  const gate = Math.max(CFG.absFloor, floor * CFG.onsetSensitivity);
  const flux = fluxRelOf(buf), hfFlux = hfFluxRelOf(buf);
  const hfBandRise = hfBandRiseOf(buf), lowBandRise = lowBandRiseOf(buf);
  const shapeFlux = shapeFluxOf(buf);
  const prevLv = levelHist.length ? levelHist[levelHist.length - 1] : 0;
  const lagged = levelHist.length >= 3 ? levelHist[levelHist.length - 3] : 0;
  const g = decideOnset({
    phase: 'waiting', now: t, refractoryUntilMs, lastOnsetMs,
    minGapCfg: CFG.minGapMs, lv, prevLv, lagged, gate, floor,
    flux, hfFlux, hfBandRise, lowBandRise, shapeFlux, repeatSame: false,
  });
  levelHist.push(lv);
  if (levelHist.length > 10) levelHist.shift();
  if (t / 1000 >= t0 && t / 1000 <= t1) {
    console.log(`${(t / 1000).toFixed(3)}  ${lv.toFixed(4)}  ${gate.toFixed(4)}`
      + `  ${flux.toFixed(3)}  ${hfFlux.toFixed(3)}  ${(hfBandRise || 0).toFixed(2)}`
      + `  ${(lowBandRise || 0).toFixed(2)}  ${shapeFlux.toFixed(3)}`
      + `  ${(lv / (lagged + 1e-9)).toFixed(2)}  → ${g.onset ? '★起音' : (g.why || '-')}`);
  }
  if (g.onset) { refractoryUntilMs = t + 110; lastOnsetMs = t; }
}
