/* 笔记页的纯函数：筛选、计数片、筛选片、左栏一行、右栏详情、仓库状态、Slack 检查状态条的 HTML。
   不碰 DOM、不认识具体功能（只认识「一条有标题 / 类型 / 状态 / 提醒 / 摘要 / 原文的东西」），测试里直接调。
   服务给的 details_html / original_html 是服务端渲染好的（markdown.py 只产出那几个标签，其余全转义），直接放；别的文字这里转义。 */
import {esc} from './util.js';

export const FILTERS = ['all', 'open', 'due', 'busy', 'done'];
var KINDS = ['slack', 'jira', 'confluence', 'link', 'text'];

function kindOf(note) { return KINDS.indexOf(note.kind) >= 0 ? note.kind : 'text'; }
function fill(text, values) { return String(text || '').replace(/\{(\w+)\}/g, function (_m, key) { return key in values ? values[key] : '{' + key + '}'; }); }

/* 筛选片的含义：全部 / 待办（未完成）/ 有提醒 / 总结中 / 已完成；搜索看标题、摘要、标签、类型 */
export function matches(note, filter, query) {
  if (filter === 'open' && !note.open) return false;
  if (filter === 'due' && !note.remind_at) return false;
  if (filter === 'busy' && !note.busy) return false;
  if (filter === 'done' && note.open) return false;
  var q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  var hay = [note.title, note.summary, (note.tags || []).join(' '), note.kind].join(' ').toLowerCase();
  return hay.indexOf(q) >= 0;
}

export function filterNotes(notes, filter, query) { return (notes || []).filter(function (n) { return matches(n, filter, query); }); }

export function countsHtml(counts, S) {
  var c = counts || {};
  var parts = [['open', c.open], ['due', c.due], ['done', c.done]];
  if (c.busy) parts.splice(2, 0, ['busy', c.busy]);
  return parts.map(function (p) {
    return '<span class="c ' + p[0] + '"><b>' + esc(p[1] || 0) + '</b>' + esc(fill(S['notes_count_' + p[0]], {n: ''}).trim()) + '</span>';
  }).join('');
}

export function filterChips(counts, filter, S) {
  var c = counts || {}, total = (c.open || 0) + (c.done || 0);
  var n = {all: total, open: c.open || 0, due: c.due || 0, busy: c.busy || 0, done: c.done || 0};
  return FILTERS.filter(function (f) { return f !== 'busy' || n.busy > 0; }).map(function (f) {
    return '<button class="chip' + (filter === f ? ' on' : '') + '" data-f="' + f + '" aria-pressed="' + (filter === f) + '">' +
      esc(S['notes_filter_' + f]) + '<span class="n">' + n[f] + '</span></button>';
  }).join('');
}

function remindText(note, S) {
  if (!note.remind_at) return '';
  return note.overdue ? '<span class="ov">' + esc(fill(S.notes_overdue, {when: note.remind_text})) + '</span>' : esc(fill(S.notes_remind, {when: note.remind_text}));
}

export function rowHtml(note, selected, S) {
  var cls = 'row kind-' + kindOf(note) + (selected ? ' sel' : '') + (note.open ? '' : ' done') + (note.busy ? ' busy' : '');
  var meta = [note.open ? remindText(note, S) : esc(S.notes_done_mark)].filter(Boolean);
  var tags = (note.tags || []).slice(0, 3).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('');
  var st = note.busy ? esc(S.notes_busy_short) : (note.open ? (note.remind_at ? '●' : '○') : '✓');
  return '<a class="' + cls + '" href="#" data-note="' + esc(note.name) + '" aria-current="' + (selected ? 'true' : 'false') + '">' +
    '<span class="rt"><span class="t">' + esc(note.title) + '</span><span class="m">' + meta.join(' · ') + tags + '</span></span>' +
    '<span class="st">' + st + '</span></a>';
}

export function rowsHtml(notes, selected, S) { return (notes || []).map(function (n) { return rowHtml(n, n.name === selected, S); }).join(''); }

function btn(op, label, extra) { return '<button class="btn ghost' + (extra || '') + '" data-op="' + op + '">' + esc(label) + '</button>'; }

