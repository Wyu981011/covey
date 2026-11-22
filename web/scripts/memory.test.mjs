// 三层记忆面板（包 E，client/src/cv/memoryLayers.ts）：按长期约定、当前决定、历史记录分组，来源只作标签和筛选，
// 旧数据没有 layer 时照旧画，纠正动作什么时候能点。跑：npm run test:memory
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../client/src/cv/memoryLayers.ts';

const m = (id, extra = {}) => ({ id, text: `记忆 ${id}`, at: 100, ...extra });
const ids = (list) => list.map((x) => x.id);

test('旧数据（没有 layer）：不算分层，面板照旧画', () => {
  const old = [m('a', { said_by: '你说的', source: 'owner' }), m('b', { said_by: '它总结的', source: 'lead' })];
  assert.equal(M.isLayered(old), false);
  assert.equal(M.isLayered([]), false);
  assert.equal(M.isLayered([...old, m('c', { layer: 'decision' })]), true);
});

test('三层：长期约定分已确认的规则和待核对参考（只认 level=owner），当前决定，历史记录；没分层的单放', () => {
  const list = [
    m('r1', { layer: 'rule', level: 'owner', asserted_by: 'owner', recorded_by: 'bridge', at: 300 }),
    m('r2', { layer: 'rule', level: 'agent', asserted_by: 'lead', recorded_by: 'lead', at: 200 }),
    // 模型说“主人同意了”也换不来 owner：level 是 agent 就是待核对
    m('r3', { layer: 'rule', level: 'agent', asserted_by: 'owner', recorded_by: 'lead', at: 250 }),
    m('d1', { layer: 'decision', level: 'owner', at: 150 }),
    m('d2', { layer: 'decision', level: 'owner', valid: 'superseded', superseded_by: 'd1', at: 120 }),
    m('h1', { layer: 'history', level: 'owner', at: 90 }),
    m('o1', { said_by: '你说的', at: 80 }),
  ];
  const [rule, decision, history, other] = M.layers(list);
  assert.deepEqual([rule.title, decision.title, history.title, other.title], ['长期约定', '当前决定', '历史记录', '还没分层']);
  assert.deepEqual(rule.parts.map((p) => [p.title, ids(p.live)]), [['已确认的规则', ['r1']], ['待核对参考', ['r3', 'r2']]]);
  assert.deepEqual([ids(decision.parts[0].live), ids(decision.parts[0].gone)], [['d1'], ['d2']]);
  assert.deepEqual([rule.count, decision.count, history.count, other.count], [3, 1, 1, 1]);
  assert.equal(M.replacedBy(list[4], list).id, 'd1');
  // 某一层空着也在（主轴不变）
  assert.deepEqual(M.layers([m('x', { layer: 'history' })]).map((l) => [l.key, l.count]), [['rule', 0], ['decision', 0], ['history', 1]]);
});

test('来源只作标签和筛选：你说的跟着 asserted_by（旧数据看 said_by）；没对上出处的原话照样是你说的，另说明', () => {
  const owner = m('a', { layer: 'rule', part: 'rule', level: 'owner', asserted_by: 'owner', recorded_by: 'bridge' });
  // 包 B：改成一题一条之前的“主人答：…”旧条目没有出处，算你说的当前决定，level 是 agent
  const oldAnswer = m('b', { layer: 'decision', part: 'decision', level: 'agent', asserted_by: 'owner', recorded_by: 'bridge' });
  const lead = m('c', { layer: 'decision', part: 'reference', level: 'agent', asserted_by: 'lead', recorded_by: 'lead' });
  const legacy = m('d', { layer: 'history', said_by: '你说的' });
  assert.deepEqual([owner, oldAnswer, lead, legacy].map((x) => M.sourceOf(x).tag), ['你说的', '你说的', '它总结的', '你说的']);
  assert.equal(M.sourceOf(owner).detail, '你说的，按原话记下');
  assert.equal(M.sourceOf(oldAnswer).detail, '你说的，还没找到原话的出处');
  assert.equal(M.sourceOf(lead).detail, '负责人总结的');
  assert.deepEqual(M.whoCounts([owner, oldAnswer, lead, legacy]), { all: 4, you: 3, ai: 1 });
  assert.deepEqual(ids(M.pick([owner, oldAnswer, lead, legacy], 'ai')), ['c']);
  const youOnly = M.layers([owner, oldAnswer, lead], 'you');
  assert.deepEqual(youOnly.map((l) => l.count), [1, 1, 0]);
});

