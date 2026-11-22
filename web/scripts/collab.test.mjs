// 多参与者协作（包 E）：shared/collab.ts 的 route 和 Covey core/collab.py 逐条一致（tests/test_collab.py 搬过来的），
// 网页的点名、汇总方、发出去的 payload、协作往返和回执放在哪。跑：npm run test:collab
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as K from '../shared/collab.ts';
import * as C from '../client/src/cv/collab.ts';
import * as R from '../client/src/cv/room.ts';

const { BUTLER, LEAD, TOPIC, ROOM, IN_TOPIC, DESK, DIRECT, COLLAB, ROUTER, REFUSED, route } = K;
const P = (key, role, project = '') => ({ key, role, ...(project ? { project } : {}) });
const Route = (to, owner = '', helpers = [], collab = '', shown_default = false, reason = '') => ({ to, owner, helpers, collab, shown_default, reason });
const BUTLER_P = P('b0', BUTLER);
const LEAD_A = P('la', LEAD, 'pa');
const LEAD_B = P('lb', LEAD, 'pb');
const T3 = P('t3', TOPIC);
const T5 = P('t5', TOPIC, 'pa');
const T7 = P('t7', TOPIC);
const T9 = P('t9', TOPIC);
const E = (where, extra = {}) => ({ where, ...extra });

/* ---- route：core/collab.py 的示例消息流，一条一个 ---- */

test('大厅不 @：照原来交给管家', () => {
  assert.deepEqual(route(E(ROOM)), Route(DESK));
});

test('单 @ 直达那一位，现在也可以是普通话题', () => {
  assert.deepEqual(route(E(ROOM, { mentions: [LEAD_A] })), Route(DIRECT, 'la'));
  assert.deepEqual(route(E(ROOM, { mentions: [T3] })), Route(DIRECT, 't3'));
  assert.deepEqual(route(E(ROOM, { mentions: [BUTLER_P] })), Route(DESK));
});

test('多 @ 且引用了话题：被引用的话题汇总', () => {
  const found = route(E(ROOM, { mentions: [T5, T7], quote: { of: T3 } }));
  assert.deepEqual([found.to, found.owner, found.helpers, found.shown_default], [COLLAB, 't3', ['t5', 't7'], false]);
});

test('多 @ 没有上下文：第一个点到的普通话题汇总，写明、可以改', () => {
  const found = route(E(ROOM, { mentions: [LEAD_A, T5, T7] }));
  assert.deepEqual([found.to, found.owner, found.helpers, found.shown_default], [COLLAB, 't5', ['la', 't7'], true]);
  const chosen = route(E(ROOM, { mentions: [LEAD_A, T5, T7], integrator: T7 }));
  assert.deepEqual([chosen.owner, chosen.helpers, chosen.shown_default], ['t7', ['la', 't5'], false]);
});

test('只点了负责人：管家归口一次；点了管家就是管家汇总', () => {
  assert.deepEqual(route(E(ROOM, { mentions: [LEAD_A, LEAD_B] })), Route(ROUTER, '', ['la', 'lb']));
  assert.deepEqual(route(E(ROOM, { mentions: [LEAD_A, BUTLER_P] })), Route(COLLAB, 'b0', ['la']));
  assert.deepEqual(route(E(ROOM, { mentions: [LEAD_A, LEAD_B], integrator: LEAD_B })), Route(COLLAB, 'lb', ['la']));
});

test('在话题里请别人：原话题汇总', () => {
  assert.deepEqual(route(E(IN_TOPIC, { here: T3, mentions: [T5] })), Route(COLLAB, 't3', ['t5']));
  assert.deepEqual(route(E(IN_TOPIC, { here: T3 })), Route(DIRECT, 't3'));
  assert.deepEqual(route(E(IN_TOPIC, { here: T3, mentions: [T3] })), Route(DIRECT, 't3'));
  assert.deepEqual(route(E(IN_TOPIC, { here: T3, mentions: [T5], integrator: T5 })), Route(COLLAB, 't5', ['t3']));
});

