// 看板「整理专项」面板（T628）的纯函数：什么时候画、一进来展开还是收成一行、「知道了」以后什么时候再出来、一行说什么。跑：npm run test:tidy
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../client/src/cv/tidyData.ts';

const P = (id, state, extra = {}) => ({
  id, run: 'r', kind: 'split', tag: '拆出', verb: '拆出来', headline: `拆出新专项「${id}」`, from: '', why: '', goal: '',
  topics: [], state, note: '', at: 0, ...extra,
});
const D = (proposals, running = null, last_run = undefined) => ({ proposals, running, updated_at: 0, ...(last_run ? { last_run } : {}) });
const RUN = (state, extra = {}) => ({ run: 'r1', state, retry: false, origin: 'web', at: 0, progress: { done: 0, total: 0, current: '' }, ...extra });

test('一条建议都没有不画；正在整理画进度（T884：网页上点的整理在面板上看得到）', () => {
  assert.equal(T.shown(T.look(D([])), []), false);
  assert.equal(T.shown(T.look(D([], { done: 3, total: 10 })), []), true);
});

test('有要你定的：总是画、一进来展开；点过收起就收成一行，其中一条在别处定掉了还收着，来了新的一条再展开', () => {
  const l = T.look(D([P('a', 'open'), P('x', 'open'), P('b', 'done')]));
  assert.equal(T.shown(l, l.marks), true);
  assert.equal(T.startOpen(l, ''), true);
  assert.equal(T.startOpen(l, l.batch), false);
  assert.equal(T.startOpen(T.look(D([P('a', 'open'), P('x', 'done'), P('b', 'done')])), l.batch), false);
  const more = T.look(D([P('c', 'open'), P('a', 'open'), P('b', 'done')]));
  assert.equal(T.startOpen(more, l.batch), true);
});

test('这次进看板以后：点了收起，来了新的一条才自己展开；点了展开或定了一条，定完最后一条也不突然收起', () => {
  const l = T.look(D([P('a', 'open'), P('b', 'done')]));
  const folded = T.choice(l, false);
  assert.equal(T.isOpen(l, folded, ''), false);
  assert.equal(T.isOpen(T.look(D([P('b', 'done'), P('a', 'done')])), folded, ''), false);
  assert.equal(T.isOpen(T.look(D([P('c', 'open'), P('a', 'open'), P('b', 'done')])), folded, ''), true);
  const opened = T.choice(l, true);
  assert.equal(T.isOpen(T.look(D([P('a', 'done'), P('b', 'done')])), opened, ''), true);
  assert.equal(T.isOpen(T.look(D([P('a', 'done'), P('b', 'done')])), null, ''), false, '没点过：都定好了收成一行');
});

test('都定好了：收成一行；点「知道了」就不画，有新建议或哪条的结果变了再出来', () => {
  const l = T.look(D([P('a', 'done'), P('b', 'declined')]));
  assert.equal(T.startOpen(l, ''), false);
  assert.equal(T.shown(l, []), true);
  assert.equal(T.dismissible(l), true);
  const gone = T.remember(l, []);
  assert.equal(T.shown(l, gone), false);
  assert.equal(T.shown(T.look(D([P('a', 'done')])), gone), false, '过了 24 小时少了一条：还是不画');
  assert.equal(T.shown(T.look(D([P('a', 'failed'), P('b', 'declined')])), gone), true, '结果变了');
  assert.equal(T.shown(T.look(D([P('c', 'done'), P('a', 'done'), P('b', 'declined')])), gone), true, '新的一条');
  assert.equal(T.shown(T.look(D([P('a', 'done')], { done: 1, total: 9 })), gone), true, '又在整理');
});

test('「知道了」只在都定好了、没在整理时能点；记下的样子不重复、有上限', () => {
  assert.equal(T.dismissible(T.look(D([P('a', 'open'), P('b', 'done')]))), false);
  assert.equal(T.dismissible(T.look(D([P('b', 'done')], { done: 1, total: 2 }))), false);
  const l = T.look(D([P('a', 'done')]));
  assert.deepEqual(T.remember(l, ['a:done', 'x:declined']), ['a:done', 'x:declined']);
  const many = Array.from({ length: T.MARKS_KEPT + 50 }, (_, i) => `z${i}:done`);
  const kept = T.remember(l, many);
  assert.equal(kept.length, T.MARKS_KEPT);
  assert.equal(kept[0], 'a:done');
});