test('包 B 的推送（app/web_collect.py memory_row）：按 part 分段，风格行单列写法，历史记录直接列，下一轮带不带', () => {
  const pid = 'p1';
  const row = (id, extra) => m(id, { ref: `project:${pid}:${id}`, by: extra.asserted_by === 'owner' ? 'owner' : 'lead', said_by: extra.asserted_by === 'owner' ? '你说的' : '它总结的', applies: '', valid: 'active', superseded_by: '', carried: true, ...extra });
  const list = [
    row('r1', { layer: 'rule', part: 'rule', level: 'owner', asserted_by: 'owner', recorded_by: 'bridge', origin: { at: 1, message_id: 'om_1', quote: '以后对跑都带基线' } }),
    row('r2', { layer: 'rule', part: 'reference', level: 'agent', asserted_by: 'lead', recorded_by: 'lead', carried: false }),
    row('s1', { layer: 'rule', part: null, kind: 'style', level: 'agent', asserted_by: 'lead', recorded_by: 'lead' }),
    row('d1', { layer: 'decision', part: 'decision', level: 'owner', asserted_by: 'owner', recorded_by: 'bridge', origin: { question: 'abcd', item: 'q1', index: 0, topic: 'k586', topic_number: 586 } }),
    row('d2', { layer: 'decision', part: 'reference', level: 'agent', asserted_by: 'lead', recorded_by: 'lead' }),
    // 做完、被替代的退到历史记录（layer=history，part 为空）：照样列出来，不收进“已失效”
    row('h1', { layer: 'history', part: null, level: 'owner', asserted_by: 'owner', recorded_by: 'bridge', valid: 'superseded', superseded_by: 'd1', carried: false }),
    row('h2', { layer: 'history', part: null, level: 'agent', asserted_by: 'lead', recorded_by: 'lead', valid: 'done', carried: false }),
  ];
  assert.deepEqual(list.map(M.partOf), ['confirmed', 'reference', 'style', 'decision', 'decision_ref', 'history', 'history']);
  const [rule, decision, history] = M.layers(list);
  assert.deepEqual(rule.parts.map((p) => [p.title, ids(p.live)]), [['已确认的规则', ['r1']], ['待核对参考', ['r2']], ['写法', ['s1']]]);
  assert.deepEqual(decision.parts.map((p) => [p.title, ids(p.live)]), [['你定的', ['d1']], ['待核对参考', ['d2']]]);
  assert.deepEqual([ids(history.parts[0].live), history.parts[0].gone.length, history.count], [['h1', 'h2'], 0, 2]);
  assert.equal(M.carriedCount(list), 4);
  assert.equal(M.carriedCount([m('x', { layer: 'rule' })]), null);
  assert.equal(M.carriedWord(list[0]), '话题下一轮会带上');
  assert.equal(M.carriedWord(list[1]), '话题下一轮不带（超出这一段的篇幅）');
  assert.equal(M.quoteOf(list[0]), '以后对跑都带基线');
  assert.deepEqual(M.originOf(list[3]), { question: 'abcd', item: 'q1', index: 0, topic: 'k586', topic_number: 586 });
  // 确认长期：已确认的规则不用；你定的当前决定、待核对参考都能
  assert.deepEqual(list.slice(0, 5).map((x) => M.fixesFor(x, 'project').confirm), [false, true, true, true, true]);
  assert.deepEqual(M.fixesFor(list[5], 'project'), { forget: true, scope: false, once: false, confirm: false });
});

test('适用范围和条件：一句话或分开写的几项', () => {
  assert.equal(M.appliesText('  只在评测对跑时 '), '只在评测对跑时');
  assert.equal(M.appliesText({ scope: '习题专项', when: '对跑新策略', except: '冒烟测试' }), '范围：习题专项；条件：对跑新策略；例外：冒烟测试');
  assert.equal(M.appliesText(undefined), '');
});

test('纠正：有效的才能改；作废只有专项记忆；已确认的规则不用再确认长期；历史记录不改条件', () => {
  const rule = m('r', { layer: 'rule', level: 'owner' });
  const ref = m('f', { layer: 'rule', level: 'agent' });
  const dec = m('d', { layer: 'decision', level: 'agent' });
  const his = m('h', { layer: 'history', level: 'owner' });
  const dead = m('x', { layer: 'rule', level: 'agent', valid: 'void' });
  assert.deepEqual(M.fixesFor(rule, 'project'), { forget: true, scope: true, once: true, confirm: false });
  assert.deepEqual(M.fixesFor(ref, 'project'), { forget: true, scope: true, once: true, confirm: true });
  assert.deepEqual(M.fixesFor(dec, 'topic'), { forget: false, scope: true, once: true, confirm: true });
  assert.deepEqual(M.fixesFor(his, 'project'), { forget: true, scope: false, once: false, confirm: false });
  assert.deepEqual(M.fixesFor(dead, 'project'), { forget: false, scope: false, once: false, confirm: false });
  assert.deepEqual(M.fixesFor({ text: '没有 id', layer: 'rule' }, 'project').forget, false);
});

test('查看原文：出处有话题、消息 id 或题才有', () => {
  assert.equal(M.originOf(m('a', { origin: { at: 100 } })), null);
  assert.deepEqual(M.originOf(m('b', { origin: { message_id: 'om_1' } })), { message_id: 'om_1' });
  assert.deepEqual(M.originOf(m('c', { origin: { question: 'tok', topic: 'k1' } })), { question: 'tok', topic: 'k1' });
});
