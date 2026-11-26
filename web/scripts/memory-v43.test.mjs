// 数据约定 v43（docs/web.md 数据约定 v43：记忆中心与仓库）：memory:* 键的认法、memory_edit 新旧两种 payload 的校验、
// settings 新操作和启动、换配置带 repos 的校验，以及 tests/golden/web_memory_v43.json 的形状。跑：npm run test:memv43
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as M from '../server/modules/workbench/workbench.memory-edit.ts';
import { MEMORY_EDIT_ACTIONS_V43, MEMORY_KEY_RE, SETTINGS_KEYS, SETTINGS_WHATS, isSettingsKey } from '../shared/api.interface.ts';

const golden = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'tests', 'golden', 'web_memory_v43.json'), 'utf8'));
const ok = (p) => assert.doesNotThrow(() => M.checkMemoryEdit(p, {}));
const bad = (p, re) => assert.throws(() => M.checkMemoryEdit(p, {}), re);

test('键：7 个旧键仍认，golden 里每个 memory:* 键都认，写错的键不认', () => {
  assert.deepEqual([...SETTINGS_KEYS], ['settings', 'usage', 'tidy', 'asks', 'memory', 'upgrade', 'quota']);
  for (const k of SETTINGS_KEYS) assert.equal(isSettingsKey(k), true, k);
  for (const k of Object.keys(golden.keys)) assert.equal(isSettingsKey(k), true, k);
  for (const k of ['memory:t:abc', 'memory:p:AB', 'memory:p:', 'memory:p:abc', 'memory:p:ABCDEF', 'memory:import:', 'memory:import:1234', 'memory:', 'memory:global:x', 'memory:p:' + 'a'.repeat(33), 'foo']) {
    assert.equal(isSettingsKey(k), false, k);
  }
  assert.ok(MEMORY_KEY_RE.test('memory:p:' + 'a'.repeat(32)));
  assert.equal('memory:p:'.length + 32 <= 41, true);
});

test('golden：每种 memory:* 键一份，global 有 ≥2 条待审核和 ≥2 条变更，条目短码前缀对得上 kind', () => {
  assert.equal(golden.version, 43);
  assert.deepEqual(Object.keys(golden.keys).sort(), ['memory:global', 'memory:import:0', 'memory:index', 'memory:p:demo01', 'memory:previews', 'memory:topics']);
  const g = golden.keys['memory:global'];
  assert.ok(g.review.length >= 2 && g.log.length >= 2);
  const idx = golden.keys['memory:index'];
  assert.equal(idx.version, 43);
  for (const k of Object.keys(idx.revs)) assert.equal(isSettingsKey(k), true, k);
  const entries = [...g.entries, ...golden.keys['memory:p:demo01'].entries, ...golden.keys['memory:topics'].topics.flatMap((t) => t.entries)];
  for (const e of entries) assert.equal(e.code[0], { rule: 'R', decision: 'D', note: 'N' }[e.kind], e.key);
  assert.equal(golden.keys['memory:import:0'].items.length <= 200, true);
});

test('memory_edit v43：golden 里每个 edit 都过，每个 action 至少一份', () => {
  for (const e of golden.edits) ok(e);
  const seen = new Set(golden.edits.map((e) => e.action));
  for (const a of MEMORY_EDIT_ACTIONS_V43) assert.ok(seen.has(a), `golden 缺 ${a}`);
});

