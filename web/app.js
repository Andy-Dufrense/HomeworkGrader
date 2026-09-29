// 作业检查 demo 的前端。流程按最终形态写：提交 → 轮询 task → 出结果，
// 所以等真批改引擎接上时，只换服务端就行，这个文件不用动。

const $ = (id) => document.getElementById(id);
const API = '/api';
let picked = null;          // 选中的文件
let pollTimer = null;
let meta = {};              // /api/assignment 回来的作业信息

const el = {
  course: $('course'), demoBanner: $('demoBanner'), demoBannerText: $('demoBannerText'),
  steps: $('steps'),
  title: $('title'), subtitle: $('subtitle'), passline: $('passline'),
  track: $('track'), bpm: $('bpm'), measures: $('measures'), source: $('source'),
  tips: $('tips'),
  drop: $('drop'), file: $('file'), chosen: $('chosen'), chosenName: $('chosenName'),
  clearFile: $('clearFile'), url: $('url'),
  submit: $('submit'), submitHint: $('submitHint'),
  progressCard: $('progressCard'), bar: $('bar'), stage: $('stage'),
  resultCard: $('resultCard'), score: $('score'), verdict: $('verdict'),
  coverage: $('coverage'), accuracy: $('accuracy'), counts: $('counts'),
  summary: $('summary'), chart: $('chart'), issues: $('issues'),
  issueCount: $('issueCount'), again: $('again'), demoNote: $('demoNote'),
};

const STEP_ATTR = ['is-on', 'is-done'];

// 步骤条：1 交作业 → 2 老师批改 → 3 看结果
function goStep(n) {
  [...el.steps.children].forEach((li) => {
    const i = Number(li.dataset.step);
    li.classList.remove(...STEP_ATTR);
    if (i < n) li.classList.add('is-done');
    if (i === n) li.classList.add('is-on');
  });
}

// 同时管 class 和 hidden 属性：index.html 里初始是 hidden 属性，
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
  el.submitHint.textContent = ok
    ? (picked ? '就交这个文件' : '就交这条链接')
    : '先选一个文件，或贴一条直链';
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

// ── 作业信息 ─────────────────────────────────────────────────────────
fetch(API + '/assignment').then(r => r.json()).then(({ assignment: a, demo, real }) => {
  meta = a;
  el.course.textContent = a.course;
  el.title.textContent = a.title;
  el.subtitle.textContent = a.artist;
  el.passline.textContent = '及格线 ' + a.pass_line;
  el.track.textContent = a.track;
  el.bpm.textContent = (a.bpm == null ? '—' : a.bpm + ' BPM');
  el.measures.textContent = (a.measures == null ? '—' : a.measures + ' 小节');
  el.source.textContent = a.source || '标准答案用的是老师上传的谱面（.gp），不是某一次录音。';
  el.tips.innerHTML = a.record_tips.map(t => '<li>' + t + '</li>').join('');
  el.demoBanner.hidden = false;
  el.demoBanner.classList.toggle('is-real', !demo);
  el.demoBannerText.textContent = demo
    ? '批改引擎还没接上，页面里的数字来自 2026-09-24 那次真机录音实测。'
    : '真数据：这条结果是从真实录音跑出来的，判定用的是跟弹那一份引擎代码。';
});

// ── 选文件 / 拖拽 ────────────────────────────────────────────────────
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

// ── 提交 → 轮询 ──────────────────────────────────────────────────────
el.submit.addEventListener('click', async () => {
  el.submit.disabled = true;
  show(el.resultCard, false);
  show(el.progressCard, true);
  goStep(2);
  el.bar.style.width = '0%';
  el.stage.textContent = '上传中…';
  try {
    let resp;
    if (picked) {
      const fd = new FormData();
      fd.append('audio', picked, picked.name);
      resp = await fetch(API + '/submit', { method: 'POST', body: fd });
    } else {
      resp = await fetch(API + '/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: el.url.value.trim() }),
      });
    }
    const j = await resp.json();
    poll(j.task_id);
  } catch (e) {
    el.stage.textContent = '没提交上去：' + e.message;
    el.submit.disabled = false;
    goStep(1);
  }
});

function poll(id) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const t = await (await fetch(API + '/task/' + id)).json();
    el.bar.style.width = (t.progress || 0) + '%';
    el.stage.textContent = (t.progress || 0) + '% · ' + (t.stage || '处理中…');
    if (t.status === 'completed') {
      clearInterval(pollTimer);
      show(el.progressCard, false);
      render(t.result);
    } else if (t.status === 'failed') {
      clearInterval(pollTimer);
      el.stage.textContent = '批改没成功：' + (t.stage || '未知原因');
      el.submit.disabled = false;
      goStep(1);
    }
  }, 400);
}

// ── 出结果 ───────────────────────────────────────────────────────────
function render(r) {
  show(el.resultCard, true);
  goStep(3);
  el.score.textContent = r.score;
  el.score.style.color = r.passed ? 'var(--ok)' : 'var(--bad)';
  el.verdict.textContent = r.passed
    ? '通过（及格线 ' + r.pass_line + ' 分）'
    : '这次还没过（及格线 ' + r.pass_line + ' 分），照着下面的地方再来一遍';
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

  el.summary.textContent = r.summary;
  el.issueCount.textContent = r.issues.length;
  el.issues.innerHTML = r.issues.length
    ? r.issues.map(it => `
      <div class="issue">
        <div class="ih"><span>${it.title}</span><span class="t">${issueTime(it)}</span></div>
        <div class="d">${it.detail}</div>
        <div class="f"><b>怎么改：</b>${it.fix}</div>
      </div>`).join('')
    : '<p class="stage">这一段没挑出明显问题。</p>';
  el.demoNote.textContent = r.note;
  drawChart(r);
  el.resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  // 整体位移：真实批改结果会给 align.offset；没有就用 demo 那次的 2.5s
  const OFF = (r.offset == null) ? 2.5 : Number(r.offset);
  const lastT = notes.length ? (+notes[notes.length - 1].t + OFF) : 30;
  const T0 = OFF, T1 = Math.max(OFF + 4, Math.min(60, Math.ceil(lastT)));
  const W = 720, H = 170, padL = 40, padR = 10, padT = 12, padB = 26;
  const x = (t) => padL + (t - T0) / (T1 - T0) * (W - padL - padR);
  const y = (s) => padT + (s - 1) / 5 * (H - padT - padB);
  const parts = [];
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

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
    parts.push(`<line x1="${xx.toFixed(1)}" y1="${padT}" x2="${xx.toFixed(1)}" y2="${H - padB}" stroke="#9fd0de" stroke-width="1" stroke-dasharray="3 3"/>`);
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
    parts.push(`<rect x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" width="10" height="10" rx="3" fill="${bad ? '#c0392b' : '#c3ced7'}"/>`);
  });
  // 时间轴
  [5, 10, 15, 20, 25].forEach(t => {
    parts.push(`<text x="${x(t).toFixed(1)}" y="${H - 8}" font-size="9" fill="#9aa8b8" text-anchor="middle">${t}s</text>`);
  });
  el.chart.innerHTML = parts.join('');
  el.chart.setAttribute('aria-label', esc(
    `谱面共 ${notes.length} 个音，其中 ${marks.length} 个没对上。`));
}

el.again.addEventListener('click', () => {
  show(el.resultCard, false);
  show(el.progressCard, false);
  setPicked(null);
  el.url.value = '';
  goStep(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

goStep(1);
refreshSubmit();
