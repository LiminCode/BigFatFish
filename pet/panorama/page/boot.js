/* 配置全景的启动脚本：决定数据从哪来，然后交给 app.js 的 start()。

   两种页面共用这一份：
   - 离线快照（本地文件）：数据嵌在页面里（PANORAMA_DATA）。WSL 那一半还没探完时隔几秒重读文件。
   - 本机服务（127.0.0.1 上的页面）：令牌从网址的 # 片段里取，马上从地址栏抹掉，之后只放在请求头里；
     向 /api/graph 要数据。同一个标签页刷新时令牌从 sessionStorage 里取回。

   只用 .then，不用 async/await：测试里用同步的假 fetch 就能把整条路跑完。
   这是页面的入口模块：本机服务的外壳只引用它，其余模块由 import 带进来。 */
import {start} from './app.js';

(function () {
  var RELOAD_MS = 3000;        /* 等 WSL 那一半时多久看一次 */
  var MAX_TRIES = 40;          /* 最多看这么多次（两分钟）：肥鱼中途退出时页面不会永远刷下去 */
  var KEEPALIVE_MS = 240000;   /* 页面开着且看得见时，每 4 分钟告诉服务「还在用」；服务空闲 15 分钟才自停 */
  var TOKEN_KEY = 'panorama-token';
  var TOKEN_HEADER = 'X-Panorama-Token';

  if (typeof PANORAMA_DATA !== 'undefined') {
    start(PANORAMA_DATA);
    if (PANORAMA_DATA.meta.pending) {
      var tries = +(location.hash.slice(1)) || 0;
      if (tries < MAX_TRIES) setTimeout(function () { location.hash = String(tries + 1); location.reload(); }, RELOAD_MS);
    }
    return;
  }

  function stored(write) {     /* 隐私模式下 sessionStorage 可能抛异常：拿不到就当没有 */
    try {
      if (write !== undefined) sessionStorage.setItem(TOKEN_KEY, write);
      return sessionStorage.getItem(TOKEN_KEY) || '';
    } catch (e) { return write || ''; }
  }
  var token = location.hash.slice(1);
  if (token) { stored(token); history.replaceState(null, '', location.pathname); }
  else token = stored();

  function api(path) {
    var headers = {};
    headers[TOKEN_HEADER] = token;
    return fetch(path, {headers: headers}).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }
  function lost() { document.getElementById('lost').hidden = false; }

  api('/api/graph').then(function (data) {
    document.documentElement.lang = data.page.lang;
    document.title = data.page.title;
    start(data);
    if (data.meta.pending) {
      var left = MAX_TRIES;
      (function wait() {
        if (left-- <= 0) return;
        setTimeout(function () {
          api('/api/graph').then(function (next) {
            if (next.revision !== data.revision) location.reload(); else wait();
          }, lost);
        }, RELOAD_MS);
      })();
    }
    setInterval(function () {
      if (document.visibilityState === 'visible') api('/api/ping').then(null, lost);
    }, KEEPALIVE_MS);
  }, lost);
})();