test('引用交给被引用的那位；再 @ 一位交给点到的', () => {
  assert.deepEqual(route(E(ROOM, { quote: { of: T3 } })), Route(DIRECT, 't3'));
  assert.deepEqual(route(E(ROOM, { quote: { of: LEAD_A } })), Route(DIRECT, 'la'));
  assert.deepEqual(route(E(ROOM, { quote: { of: BUTLER_P } })), Route(DESK));
  assert.deepEqual(route(E(ROOM, { quote: { of: T3 }, mentions: [T5] })), Route(DIRECT, 't5'));
});

test('引用一次协作里的话：还是那次协作，它的汇总方接', () => {
  const quoted = { of: T5, collab: 'c1', integrator: T3 };
  assert.deepEqual(route(E(ROOM, { quote: quoted })), Route(COLLAB, 't3', [], 'c1'));
  assert.deepEqual(route(E(ROOM, { quote: quoted, mentions: [T5] })), Route(COLLAB, 't3', ['t5'], 'c1'));
  assert.throws(() => route(E(ROOM, { quote: { of: T5, collab: 'c1' } })));
});

test('明确点名负责人：它是协助方，会跑', () => {
  const found = route(E(IN_TOPIC, { here: T5, mentions: [LEAD_A] }));
  assert.deepEqual([found.to, found.owner, found.helpers], [COLLAB, 't5', ['la']]);
});

test('每种说法都只有一个交付归属，或说明谁来定', () => {
  const entries = [E(ROOM), E(ROOM, { mentions: [T3] }), E(ROOM, { mentions: [T3, T5] }), E(ROOM, { mentions: [LEAD_A, LEAD_B] }),
    E(IN_TOPIC, { here: T3, mentions: [T5, T7] }), E(ROOM, { quote: { of: T3 }, mentions: [T5, T7] })];
  for (const entry of entries) {
    const found = route(entry);
    if (found.to === DESK || found.to === ROUTER) assert.equal(found.owner, '');
    else {
      assert.ok(found.owner);
      assert.ok(!found.helpers.includes(found.owner));
    }
  }
});

test('协助方超过 3 位：发起前就拒，什么都不发', () => {
  const four = [T5, T7, T9, LEAD_A];
  for (const entry of [E(IN_TOPIC, { here: T3, mentions: four }), E(ROOM, { mentions: [T3, ...four] }),
    E(ROOM, { mentions: [LEAD_A, LEAD_B, P('lc', LEAD), P('ld', LEAD)] })]) {
    const found = route(entry);
    assert.equal(found.to, REFUSED);
    assert.match(found.reason, /最多请 3 位/u);
  }
  assert.deepEqual(route(E(IN_TOPIC, { here: T3, mentions: four.slice(0, 3) })).helpers, ['t5', 't7', 't9']);
});

test('状态只往前走，终态不回退；词表和状态表对得上', () => {
  const path = [K.CHECKING, K.QUEUED, K.TAKEN, K.REPLIED, K.READ];
  for (let i = 0; i + 1 < path.length; i += 1) assert.equal(K.moved(K.ASK_TRANSITIONS, path[i], path[i + 1]), path[i + 1]);
  for (const ended of [K.READ, K.NOT_TAKEN, K.FAILED, K.EXPIRED, K.CANCELLED]) {
    for (const next of Object.keys(K.ASK_TRANSITIONS)) assert.throws(() => K.moved(K.ASK_TRANSITIONS, ended, next));
  }
  assert.throws(() => K.moved(K.ASK_TRANSITIONS, K.REPLIED, K.QUEUED));
  assert.deepEqual(new Set(Object.keys(K.ASK_WORDS)), new Set(Object.keys(K.ASK_TRANSITIONS)));
  assert.equal(K.moved(K.COLLAB_TRANSITIONS, K.OPEN, K.DONE), K.DONE);
  assert.throws(() => K.moved(K.COLLAB_TRANSITIONS, K.DONE, K.OPEN));
});

/* ---- 网页：点名、汇总方、payload ---- */

