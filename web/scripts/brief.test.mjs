// 专项的「简报」标签（v40，client/src/cv/briefData.ts）：动作的五种状态、一个话题挂几个动作、话题在项目里的位置和影响、没挂条目的话题、
// 任务图（防环）、缺口挂到动作、没有简报字段不报错、服务端怎么过滤 Covey 推来的背景、动作、缺口。跑：npm run test:brief
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as B from '../client/src/cv/briefData.ts';
import * as G from '../client/src/cv/progressData.ts';
import * as S from '../server/modules/workbench/workbench.v4.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const src = (f) => readFileSync(join(CV, f), 'utf8');
const NOW = Date.parse('2026-11-25T21:10:00+08:00') / 1000;
const at = (hm) => Date.parse(`2026-11-25T${hm}:00+08:00`) / 1000;
const item = (id, extra = {}) => ({ id, criterion: `标准 ${id}`, topic: '', needs: [], evidence: '', gap: '', state: 'open', at: 100, ...extra });
const topic = (n, tone, extra = {}) => ({ key: `k${n}`, number: n, title: `话题 ${n}`, kind: 'topic', project_key: 'p1', state: '', unseen: false, updated_at: 1000 + n, tone, latest: '', latest_role: 'agent', ...extra });
const action = (id, extra = {}) => ({ id, title: `动作 ${id}`, note: '', items: [], topics: [], state: 'open', at: 0, ...extra });
const proj = (extra = {}) => ({ key: 'p1', goal: '目标', ...extra });
const snap = (topics, questions = []) => ({ topics, questions });
const brief = (p, topics, questions = [], now = NOW) => B.briefOf(proj(p), snap(topics, questions), now);
const stateOf = (b, id) => b.actions.find((v) => v.action.id === id).state;

test('五种动作状态：等你 > 在做 > 做完 > 待核对 > 将要做，条目和话题一起看', () => {
  const b = brief(
    {
      checklist: [
        item('c1', { state: 'done' }),
        item('c2', { state: 'dropped' }),
        item('c3'),
        item('c4', { gap: '只差主人点头', topic: 'k4' }),
        item('c5', { state: 'done' }),
        item('c6'),
      ],
      actions: [
        action('a1', { items: ['c1', 'c2'], topics: ['k1'] }), // 条目都满足（不做了也算），话题结束了：做完
        action('a2', { items: ['c3'], topics: ['k2'] }), // 条目没满足，话题都结束了：待核对
        action('a3', { items: ['c6'] }), // 还没有话题：将要做
        action('a4', { items: ['c3'], topics: ['k3'] }), // 有话题在跑：在做
        action('a5', { items: ['c4'], topics: ['k3'] }), // 条目的缺口说只差主人（没写 waiting_on）：等你
        action('a6', { items: ['c5'], topics: ['k5'] }), // 条目都满足，可是有话题在跑：在做
        action('a7', { items: ['c5'], topics: ['k6'] }), // 条目都满足，可是有话题在等主人：等你
      ],
    },
    [topic(1, 'done'), topic(2, 'done'), topic(3, 'running'), topic(4, 'done'), topic(5, 'queued'), topic(6, 'waiting')],
  );
  assert.deepEqual(['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'].map((id) => stateOf(b, id)), ['done', 'check', 'next', 'doing', 'owner', 'doing', 'owner']);
  assert.deepEqual(b.counts, { owner: 2, doing: 2, check: 1, done: 1, next: 1 });
  assert.deepEqual(Object.values(B.ACT_WORD), ['等你', '在做', '待核对', '做完', '将要做']);
});

