// 作业检查的前端。流程按最终形态写：提交 → 轮询批改 → 出报告，
// 所以等真正的批改服务接上时，只换服务端，这个文件不用动。

const $ = (id) => document.getElementById(id);
const API = '/api';
let picked = null;          // 选中的文件
let pollTimer = null;
let meta = {};              // /api/assignment 回来的作业信息
let submittedLabel = '';    // 这次交的是哪个文件（页面只收上传的文件）
let currentAid = '';        // 当前选中的作业 id
let currentStd = {};        // 当前作业的标准（谱面信息）
let scoreApi = null;        // alphaTab 实例（画谱面用；换作业就销毁重建）
let assignReady = null;     // 作业信息加载的 Promise（提交前等它，别用空作业 id 去提交）

const el = {
  course: $('course'), verTag: $('verTag'),
  pick: $('pick'), followLink: $('followLink'),
  scoreSection: $('scoreSection'), scoreWrap: $('scoreWrap'),
  scoreView: $('scoreView'), scoreHint: $('scoreHint'), scoreMarks: $('scoreMarks'),
  demoBanner: $('demoBanner'), demoBannerText: $('demoBannerText'),
  steps: $('steps'),
  title: $('title'), subtitle: $('subtitle'), passline: $('passline'),
  facts: $('facts'), source: $('source'), tips: $('tips'),
  drop: $('drop'), file: $('file'), chosen: $('chosen'), chosenName: $('chosenName'),
  clearFile: $('clearFile'),
  submit: $('submit'), submitHint: $('submitHint'),
  progressCard: $('progressCard'), bar: $('bar'), stage: $('stage'), pipe: $('pipe'),
  resultCard: $('resultCard'), reportMeta: $('reportMeta'),
  noAudio: $('noAudio'), reportBody: $('reportBody'),
  score: $('score'), verdict: $('verdict'),
  coverage: $('coverage'), accuracy: $('accuracy'), counts: $('counts'),
  summary: $('summary'), process: $('process'), issues: $('issues'),
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
  el.submit.disabled = !picked;
  el.submitHint.textContent = picked ? '提交后开始自动批改' : '请先选择录音文件';
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

function applyAssignment(a, std, demo, real, followUrl) {
  meta = a || {};
  if (el.followLink) {
    el.followLink.href = followUrl || '#';
    el.followLink.hidden = !followUrl;
  }
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
    applyAssignment(d.assignment, d.standard, d.demo, d.real, d.follow_url);
    currentStd = d.standard || {};
    return d;
  });
}

// ── 谱面：用 alphaTab 把老师那份 .gp 画出来（跟跟练页同一份库）──────────
function renderScore(std, errors) {
  if (!el.scoreView || !el.scoreHint) return;
  std = std || {};
  errors = errors || [];
  if (!window.alphaTab) {
    el.scoreHint.textContent = '谱面库没加载起来（vendor/alphaTab.min.js）。';
    return;
  }
  if (scoreApi && scoreApi.destroy) { try { scoreApi.destroy(); } catch (e) { /* ignore */ } }
  scoreApi = null;
  el.scoreView.innerHTML = '';
  el.scoreMarks.innerHTML = '';
  el.scoreHint.textContent = '正在加载谱面…';
  const url = API + '/score?id=' + encodeURIComponent(currentAid || '');
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
  let beats = [];
  let segNotes = [];
  api.scoreLoaded.on((s) => {
    const seg = segmentBeats(s, std);
    beats = seg.beats;
    segNotes = seg.notes;
    window.__hgBeats = beats;        // 排查用（谱面拍点表）
    window.__hgSegNotes = segNotes;
    el.scoreHint.dataset.base = ('谱面：' + (s.title || '—')
      + (s.artist ? ' — ' + s.artist : '')
      + '（' + s.tracks.length + ' 个声部，全曲 ' + s.masterBars.length + ' 小节'
      + (std.crop ? '，这里显示 ' + std.crop : '')
      + '）');
    el.scoreHint.textContent = el.scoreHint.dataset.base + '；红框就是没对上的那几下。';
  });
  const paint = () => drawMarks(beats, segNotes, errors);
  window.__hgErrors = errors;
  if (api.renderFinished) api.renderFinished.on(paint);
  setTimeout(paint, 900);
}

