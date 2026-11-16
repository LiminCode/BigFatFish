/* 交互与侧栏：点磁贴追踪、详情、待处理、线路筛选、搜索、动效开关、缩放，以及页面上的固定文字。 */
import {esc} from './util.js';

export function interact(M, E, map) {
const {G, R, N, W, H} = M;
const S = G.strings, STATE = S.state, ESTATE = S.edge_state;
let selected = null, lineOn = null;
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
  const link = src.path ? (src.env === 'wsl' ? `vscode://vscode-remote/wsl+${src.distro}${src.path}` : 'vscode://file/' + src.path.replace(/\\/g, '/')) : '';
  const rows = (n.items || []).slice().sort((a, b) => (a.state === 'ok') - (b.state === 'ok'));
  const nb = (list, key) => list.map(e => `<button data-go="${e[key]}"><i class="dot ${e.state === 'broken' ? 'bad' : e.state}"></i>${esc(N[e[key]].title)}${e.label ? ' · ' + esc(e.label) : ''}<span style="color:var(--muted)">${ESTATE[e.state]}</span></button>`).join('');
  box.innerHTML = `<h2>${esc(k.name || n.kind)} · ${esc(R[n.region].title)}</h2><h3>${esc(n.title)}</h3>
    <div style="display:flex;gap:8px;align-items:center;font-size:12.5px;margin-top:4px"><i class="dot ${n.state}"></i>${STATE[n.state] || ''}</div>
    <dl class="kv">${(n.facts || []).filter(f => f[1] !== undefined && f[1] !== null && f[1] !== '').map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join('')}</dl>
    ${rows.length ? `<div class="list">${rows.map(r => `<div><i class="dot ${r.state === 'auth' ? 'warn' : r.state}"></i>${esc(r.name)}<small>${esc(r.detail || '')}</small></div>`).join('')}</div>` : ''}
    ${src.path ? `<div class="path">${esc(src.path)}${src.key ? '<br>→ ' + esc(src.key) : ''}</div>` : ''}
    <div class="btns">${link ? `<a class="btn" href="${esc(link)}">${esc(S.open_vscode)}</a><button class="btn" data-copy="${esc(src.path)}">${esc(S.copy_path)}</button>` : ''}
      ${n.page ? `<span class="btn ghost" title="${esc(S.settings_hint)}">${esc(S.settings_at.replace('{page}', n.page))}</span>` : ''}</div>
    ${out.length ? `<h2 style="margin-top:14px">${esc(S.uses)}</h2><div class="nb">${nb(out, 'to')}</div>` : ''}
    ${inn.length ? `<h2 style="margin-top:14px">${esc(S.used_by)}</h2><div class="nb">${nb(inn, 'from')}</div>` : ''}`; }
map.addEventListener('click', ev => { const t = ev.target.closest('.tile'); select(t ? (t.dataset.id === selected ? null : t.dataset.id) : null); });
document.getElementById('detail').addEventListener('click', ev => {
  const go = ev.target.closest('[data-go]'); if (go) return select(go.dataset.go);
  const cp = ev.target.closest('[data-copy]'); if (cp) { navigator.clipboard?.writeText(cp.dataset.copy); cp.textContent = S.copied; } });
document.getElementById('quests').innerHTML = !G.quests.length ? `<p class="hint">${esc(S.no_quests)}</p>` : G.quests.map(q => `<div class="quest" data-go="${q.node}"><i class="dot ${q.sev}"></i><span>${esc(q.text)}</span></div>`).join('');
document.getElementById('quests').addEventListener('click', ev => { const q = ev.target.closest('[data-go]'); if (q && N[q.dataset.go]) select(q.dataset.go); });
document.getElementById('lines').innerHTML = Object.entries(G.lines).map(([k, l]) => `<button class="chip" data-line="${k}" title="${esc(l.tip)}"><i style="background:${l.color}"></i>${esc(l.name)}</button>`).join('');
document.getElementById('lines').addEventListener('click', ev => { const c = ev.target.closest('[data-line]'); if (!c) return;
  const k = c.dataset.line === lineOn ? null : c.dataset.line; select(null); lineOn = k;
  document.querySelectorAll('#lines .chip').forEach(x => x.classList.toggle('active', x.dataset.line === k)); if (!k) return;
  const ns = new Set(), es = new Set(); E.forEach((e, i) => { if (e.line === k) { es.add(i); ns.add(e.from); ns.add(e.to); } }); paint(ns, es); });
document.getElementById('q').addEventListener('input', ev => { const q = ev.target.value.trim().toLowerCase(); if (!q) return paint(null, null);
  paint(new Set(G.nodes.filter(n => [n.title, n.sub, ...(n.lines || []), (G.kinds[n.kind] || {}).name, ...(n.facts || []).flat(), ...(n.items || []).map(p => p.name), (n.source || {}).path, (n.source || {}).key].join(' ').toLowerCase().includes(q)).map(n => n.id)), new Set()); });
document.getElementById('motion').addEventListener('click', ev => { const still = document.body.classList.toggle('still'); ev.target.textContent = still ? S.motion_off : S.motion_on; });
const sample = (st, text) => `<span><svg width="54" height="12"><g class="edge st-${st}" style="--lc:#3fc9bb"><path class="rail" d="${st === 'broken' ? 'M2 6H20M34 6H52' : 'M2 6H52'}"/><path class="flow" d="M2 6H52"/>${st === 'broken' ? '<g class="cut" transform="translate(27 6) scale(.7)"><circle r="7.5"/><path d="M-3 -3L3 3M3 -3L-3 3"/></g>' : ''}</g></svg>${text}</span>`;
document.getElementById('legend').innerHTML = ['live', 'ok', 'warn', 'broken', 'unknown', 'off'].map(st => sample(st, esc(ESTATE[st]))).join('');
function fit() { const st = document.getElementById('stage'), s = Math.max(.45, Math.min(1.3, st.clientWidth / W));
  map.style.transform = `scale(${s})`; st.style.height = Math.ceil(H * s) + 14 + 'px'; }
addEventListener('resize', fit); fit();
document.getElementById('title').textContent = S.title;
document.getElementById('q').placeholder = S.search_placeholder;
document.getElementById('motion').textContent = S.motion_on;
document.getElementById('quests-title').textContent = S.quests_title;
document.getElementById('meta').textContent = G.meta.summary;
document.getElementById('foot').textContent = S.footer;
/* WSL 那半张图还在后台探测：这里只把提示条露出来；怎么等到新数据由 boot.js 管 */
if (G.meta.pending) { const p = document.getElementById('pending'); p.hidden = false; p.textContent = S.pending; }
detail(null);
}
