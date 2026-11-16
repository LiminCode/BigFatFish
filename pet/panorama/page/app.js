/* 配置全景的页面程序：start(G) 把一份图画出来，并接好页面上的交互。
   数据从哪来不归这里管——离线快照把它嵌在页面里，本机服务的页面向 /api/graph 要（见 boot.js）。
   这里没有任何功能名和界面文字：版面、走线只按图的结构算，文字都在 G.strings 里。
   注意：页面带「只许同源脚本」的内容策略，这个文件里不能生成内联脚本或 on* 属性。 */
function start(G) {
const S = G.strings;
/* 没有节点的分区、没有分区的账号带（比如没装 WSL）不占地方 */
G.regions = G.regions.filter(r => G.nodes.some(n => n.region === r.id));
G.nodes = G.nodes.filter(n => G.regions.some(r => r.id === n.region));
G.zones = G.zones.filter(z => G.regions.some(r => r.zone === z.id));
G.tiers = G.tiers.filter(x => G.regions.some(r => r.tier === x.id));
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const STATE = S.state, ESTATE = S.edge_state;
const ICONS = {
  terminal:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
  window:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M6.5 6.5h.01M9.5 6.5h.01"/>',
  fish:'<path d="M3 12c3-5 9-6 13-3l5-3v12l-5-3c-4 3-10 2-13-3z"/><path d="M8 11h.01"/>',
  chat:'<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
  eye:'<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
  file:'<path d="M6 3h8l4 4v14H6zM14 3v4h4M9 13h6M9 17h6"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
  funnel:'<path d="M3 4h18l-7 8v7l-4 2v-9z"/>',
  news:'<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M7 8h6M7 12h10M7 16h10"/>',
  hash:'<path d="M9 3L7 21M17 3l-2 18M4 9h17M3 15h17"/>',
  note:'<path d="M5 3h11l3 3v15H5zM9 8h6M9 12h6M9 16h4"/>',
  link:'<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  chip:'<rect x="7" y="7" width="10" height="10" rx="1"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
  key:'<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14 9l2 2"/>',
  plug:'<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>',
  plugoff:'<path d="M9 2v4M15 2v6M6 8h12v3a6 6 0 0 1-9 5M12 17v5M3 3l18 18"/>',
  book:'<path d="M4 4h7a3 3 0 0 1 1 2 3 3 0 0 1 1-2h7v15h-7a2 2 0 0 0-1 1 2 2 0 0 0-1-1H4zM12 6v14"/>',
  stack:'<path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5"/>',
  gear:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  puzzle:'<path d="M4 8h4a2 2 0 1 1 4 0h4v4a2 2 0 1 1 0 4v4H4z"/>',
  repo:'<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 7v10M18 11c0 4-6 3-12 6"/>',
  github:'<path d="M9 19c-4 1.5-4-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.500 2.800 5.400 3.100 5.400 3.100a4.200 4.200 0 0 0-.100 3.200A4.600 4.600 0 0 0 4 9.500c0 4.600 2.700 5.700 5.500 6-.600.600-.600 1.200-.500 2V21"/>',
  wrench:'<path d="M14 6a4 4 0 0 0 5 5l-9 9-3-3 9-9M7 17l-3 3"/>',
  dot:'<circle cx="12" cy="12" r="4"/>',
};
/* 磁贴底色：和蒸馏流程页同一条规则——强调色的饱和度 ×0.6、明度 ×0.8 */
function hsv(hex) { const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), d = mx - Math.min(r, g, b); let h = 0;
  if (d) h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, mx ? d / mx : 0, mx]; }
function rgb(h, s, v) { const f = k => { const x = (k + h / 60) % 6; return Math.round(255 * (v - v * s * Math.max(0, Math.min(x, 4 - x, 1)))); };
  return `rgb(${f(5)},${f(3)},${f(1)})`; }
const soften = (hex, ks = .6, kv = .8) => { const [h, s, v] = hsv(hex); return rgb(h, s * ks, v * kv); };
const tint = (hex, kv) => { const [h, s] = hsv(hex); return rgb(h, Math.min(s, .55) * .5, kv); };