test('等你的几个来源：话题有题没答、检查点写了在等主人；条目 waiting_on 先于缺口文字，没写过才按文字推断', () => {
  const t = (n, extra) => topic(n, 'done', extra);
  const owner = (topics, questions = []) => stateOf(brief({ checklist: [item('c1')], actions: [action('a1', { items: ['c1'], topics: topics.map((x) => x.key) })] }, topics, questions), 'a1');
  assert.equal(owner([t(1)]), 'check');
  assert.equal(owner([t(1)], [{ topic_key: 'k1' }]), 'owner');
  assert.equal(owner([t(1, { progress: { waiting: '要不要换模型？' } })]), 'owner');
  const of = (it) => stateOf(brief({ checklist: [it], actions: [action('a1', { items: [it.id], topics: ['k1'] })] }, [t(1)]), 'a1');
  assert.equal(of(item('c1', { gap: '只差主人操作' })), 'owner'); // 没写过 waiting_on：按缺口文字
  assert.equal(of(item('c1', { gap: '只差主人操作', waiting_on: '' })), 'check'); // 写过空串：不在主人手上
  assert.equal(of(item('c1', { gap: '等 T74 回来', waiting_on: 'owner' })), 'owner'); // 写了 owner：不看文字
  assert.equal(of(item('c1', { gap: '只差主人操作', waiting_on: 'owner', state: 'done' })), 'done'); // 满足了的不算
  assert.equal(G.ownerWaits({ gap: '要主人点头' }), true);
  assert.equal(G.ownerWaits({ gap: '要主人点头', waiting_on: '' }), false);
  // 第一期的三栏（负责人还没写简报时退回）同一个规则
  assert.equal(G.board([item('c1', { gap: '只差主人', waiting_on: '' })], new Map()).placed[0].col, 'next');
  assert.equal(G.board([item('c1', { gap: '没有那几个字', waiting_on: 'owner' })], new Map()).placed[0].col, 'owner');
});

test('动作没有条目：话题都结束了是待核对，还没有话题是将要做，都不算做完', () => {
  const b = brief({ actions: [action('a1', { topics: ['k1'] }), action('a2'), action('a3', { topics: ['k2'] })] }, [topic(1, 'done'), topic(2, 'running')]);
  assert.deepEqual(['a1', 'a2', 'a3'].map((id) => stateOf(b, id)), ['check', 'next', 'doing']);
});

test('“自动”那一行：在动的话题第几步、没在动的写最近哪个话题几点做了什么、没满足的条目、待核对请负责人核对', () => {
  const running = topic(91, 'running', { running: { step_label: '跑测试', step_kind: 'command', plan_doing: '跑全量', plan_done: 2, plan_total: 5, started_at: 1 } });
  const ended = topic(73, 'done', { updated_at: at('20:22') });
  const b = brief(
    {
      checklist: [item('c8', { state: 'done' }), item('c9', { gap: '只差主人', waiting_on: 'owner' }), item('c10', { state: 'blocked' }), item('c11')],
      actions: [action('a1', { items: ['c8', 'c11'], topics: ['k91'] }), action('a2', { items: ['c9', 'c10'], topics: ['k73'] }), action('a3', { items: ['c8'], topics: ['k73'] })],
    },
    [running, ended],
  );
  assert.equal(b.actions[0].auto, 'T91 在做 第 2/5 步 · 还没满足 c11');
  assert.equal(b.actions[1].auto, '最近 T73 20:22 做完 · 还没满足 c9（等你）、c10（卡住）');
  assert.equal(b.actions[2].auto, '最近 T73 20:22 做完 · 检查表 1 条都满足');
  const check = brief({ checklist: [item('c9')], actions: [action('a1', { items: ['c9'], topics: ['k73'] })] }, [ended]);
  assert.equal(check.actions[0].auto, '最近 T73 20:22 做完 · 还没满足 c9 · 话题都结束了，等负责人核对');
  // 昨天的写月-日
  assert.equal(B.autoLine('check', [], [{ ...ended, updated_at: at('20:22') - 86400 }], new Set(), NOW), '最近 T73 11-24 20:22 做完 · 话题都结束了，等负责人核对');
});

test('一个话题挂几个动作：每个动作下面都有它，话题 key、T 号、纯数字都认；也在动作 N 写在行里', () => {
  const b = brief(
    {
      checklist: [item('c1', { topic: 'k58', topics: ['T95', '64'] }), item('c2', { topic: 'k58' })],
      actions: [action('a1', { items: ['c1'], topics: ['k58', 'T64'] }), action('a2', { items: ['c2'], topics: ['58', 'k95'] })],
    },
    [topic(58, 'running'), topic(64, 'done'), topic(95, 'done')],
  );
  assert.deepEqual(b.actions.map((v) => v.topics.map((t) => t.number)), [[58, 64], [58, 95]]);
  assert.deepEqual(b.byTopic.get('k58').map((v) => v.n), [1, 2]);
  assert.deepEqual([...b.deliver.entries()].map(([k, v]) => [k, v]).sort(), [['k58', ['c1', 'c2']], ['k64', ['c1']], ['k95', ['c1']]]);
  const pos = B.positionOf(b, 'k58');
  assert.deepEqual(pos.acts.map((v) => v.n), [1, 2]);
  // 简报动态里一行写两个动作和各自的状态
  assert.match(b.feed.find((f) => f.topic?.number === 58).text, /^在做 → 动作 1、动作 2：在做、在做$/u);
  // 没结束的话题排前面，动作号取 id 里的数字，dropped 的不画、号码不重排
  const d = brief({ actions: [action('a3', { title: '后' }), action('a1', { title: '前' }), action('a2', { state: 'dropped' })] }, []);
  assert.deepEqual(d.actions.map((v) => [v.n, v.action.title]), [[1, '前'], [3, '后']]);
});

