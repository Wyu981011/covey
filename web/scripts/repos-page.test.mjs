// 设置页「仓库」页的纯函数：页签替换、概要、灰字、repos_set 只带改动、清理 worktree 的选择与分批。
// 跑：node --import ./scripts/alias.mjs --test scripts/repos-page.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as R from '../client/src/cv/reposPage.ts';

const tab = (key, label = key) => ({ key, label });
const item = (extra = {}) => ({ name: 'demo-repo', tail: 'work/demo-repo', note: '', status: 'active', write_mode: 'worktree', branch: 'main', rules: [], live_topics: 0, ...extra });
const wt = (n, extra = {}) => ({ repo: 'demo-repo', branch: `topic-${n}`, tail: `wt/demo-repo-${n}`, ...extra });
const ago = (sec, now) => `${Math.floor((now - sec) / 60)} 分钟前`;
const page = { home: { tail: 'home/demo' }, items: [item()], worktrees: { total: 3, prunable: [wt(1), wt(2)] } };

test('页签：有 repos 就原样用', () => {
  const tabs = [tab('config'), tab('repos', '仓库'), tab('workspace')];
  assert.equal(R.tabsWithRepos(tabs, { repos: page }), tabs);
});
test('页签：没有 repos 但有 workspace 且 data.repos 存在，原位换成「仓库」', () => {
  const out = R.tabsWithRepos([tab('config'), tab('workspace', '工作区'), tab('proxy')], { repos: page });
  assert.deepEqual(out.map((t) => t.key), ['config', 'repos', 'proxy']);
  assert.equal(out[1].label, '仓库');
});
test('页签：repos 是错误条目也算仓库模式（页里显示错误）', () => {
  const out = R.tabsWithRepos([tab('workspace', '工作区')], { repos: { error: 'x' } });
  assert.equal(out[0].key, 'repos');
});
test('页签：data.repos 不存在时一字不动（旧 Covey）', () => {
  const tabs = [tab('config'), tab('workspace', '工作区')];
  assert.equal(R.tabsWithRepos(tabs, {}), tabs);
  assert.equal(R.tabsWithRepos(tabs, null), tabs);
  assert.deepEqual(R.tabsWithRepos(tabs, {}).map((t) => t.label), ['config', '工作区']);
});
test('页签：既没有 repos 也没有 workspace 不加', () => {
  const tabs = [tab('config')];
  assert.equal(R.tabsWithRepos(tabs, { repos: page }), tabs);
});
test('旧地址 /settings/workspace 仅在仓库模式下跳走', () => {
  assert.equal(R.repoRedirect('workspace', [tab('config'), tab('repos')]), 'repos');
  assert.equal(R.repoRedirect('workspace', [tab('config'), tab('workspace')]), null);
  assert.equal(R.repoRedirect('config', [tab('repos')]), null);
});

test('概要：主目录 · 仓库 · 可清理', () => {
  assert.equal(R.summaryText(page), '主目录 …/home/demo · 仓库 1 个 · 可清理 worktree 2 个');
  assert.equal(R.summaryText({ ...page, home: { tail: '' } }), '仓库 1 个 · 可清理 worktree 2 个');
  assert.equal(R.tailText('…/a/b'), '…/a/b');
  assert.equal(R.tailText('/a/b'), '…/a/b');
});
test('状态标签：active 不画', () => {
  assert.equal(R.statusLabel('active'), '');
  assert.equal(R.statusLabel('readonly'), '只读');
  assert.equal(R.statusLabel('frozen'), '冻结');
});
test('灰字：为 0 的、空的不写', () => {
  assert.deepEqual(R.repoMeta(item({ branch: '' }), 1000, ago), ['…/work/demo-repo', '写法 独立 worktree']);
  const full = R.repoMeta(item({ write_mode: 'inplace', rules: ['AGENTS.md', 'CLAUDE.md'], last_used: 940, live_topics: 2 }), 1000, ago);
  assert.deepEqual(full, ['…/work/demo-repo', 'main', '写法 原目录', '规范 AGENTS.md 等 2 个', '最近 1 分钟前', '在跑 2 个话题']);
  assert.equal(R.rulesText(['AGENTS.md']), '规范 AGENTS.md');
  assert.equal(R.rulesText([]), '');
});

