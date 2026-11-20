/* 报告页的脚本（/report/<名字>，现在只有工作简报）：取令牌 → 向 /api/report/<名字> 要数据 → 摆到页面上 →
   带着编号去「等更新的」（服务把请求挂住，生成开始 / 结束那一刻才回），页面原地重画。

   页面不认识具体功能：标题、概要、用量、全文、按钮都是服务给的字段。全文是服务端渲染好的 HTML（markdown.py 只会产出
   那几个标签，别的全转义过了），直接放进 article；概要、用量这类纯文字这里转义。
   「重新生成」：POST /api/actions/<动作名> {report}；服务回 started 之后不动按钮——生成开始的信号会让页面重画成忙碌，
   结束再重画成新内容。回 busy 时按钮保持灰，别的回答把原因写在状态栏、按钮放开。 */
import {esc} from './util.js';
import {takeToken, makeApi} from './client.js';

(function () {
  var RETRY_MS = 1000;         /* 服务说「这段时间没有新数据」之后隔多久再去等：只为防止出错时空转 */
  var name = location.pathname.split('/').pop();
  var api = makeApi(takeToken('report-token').token);
  var el = function (id) { return document.getElementById(id); };
  var revision = 0, waiting = false, dead = false, S = {};

  function lost() { dead = true; waiting = false; el('lost').hidden = false; el('action').disabled = true; }

  function show(data) {
    var r = data.report || {};
    S = data.strings || {};
    document.documentElement.lang = data.page.lang;
    document.documentElement.dataset.theme = r.theme || 'dark';
    document.title = data.page.title;
    el('title').textContent = r.title || '';
    el('generated').textContent = r.generated || '';
    el('summary').textContent = r.summary || '';
    el('summary').hidden = !r.summary;
    el('usage').innerHTML = (r.usage || []).map(function (u) { return '<span class="u" title="' + esc(u.tip) + '">' + esc(u.text) + '</span>'; }).join('');
    if (r.available === false) el('body').innerHTML = '<p class="note">' + esc(S.report_unavailable) + '</p>';
    else if (r.html) el('body').innerHTML = r.html;
    else el('body').innerHTML = '<p class="note">' + esc(r.busy ? r.busy_text : r.empty_text) + '</p>';
    el('status').textContent = r.busy ? r.busy_text : (r.error || '');
    el('status').className = 'status' + (r.error && !r.busy ? ' bad' : '');
    var btn = el('action');
    if (r.action && r.available !== false) {
      btn.hidden = false;
      btn.textContent = r.action.label;
      btn.title = r.action.hint || '';
      btn.disabled = !!r.busy;
      btn.dataset.name = r.action.name;
      btn.dataset.report = r.action.report;
    } else btn.hidden = true;
    revision = data.revision;
  }

  function listen() {          /* 同一时刻只挂一个请求；标签页藏着或连接已断就不挂 */
    if (waiting || dead || document.visibilityState !== 'visible') return;
    waiting = true;
    api('/api/report/' + name + '?after=' + revision).then(function (next) {
      waiting = false;
      if (next) { show(next); listen(); } else setTimeout(listen, RETRY_MS);
    }).then(null, lost);
  }

  el('action').addEventListener('click', function () {
    var btn = el('action');
    if (btn.disabled || dead) return;
    btn.disabled = true;
    el('status').textContent = S.report_action_started || '';
    api.post('/api/actions/' + btn.dataset.name, {report: btn.dataset.report}).then(function (r) {
      var state = (r.body || {}).state;
      if (r.status === 200 && state === 'started') return;
      el('status').textContent = S[state === 'busy' ? 'report_action_busy' : 'report_action_failed'] || '';
      btn.disabled = state === 'busy';
    }).then(null, function () { el('status').textContent = S.report_action_lost || ''; btn.disabled = false; });
  });

  api('/api/report/' + name).then(function (data) {
    if (!data) throw new Error('empty');
    show(data);
    document.addEventListener('visibilitychange', listen);   /* 回到这个标签页时接着等（期间有新数据会立刻拿到） */
    listen();
  }).then(null, lost);
})();
