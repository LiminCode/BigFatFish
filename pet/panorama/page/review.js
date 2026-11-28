/* 复习页的脚本（/report/review）：取令牌 → 向 /api/report/review 要今天这一轮 → 一次摆一张卡 →
   带着编号去等更新（打完分服务发布新数据，那张卡就不在这一轮里了，页面自然翻到下一张）。

   一张卡两步：先只给标题、种类、出处，让人回想；点「看答案」（空格 / 回车）才露出「要点」和「我的话」，下面三个回答
   （1 / 2 / 3），每个按钮上写着选它下次几天后再见。动作一律 POST /api/actions/review {op, path?, answer?}：
   grade（打分）/ flush（现在推送）。页面不自己改列表，等服务的新数据。 */
import {esc} from './util.js';
import {takeToken, makeApi, follow, banner} from './client.js';

/* 一张卡的 HTML。revealed：答案露没露出来；busy：刚点了回答，等服务回话时按钮灰着 */
export function cardHtml(card, revealed, busy, left, S) {
  if (!card) return '';
  var source = card.source_link ? '<a href="' + esc(card.source) + '" target="_blank" rel="noopener">' + esc(card.source) + '</a>' : esc(card.source || '');
  var meta = [card.kind_text ? '<span class="kind">' + esc(card.kind_text) + '</span>' : '', card.captured ? esc(card.captured) : '', source]
    .filter(Boolean).map(function (part) { return '<span>' + part + '</span>'; }).join('');
  var head = '<p class="left">' + esc(String(S.review_left || '').replace('{n}', left)) + '</p><h2>' + esc(card.title) + '</h2>' +
    '<p class="meta">' + meta + '</p>';
  if (!revealed) return head + '<button class="btn show" data-op="show">' + esc(S.review_show || '') + '</button>';
  var parts = (card.points_html ? '<h3>' + esc(S.review_points || '') + '</h3><div class="md">' + card.points_html + '</div>' : '') +
    (card.words_html ? '<h3>' + esc(S.review_words || '') + '</h3><div class="md">' + card.words_html + '</div>' : '');
  var answers = (card.choices || []).map(function (c, i) {
    return '<button class="btn ' + esc(c.answer) + '" data-op="grade" data-answer="' + esc(c.answer) + '"' + (busy ? ' disabled' : '') +
      ' title="' + (i + 1) + '">' + esc(c.label) + '<small>' + esc(c.hint) + '</small></button>';
  }).join('');
  return head + parts + '<div class="answers">' + answers + '</div>';
}

(function () {
  if (typeof document === 'undefined' || !document.getElementById('card')) return;
  var taken = takeToken('report-token'), token = taken.token, api = makeApi(token);
  var el = function (id) { return document.getElementById(id); };
  var dead = false, S = {}, R = {};
  var shownPath = '', revealed = false, busy = false;

  function gone() { dead = true; el('push').disabled = true; }   /* 令牌作废：重连也没用 */
  function say(text, cls) { el('status').textContent = text || ''; el('status').className = 'status' + (cls ? ' ' + cls : ''); }
  function card() { return (R.cards || [])[0] || null; }

  function paint() {
    var c = card();
    el('card').innerHTML = cardHtml(c, revealed, busy, (R.cards || []).length ? (R.counts || {}).due || 0 : 0, S);
  }

  function show(data) {
    R = data.report || {};
    S = data.strings || {};
    document.documentElement.lang = data.page.lang;
    document.documentElement.dataset.theme = R.theme || 'dark';
    document.title = data.page.title;
    el('title').textContent = R.title || '';
    var counts = R.counts || {};
    el('counts').textContent = R.available === false ? '' : String(S.review_counts || '').replace('{due}', counts.due || 0).replace('{done}', counts.done || 0);
    var sync = R.sync || {};
    el('sync').textContent = sync.text || '';
    el('sync').className = 'sync' + (sync.failed ? ' bad' : '');
    el('push').hidden = !(R.available !== false && sync.pending);
    el('push').textContent = S.review_push || '';
    var c = R.available === false ? null : card();
    if (!c || c.path !== shownPath) { revealed = false; busy = false; shownPath = c ? c.path : ''; }
    el('empty').hidden = !!c;
    el('empty').textContent = R.available === false ? (R.unavailable_text || '') : (R.empty_text || '');
    el('card').hidden = !c;
    el('keys').hidden = !c;
    el('keys').textContent = S.review_keys || '';
    paint();
  }

  function reveal() { if (card() && !revealed) { revealed = true; paint(); } }

  function grade(answer) {
    var c = card();
    if (!c || !revealed || busy || dead) return;
    busy = true; paint(); say('');
    api.post('/api/actions/review', {op: 'grade', path: c.path, answer: answer}).then(function (r) {
      var b = r.body || {}, state = r.status === 200 ? b.state : 'failed';
      if (state === 'graded') { say(String(S.review_graded || '').replace('{next}', b.next || ''), 'ok'); return; }
      busy = false; paint();
      say(S['review_' + state] || S.review_failed || '', 'bad');
    }).then(null, function () { busy = false; paint(); say(S.report_action_lost || '', 'bad'); });
  }

  el('card').addEventListener('click', function (event) {
    var b = event.target.closest ? event.target.closest('[data-op]') : null;
    if (!b || b.disabled) return;
    if (b.dataset.op === 'show') reveal();
    else if (b.dataset.op === 'grade') grade(b.dataset.answer);
  });
  document.addEventListener('keydown', function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    var key = event.key;
    if ((key === ' ' || key === 'Enter') && !revealed) { event.preventDefault(); reveal(); return; }
    var c = card(), i = ['1', '2', '3'].indexOf(key);
    if (c && i >= 0 && c.choices && c.choices[i]) { event.preventDefault(); grade(c.choices[i].answer); }
  });
  el('push').addEventListener('click', function () {
    if (dead) return;
    el('push').disabled = true;
    api.post('/api/actions/review', {op: 'flush'}).then(function (r) {
      var state = (r.body || {}).state;
      el('push').disabled = false;
      say(S['review_flush_' + state] || S.review_failed || '', state === 'started' ? '' : 'bad');
    }).then(null, function () { el('push').disabled = false; say(S.report_action_lost || '', 'bad'); });
  });

  follow(api, '/api/report/review', {show: show, trouble: banner(el('lost'), gone)});
})();