test('位置和影响（本专项真实形状）：T92 交付 c20，前置 c17 再往前 c6，解锁 c15 再往后 c12', () => {
  const b = brief(
    {
      checklist: [
        item('c6', { state: 'done', topic: 'k65', title: '部署和测试' }),
        item('c17', { state: 'done', needs: ['c6'], topic: 'k74' }),
        item('c20', { state: 'done', needs: ['c17'], topic: 'k92' }),
        item('c15', { state: 'done', needs: ['c20'], topic: 'k95' }),
        item('c12', { needs: ['c15', 'c4'], topic: 'k95' }),
        item('c4', { state: 'open' }),
      ],
      actions: [action('a2', { title: '跟上游同步和部署', items: ['c6', 'c17', 'c20', 'c15'], topics: ['k92', 'k65', 'k74', 'k95'] }), action('a4', { items: ['c12', 'c4'], topics: ['k95'] })],
    },
    [topic(92, 'done'), topic(65, 'done'), topic(74, 'done'), topic(95, 'done')],
  );
  const pos = B.positionOf(b, 'k92');
  assert.deepEqual([pos.mine, pos.up, pos.upMore, pos.down, pos.downMore], [['c20'], ['c17'], ['c6'], ['c15'], ['c12']]);
  assert.equal(pos.line, '交付 c20✓ · 前置 c17✓ · 解锁 c15✓');
  assert.deepEqual(pos.acts.map((v) => v.n), [2]);
  assert.deepEqual(pos.effects, [
    '动作 2「跟上游同步和部署」：检查表 4/4 满足，动作做完',
    '解锁的 c15 已经满足（T95 做的）',
    '整个专项：目标检查表 4/6 满足，其中 1 条是它交付的',
  ]);
  // 交付的条目还没满足时：动作还差谁，后面的条目是不是就可以开始
  const open = brief(
    {
      checklist: [item('c20', { topic: 'k92' }), item('c15', { needs: ['c20'] }), item('c16', { needs: ['c20', 'c4'] }), item('c21', { needs: ['c20'], state: 'done' }), item('c4'), item('c22', { topic: 'k92', state: 'done' })],
      actions: [action('a2', { title: '同步', items: ['c20', 'c15', 'c22'], topics: ['k92'] }), action('a3', { items: ['c4'] })],
    },
    [topic(92, 'running')],
  );
  const p2 = B.positionOf(open, 'k92');
  assert.deepEqual([p2.mine, p2.down], [['c20', 'c22'], ['c15', 'c16', 'c21']]);
  assert.equal(p2.line, '交付 c20○、c22✓ · 解锁 c15○、c16○、c21✓');
  assert.deepEqual(p2.effects, [
    '动作 2「同步」：检查表 1/3 满足；它的 c20 满足后，只差 c15',
    '它的条目满足后，c15 就可以开始',
    '它的条目满足后，c16 还在等 c4',
    '解锁的 c21 已经满足',
    '整个专项：目标检查表 2/6 满足，其中 1 条是它交付的',
  ]);
  // 动作里还有别人的条目没满足、它自己的条目已经满足：写还差谁（不是它交付的）
  const rest = brief({ checklist: [item('c1', { topic: 'k1', state: 'done' }), item('c2')], actions: [action('a1', { items: ['c1', 'c2'], topics: ['k1'] })] }, [topic(1, 'done')]);
  assert.equal(B.positionOf(rest, 'k1').effects[0], '动作 1「动作 a1」：检查表 1/2 满足，还差 c2（不是它交付的）');
  const part = brief({ checklist: [item('c1', { topic: 'k1' }), item('c2')], actions: [action('a1', { items: ['c1', 'c2'], topics: ['k1'] })] }, [topic(1, 'running')]);
  assert.equal(B.positionOf(part, 'k1').effects[0], '动作 1「动作 a1」：检查表 0/2 满足；它的 c1 满足后，只差 c2');
});