test('repos_set 只带改了的字段', () => {
  const it = item({ note: '旧用途' });
  assert.equal(R.repoSetPayload(it, R.draftOf(it)), null);
  assert.deepEqual(R.repoSetPayload(it, { ...R.draftOf(it), status: 'frozen' }), { what: 'repos_set', name: 'demo-repo', status: 'frozen' });
  assert.deepEqual(R.repoSetPayload(it, { note: ' 新用途 ', status: 'active', write_mode: 'inplace' }), { what: 'repos_set', name: 'demo-repo', note: '新用途', write_mode: 'inplace' });
  // 只多了空白不算改动
  assert.equal(R.repoSetPayload(it, { ...R.draftOf(it), note: ' 旧用途 ' }), null);
  // 清空用途是改动
  assert.deepEqual(R.repoSetPayload(it, { ...R.draftOf(it), note: '' }), { what: 'repos_set', name: 'demo-repo', note: '' });
});
test('repos_add / repos_remove', () => {
  assert.equal(R.repoAddPayload('  ', 'n', 'x'), null);
  assert.deepEqual(R.repoAddPayload(' /absolute/demo ', '', ''), { what: 'repos_add', path: '/absolute/demo' });
  assert.deepEqual(R.repoAddPayload('box:/absolute/demo', ' d ', ' 用途 '), { what: 'repos_add', path: 'box:/absolute/demo', name: 'd', note: '用途' });
  assert.equal(R.repoAddPayload('/a'.repeat(400), '', '').path.length, R.PATH_MAX);
  assert.deepEqual(R.repoRemovePayload('demo-repo'), { what: 'repos_remove', name: 'demo-repo' });
});

test('可清理行字样', () => {
  const ended = Math.floor(new Date(2026, 10, 5, 12).getTime() / 1000);
  assert.equal(R.pruneLine(wt(1, { topic_number: 12, ended_at: ended })), 'demo-repo · topic-1 · …/wt/demo-repo-1 · T12 · 结束于 11-05');
  assert.equal(R.pruneLine(wt(2)), 'demo-repo · topic-2 · …/wt/demo-repo-2');
});
test('勾选：切换、全选、丢掉已不存在的', () => {
  const list = [wt(1), wt(2), wt(3)];
  let sel = R.toggleKey([], 'wt/demo-repo-1');
  assert.deepEqual(sel, ['wt/demo-repo-1']);
  assert.deepEqual(R.toggleKey(sel, 'wt/demo-repo-1'), []);
  sel = R.toggleAll(sel, list);
  assert.equal(sel.length, 3);
  assert.deepEqual(R.toggleAll(sel, list), []);
  assert.deepEqual(R.keepSelected(['wt/demo-repo-1', 'gone'], list), ['wt/demo-repo-1']);
});
test('清理分批：最多 50 个，去重，余数提示', () => {
  const list = Array.from({ length: 120 }, (_, i) => wt(i));
  const all = list.map(R.pruneKey);
  const b = R.pruneBatch(all, list);
  assert.equal(b.paths.length, 50);
  assert.equal(b.rest, 70);
  assert.deepEqual(R.pruneBatch(['wt/demo-repo-3', 'wt/demo-repo-3', 'nope'], list), { paths: ['wt/demo-repo-3'], rest: 0 });
  assert.deepEqual(R.prunePayload(['a']), { what: 'worktrees_prune', paths: ['a'] });
  assert.match(R.pruneAskText(50, 70), /会删除这些 worktree 目录和分支.*剩下 70 个/u);
  assert.match(R.pruneAskText(2, 0), /^清理选中的 2 个？会删除/u);
});
test('没有可清理项的灰字', () => {
  assert.equal(R.pruneEmptyText(0), '没有可清理的 worktree');
  assert.equal(R.pruneEmptyText(4), '共 4 个 worktree，都在用');
});
