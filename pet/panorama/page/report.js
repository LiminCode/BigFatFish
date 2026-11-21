/* 报告页的脚本（/report/<名字>：工作简报、个人简报）：取令牌 → 向 /api/report/<名字> 要数据 → 摆到页面上 →
   带着编号去「等更新的」（服务把请求挂住，生成开始 / 结束那一刻才回），页面原地重画。

   页面不认识具体功能：标题、概要、用量、分区、全文、按钮、「这次是怎么生成的」几段都是服务给的字段。
   分区（sections）有的话：左栏一块块磁贴（点了滚过去）+ 筛选片，右栏每区一张卡（实色磁贴头 + 列表）；没有就把整段
   html 放进 article。每张卡里顶层的每一条，进页面后按 items.classify 打上 data-p / data-bug / data-upd，前面插一个勾选框：
   勾掉只存在这个浏览器的 localStorage 里（键 = 生成时间 + 区 + 序号，重新生成就是新的一套），不进肥鱼、不进配置。
   筛选片多选取并集；「隐藏已勾掉」另算。折叠状态只在内存里，重画时保留。
   全文、每区的 html 都是服务端渲染好的（markdown.py 只会产出那几个标签，别的全转义过了），直接放进去；概要、用量、标题
   这类纯文字这里转义。
   「重新生成」：POST /api/actions/<动作名> {report}；服务回 started 之后不动按钮——生成开始的信号会让页面重画成忙碌，
   结束再重画成新内容。回 busy 时按钮保持灰，别的回答把原因写在状态栏、按钮放开。
   顶部的输入区（composer，个人简报的「记灵感」）：POST /api/actions/<动作名> {report, text}，回 saved 就清空框；推送到哪一步了
   由服务说（回答里的 status，之后每次重画也带着），页面不自己编。 */
import {esc} from './util.js';
import {takeToken, makeApi} from './client.js';
import {classify, passes, navTiles, filterChips, card} from './items.js';