/* ───────── 版面：位置全由数据算出 ───────── */
const SZ = {bar:[176,28], row:[176,44], std:[206,60], tall:[206,82], big:[168,174]};
const CH = 46, PADX = 30, PADT = 40, PADB = 24, VG = 10, GUT = 118, BRIDGE = 150, MX = 26, MY = 44, CAP = 36, BOT = 54;
const Z = {}, T = {}, R = {}, N = {};
G.zones.forEach((z, i) => { z.i = i; Z[z.id] = z; }); G.tiers.forEach((t, i) => { t.i = i; T[t.id] = t; });
G.regions.forEach(r => { R[r.id] = r; r.cols = []; });
G.nodes.forEach(n => { N[n.id] = n; [n.w0, n.h] = SZ[n.size] || SZ.std; const r = R[n.region];
  if (!r.cols[n.col]) r.cols[n.col] = {id: n.col, nodes: []}; r.cols[n.col].nodes.push(n); });
(G.columns || []).forEach(o => { const c = R[o.region] && R[o.region].cols[o.col]; if (c) Object.assign(c, o); });
G.regions.forEach(r => {
  r.cols = r.cols.filter(Boolean);
  r.cols.forEach((c, k) => { c.k = k; c.r = r; c.w = Math.max(...c.nodes.map(n => n.w0));
    c.top = c.nodes.filter(n => n.anchor !== 'bottom'); c.bot = c.nodes.filter(n => n.anchor === 'bottom');
    let y = c.caption && !c.top.some(n => n.size === 'bar') ? CAP : 0;
    c.top.forEach(n => { n.c = c; y += n.gap || 0; n.ry = y; y += n.h + (n.size === 'bar' ? 8 : VG); });
    c.bot.forEach(n => { n.c = c; });
    c.h = y - VG + (c.bot.length ? 26 + c.bot.reduce((a, n) => a + n.h + VG, 0) : 0); });
  r.w0 = r.cols.reduce((a, c) => a + c.w, 0) + CH * (r.cols.length - 1) + 2 * PADX;
  r.h0 = PADT + Math.max(0, ...r.cols.map(c => c.h)) + PADB;
});
let cur = MX; G.zones.forEach(z => { z.w = Math.max(...G.regions.filter(r => r.zone === z.id).map(r => r.w0)); z.x = cur; cur += z.w + BRIDGE; });
const W = cur - BRIDGE + MX;
cur = MY; G.tiers.forEach(t => { t.h = Math.max(...G.regions.filter(r => r.tier === t.id).map(r => r.h0)); t.y = cur; cur += t.h + GUT; });
const H = cur - GUT + BOT;
const gut = G.tiers.map((t, i) => ({y0: t.y + t.h, y1: i < G.tiers.length - 1 ? G.tiers[i + 1].y : H - 6, keys: []}));
G.regions.forEach(r => { const z = Z[r.zone], t = T[r.tier]; Object.assign(r, {x: z.x, y: t.y, w: z.w, h: t.h});
  const n = r.cols.length, extra = r.w - r.w0, gap = CH + (n > 1 ? extra / (n - 1) : 0); let x = r.x + PADX + (n === 1 ? extra / 2 : 0);
  r.cols.forEach(c => { c.x = x; x += c.w + gap;
    c.top.forEach(m => Object.assign(m, {x: c.x, w: c.w, y: r.y + PADT + m.ry}));
    let by = r.y + r.h - PADB; [...c.bot].reverse().forEach(m => { by -= m.h; Object.assign(m, {x: c.x, w: c.w, y: by}); by -= VG; }); });
  r.ch = []; for (let k = 0; k <= n; k++) r.ch.push({keys: [],
    x0: k === 0 ? r.x + (z.i > 0 ? -BRIDGE / 2 + 10 : 5) : r.cols[k - 1].x + r.cols[k - 1].w,
    x1: k === n ? r.x + r.w + (z.i < G.zones.length - 1 ? BRIDGE / 2 - 10 : -5) : r.cols[k].x});
});

