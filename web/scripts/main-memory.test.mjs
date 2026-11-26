// 设置页「记忆」（v37，T748）的纯函数：字数照 Covey 数、草稿能不能存、筛选和搜索、高亮、配额的状态和说法、发给 Covey 的载荷、
// 未保存的判断、几个下拉的选项。跑：npm run test:mainmem
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../client/src/cv/mainMemory.ts';

const entry = (key, text, extra = {}) => ({ key, kind: key.split(':')[0], text, by: 'owner', pinned: false, pinnable: key.startsWith('principle'),
  editable: !key.startsWith('candidate'), carried: true, chars: text.length, at: 1795400000, origin: '', edited: '', ...extra });
const groups = [
  { scope: 'global', workspace: '', title: '全局', used: 300, limit: 1200, left: 0,
    entries: [entry('principle:p000001', '回复先给结论', { pinned: true }), entry('knowledge:k000001', '周报每周一发', { knowledge_kind: 'decision', why: '主人定的' })] },
  { scope: 'workspace', workspace: 'docs', title: '工作区 docs', used: 790, limit: 800, left: 2, entries: [entry('principle:p000002', 'Commit message in English')] },
  { scope: 'workspace', workspace: 'web', title: '工作区 web', used: 0, limit: 800, left: 0, entries: [] },
];

test('字数照 Covey 存的数：空白收成一个空格，emoji 和中文都算一个', () => {
  assert.equal(M.cleanText('  先给\n\n结论  再说 '), '先给 结论 再说');
  assert.equal(M.charCount('先给\n结论'), 5);  // 换行收成一个空格，也算一个字，和 Covey 存下的一样
  assert.equal(M.charCount('👍好'), 2);
});

test('草稿：空的、超长的不能存，说清超了几个字', () => {
  assert.deepEqual(M.checkDraft('   ', 200), { ok: false, why: '正文是空的', count: 0 });
  assert.deepEqual(M.checkDraft('长'.repeat(203), 200), { ok: false, why: '超出 3 字（最多 200 字）', count: 203 });
  assert.equal(M.checkDraft('先给结论', 200).ok, true);
});

test('筛选：全部、全局、某个工作区；搜索不分大小写、查正文和原因；没剩条目的组只在搜索时不列', () => {
  assert.deepEqual(M.filterGroups(groups, 'all', '').map((g) => g.title), ['全局', '工作区 docs', '工作区 web']);
  assert.deepEqual(M.filterGroups(groups, 'global', '').map((g) => g.title), ['全局']);
  assert.deepEqual(M.filterGroups(groups, 'w:web', '').map((g) => g.entries.length), [0]);
  assert.deepEqual(M.filterGroups(groups, 'all', 'ENGLISH').map((g) => g.entries.map((e) => e.key)), [['principle:p000002']]);
  assert.deepEqual(M.filterGroups(groups, 'all', '主人定').map((g) => g.entries.map((e) => e.key)), [['knowledge:k000001']]);
  assert.deepEqual(M.scopeOptions(groups).map((o) => [o.value, o.count]), [['all', 3], ['global', 2], ['w:docs', 1], ['w:web', 0]]);
});

test('高亮：每一处都标，不分大小写', () => {
  assert.deepEqual(M.hitRanges('Abc abc ABC', 'abc'), [[0, 3], [4, 7], [8, 11]]);
  assert.deepEqual(M.hitRanges('先给结论', ''), []);
});

test('配额：放不下、常驻超了、快满了、都带上', () => {
  assert.equal(M.roomOf(groups[1]), 'full');
  assert.match(M.roomWords(groups[1]), /^放不下 2 条/u);
  assert.equal(M.roomOf({ used: 1300, limit: 1200, left: 0 }), 'over');
  assert.equal(M.roomOf({ used: 960, limit: 1200, left: 0 }), 'near');
  assert.equal(M.roomOf(groups[0]), 'ok');
  assert.equal(M.roomPercent({ used: 1300, limit: 1200 }), 100);
  assert.equal(M.roomPercent({ used: 300, limit: 1200 }), 25);
});