(function () {
  var RETRY_MS = 1000;         /* 服务说「这段时间没有新数据」之后隔多久再去等：只为防止出错时空转 */
  var name = location.pathname.split('/').pop();
  var token = takeToken('report-token').token, api = makeApi(token);
  var el = function (id) { return document.getElementById(id); };
  var revision = 0, waiting = false, dead = false, S = {};
  var filters = [], hideDone = false, collapsed = {}, doneKey = '', done = {};

  function lost() { dead = true; waiting = false; el('lost').hidden = false; el('action').disabled = true; el('add').disabled = true; }

  function load(key) { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (e) { return {}; } }
  function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 隐私窗口等：勾掉就只在这一次 */ } }

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
    var sections = r.available === false ? [] : (r.sections || []);
    if (sections.length) {
      doneKey = 'report-done:' + name + ':' + (r.generated || '');
      done = load(doneKey);
      el('side').hidden = false;
      el('nav-title').textContent = S.report_sections || '';
      el('filter-title').textContent = S.report_filters || '';
      el('nav').innerHTML = navTiles(sections, S);
      el('filters').innerHTML = filterChips(filters, hideDone, S);
      el('trace-link').textContent = S.report_trace || '';
      el('trace-link').hidden = !(r.details || []).length;
      el('cards').innerHTML = sections.map(function (s) { return card(s, S, !!collapsed[s.id]); }).join('');
      el('body').innerHTML = '';
      enhance();
    } else {
      el('side').hidden = true;
      el('nav').innerHTML = ''; el('filters').innerHTML = ''; el('cards').innerHTML = '';
      if (r.available === false) el('body').innerHTML = '<p class="note">' + esc(S.report_unavailable) + '</p>';
      else if (r.html) el('body').innerHTML = r.html;
      else el('body').innerHTML = '<p class="note">' + esc(r.busy ? r.busy_text : r.empty_text) + '</p>';
    }
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
    /* 旁边的几个按钮（个人简报的「在 Obsidian 打开 AI-Base」）：同一个动作通道，回 opened 就在状态栏说一声 */
    el('actions').innerHTML = r.available === false ? '' : (r.actions || []).map(function (a) {
      return '<button class="btn" data-name="' + esc(a.name) + '" data-report="' + esc(a.report) + '" title="' + esc(a.hint || '') + '">' + esc(a.label) + '</button>';
    }).join('');
    /* 顶部的输入区：服务给什么字就摆什么；推送到哪一步了也是服务说的 */
    var c = r.composer;
    el('composer').hidden = !(c && r.available !== false);
    if (c) {
      el('text').placeholder = c.placeholder || '';
      el('add').textContent = c.label || '';
      el('add').dataset.name = c.action.name;
      el('add').dataset.report = c.action.report;
      el('composer-hint').textContent = c.hint || '';
      el('composer-status').textContent = c.status || '';
      el('composer-status').className = 'cstatus' + (c.failed ? ' bad' : '');
    }
    /* 详情几段也是服务端渲染好的 HTML（reports.trace_sections），第一段默认展开；里面「到设置里改」的占位换成
       配置全景带令牌的地址（同一个服务、同一个令牌） */
    var settingsUrl = location.origin + '/#' + token + (r.settings_focus ? '&settings=' + encodeURIComponent(r.settings_focus) : '');
    el('details').innerHTML = (r.details || []).map(function (d, i) {
      return '<details' + (i === 0 ? ' open' : '') + '><summary>' + esc(d.title) + '</summary><div class="d">' +
        String(d.html || '').split('__SETTINGS_URL__').join(settingsUrl) + '</div></details>';
    }).join('');
    revision = data.revision;
  }

  /* 每张卡里顶层的每一条：分类、勾选框、正文包进 .body；然后按当前筛选显示 / 隐藏 */
  function enhance() {
    var items = el('cards').querySelectorAll('.card > .list > ul > li, .card > .list > ol > li');
    Array.prototype.forEach.call(items, function (li, i) {
      var section = li.closest('.card').id, key = section + ':' + i, c = classify(li.innerHTML, li.className);
      li.dataset.key = key; li.dataset.p = c.p; li.dataset.bug = c.bug ? '1' : '0'; li.dataset.upd = c.upd ? '1' : '0';
      var body = document.createElement('div'); body.className = 'body';
      while (li.firstChild) body.appendChild(li.firstChild);
      var box = document.createElement('label'); box.className = 'done'; box.title = S.report_done || '';
      var input = document.createElement('input'); input.type = 'checkbox'; input.checked = !!done[key];
      input.addEventListener('change', function () {
        if (input.checked) done[key] = 1; else delete done[key];
        save(doneKey, done);
        apply();
      });
      box.appendChild(input); li.appendChild(box); li.appendChild(body);
    });
    apply();
  }

  function apply() {
    var items = el('cards').querySelectorAll('li[data-key]');
    Array.prototype.forEach.call(items, function (li) {
      var isDone = !!done[li.dataset.key];
      li.classList.toggle('is-done', isDone);
      li.hidden = !passes({p: +li.dataset.p, bug: li.dataset.bug === '1', upd: li.dataset.upd === '1', done: isDone}, filters, hideDone);
    });
  }

  el('filters').addEventListener('click', function (event) {
    var chip = event.target.closest ? event.target.closest('.chip') : null;
    if (chip) {
      var f = chip.dataset.f;
      if (!f) filters = [];
      else if (filters.indexOf(f) >= 0) filters.splice(filters.indexOf(f), 1);
      else filters.push(f);
      el('filters').innerHTML = filterChips(filters, hideDone, S);
      apply();
    }
  });
  el('filters').addEventListener('change', function (event) {
    if (event.target && event.target.id === 'hide-done') { hideDone = !!event.target.checked; apply(); }
  });
  el('nav').addEventListener('click', function (event) {
    var tile = event.target.closest ? event.target.closest('[data-go]') : null;
    if (!tile) return;
    event.preventDefault();
    var target = el(tile.dataset.go);
    if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
  el('cards').addEventListener('click', function (event) {
    var fold = event.target.closest ? event.target.closest('[data-fold]') : null;
    if (!fold) return;
    var id = fold.dataset.fold, section = el(id);
    collapsed[id] = !collapsed[id];
    if (section) { section.dataset.collapsed = collapsed[id] ? '1' : ''; fold.textContent = collapsed[id] ? '▸' : '▾'; fold.setAttribute('aria-expanded', !collapsed[id]); }
  });

  function listen() {          /* 同一时刻只挂一个请求；标签页藏着或连接已断就不挂 */
    if (waiting || dead || document.visibilityState !== 'visible') return;
    waiting = true;
    api('/api/report/' + name + '?after=' + revision).then(function (next) {
      waiting = false;
      if (next) { show(next); listen(); } else setTimeout(listen, RETRY_MS);
    }).then(null, lost);
  }

  function act(btn) {
    if (btn.disabled || dead) return;
    btn.disabled = true;
    el('status').textContent = S.report_action_started || '';
    api.post('/api/actions/' + btn.dataset.name, {report: btn.dataset.report}).then(function (r) {
      var state = (r.body || {}).state;
      if (r.status === 200 && state === 'started') return;
      el('status').textContent = S[state === 'busy' ? 'report_action_busy' : state === 'opened' ? 'report_action_opened' : 'report_action_failed'] || '';
      btn.disabled = state === 'busy';
    }).then(null, function () { el('status').textContent = S.report_action_lost || ''; btn.disabled = false; });
  }
  el('action').addEventListener('click', function () { act(el('action')); });

  function compose() {
    var box = el('text'), btn = el('add'), status = el('composer-status');
    if (btn.disabled || dead) return;
    if (!String(box.value || '').trim()) { status.textContent = S.report_compose_empty || ''; status.className = 'cstatus bad'; return; }
    btn.disabled = true;
    api.post('/api/actions/' + btn.dataset.name, {report: btn.dataset.report, text: box.value}).then(function (r) {
      var body = r.body || {}, state = body.state;
      btn.disabled = false;
      if (r.status === 200 && state === 'saved') box.value = '';
      status.textContent = body.status || S[state === 'empty' ? 'report_compose_empty' : 'report_action_failed'] || '';
      status.className = 'cstatus' + (state === 'saved' ? '' : ' bad');
    }).then(null, function () { btn.disabled = false; status.textContent = S.report_action_lost || ''; status.className = 'cstatus bad'; });
  }
  el('add').addEventListener('click', compose);
  el('text').addEventListener('keydown', function (event) {
    if ((event.key === 'Enter' || event.keyCode === 13) && (event.ctrlKey || event.metaKey)) { event.preventDefault(); compose(); }
  });
  el('actions').addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('[data-name]') : null;
    if (btn) act(btn);
  });

  api('/api/report/' + name).then(function (data) {
    if (!data) throw new Error('empty');
    show(data);
    document.addEventListener('visibilitychange', listen);   /* 回到这个标签页时接着等（期间有新数据会立刻拿到） */
    listen();
  }).then(null, lost);
})();
