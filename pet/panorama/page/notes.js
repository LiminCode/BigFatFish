/* 笔记页的脚本（/report/work_notes、/report/slack_watch）：取令牌 → 向 /api/report/<名字> 要数据 → 摆到页面上 →
   带着编号去「等更新的」（服务把请求挂住，笔记变了那一刻才回），页面原地重画，选中的那条和筛选保持不变。

   页面不认识具体功能：标题、计数、输入框有没有、每条的字段、仓库状态、Slack 检查状态条、按钮都是服务给的字段。
   动作一律 POST /api/actions/note {report, op, name, …}：记下 / 完成 / 稍后 / 删除（先 confirm）/ 重新总结 / 打开链接 /
   Obsidian / 文件夹 / 再推一次。服务回了之后不自己改列表——笔记服务发 changed，页面等到新数据再重画。
   「现在检查」（Slack 页）走报告页同一个动作 generate_report。

   选中的那条记在 sessionStorage（刷新不丢）；肥鱼从提醒气泡「查看」开过来时网址片段里带 note=<名字>，进来就选中它。 */
import {esc} from './util.js';
import {takeToken, makeApi} from './client.js';
import {filterNotes, countsHtml, filterChips, rowsHtml, detailHtml, repoHtml, watchHtml} from './notelist.js';

