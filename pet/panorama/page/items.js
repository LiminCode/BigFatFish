/* 简报页的纯函数：给一条 <li> 分类、按筛选判断显不显示、左栏磁贴 / 筛选片 / 右栏卡片的 HTML。
   不碰 DOM、不认识具体功能（只认识「几区、每区几条、每条有没有 ★ / bug / 有更新」），测试里直接调。 */
import {esc} from './util.js';

var PRIORITY = /^\s*<span class="star s([123])">/;
var FILTERS = ['p3', 'p2', 'p1', 'bug', 'upd'];

/* 一条的分类：优先级（渲染器把开头的 ★ 变成 <span class="star sN">）、bug（<li class="bug">）、有更新（行里的 <strong>） */
export function classify(html, className) {
  var m = PRIORITY.exec(String(html || ''));
  return {p: m ? +m[1] : 0, bug: /(^|\s)bug(\s|$)/.test(String(className || '')), upd: /<strong>/.test(String(html || ''))};
}

/* 选中的筛选片（数组，空 = 全部；多选取并集）+「隐藏已勾掉」→ 这条显不显示 */
export function passes(item, filters, hideDone) {
  if (hideDone && item.done) return false;
  if (!filters.length) return true;
  return filters.some(function (f) { return f === 'bug' ? item.bug : f === 'upd' ? item.upd : item.p === +f.slice(1); });
}

function countText(strings, key, count) { return esc(String(strings[key] || '{n}').replace('{n}', count)); }

export function navTiles(sections, strings) {
  return sections.map(function (s) {
    return '<a class="tile src-' + esc(s.source) + '" href="#' + esc(s.id) + '" data-go="' + esc(s.id) + '">' +
      '<span class="t">' + esc(s.title || strings.report_untitled) + '</span><span class="n">' + countText(strings, 'report_items', s.count) + '</span></a>';
  }).join('');
}

export function filterChips(filters, hideDone, strings) {
  var chips = [{f: '', label: strings.report_filter_all, on: !filters.length}].concat(FILTERS.map(function (f) {
    return {f: f, label: strings['report_filter_' + f], on: filters.indexOf(f) >= 0};
  }));
  return chips.map(function (c) {
    return '<button class="chip' + (c.on ? ' on' : '') + '" data-f="' + c.f + '" aria-pressed="' + c.on + '">' + esc(c.label) + '</button>';
  }).join('') + '<label class="hide"><input type="checkbox" id="hide-done"' + (hideDone ? ' checked' : '') + '> ' + esc(strings.report_hide_done) + '</label>';
}

export function card(s, strings, collapsed) {
  var badges = [['p3', s.p3, '★★★'], ['bug', s.bugs, '🐞'], ['upd', s.updated, strings.report_filter_upd]].filter(function (b) { return b[1] > 0; })
    .map(function (b) { return '<span class="badge ' + b[0] + '">' + esc(b[2]) + ' ' + b[1] + '</span>'; }).join('');
  return '<section class="card src-' + esc(s.source) + '" id="' + esc(s.id) + '"' + (collapsed ? ' data-collapsed="1"' : '') + '>' +
    '<header class="head"><h3>' + esc(s.title || strings.report_untitled) + '</h3><span class="count">' + countText(strings, 'report_items', s.count) + '</span>' +
    badges + '<button class="fold" data-fold="' + esc(s.id) + '" aria-expanded="' + !collapsed + '" title="' + esc(strings.report_fold) + '">' +
    (collapsed ? '▸' : '▾') + '</button></header><div class="list">' + (s.html || '') + '</div></section>';
}
