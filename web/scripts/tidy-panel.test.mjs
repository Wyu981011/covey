// 看板「整理专项」面板（T628）的纯函数：什么时候画、一进来展开还是收成一行、「知道了」以后什么时候再出来、一行说什么。跑：npm run test:tidy
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../client/src/cv/tidyData.ts';

const P = (id, state, extra = {}) => ({
  id, run: 'r', kind: 'split', tag: '拆出', verb: '拆出来', headline: `拆出新专项「${id}」`, from: '', why: '', goal: '',
  topics: [], state, note: '', at: 0, ...extra,
});
const D = (proposals, running = null) => ({ proposals, running, updated_at: 0 });

test('一条建议都没有不画，正在整理也不画（进度在「整理」按钮旁）', () => {
  assert.equal(T.shown(T.look(D([])), []), false);
  assert.equal(T.shown(T.look(D([], { done: 3, total: 10 })), []), false);
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
  assert.deepEqual(asking, { state: '要你定 2 条', head: '拆出新专项「a」', more: '', count: '', run: '', failed: '' });
  const settled = T.panelWords(T.look(D([P('a', 'done'), P('b', 'declined'), P('c', 'failed')], { done: 2, total: 5 })));
  assert.deepEqual(settled, { state: '都定好了', head: '拆出新专项「a」', more: '等 3 条', count: '3 条', run: '正在整理（2/5）', failed: '1 条没做成' });
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
