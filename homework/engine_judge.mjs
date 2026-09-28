// 作业检查 · 判定桥：给一批「已经对齐好的 (时刻, 期望音)」逐个跑跟弹的判定。
//
// 为什么不"每一响读一个音名"：
//   在"和弦一直在响 + 分解和弦"的材料上，绝对读数不可用（本机实测：
//   60 个起音里 54 个读不出成串的基频；跟弹那边也量到"琶音 0/52"）。
//   跟弹产品页真正用的判据是反过来问：**我要的那个音，在不在这一下的差分谱里**
//   （matchNoteByCandidates → decideByCandidates）。这里就照抄这条产品逻辑，
//   代码仍然只有跟弹那一份（judger.js / analysis.js / dsp.js），本文件只做编排。
//
// 输入 JSON：
//   { "audio": "...f32", "band": [loHz, hiHz],
//     "pairs": [ { "t": 1.23, "expectedMidi": 48 }, ... ] }
// 输出 JSON：
//   { ..., "judged": [ { t, expectedMidi, pass, heard, heardName, fit, margin, octaveBelow } ] }
//
// 用法：
//   node homework/engine_judge.mjs <pairs.json> <out.json>

import fs from 'node:fs';
import path from 'node:path';

const M = 'file:///E:/GuitarFollowLab/backend/engine/';
const { diffMags } = await import(M + 'analysis.js');
const { spectrumOf, hzToMidi, midiToName } = await import(M + 'dsp.js');
const { judgeNote } = await import(M + 'judger.js');

const SR = 48000;
const PRE_FROM_MS = -40, PRE_LEN_MS = 30;    // 以起音为中心（同 engine_bridge.mjs）
const POST_FROM_MS = 10, POST_LEN_MS = 30;

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

const judged = [];
for (const p of job.pairs) {
  const tMs = p.t * 1000;
  const post = spectrumOf(absWindow(tMs + POST_FROM_MS, POST_LEN_MS));
  const pre = spectrumOf(absWindow(tMs + PRE_FROM_MS, PRE_LEN_MS));
  const diff = diffMags(post, pre);
  const j = judgeNote({
    spec: diff, sampleRate: SR, fftSize: post.length,
    expectedMidi: p.expectedMidi, opts: {},
  });
  const heardMidi = j.heard == null ? null : j.heard;
  judged.push({
    t: p.t,
    expectedMidi: p.expectedMidi,
    expectedName: midiToName(p.expectedMidi),
    pass: !!j.pass,
    heard: heardMidi,
    heardName: heardMidi == null ? null : midiToName(heardMidi),
    fit: j.fit == null ? null : Number(j.fit.toFixed(0)),
    margin: j.margin == null ? null : Number(j.margin.toFixed(3)),
    octaveBelow: j.octaveBelow || null,
  });
}

const out = { ...job, judged };
fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out, null, 1), 'utf8');

const ok = judged.filter((x) => x.pass).length;
console.log(`判定 ${judged.length} 个音：过 ${ok} ｜ 没过 ${judged.length - ok}`);
console.log(`结果已写到 ${outPath}`);
