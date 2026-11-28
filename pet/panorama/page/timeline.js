/* 右栏里的时间轴：磁贴正面（或详情里）的「时间轴」带着 show=panel，点了不另开浏览器页，而是在右栏占详情那张卡的位置。

   数据和时间轴页（/report/activity）是同一份：先 GET /api/report/<名字> 要现成的（服务每次都重做一份），再带着编号去
   「等更新的」（?after=编号，服务挂住请求，刚同步 / 核对完就回），开着就一直等，关了就不再等。内容是服务端渲染好的
   .waterfall（activity.py，文字全转义过），直接放进去；样式是两张页面共用的 activity.css。
   面板头上「在新页面打开」走原来的动作（POST /api/actions/<名字>，按钮不带 show），「关闭」把详情放回来；点任一块磁贴也会关
   （interact.js 管）。打开时右栏不到 OPEN_WIDTH 就临时放宽到它，关掉时还原——不存，用户拖过的宽度照旧。

   **跨重画存活**：服务重新发布一次图，interact() 会整个重跑，可开着的时间轴不能跟着没了。所以和设置面板一样，整页只有一个
   （livePanel），监听挂在面板自己的元素上。离线快照没有服务（api 是空的），openFrom() 什么也不做。 */
import {esc, clampAside} from './util.js';
import {runAction} from './repair.js';

const OPEN_WIDTH = 640, RETRY_MS = 1000, RECONNECT_MS = 3000;
let livePanel = null;

export function timelinePanel(api, S) {
if (livePanel) return livePanel;
const box = document.getElementById('timeline'), detailCard = document.getElementById('detail');
const rootStyle = document.documentElement && document.documentElement.style;
let turn = 0, name = '', action = null, revision = 0, widened = null;   /* turn：每开一次、每关一次加一，晚到的回答对不上号就丢掉 */

function widen() { if (!rootStyle || !rootStyle.setProperty) return;
  const before = rootStyle.getPropertyValue('--aside-w') || '';
  if (clampAside(parseFloat(before) || 380) >= OPEN_WIDTH) return;
  widened = before; rootStyle.setProperty('--aside-w', OPEN_WIDTH + 'px');
  if (typeof dispatchEvent === 'function' && typeof Event === 'function') dispatchEvent(new Event('resize')); }  /* 地图跟着重算缩放 */
function narrow() { if (widened === null || !rootStyle) return;
  if (widened) rootStyle.setProperty('--aside-w', widened); else if (rootStyle.removeProperty) rootStyle.removeProperty('--aside-w');
  widened = null; if (typeof dispatchEvent === 'function' && typeof Event === 'function') dispatchEvent(new Event('resize')); }

function frame(title, meta, body) {
  const newTab = action ? `<button class="btn" data-action="${esc(action.name)}" data-words="${esc(action.words || '')}" data-ask="0"` +
    (action.body ? ` data-body="${esc(JSON.stringify(action.body))}"` : '') + `>${esc(S.timeline_newtab)}</button>` : '';
  box.innerHTML = `<div class="tlhead"><h2>${esc(title)}</h2>${newTab}<button class="btn" data-tl-close="1">${esc(S.viewer_close)}</button></div>` +
    (meta ? `<p class="tlmeta">${esc(meta)}</p>` : '') + `<div class="tlbody">${body}</div>`; }
function show(data) { const r = (data && data.report) || {};
  revision = data && data.revision || 0;
  frame(r.title || S.activity, [r.summary, r.generated].filter(Boolean).join(' · '),
        r.available === false ? `<p class="hint">${esc(r.empty_text || '')}</p>` : (r.html || `<p class="hint">${esc(r.empty_text || '')}</p>`)); }
function wait(mine) {               /* 开着就一直等更新的：有就重画再等，没有（null）隔一会儿再等 */
  api('/api/report/' + encodeURIComponent(name) + '?after=' + revision).then(data => { if (mine !== turn) return;
    if (data) show(data); else return setTimeout(() => { if (mine === turn) wait(mine); }, RETRY_MS);
    wait(mine); }, () => retry(mine)); }
/* 连不上（肥鱼退出、重启中）：留着最后一份，隔几秒不带编号重新要一份（重启后编号从头数），要到了接着等 */
function retry(mine) { if (mine === turn) setTimeout(() => { if (mine === turn) fetchFresh(mine); }, RECONNECT_MS); }
function fetchFresh(mine) {
  api('/api/report/' + encodeURIComponent(name)).then(data => { if (mine !== turn) return; show(data); wait(mine); }, () => retry(mine)); }
function open(report, act) { if (!api || !report) return;
  const mine = ++turn; name = report; action = act || null; revision = 0;
  box.hidden = false; detailCard.hidden = true; widen();
  frame(S.activity, '', `<p class="hint">${esc(S.viewer_loading)}</p>`);
  api('/api/report/' + encodeURIComponent(name)).then(data => { if (mine !== turn) return; show(data); wait(mine); },
    () => { if (mine === turn) { frame(S.activity, '', `<p class="hint">${esc(S.timeline_failed)}</p>`); retry(mine); } }); }
/* 一个带 data-show="panel" 的按钮（磁贴正面或详情里）→ 开它 body 里那份报告；「在新页面打开」用同一个动作，去掉 show */
function openFrom(el) { const d = el.dataset || {}; let body = {};
  try { body = d.body ? JSON.parse(d.body) : {}; } catch (e) { body = {}; }
  open(body.report, {name: d.action, words: d.words, body: body}); }
function close() { if (box.hidden && !name) return; turn++; name = ''; action = null;
  box.hidden = true; box.innerHTML = ''; detailCard.hidden = false; narrow(); }
box.addEventListener('click', ev => {
  if (ev.target.closest('[data-tl-close]')) return close();
  const act = ev.target.closest('[data-action]'); if (act && !act.disabled) runAction(api, S, act); });
livePanel = {open, openFrom, close, isOpen: () => !!name};
return livePanel;
}