const B = 'butler0';
const L1 = 'lead1';
const L2 = 'lead2';
const t = (key, number, title, extra = {}) => ({ key, number, title, kind: 'topic', project_key: null, state: '做完', unseen: false, updated_at: number, ...extra });
const snap = {
  butler_key: B,
  synced_at: null,
  projects: [
    { key: 'p1', title: '夜航改版', goal: '', status: '在做', status_reason: '', lead_topic_key: L1, started_at: 100, topic_keys: ['k12'], memory: [], library: [], updated_at: 500, counts: { topics: 1, waiting: 0, running: 0 } },
    { key: 'p2', title: '习题', goal: '', status: '在做', status_reason: '', lead_topic_key: L2, started_at: 120, topic_keys: [], memory: [], library: [], updated_at: 400, counts: { topics: 0, waiting: 0, running: 0 } },
  ],
  topics: [
    { key: B, number: 0, title: '管家', kind: 'butler', project_key: null, state: '空闲', unseen: false, updated_at: 900 },
    { key: L1, number: 0, title: '负责人', kind: 'lead', project_key: 'p1', state: '空闲', unseen: false, updated_at: 800 },
    t('k12', 12, '密度', { project_key: 'p1', updated_at: 300 }),
    t('k586', 586, 'Golden 作答', { state: '在做', updated_at: 700 }),
    t('k505', 505, '题面优化', { updated_at: 650 }),
    t('k7', 7, '别的', { updated_at: 50 }),
    t('k9', 9, '再一个', { updated_at: 40 }),
  ],
  questions: [],
};
const base = (extra = {}) => ({ where: 'room', here: null, picks: [], integrator: null, quote: null, snap, butler: B, collabs: [], ...extra });

test('点名候选：管家、负责人在前，再是普通话题；按 T 号、标题都能找', () => {
  const list = C.candidates(snap);
  assert.deepEqual(list.slice(0, 3).map((c) => c.name), ['管家', '夜航改版 负责人', '习题 负责人']);
  assert.deepEqual(list.slice(3).map((c) => c.name), ['T586', 'T505', 'T12', 'T7', 'T9']);
  assert.deepEqual(C.searchCandidates(list, 'T505').map((c) => c.key), ['k505']);
  assert.deepEqual(C.searchCandidates(list, '505').map((c) => c.key), ['k505']);
  assert.deepEqual(C.searchCandidates(list, '题').map((c) => c.key), [L2, 'k505']);
  assert.deepEqual(C.searchCandidates(list, 'golden').map((c) => c.key), ['k586']);
  // 话题页里自己不在候选里
  assert.ok(!C.candidates(snap, ['k586']).some((c) => c.key === 'k586'));
});

test('不 @ 交给管家，输入框上不多写；单 @ 普通话题直达', () => {
  const none = C.plan(base());
  assert.deepEqual([none.topicKey, none.line, none.integrator], [B, '', null]);
  const one = C.plan(base({ picks: ['k505'] }));
  assert.deepEqual([one.route.to, one.topicKey, one.line], [DIRECT, 'k505', '交给 T505']);
  assert.deepEqual(C.sayPayload('看下', [], base({ picks: ['k505'] }), one), { text: '看下', room: true, to: ['k505'] });
});

test('多 @：第一个普通话题汇总写明可改；换了才带 integrator', () => {
  const two = base({ picks: [L1, 'k586', 'k505'] });
  const p = C.plan(two);
  assert.deepEqual([p.route.to, p.topicKey, p.owner, p.helpers, p.line, p.change], [COLLAB, 'k586', 'k586', [L1, 'k505'], '这件事由 T586 汇总', true]);
  assert.deepEqual(p.choices, [L1, 'k505']);
  assert.equal(p.integrator, null);
  const changed = C.plan({ ...two, integrator: 'k505' });
  assert.deepEqual([changed.topicKey, changed.line, changed.integrator], ['k505', '这件事由 T505 汇总', 'k505']);
  assert.deepEqual(C.sayPayload('一起核对第 18 题', [], { ...two, integrator: 'k505' }, changed),
    { text: '一起核对第 18 题', room: true, to: [L1, 'k586', 'k505'], integrator: 'k505' });
  // 选的和默认一样：不带
  assert.equal(C.plan({ ...two, integrator: 'k586' }).integrator, null);
});