// 这一段谱面里的所有拍 + 所有"要弹的音"（顺序跟参考时间轴对齐）
//
// 为什么除了拍还要单独列一遍音：参考时间轴（gp_timeline.py）会把延音并进上一个音、
// 跳过休止和装饰音；alphaTab 的模型里延音是单独一拍。两边"第几个音"才对得齐，
// 拿时间对会因为这份 .gp 开头那个 1/4 小节（前奏弱起）两边解释不一样而错位。
function segmentBeats(score, std) {
  const idx = (std.track_index == null) ? 0 : std.track_index;
  const track = (score.tracks && (score.tracks[idx] || score.tracks[0]));
  const staff = track && track.staves && track.staves[0];
  if (!staff) return { beats: [], notes: [] };
  const tps = 60 / (score.tempo || 80) / 960;     // 秒 / tick
  const beats = [], notes = [];
  const from = (std.crop && std.bar_from) ? std.bar_from : 1;
  const to = (std.crop && std.bar_to) ? std.bar_to : staff.bars.length;
  for (let i = from - 1; i < to && i < staff.bars.length; i++) {
    const bar = staff.bars[i];
    for (const voice of bar.voices) {
      for (const beat of voice.beats) {
        const t = (beat.absolutePlaybackStart || 0) * tps;
        beats.push({ beat: beat, t: t });
        for (const note of (beat.notes || [])) {
          if (note.isTieDestination) continue;     // 延音不是"再弹一下"
          notes.push({ note: note, beat: beat, t: t });
        }
      }
    }
  }
  return { beats: beats, notes: notes };
}

// 在谱面上把错音框出来（alphaTab 1.8 没有高亮 API，用它的布局坐标自己画）
function drawMarks(beats, segNotes, errors) {
  if (!el.scoreMarks || !scoreApi || !scoreApi.renderer) return;
  const lookup = scoreApi.renderer.boundsLookup;
  if (!lookup || !lookup.findBeat || !beats.length) return;
  el.scoreMarks.innerHTML = '';
  const off = markOffset();
  const used = new Set();
  // 首选"第几个音"直接对上（segmentBeats 已经把延音/休止对齐过了）；
  // 对不上再退回按时间就近挑一个还没被用过的拍。
  // 音数跟作业档案里的一致，才敢按"第几个音"直接对
  const byIndex = segNotes.length > 0
    && (!stdNoteCount() || segNotes.length === stdNoteCount());
  (errors || []).forEach((e) => {
    if (e.t_score == null) return;
    let target = null;
    if (byIndex && e.note_index && segNotes[e.note_index - 1]) {
      target = segNotes[e.note_index - 1];
    }
    if (!target) {
      let bd = 1e9;
      for (const b of beats) {
        if (used.has(b)) continue;
        const d = Math.abs(b.t - e.t_score);
        if (d < bd) { bd = d; target = b; }
      }
      if (target && bd > 0.5) target = null;             // 离得太远就不画（宁缺勿错）
    }
    if (!target || used.has(target)) return;
    used.add(target);
    const bb = lookup.findBeat(target.beat);
    const vb = bb && (bb.visualBounds || bb.realBounds || bb);
    if (!vb || vb.w == null) return;
    const div = document.createElement('div');
    div.className = 'mk mk-' + esc(e.kind || 'wrong_note');
    div.style.left = Math.round(vb.x + off.x) + 'px';
    div.style.top = Math.round(vb.y + off.y) + 'px';
    div.style.width = Math.max(9, Math.round(vb.w)) + 'px';
    div.style.height = Math.max(9, Math.round(vb.h)) + 'px';
    // 标记上写清"是什么错"：漏 / 错 / 抢 0.3s / 拖 1.2s / 停 1.4s
    // （用户 2026-09-29：别让我再回头猜是哪一种；标签表来自服务端）
    let label = kindLabel(e.kind, render.last) || '错';
    if (e.kind === 'rush' || e.kind === 'drag' || e.kind === 'pause'
        || e.sub === 'early' || e.sub === 'late') {
      const secs = (e.seconds != null) ? e.seconds : (e.dev != null ? Math.abs(e.dev) : null);
      if (secs != null) label += ' ' + secs + 's';
    }
    div.innerHTML = '<b>' + esc(label) + '<\/b>';
    el.scoreMarks.appendChild(div);
  });
  const n = el.scoreMarks.children.length;
  if (n && el.scoreHint && el.scoreHint.dataset.base) {
    el.scoreHint.textContent = el.scoreHint.dataset.base + '；红框 ' + n + ' 处。';
  }
}

// 这份作业一共几个音（用来判断"按第几个音对"靠不靠谱）
function stdNoteCount() {
  return currentStd && currentStd.notes ? currentStd.notes : 0;
}

