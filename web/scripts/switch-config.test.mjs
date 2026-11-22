// 话题页换配置（T616，Covey v20）：初值、有没有变化、网页上换不了的情况。跑：npm run test:switch
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as S from '../client/src/cv/switchConfig.ts';

const m = (key, extra = {}) => ({
  key, harness: key.split(':')[0], harness_title: key.split(':')[0], provider: '', provider_title: '自带', label: key,
  budgets: [{ value: 'high', text: '高' }, { value: 'low', text: '低' }], default_budget: 'high', start_budget: 'high',
  redaction: true, work_modes: [], ...extra,
});
const D = {
  models: [m('claude:opus'), m('codex:gpt', { redaction: false, work_modes: ['auto', 'fast'], start_budget: 'low' })],
  workspaces: [{ name: 'covey', device: '', harnesses: [] }, { name: 'ws-root', device: '', harnesses: [] }],
  run_modes: [{ value: 'direct', text: '原目录' }, { value: 'worktree', text: '独立 worktree' }],
  preselect: { model: 'claude:opus', effort: 'high', work_mode: '', redaction: 'off', workspace: 'covey', run_mode: 'direct' },
};
const C = { model: 'claude:opus', effort: 'high', work_mode: '', workspace: 'covey', run_mode: 'direct', redaction: 'on' };

test('初值补成模型能选的', () => {
  assert.deepEqual(S.fromConfig(D, C), C);
  assert.equal(S.fromConfig(D, { ...C, effort: 'max' }).effort, 'high');
  const g = S.fromConfig(D, { ...C, model: 'codex:gpt', effort: 'zzz' });
  assert.deepEqual([g.effort, g.work_mode, g.redaction], ['low', 'auto', 'off']);
  assert.equal(S.fromConfig(D, { ...C, model: 'gone:x' }).model, 'gone:x');
});

test('没动过不算变化，只补齐也不算', () => {
  const base = S.fromConfig(D, { ...C, effort: 'max' });
  assert.deepEqual(S.changedFields(base, { ...base }), []);
  assert.deepEqual(S.changedFields(base, { ...base, effort: 'low', workspace: 'ws-root' }), ['effort', 'workspace']);
});

test('换不了的情况', () => {
  const base = S.fromConfig(D, C);
  assert.equal(S.switchBlock(D, base, { ...base, effort: 'low' }, false), '');
  assert.equal(S.switchBlock(D, base, { ...base, effort: 'low' }, true), '在做时不能换，先停止');
  assert.match(S.switchBlock(D, base, { ...base, run_mode: 'worktree' }, false), /飞书的换配置卡/u);
  const wt = { ...base, run_mode: 'worktree' };
  assert.equal(S.switchBlock(D, wt, { ...wt, effort: 'low' }, false), '');
  assert.match(S.switchBlock(D, wt, { ...wt, workspace: 'ws-root' }, false), /飞书的换配置卡/u);
  assert.equal(S.switchBlock(D, wt, { ...wt, run_mode: 'direct' }, false), '');
  const gone = { ...base, model: 'gone:x' };
  assert.match(S.switchBlock(D, gone, gone, false), /重选模型/u);
});
