// 临时探针：把"我们桥的判定"和"跟弹产品页自己导出的判定"逐音对上，看哪种约定更像页面。
//
// 用法：node tools/_probe_vs_page.mjs <page-export.txt> <jobdirA> [jobdirB ...]
// 页面导出 = vc_gf/label24-latest.txt 里那行 "RESULT {...}"（onsets2/log 里有
//   每个起音的 exp / cand / candFit / candMargin）。

import fs from 'node:fs';
import path from 'node:path';

const [exportPath, ...jobdirs] = process.argv.slice(2);
const txt = fs.readFileSync(exportPath, 'utf8');
const line = txt.split(/\r?\n/).find((l) => l.startsWith('RESULT '));
if (!line) throw new Error('没找到 RESULT 行');
const page = JSON.parse(line.slice('RESULT '.length));
// log 里有逐音的 exp(数字) / cand / candFit / candMargin / result；
// onsets2 用的是 expect（音名）没给 fit，这里只用 log。
const log = (page.log || []).filter((e) => e.exp != null && e.candFit != null);
console.log(`页面导出：逐音记录 ${log.length} 条`);

for (const dir of jobdirs) {
  const judged = JSON.parse(fs.readFileSync(path.join(dir, 'judged.json'), 'utf8')).judged;
  let n = 0, heardSame = 0, passSame = 0;
  const diffs = [];
  for (const e of log) {
    // 找我们这边同一个起音 + 同一个期望音的配对
    // 页面的 log 里 t 是"判定那一刻"（起音 + 约 96ms），我们的 t 是起音时刻 → 容差放宽到 0.15s
    // （谱面上相邻音至少 0.45s，不会串台）
    const mine = judged.filter((x) => x.expectedMidi === e.exp && Math.abs(x.t - e.t) < 0.15);
    if (!mine.length) continue;
    // 同一次起音同一期望音可能有多条配对（不同格），取最贴页面 candFit 的那条来比
    let m = mine[0];
    if (e.candFit != null) {
      m = mine.reduce((a, b) => (Math.abs(b.fit - e.candFit) < Math.abs(a.fit - e.candFit) ? b : a));
    }
    n++;
    if (m.heard === e.cand) heardSame++;
    if (!!m.pass === (e.result === 'ok')) passSame++;
    if (m.fit != null && e.candFit != null) diffs.push(Math.abs(m.fit - e.candFit));
  }
  diffs.sort((a, b) => a - b);
  console.log(`${path.basename(dir)}：和页面同音同刻 ${n} 个 ｜ heard 一致 ${heardSame}`
    + ` ｜ pass 一致 ${passSame} ｜ |fit 差| 中位 ${diffs.length ? diffs[diffs.length >> 1] : '-'}`
    + ` 最大 ${diffs.length ? diffs[diffs.length - 1] : '-'}`);
}
