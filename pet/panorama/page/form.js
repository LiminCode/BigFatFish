/* 设置表单：按本机服务给的描述（GET /api/settings/<组>）画一组设置，改了就交出去。

   页面里没有任何一项设置的名字：画什么、叫什么、能选什么都在描述里（pet/panorama/settings_api.describe），
   能不能存由服务说了算（pet/settings_table.check_changes）。这里只管三件事：
   - 画八种控件：开关、下拉、可自填的下拉、数字、单行文本、长文本、一行一个的列表、记录表（records：几列文本，一行一条，
     可加行 / 删行，整张表一个「保存」）；收在「高级」里的默认折起来；
   - 什么时候交：开关、下拉、数字一动就交；文本和列表等用户点「保存」，没存的标出来，可以撤销；
   - 服务每一种回答的样子：存上了 / 值已经变了（换成现在的值）/ 哪几项不对 / 忙 / 用不了 / 连接断了。
   用户打到一半的文字，除非存上了，否则任何回答都不会把它冲掉。

   长文本可以有「内置文字」（builtin）：值为空时功能实际用的那一段。框里没写东西时显示它；
   存的时候文字和内置的一样，就存空（= 继续用内置，内置以后更新了也跟着更新），和 Qt 设置窗口的提示词编辑器一个规矩。

   一项可以带一个动作按钮（描述里的 action，现在只有「试听」）：点了把组、项和此刻选着的值交给 act(name, body)，
   回答写在状态行上（played / missing / failed / 连不上），不改任何值、不锁表单。

   send(changes, base) 返回一个 Promise，结果是 {status, body}；连不上就 reject。页面上怎么发请求由调用方定。
   act(name, body) 同样（动作走 POST /api/actions/<name>）；不给 act 就不画动作按钮。
   所有来自服务的文字都转义后再进页面。 */
import {esc} from './util.js';