test('后面再加人不偷偷改掉已经写出来的汇总方', () => {
  // 第一个话题一直是第一个：加人不变，也不用留
  const a = C.addPick(base({ picks: ['k586', 'k505'] }), 'k7');
  assert.deepEqual(a, { picks: ['k586', 'k505', 'k7'], integrator: null });
  // 管家汇总（点了管家和负责人）之后再加一个话题：route 会换成话题，留住管家
  const b = C.addPick(base({ picks: [B, L1] }), 'k505');
  assert.deepEqual(b, { picks: [B, L1, 'k505'], integrator: B });
  const kept = C.plan(base(b));
  assert.deepEqual([kept.owner, kept.topicKey, kept.integrator, kept.line], [B, B, B, '这件事由 管家 汇总']);
  // 管家归口（只有负责人）时还没写出谁汇总：加话题就由它汇总
  const c = C.addPick(base({ picks: [L1, L2] }), 'k505');
  assert.deepEqual(c, { picks: [L1, L2, 'k505'], integrator: null });
  assert.equal(C.plan(base(c)).owner, 'k505');
  // 选过的汇总方：加人不动
  assert.deepEqual(C.addPick(base({ picks: ['k586', 'k505'], integrator: 'k505' }), 'k7').integrator, 'k505');
  // 已经点过的、话题页里自己：不重复加
  assert.deepEqual(C.addPick(base({ picks: ['k586'] }), 'k586').picks, ['k586']);
  assert.deepEqual(C.addPick(base({ where: 'topic', here: 'k586', picks: [] }), 'k586').picks, []);
});

test('移掉一位：实时重算汇总方；移掉选定的汇总方就退回默认', () => {
  const input = base({ picks: [L1, 'k586', 'k505'], integrator: 'k505' });
  const out = C.removePick(input, 'k505');
  assert.deepEqual(out, { picks: [L1, 'k586'], integrator: null });
  assert.equal(C.plan(base(out)).owner, 'k586');
  const gone = C.removePick(base({ picks: [L1, 'k586', 'k505'] }), 'k586');
  assert.equal(C.plan(base(gone)).owner, 'k505');
  const lone = C.removePick(base({ picks: ['k586', 'k505'] }), 'k505');
  assert.deepEqual([C.plan(base(lone)).route.to, C.plan(base(lone)).line], [DIRECT, '交给 T586']);
});

test('只点了负责人：写“由管家归口”，可以改成其中一位', () => {
  const p = C.plan(base({ picks: [L1, L2] }));
  assert.deepEqual([p.route.to, p.topicKey, p.change, p.choices], [ROUTER, B, true, [L1, L2]]);
  assert.match(p.line, /^由管家归口/u);
  const chosen = C.plan(base({ picks: [L1, L2], integrator: L2 }));
  assert.deepEqual([chosen.route.to, chosen.topicKey, chosen.integrator], [COLLAB, L2, L2]);
});

test('协助方超过 3 位：拦下，不发', () => {
  const p = C.plan(base({ picks: ['k586', 'k505', 'k12', 'k7', 'k9'] }));
  assert.equal(p.route.to, REFUSED);
  assert.equal(p.topicKey, null);
  assert.match(p.blocked, /一次最多请 3 位协助，这次点了 4 位/u);
  assert.equal(C.plan(base({ picks: ['k586', 'k505', 'k12', 'k7'] })).blocked, '');
  const inTopic = C.plan(base({ where: 'topic', here: 'k586', picks: ['k505', 'k12', 'k7', 'k9'] }));
  assert.match(inTopic.blocked, /最多请 3 位/u);
});

test('话题页：邀请别人时原话题汇总，topic_key 一直是这个话题，没点人照原来发', () => {
  const here = base({ where: 'topic', here: 'k586', picks: ['k505'] });
  const p = C.plan(here);
  assert.deepEqual([p.route.to, p.topicKey, p.owner, p.line], [COLLAB, 'k586', 'k586', '这件事由 T586（这个话题） 汇总']);
  assert.deepEqual(C.sayPayload('请 T505 一起看', [], here, p), { text: '请 T505 一起看', to: ['k505'] });
  const alone = C.plan(base({ where: 'topic', here: 'k586' }));
  assert.deepEqual([alone.route.to, alone.topicKey, alone.line], [DIRECT, 'k586', '']);
  const moved = C.plan({ ...here, integrator: 'k505' });
  assert.deepEqual([moved.owner, moved.topicKey, moved.integrator], ['k505', 'k586', 'k505']);
});

