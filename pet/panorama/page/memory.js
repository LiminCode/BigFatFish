/* 记忆一览：按作用域把记忆列出来——每台机器一栏，栏里先是全局（CLAUDE.md 受管块里的规矩），再是各个项目。
   重复的、像是放错了作用域的带一个小标记，悬停说明另一份在哪。「只看有标记的」把没问题的收起来。

   数据在图里（G.memory，由 sources.memory_view 配好了文字），这里只管画，不向服务要东西。
   带 view 的条目能点「查看」：交给 openFile（文件查看面板）；离线快照没有服务，openFile 是空的，就不给按钮。
   名字和说明都是别人写的文字：一律转义。 */
import {esc} from './util.js';

export function memory(G, S, on, openFile) {
const box = document.getElementById('memory');
const sides = (G.memory || {}).sides || [];
let only = false;
const keep = row => !only || (row.flags || []).length > 0;
const marks = row => (row.flags || []).map(f => `<i class="flag f-${esc(f.kind)}" title="${esc(f.tip)}">${esc(f.label)}</i>`).join('');
const peek = (row, title) => row.view && openFile
  ? `<button class="peek" data-store="${esc(row.view.store)}" data-path="${esc(row.view.path)}" data-title="${esc(title)}">${esc(S.view)}</button>` : '';
const line = (title, kind, text, row) => `<div class="mrow"><div><b>${esc(title)}</b>${kind ? `<em>${esc(kind)}</em>` : ''}${marks(row)}${peek(row, title)}</div>` +
  (text ? `<p>${esc(text)}</p>` : '') + `</div>`;
function column(side) {
  const rules = side.rules.filter(keep);
  const projects = side.projects.map(p => ({p: p, rows: p.entries.filter(keep)})).filter(x => x.rows.length);
  return `<section><h3>${esc(side.title)}<small>${esc(S.memory_count.replace('{n}', side.counts.entries))}</small></h3>` +
    `<h4>${esc(S.memory_global)}<small>${rules.length}</small></h4>` +
    (rules.length ? rules.map(r => line(r.title, '', r.text, r)).join('') : `<p class="hint">${esc(S.memory_none)}</p>`) +
    (!only && side.sections.length ? `<p class="hint">${esc(S.memory_own)}${esc(side.sections.join(' · '))}</p>` : '') +
    projects.map(x => `<h4 title="${esc(x.p.name)}">${esc(S.memory_project)} · ${esc(x.p.label)}<small>${x.rows.length}</small></h4>` +
      x.rows.map(e => line(e.name, e.type, e.description, e)).join('')).join('') +
    (side.truncated ? `<p class="hint">${esc(S.memory_truncated)}</p>` : '') + `</section>`;
}
function draw() {
  box.innerHTML = `<div class="sheet"><header><b>${esc(S.memory_title)}</b>` +
    `<button class="btn" data-only="1">${esc(only ? S.memory_all : S.memory_only_flagged)}</button>` +
    `<button class="btn" data-close="1">${esc(S.viewer_close)}</button></header>` +
    `<p class="mnote">${esc(S.memory_note)}</p><div class="mbody">${sides.map(column).join('') || `<p class="hint">${esc(S.memory_empty)}</p>`}</div></div>`;
}
function open(flagged) { only = !!flagged; box.hidden = false; draw(); }
function close() { box.hidden = true; box.innerHTML = ''; }
box.addEventListener('click', ev => {
  if (ev.target === box || ev.target.closest('[data-close]')) return close();
  if (ev.target.closest('[data-only]')) { only = !only; return draw(); }
  const see = ev.target.closest('[data-store]'); if (see && openFile) openFile(see.dataset.store, see.dataset.title, see.dataset.path); }, on);
/* Esc 一次只关最上面那一层：文件查看面板先处理并标记了这次按键，这里就不动 */
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !box.hidden && !ev.defaultPrevented) close(); }, on);
return {open, close};
}
