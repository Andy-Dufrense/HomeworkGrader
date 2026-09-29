// 作业检查的前端。流程按最终形态写：提交 → 轮询批改 → 出报告，
// 所以等真正的批改服务接上时，只换服务端，这个文件不用动。

const $ = (id) => document.getElementById(id);
const API = '/api';
let picked = null;          // 选中的文件
let pollTimer = null;
let meta = {};              // /api/assignment 回来的作业信息
let submittedLabel = '';    // 这次交的是什么（文件名 / 直链）
let currentAid = '';        // 当前选中的作业 id
let scoreApi = null;        // alphaTab 实例（画谱面用；换作业就销毁重建）

const el = {
  course: $('course'), verTag: $('verTag'),
  pick: $('pick'),
  scoreView: $('scoreView'), scoreHint: $('scoreHint'), scoreCard: $('scoreCard'),
  demoBanner: $('demoBanner'), demoBannerText: $('demoBannerText'),
  steps: $('steps'),
  title: $('title'), subtitle: $('subtitle'), passline: $('passline'),
  facts: $('facts'), source: $('source'), tips: $('tips'),
  drop: $('drop'), file: $('file'), chosen: $('chosen'), chosenName: $('chosenName'),
  clearFile: $('clearFile'), url: $('url'),
  submit: $('submit'), submitHint: $('submitHint'),
  progressCard: $('progressCard'), bar: $('bar'), stage: $('stage'), pipe: $('pipe'),
  resultCard: $('resultCard'), reportMeta: $('reportMeta'),
  noAudio: $('noAudio'), reportBody: $('reportBody'),
  score: $('score'), verdict: $('verdict'),
  coverage: $('coverage'), accuracy: $('accuracy'), counts: $('counts'),
  summary: $('summary'), process: $('process'), chart: $('chart'), issues: $('issues'),
  issueFold: $('issueFold'), foldSummary: $('foldSummary'),
  moreWrap: $('moreWrap'), moreCount: $('moreCount'), moreIssues: $('moreIssues'),
  again: $('again'), demoNote: $('demoNote'),
};

const STEP_ATTR = ['is-on', 'is-done'];

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// 步骤条：1 提交作业 → 2 自动批改 → 3 查看报告
function goStep(n) {
  [...el.steps.children].forEach((li) => {
    const i = Number(li.dataset.step);
    li.classList.remove(...STEP_ATTR);
    if (i < n) li.classList.add('is-done');
    if (i === n) li.classList.add('is-on');
  });
}

// 同时管 class 和 hidden：index.html 里初始是 hidden 属性，
// 而 .card 这类作者样式会盖掉浏览器默认的 [hidden]{display:none}。
function show(node, on) {
  node.classList.toggle('hidden', !on);
  node.hidden = !on;
}

function fmtSize(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n > 1024) return Math.round(n / 1024) + ' KB';
  return n + ' B';
}

function refreshSubmit() {
  const ok = !!(picked || el.url.value.trim());
  el.submit.disabled = !ok;
  el.submitHint.textContent = ok ? '提交后开始自动批改' : '请先选择文件，或填写音频直链';
}

function setPicked(file) {
  picked = file || null;
  if (picked) {
    el.chosenName.textContent = picked.name + '（' + fmtSize(picked.size) + '）';
    el.chosen.hidden = false;
  } else {
    el.chosen.hidden = true;
    el.file.value = '';
  }
  refreshSubmit();
}

// ── 作业信息（标准答案）────────────────────────────────────────────
function renderFacts(a, std) {
  const rows = [];
  rows.push(['标准答案', a.track || '—']);
  rows.push(['速度', a.bpm == null ? '—' : a.bpm + ' BPM']);
  rows.push(['乐曲长度', a.measures == null ? '—' : a.measures + ' 小节']);
  if (std && std.notes) rows.push(['本次要弹', std.notes + ' 个音']);
  if (std && std.bar_from) rows.push(['有音的小节', std.bar_from + '~' + std.bar_to]);
  if (std && std.crop) rows.push(['取段', std.crop]);
  el.facts.innerHTML = rows
    .map(([k, v]) => '<div><dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd></div>')
    .join('');
}

