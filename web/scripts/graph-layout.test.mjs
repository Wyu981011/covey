// 专项全图的布局验收（T550 评审第 9 条）：node --test scripts/graph-layout.test.mjs
// 2、23、60 个话题，各种状态混着，电脑和手机、三档缩放、做完展开和折起：卡不重叠、线不交叉、线不穿卡，适应后放得进首屏。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GROUP_ORDER, fitLayout, groupOf, layout, problems } from '../client/src/cv/graphLayout.ts';

const TONES = ['waiting', 'stopped', 'stuck', 'running', 'result', 'queued', 'done', 'cancelled', 'idle'];
function topics(n, seed, mix) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
  return Array.from({ length: n }, (_, i) => {
    const tone = mix ? mix[i % mix.length] : TONES[Math.floor(rnd() * TONES.length)];
    const board = rnd() < 0.3 ? '' : tone;
    return { key: `k${i}`, number: 500 + i, group: groupOf(tone, board), sort: Math.floor(rnd() * 1e6) };
  });
}
// 评审时 Covey 专项的样子：23 个，等你 0、在做 8、做完 14、排队 1
const COVEY = [...Array(8).fill('running'), ...Array(14).fill('done'), 'queued'];
const CASES = [
  ['习题 2 个', topics(2, 1, ['waiting', 'running'])],
  ['Covey 23 个', topics(23, 2, COVEY)],
  ['23 个混合', topics(23, 3)],
  ['60 个混合', topics(60, 4)],
  ['60 个在做', topics(60, 5, ['running'])],
  ['空专项', []],
];
const OPENS = [new Set(), new Set(['done']), new Set(['running', 'waiting'])];

for (const [name, list] of CASES) {
  test(`${name}：不重叠、不交叉、不穿卡`, () => {
    for (const compact of [false, true])
      for (const dense of [0, 1, 2])
        for (const toggled of OPENS) {
          const L = layout(list, { compact, dense, toggled });
          assert.deepEqual(problems(L), [], `${name} compact=${compact} dense=${dense} toggled=${[...toggled]}`);
          // 线的条数：交代、负责人到主干、主干、每组一条分支、等你一条
          const groups = new Set(list.map((t) => t.group)).size || 1;
          const lines = L.edges.filter((e) => e.kind !== 'flow').length;
          assert.ok(lines <= 3 + groups + 1, `${name}: ${lines} 条线`);
        }
  });
}

test('等你走顶部通道，在所有组和主干的上方；“你”在负责人正上方', () => {
  const L = layout(topics(23, 3, ['waiting', 'running', 'done', 'stopped']), { compact: false, dense: 0 });
  const you = L.nodes.find((n) => n.kind === 'you');
  const lead = L.nodes.find((n) => n.kind === 'lead');
  assert.equal(you.x + you.w / 2 < lead.x + lead.w, true);
  assert.ok(you.y + you.h <= lead.y);
  const wait = L.edges.find((e) => e.kind === 'wait');
  const lane = Math.min(...wait.pts.map((p) => p[1]));
  for (const b of [...L.nodes, ...L.frames]) assert.ok(b.y > lane, 'lane above everything');
  assert.equal(L.frames[0].group, 'waiting');
});

test('组的顺序固定，空组不画，做完默认折起', () => {
  const L = layout(topics(23, 2, COVEY), { compact: false, dense: 0 });
  assert.deepEqual(L.frames.map((f) => f.group), ['running', 'queued']);
  assert.ok(L.nodes.some((n) => n.kind === 'fold' && n.group === 'done'));
  const order = [...L.frames.map((f) => [f.y, f.group]), ...L.nodes.filter((n) => n.kind === 'fold').map((n) => [n.y, n.group])].sort((a, b) => a[0] - b[0]).map((x) => x[1]);
  assert.deepEqual(order, GROUP_ORDER.filter((g) => order.includes(g)));
});

test('看板分组：停住了、有结果只算看板上的', () => {
  assert.equal(groupOf('stopped', 'stopped'), 'stopped');
  assert.equal(groupOf('stopped', ''), 'done');
  assert.equal(groupOf('stopped', undefined), 'stopped');
  assert.equal(groupOf('result', ''), 'done');
  assert.equal(groupOf('stuck', 'stuck'), 'running');
  assert.equal(groupOf('cancelled', 'cancelled'), 'done');
  assert.equal(groupOf('idle', undefined), 'queued');
});

test('位置只在状态变化时移动：同一组内的话题不动，别的组里的话题更新不影响它', () => {
  const a = topics(23, 3);
  const b = a.map((t) => (t.group === 'done' ? { ...t, sort: t.sort - 7 } : t));
  const L1 = layout(a, { compact: false, dense: 0, toggled: new Set() });
  const L2 = layout(b, { compact: false, dense: 0, toggled: new Set() });
  for (const n of L1.nodes.filter((x) => x.kind === 'card')) {
    const m = L2.nodes.find((x) => x.key === n.key);
    assert.deepEqual([m.x, m.y], [n.x, n.y]);
  }
});

test('1440×1000 下适应：你、负责人、等你、在做都在首屏，字不小于 0.5 倍', () => {
  // 1440 宽减侧栏 248、右栏 316；1000 高减页头和磁贴约 300
  const [cw, ch] = [876, 700];
  for (const [name, list] of CASES) {
    const { L, z } = fitLayout((d) => layout(list, { compact: false, dense: d }), cw, ch);
    assert.ok(z >= 0.5 || L.dense === 2, `${name}: z=${z}`);
    const keep = [...L.nodes.filter((n) => n.kind === 'you' || n.kind === 'lead'), ...L.frames.filter((f) => f.group === 'waiting' || f.group === 'running')];
    for (const b of keep) assert.ok((b.x + b.w) * z <= cw && (b.y + b.h) * z <= ch, `${name}: ${b.key ?? b.group} 出了首屏 z=${z}`);
  }
  const covey = fitLayout((d) => layout(CASES[1][1], { compact: false, dense: d }), cw, ch);
  assert.equal(covey.L.dense, 0, 'Covey 专项 23 个话题不用缩成紧凑行');
});

test('检查本身管用：改前那种点到点的扇形线会被查出交叉和穿卡', () => {
  const L = layout(topics(2, 1, ['waiting', 'running']), { compact: false, dense: 0 });
  const lead = L.nodes.find((n) => n.kind === 'lead');
  const you = L.nodes.find((n) => n.kind === 'you');
  const card = L.nodes.find((n) => n.kind === 'card' && n.group === 'waiting');
  // 改前：等你的回线从卡片左边出来，横着去“你”的右边（穿过负责人）
  const bad = { ...L, edges: [...L.edges, { key: 'old-wait', kind: 'wait', pts: [[card.x, lead.y + 30], [you.x + you.w, lead.y + 30]] }] };
  const p = problems(bad);
  assert.ok(p.some((x) => x.includes('穿过 lead')), p.join('\n'));
  assert.ok(p.some((x) => x.startsWith('线交叉')), p.join('\n'));
});