(function () {
  var RETRY_MS = 1000;
  var name = location.pathname.split('/').pop();
  var taken = takeToken('report-token'), token = taken.token, api = makeApi(token);
  var el = function (id) { return document.getElementById(id); };
  var revision = 0, waiting = false, dead = false, S = {}, R = {};
  var filter = 'all', query = '', selected = '', selKey = 'notes-selected:' + name;

  (taken.extras || []).forEach(function (part) {      /* note=<名字>：肥鱼让这页直接翻到那一条 */
    var kv = part.split('=');
    if (kv[0] === 'note' && kv[1]) selected = decodeURIComponent(kv[1]);
  });
  if (!selected) { try { selected = sessionStorage.getItem(selKey) || ''; } catch (e) { selected = ''; } }

  function remember() { try { sessionStorage.setItem(selKey, selected); } catch (e) { /* 隐私窗口：刷新后从头选 */ } }
  function lost() { dead = true; waiting = false; el('lost').hidden = false; el('add').disabled = true; }
  function say(text, cls) { el('status').textContent = text || ''; el('status').className = 'status' + (cls ? ' ' + cls : ''); }

  function current() {
    var notes = R.notes || [];
    for (var i = 0; i < notes.length; i++) if (notes[i].name === selected) return notes[i];
    return null;
  }

  function show(data) {
    R = data.report || {};
    S = data.strings || {};
    document.documentElement.lang = data.page.lang;
    document.documentElement.dataset.theme = R.theme || 'dark';
    document.title = data.page.title;
    el('title').textContent = R.title || '';
    el('settings-link').textContent = S.notes_btn_settings || '';
    el('settings-link').href = location.origin + '/#' + token + (R.settings_focus ? '&settings=' + encodeURIComponent(R.settings_focus) : '');
    var notes = R.available === false ? [] : (R.notes || []);
    el('counts').innerHTML = R.available === false ? '' : countsHtml(R.counts, S);
    el('repo').innerHTML = R.available === false ? '' : repoHtml(R.repo, S);
    el('folder').hidden = R.available === false;
    el('folder').textContent = S.notes_btn_folder || '';
    el('composer').hidden = !(R.composer && R.available !== false);
    el('text').placeholder = R.placeholder || '';
    el('add').textContent = R.add_label || '';
    el('add').title = R.add_hint || '';
    el('watch').hidden = !(R.watch && R.available !== false);
    el('watch').innerHTML = R.watch ? watchHtml(R.watch, S) + actionButton(R.action, R.watch.busy) : '';
    el('actions').innerHTML = R.available === false ? '' : (R.actions || []).map(function (a) {
      return '<button class="btn" data-name="' + esc(a.name) + '" data-report="' + esc(a.report) + '" title="' + esc(a.hint || '') + '">' + esc(a.label) + '</button>';
    }).join('');
    if (R.available === false) {
      el('empty').hidden = false; el('empty').textContent = R.unavailable_text || S.notes_unavailable || '';
      el('grid').hidden = true;
    } else if (!notes.length) {
      el('empty').hidden = false; el('empty').textContent = R.empty_text || '';
      el('grid').hidden = true;
    } else {
      el('empty').hidden = true; el('grid').hidden = false;
      if (!current()) { var open = notes.filter(function (n) { return n.open; }); selected = (open[0] || notes[0]).name; }
      el('search').hidden = notes.length <= 5;
      el('search').placeholder = S.notes_search || '';
      paint();
    }
    revision = data.revision;
  }

  function actionButton(action, busy) {
    if (!action) return '';
    return '<button class="btn" id="action" data-name="' + esc(action.name) + '" data-report="' + esc(action.report) + '" title="' + esc(action.hint || '') + '"' +
      (busy ? ' disabled' : '') + '>' + esc(action.label) + '</button>';
  }

  function paint() {         /* 列表 + 详情按当前筛选 / 搜索 / 选中重画；数据本身不动 */
    var notes = R.notes || [], shown = filterNotes(notes, filter, query);
    el('filters').innerHTML = filterChips(R.counts, filter, S);
    el('rows').innerHTML = rowsHtml(shown, selected, S);
    el('detail').innerHTML = detailHtml(current(), S);
  }

  function select(noteName, scroll) {
    selected = noteName; remember(); paint();
    if (scroll) { var row = el('rows').querySelector('[data-note="' + noteName.replace(/"/g, '\\"') + '"]'); if (row && row.scrollIntoView) row.scrollIntoView({block: 'nearest'}); }
  }

  /* 动作：POST /api/actions/note；回答里的 state 翻成状态栏一句话。列表的变化等服务发布新数据 */
  function act(op, noteName, extra, onDone) {
    if (dead) return;
    var body = {report: name, op: op, name: noteName || ''};
    for (var key in (extra || {})) body[key] = extra[key];
    say(S.notes_started || '');
    api.post('/api/actions/note', body).then(function (r) {
      var state = (r.body || {}).state || 'failed';
      var text = {saved: S.notes_saved, empty: S.notes_empty_text, started: S.notes_started, done: '', opened: S.notes_opened,
                  folder: S.notes_folder_opened, no_link: S.notes_no_link, missing: S.notes_missing, busy: S.notes_busy_short}[state];
      if (text === undefined) text = String(S.notes_failed || '').replace('{error}', (r.body || {}).error || r.status);
      say(text, state === 'failed' || r.status !== 200 ? 'bad' : (state === 'saved' ? 'ok' : ''));
      if (onDone) onDone(state, r.body || {});
    }).then(null, function () { say(S.notes_lost || '', 'bad'); });
  }

  function add() {
    var text = el('text').value;
    if (!String(text || '').trim()) { say(S.notes_empty_text || ''); return; }
    el('add').disabled = true;
    act('add', '', {text: text}, function (state, body) {
      el('add').disabled = false;
      if (state === 'saved') { el('text').value = ''; if (body.name) { selected = body.name; remember(); } }
    });
  }

  el('add').addEventListener('click', add);
  el('text').addEventListener('keydown', function (event) {
    if ((event.key === 'Enter' || event.keyCode === 13) && (event.ctrlKey || event.metaKey)) { event.preventDefault(); add(); }
  });
  el('folder').addEventListener('click', function () { act('folder', ''); });
  el('repo').addEventListener('click', function (event) {
    var b = event.target.closest ? event.target.closest('[data-op]') : null;
    if (b) act(b.dataset.op, '');
  });
  el('filters').addEventListener('click', function (event) {
    var chip = event.target.closest ? event.target.closest('.chip') : null;
    if (chip) { filter = chip.dataset.f || 'all'; paint(); }
  });
  el('search').addEventListener('input', function (event) { query = event.target.value || ''; paint(); });
  el('rows').addEventListener('click', function (event) {
    var row = event.target.closest ? event.target.closest('[data-note]') : null;
    if (!row) return;
    event.preventDefault();
    select(row.dataset.note, false);
  });
  el('detail').addEventListener('click', function (event) {
    var b = event.target.closest ? event.target.closest('[data-op]') : null;
    if (!b || b.disabled) return;
    var acts = b.closest('.acts'), noteName = acts ? acts.dataset.note : selected, op = b.dataset.op, note = current();
    if (op === 'delete') {
      if (!confirm(String(S.notes_confirm_delete || '{title}').replace('{title}', note ? note.title : noteName))) return;
    }
    if (op === 'snooze') act(op, noteName, {minutes: parseInt(b.dataset.minutes, 10)});
    else act(op, noteName);
  });
  /* 「现在检查」（Slack 页）和别的副按钮：报告页同一个动作通道 */
  function generic(btn) {
    if (btn.disabled || dead) return;
    btn.disabled = true;
    say(S.report_action_started || '');
    api.post('/api/actions/' + btn.dataset.name, {report: btn.dataset.report}).then(function (r) {
      var state = (r.body || {}).state;
      if (r.status === 200 && state === 'started') return;
      say(S[state === 'busy' ? 'report_action_busy' : state === 'opened' ? 'report_action_opened' : 'report_action_failed'] || '');
      btn.disabled = state === 'busy';
    }).then(null, function () { say(S.report_action_lost || '', 'bad'); btn.disabled = false; });
  }
  el('watch').addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('[data-name]') : null;
    if (btn) generic(btn);
  });
  el('actions').addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('[data-name]') : null;
    if (btn) generic(btn);
  });

  function listen() {
    if (waiting || dead || document.visibilityState !== 'visible') return;
    waiting = true;
    api('/api/report/' + name + '?after=' + revision).then(function (next) {
      waiting = false;
      if (next) { show(next); listen(); } else setTimeout(listen, RETRY_MS);
    }).then(null, lost);
  }

  api('/api/report/' + name).then(function (data) {
    if (!data) throw new Error('empty');
    show(data);
    if (selected) select(selected, true);
    document.addEventListener('visibilitychange', listen);
    listen();
  }).then(null, lost);
})();