const collab = (extra = {}) => ({
  key: 'c1', root: { message_id: 'web-op1' }, integrator: 'k586', helpers: ['k505'], state: 'open', created_at: 1000, updated_at: 1100,
  asks: [
    { id: 'a1', from: 'k586', to: 'k505', number: 1, state: 'replied', text: '请给出成功判据的原文和位置。', reply: { text: '题面规定了 X，没有规定 Y。', evidence: [{ text: '题面第 3 段', topic_key: 'k505', seq: 4 }], topic_key: 'k505', seq: 4, at: 1050 } },
    { id: 'a2', from: 'k586', to: 'k505', number: 2, state: 'taken', text: 'Y 是刻意不要求，还是遗漏？', reply: null },
  ],
  ...extra,
});

test('引用协作里的话、回复这次协作：回到那次协作的汇总方，带 quote.collab', () => {
  const quote = { key: 'receipt-c1', topic_key: 'k505', seq: 9, collab: 'c1', who: '这次协作', text: '' };
  const fromHelper = base({ where: 'topic', here: 'k505', quote, collabs: [collab()] });
  const p = C.plan(fromHelper);
  assert.deepEqual([p.route.to, p.owner, p.collab, p.topicKey, p.change], [COLLAB, 'k586', 'c1', 'k505', false]);
  assert.equal(p.line, '回复这次协作，由 T586 汇总');
  assert.deepEqual(C.sayPayload('补一句', [], fromHelper, p), { text: '补一句', quote: { topic_key: 'k505', seq: 9, collab: 'c1' } });
  // 协助方话题里不带引用另说一句：还是对它自己工作的话
  const own = C.plan(base({ where: 'topic', here: 'k505', collabs: [collab()] }));
  assert.deepEqual([own.route.to, own.owner, own.collab], [DIRECT, 'k505', '']);
  // 大厅里引用协作的一句：交给汇总方
  const inRoom = C.plan(base({ quote: { ...quote, topic_key: 'k505' }, collabs: [collab()] }));
  assert.deepEqual([inRoom.topicKey, inRoom.collab], ['k586', 'c1']);
  // 认不出那次协作（条目没到）：当普通引用，不带 collab
  const unknown = base({ quote: { ...quote, collab: 'c9' } });
  const u = C.plan(unknown);
  assert.deepEqual([u.route.to, u.owner, u.collab], [DIRECT, 'k505', '']);
  assert.deepEqual(C.sayPayload('x', [], unknown, u).quote, { topic_key: 'k505', seq: 9 });
});

test('引用一段时拼进引用块；没有那段只带结构化引用', () => {
  const q = { key: 'k', topic_key: 'k12', seq: 3, who: 'T12 密度', text: '第一行\n\n\n\n第二行' };
  assert.equal(C.quoted(' 再压一档 ', q), '> 引用 T12 密度：\n> 第一行\n> \n> 第二行\n\n再压一档');
  assert.equal(C.quoted('只说话', { ...q, text: '' }), '只说话');
});

test('协作条目：形状不对的不认，字数有上限，证据和出处认得几种写法', () => {
  assert.equal(K.collabOf('c1', { helpers: ['a'] }), null);
  const c = K.collabOf('c1', {
    root: 'web-op1', integrator: 'k586', helpers: ['k505', 'k505', 'bad key'], state: 'open', goal_rev: 12, created_at: 1, updated_at: 2,
    asks: [{ id: 'a1', from: 'k586', to: 'k505', number: 2, state: 'replied', text: 'q', reply: { text: 'r', evidence: ['原文', { title: '链接', url: 'https://x.test/a' }, { name: 'js', url: 'javascript:alert(1)' }] } }, { to: '' }],
  });
  assert.deepEqual(c.root, { message_id: 'web-op1' });
  assert.deepEqual(c.helpers, ['k505']);
  assert.equal(c.goal_rev, '12');
  assert.equal(c.asks.length, 1);
  assert.deepEqual(c.asks[0].reply.evidence, [{ text: '原文' }, { text: '链接', link: 'https://x.test/a' }, { text: 'js' }]);
  assert.deepEqual(K.turnCollabOf({ key: 'c1', role: 'helper' }), { key: 'c1', role: 'helper' });
  assert.equal(K.turnCollabOf({ key: 'c1', role: 'owner' }), undefined);
  assert.equal(K.stoppable(c), false);
  assert.equal(K.stoppable(collab()), true);
  assert.equal(K.stoppable(collab({ state: 'cancelled' })), false);
});

