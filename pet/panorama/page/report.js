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
   顶部的输入区（composer，个人简报的「随手记」）：POST /api/actions/<动作名> {report, text, images?}，回 saved 就清空框；
   推送到哪一步了由服务说（回答里的 status，之后每次重画也带着），页面不自己编。
   服务给了 composer.images 才收图：粘贴（剪贴板里同时有文字时不拦，让文字照常进框）、拖进输入框、点「添加图片」选文件；
   先排成一行缩略图（点 × 去掉），「记下」时和文字一起发 [{type, data(base64)}]。超过 composer.images.max 张的不收、说一声；
   太大的图（> SHRINK_BYTES）先在画布上缩成长边 SHRINK_EDGE 的 JPEG 再收——服务那头单张只收 3 MB。 */
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
  var SHRINK_BYTES = 2500000, SHRINK_EDGE = 2000;
  var pictures = [], reading = 0, pictureRules = null;  /* 排着的图 [{type, data}]、还在读的张数；服务说的收图规矩（composer.images），没有就不收 */

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
    pictureRules = c && c.images ? c.images : null;
    el('pick').hidden = !pictureRules;
    el('pick').textContent = pictureRules ? pictureRules.label || '' : '';
    if (!pictureRules) pictures = [];
    tray();
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

  /* 排着的图：一行缩略图，每张一个 × */
  function tray() {
    var box = el('tray');
    box.hidden = !pictures.length;
    box.innerHTML = pictures.map(function (p, i) {
      return '<span class="thumb"><img src="data:' + esc(p.type) + ';base64,' + esc(p.data) + '" alt="">' +
        '<button type="button" class="drop" data-drop="' + i + '" title="' + esc(pictureRules ? pictureRules.remove : '') + '">×</button></span>';
    }).join('');
  }
  function say(text, bad) { var status = el('composer-status'); status.textContent = text || ''; status.className = 'cstatus' + (bad ? ' bad' : ''); }
  /* 一个图片文件 → {type, data}：太大的先缩成 JPEG。读不出来的就算了（服务那头还会再查一遍） */
  function readPicture(file, done) {
    var reader = new FileReader();
    reader.onload = function () {
      var url = String(reader.result || ''), comma = url.indexOf(',');
      if (comma < 0) return;
      if (file.size <= SHRINK_BYTES || typeof document.createElement !== 'function') {
        done({type: file.type, data: url.slice(comma + 1)}); return;
      }
      var img = document.createElement('img');
      img.onload = function () {
        var scale = Math.min(1, SHRINK_EDGE / Math.max(img.naturalWidth, img.naturalHeight)), canvas = document.createElement('canvas');
        canvas.width = Math.round(img.naturalWidth * scale); canvas.height = Math.round(img.naturalHeight * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        var small = canvas.toDataURL('image/jpeg', 0.85);
        done({type: 'image/jpeg', data: small.slice(small.indexOf(',') + 1)});
      };
      img.src = url;
    };
    reader.readAsDataURL(file);
  }
  function takePictures(files) {
    if (!pictureRules || dead) return;
    files.forEach(function (file) {
      if (!file || !/^image\/(png|jpeg|webp|gif)$/.test(file.type || '')) return;
      if (pictures.length + reading >= (pictureRules.max || 0)) { say(pictureRules.full, true); return; }
      reading += 1;                              /* 读图是异步的：还在读的也算进上限 */
      readPicture(file, function (picture) { reading -= 1; pictures.push(picture); tray(); });
    });
  }
  function filesOf(items) { var out = []; for (var i = 0; i < (items ? items.length : 0); i++) out.push(items[i]); return out; }

  function compose() {
    var box = el('text'), btn = el('add'), status = el('composer-status');
    if (btn.disabled || dead) return;
    var sending = pictures.slice();
    if (!String(box.value || '').trim() && !sending.length) { say(S.report_compose_empty, true); return; }
    btn.disabled = true;
    var body = {report: btn.dataset.report, text: box.value};
    if (sending.length) body.images = sending.map(function (p) { return {type: p.type, data: p.data}; });
    api.post('/api/actions/' + btn.dataset.name, body).then(function (r) {
      var body = r.body || {}, state = body.state;
      btn.disabled = false;
      if (r.status === 200 && state === 'saved') { box.value = ''; pictures = []; tray(); }
      status.textContent = body.status || S[state === 'empty' ? 'report_compose_empty' : 'report_action_failed'] || '';
      status.className = 'cstatus' + (state === 'saved' ? '' : ' bad');
    }).then(null, function () { btn.disabled = false; status.textContent = S.report_action_lost || ''; status.className = 'cstatus bad'; });
  }
  el('add').addEventListener('click', compose);
  el('text').addEventListener('paste', function (event) {
    var items = filesOf(event.clipboardData && event.clipboardData.items);
    var files = items.filter(function (it) { return it.kind === 'file'; }).map(function (it) { return it.getAsFile(); });
    if (!pictureRules || !files.length) return;
    if (!items.some(function (it) { return it.kind === 'string'; })) event.preventDefault();
    takePictures(files);
  });
  el('text').addEventListener('dragover', function (event) { if (pictureRules) event.preventDefault(); });
  el('text').addEventListener('drop', function (event) {
    var files = filesOf(event.dataTransfer && event.dataTransfer.files);
    if (!pictureRules || !files.length) return;
    event.preventDefault();
    takePictures(files);
  });
  el('pick').addEventListener('click', function () { el('file').click(); });
  el('file').addEventListener('change', function (event) { takePictures(filesOf(event.target.files)); event.target.value = ''; });
  el('tray').addEventListener('click', function (event) {
    var drop = event.target.closest ? event.target.closest('[data-drop]') : null;
    if (!drop) return;
    pictures.splice(Number(drop.dataset.drop), 1);
    tray();
  });
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