function applyAssignment(a, std, demo, real) {
  meta = a || {};
  el.course.textContent = a.course || '—';
  el.title.textContent = a.title || '—';
  el.subtitle.textContent = a.artist || '';
  el.passline.textContent = '及格线 ' + a.pass_line + ' 分';
  el.verTag.textContent = real ? '验证版 · 真数据' : '验证版';
  renderFacts(a, std || {});
  el.source.textContent = a.source || '标准答案用的是老师上传的谱面（.gp），不是某一次录音。';
  el.tips.innerHTML = (a.record_tips || []).map(t => '<li>' + esc(t) + '</li>').join('');
  el.demoBanner.hidden = false;
  el.demoBannerText.textContent = demo
    ? '批改引擎还没接上，页面里的数字来自 2026-09-24 的一次真机录音实测。'
    : '本页数字来自本机真机素材（真实录音）的批改结果；起音与判定用的是「老师跟练」同一份引擎代码。';
}

function loadAssignment(id) {
  const q = id ? ('?id=' + encodeURIComponent(id)) : '';
  return fetch(API + '/assignment' + q).then(r => r.json()).then((d) => {
    currentAid = d.id || id || '';
    applyAssignment(d.assignment, d.standard, d.demo, d.real);
    renderScore(currentAid, d.standard || {});
    return d;
  });
}

// ── 谱面：用 alphaTab 把老师那份 .gp 画出来（跟跟练页同一份库）──────────
function renderScore(aid, std) {
  if (!el.scoreView || !el.scoreHint) return;
  if (!window.alphaTab) {
    el.scoreHint.textContent = '谱面库没加载起来（vendor/alphaTab.min.js）。';
    return;
  }
  if (scoreApi && scoreApi.destroy) { try { scoreApi.destroy(); } catch (e) { /* ignore */ } }
  scoreApi = null;
  el.scoreView.innerHTML = '';
  el.scoreHint.textContent = '正在加载谱面…';
  const url = API + '/score?id=' + encodeURIComponent(aid || '');
  const display = {
    layoutMode: 'page',
    // 注意：这里要用 alphaTab 的**枚举名**（ScoreTab），写成 'score-tab' 会让
    // 渲染器的 this.profile 变 undefined，报 "Cannot read properties of undefined (reading 'has')"
    staveProfile: 'ScoreTab',                      // 五线谱 + 六线谱一起显示
    scale: window.innerWidth < 560 ? 0.6 : 0.9,
  };
  // 这次作业只取了一段（比如 Hey Jude 第 1~8 小节）→ 谱面也只画这一段
  if (std && std.crop && std.bar_from && std.bar_to) {
    display.startBar = std.bar_from;
    display.barCount = std.bar_to - std.bar_from + 1;
  }
  const api = new alphaTab.AlphaTabApi(el.scoreView, {
    file: url,
    core: { fontDirectory: './vendor/font/' },     // 字体在本地（CDN 被挡）
    display: display,
    player: { enablePlayer: false, enableCursor: false },
  });
  scoreApi = api;
  api.error.on((e) => {
    el.scoreHint.textContent = '谱面画不出来：' + ((e && (e.message || e)) || e);
  });
  api.scoreLoaded.on((s) => {
    el.scoreHint.textContent = ('谱面：' + (s.title || '—')
      + (s.artist ? ' — ' + s.artist : '')
      + '（' + s.tracks.length + ' 个声部，全曲 ' + s.masterBars.length + ' 小节，'
      + (std && std.crop ? '这里显示 ' + std.crop + '，' : '')
      + Math.round(s.tempo || 0) + ' BPM）');
  });
}

// 作业选择器：把 data/assignments 里登记好的作业列出来
fetch(API + '/assignments').then(r => r.json()).then(({ assignments, current }) => {
  if (!assignments || assignments.length < 2) return;
  el.pick.innerHTML = assignments.map(a =>
    '<option value="' + esc(a.id) + '">' + esc(a.title || a.id)
    + (a.has_report ? '（已批改）' : '') + '</option>').join('');
  el.pick.hidden = false;
  el.pick.value = current;
  el.pick.addEventListener('change', () => {
    show(el.resultCard, false);
    loadAssignment(el.pick.value);
  });
});

loadAssignment();

// ── 选文件 / 拖拽 ────────────────────────────────────────────────
el.drop.addEventListener('click', () => el.file.click());
el.file.addEventListener('change', () => setPicked(el.file.files[0] || null));
el.clearFile.addEventListener('click', () => setPicked(null));
['dragenter', 'dragover'].forEach(ev => el.drop.addEventListener(ev, e => {
  e.preventDefault(); el.drop.classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => el.drop.addEventListener(ev, e => {
  e.preventDefault(); el.drop.classList.remove('over');
}));
el.drop.addEventListener('drop', e => setPicked((e.dataTransfer.files || [])[0] || null));
el.url.addEventListener('input', refreshSubmit);

// ── 提交 → 轮询 ──────────────────────────────────────────────────
el.submit.addEventListener('click', async () => {
  el.submit.disabled = true;
  show(el.resultCard, false);
  show(el.progressCard, true);
  goStep(2);
  el.bar.style.width = '0%';
  el.stage.textContent = '上传中…';
  submittedLabel = picked ? picked.name : el.url.value.trim();
  try {
    let resp;
    const q = '?id=' + encodeURIComponent(currentAid || '');
    if (picked) {
      const fd = new FormData();
      fd.append('audio', picked, picked.name);
      resp = await fetch(API + '/submit' + q, { method: 'POST', body: fd });
    } else {
      resp = await fetch(API + '/submit' + q, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: el.url.value.trim() }),
      });
    }
    const j = await resp.json();
    poll(j.task_id);
  } catch (e) {
    el.stage.textContent = '提交失败：' + e.message;
    el.submit.disabled = false;
    goStep(1);
  }
});

