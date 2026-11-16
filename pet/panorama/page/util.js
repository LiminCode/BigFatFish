/* 配置全景页面的小工具：转义、图标、颜色。不碰 DOM，不认识图的结构。 */
export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
export const ICONS = {
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
export function hsv(hex) { const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), d = mx - Math.min(r, g, b); let h = 0;
  if (d) h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, mx ? d / mx : 0, mx]; }
export function rgb(h, s, v) { const f = k => { const x = (k + h / 60) % 6; return Math.round(255 * (v - v * s * Math.max(0, Math.min(x, 4 - x, 1)))); };
  return `rgb(${f(5)},${f(3)},${f(1)})`; }
export const soften = (hex, ks = .6, kv = .8) => { const [h, s, v] = hsv(hex); return rgb(h, s * ks, v * kv); };
export const tint = (hex, kv) => { const [h, s] = hsv(hex); return rgb(h, Math.min(s, .55) * .5, kv); };