test('条目的 topics：参与这一条的几个话题都算交付，topic 是主要的；选中话题时高亮它、前置和被它解锁的', () => {
  const b = brief(
    {
      checklist: [item('c1', { topic: 'k1', state: 'done' }), item('c2', { topic: 'k2', topics: ['k3', 'k2'], needs: ['c1'] }), item('c3', { needs: ['c2'], topic: 'k4' }), item('c4', { needs: ['c3'] })],
      actions: [action('a1', { items: ['c1', 'c2', 'c3', 'c4'], topics: ['k1', 'k2', 'k3', 'k4'] })],
    },
    [topic(1, 'done'), topic(2, 'done'), topic(3, 'running'), topic(4, 'done')],
  );
  assert.deepEqual(B.topicRefs(b.ctx.items.get('c2')), ['k2', 'k3']);
  assert.deepEqual(b.deliver.get('k3'), ['c2']);
  const tr = B.traceOf(b, 'k3');
  assert.deepEqual([[...tr.self], [...tr.up], [...tr.down].sort(), tr.acts], [['c2'], ['c1'], ['c3', 'c4'], ['a1']]);
  assert.equal(B.edgeOn(tr, { from: 'c1', to: 'c2' }), true);
  assert.equal(B.edgeOn(tr, { from: 'c2', to: 'c3' }), true);
  assert.equal(B.edgeOn(tr, { from: 'c3', to: 'c4' }), true);
  assert.equal(B.edgeOn(B.traceOf(b, 'k1'), { from: 'c3', to: 'c4' }), true); // 一路往后走到底
  assert.equal(B.edgeOn(B.traceOf(b, 'k4'), { from: 'c1', to: 'c2' }), true); // 一路往前走到底
  assert.equal(B.edgeOn(B.traceOf(b, 'k3'), { from: 'c9', to: 'c8' }), false);
  assert.deepEqual(b.unmapped, []);
});

test('没挂条目的话题：位置写只挂在动作几；动作也没挂的写还没挂；列进还没挂到条目上的话题', () => {
  const b = brief(
    { checklist: [item('c1', { topic: 'k1' })], actions: [action('a1', { items: ['c1'], topics: ['k1', 'k91'] }), action('a3', { topics: ['k91'] })] },
    [topic(1, 'done'), topic(91, 'done'), topic(75, 'done'), { ...topic(80, 'done'), project_key: 'p2' }],
  );
  const p91 = B.positionOf(b, 'k91');
  assert.deepEqual(p91.mine, []);
  assert.equal(p91.line, '只挂在动作 1、动作 3，没对应检查表条目');
  assert.equal(p91.effects.at(-1), '整个专项：目标检查表 0/1 满足');
  assert.equal(B.positionOf(b, 'k75').line, '还没挂到动作和检查表条目上');
  assert.deepEqual(b.unmapped.map((t) => t.number), [91, 75]);
  assert.equal(B.positionOf(b, 'k91').effects.length, 3);
  // 抽屉里写“还没挂到检查表条目上”，位置那一行有「在任务图里看」
  const view = src('ProjectBrief.tsx');
  assert.match(view, /这个话题还没挂到检查表条目上/u);
  assert.match(view, /在任务图里看 ›/u);
});