test('memory_edit v43：拒绝超长、缺字段、不认识的值', () => {
  const add = golden.edits.find((e) => e.action === 'add');
  const dec = { ...add, kind: 'decision', scope: 'project' };
  ok({ ...dec, text: '字'.repeat(600) });
  bad({ ...dec, text: '字'.repeat(601) }, /600/u);
  bad({ ...add, text: '字'.repeat(201) }, /200/u);
  bad({ ...add, title: '字'.repeat(41) }, /title/u);
  bad({ ...add, why: '字'.repeat(201) }, /why/u);
  bad({ v: 43, action: 'undo', keys: [] }, /undo_token/u);
  bad({ v: 43, action: 'undo', keys: [], undo_token: 'x'.repeat(65) }, /undo_token/u);
  bad({ v: 43, action: 'add', keys: [], title: 't', text: 'x', kind: 'rule' }, /kind 和 scope/u);
  bad({ v: 43, action: 'add', keys: [], text: 'x', kind: 'rule', scope: 'global' }, /title/u);
  bad({ v: 43, action: 'pin', keys: ['a'] }, /action/u);
  bad({ v: 43, action: 'archive', keys: [] }, /keys/u);
  bad({ v: 43, action: 'archive', keys: Array(201).fill('a') }, /200/u);
  bad({ v: 43, action: 'archive', keys: ['a'.repeat(201)] }, /keys/u);
  bad({ v: 43, action: 'edit', keys: ['a'], kind: 'idea' }, /kind/u);
  bad({ v: 43, action: 'edit', keys: ['a'], scope: 'world' }, /scope/u);
  bad({ v: 43, action: 'edit', keys: ['a'], repos: Array(11).fill('r') }, /repos/u);
  bad({ v: 43, action: 'edit', keys: ['a'], oops: 1 }, /字段/u);
  assert.throws(() => M.checkMemoryEdit({ v: 43, action: 'archive', keys: ['a'] }, { topic_key: 't1' }), /topic_key/u);
});

test('memory_edit 旧 v37（没有 v）：原规则不变', () => {
  ok({ action: 'add', what: 'principle', scope: 'global', text: '先跑测试' });
  ok({ action: 'pin', key: 'principle:pabcdef' });
  bad({ action: 'add', what: 'principle', scope: 'global', text: '字'.repeat(201) }, /200/u);
  bad({ action: 'archive', key: 'principle:pabcdef' }, /action/u);
  bad({ action: 'pin', key: 'bad' }, /key/u);
  bad({ action: 'pin', key: 'principle:pabcdef', keys: [] }, /字段/u);
});

test('settings：4 个新 what 在清单里，golden 样例过校验，写错的拒绝；旧 workspace_* 还在', () => {
  for (const w of ['repos_set', 'repos_add', 'repos_remove', 'worktrees_prune', 'workspace_add', 'workspace_remove', 'workspace_prune']) assert.ok(SETTINGS_WHATS.includes(w), w);
  for (const w of ['repos_set', 'repos_add', 'repos_remove', 'worktrees_prune']) assert.equal(M.reposSettingsError(w, golden.settings[w]), null, w);
  assert.match(M.reposSettingsError('repos_set', { name: 'x', status: 'gone' }), /status/u);
  assert.match(M.reposSettingsError('repos_set', { name: 'x', write_mode: 'copy' }), /write_mode/u);
  assert.match(M.reposSettingsError('repos_set', { name: 'x'.repeat(65) }), /name/u);
  assert.match(M.reposSettingsError('repos_set', { name: 'x', note: 'n'.repeat(201) }), /note/u);
  assert.match(M.reposSettingsError('repos_add', { path: '/' + 'p'.repeat(500) }), /path/u);
  assert.match(M.reposSettingsError('repos_add', { path: '' }), /path/u);
  assert.match(M.reposSettingsError('repos_remove', {}), /name/u);
  assert.match(M.reposSettingsError('worktrees_prune', { paths: Array(51).fill('/a') }), /50/u);
  assert.match(M.reposSettingsError('worktrees_prune', { paths: ['/' + 'p'.repeat(500)] }), /paths/u);
});

test('launch、switch 的 repos：golden 过，超过 10 项、name 太长、mode 不对拒绝；不带照旧', () => {
  assert.equal(M.launchReposError(undefined), null);
  assert.equal(M.launchReposError(golden.settings.launch.repos), null);
  assert.equal(M.launchReposError(golden.settings.switch.repos), null);
  assert.equal('workspace' in golden.settings.launch || 'run_mode' in golden.settings.launch, false);
  assert.equal(M.launchReposError(Array.from({ length: 10 }, (_, i) => ({ name: `r${i}`, mode: 'read' }))), null);
  assert.ok(M.launchReposError(Array.from({ length: 11 }, (_, i) => ({ name: `r${i}`, mode: 'read' }))));
  assert.ok(M.launchReposError([{ name: 'x'.repeat(65), mode: 'read' }]));
  assert.ok(M.launchReposError([{ name: 'x', mode: 'rw' }]));
  assert.ok(M.launchReposError('demo'));
});
