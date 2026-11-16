/* 走线：通道 + 车道，同一束（同种线、同一个枢纽）共用一条车道。
   roads(M) 给每条线算出折线 e.pts 和带圆角的路径 e.d，返回两端节点都在图上的那些线。 */
export function roads(M) {
const {G, Z, T, R, N, gut} = M;
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
E.forEach(e => { e.pts = tidy(route(e)); e.d = rounded(e.pts); });
return E;
}
