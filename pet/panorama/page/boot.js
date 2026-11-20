/* 配置全景的启动脚本：决定数据从哪来，然后交给 app.js 的 start()。

   两种页面共用这一份：
   - 离线快照（本地文件）：数据嵌在页面里（PANORAMA_DATA）。WSL 那一半还没探完时隔几秒重读文件。
   - 本机服务（127.0.0.1 上的页面）：令牌和带令牌的 fetch 在 client.js（报告页也用它）；向 /api/graph 要数据。
     片段里令牌后面可以跟 &settings=<组>（设置窗口里点「到配置全景里改」时肥鱼这样开）：第一张图画完就翻到那一组设置。
     改设置走 api.patch、动作走 api.post：JSON、带令牌；服务的每一种回答（包括 4xx）都原样交给调用方，只有连不上才算失败。
     拿到第一份之后带着它的编号去「等更新的」（/api/graph?after=编号）：服务把请求挂住，有新数据的那一刻才回，
     页面原地重画并保留选中状态。标签页藏起来时不等——服务靠这个知道「没人在看」，空闲够久就自停。

   只用 .then，不用 async/await：测试里用同步的假 fetch 就能把整条路跑完。
   这是页面的入口模块：本机服务的外壳只引用它，其余模块由 import 带进来。 */
import {start} from './app.js';
import {takeToken, makeApi} from './client.js';

(function () {
  var RELOAD_MS = 3000;        /* 离线快照等 WSL 那一半时多久重读一次文件 */
  var MAX_TRIES = 40;          /* 离线快照最多重读这么多次（两分钟） */
  var RETRY_MS = 1000;         /* 服务说「这段时间没有新数据」之后，隔多久再去等：只为防止出错时空转 */
  var TOKEN_KEY = 'panorama-token';

  if (typeof PANORAMA_DATA !== 'undefined') {
    start(PANORAMA_DATA);
    if (PANORAMA_DATA.meta.pending) {
      var tries = +(location.hash.slice(1)) || 0;
      if (tries < MAX_TRIES) setTimeout(function () { location.hash = String(tries + 1); location.reload(); }, RELOAD_MS);
    }
    return;
  }

  var taken = takeToken(TOKEN_KEY), focus = '';
  taken.extras.forEach(function (part) { if (part.indexOf('settings=') === 0) focus = decodeURIComponent(part.slice(9)); });
  var api = makeApi(taken.token);   /* api(path) 取数据；api.patch 改设置；api.post 动作（待处理里的「修复」） */

  var view = null, revision = 0, waiting = false, dead = false;

  function lost() { dead = true; waiting = false; document.getElementById('lost').hidden = false; }

  function show(data) {        /* 第一次是画，之后是原地重画：先记下用户正看着什么，摘掉旧监听，再画新的 */
    var kept = view ? view.capture() : undefined;
    if (view) view.dispose();
    document.documentElement.lang = data.page.lang;
    document.title = data.page.title;
    view = start(data, kept, api);
    revision = data.revision;
  }

  function listen() {          /* 同一时刻只挂一个请求；标签页藏着或连接已断就不挂 */
    if (waiting || dead || document.visibilityState !== 'visible') return;
    waiting = true;
    api('/api/graph?after=' + revision).then(function (next) {
      waiting = false;
      if (next) { show(next); listen(); } else setTimeout(listen, RETRY_MS);
    }).then(null, lost);
  }

  api('/api/graph').then(function (data) {
    if (!data) throw new Error('empty');
    show(data);
    if (focus && view.openSettings) view.openSettings(focus);
    document.addEventListener('visibilitychange', listen);   /* 回到这个标签页时接着等（期间有新数据会立刻拿到） */
    listen();
  }).then(null, lost);
})();