/* ───────── 走线：通道 + 车道，同一束共用一条车道 ───────── */
const mx = n => n.x + n.w / 2, my = n => n.y + n.h / 2;
const chan = (n, side) => n.c.r.ch[side === 'left' ? n.c.k : n.c.k + 1];
const isTop = n => n.anchor !== 'bottom' && n.c.top[0] === n;
const isBottom = n => !n.c.nodes.some(m => m !== n && m.y > n.y);
const opp = s => s === 'left' ? 'right' : 'left';
const cnt = {}; G.edges.forEach(e => { for (const k of ['>' + e.line + e.to, '<' + e.line + e.from]) cnt[k] = (cnt[k] || 0) + 1; });
const E = G.edges.filter(e => N[e.from] && N[e.to]);
E.forEach(e => { const s = N[e.from], t = N[e.to], ts = T[R[s.region].tier].i, tt = T[R[t.region].tier].i;
  e.key = cnt['>' + e.line + e.to] > cnt['<' + e.line + e.from] ? `${e.line}>${e.to}` : `${e.line}<${e.from}`;
  if (s.c === t.c) { e.k = 'spine'; e.ss = e.ts = s.c.spine || (Z[R[s.region].zone].i === 0 ? 'left' : 'right'); }
  else if (ts !== tt) { const a = ts > tt ? s : t, b = ts > tt ? t : s, dir = mx(b) >= mx(a) ? 'right' : 'left';
    e.k = 'tier'; e.lower = a; e.upper = b; e.ls = isTop(a) ? 'top' : dir; e.us = isBottom(b) ? 'bottom' : (mx(a) <= mx(b) ? 'left' : 'right');
    e.ss = a === s ? e.ls : e.us; e.ts = a === s ? e.us : e.ls; e.g = Math.min(ts, tt); }
  else { const dir = mx(t) >= mx(s) ? 'right' : 'left'; e.k = 'side'; e.ss = dir; e.ts = opp(dir); e.g = ts; }
});
const ports = {};
const addPort = (n, side, key, o) => { const id = n.id + '|' + side, a = ports[id] || (ports[id] = []); let p = a.find(p => p.key === key); if (!p) a.push(p = {key, o: []}); p.o.push(o); };
E.forEach(e => { const s = N[e.from], t = N[e.to], v = side => side === 'top' || side === 'bottom';
  addPort(s, e.ss, e.key, v(e.ss) ? mx(t) : my(t)); addPort(t, e.ts, e.key, v(e.ts) ? mx(s) : my(s)); });
Object.entries(ports).forEach(([id, a]) => { const [nid, side] = id.split('|'), n = N[nid], vert = side === 'top' || side === 'bottom';
  const avg = p => p.o.reduce((x, y) => x + y, 0) / p.o.length; a.sort((p, q) => avg(p) - avg(q));
  a.forEach((p, i) => { const f = (i + 1) / (a.length + 1);
    p.xy = vert ? [n.x + n.w * f, side === 'top' ? n.y : n.y + n.h] : [side === 'left' ? n.x : n.x + n.w, n.y + n.h * f]; }); });
const port = (n, side, key) => ports[n.id + '|' + side].find(p => p.key === key).xy;
const mid = ch => (ch.x0 + ch.x1) / 2;
const clearH = (y, x1, x2, skip) => !G.nodes.some(n => !skip.includes(n) && y > n.y - 6 && y < n.y + n.h + 6 && n.x < Math.max(x1, x2) && n.x + n.w > Math.min(x1, x2));
const use = (ch, key) => { if (!ch.keys.includes(key)) ch.keys.push(key); };
E.forEach(e => { const s = N[e.from], t = N[e.to];
  if (e.k === 'spine') { e.c1 = chan(s, e.ss); use(e.c1, e.key); }
  else if (e.k === 'tier') { if (e.ls !== 'top') { e.c1 = chan(e.lower, e.ls); use(e.c1, e.key); }
    if (e.us !== 'bottom') { e.c2 = chan(e.upper, e.us); use(e.c2, e.key); } e.gut = gut[e.g]; use(e.gut, e.key); }
  else { const cs = chan(s, e.ss), ct = chan(t, e.ts), ps = port(s, e.ss, e.key), pt = port(t, e.ts, e.key);
    if (cs === ct || clearH(pt[1], mid(cs), pt[0], [s, t])) e.c1 = cs;
    else if (clearH(ps[1], ps[0], mid(ct), [s, t])) e.c1 = ct;
    else { e.c1 = cs; e.c2 = ct; e.gut = gut[e.g]; use(e.c2, e.key); use(e.gut, e.key); }
    use(e.c1, e.key); }
});
const laneX = (ch, key) => { const n = ch.keys.length, st = Math.min(9, (ch.x1 - ch.x0 - 12) / n); return mid(ch) + (ch.keys.indexOf(key) - (n - 1) / 2) * st; };
const laneY = (g, key) => { const n = g.keys.length, st = Math.min(9, (g.y1 - g.y0 - 24) / n); return (g.y0 + g.y1) / 2 + (g.keys.indexOf(key) - (n - 1) / 2) * st; };
function route(e) { const s = N[e.from], t = N[e.to], ps = port(s, e.ss, e.key), pt = port(t, e.ts, e.key);
  if (e.k === 'spine' || (e.k === 'side' && !e.c2)) { const lx = laneX(e.c1, e.key); return [ps, [lx, ps[1]], [lx, pt[1]], pt]; }
  if (e.k === 'side') { const l1 = laneX(e.c1, e.key), l2 = laneX(e.c2, e.key), gy = laneY(e.gut, e.key); return [ps, [l1, ps[1]], [l1, gy], [l2, gy], [l2, pt[1]], pt]; }
  const up = e.lower === s, pa = up ? ps : pt, pb = up ? pt : ps, gy = laneY(e.gut, e.key), p = [pa];
  if (e.ls !== 'top') { const lx = laneX(e.c1, e.key); p.push([lx, pa[1]], [lx, gy]); } else p.push([pa[0], gy]);
  if (e.us !== 'bottom') { const lx = laneX(e.c2, e.key); p.push([lx, gy], [lx, pb[1]]); } else p.push([pb[0], gy]);
  p.push(pb); return up ? p : p.reverse(); }