test('一行的字：要你定的说条数和第一条；都定好了说“等 N 条”和没做成几条', () => {
  const asking = T.panelWords(T.look(D([P('a', 'open'), P('b', 'open'), P('c', 'failed')])));
  assert.deepEqual(asking, { state: '要你定 2 条', head: '拆出新专项「a」', more: '', count: '', run: '', failed: '', fail: '' });
  const settled = T.panelWords(T.look(D([P('a', 'done'), P('b', 'declined'), P('c', 'failed')], { done: 2, total: 5 })));
  assert.deepEqual(settled, { state: '都定好了', head: '拆出新专项「a」', more: '等 3 条', count: '3 条', run: '正在整理（2/5）', failed: '1 条没做成', fail: '' });
  assert.equal(T.panelWords(T.look(D([P('a', 'done')]))).more, '');
});

test('定好的一行末尾的结果词：照办了按种类说，没做成是红的', () => {
  assert.deepEqual(T.outcome({ kind: 'split', state: 'done' }), { word: '已拆出', tone: 'ok' });
  assert.deepEqual(T.outcome({ kind: 'create', state: 'done' }), { word: '已建', tone: 'ok' });
  assert.deepEqual(T.outcome({ kind: 'leave', state: 'done' }), { word: '已移出', tone: 'ok' });
  assert.deepEqual(T.outcome({ kind: 'split', state: 'failed' }), { word: '没做成', tone: 'bad' });
  assert.deepEqual(T.outcome({ kind: 'create', state: 'declined' }), { word: '不用', tone: 'off' });
  assert.deepEqual(T.outcome({ kind: 'create', state: 'expired' }), { word: '已过时', tone: 'off' });
  assert.deepEqual(T.outcome({ kind: 'create', state: 'never' }), { word: '不再提议', tone: 'off' });
});

test('T884 最近一次没整理成：没有建议也画原因，「知道了」收走，下一次没整理成再出来；旧版 Covey 不带 last_run 照旧', () => {
  const bad = RUN('failed', { why: 'Codex 登录失效或没有权限', why_code: 'authentication_error', via: 'codex' });
  const l = T.look(D([], null, bad));
  assert.equal(T.shown(l, []), true);
  assert.equal(T.dismissible(l), true);
  assert.equal(T.failWords(T.failedRun(l)), '这次没整理成：Codex 登录失效或没有权限');
  assert.equal(T.wantsSettings(T.failedRun(l)), true);
  assert.equal(T.panelWords(l).state, '没整理成');
  const gone = T.remember(l, []);
  assert.equal(T.shown(l, gone), false);
  assert.equal(T.shown(T.look(D([], null, { ...bad, run: 'r2' })), gone), true, '又一次没整理成');
  assert.equal(T.shown(T.look(D([], null, RUN('done'))), []), false, '最近一次整理好了、没有建议：不画');
  assert.equal(T.shown(T.look(D([])), []), false);
});

test('T884 过一会儿真能好的才说再试，不给「去设置」；选了不用模型说去设置选一个', () => {
  const late = T.look(D([], null, RUN('failed', { why: 'Codex 判断超时了', why_code: 'timeout', retry: true })));
  assert.equal(T.nextWords(T.failedRun(late)), '可以过一会儿再试。');
  assert.equal(T.wantsSettings(T.failedRun(late)), false);
  const none = T.look(D([], null, RUN('failed', { why: '辅助模型选了不用模型', why_code: 'none' })));
  assert.match(T.nextWords(T.failedRun(none)), /选一个辅助模型/);
});

test('T884 正在整理：读到哪个话题、读了几个，进度条的比例；没在整理时不算没整理成', () => {
  const run = RUN('running', { progress: { done: 3, total: 10, current: 'T503 老话题' } });
  const l = T.look(D([], { done: 3, total: 10 }, run));
  assert.equal(T.progressWords(l), '正在读 T503 老话题（3/10）');
  assert.equal(T.progressShare(l), 0.3);
  assert.equal(T.failedRun(l), null);
  assert.equal(T.dismissible(l), false);
  const judging = T.look(D([], { done: 10, total: 10 }, RUN('running', { progress: { done: 10, total: 10, current: '' } })));
  assert.equal(T.progressWords(judging), '正在判断（10 个话题）');
  assert.equal(T.progressWords(T.look(D([], { done: 1, total: 4 }))), '正在整理（1/4）', '旧版 Covey：只有 running');
  assert.equal(T.progressShare(T.look(D([], { done: 0, total: 0 }))), null);
});

test('T884 有建议时最近一次没整理成：收成一行也写原因', () => {
  const l = T.look(D([P('a', 'done')], null, RUN('failed', { why: 'Claude Code 被官方内容安全拦了' })));
  assert.equal(T.panelWords(l).fail, '这次没整理成：Claude Code 被官方内容安全拦了');
  assert.equal(T.shown(l, []), true);
});
