// 停住的一轮接真恢复（T647 P0-5，Covey 数据约定 v33）：按钮照 failure.labels / how / auto_retry 画，点了发 recover，
// 不再替你说一句“继续”；服务端放行 v33 的字段和 recover 操作。跑：npm run test:recover
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as R from '../client/src/cv/recover.ts';
import * as T from '../client/src/cv/topicText.ts';
import * as V from '../server/modules/workbench/workbench.v4.ts';
import { OUTBOX_KINDS, RECOVER_ACTIONS } from '../shared/api.interface.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const keys = (plan) => plan.buttons.map((b) => [b.key, b.label, b.how, b.primary]);

test('v33：字照 labels（结果没发出去时是“重新投递结果”），做法照 how，主按钮只有一个、是接着做的那颗', () => {
  const f = {
    title: '结果没能发出去；点重新投递结果',
    actions: ['continue', 'diagnose', 'switch_model'],
    labels: { continue: '重新投递结果', diagnose: '看原因', switch_model: '换个模型' },
    how: { continue: 'recover', diagnose: 'recover', switch_model: 'switch' },
  };
  assert.deepEqual(keys(R.recoverPlan(f, { canSwitch: true })), [
    ['continue', '重新投递结果', 'recover', true],
    ['diagnose', '看原因', 'recover', false],
    ['switch_model', '换个模型', 'switch', false],
  ]);
  // 管家、负责人的换个模型只有飞书能做（how=feishu），网页不硬换
  const lead = { ...f, how: { ...f.how, switch_model: 'feishu' } };
  assert.equal(R.recoverPlan(lead, { canSwitch: true }).buttons[2].how, 'feishu');
});

test('排着自动重试：只给“现在重试”“停止自动重试”和别的，不再另画检查并继续，也没有主按钮（免得并排再开一轮）', () => {
  const f = {
    title: '限流了，21:40 自动重试（第 2/5 次）',
    actions: ['continue', 'retry', 'diagnose'],
    labels: { continue: '检查并继续', retry: '现在重试', diagnose: '看原因', stop_auto_retry: '停止自动重试' },
    how: { continue: 'recover', retry: 'recover', diagnose: 'recover', stop_auto_retry: 'recover' },
    auto_retry: { state: 'pending', at: 1_800_000_600, attempt: 2, total: 5, kind: 'rate_limited', now: 'retry' },
  };
  const plan = R.recoverPlan(f, { canSwitch: true });
  assert.deepEqual(keys(plan), [
    ['retry', '现在重试', 'recover', false],
    ['stop_auto_retry', '停止自动重试', 'recover', false],
    ['diagnose', '看原因', 'recover', false],
  ]);
  assert.equal(plan.auto?.attempt, 2);
  // now 是 continue（重启打断、没做完的那几种）时按钮也叫“现在重试”
  const cont = { ...f, actions: [], labels: { continue: '检查并继续', stop_auto_retry: '停止自动重试' }, auto_retry: { ...f.auto_retry, now: 'continue', total: null } };
  assert.deepEqual(keys(R.recoverPlan(cont, { canSwitch: true })), [['continue', '现在重试', 'recover', false], ['stop_auto_retry', '停止自动重试', 'recover', false]]);
});

test('actions 为空就是现在没有能点的：不补一颗检查并继续', () => {
  assert.deepEqual(R.recoverPlan({ title: '换旧模型重试已经排好', actions: [] }, { canSwitch: true }).buttons, []);
});

test('旧数据（没有 labels、how）：用 ui.md 的叫法；换个模型普通话题在网页上换，管家负责人去飞书；其余发 recover', () => {
  const f = { title: '执行进程没有正常退出', actions: ['continue', 'retry', 'switch_model'] };
  assert.deepEqual(keys(R.recoverPlan(f, { canSwitch: true })), [
    ['continue', '检查并继续', 'recover', true],
    ['retry', '现在重试', 'recover', false],
    ['switch_model', '换个模型', 'switch', false],
  ]);
  assert.equal(R.recoverPlan(f, { canSwitch: false }).buttons[2].how, 'feishu');
});

test('自动重试的倒计时从 at 自己算（推的内容不按分钟变）', () => {
  const a = { state: 'pending', at: 1000 + 185, attempt: 2, total: 5, kind: 'rate_limited', now: 'retry' };
  assert.equal(R.autoRetryWords(a, 1000), '约 3 分钟后自动重试（第 2/5 次）');
  assert.equal(R.autoRetryWords({ ...a, total: null }, 1000), '约 3 分钟后自动重试（第 2 次）');
  assert.equal(R.autoRetryWords(a, 1000 + 170), '马上自动重试（第 2/5 次）');
  assert.equal(R.autoRetryWords({ ...a, at: 1000 + 2 * 3600 + 600 }, 1000), '约 2 小时 10 分钟后自动重试（第 2/5 次）');
  assert.equal(R.autoRetryWords({ ...a, at: null, attempt: null }, 1000), '已排好自动重试');
  // 原因那句已经写了第几次（Covey 的 title），倒计时不再重复
  assert.equal(R.autoRetryWords(a, 1000, '限流了，21:40 自动重试（第 2/5 次）'), '约 3 分钟后自动重试');
});