// #scoreMarks 挂在滚动容器上，而 alphaTab 给的是相对它自己容器的坐标 —— 把偏移补上
function markOffset() {
  try {
    const s = el.scoreView.getBoundingClientRect();
    const w = el.scoreWrap.getBoundingClientRect();
    return { x: s.left - w.left + el.scoreWrap.scrollLeft,
             y: s.top - w.top + el.scoreWrap.scrollTop };
  } catch (e) {
    return { x: 0, y: 0 };
  }
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

assignReady = loadAssignment();

// ── 选文件 / 拖拽 ────────────────────────────────────────────────
// 开文件对话框**只留一条路**：<label for="file"> 的原生行为。
// （以前这里还挂了一句 el.file.click()，等于一次点击开两次对话框：
//   第一次选的会被后开的那个顶掉，表现就是"第一次上不去、第二次才行"。）
el.file.addEventListener('change', () => {
  setPicked(el.file.files[0] || null);
  el.file.value = '';       // 清掉，允许再选同一个文件（否则 change 不会触发）
});
el.clearFile.addEventListener('click', () => setPicked(null));
['dragenter', 'dragover'].forEach(ev => el.drop.addEventListener(ev, e => {
  e.preventDefault(); el.drop.classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => el.drop.addEventListener(ev, e => {
  e.preventDefault(); el.drop.classList.remove('over');
}));
el.drop.addEventListener('drop', e => setPicked((e.dataTransfer.files || [])[0] || null));

// ── 提交 → 轮询 ──────────────────────────────────────────────────
el.submit.addEventListener('click', async () => {
  el.submit.disabled = true;
  show(el.resultCard, false);
  show(el.progressCard, true);
  goStep(2);
  el.bar.style.width = '0%';
  el.stage.textContent = '上传中…';
  // 等作业信息加载完再提交：不然第一次点得太快，会带着空作业 id 提交（判到别的作业上）
  if (assignReady) { try { await assignReady; } catch (e) { /* 没加载上就按默认作业走 */ } }
  submittedLabel = picked ? picked.name : '';
  try {
    const q = '?id=' + encodeURIComponent(currentAid || '');
    const fd = new FormData();
    fd.append('audio', picked, picked.name);
    const resp = await fetch(API + '/submit' + q, { method: 'POST', body: fd });
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
  render.last = r;                 // 类型标签表从服务端来，后面画标记时要用
  show(el.resultCard, true);
  goStep(3);
  const a = r.assignment || meta;
  const std = r.standard || {};

  const sub = r.submitted || {};
  const metaRows = [
    ['作业', a.title || '—'],
    ['标准答案', a.track || '—'],
    ['本次要弹', std.notes ? std.notes + ' 个音' : '—'],
    ['提交内容', sub.file
      ? (sub.file + (sub.seconds ? '（' + sub.seconds + ' 秒）' : ''))
      : (submittedLabel || '本机真机素材')],
  ];
  el.reportMeta.innerHTML = metaRows
    .map(([k, v]) => '<div><dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd></div>')
    .join('');

  // 这条作业还没有录音样例：只显示标准答案，不显示分数
  if (r.no_audio) {
    show(el.noAudio, true);
    show(el.reportBody, false);
    show(el.scoreSection, false);
    el.noAudio.textContent = r.note || '这条作业还没有录音样例。';
    el.demoNote.textContent = r.note || '';
    el.resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  show(el.noAudio, false);
  show(el.reportBody, true);
  show(el.scoreSection, true);

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
        <div class="ih">${kindBadge(it.kind, r)}<span>${esc(it.title)}</span>
          <span class="t">${esc(issueTime(it))}</span></div>
        <div class="d">${esc(it.detail)}</div>
      </div>`;
  el.issues.innerHTML = key.length
    ? key.map(card).join('')
    : '<p class="stage">这一段没挑出明显问题。</p>';
  el.foldSummary.textContent = r.passed
    ? '这次的小问题（' + key.length + ' 处，不拦你过）'
    : '先改这几处（' + key.length + ' 处）';
  el.issueFold.open = true;      // 一律默认展开：用户要的是"老师指着谱子告诉我哪错了"
  el.resultCard.dataset.issueTotal = String((r.issues || []).length);
  el.moreCount.textContent = more.length;
  renderMoreIssues(more);
  el.demoNote.textContent = r.note;
  // 出结果之后才把谱面画出来，并把没对上的地方框红（交作业前不看谱，练去跟练页）
  renderScore(r.standard || currentStd, r.error_notes || []);
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

// 错误类型徽章。标签**只认服务端给的那一份**（homework/issue_types.py 是单一来源，
// 学隔壁那条教训：两边各写一套就会"数了却渲染不出来"）。这里的兜底只在老数据上生效。
const KIND_FALLBACK = { missing_note: '漏', wrong_note: '错', extra_note: '多弹',
                        rush: '抢', drag: '拖', pause: '停', rhythm_unstable: '节奏不稳' };
function kindLabel(kind, r) {
  const table = (r && r.issue_labels) || (render.last && render.last.issue_labels) || {};
  return table[kind] || KIND_FALLBACK[kind] || '';
}
function kindBadge(kind, r) {
  const label = kindLabel(kind, r);
  if (!kind || !label) return '';
  return '<i class="badge k-' + esc(kind) + '">' + esc(label) + '</i>';
}

refreshSubmit();