test('协作往返的每一行：谁问谁、咨询还是澄清、状态词', () => {
  const lines = C.askLines(collab(), snap, B);
  assert.deepEqual(lines.map((l) => [l.from, l.to, l.what, l.word, l.live]), [['T586', 'T505', '咨询', '已答复', false], ['T586', 'T505', '澄清', '已接手', true]]);
  const head = C.collabHead(collab(), snap, B);
  assert.deepEqual([head.integrator, head.helpers, head.word, head.asks, head.replied], ['T586', ['T505'], '在做', 2, 1]);
});

const turn = (topic, seq, role, at, extra = {}) => ({ key: `${topic}:${seq}`, seq, role, status: 'done', body: `${topic}-${seq}`, job_id: null, started_at: at, ended_at: at + 5, artifacts: [], ...extra });

test('汇总方话题页：协作往返放在发起它的那句话后面，答完的结论在它后面', () => {
  const turns = [turn('k586', 1, 'owner', 900), turn('k586', 2, 'agent', 905), turn('k586', 3, 'owner', 990, { collab: { key: 'c1', role: 'integrator' } }), turn('k586', 4, 'agent', 1200, { collab: { key: 'c1', role: 'integrator' } })];
  const rows = C.topicRows(turns, [collab()], 'k586');
  assert.deepEqual(rows.map((r) => r.key), ['k586:1', 'k586:2', 'k586:3', 'collab-c1', 'k586:4']);
  const groups = C.groupTurns(rows);
  assert.deepEqual(groups.map((g) => [g.owner.map((o) => o.seq), g.agent?.key ?? null]), [[[1], 'k586:2'], [[3], null], [[], 'collab-c1'], [[], 'k586:4']]);
  // 那一轮没带 collab：按协作开始的时刻放
  const plain = C.topicRows([turn('k586', 1, 'owner', 900), turn('k586', 2, 'agent', 905), turn('k586', 3, 'owner', 995), turn('k586', 4, 'agent', 1200)], [collab()], 'k586');
  assert.deepEqual(plain.map((r) => r.key), ['k586:1', 'k586:2', 'k586:3', 'collab-c1', 'k586:4']);
  // 没有协作：原样（分组和原来一样）
  assert.deepEqual(C.topicRows(turns.slice(0, 2), [], 'k586').map((r) => r.key), ['k586:1', 'k586:2']);
});

test('协助方话题页：答咨询那几行收成一行回执，不算它自己的最近一轮', () => {
  const turns = [
    turn('k505', 1, 'owner', 800), turn('k505', 2, 'agent', 850, { body: '题面改好了' }),
    turn('k505', 3, 'owner', 1010, { collab: { key: 'c1', role: 'helper' } }), turn('k505', 4, 'agent', 1040, { collab: { key: 'c1', role: 'helper' }, body: '题面规定了 X' }),
    turn('k505', 5, 'event', 1045, { collab: { key: 'c1', role: 'helper' }, body: '已协助 T586（看这次协作）' }),
  ];
  const rows = C.topicRows(turns, [collab()], 'k505');
  assert.deepEqual(rows.map((r) => r.key), ['k505:1', 'k505:2', 'receipt-c1']);
  const r = C.receiptOf(rows[2], collab(), 'k505', snap, B);
  assert.deepEqual([r.integrator, r.name, r.phase, r.asked, r.answer], ['k586', 'T586', 'live', '请给出成功判据的原文和位置。', '题面规定了 X']);
  const done = C.receiptOf(rows[2], collab({ asks: [collab().asks[0]] }), 'k505', snap, B);
  assert.equal(done.phase, 'done');
  assert.equal(C.collabHref(collab(), snap, B), '/topics/k586?collab=c1');
  assert.equal(C.collabHref(collab({ integrator: B }), snap, B), '/butler?collab=c1');
  // 还没有回执行、协作说它在问这个话题：按时刻补一行“正在协助”
  const early = C.topicRows(turns.slice(0, 2), [collab()], 'k505');
  assert.deepEqual(early.map((x) => x.key), ['k505:1', 'k505:2', 'receipt-c1']);
});

