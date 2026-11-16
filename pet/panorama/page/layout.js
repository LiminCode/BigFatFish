/* 版面：位置全由数据算出。layout(G) 给每个节点、分区、通道算好坐标，返回后面几步共用的模型。
   哪里都不写死坐标：账号带 × 层的格子里放分区，分区里是列，节点在列里从上往下排。 */
export const SZ = {bar:[176,28], row:[176,44], std:[206,60], tall:[206,82], big:[168,174]};
export const CH = 46, PADX = 30, PADT = 40, PADB = 24, VG = 10, GUT = 118, BRIDGE = 150, MX = 26, MY = 44, CAP = 36, BOT = 54;

export function layout(G) {
/* 没有节点的分区、没有分区的账号带（比如没装 WSL）不占地方 */
G.regions = G.regions.filter(r => G.nodes.some(n => n.region === r.id));
G.nodes = G.nodes.filter(n => G.regions.some(r => r.id === n.region));
G.zones = G.zones.filter(z => G.regions.some(r => r.zone === z.id));
G.tiers = G.tiers.filter(x => G.regions.some(r => r.tier === x.id));
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
return {G, Z, T, R, N, W, H, gut};
}