test('任务图：一个动作一行，有依赖的按深度从左往右，没依赖的填空格，没挂动作的单独一行；成环、自己等自己不死循环', () => {
  const items = new Map([
    ['c1', item('c1', { state: 'done' })],
    ['c2', item('c2', { needs: ['c1'] })],
    ['c3', item('c3', { needs: ['c2'] })],
    ['c4', item('c4')],
    ['c5', item('c5')],
    ['c6', item('c6', { needs: ['c6', 'c9'] })],
    ['c7', item('c7')],
  ]);
  const g = B.graphOf(items, [{ id: 'a1', items: ['c1', 'c2', 'c3', 'c4'] }, { id: 'a2', items: ['c5', 'c4'] }, { id: 'a3', items: [] }]);
  const { LW, NW, NH, XG, YG, LP } = B.GBOX;
  const pos = Object.fromEntries(g.nodes.map((n) => [n.id, [n.x, n.y]]));
  const col = (c) => LW + c * (NW + XG);
  assert.deepEqual(pos.c1, [col(0), LP]);
  assert.deepEqual(pos.c2, [col(1), LP]);
  assert.deepEqual(pos.c3, [col(2), LP]);
  assert.deepEqual(pos.c4, [col(3), LP]); // 没依赖的填在第一行空着的格子里
  assert.equal(g.nodes.filter((n) => n.id === 'c4').length, 1); // 在两个动作里也只画一次（第一个）
  assert.deepEqual(g.lanes.map((l) => l.id), ['a1', 'a2', 'a3', '']);
  assert.equal(g.lanes[1].y, LP + NH + LP * 2);
  assert.deepEqual(pos.c5, [col(0), g.lanes[1].y]);
  assert.equal(g.lanes[3].y > g.lanes[2].y, true); // 空的动作也占一行
  assert.deepEqual(g.nodes.map((n) => n.id).sort(), ['c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7']);
  assert.equal(new Set(g.nodes.map((n) => `${n.x},${n.y}`)).size, 7);
  assert.equal(g.cols >= 4, true);
  assert.equal(g.width, LW + g.cols * (NW + XG) - XG + 4);
  assert.equal(g.height > LP + (NH + YG), true);
  // 成环：c1 → c2 → c3 → c1
  const loop = B.graphOf(new Map([['c1', item('c1', { needs: ['c3'] })], ['c2', item('c2', { needs: ['c1'] })], ['c3', item('c3', { needs: ['c2'] })]]), [{ id: 'a1', items: ['c1', 'c2', 'c3'] }]);
  assert.equal(loop.nodes.length, 3);
  assert.equal(new Set(loop.nodes.map((n) => `${n.x},${n.y}`)).size, 3);
  assert.equal(loop.edges.length, 3);
  // 成环时一路往前、往后也走得完
  const b = brief({ checklist: [item('c1', { needs: ['c3'], topic: 'k1' }), item('c2', { needs: ['c1'] }), item('c3', { needs: ['c2'] })], actions: [action('a1', { items: ['c1', 'c2', 'c3'], topics: ['k1'] })] }, [topic(1, 'running')]);
  const tr = B.traceOf(b, 'k1');
  assert.deepEqual([[...tr.up].sort(), [...tr.down].sort()], [['c2', 'c3'], ['c2', 'c3']]);
  assert.equal(B.positionOf(b, 'k1').effects.length >= 2, true);
  // 没有检查表：只有空的动作行，不报错
  assert.deepEqual(B.graphOf(new Map(), []).nodes, []);
  assert.equal(brief({ actions: [action('a1')] }, []).graph.nodes.length, 0);
});

test('缺口挂到包含这个话题的动作上（key 和 T 号都认）；报缺口的话题不在任何动作里的另列', () => {
  const b = brief(
    {
      actions: [action('a1', { topics: ['k91'] }), action('a2', { topics: ['k92'] })],
      gaps: [{ id: 'g1', thread: 'k91', text: '缺 T86 的回执', at: 5 }, { id: 'g2', thread: 'T92', text: '缺凭据', at: 6 }, { id: 'g3', thread: 'k99', text: '没人认领', at: 7 }],
    },
    [topic(91, 'done'), topic(92, 'done'), topic(99, 'done')],
  );
  assert.deepEqual(b.actions.map((v) => v.gaps.map((g) => g.id)), [['g1'], ['g2']]);
  assert.deepEqual(b.strayGaps.map((g) => g.id), ['g3']);
  const view = src('ProjectBrief.tsx');
  assert.match(view, /⚠ 缺口/u);
  assert.match(view, /没挂到动作的缺口/u);
});

test('一个动作下面显示哪些话题：没结束的都显示再补到最近 2 个，其余收成一排；做完的动作只留 T 号', () => {
  const ts = [topic(1, 'running'), topic(2, 'done', { updated_at: 50 }), topic(3, 'done', { updated_at: 40 }), topic(4, 'stopped', { updated_at: 30 }), topic(5, 'waiting')];
  const b = brief({ checklist: [item('c1')], actions: [action('a1', { items: ['c1'], topics: ts.map((t) => t.key) })] }, ts);
  const v = b.actions[0];
  assert.deepEqual(v.topics.map((t) => t.number), [5, 1, 2, 3, 4]); // 没结束的在前，其余新的在前
  const { shown, rest } = B.sessionsOf(v, b.ctx.asked);
  assert.deepEqual([shown.map((t) => t.number), rest.map((t) => t.number)], [[5, 1], [2, 3, 4]]);
  assert.equal(B.restWords(rest), '做完 2、停住了 1');
  const quiet = brief({ checklist: [item('c1')], actions: [action('a1', { items: ['c1'], topics: ['k2', 'k3', 'k4'] })] }, ts.slice(1, 4));
  assert.deepEqual(B.sessionsOf(quiet.actions[0], quiet.ctx.asked).shown.map((t) => t.number), [2, 3]);
  const done = brief({ checklist: [item('c1', { state: 'done' })], actions: [action('a1', { items: ['c1'], topics: ['k2', 'k3'] })] }, ts.slice(1, 3));
  assert.deepEqual([done.actions[0].state, B.sessionsOf(done.actions[0], done.ctx.asked).shown.length, B.sessionsOf(done.actions[0], done.ctx.asked).rest.length], ['done', 0, 2]);
});