test('载荷：新建带作用域和工作区，知识条目带种类和原因；改带改之前的正文（base），知识条目只带改了的种类和原因', () => {
  assert.deepEqual(M.addPayload('principle', 'global', ' 先给\n结论 '), { action: 'add', what: 'principle', scope: 'global', text: '先给 结论' });
  assert.deepEqual(M.addPayload('knowledge', 'w:docs', '发版走脚本', 'practice', ''),
    { action: 'add', what: 'knowledge', scope: 'workspace', workspace: 'docs', text: '发版走脚本', knowledge_kind: 'practice' });
  const k = groups[0].entries[1];
  assert.deepEqual(M.editPayload(k, '周报每周一早上发', 'decision', '主人定的'), { action: 'edit', key: k.key, text: '周报每周一早上发', base: '周报每周一发' });
  assert.deepEqual(M.editPayload(k, '周报每周一发', 'fact', '换了'), { action: 'edit', key: k.key, text: '周报每周一发', base: '周报每周一发', knowledge_kind: 'fact', why: '换了' });
});

test('未保存：正文收好空白以后变了才算；知识条目的种类、原因变了也算', () => {
  const p = groups[0].entries[0];
  assert.equal(M.edited(p, ' 回复先给结论 '), false);
  assert.equal(M.edited(p, '回复先给结论。'), true);
  const k = groups[0].entries[1];
  assert.equal(M.edited(k, k.text, 'decision', '主人定的'), false);
  assert.equal(M.edited(k, k.text, 'fact', '主人定的'), true);
});

test('标签、谁说的、时间、下拉选项', () => {
  const kinds = [{ value: 'decision', text: '决定' }];
  assert.equal(M.kindLabel(groups[0].entries[1], kinds), '知识 · 决定');
  assert.equal(M.kindLabel(groups[0].entries[0], kinds), '原则');
  assert.equal(M.byWords('lead'), '它总结的');
  const now = new Date(2026, 10, 24, 22, 0).getTime() / 1000;
  assert.equal(M.whenWords(new Date(2026, 10, 24, 9, 5).getTime() / 1000, now), '今天 09:05');
  assert.equal(M.whenWords(new Date(2026, 10, 20, 9, 5).getTime() / 1000, now), '11/20');
  assert.equal(M.whenWords(new Date(2025, 0, 2).getTime() / 1000, now), '2025/1/2');
  assert.deepEqual(M.previewOptions({ default: 'web', previews: { docs: {}, web: {} } }), ['web', 'docs']);
  assert.deepEqual(M.placeOptions({ default: 'web', workspaces: ['docs', 'web'] }).map((o) => o.value), ['global', 'w:web', 'w:docs']);
});

test('知识条目：正文、编辑的 base 都是存的纯正文；行上字数和编辑框同一个数，额度另说清楚（T852）', () => {
  const k = entry('knowledge:k000002', '周报每周一发', { knowledge_kind: 'decision', why: '主人定的', chars: 38, size: 6 });
  assert.equal(M.editPayload(k, '周报每周二发', 'decision', '主人定的').base, '周报每周一发');
  assert.equal(M.edited(k, '周报每周一发', 'decision', '主人定的'), false);
  assert.equal(M.sizeOf(k), 6);
  assert.equal(M.sizeOf({ text: '先给 结论', chars: 40 }), 5);  // 旧版 Covey 不推 size：按正文数
  assert.match(M.sizeTitle(k), /正文 6 字.*额度 38 字/u);
  assert.equal(M.filterGroups([{ ...groups[0], entries: [entry('principle:p000009', '先给结论', { quote: '我说过很多次，先给结论', topic: 'T83' })] }], 'all', 'T83')[0].entries.length, 1);
  assert.equal(M.filterGroups([{ ...groups[0], entries: [entry('principle:p000009', '先给结论', { quote: '我说过很多次，先给结论' })] }], 'all', '很多次').length, 1);
});

test('说明和真实算法一致：放不下的是最近没用到的，原则才能标常驻；删、记下、不用在页面上方留回执，常驻只写在行上（T852）', () => {
  assert.doesNotMatch(M.roomWords(groups[1]), /最早/u);
  assert.match(M.roomWords(groups[1]), /最近没用到/u);
  assert.match(M.roomWords(groups[1]), /原则可以标常驻/u);
  for (const action of ['delete', 'keep', 'drop', 'edit', 'add']) assert.equal(M.noticeAction({ action }), true);
  for (const action of ['pin', 'unpin']) assert.equal(M.noticeAction({ action }), false);
});
