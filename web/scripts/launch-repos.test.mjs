// 去工作区（v43）：新旧两代 Covey 的判定、设备联动、仓库轮换、payload 清洗、标签文字。
// 跑：node --import ./scripts/alias.mjs --test scripts/launch-repos.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as R from '../client/src/cv/launchRepos.ts';
// launch.ts 引了 React 和数据钩子，不进单测；pickDevice = applyDevice + withModel，这里用同样规则的 swap 代替
import * as S from '../client/src/cv/switchConfig.ts';

const m = (key, extra = {}) => ({
  key, harness: key.split(':')[0], harness_title: key.split(':')[0], provider: '', provider_title: '自带', label: key,
  budgets: [{ value: 'high', text: '高' }], default_budget: 'high', start_budget: 'high', redaction: true, work_modes: [], ...extra,
});
const models = [m('claude:opus'), m('codex:gpt', { redaction: false })];
const pre = { model: 'claude:opus', effort: 'high', work_mode: '', redaction: 'off' };
const swap = (mm, s) => ({ ...s, model: mm.key, effort: mm.start_budget, work_mode: '', redaction: mm.redaction ? s.redaction : 'off' });
const pickDevice = (d, sel, name) => R.applyDevice(d, sel, name, swap);
const NEW = { models, preselect: pre, devices: [{ name: 'mac', dot: 'ok', harnesses: [] }, { name: 'box', dot: 'down', harnesses: ['codex'] }] };
const OLD = {
  models, workspaces: [{ name: 'covey', device: '', harnesses: [] }, { name: 'dev', device: 'box', harnesses: ['codex'] }],
  run_modes: [{ value: 'direct', text: '原目录' }, { value: 'worktree', text: '独立 worktree' }],
  preselect: { ...pre, workspace: 'covey', run_mode: 'worktree' },
};

test('新旧判定', () => {
  assert.equal(R.isRepoMode(NEW), true);
  assert.equal(R.isRepoMode(OLD), false);
  assert.equal(R.showDevice(NEW), true);
  assert.equal(R.showDevice({ ...NEW, devices: [NEW.devices[0]] }), false);
  assert.equal(R.showDevice({ ...NEW, devices: undefined }), false);
  assert.equal(R.showDevice({ ...OLD, devices: NEW.devices }), false);
});

test('设备联动：Harness 不在设备能用的里就换模型', () => {
  const a = pickDevice(NEW, { ...pre }, 'box');
  assert.equal(a.device, 'box');
  assert.equal(a.model, 'codex:gpt');
  assert.equal(a.redaction, 'off');
  const b = pickDevice(NEW, { ...pre }, 'mac');
  assert.equal(b.model, 'claude:opus');
  assert.match(R.deviceText(NEW.devices[1]), /离线/u);
  assert.equal(R.deviceText(NEW.devices[0]), 'mac');
});

test('仓库轮换：不用 → 只读 → 可写 → 不用，最多 10 个', () => {
  let r = R.cycleRepo(undefined, 'a');
  assert.deepEqual(r, [{ name: 'a', mode: 'read' }]);
  r = R.cycleRepo(r, 'a');
  assert.deepEqual(r, [{ name: 'a', mode: 'write' }]);
  assert.deepEqual(R.cycleRepo(r, 'a'), []);
  assert.deepEqual(R.cycleRepo([{ name: 'a', mode: 'read' }], 'a', true), []);
  const full = Array.from({ length: 10 }, (_, i) => ({ name: `r${i}`, mode: 'read' }));
  assert.equal(R.cycleRepo(full, 'x').length, 10);
  assert.equal(R.cycleRepo(full, 'r3').find((x) => x.name === 'r3').mode, 'write');
});

test('仓库名单：排除冻结，已选但不在名单的留着', () => {
  const items = [{ name: 'a', status: 'active', note: '' }, { name: 'b', status: 'frozen', note: '' }, { name: 'c', status: 'readonly', note: 'x' }];
  const out = R.repoChoices(items, [{ name: 'old', mode: 'read' }]);
  assert.deepEqual(out.map((x) => x.name), ['a', 'c', 'old']);
  assert.equal(out[1].readonly, true);
});

