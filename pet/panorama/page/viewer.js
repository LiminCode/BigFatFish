/* 文件查看面板（只读）：点「查看」→ 向本机服务要这一项存储名下的文件清单 → 读其中一个，按纯文本显示。

   能读哪些文件由服务把关（pet/panorama/files.py），这里只管问和显示。内容是原文，不脱敏；一律当文本转义后放进页面，
   不当标记解析——记忆文件里写了 <script> 也只是几个字。服务标出来的段落（受管块）整行加底色。
   离线快照没有服务可问：api 是空的，「查看」按钮不可用（interact.js 里处理），这里的 open() 什么也不做。 */
import {esc} from './util.js';

export const fileSize = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';

export function viewer(api, S, on) {
const box = document.getElementById('viewer');
let turn = 0;                  /* 每开一次、每换一个文件加一：晚到的回答对不上号就丢掉 */
const part = id => document.getElementById(id);
const ask = (path, params) => api(path + '?' + Object.keys(params).map(k => k + '=' + encodeURIComponent(params[k])).join('&'));
function say(text) { part('viewer-meta').textContent = ''; part('viewer-text').innerHTML = `<span class="ln note">${esc(text)}</span>`; }
function show(store, path) { const mine = ++turn; box.dataset.path = path; say(S.viewer_loading);
  box.querySelectorAll('[data-file]').forEach(b => b.classList.toggle('on', b.dataset.file === path));
  ask('/api/file', {store: store, path: path}).then(f => { if (mine !== turn) return;
    const marks = f.marks || [], inMark = n => marks.some(m => n >= m.from && n <= m.to);
    part('viewer-meta').textContent = [f.path, fileSize(f.bytes), f.mtime, f.truncated ? S.viewer_truncated : '', marks.length ? S.viewer_managed : ''].filter(Boolean).join(' · ');
    if (f.binary) { part('viewer-text').innerHTML = `<span class="ln note">${esc(S.viewer_binary)}</span>`; return; }
    part('viewer-text').innerHTML = f.text.replace(/\r\n/g, '\n').split('\n').map((line, i) => `<span class="ln${inMark(i + 1) ? ' managed' : ''}">${esc(line) || ' '}</span>`).join('');
  }).then(null, () => { if (mine === turn) say(S.viewer_failed); }); }
function open(store, title, path) { if (!api) return; const mine = ++turn;       /* path：直接翻到这一个文件；不给就看第一个 */
  box.dataset.store = store; box.hidden = false;
  box.innerHTML = `<div class="sheet"><header><b>${esc(title)}</b><button class="btn" data-close="1">${esc(S.viewer_close)}</button></header>` +
    `<div class="vbody"><nav id="viewer-files"></nav><div class="vmain"><div class="vmeta" id="viewer-meta"></div><pre id="viewer-text"></pre></div></div></div>`;
  say(S.viewer_loading);
  ask('/api/files', {store: store}).then(list => { if (mine !== turn) return;
    part('viewer-files').hidden = list.files.length < 2;
    part('viewer-files').innerHTML = list.files.map(f => `<button data-file="${esc(f.path)}" title="${esc(f.path)}">${esc(f.label || f.path)}<small>${esc(f.mtime)}</small></button>`).join('') +
      (list.truncated ? `<em>${esc(S.viewer_more)}</em>` : '');
    if (path || list.files.length) show(store, path || list.files[0].path); else say(S.viewer_empty);
  }).then(null, () => { if (mine === turn) say(S.viewer_failed); }); }
function close() { turn++; box.hidden = true; box.innerHTML = ''; }
box.addEventListener('click', ev => {
  if (ev.target === box || ev.target.closest('[data-close]')) return close();
  const f = ev.target.closest('[data-file]'); if (f) show(box.dataset.store, f.dataset.file); }, on);
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !box.hidden) { ev.preventDefault(); close(); } }, on);
return {open, close, show};
}
