/* 本机服务的每张页面共用的那一小段：从网址的 # 片段取令牌、带令牌的 fetch、跟着一份数据走（follow）和断线横幅（banner）。
   boot.js（配置全景）和报告页、笔记页、复习页都用它。

   令牌从网址的 # 片段里取（肥鱼打开浏览器时放在那里：片段不发给服务器、不进 Referer），马上从地址栏抹掉，之后只放在
   请求头里；同一个标签页刷新时从 sessionStorage 取回。片段里令牌后面可以跟 &key=value（配置全景用它翻到某一组设置），
   原样交给调用方。

   只用 .then，不用 async/await：测试里用同步的假 fetch 就能把整条路跑完。 */
export const TOKEN_HEADER = 'X-Panorama-Token';

export function takeToken(storageKey) {   /* 返回 {token, extras: [令牌后面那几段]} */
  function stored(write) {       /* 隐私模式下 sessionStorage 可能抛异常：拿不到就当没有 */
    try {
      if (write !== undefined) sessionStorage.setItem(storageKey, write);
      return sessionStorage.getItem(storageKey) || '';
    } catch (e) { return write || ''; }
  }
  var parts = location.hash.slice(1).split('&'), token = parts[0];
  if (token) { stored(token); history.replaceState(null, '', location.pathname); }
  else token = stored();
  return {token: token, extras: parts.slice(1)};
}

export function makeApi(token) {
  function api(path) {           /* 结果是数据；服务回 204（没有新的）时是 null */
    var headers = {};
    headers[TOKEN_HEADER] = token;
    return fetch(path, {headers: headers}).then(function (response) {
      if (response.status === 204) return null;
      if (!response.ok) { var error = new Error('HTTP ' + response.status); error.status = response.status; throw error; }
      return response.json();
    });
  }
  function send(method) {       /* 结果是 {status, body}；不按状态码抛，只有连不上才 reject */
    return function (path, data) {
      var headers = {'Content-Type': 'application/json'}, status = null;
      headers[TOKEN_HEADER] = token;
      return fetch(path, {method: method, headers: headers, body: JSON.stringify(data)}).then(function (response) {
        status = response.status;
        return response.json();
      }).then(function (body) { return {status: status, body: body || {}}; },
              function (error) { if (status === null) throw error; return {status: status, body: {}}; });
    };
  }
  api.patch = send('PATCH');    /* 改设置 */
  api.post = send('POST');      /* 动作（待处理里的「修复」、报告页的「重新生成」） */
  return api;
}

var FOLLOW_RETRY_MS = 1000;             /* 服务说「这段时间没有新数据」（204）之后隔多久再去等：只为防止出错时空转 */
var FOLLOW_RECONNECT_MS = 3000;     /* 连不上之后隔多久再试一次 */

/* 跟着服务上的一份数据走：先要现成的（path），再带着它的编号挂一个「等更新的」（path?after=编号），服务有新的那一刻才回。
   同一时刻只挂一个请求；标签页藏着时不挂（服务靠挂着的请求知道有人在看），回到前台接着等。第一份不管藏没藏都要。

   连不上（肥鱼退出、重启中）或服务回 5xx（还没准备好、忙）：不放弃，hooks.trouble('retrying')，隔 FOLLOW_RECONNECT_MS 再来；
   重来时**不带编号**重新要一份——肥鱼重启后编号从头数，带着旧编号会一直等不到。要到了先 trouble('ok') 再交给 show。
   服务回 4xx（令牌作废、页面不认识了）才是真断了：trouble('gone')，之后不再敲门。

   hooks.show(data, first)：拿到一份（第一份 first 为真，页面在这时做只做一次的事）。 */
export function follow(api, path, hooks) {
  var revision = 0, waiting = false, sleeping = false, dead = false, fresh = true, first = true, troubled = false;
  function later(ms) { sleeping = true; setTimeout(function () { sleeping = false; step(); }, ms); }
  function fail(error) {
    waiting = false;
    var status = error && error.status;
    if (status >= 400 && status < 500) { dead = true; hooks.trouble('gone'); return; }
    fresh = true;
    if (!troubled) { troubled = true; hooks.trouble('retrying'); }
    later(FOLLOW_RECONNECT_MS);
  }
  function step() {
    if (waiting || sleeping || dead || (!first && document.visibilityState !== 'visible')) return;
    waiting = true;
    api(fresh ? path : path + '?after=' + revision).then(function (data) {
      waiting = false;
      if (!data) {
        if (fresh) throw new Error('empty');
        later(FOLLOW_RETRY_MS);
        return;
      }
      var wasFirst = first;
      fresh = false; first = false; revision = data.revision;
      if (troubled) { troubled = false; hooks.trouble('ok'); }
      hooks.show(data, wasFirst);
      step();
    }).then(null, fail);
  }
  document.addEventListener('visibilitychange', step);
  step();
}

/* 断线横幅：外壳里那一块 #lost，正文是「接不上了」，data-retry 里是「正在重连」。返回给 follow 用的 trouble(state)；
   onGone 在真断了的时候调一次（页面把按钮灰掉）。 */
export function banner(box, onGone) {
  var goneText = box.textContent;
  return function (state) {
    if (state === 'ok') { box.hidden = true; return; }
    box.textContent = state === 'gone' ? goneText : (box.dataset.retry || goneText);
    box.hidden = false;
    if (state === 'gone' && onGone) onGone();
  };
}