export function settingsForm(host, S, send, on, act) {
const CUSTOM = '__custom__';
let st = null;
const row = id => st.desc.settings.find(r => r.id === id);
const textual = r => r.control === 'text' || r.control === 'long_text' || r.control === 'lines' || r.control === 'records';
const listy = r => r.control === 'lines';
const recordy = r => r.control === 'records';
const hasBuiltin = r => r.builtin !== null && r.builtin !== undefined;
/* 文本框里的字存下去是什么：去掉首尾空白；和内置文字一样就是空。列表：一行一项，去掉首尾空白，空行不要 */
const stored = (r, text) => {
  if (listy(r)) return String(text).split('\n').map(s => s.trim()).filter(Boolean);
  if (recordy(r)) return (text || []).map(row => { const o = {}; r.fields.forEach(f => { o[f.id] = String(row[f.id] || '').trim(); }); return o; })
    .filter(o => r.fields.some(f => o[f.id]));   /* 全空的行不要：和服务那边 _as_stored 一样 */
  const v = String(text).trim(); return hasBuiltin(r) && v === String(r.builtin).trim() ? '' : v;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const dirty = r => textual(r) && r.id in st.drafts && !same(stored(r, st.drafts[r.id]), r.value);
/* 正在交出去的那个值先显示出来（不然开关点了会先弹回去再跳过来） */
const shown = r => st.busy && r.id in st.pending ? st.pending[r.id] : r.value;
const locked = r => st.busy || !st.desc.available || (!!r.depends_on && !!row(r.depends_on) && shown(row(r.depends_on)) !== true);
const idOf = r => `f-${st.desc.group}-${r.id}`.replace(/[^\w-]/g, '-');
function say(text, tone) { st.status = text; st.tone = tone || ''; }

function buttons(r) {
  const d = dirty(r), off = locked(r), key = esc(r.id), dis = cond => cond ? ' disabled' : '';
  return `<div class="fbtns"><button class="btn" data-save="${key}"${dis(!d || off)}>${esc(S.form_save)}</button>` +
    `<button class="btn ghost-btn" data-revert="${key}"${dis(!d || off)}>${esc(S.form_revert)}</button>` +
    (hasBuiltin(r) ? `<button class="btn ghost-btn" data-builtin="${key}"${dis(off)}>${esc(S.form_restore_builtin)}</button>` +
      (r.value === '' && !d ? `<small class="fnote">${esc(S.form_using_builtin)}</small>` : '') : '') +
    (d ? `<small class="fdirty">${esc(S.form_dirty)}</small>` : '') + '</div>';
}

const bounded = r => r.min != null && r.max != null;
const whole = r => bounded(r) && Number.isInteger(r.min) && Number.isInteger(r.max);
const range = r => bounded(r) ? ` min="${esc(r.min)}" max="${esc(r.max)}"${whole(r) ? ' step="1"' : ''}` : '';

/** 一个数字放不放得进声明的范围：放不进返回错误代码（和服务那边同名），放得进返回空串。 */
function numberError(r, n) {
  if (!bounded(r)) return '';
  if (n < r.min || n > r.max) return 'out_of_range';
  return whole(r) && !Number.isInteger(n) ? 'type' : '';
}

function errorText(r, code) {
  const text = S['form_err_' + code] || S.form_err_rejected;
  return code === 'out_of_range' && bounded(r) ? text.replace('{min}', r.min).replace('{max}', r.max) : text;
}

/* 选项上显示什么：服务给了文字就是「文字 · 值」（值是空串时只有文字），没给就是值本身 */
const optionText = (r, c, i) => { const name = r.labels && r.labels[i]; return name ? (c === '' ? name : `${name} · ${c}`) : c; };

function control(r) {
  const id = idOf(r), key = esc(r.id), off = locked(r) ? ' disabled' : '', value = shown(r);
  if (r.control === 'toggle') return `<input type="checkbox" role="switch" data-set="${key}"${value === true ? ' checked' : ''}${off} id="${id}">`;
  if (r.control === 'number') return `<input type="number" data-set="${key}" value="${esc(value)}"${range(r)}${off} id="${id}">` +
    (r.unit ? `<span class="funit">${esc(r.unit)}</span>` : '');
  if (r.control === 'choice' || r.control === 'choice_or_text') {
    const free = r.control === 'choice_or_text', custom = free && (!!st.custom[r.id] || r.choices.indexOf(value) < 0);
    const options = r.choices.map((c, i) => `<option value="${esc(c)}"${!custom && String(c) === String(value) ? ' selected' : ''}>${esc(optionText(r, c, i))}</option>`).join('') +
      (free ? `<option value="${CUSTOM}"${custom ? ' selected' : ''}>${esc(S.form_custom)}</option>` : '');
    return `<select data-set="${key}"${off} id="${id}">${options}</select>` + (custom ?
      `<input type="text" class="fcustom" data-custom="${key}" value="${esc(r.choices.indexOf(value) < 0 ? value : '')}"${off} aria-label="${esc(S.form_custom_label)}">` : '');
  }
  if (recordy(r)) {
    const rows = r.id in st.drafts ? st.drafts[r.id] : (r.value || []), k = esc(r.id);
    const head = '<tr>' + r.fields.map(f => `<th>${esc(f.title)}</th>`).join('') + '<th></th></tr>';
    const body = rows.map((row, i) => '<tr>' + r.fields.map(f =>
      `<td><input type="text" data-rec="${k}" data-i="${i}" data-f="${esc(f.id)}" value="${esc(row[f.id] || '')}"${off} aria-label="${esc(f.title)}"></td>`).join('') +
      `<td><button class="btn ghost-btn frec-del" data-del="${k}" data-i="${i}"${off} title="${esc(S.form_delete_row)}">×</button></td></tr>`).join('');
    return `<table class="frecords" id="${id}">${head}${body}</table><button class="btn ghost-btn" data-add="${k}"${off}>${esc(S.form_add_row)}</button>` + buttons(r);
  }
  const text = r.id in st.drafts ? st.drafts[r.id] : listy(r) ? (r.value || []).join('\n') : (r.value === '' && hasBuiltin(r) ? r.builtin : r.value);
  if (r.control === 'text') return `<input type="text" data-draft="${key}" value="${esc(text)}"${off} id="${id}">` + buttons(r);
  return `<textarea data-draft="${key}"${off} id="${id}" rows="${hasBuiltin(r) ? 12 : listy(r) ? 3 : 4}" spellcheck="false">${esc(text)}</textarea>` + buttons(r);
}

/* 一项旁边的动作按钮（试听）：文字按动作名取（form_<动作名>），锁着的项它也灰 */
const actionBtn = r => !r.action || !act ? '' :
  `<button class="btn mini fact" data-act="${esc(r.id)}"${locked(r) ? ' disabled' : ''}>${esc(S['form_' + r.action] || S.form_preview)}</button>`;

function rowHtml(r) {
  const error = st.errors[r.id];
  return `<div class="frow f-${esc(r.control)}${r.control === 'long_text' || listy(r) || recordy(r) ? ' stacked' : ''}${dirty(r) ? ' dirty' : ''}${error ? ' bad' : ''}" data-row="${esc(r.id)}">` +
    `<div class="flabel"><label for="${idOf(r)}">${esc(r.title)}</label>${r.hint ? `<small>${esc(r.hint)}</small>` : ''}</div>` +
    `<div class="fctl">${control(r)}${actionBtn(r)}</div>` +
    (error ? `<p class="ferr" role="alert">${esc(errorText(r, error))}</p>` : '') + '</div>';
}

function draw() {
  const primary = st.desc.settings.filter(r => r.disclosure !== 'advanced'), advanced = st.desc.settings.filter(r => r.disclosure === 'advanced');
  host.innerHTML = `<div class="sform" data-group="${esc(st.desc.group)}">` +
    `<p class="fstatus${st.tone ? ' ' + st.tone : ''}" role="status" aria-live="polite">${esc(st.status)}</p>` +
    (st.desc.available ? '' : `<p class="funavail">${esc(st.desc.unavailable || S.form_unavailable)}</p>`) +
    primary.map(rowHtml).join('') +
    (advanced.length ? `<button class="fadv" data-advanced="" aria-expanded="${st.advanced}">${esc(S.form_advanced.replace('{n}', advanced.length))}</button>` +
      (st.advanced ? advanced.map(rowHtml).join('') : '') : '') + '</div>';
}

/* 打字的时候不整张重画（会丢掉光标）：只换掉这一行的按钮和「没保存」标记 */
function refresh(r) {
  const box = host.querySelector(`[data-row="${r.id}"]`);
  if (!box) return;
  box.classList.toggle('dirty', dirty(r));
  const old = box.querySelector('.fbtns');
  if (old) old.outerHTML = buttons(r);
}

function land(reply, ids) {
  st.busy = false;
  st.pending = {};
  const body = (reply && reply.body) || {};
  const status = reply && reply.status;
  if (status === 200) { st.desc = body; ids.forEach(id => { delete st.drafts[id]; }); say(S.form_saved, 'ok'); }
  else if (status === 409 && body.error === 'stale' && body.current) { st.desc = body.current; say(S.form_stale, 'warn'); }
  else if (status === 422) { (body.errors || []).forEach(e => { st.errors[e.id] = e.code; }); say(S.form_invalid, 'bad'); }
  else if (status === 409 && body.error === 'unavailable') { st.desc.available = false; say(S.form_unavailable, 'bad'); }
  else if (status === 503) say(S.form_busy, 'warn');
  else say(S.form_failed, 'bad');
  draw();
}

function commit(changes) {
  if (st.busy || !st.desc.available) return draw();
  const ids = Object.keys(changes);
  ids.forEach(id => { delete st.errors[id]; });
  st.busy = true;
  st.pending = changes;
  say(S.form_saving);
  draw();
  send(changes, st.desc.version).then(reply => land(reply, ids), () => { st.busy = false; st.pending = {}; say(S.form_lost, 'bad'); draw(); });
}

host.addEventListener('change', ev => {
  const free = ev.target.closest('[data-custom]');
  if (free) { const r = row(free.dataset.custom), v = String(free.value).trim(); if (r && v && !locked(r)) commit({[r.id]: v}); return; }
  const t = ev.target.closest('[data-set]');
  if (!t) return;
  const r = row(t.dataset.set);
  if (!r || locked(r)) return draw();
  if (r.control === 'toggle') return commit({[r.id]: !!t.checked});
  if (r.control === 'number') {
    const n = Number(t.value);
    if (String(t.value).trim() === '' || !isFinite(n)) { st.errors[r.id] = 'type'; return draw(); }
    const wrong = numberError(r, n);
    if (wrong) { st.errors[r.id] = wrong; return draw(); }
    return commit({[r.id]: n});
  }
  if (r.control === 'choice_or_text' && t.value === CUSTOM) { st.custom[r.id] = true; return draw(); }
  st.custom[r.id] = false;
  /* <option> 的值只能是字串；可选值可以是整数（详情卡文字大小）——交回去前换回声明的那个值 */
  const picked = r.choices.find(c => String(c) === String(t.value));
  commit({[r.id]: picked === undefined ? t.value : picked});
}, on);
/* 记录表的草稿是一组对象：第一次改时从当前值复制一份（每行一个新对象，不碰服务给的那份） */
const recDraft = r => { if (!(r.id in st.drafts)) st.drafts[r.id] = (r.value || []).map(row => Object.assign({}, row)); return st.drafts[r.id]; };
host.addEventListener('input', ev => {
  const cell = ev.target.closest('[data-rec]');
  if (cell) {
    const r = row(cell.dataset.rec);
    if (!r || locked(r)) return;
    const rows = recDraft(r), i = +cell.dataset.i;
    if (rows[i]) { rows[i][cell.dataset.f] = cell.value; refresh(r); }
    return;
  }
  const t = ev.target.closest('[data-draft]');
  const r = t && row(t.dataset.draft);
  if (!r || locked(r)) return;
  st.drafts[r.id] = t.value;
  refresh(r);
}, on);
/* 动作：把此刻选着的值交出去，回答只写在状态行上。不锁表单、不动任何值 */
function runAct(r) {
  say(S.form_preview_working);
  draw();
  act(r.action, {group: st.desc.group, id: r.id, value: shown(r)}).then(reply => {
    const state = reply && reply.status === 200 && reply.body && reply.body.state ? reply.body.state : 'failed';
    say(S['form_preview_' + state] || S.form_preview_failed, state === 'played' ? 'ok' : 'bad');
    draw();
  }, () => { say(S.form_lost, 'bad'); draw(); });
}

host.addEventListener('click', ev => {
  if (ev.target.closest('[data-advanced]')) { st.advanced = !st.advanced; return draw(); }
  const go = ev.target.closest('[data-act]');
  if (go) { const r = row(go.dataset.act); if (r && r.action && act && !locked(r)) runAct(r); return; }
  const save = ev.target.closest('[data-save]');
  if (save) { const r = row(save.dataset.save); if (r && dirty(r) && !locked(r)) commit({[r.id]: stored(r, st.drafts[r.id])}); return; }
  const back = ev.target.closest('[data-revert]');
  if (back) { delete st.drafts[back.dataset.revert]; return draw(); }
  const builtin = ev.target.closest('[data-builtin]');
  if (builtin) { const r = row(builtin.dataset.builtin); if (r && !locked(r)) { st.drafts[r.id] = r.builtin; draw(); } return; }
  const add = ev.target.closest('[data-add]');
  if (add) { const r = row(add.dataset.add); if (r && !locked(r)) { const o = {}; r.fields.forEach(f => { o[f.id] = ''; }); recDraft(r).push(o); draw(); } return; }
  const del = ev.target.closest('[data-del]');
  if (del) { const r = row(del.dataset.del); if (r && !locked(r)) { recDraft(r).splice(+del.dataset.i, 1); draw(); } }
}, on);

return {
  show(desc) { st = {desc: desc, drafts: {}, custom: {}, errors: {}, pending: {}, status: '', tone: '', busy: false, advanced: false}; draw(); },
  state: () => ({version: st.desc.version, errors: Object.assign({}, st.errors), dirty: st.desc.settings.filter(dirty).map(r => r.id), busy: st.busy}),
};
}
