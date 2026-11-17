/* 设置面板：功能磁贴上点「设置」→ 向本机服务要这一组的描述（GET /api/settings/<组>）→ 交给 form.js 画表单，
   改动经 PATCH 交回去（boot.js 给的 api.patch）。能不能改、改成什么样都由服务说了算，这里只管开、关、转交。

   **面板跨重画存活。** 改完设置服务会重新发布一次图，页面原地重画，interact() 会整个重跑——可打开着的面板和里面
   打了一半的字不能跟着没了。所以面板是整页只有一个的东西（live）：第一次调 settingsPanel() 时建，之后每次重画拿到的
   都是同一个；它的监听不挂在某一次画图的中止信号上，表单的监听挂在表单自己的宿主元素上，面板关掉时随元素一起扔掉。

   关面板时有没保存的文字：先在标题栏说一声，再关一次才丢。离线快照没有服务（api 是空的），open() 什么也不做。 */
import {esc} from './util.js';
import {settingsForm} from './form.js';

let live = null;

/* 表单的 send：把一次改动连同它所基于的版本交给服务；结果是 {status, body}，连不上就 reject */
export const sender = (api, group) => (changes, base) =>
  api.patch('/api/settings/' + encodeURIComponent(group), {base: base, changes: changes});

export function settingsPanel(api, S) {
if (live) return live;
const box = document.getElementById('settings');
let turn = 0, form = null, warned = false;       /* turn：每开一次加一，晚到的回答对不上号就丢掉 */
const part = id => document.getElementById(id);
const unsaved = () => !!form && form.state().dirty.length > 0;
function note(text) { part('settings-note').textContent = text; }
function open(group, title) {
  if (!api) return;
  if (!box.hidden && box.dataset.group === group) return;          /* 已经开着这一组：不重建，免得冲掉没保存的字 */
  if (unsaved()) { note(S.settings_unsaved); return; }
  const mine = ++turn; form = null; warned = false;
  box.dataset.group = group; box.hidden = false;
  box.innerHTML = `<div class="sheet settings-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title">` +
    `<header><b id="settings-title">${esc(title)}</b><span class="snote" id="settings-note" role="status" aria-live="polite"></span>` +
    `<button class="btn" data-close="1">${esc(S.viewer_close)}</button></header>` +
    `<div class="sbody" id="settings-form"><p class="hint">${esc(S.viewer_loading)}</p></div></div>`;
  api('/api/settings/' + encodeURIComponent(group)).then(desc => { if (mine !== turn) return;
    form = settingsForm(part('settings-form'), S, sender(api, group), {});
    form.show(desc);
  }).then(null, () => { if (mine === turn) part('settings-form').innerHTML = `<p class="hint">${esc(S.settings_failed)}</p>`; });
}
/* 关上；有没保存的字时第一次只提醒，返回 false */
function close() {
  if (unsaved() && !warned) { warned = true; note(S.settings_unsaved); return false; }
  turn++; form = null; warned = false; box.hidden = true; box.innerHTML = ''; delete box.dataset.group;
  return true;
}
box.addEventListener('click', ev => { if (ev.target === box || ev.target.closest('[data-close]')) close(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !box.hidden) { ev.preventDefault(); close(); } });
live = {open, close, state: () => ({open: !box.hidden, group: box.dataset.group || '', form: form ? form.state() : null})};
return live;
}
