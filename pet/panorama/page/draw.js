/* 画：把算好的版面和走线变成标记，写进地图。只画，不接任何交互。
   注意：页面带「只许同源脚本」的内容策略，这里不能生成内联脚本或 on* 属性。 */
import {esc, soften, tint, ICONS} from './util.js';
import {PADT, BRIDGE} from './layout.js';

export function draw(M, E, redraw, served) {
const {G, Z, W, H} = M, S = G.strings || {};
/* 磁贴正面的动作（克隆和知识库同步上的「时间轴」、有页面的功能上的「查看」）：和详情里的按钮同一种 data-*，点了由 interact.js
   分流（show=panel 进右栏，别的 runAction 发出去）。图标跟着动作走（icon），默认时钟。
   离线快照没有服务（served 为假）：按钮灰着，悬停说为什么 */
const face = a => `<button class="face" data-action="${esc(a.name)}" data-words="${esc(a.words || '')}"` + (a.ask === false ? ' data-ask="0"' : '') +
  (a.body ? ` data-body="${esc(JSON.stringify(a.body))}"` : '') + (a.show ? ` data-show="${esc(a.show)}"` : '') + (served ? '' : ` disabled title="${esc(S.action_needs_service)}"`) +
  `><svg viewBox="0 0 24 24">${ICONS[a.icon] || ICONS.clock}</svg><span>${esc(S[a.words] || a.name)}</span></button>`;
const map = document.getElementById('map');
map.classList.toggle('redraw', !!redraw);     /* 原地重画时磁贴不再重放入场动画（样式里 .map.redraw） */
map.style.width = W + 'px'; map.style.height = H + 'px';
let html = G.zones.map(z => `<div class="band" style="left:${z.x - 12}px;top:8px;width:${z.w + 24}px;height:${H - 16}px;--zc:${soften(z.accent, .55, .95)};background:${tint(z.accent, .135)}"><b>${esc(z.title)}</b></div>`).join('');
html += G.regions.map(r => { const a = Z[r.zone].accent;
  return `<div class="region p-${r.pattern}" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;--rf:${tint(a, .2)};--rb:${tint(a, .36)}"><span>${esc(r.title)}<small>${esc(r.sub || '')}</small></span></div>`; }).join('');
html += (G.groups || []).map(g => { const m = G.nodes.filter(n => n.group === g.id); if (!m.length) return '';
  const x0 = Math.min(...m.map(n => n.x)) - 10, y0 = Math.min(...m.map(n => n.y)) - 10, x1 = Math.max(...m.map(n => n.x + n.w)) + 10, y1 = Math.max(...m.map(n => n.y + n.h)) + 10;
  return `<div class="frame" style="left:${x0}px;top:${y0}px;width:${x1 - x0}px;height:${y1 - y0}px"></div>`; }).join('');
G.regions.forEach(r => r.cols.forEach(c => { if (c.caption) html += `<div class="cap" style="left:${c.x + 2}px;top:${r.y + PADT + 8}px">${esc(c.caption)}</div>`; }));
if (G.zones.length > 1 && G.meta.bridge) { const z = G.zones[0], t = G.tiers[G.tiers.length - 1];
  html += `<div class="bridge" style="left:${z.x + z.w}px;top:${t.y + 6}px;width:${BRIDGE}px">${esc(G.meta.bridge)}<i>› › ›</i></div>`; }
html += `<svg class="roads" width="${W}" height="${H}">` + E.map((e, i) => { const p = e.pts, d = e.d, end = p[p.length - 1];
  return `<g class="edge st-${e.state}" data-e="${i}" style="--lc:${G.lines[e.line].color}"><path class="rail" d="${d}"/><path class="flow" d="${d}"/><circle class="end" cx="${end[0]}" cy="${end[1]}" r="3.6"/></g>`; }).join('') + `</svg>`;
html += G.nodes.map((n, i) => { const k = G.kinds[n.kind] || {accent: '#647687', icon: 'dot'}, pips = n.size === 'tall' && n.items;
  return `<div class="tile sz-${n.size} st-${n.state}${n.face ? ' has-face' : ''}" data-id="${n.id}" style="left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px;--tc:${soften(k.accent)};animation-delay:${i * 16}ms">` +
    `<div class="plate"><svg viewBox="0 0 24 24">${ICONS[n.icon || k.icon] || ICONS.dot}</svg></div><div class="txt"><b>${esc(n.title)}</b>` +
    (n.sub ? `<span>${esc(n.sub)}</span>` : '') + (n.lines || []).map(l => `<span>${esc(l)}</span>`).join('') +
    (pips ? `<div class="pips">${n.items.slice(0, 22).map(p => `<i class="${p.state}" title="${esc(p.name)}"></i>`).join('')}${n.items.length > 22 ? `<em>+${n.items.length - 22}</em>` : ''}</div>` : '') +
    `</div><i class="dot ${n.state}"></i>` + (n.badge ? `<em class="badge" style="font-style:normal">${esc(n.badge)}</em>` : '') + (n.face ? face(n.face) : '') + `</div>`; }).join('');
map.innerHTML = html;
/* 断开的线：中间留一个缺口，放一个叉 */
map.querySelectorAll('.edge.st-broken').forEach(g => { const rail = g.querySelector('.rail'), len = rail.getTotalLength(), m = rail.getPointAtLength(len / 2), gap = 22;
  rail.setAttribute('stroke-dasharray', `${Math.max(0, len / 2 - gap / 2)} ${gap} ${len}`);
  g.insertAdjacentHTML('beforeend', `<g class="cut" transform="translate(${m.x} ${m.y})"><circle r="7.5"/><path d="M-3 -3L3 3M3 -3L-3 3"/></g>`); });
return map;
}
