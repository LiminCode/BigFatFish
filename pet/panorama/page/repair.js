/* 待处理里的「修复」：页面上能点的第一个动作（装 hooks）。

   装 hooks 每次都要用户同意（ADR 0006）：先 confirm()，文案和右键菜单那条路的 Qt 弹框一样；点「取消」什么都不发。
   同意了才 POST /api/actions/<动作>，结果写在按钮上：installed（本机当场装好，服务随后重探、页面原地重画，那条线
   变回来）/ pending（WSL 在后台装，装完服务自己重探）/ failed（可以再点）。连不上也可以再点。
   离线快照没有服务，按钮是灰的（interact.js 画的时候就决定了）。 */
import {esc} from './util.js';

/* 一条待处理项（或它指的那块磁贴）的动作按钮；没有动作就是空串 */
export const actionButton = (S, quest, api) => !quest || !quest.action ? '' :
  `<button class="btn mini" data-action="${esc(quest.action.name)}" data-agent="${esc(quest.action.agent)}" data-side="${esc(quest.action.side)}"${api ? '' : ` disabled title="${esc(S.action_needs_service)}"`}>${esc(S.repair)}</button>`;

/* 点了按钮：问 → 发 → 把结果写在按钮上。结果是 installed / pending / failed / lost，取消是 null */
export function runAction(api, S, el) {
  const name = el.dataset.action, agent = el.dataset.agent, side = el.dataset.side;
  /* 取消：同步地「算完了」（不用 Promise.resolve：测试里的假环境没有微任务队列）*/
  if (!confirm(S['repair_confirm_' + side] || S.repair_confirm_win)) return {then: function (ok) { if (ok) ok(null); return this; }};
  el.disabled = true; el.textContent = S.repair_working;
  return api.post('/api/actions/' + encodeURIComponent(name), {agent: agent}).then(r => {
    const state = r.status === 200 && r.body && r.body.state ? r.body.state : 'failed';
    el.textContent = S['repair_' + state] || S.repair_failed;
    if (state === 'failed') el.disabled = false;
    return state;
  }, () => { el.textContent = S.repair_lost; el.disabled = false; return 'lost'; });
}