test('话题身上读出来的几样：Bridge 垫的阶段不算，下一步以“无”开头的不算，第几步，最后结论只取它自己答完的', () => {
  const t = topic(7, 'running', { progress: { phase: '准备处理本轮请求', next_step: '无', plan_done: 2, plan_total: 5, waiting: '  ' }, running: { step_label: 'x', step_kind: 'k', plan_doing: '跑全量单测', plan_done: 2, plan_total: 5, started_at: 1 } });
  assert.deepEqual([B.phaseOf(t), B.nextStepOf(t), B.stepLine(t), B.waitsOwner(t, new Set())], ['', '', '第 2/5 步「跑全量单测」', false]);
  const u = topic(8, 'done', { progress: { phase: '模板已跟上线上', next_step: '负责人核对', plan_done: 5, plan_total: 5 }, latest: '模板已跟上线上，两个提交都在本地', latest_role: 'agent', latest_status: 'done' });
  assert.deepEqual([B.phaseOf(u), B.nextStepOf(u), B.stepLine(u), B.lastWord(u)], ['模板已跟上线上', '负责人核对', '第 5/5 步', '模板已跟上线上，两个提交都在本地']);
  assert.equal(B.lastWord({ ...u, latest_role: 'owner' }), '');
  assert.equal(B.lastWord({ ...u, latest_status: 'running' }), '');
  assert.equal(B.waitsOwner(topic(9, 'waiting'), new Set()), true);
  assert.equal(B.waitsOwner(topic(9, 'done'), new Set(['k9'])), true);
});

test('条目：状态词、短标题没有就用标准；等你、卡住、不做了各有图标', () => {
  assert.deepEqual(['done', 'dropped', 'blocked', 'open'].map((s) => B.itemKind(item('c1', { state: s }))), ['done', 'gone', 'stop', 'next']);
  assert.equal(B.itemKind(item('c1', { gap: '只差主人', state: 'blocked' })), 'wait');
  assert.equal(B.itemKind(item('c1', { gap: '只差主人', waiting_on: '' })), 'next');
  assert.equal(B.itemName(item('c1', { title: '短标题' })), '短标题');
  assert.equal(B.itemName(item('c1')), '标准 c1');
  assert.deepEqual(Object.values(B.ITEM_WORD), ['满足', '等你', '卡住', '没满足', '不做了']);
  assert.equal(B.fitText('部署和测试流程', 8), '部署和测…');
  assert.equal(B.fitText('abc', 8), 'abc');
});

test('等你、简报动态、统计：条目和话题里要你做的都列；动态按时间新的在前，话题自动、负责人改动作', () => {
  const b = brief(
    {
      checklist: [item('c1', { gap: '只差主人操作', waiting_on: 'owner' }), item('c2', { state: 'done' }), item('c3')],
      actions: [action('a4', { title: '接入', items: ['c1'], topics: ['k1'], at: at('20:47') }), action('a5', { items: ['c2'], topics: ['k2', 'k3'], at: at('19:00') })],
    },
    [topic(1, 'waiting', { updated_at: at('21:00'), progress: { waiting: '设置卡固定哪个配置？' } }), topic(2, 'done', { updated_at: at('20:00') }), topic(3, 'running', { updated_at: at('20:30'), progress: { plan_done: 1, plan_total: 4 } }), topic(4, 'done')],
  );
  assert.deepEqual(b.owner.map((r) => [r.kind, r.n, r.item?.id ?? r.topic.number, r.text]), [['item', 4, 'c1', '只差主人操作'], ['topic', 4, 1, '设置卡固定哪个配置？']]);
  assert.deepEqual(b.feed.map((f) => [f.who, f.topic?.number ?? 0]), [['auto', 1], ['lead', 0], ['auto', 3], ['auto', 2], ['lead', 0]]);
  assert.equal(b.feed[0].text, '等你 → 动作 4：等你');
  assert.equal(b.feed[2].text, '在做 第 1/4 步 → 动作 5：在做');
  assert.equal(b.feed[1].text, '改了动作 4「接入」');
  assert.deepEqual([b.members.length, b.liveN, b.met, b.total, b.changedAt], [4, 1, 1, 3, at('20:47')]);
  assert.deepEqual(b.unmapped.map((t) => t.number), [1, 2, 3, 4]);
});

