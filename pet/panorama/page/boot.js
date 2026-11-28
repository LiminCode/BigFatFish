/* 配置全景的启动脚本：决定数据从哪来，然后交给 app.js 的 start()。

   两种页面共用这一份：
   - 离线快照（本地文件）：数据嵌在页面里（PANORAMA_DATA）。WSL 那一半还没探完时隔几秒重读文件。
   - 本机服务（127.0.0.1 上的页面）：令牌和带令牌的 fetch 在 client.js（报告页也用它）；向 /api/graph 要数据。
     片段里令牌后面可以跟 &settings=<组>（设置窗口里点「到配置全景里改」时肥鱼这样开）：第一张图画完就翻到那一组设置。
     改设置走 api.patch、动作走 api.post：JSON、带令牌；服务的每一种回答（包括 4xx）都原样交给调用方，只有连不上才算失败。
     拿到第一份之后带着它的编号去「等更新的」（/api/graph?after=编号）：服务把请求挂住，有新数据的那一刻才回，
     页面原地重画并保留选中状态。连不上就亮出「正在重连」、隔几秒再试，肥鱼回来后接着画（client.js 的 follow）。

   只用 .then，不用 async/await：测试里用同步的假 fetch 就能把整条路跑完。
   这是页面的入口模块：本机服务的外壳只引用它，其余模块由 import 带进来。 */
import {start} from './app.js';
import {takeToken, makeApi, follow, banner} from './client.js';

(function () {
  var RELOAD_MS = 3000;        /* 离线快照等 WSL 那一半时多久重读一次文件 */
  var MAX_TRIES = 40;          /* 离线快照最多重读这么多次（两分钟） */
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

  var view = null;

  function show(data, first) {   /* 第一次是画，之后是原地重画：先记下用户正看着什么，摘掉旧监听，再画新的 */
    var kept = view ? view.capture() : undefined;
    if (view) view.dispose();
    document.documentElement.lang = data.page.lang;
    document.title = data.page.title;
    view = start(data, kept, api);
    if (first && focus && view.openSettings) view.openSettings(focus);
  }

  follow(api, '/api/graph', {show: show, trouble: banner(document.getElementById('lost'))});
})();
