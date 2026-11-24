/* 交互与侧栏：点磁贴追踪、详情、待处理、线路筛选、搜索、动效开关、缩放，以及页面上的固定文字。

   数据换了页面会原地重画，所以这里可以反复调：每次调用挂的监听都带同一个中止信号，返回的 dispose() 一次摘干净；
   kept 是上一次 capture() 记下的「用户正看着什么」，重画后照原样恢复（那个节点或那条线还在的话）。 */
import {esc, ago, rowMatches, clampAside} from './util.js';
import {viewer} from './viewer.js';
import {memory} from './memory.js';
import {settingsPanel} from './settings.js';
import {actionButton, runAction} from './repair.js';

/* 详情里列表的状态放在模块里（不随重画丢）：哪些条目展开着（磁贴 id + 条目名）、每块磁贴的筛选词、「全部展开」。
   「全部展开」和右栏宽度还存 localStorage——只是这个浏览器的便利，不进配置。 */
const expanded = new Set(), filters = new Map();
const store = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 隐私窗口等 */ } }};
let expandAll = store.get('panorama-rows') === 'all';

export function interact(M, E, map, kept, api) {
const {G, R, N, W, H} = M;
const S = G.strings, STATE = S.state, ESTATE = S.edge_state;
const off = new AbortController(), on = {signal: off.signal};
const files = viewer(api, S, on);
const memo = memory(G, S, on, api ? files.open : null);
const panel = settingsPanel(api, S);      /* 整页只有一个，重画时拿到的还是它（见 settings.js） */
/* 「查看」按钮：从肥鱼打开的页面才有服务可问；离线快照里按钮是灰的，悬停说明为什么 */
const viewBtn = (store, title, cls) => `<button class="${cls}" data-view="${esc(store)}" data-title="${esc(title)}"${api ? '' : ` disabled title="${esc(S.view_needs_service)}"`}>${esc(S.view)}</button>`;
let selected = null, lineOn = null, lastRows = new Map();
function trace(id) { const ns = new Set([id]), es = new Set();
  const walk = fwd => { const q = [id], seen = new Set([id]);
    while (q.length) { const c = q.pop(); E.forEach((e, i) => { const a = fwd ? e.from : e.to, b = fwd ? e.to : e.from;
      if (a === c) { es.add(i); ns.add(b); if (!seen.has(b)) { seen.add(b); q.push(b); } } }); } };
  walk(true); walk(false); return {ns, es}; }
function paint(ns, es) { map.classList.toggle('focus', !!ns);
  map.querySelectorAll('.tile').forEach(t => t.classList.toggle('on', !!ns && ns.has(t.dataset.id)));
  map.querySelectorAll('.edge').forEach(p => p.classList.toggle('on', !!es && es.has(+p.dataset.e))); }
function select(id) { selected = id; lineOn = null; document.getElementById('q').value = '';
  document.querySelectorAll('#lines .chip').forEach(c => c.classList.remove('active'));
  map.querySelectorAll('.tile').forEach(t => t.classList.toggle('sel', t.dataset.id === id));
  if (!id) { paint(null, null); detail(null); return; }
  const n = N[id], seeds = n.head ? G.nodes.filter(m => m.group === n.group).map(m => m.id) : [id], ns = new Set(), es = new Set();
  seeds.forEach(k => { const t = trace(k); t.ns.forEach(x => ns.add(x)); t.es.forEach(x => es.add(x)); });
  paint(ns, es); detail(id); }
function detail(id) { const box = document.getElementById('detail');
  if (!id) { box.innerHTML = `<h2>${esc(S.help_title)}</h2><p class="hint">${esc(S.help_text).split('\n').join('<br>')}</p>`; return; }
  const n = N[id], k = G.kinds[n.kind] || {}, out = E.filter(e => e.from === id), inn = E.filter(e => e.to === id), src = n.source || {};
  /* 「在 VS Code 打开」。WSL 里的路径走远程链接：VS Code 默认把它当文件夹开，结尾带 :行号 才当文件——
     不带的话点一个文件会开出空白窗口。是目录（src.dir）就不带。发行版名字没探到时不给链接，只留路径。
     两种链接都带 ?windowId=_blank：让 VS Code 开一个新窗口，而不是把文件塞进手头正开着的那个项目里。 */
  const target = !src.path ? '' : src.env !== 'wsl' ? 'vscode://file/' + src.path.replace(/\\/g, '/')
    : src.distro ? `vscode://vscode-remote/wsl+${src.distro}${src.path}${src.dir ? '' : ':1'}` : '';
  const link = target && target + '?windowId=_blank';
  /* 要处理的（坏了、待授权、警告）在前，这台机器上没有的垫底；探测不到的和正常的不分先后，保持数据给的顺序 */
  const rank = r => r.state === 'off' ? 2 : r.state === 'ok' || r.state === 'unknown' || r.state === 'live' ? 1 : 0;
  const rows = (n.items || []).slice().sort((a, b) => rank(a) - rank(b));
  const todo = G.quests.find(q => q.node === id && q.action);     /* 这块磁贴名下有带动作的待处理（装 hooks）：详情里也给一个按钮；磁贴自己带 actions 的（知识库克隆）用它的，一直都在 */
  /* 时间值后面补「· N 小时前」；列表默认紧凑：带 more 的条目折着，点 ▸ 展开；超过 5 条给一个筛选框 */
  const when = v => { const a = ago(v, S); return esc(v) + (a ? `<span class="ago"> · ${esc(a)}</span>` : ''); };
  const keyOf = r => id + '\u0000' + r.name, open = r => expandAll || expanded.has(keyOf(r)), q = filters.get(id) || '';
  lastRows = new Map(rows.map(r => [r.name, r]));
  const tools = !rows.length ? '' : `<div class="ltools"><span class="lcount">${esc(String(S.list_count || '{n}').replace('{n}', rows.length))}</span>` +
    (rows.length > 5 ? `<input class="lfilter" data-filter="${esc(id)}" value="${esc(q)}" placeholder="${esc(S.list_filter)}" aria-label="${esc(S.list_filter)}">` : '') +
    (rows.some(r => r.more) ? `<button class="peek" data-expand-all="1">${esc(expandAll ? S.collapse_all : S.expand_all)}</button>` : '') + '</div>';
  const nb = (list, key) => list.map(e => `<button data-go="${e[key]}"><i class="dot ${e.state === 'broken' ? 'bad' : e.state}"></i>${esc(N[e[key]].title)}${e.label ? ' · ' + esc(e.label) : ''}<span style="color:var(--muted)">${ESTATE[e.state]}</span></button>`).join('');
  box.innerHTML = `<h2>${esc(k.name || n.kind)} · ${esc(R[n.region].title)}</h2><h3>${esc(n.title)}</h3>
    <div style="display:flex;gap:8px;align-items:center;font-size:12.5px;margin-top:4px"><i class="dot ${n.state}"></i>${STATE[n.state] || ''}</div>
    <dl class="kv">${(n.facts || []).filter(f => f[1] !== undefined && f[1] !== null && f[1] !== '').map(([a, b]) => `<dt>${esc(a)}</dt><dd>${when(b)}</dd>`).join('')}</dl>
    ${rows.length ? tools + `<div class="list">${rows.map(r => `<div class="item" data-row="${esc(r.name)}"${rowMatches(r, q) ? '' : ' hidden'}><div class="row">` +
      (r.more ? `<button class="fold" data-toggle="${esc(r.name)}" aria-expanded="${open(r)}">${open(r) ? '▾' : '▸'}</button>` : '<i class="fold-gap"></i>') +
      `<i class="dot ${r.state === 'auth' ? 'warn' : r.state}"></i>${esc(r.name)}<small>${esc(r.detail || '')}</small>${r.view ? viewBtn(r.view, r.name, 'peek') : ''}</div>` +
      (r.more ? `<dl class="more"${open(r) ? '' : ' hidden'}>${r.more.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${when(b)}</dd>`).join('')}</dl>` : '') + '</div>').join('')}</div>` : ''}
    ${src.path ? `<div class="path">${esc(src.path)}${src.key ? '<br>→ ' + esc(src.key) : ''}</div>` : ''}
    <div class="btns">${(n.actions ? n.actions.map(a => ({action: a})) : todo ? [todo] : []).map(q => actionButton(S, q, api).replace(' mini', '')).join('')}${n.settings ? `<button class="btn" data-settings="${esc(n.settings)}" data-title="${esc(n.title)}"${api ? '' : ` disabled title="${esc(S.settings_needs_service)}"`}>${esc(S.settings_open)}</button>` : ''}${n.view ? viewBtn(n.view, n.title, 'btn') : ''}${n.memory ? `<button class="btn" data-memory="1">${esc(S.memory_button)}</button>` : ''}${link ? `<a class="btn" href="${esc(link)}">${esc(S.open_vscode)}</a>` : ''}${src.path ? `<button class="btn" data-copy="${esc(src.path)}">${esc(S.copy_path)}</button>` : ''}
      ${n.page ? `<span class="btn ghost" title="${esc(S.settings_hint)}">${esc(S.settings_at.replace('{page}', n.page))}</span>` : ''}</div>
    ${out.length ? `<h2 style="margin-top:14px">${esc(S.uses)}</h2><div class="nb">${nb(out, 'to')}</div>` : ''}
    ${inn.length ? `<h2 style="margin-top:14px">${esc(S.used_by)}</h2><div class="nb">${nb(inn, 'from')}</div>` : ''}`; }
function pickLine(k) { select(null); lineOn = k;
  document.querySelectorAll('#lines .chip').forEach(x => x.classList.toggle('active', x.dataset.line === k)); if (!k) return;
  const ns = new Set(), es = new Set(); E.forEach((e, i) => { if (e.line === k) { es.add(i); ns.add(e.from); ns.add(e.to); } }); paint(ns, es); }
function search(text) { const q = text.trim().toLowerCase(); if (!q) return paint(null, null);
  paint(new Set(G.nodes.filter(n => [n.title, n.sub, ...(n.lines || []), (G.kinds[n.kind] || {}).name, ...(n.facts || []).reduce((all, f) => all.concat(f), []), ...(n.items || []).map(p => p.name), ...(n.items || []).reduce((all, p) => all.concat((p.more || []).map(m => m[1])), []), (n.source || {}).path, (n.source || {}).key].join(' ').toLowerCase().includes(q)).map(n => n.id)), new Set()); }
map.addEventListener('click', ev => { const act = ev.target.closest('[data-action]');      /* 磁贴正面的按钮：只发动作，不选中磁贴 */
  if (act) { if (!act.disabled) runAction(api, S, act); return; }
  const t = ev.target.closest('.tile'); select(t ? (t.dataset.id === selected ? null : t.dataset.id) : null); }, on);
/* 列表内筛选：不重画（重画会丢掉输入焦点），只改每条的 hidden */
function applyFilter(id) { const q = filters.get(id) || '';
  document.getElementById('detail').querySelectorAll('.list .item').forEach(it => { const r = lastRows.get(it.dataset.row); it.hidden = !!r && !rowMatches(r, q); }); }
document.getElementById('detail').addEventListener('input', ev => { const f = ev.target.closest('[data-filter]'); if (!f) return;
  filters.set(f.dataset.filter, f.value); applyFilter(f.dataset.filter); }, on);
document.getElementById('detail').addEventListener('click', ev => {
  const act = ev.target.closest('[data-action]'); if (act) return act.disabled || runAction(api, S, act);
  const tog = ev.target.closest('[data-toggle]'); if (tog) { const k = selected + '\u0000' + tog.dataset.toggle; if (expanded.has(k)) expanded.delete(k); else expanded.add(k); return detail(selected); }
  if (ev.target.closest('[data-expand-all]')) { expandAll = !expandAll; store.set('panorama-rows', expandAll ? 'all' : 'compact'); return detail(selected); }
  const go = ev.target.closest('[data-go]'); if (go) return select(go.dataset.go);
  const see = ev.target.closest('[data-view]'); if (see) return files.open(see.dataset.view, see.dataset.title);
  const set = ev.target.closest('[data-settings]'); if (set) return panel.open(set.dataset.settings, set.dataset.title);
  if (ev.target.closest('[data-memory]')) return memo.open();
  const cp = ev.target.closest('[data-copy]'); if (cp) { navigator.clipboard?.writeText(cp.dataset.copy); cp.textContent = S.copied; } }, on);
document.getElementById('quests').innerHTML = !G.quests.length ? `<p class="hint">${esc(S.no_quests)}</p>` : G.quests.map(q => `<div class="quest" data-go="${q.node}"><i class="dot ${q.sev}"></i><span>${esc(q.text)}</span>${actionButton(S, q, api)}</div>`).join('');
document.getElementById('quests').addEventListener('click', ev => {
  const act = ev.target.closest('[data-action]'); if (act) return act.disabled || runAction(api, S, act);
  const q = ev.target.closest('[data-go]'); if (q && N[q.dataset.go]) select(q.dataset.go); }, on);
document.getElementById('lines').innerHTML = Object.entries(G.lines).map(([k, l]) => `<button class="chip" data-line="${k}" title="${esc(l.tip)}"><i style="background:${l.color}"></i>${esc(l.name)}</button>`).join('');
document.getElementById('lines').addEventListener('click', ev => { const c = ev.target.closest('[data-line]'); if (!c) return;
  pickLine(c.dataset.line === lineOn ? null : c.dataset.line); }, on);
document.getElementById('q').addEventListener('input', ev => search(ev.target.value), on);
document.getElementById('motion').addEventListener('click', ev => { const still = document.body.classList.toggle('still'); ev.target.textContent = still ? S.motion_off : S.motion_on; }, on);
const sample = (st, text) => `<span><svg width="54" height="12"><g class="edge st-${st}" style="--lc:#3fc9bb"><path class="rail" d="${st === 'broken' ? 'M2 6H20M34 6H52' : 'M2 6H52'}"/><path class="flow" d="M2 6H52"/>${st === 'broken' ? '<g class="cut" transform="translate(27 6) scale(.7)"><circle r="7.5"/><path d="M-3 -3L3 3M3 -3L-3 3"/></g>' : ''}</g></svg>${text}</span>`;
document.getElementById('legend').innerHTML = ['live', 'ok', 'warn', 'broken', 'unknown', 'off'].map(st => sample(st, esc(ESTATE[st]))).join('');
function fit() { const st = document.getElementById('stage'), s = Math.max(.45, Math.min(1.3, st.clientWidth / W));
  map.style.transform = `scale(${s})`; st.style.height = Math.ceil(H * s) + 14 + 'px'; }
addEventListener('resize', fit, on); fit();
/* 右栏宽度：拖两列之间的把手改 --aside-w，松手存起来，双击复原；地图跟着重算缩放。单栏（窄屏）时把手藏着。 */
const gutter = document.getElementById('gutter'), rootStyle = document.documentElement && document.documentElement.style;
function setAside(px, persist) { if (!rootStyle || !rootStyle.setProperty) return; const w = clampAside(px); rootStyle.setProperty('--aside-w', w + 'px');
  if (persist) store.set('panorama-aside', String(w)); fit(); }
if (gutter) { gutter.title = S.gutter_tip || ''; const saved = store.get('panorama-aside'); if (saved) setAside(saved);
  gutter.addEventListener('pointerdown', ev => { ev.preventDefault(); gutter.classList.add('drag'); let last = null;
    const move = e => { last = clampAside(innerWidth - e.clientX - 16); setAside(last); };
    const up = () => { gutter.classList.remove('drag'); removeEventListener('pointermove', move); removeEventListener('pointerup', up); if (last !== null) setAside(last, true); };
    addEventListener('pointermove', move); addEventListener('pointerup', up); }, on);
  gutter.addEventListener('dblclick', () => setAside(380, true), on); }
document.getElementById('title').textContent = S.title;
document.getElementById('q').placeholder = S.search_placeholder;
document.getElementById('motion').textContent = document.body.classList.contains('still') ? S.motion_off : S.motion_on;
document.getElementById('memory-open').textContent = S.memory_button;
document.getElementById('memory-open').addEventListener('click', () => memo.open(), on);
document.getElementById('quests-title').textContent = S.quests_title;
document.getElementById('meta').textContent = G.meta.summary;
document.getElementById('foot').textContent = S.footer;
/* WSL 那半张图还在后台探测：这里只管提示条露不露；怎么等到新数据由 boot.js 管 */
const pending = document.getElementById('pending'); pending.hidden = !G.meta.pending; if (G.meta.pending) pending.textContent = S.pending;
detail(null);
/* 重画之后把用户正看着的东西放回去：选中的节点优先，其次是线路筛选，再其次是搜索词 */
if (kept && kept.selected && N[kept.selected]) select(kept.selected);
else if (kept && kept.lineOn && G.lines[kept.lineOn]) pickLine(kept.lineOn);
else if (kept && kept.query) { document.getElementById('q').value = kept.query; search(kept.query); }
/* 翻到某一组设置：选中管它的那块磁贴，打开它的设置面板（设置窗口里「到配置全景里改」经网址传来） */
function openSettings(group) { const n = G.nodes.find(m => m.settings === group);
  if (!n || !api) return false;
  select(n.id); panel.open(group, n.title); return true; }
return {select: id => select(N[id] ? id : null), openSettings,
  capture: () => ({selected, lineOn, query: document.getElementById('q').value}),
  dispose: () => off.abort()};
}