export function detailHtml(note, S) {
  if (!note) return '<p class="pick">' + esc(S.notes_select) + '</p>';
  var kind = kindOf(note);
  var badges = [];
  if (note.busy) badges.push('<span class="badge">' + esc(S.notes_busy_short) + '</span>');
  if (!note.open) badges.push('<span class="badge">' + esc(S.notes_done_mark) + '</span>');
  else if (note.remind_at) badges.push('<span class="badge' + (note.overdue ? ' ov' : '') + '">' + esc(fill(note.overdue ? S.notes_overdue : S.notes_remind, {when: note.remind_text})) + '</span>');
  var meta = ['<span>' + esc(note.created_text) + '</span>'];
  if (note.open && note.reason) meta.push('<span>' + esc(note.reason) + '</span>');
  (note.tags || []).forEach(function (t) { meta.push('<span class="tag">' + esc(t) + '</span>'); });
  var body;
  if (note.busy) body = '<p class="summary busy">' + esc(S.notes_busy) + '</p>';
  else if (note.summary) body = '<p class="summary">' + esc(note.summary) + '</p>' + (note.details_html ? '<div class="points">' + note.details_html + '</div>' : '');
  else body = '<p class="summary note">' + esc(S.notes_no_summary) + '</p>';
  var usage = (note.usage || []).map(function (u) { return '<span class="u" title="' + esc(u.tip) + '">' + esc(u.text) + '</span>'; }).join('');
  var acts = [];
  if (note.open && !note.busy) acts.push('<button class="btn" data-op="done">' + esc(S.notes_btn_done) + '</button>');
  if ((note.links || []).length) acts.push(btn('open_link', S.notes_btn_link));
  acts.push(btn('obsidian', S.notes_btn_obsidian));
  acts.push('<button class="btn ghost" data-op="resummarize"' + (note.busy ? ' disabled' : '') + '>' + esc(S.notes_btn_resummarize) + '</button>');
  if (note.open) {
    acts.push('<span class="snz">' + esc(S.notes_snooze) + '<button class="chip" data-op="snooze" data-minutes="60">' + esc(S.notes_snooze_hour) + '</button>' +
      '<button class="chip" data-op="snooze" data-minutes="180">' + esc(S.notes_snooze_three) + '</button>' +
      '<button class="chip" data-op="snooze" data-minutes="-1">' + esc(S.notes_snooze_tomorrow) + '</button></span>');
  }
  acts.push(btn('delete', S.notes_btn_delete, ' danger'));
  return '<header class="head kind-' + kind + '"><span class="kind">' + esc(S['notes_kind_' + kind]) + '</span><h2>' + esc(note.title) + '</h2>' + badges.join('') + '</header>' +
    '<div class="body"><p class="meta">' + meta.join('') + '</p>' + body +
    '<div class="otitle">' + esc(S.notes_original) + '</div><pre class="orig">' + (note.original_html || '') + '</pre>' +
    (usage ? '<div class="usage">' + usage + '</div>' : '') +
    '<div class="acts" data-note="' + esc(note.name) + '">' + acts.join('') + '</div></div>';
}

/* 顶栏右边的仓库状态：正常时什么都不显示；仓库没找到 / git 失败时写原因，仓库在时再给「再推一次」 */
export function repoHtml(repo, S) {
  var r = repo || {};
  if (!r.status) return '';
  return '<span title="' + esc(r.status) + '">' + esc(r.status) + '</span>' + (r.ready ? btn('push', S.notes_btn_push) : '');
}

/* Slack 页的检查状态条：上次检查 · 发现几条 · 下一次约几点 · 概要 · 失败原因；按钮由页面另放 */
export function watchHtml(watch, S) {
  var w = watch || {};
  var bits = [];
  if (w.checked_text) bits.push('<span class="w">' + esc(fill(S.notes_watch_last, {when: w.checked_text, ago: w.ago_text || ''})) + '</span>');
  if (typeof w.found === 'number') bits.push('<span class="w"><b>' + w.found + '</b> ' + esc(fill(S.notes_watch_found, {n: ''}).trim()) + '</span>');
  if (w.next_text) bits.push('<span class="w">' + esc(fill(S.notes_watch_next, {when: w.next_text})) + '</span>');
  if (!bits.length) bits.push('<span class="w">' + esc(S.notes_watch_never) + '</span>');
  if (w.busy) bits.push('<span class="w busy">' + esc(S.notes_watch_busy) + '</span>');
  if (w.summary) bits.push('<p class="sum">' + esc(w.summary) + '</p>');
  if (w.error) bits.push('<span class="bad">' + esc(w.error) + '</span>');
  return bits.join('');
}
