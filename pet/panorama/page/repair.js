/* 待处理里能点的动作：「修复」（装 hooks，页面上的第一个动作）和「现在核对」（让一个克隆去问一次远端）。

   **按钮上的字、要不要先问、发什么，都跟着动作走，这里不认识具体是哪个动作**（来源在待处理项的 action 里写明）：
   - words：这组字在界面文字里的前缀，默认 repair。按钮上是 S[words]，过程和结果是 S[words + '_working' / '_<结果>']；
   - ask：false = 不先问。默认先 confirm()——装 hooks 每次都要用户同意（ADR 0006），文案和右键菜单那条路的 Qt 弹框一样，
     点「取消」什么都不发；只读远端的「现在核对」不问；
   - body：POST 的内容，默认 {agent}；
   - show：panel = 不发，在右栏里看 body.report 那份报告（timeline.js；interact.js 分流）。

   同意了（或不用问）才 POST /api/actions/<动作>，结果写在按钮上。磁贴正面的小按钮（图标 + 一格字）只换那格字、
   全句挂在悬停提示上，开了页的过一会儿换回原来的字——长句子不许把按钮撑出磁贴。办成了按钮保持灰着：服务随后重探、页面原地重画，
   那条线自己变回来。RETRY 里的几种结果（没办成、正忙、东西不在）和连不上，可以再点。
   离线快照没有服务，按钮是灰的（interact.js 画的时候就决定了）。 */
import {esc} from './util.js';

const RETRY = ['failed', 'busy', 'missing', 'opened'];   /* opened：开了一张页，图不会变，按钮得能再点 */
const RESTORE_MS = 2500;

/* 一条待处理项（或它指的那块磁贴）的动作按钮；没有动作就是空串 */
export const actionButton = (S, quest, api) => { if (!quest || !quest.action) return '';
  const a = quest.action, words = a.words || 'repair';
  return `<button class="btn mini" data-action="${esc(a.name)}" data-agent="${esc(a.agent)}" data-side="${esc(a.side)}"` +
    (a.words ? ` data-words="${esc(a.words)}"` : '') + (a.ask === false ? ' data-ask="0"' : '') +
    (a.body ? ` data-body="${esc(JSON.stringify(a.body))}"` : '') + (a.show ? ` data-show="${esc(a.show)}"` : '') +
    `${api ? '' : ` disabled title="${esc(S.action_needs_service)}"`}>${esc(S[words])}</button>`; };

/* 点了按钮：（问 →）发 → 把结果写在按钮上。结果是服务回的 state，或 failed / lost；取消是 null */
export function runAction(api, S, el) {
  const name = el.dataset.action, agent = el.dataset.agent, side = el.dataset.side, words = el.dataset.words || 'repair';
  /* 取消：同步地「算完了」（不用 Promise.resolve：测试里的假环境没有微任务队列）*/
  if (el.dataset.ask !== '0' && !confirm(S[words + '_confirm_' + side] || S[words + '_confirm_win'])) return {then: function (ok) { if (ok) ok(null); return this; }};
  const label = el.querySelector ? el.querySelector('span') : null;      /* 磁贴正面的按钮：只换字那一格 */
  const say = text => { (label || el).textContent = text; if (label) el.title = text; };
  el.disabled = true; say(S[words + '_working']);
  return api.post('/api/actions/' + encodeURIComponent(name), el.dataset.body ? JSON.parse(el.dataset.body) : {agent: agent}).then(r => {
    const state = r.status === 200 && r.body && r.body.state ? r.body.state : 'failed';
    say(S[words + '_' + state] || S[words + '_failed']);
    if (RETRY.includes(state)) el.disabled = false;
    if (label && state === 'opened') setTimeout(() => { label.textContent = S[words] || label.textContent; el.title = ''; }, RESTORE_MS);
    return state;
  }, () => { say(S[words + '_lost'] || S.repair_lost); el.disabled = false; return 'lost'; });
}