test('和负责人说：引用是“关于动作 3「标题」· 状态 · 那一句”，话题是“关于 T91「标题」”', () => {
  const b = brief({ actions: [action('a3', { title: 'GreenCloud 链路', note: '在做：今晚高峰回看' })] }, []);
  assert.equal(B.quoteAction(b.actions[0]), '关于动作 3「GreenCloud 链路」· 将要做 · 在做：今晚高峰回看');
  assert.equal(B.quoteAction({ n: 1, state: 'done', action: action('a1', { title: 'x' }) }), '关于动作 1「x」· 做完');
  assert.equal(B.quoteTopic({ number: 91, title: '隧道切连接池' }), '关于 T91「隧道切连接池」');
  assert.equal(G.withQuote(B.quoteTopic({ number: 9, title: 'a' }), '先等一下'), '关于 T9「a」\n先等一下');
  const view = src('ProjectBrief.tsx');
  assert.match(view, /setDraft\(lead\.key, withQuote\(quote, getDraft\(lead\.key\)\)\)/u);
  assert.match(view, /nav\(base\)/u);
  assert.match(view, /和负责人说/u);
});

test('没有简报字段时不报错：没写背景和动作就退回第一期的三栏，加一句“负责人还没写背景和动作”；只写了背景也算有简报', () => {
  const none = brief({}, []);
  assert.deepEqual([none.has, none.actions, none.owner, none.feed, none.strayGaps, none.unmapped, none.graph.nodes, none.total, none.changedAt], [false, [], [], [], [], [], [], 0, 0]);
  assert.equal(brief({ checklist: [item('c1')] }, [topic(1, 'done')]).has, false);
  assert.equal(brief({ background: '跑本机机器人' }, []).has, true);
  assert.equal(brief({ actions: [action('a1', { state: 'dropped' })] }, []).has, false); // 只剩 dropped 的：没有可画的动作
  assert.equal(brief({ actions: [action('a1')] }, []).has, true);
  // 动作引用了不存在的条目和话题：照样算
  const odd = brief({ actions: [action('a1', { items: ['c9'], topics: ['k404'] })], gaps: [{ id: 'g', thread: 'k404', text: 'x', at: 0 }] }, []);
  assert.deepEqual([odd.actions[0].state, odd.actions[0].items, odd.actions[0].topics], ['next', [], []]);
  assert.equal(odd.strayGaps.length, 1);
  const view = src('ProjectBrief.tsx');
  assert.match(view, /if \(!b\.has\) return <ProjectProgress [^>]*hint="负责人还没写背景和动作"/u);
  assert.match(src('ProjectProgress.tsx'), /hint \? <div className="pg-hintbar"/u);
});