function markPipe(i) {
  [...el.pipe.children].forEach((li, k) => {
    li.classList.toggle('is-done', k < i);
    li.classList.toggle('is-on', k === i);
  });
}

function poll(id) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const t = await (await fetch(API + '/task/' + id)).json();
    el.bar.style.width = (t.progress || 0) + '%';
    el.stage.textContent = (t.progress || 0) + '% · ' + (t.stage || '处理中…');
    if (typeof t.stage_index === 'number') markPipe(t.stage_index);
    if (t.status === 'completed') {
      clearInterval(pollTimer);
      show(el.progressCard, false);
      render(t.result);
    } else if (t.status === 'failed') {
      clearInterval(pollTimer);
      el.stage.textContent = '批改失败：' + (t.stage || '未知原因');
      el.submit.disabled = false;
      goStep(1);
    }
  }, 400);
}

// ── 出报告 ───────────────────────────────────────────────────────
function render(r) {
  show(el.resultCard, true);
  goStep(3);
  const a = r.assignment || meta;
  const std = r.standard || {};

  const metaRows = [
    ['作业', a.title || '—'],
    ['标准答案', a.track || '—'],
    ['本次要弹', std.notes ? std.notes + ' 个音' : '—'],
    ['提交内容', submittedLabel || '本机真机素材'],
  ];
  el.reportMeta.innerHTML = metaRows
    .map(([k, v]) => '<div><dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd></div>')
    .join('');

  // 这条作业还没有录音样例：只显示标准答案，不显示分数
  if (r.no_audio) {
    show(el.noAudio, true);
    show(el.reportBody, false);
    el.noAudio.textContent = r.note || '这条作业还没有录音样例。';
    el.demoNote.textContent = r.note || '';
    el.resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  show(el.noAudio, false);
  show(el.reportBody, true);

  el.score.textContent = r.score;
  el.score.style.color = r.passed ? 'var(--ok)' : 'var(--bad)';
  el.verdict.textContent = r.passed
    ? '通过（及格线 ' + r.pass_line + ' 分）'
    : '未通过（及格线 ' + r.pass_line + ' 分），按下面几处再练一遍';
  el.verdict.className = 'verdict ' + (r.passed ? 'ok' : 'no');
  el.coverage.textContent = r.coverage + '%';
  el.accuracy.textContent = r.accuracy + '%';

  const c = r.counts || {};
  const cells = [
    ['对', c.right, 'c-ok'], ['错', c.wrong, 'c-bad'], ['漏', c.missing, ''],
  ];
  if (c.extra) cells.push(['多弹', c.extra, 'c-bad']);
  el.counts.innerHTML = cells.map(([k, v, cls]) =>
    '<span class="' + cls + '">' + k + '<b>' + (v == null ? '—' : v) + '</b></span>'
  ).join('');

  // 总评（先说结论）
  el.summary.textContent = r.verdict_text || r.summary || '';

  // 过程提醒（节奏/停顿/快慢）：不占问题清单
  const proc = r.process || [];
  el.process.innerHTML = proc.map(t => '<li>' + esc(t) + '</li>').join('');
  show(el.process, proc.length > 0);

  // 问题清单：先展开"先改这几处"，其余折起来；整份过了就默认收起
  const key = r.key_issues || r.issues || [];
  const more = r.more_issues || [];
  const card = (it) => `
      <div class="issue">
        <div class="ih"><span>${esc(it.title)}</span><span class="t">${esc(issueTime(it))}</span></div>
        <div class="d">${esc(it.detail)}</div>
        <div class="f"><b>怎么改：</b>${esc(it.fix)}</div>
      </div>`;
  el.issues.innerHTML = key.length
    ? key.map(card).join('')
    : '<p class="stage">这一段没挑出明显问题。</p>';
  el.foldSummary.textContent = r.passed
    ? '这次的小问题（' + key.length + ' 处，不拦你过）'
    : '先改这几处（' + key.length + ' 处）';
  el.issueFold.open = !r.passed;
  el.moreCount.textContent = more.length;
  renderMoreIssues(more);
  el.demoNote.textContent = r.note;
  drawChart(r);
  el.resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 折叠区里那几条零星问题（只列位置，不展开改法 —— 免得报告太长）
function renderMoreIssues(more) {
  show(el.moreWrap, more.length > 0);
  el.moreIssues.innerHTML = (more || []).map(it =>
    '<div class="issue"><div class="ih"><span>' + esc(it.title) + '</span>'
    + '<span class="t">' + esc(it.t_audio == null ? '' : ('录音 ' + it.t_audio + ' 秒'))
    + '</span></div></div>').join('');
}

// 一处问题的时间：录音第几秒（判定听到的那一下）+ 谱面第几秒（对得上的那个音）
function issueTime(it) {
  const parts = [];
  if (it.t_audio != null) parts.push('录音 ' + it.t_audio + ' 秒');
  if (it.t_score != null) parts.push('谱面 ' + it.t_score + ' 秒');
  return parts.join(' · ') || '—';
}

// 谱面滚轴图：横轴 = 音频秒数，纵轴 = 第几弦（1 弦在最上面，和琴上一致）
function drawChart(r) {
  const notes = r.score_notes || [];
  const marks = r.error_marks || [];
  const OFF = (r.offset == null) ? 2.5 : Number(r.offset);
  const lastT = notes.length ? (+notes[notes.length - 1].t + OFF) : 30;
  const T0 = OFF, T1 = Math.max(OFF + 4, Math.min(60, Math.ceil(lastT)));
  const W = 720, H = 170, padL = 40, padR = 10, padT = 12, padB = 26;
  const x = (t) => padL + (t - T0) / (T1 - T0) * (W - padL - padR);
  const y = (s) => padT + (s - 1) / 5 * (H - padT - padB);
  const parts = [];

  // 六条弦 + 弦号
  for (let s = 1; s <= 6; s++) {
    parts.push(`<line x1="${padL}" y1="${y(s)}" x2="${W - padR}" y2="${y(s)}" stroke="#e8eef3" stroke-width="1"/>`);
    parts.push(`<text x="${padL - 6}" y="${y(s) + 3}" font-size="10" fill="#8b97a6" text-anchor="end">${s}弦</text>`);
  }
  // 小节线（76 BPM 4/4）
  const bpm = Number(meta.bpm) || 76;
  const bar = 60 / bpm * 4;
  for (let t = 0; t + OFF <= T1; t += bar) {
    const xx = x(t + OFF);
    if (xx < padL) continue;
    parts.push(`<line x1="${xx.toFixed(1)}" y1="${padT}" x2="${xx.toFixed(1)}" y2="${H - padB}" stroke="#bcd2ee" stroke-width="1" stroke-dasharray="3 3"/>`);
    parts.push(`<text x="${(xx + 3).toFixed(1)}" y="${H - 8}" font-size="9" fill="#9aa8b8">${Math.round(t / bar) + 1}</text>`);
  }
  // 谱面音
  const errT = new Set(marks.map(m => (+m.t).toFixed(2)));
  const errIdx = new Set(marks.filter(m => m.idx != null).map(m => +m.idx));
  notes.forEach(n => {
    const t = +n.t + OFF;
    if (t < T0 || t > T1) return;
    // 优先按"第几个音"对上（判定记录里给的就是这个）；没有才退回按时刻比
    const bad = (n.idx != null && errIdx.size) ? errIdx.has(+n.idx) : errT.has((+n.t).toFixed(2));
    const cx = x(t) - 5, cy = y(n.string) - 5;
    parts.push(`<rect x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" width="10" height="10" rx="3" fill="${bad ? '#b42318' : '#c3ced7'}"/>`);
  });
  // 时间轴
  [5, 10, 15, 20, 25].forEach(t => {
    parts.push(`<text x="${x(t).toFixed(1)}" y="${H - 8}" font-size="9" fill="#9aa8b8" text-anchor="middle">${t}s</text>`);
  });
  el.chart.innerHTML = parts.join('');
  el.chart.setAttribute('aria-label',
    `谱面共 ${notes.length} 个音，其中 ${marks.length} 个未对上。`);
}

el.again.addEventListener('click', () => {
  show(el.resultCard, false);
  show(el.progressCard, false);
  setPicked(null);
  el.url.value = '';
  submittedLabel = '';
  goStep(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

goStep(1);
refreshSubmit();