test('大厅：协作往返跟在发起它的那句后面，那句写谁汇总、谁协助', () => {
  const outbox = [{ seq: 1, op_id: 'op1', kind: 'say', topic_key: 'k586', project_key: null, payload: { text: '两位一起核对', room: true, to: ['k586', 'k505'] }, state: 'done', message: '', created_at: new Date(990_000).toISOString() }];
  const rows = R.buildRoom({ turns: [turn(B, 1, 'owner', 950, { topic_key: B }), turn(B, 2, 'agent', 960, { topic_key: B })], outbox, snap, butler: B });
  const sent = rows.find((x) => x.key === 'ob-op1');
  assert.equal(sent.route, '→ T586 汇总 · 协助 T505');
  assert.deepEqual(sent.routeView, { to: [], integrator: 'k586', helpers: ['k505'] });
  assert.equal(rows.find((x) => x.key === `${B}:1`).orig_seq, 1);
  const own = (list) => list.filter((x) => x.synth !== 'project').map((x) => x.key);
  const withCollab = C.roomCollabs(rows, [collab()], snap, B);
  assert.deepEqual(own(withCollab), [`${B}:1`, `${B}:2`, 'ob-op1', 'collab-c1']);
  assert.deepEqual(withCollab.map((x) => x.seq), withCollab.map((_, i) => i + 1));
  assert.deepEqual(withCollab.find((x) => x.key === 'collab-c1').targets, ['k586', 'k505']);
  assert.deepEqual(withCollab.find((x) => x.key === 'ob-op1').routeView, { to: [], integrator: 'k586', helpers: ['k505'] });
  // 对不上发件行的：按协作开始的时刻放
  const loose = C.roomCollabs(rows, [collab({ key: 'c2', root: { message_id: 'om_x' }, created_at: 955 })], snap, B);
  assert.deepEqual(own(loose), [`${B}:1`, 'collab-c2', `${B}:2`, 'ob-op1']);
});

test('合并协作：同一条用新的，最近动过的在前', () => {
  const merged = C.mergeCollabs([collab({ updated_at: 5 }), collab({ key: 'c0', updated_at: 9 })], [collab({ updated_at: 20, state: 'done' })]);
  assert.deepEqual(merged.map((c) => [c.key, c.state]), [['c1', 'done'], ['c0', 'open']]);
});

test('咨询的原因、状态词、迟到的答复照 Covey collab_records.view 透传', () => {
  const c = K.collabOf('c9', {
    integrator: 'k586', helpers: ['k505'], state: 'open', created_at: 1, updated_at: 2,
    asks: [{ id: 'a1', from: 'k586', to: 'k505', number: 1, state: 'not_taken', words: '未接手', reason: 'T505 在等你回答问题，没有接手', text: 'q', reply: null, late: { text: '迟到的答复', at: 9 } }],
  });
  assert.deepEqual([c.asks[0].reason, c.asks[0].words, c.asks[0].late], ['T505 在等你回答问题，没有接手', '未接手', { text: '迟到的答复', at: 9 }]);
  assert.equal(K.collabOf('c9', { integrator: 'k586', asks: [{ to: 'k505' }] }).asks[0].reason, '');
  const lines = C.askLines(c, snap, B);
  assert.deepEqual([lines[0].word, lines[0].live], ['未接手', false]);
  const r = C.receiptOf({ key: 'receipt-c9', ref: 'c9', seq: 3, rows: [] }, c, 'k505', snap, B);
  assert.deepEqual([r.phase, r.reason], ['off', 'T505 在等你回答问题，没有接手']);
});

test('头像条：每次咨询带谁问谁的 key（问的人空着是汇总方）；发送钮 title 写完整去向；底栏胶囊的种类', () => {
  const lines = C.askLines(collab(), snap, B);
  assert.ok(lines.length > 0);
  for (const l of lines) assert.ok(l.fromKey && l.toKey);
  assert.equal(lines[0].fromKey, 'k586');
  const many = C.plan(base({ picks: ['k586', 'k505', 'k7'] }));
  assert.deepEqual([many.chip, many.title], ['collab', '由 T586 汇总，请 T505、T7 协助']);
  assert.deepEqual([C.plan(base()).chip, C.plan(base({ picks: ['k505'] })).chip, C.plan(base({ picks: [L1, L2] })).chip], ['', '', 'router']);
});