test('服务端：背景、动作、缺口按类型过滤，坏的那条不要，一条不剩就当没推', () => {
  assert.equal(S.actionsOf(undefined), undefined);
  assert.equal(S.actionsOf({ items: [] }), undefined);
  assert.equal(S.actionsOf([{ id: 'a1', title: '', state: 'open' }]), undefined);
  const got = S.actionsOf([
    { id: 'a1', title: ' 仓库搭建 ', note: '在做：回看', items: ['c1', 'c1', 'x2', 3, 'c4'], topics: ['k1', 'T92', '', 'k1', 7], state: 'open', at: 12.5, job: 'j' },
    { id: 'a2', title: '不做了', state: 'dropped' },
    { id: 'a3', title: '状态不对', state: 'done' },
    { id: 'x4', title: 'id 不对', state: 'open' },
    { id: 'a1', title: '重复的', state: 'open' },
    { id: 'a5', title: '没有 at', state: 'open', at: 'soon' },
    'a6',
  ]);
  assert.deepEqual(got, [
    { id: 'a1', title: '仓库搭建', note: '在做：回看', items: ['c1', 'c4'], topics: ['k1', 'T92'], state: 'open', at: 12.5 },
    { id: 'a2', title: '不做了', note: '', items: [], topics: [], state: 'dropped', at: 0 },
    { id: 'a5', title: '没有 at', note: '', items: [], topics: [], state: 'open', at: 0 },
  ]);
  assert.equal(S.actionsOf(Array.from({ length: 50 }, (_, i) => ({ id: `a${i + 1}`, title: `第 ${i} 个`, state: 'open' }))).length, 40);
  assert.equal(S.gapsOf('x'), undefined);
  assert.equal(S.gapsOf([{ id: 'g1', text: '' }, { text: '没有 id' }]), undefined);
  assert.deepEqual(S.gapsOf([{ id: 'g1', thread: 'k91', text: '缺 T86 的回执', at: 5 }, { id: 'g2', text: '没写话题', at: 'x' }, 'g3']), [
    { id: 'g1', thread: 'k91', text: '缺 T86 的回执', at: 5 },
    { id: 'g2', thread: '', text: '没写话题', at: 0 },
  ]);
  assert.equal(S.gapsOf([{ id: 'g1', text: '字'.repeat(300) }])[0].text.length, 200);
  assert.equal(S.backgroundOf(undefined), undefined);
  assert.equal(S.backgroundOf('   '), undefined);
  assert.equal(S.backgroundOf({ text: '对象不要' }), undefined);
  assert.equal(S.backgroundOf(' 跑本机机器人 '), '跑本机机器人');
  assert.equal(S.backgroundOf('字'.repeat(400)).length, 300);
});

test('服务端：检查表条目的 title、waiting_on、done_at、topics 有才带，形状不对不带；旧数据照旧；话题进度多 next_step、waiting', () => {
  const [a, b, c] = S.checklistOf([
    { id: 'c1', criterion: '新库能写', state: 'done', title: ' 新库 ', waiting_on: 'owner', done_at: 99.5, topics: ['k1', 'T92', 'k1', '', 5] },
    { id: 'c2', criterion: '对账', state: 'open', waiting_on: '', done_at: 0, topics: [] },
    { id: 'c3', criterion: '旧数据', state: 'open', waiting_on: 'someone', done_at: 'x', topics: 'k1', title: '  ' },
  ]);
  assert.deepEqual(a, { id: 'c1', criterion: '新库能写', topic: '', needs: [], evidence: '', gap: '', state: 'done', at: 0, title: '新库', waiting_on: 'owner', done_at: 99.5, topics: ['k1', 'T92'] });
  assert.deepEqual(b, { id: 'c2', criterion: '对账', topic: '', needs: [], evidence: '', gap: '', state: 'open', at: 0, waiting_on: '' });
  assert.deepEqual(c, { id: 'c3', criterion: '旧数据', topic: '', needs: [], evidence: '', gap: '', state: 'open', at: 0 });
  assert.deepEqual(S.progressOf({ phase: '在跑', next_step: ' 下一步做回看 ', waiting: '字'.repeat(200) }), { phase: '在跑', next_step: '下一步做回看', waiting: '字'.repeat(160) });
  assert.deepEqual(S.progressOf({ phase: '在跑', next_step: '', waiting: 3 }), { phase: '在跑' });
  assert.equal(S.progressOf({ next_step: '字'.repeat(200) }).next_step.length, 120);
});

test('专项页：「简报」放在全图和报告之间，路由 /brief，/progress 跳到 /brief；总览每个专项一张简报卡', () => {
  const page = src('ProjectPage.tsx');
  assert.match(page, /\['graph', '\/graph', '全图'\], \['brief', '\/brief', '简报'\], \['report', '\/report', '报告'\]/u);
  assert.match(page, /rest\.startsWith\('\/brief'\)/u);
  assert.match(page, /if \(rest\.startsWith\('\/progress'\)\) return <Navigate to=\{`\$\{base\}\/brief\$\{loc\.search\}`\} replace \/>/u);
  assert.doesNotMatch(page, /'进度'/u);
  const list = src('ProjectsPage.tsx');
  assert.match(list, /briefOf\(p, snap, now\)/u);
  assert.match(list, /<BriefBlock b=\{brief\} base=\{base\} \/>/u);
  assert.match(list, /负责人还没写背景和动作/u);
});
