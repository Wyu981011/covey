// 数据约定 v34（covey docs/web.md）：专项的收尾、停止，到点回来看，代发草稿，完成标准与改动两行，记忆的「不对」，要你处理的权威计数。
// 跑：npm run test:v34
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as V from '../client/src/cv/v34.ts';
import * as P from '../client/src/cv/projectData.ts';
import * as S from '../server/modules/workbench/workbench.v4.ts';
import { OUTBOX_KINDS, SETTINGS_KEYS } from '../shared/api.interface.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const NOW = Date.parse('2026-11-23T10:00:00+08:00') / 1000;

test('新操作和新的设置条目网页认得：收尾、停止、记忆的不对，settings 的 asks', () => {
  for (const k of ['project_finish', 'project_stop', 'memory_undo']) assert.ok(OUTBOX_KINDS.includes(k), k);
  assert.ok(SETTINGS_KEYS.includes('asks'));
});

test('只在 Covey 认这个操作时画新按钮（settings.ops）：旧 Covey 没有 ops，一律不画', () => {
  assert.equal(V.canDo(undefined, 'project_finish'), false);
  assert.equal(V.canDo(['say', 'recover'], 'memory_undo'), false);
  assert.equal(V.canDo(['say', 'memory_undo'], 'memory_undo'), true);
  const bits = readFileSync(join(CV, 'V34Bits.tsx'), 'utf8');
  for (const k of ['project_finish', 'project_stop', 'memory_undo']) assert.match(bits, new RegExp(`canDo\\(ops, '${k}'\\)`, 'u'), k);
  // 停止先问一句（确认停止），不是一点就停；你停住的专项原地有「继续」（reopen 是老操作，旧 Covey 也认，不看 ops）
  assert.match(bits, /确认停止/u);
  assert.match(bits, /again: 'reopen'/u);
});

test('收尾、停止给哪些专项：收尾给在做、等你和停住、收起的，停止只给在做、等你的', () => {
  assert.deepEqual(['在做', '等你', '停住', '收起', '做完', '已取消'].map((status) => P.canFinish({ status })), [true, true, true, true, false, false]);
  assert.deepEqual(['在做', '等你', '停住', '收起', '做完', '已取消'].map((status) => P.canStop({ status })), [true, true, false, false, false, false]);
});