function tidy(p) { const o = [p[0]];
  for (let i = 1; i < p.length; i++) { const a = o[o.length - 1], b = p[i], c = p[i + 1];
    if (Math.abs(a[0] - b[0]) < .5 && Math.abs(a[1] - b[1]) < .5) continue;
    if (c && ((Math.abs(a[0] - b[0]) < .5 && Math.abs(b[0] - c[0]) < .5) || (Math.abs(a[1] - b[1]) < .5 && Math.abs(b[1] - c[1]) < .5))) continue;
    o.push(b); } return o; }
function rounded(p, r = 8) { let d = `M${p[0][0]} ${p[0][1]}`;
  for (let i = 1; i < p.length; i++) { const [a, b] = p[i]; if (i === p.length - 1) { d += ` L${a} ${b}`; break; }
    const [pa, pb] = p[i - 1], [na, nb] = p[i + 1], d1 = Math.hypot(a - pa, b - pb), d2 = Math.hypot(na - a, nb - b), q = Math.min(r, d1 / 2, d2 / 2);
    d += ` L${a - (a - pa) / d1 * q} ${b - (b - pb) / d1 * q} Q${a} ${b} ${a + (na - a) / d2 * q} ${b + (nb - b) / d2 * q}`; }
  return d; }

/* ───────── 画 ───────── */
const map = document.getElementById('map');
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
html += `<svg class="roads" width="${W}" height="${H}">` + E.map((e, i) => { const p = tidy(route(e)), d = rounded(p), end = p[p.length - 1]; e.pts = p;
  return `<g class="edge st-${e.state}" data-e="${i}" style="--lc:${G.lines[e.line].color}"><path class="rail" d="${d}"/><path class="flow" d="${d}"/><circle class="end" cx="${end[0]}" cy="${end[1]}" r="3.6"/></g>`; }).join('') + `</svg>`;
html += G.nodes.map((n, i) => { const k = G.kinds[n.kind] || {accent: '#647687', icon: 'dot'}, pips = n.size === 'tall' && n.items;
  return `<div class="tile sz-${n.size} st-${n.state}" data-id="${n.id}" style="left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px;--tc:${soften(k.accent)};animation-delay:${i * 16}ms">` +
    `<div class="plate"><svg viewBox="0 0 24 24">${ICONS[n.icon || k.icon] || ICONS.dot}</svg></div><div class="txt"><b>${esc(n.title)}</b>` +
    (n.sub ? `<span>${esc(n.sub)}</span>` : '') + (n.lines || []).map(l => `<span>${esc(l)}</span>`).join('') +
    (pips ? `<div class="pips">${n.items.slice(0, 22).map(p => `<i class="${p.state}" title="${esc(p.name)}"></i>`).join('')}${n.items.length > 22 ? `<em>+${n.items.length - 22}</em>` : ''}</div>` : '') +
    `</div><i class="dot ${n.state}"></i>` + (n.badge ? `<em class="badge" style="font-style:normal">${esc(n.badge)}</em>` : '') + `</div>`; }).join('');
map.innerHTML = html;
/* 断开的线：中间留一个缺口，放一个叉 */
map.querySelectorAll('.edge.st-broken').forEach(g => { const rail = g.querySelector('.rail'), len = rail.getTotalLength(), m = rail.getPointAtLength(len / 2), gap = 22;
  rail.setAttribute('stroke-dasharray', `${Math.max(0, len / 2 - gap / 2)} ${gap} ${len}`);
  g.insertAdjacentHTML('beforeend', `<g class="cut" transform="translate(${m.x} ${m.y})"><circle r="7.5"/><path d="M-3 -3L3 3M3 -3L-3 3"/></g>`); });

/* ───────── 交互 ───────── */
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
return {width: W, height: H};
}