test('repos 比较和标签文字', () => {
  const a = [{ name: 'a', mode: 'read' }, { name: 'b', mode: 'write' }];
  assert.equal(R.sameRepos(a, [a[1], a[0]]), true);
  assert.equal(R.sameRepos(a, [{ name: 'a', mode: 'write' }, a[1]]), false);
  assert.equal(R.sameRepos(undefined, []), true);
  assert.equal(R.repoLabel(a), '仓库 a、b');
  assert.equal(R.repoLabel([...a, { name: 'c' }, { name: 'd' }]), '仓库 a、b 等 4 个');
  assert.equal(R.repoLabel([]), '');
});

test('launch payload：旧 Covey 一字不变', () => {
  const p = R.launchPayload(OLD, OLD.preselect, 'hi', [], false);
  assert.deepEqual(p, { ...OLD.preselect, text: 'hi', run_mode: 'worktree' });
  const q = R.launchPayload(OLD, { ...OLD.preselect, workspace: 'dev' }, 'hi', [{ x: 1 }], true);
  assert.equal(q.run_mode, 'direct');
  assert.deepEqual(q.files, [{ x: 1 }]);
});

test('launch payload：新 Covey 没有 workspace、run_mode，键集合同 golden', () => {
  const golden = JSON.parse(readFileSync(new URL('../../tests/golden/web_memory_v43.json', import.meta.url), 'utf8'));
  const want = Object.keys(golden.settings.launch).sort();
  const sel = { ...pre, workspace: '', run_mode: '', device: 'mac', repos: [{ name: 'a', mode: 'write' }] };
  const p = R.launchPayload(NEW, sel, 'hi', [], false);
  assert.ok(!('workspace' in p) && !('run_mode' in p));
  assert.deepEqual(Object.keys(p).sort(), ['device', ...want].sort());
  // 默认：不带 repos、单设备不带 device
  const q = R.launchPayload({ ...NEW, devices: [NEW.devices[0]] }, { ...pre, repos: [] }, 'hi', [], false);
  assert.deepEqual(Object.keys(q).sort(), ['effort', 'model', 'redaction', 'text', 'work_mode']);
});

test('switch payload：新 Covey 键集合同 golden；全取消发 []；负责人不带仓库', () => {
  const golden = JSON.parse(readFileSync(new URL('../../tests/golden/web_memory_v43.json', import.meta.url), 'utf8'));
  const cur = { ...pre, workspace: 'old', run_mode: 'direct', repos: [{ name: 'a', mode: 'read' }] };
  const p = R.switchPayload(NEW, cur, true, false);
  assert.deepEqual(Object.keys(p).sort(), Object.keys(golden.settings.switch).sort());
  assert.deepEqual(R.switchPayload(NEW, { ...cur, repos: [] }, true, false).repos, []);
  assert.ok(!('repos' in R.switchPayload(NEW, { ...cur, repos: [] }, false, false)));
  assert.ok(!('repos' in R.switchPayload(NEW, cur, true, true)));
  assert.deepEqual(R.switchPayload(OLD, OLD.preselect, false, false), { ...OLD.preselect });
});

test('换配置：初值取话题的 repos，变化才算 changed；worktree 拦截只在旧 Covey', () => {
  const cfg = { ...pre };
  const base = S.withTopicRepos(NEW, S.fromConfig(NEW, cfg), [{ name: 'a', mode: 'write', rules_read: true, branch: 'x' }]);
  assert.deepEqual(base.repos, [{ name: 'a', mode: 'write' }]);
  assert.deepEqual(S.changedFields(base, { ...base }), []);
  assert.deepEqual(S.changedFields(base, { ...base, repos: [{ name: 'a', mode: 'read' }] }), ['repos']);
  assert.deepEqual(S.changedFields(base, { ...base, device: 'box' }), ['device']);
  assert.equal(S.withTopicRepos(OLD, S.fromConfig(OLD, OLD.preselect), [{ name: 'a', mode: 'read' }]).repos, undefined);
  const wt = { ...base, run_mode: 'worktree', effort: 'low' };
  assert.equal(S.switchBlock(NEW, base, wt, false), '');
  assert.match(S.switchBlock(OLD, S.fromConfig(OLD, OLD.preselect), { ...OLD.preselect, run_mode: 'worktree', effort: 'low', workspace: 'dev' }, false), /飞书/u);
});