test('要你处理以 Covey 算好的为准，没推或形状不对时自己数', () => {
  const local = { waiting: [{}, {}], stopped: [{}], stuck: [], projects: [{}] };
  assert.deepEqual(P.askNumbers(local, undefined), { waiting: 2, stopped: 2, stuck: 0 });
  assert.deepEqual(P.askNumbers(local, { waiting: 3, stopped: 0, stuck: 1 }), { waiting: 3, stopped: 0, stuck: 1 });
  assert.deepEqual(P.askNumbers(local, { waiting: -1, stopped: 0, stuck: 0 }), { waiting: 2, stopped: 2, stuck: 0 });
  assert.equal(P.askSum({ waiting: 3, stopped: 0, stuck: 1 }), 4);
  for (const f of ['Board.tsx', 'Shell.tsx']) assert.match(readFileSync(join(CV, f), 'utf8'), /askNumbers\(/u, f);
});

test('到点回来看：今天的只写时刻，过了时间说该回来看了', () => {
  assert.equal(V.revisitWords({ at: NOW + 3600, what: 'CI 跑完没有' }, NOW), '约好 11:00 回来看：CI 跑完没有');
  assert.equal(V.revisitWords({ at: NOW - 60, what: '' }, NOW), '约好 09:59 回来看，该回来看了');
  assert.equal(V.revisitWords({ at: NOW + 86400, what: '复查' }, NOW), '约好 11-24 10:00 回来看：复查');
});

test('代发草稿只读：一句话说给谁、写了什么，没发出去的说要在卡上再点', () => {
  assert.equal(V.draftWords({ id: 'd1', to: '张三', state: 'waiting', preview: '周报已更新', created_at: null }), '→ 张三：周报已更新');
  assert.equal(V.draftWords({ id: 'd2', to: '', state: 'failed', preview: '', created_at: null }), '→ 收件人待定（没发出去，要在卡上再点一次）');
  // 网页不发任何消息：草稿那几行只有去飞书的链接，没有发件操作
  const bits = readFileSync(join(CV, 'V34Bits.tsx'), 'utf8');
  const drafts = bits.slice(bits.indexOf('export const DraftLines'), bits.indexOf('export const LaterPanel'));
  assert.doesNotMatch(drafts, /\.run\(|postOutbox|kind:/u);
});

test('完成标准一行和改动一行，和飞书答案卡同义', () => {
  assert.deepEqual(V.criteriaSummary([{ item: 'a', state: '满足' }, { item: 'b', state: '没满足' }, { item: 'c', state: '没查' }]),
    { text: '1/3 满足 · 1 条没满足 · 1 条没查', unmet: 2 });
  assert.deepEqual(V.criteriaSummary([{ item: 'a', state: '满足' }]), { text: '1/1 满足', unmet: 0 });
  assert.deepEqual(V.criteriaSummary(undefined), { text: '', unmet: 0 });
  assert.deepEqual(V.deliveryBits({ commit: 'd060d7da0d74703e5f59a7d9eaf3eb1b0373722f 3854a59', deployed: '第 9 代', verified: 'lint 通过' }),
    ['提交 d060d7d 3854a59', '已部署：第 9 代', '已自检']);
  assert.deepEqual(V.deliveryBits({ verified: '读了报告' }), ['已自检']);
  assert.deepEqual(V.deliveryBits(undefined), []);
});

test('服务端：到点回来看、代发草稿、完成标准、交付、要你处理只留认得的', () => {
  assert.deepEqual(S.revisitOf({ at: 1800000000, what: 'CI\n跑完没有', extra: 1 }), { at: 1800000000, what: 'CI\n跑完没有' });
  assert.equal(S.revisitOf({ at: 0, what: 'x' }), undefined);
  const drafts = S.ownerSendOf([{ id: 'd1', to: '张三', state: 'waiting', preview: '周报', created_at: 17, link: 'http://evil' },
    { id: '', to: 'x' }, { id: 'd2', to: '李四', link: 'https://applink.example/x' }]);
  assert.deepEqual(drafts.map((d) => [d.id, d.state, d.link ?? '']), [['d1', 'waiting', ''], ['d2', 'waiting', 'https://applink.example/x']]);
  assert.equal(S.ownerSendOf(Array.from({ length: 8 }, (_, i) => ({ id: `d${i}` }))).length, 5);
  assert.deepEqual(S.criteriaOf([{ item: '测试过', state: '满足', evidence: '165 条' }, { item: '' }, { item: '文档', state: '' }]),
    [{ item: '测试过', state: '满足', evidence: '165 条' }, { item: '文档', state: '没查' }]);
  assert.deepEqual(S.deliveryOf({ commit: 'abc1234', deployed: '', verified: 'ok' }), { commit: 'abc1234', verified: 'ok' });
  assert.equal(S.deliveryOf({ commit: '', deployed: '' }), undefined);
  assert.deepEqual(S.asksOf({ waiting: 2, stopped: 1, stuck: 0, at: 5 }), { waiting: 2, stopped: 1, stuck: 0 });
  assert.equal(S.asksOf({ waiting: 2, stopped: 1 }), undefined);
  assert.equal(S.asksOf({ waiting: 1.5, stopped: 1, stuck: 0 }), undefined);
});

test('服务端：收尾、停止要 project_key、payload 空；不对要 topic_key、任务号和记忆编号', () => {
  assert.equal(S.projectOpShape('project_stop', {}, '', 'p1'), null);
  assert.match(S.projectOpShape('project_stop', {}, 't1', 'p1'), /project_key/u);
  assert.match(S.projectOpShape('project_finish', { text: '收' }, '', 'p1'), /空的/u);
  assert.deepEqual(S.memoryUndoShape({ job_id: 7, entry_id: 'e1' }, 't1', ''), { job_id: '7', entry_id: 'e1' });
  assert.match(S.memoryUndoShape({ job_id: 'x', entry_id: 'e1' }, 't1', '').error, /job_id/u);
  assert.match(S.memoryUndoShape({ job_id: '7', entry_id: 'a b' }, 't1', '').error, /entry_id/u);
  assert.match(S.memoryUndoShape({ job_id: '7', entry_id: 'e1' }, '', 'p1').error, /topic_key/u);
});
