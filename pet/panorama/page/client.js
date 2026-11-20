/* 本机服务的每张页面共用的那一小段：从网址的 # 片段取令牌、带令牌的 fetch。boot.js（配置全景）和 report.js（报告页）都用它。

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
      if (!response.ok) throw new Error('HTTP ' + response.status);
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