test('recover 的 payload：任务号和动作；没有任务号（旧数据）、换个模型不发 recover', () => {
  assert.deepEqual(R.recoverPayload('22', 'continue'), { job_id: '22', action: 'continue' });
  assert.deepEqual(R.recoverPayload(' 7 ', 'stop_auto_retry'), { job_id: '7', action: 'stop_auto_retry' });
  assert.equal(R.recoverPayload(null, 'continue'), null);
  assert.equal(R.recoverPayload('abc', 'retry'), null);
  assert.equal(R.recoverPayload('22', 'switch_model'), null);
});

test('网页不再替按钮发话：topicText 没有 ACTION_SAY，页面代码里不再有“请在飞书话题里点「🔁 换配置」”', () => {
  assert.equal('ACTION_SAY' in T, false);
  assert.equal('ACTION_LABEL' in T, false);
  for (const f of ['Timeline.tsx', 'TopicOverview.tsx', 'Board.tsx', 'RecoverBits.tsx']) {
    const src = readFileSync(join(CV, f), 'utf8');
    assert.doesNotMatch(src, /🔁 换配置|say\('继续'|ACTION_SAY/u, f);
  }
  // 「换个模型」展开同页的换配置面板（ConfigBar 登记了 openSwitch）
  assert.match(readFileSync(join(CV, 'ConfigBar.tsx'), 'utf8'), /onOpenSwitch\(/u);
  assert.match(readFileSync(join(CV, 'RecoverBits.tsx'), 'utf8'), /openSwitch\(topicKey\)/u);
});

test('服务端：failure 放行 labels、how、auto_retry，只留认得的；不在排着的自动重试不带', () => {
  const f = V.failureOf({
    title: '限流了', detail: 'HTTP 429', actions: ['retry', 'diagnose', 'nope'],
    labels: { retry: '现在重试', diagnose: '看原因', stop_auto_retry: '停止自动重试', bogus: 'x' },
    how: { retry: 'recover', diagnose: 'recover', stop_auto_retry: 'recover', switch_model: 'teleport' },
    auto_retry: { state: 'pending', at: 1800000600.4, attempt: 2, total: 5, kind: 'rate_limited', now: 'retry', extra: 1 },
  });
  assert.deepEqual(f, {
    title: '限流了', detail: 'HTTP 429', actions: ['retry', 'diagnose'],
    labels: { retry: '现在重试', diagnose: '看原因', stop_auto_retry: '停止自动重试' },
    how: { retry: 'recover', diagnose: 'recover', stop_auto_retry: 'recover' },
    auto_retry: { state: 'pending', at: 1800000600.4, attempt: 2, total: 5, kind: 'rate_limited', now: 'retry' },
  });
  assert.equal('auto_retry' in V.failureOf({ title: 'x', actions: [], auto_retry: { state: 'cancelled' } }), false);
  // 旧 Covey（v32 及以前）只推 title、detail、actions：照旧
  assert.deepEqual(V.failureOf({ title: '没做完', actions: ['continue'] }), { title: '没做完', actions: ['continue'] });
});

test('服务端：进度放行 slow_step 和 command（在等命令跑完、这步比平均慢），形状不对就当没有', () => {
  const p = V.progressOf({ phase: '跑测试', maybe_stuck: false, slow_step: { number: 3, since: 1000, seconds: 2100, usual: 360 }, command: { since: 900, seconds: 2280, long: true } });
  assert.deepEqual(p, { phase: '跑测试', slow_step: { number: 3, since: 1000, seconds: 2100, usual: 360 }, command: { since: 900, seconds: 2280, long: true } });
  assert.deepEqual(V.progressOf({ phase: 'x', slow_step: null }), { phase: 'x', slow_step: null });
  assert.deepEqual(V.progressOf({ phase: 'x', slow_step: { number: 'a' }, command: 'no' }), { phase: 'x', slow_step: null });
});

test('服务端：recover 是认得的操作，形状照 docs/web.md（topic_key、payload 只有 job_id 和 action）', () => {
  assert.ok(OUTBOX_KINDS.includes('recover'));
  assert.deepEqual([...RECOVER_ACTIONS], ['continue', 'retry', 'diagnose', 'split', 'stop_auto_retry']);
  assert.deepEqual(V.recoverShape({ job_id: 22, action: 'continue' }, 't1', ''), { job_id: '22' });
  assert.deepEqual(V.recoverShape({ job_id: '23', action: 'stop_auto_retry' }, 't1', ''), { job_id: '23' });
  assert.match(V.recoverShape({ job_id: '1', action: 'continue' }, '', '').error, /topic_key/u);
  assert.match(V.recoverShape({ job_id: '1', action: 'continue' }, 't1', 'p1').error, /project_key/u);
  assert.match(V.recoverShape({ job_id: 'x', action: 'continue' }, 't1', '').error, /job_id/u);
  assert.match(V.recoverShape({ job_id: '1', action: 'switch_model' }, 't1', '').error, /action/u);
  assert.match(V.recoverShape({ job_id: '1', action: 'retry', text: '继续' }, 't1', '').error, /只有/u);
});
