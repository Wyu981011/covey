// 正文里的 @ 胶囊（T642）：记号 [@T586](covey-mention:<key>) 和纯文字 @T586 互转、从 Markdown 读出参与者（顺序、去重、删光即移出）、
// 插入先后定默认汇总方、发出去的 payload 和旧实现逐字段一样、mentionAt 放宽。跑：npm run test:mention
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../client/src/cv/mention.ts';
import * as C from '../client/src/cv/collab.ts';
import * as R from '../client/src/cv/room.ts';
import * as K from '../shared/collab.ts';

const B = 'butler0';
const L1 = 'lead1';
const L2 = 'lead2';
const t = (key, number, title, extra = {}) => ({ key, number, title, kind: 'topic', project_key: null, state: '做完', unseen: false, updated_at: number, ...extra });
const snap = {
  butler_key: B,
  synced_at: null,
  projects: [
    { key: 'p1', title: '夜航改版', goal: '', status: '在做', status_reason: '', lead_topic_key: L1, started_at: 100, topic_keys: ['k12'], memory: [], library: [], updated_at: 500, avatar: 'wolf', counts: { topics: 1, waiting: 0, running: 0 } },
    { key: 'p2', title: '习题专项', goal: '', status: '在做', status_reason: '', lead_topic_key: L2, started_at: 120, topic_keys: [], memory: [], library: [], updated_at: 400, counts: { topics: 0, waiting: 0, running: 0 } },
  ],
  topics: [
    { key: B, number: 0, title: '管家', kind: 'butler', project_key: null, state: '空闲', unseen: false, updated_at: 900 },
    { key: L1, number: 0, title: '负责人', kind: 'lead', project_key: 'p1', state: '空闲', unseen: false, updated_at: 800 },
    t('k12', 12, '密度', { project_key: 'p1', updated_at: 300 }),
    t('k586', 586, 'Golden 作答', { state: '在做', updated_at: 700 }),
    t('k505', 505, '题面优化', { updated_at: 650 }),
    t('k601', 601, '评测脚本', { updated_at: 640 }),
    t('k7', 7, '别的', { updated_at: 50 }),
  ],
  questions: [],
};
const base = (extra = {}) => ({ where: 'room', here: null, picks: [], integrator: null, quote: null, snap, butler: B, collabs: [], ...extra });
const tok = (key, label) => M.mentionToken(key, label);

/** 旧实现（f48de7c）的发出：点到的人由芯片行管，正文里没有“@谁”；字段构成同 sayPayload */
const oldPayload = (text, picks, integrator, quote, room) => ({
  text,
  ...(room ? { room: true } : {}),
  ...(picks.length ? { to: [...picks] } : {}),
  ...(integrator ? { integrator } : {}),
  ...(quote ? { quote } : {}),
});

test('记号：写出来、读回来，名字里的括号和转义不乱', () => {
  assert.equal(tok('k586', 'T586'), '[@T586](covey-mention:k586)');
  assert.equal(tok('lead 1', '习题专项 负责人'), '[@习题专项 负责人](covey-mention:lead%201)');
  const odd = tok('a(b)c', 'x]y[z\\');
  assert.deepEqual(M.mentionsIn(odd), [{ key: 'a(b)c', label: 'x]y[z\\' }]);
  assert.deepEqual(M.tokenAtStart(`${tok('k1', 'T1')} 后面`), { raw: '[@T1](covey-mention:k1)', key: 'k1', label: 'T1' });
  assert.equal(M.tokenAtStart('前面 [@T1](covey-mention:k1)'), null);
});

test('发出去：记号换成纯文字 @T586、@管家、@习题专项 负责人，别的字原样', () => {
  const md = `${tok('k586', 'T586')} 核对第 18 题，${tok(B, '管家')} 看进度，${tok(L2, '习题专项 负责人')} 汇总\n\n手打的 @T505 还是字`;
  assert.equal(M.plainMentions(md), '@T586 核对第 18 题，@管家 看进度，@习题专项 负责人 汇总\n\n手打的 @T505 还是字');
  assert.equal(M.plainMentions('没有胶囊 [链接](https://x.y)'), '没有胶囊 [链接](https://x.y)');
});

test('代码块和行内代码里的记号只当字，不算参与者、不转换', () => {
  const md = `\`\`\`\n${tok('k1', 'T1')}\n\`\`\`\n\n行内 \`${tok('k2', 'T2')}\` 和 ${tok('k586', 'T586')}`;
  assert.deepEqual(M.mentionKeys(md), ['k586']);
  assert.equal(M.plainMentions(md), `\`\`\`\n${tok('k1', 'T1')}\n\`\`\`\n\n行内 \`${tok('k2', 'T2')}\` 和 @T586`);
});

test('参与者：正文里所有胶囊去重；手打的 @T586 纯文字不算', () => {
  const md = `${tok('k586', 'T586')} 做 A，${tok('k505', 'T505')} 做 B，再请 ${tok('k586', 'T586')} 汇总。@T601 只是字`;
  assert.deepEqual(M.mentionKeys(md), ['k586', 'k505']);
  assert.deepEqual(M.mentionsIn(md).map((m) => m.key), ['k586', 'k505', 'k586']);
  assert.deepEqual(M.mentionKeys('没人 @T586'), []);
});

test('顺序：按第一次插入的先后，不按正文位置；刷新读回时按正文顺序', () => {
  // 先插了 k505，后来在句首补了 k586：名单仍是 k505、k586
  const first = `${tok('k505', 'T505')} 查 B`;
  const later = `${tok('k586', 'T586')} ${first}`;
  const p1 = M.participants([], first);
  assert.deepEqual(p1, ['k505']);
  assert.deepEqual(M.participants(p1, later), ['k505', 'k586']);
  // 刷新后没有上一次的名单：正文顺序
  assert.deepEqual(M.participants([], later), ['k586', 'k505']);
  // 同一位又插一枚：不变
  assert.deepEqual(M.participants(['k505', 'k586'], `${later} ${tok('k505', 'T505')}`), ['k505', 'k586']);
  // 删光就移出，别的留着、顺序不变
  assert.deepEqual(M.participants(['k505', 'k586', 'k601'], `${tok('k601', 'T601')} ${tok('k505', 'T505')}`), ['k505', 'k601']);
});

test('删掉一位的所有 @：别的字不丢，空格收一收', () => {
  const md = `${tok('k586', 'T586')} 核对 A，请 ${tok('k505', 'T505')} 查 B，${tok('k586', 'T586')} 汇总`;
  const out = M.dropMention(md, 'k586');
  assert.equal(out, `核对 A，请 ${tok('k505', 'T505')} 查 B，汇总`);
  assert.deepEqual(M.mentionKeys(out), ['k505']);
  assert.equal(M.dropMention('请@T5', 'k5'), '请@T5');
  assert.equal(M.dropMention(`请${tok('k5', 'T5')} 看`, 'k5'), '请看');
  assert.equal(M.dropMention(`see${tok('k5', 'T5')} it`, 'k5'), 'see it');
  assert.equal(M.dropMention(`${tok('k5', 'T5')} 开头`, 'k5'), '开头');
});

test('正文变了以后名单跟着算：加人不偷偷改汇总方，删光退回默认', () => {
  const at = (picks, integrator = null) => base({ picks, integrator });
  // 先点了管家和负责人，再插一个话题：汇总方留在管家
  const md1 = `${tok(B, '管家')} ${tok(L1, '夜航改版 负责人')}`;
  const s1 = C.syncPicks(at([]), md1);
  assert.deepEqual(s1, { picks: [B, L1], integrator: null });
  const s2 = C.syncPicks(at(s1.picks, s1.integrator), `${md1} ${tok('k505', 'T505')}`);
  assert.deepEqual(s2, { picks: [B, L1, 'k505'], integrator: B });
  // 选过的汇总方被删光：退回默认
  const chosen = C.syncPicks(at(['k586', 'k505'], 'k505'), tok('k586', 'T586'));
  assert.deepEqual(chosen, { picks: ['k586'], integrator: null });
  // 删光所有：名单空
  assert.deepEqual(C.syncPicks(at(['k586']), '没有胶囊了'), { picks: [], integrator: null });
  // 话题页里自己的胶囊不算
  assert.deepEqual(C.syncPicks(base({ where: 'topic', here: 'k586' }), `${tok('k586', 'T586')} ${tok('k505', 'T505')}`), { picks: ['k505'], integrator: null });
});

test('插入先后定默认汇总方：第一个点的普通话题汇总', () => {
  // 先点 k505 再点 k586，即使正文里 k586 在前
  const picks = M.participants(M.participants([], tok('k505', 'T505')), `${tok('k586', 'T586')} ${tok('k505', 'T505')}`);
  assert.deepEqual(picks, ['k505', 'k586']);
  const p = C.plan(base({ picks }));
  assert.deepEqual([p.route.to, p.owner, p.helpers], [K.COLLAB, 'k505', ['k586']]);
  assert.equal(p.title, '由 T505 汇总，请 T586 协助');
  // 刷新读回（正文顺序）：k586 汇总
  assert.equal(C.plan(base({ picks: M.participants([], `${tok('k586', 'T586')} ${tok('k505', 'T505')}`) })).owner, 'k586');
});

test('底栏小胶囊和发送钮 title：多人协作、管家归口、协助方太多、回复协作、单人什么都不加', () => {
  const none = C.plan(base());
  assert.deepEqual([none.chip, none.title], ['', '']);
  const one = C.plan(base({ picks: ['k505'] }));
  assert.deepEqual([one.chip, one.title], ['', '交给 T505']);
  const many = C.plan(base({ picks: ['k586', 'k505', 'k601'] }));
  assert.deepEqual([many.chip, many.title], ['collab', '由 T586 汇总，请 T505、T601 协助']);
  const router = C.plan(base({ picks: [L1, L2] }));
  assert.equal(router.chip, 'router');
  assert.match(router.title, /^由管家归口/u);
  const bad = C.plan(base({ picks: ['k586', 'k505', 'k601', 'k12', 'k7'] }));
  assert.equal(bad.chip, 'bad');
  assert.match(bad.title, /一次最多请 3 位协助，这次点了 4 位/u);
  const reply = C.plan(base({ picks: [], quote: { key: 'q', topic_key: 'k505', who: 'x', text: '', collab: 'c1' }, collabs: [{ key: 'c1', integrator: 'k586', helpers: ['k505'], state: 'open', asks: [], root: {}, created_at: 1, updated_at: 1 }] }));
  assert.equal(reply.chip, 'reply');
  assert.match(reply.title, /^回复这次协作，由 T586 汇总/u);
  const here = C.plan(base({ where: 'topic', here: 'k586', picks: ['k505'] }));
  assert.deepEqual([here.chip, here.title], ['collab', '由 T586 汇总，请 T505 协助']);
});

test('payload：和旧实现逐字段一样（to 按插入先后、integrator 和默认不同才带、quote、room、files），正文里多了 @谁', () => {
  const quote = { key: 'q1', topic_key: 'k12', seq: 4, who: 'T12 密度', text: '第一段', collab: '' };
  const files = [{ name: 'a.png', mime: 'image/png', key: 'f1' }];
  const cases = [
    { picks: [], integrator: null, quote: null, where: 'room' },
    { picks: ['k505'], integrator: null, quote: null, where: 'room' },
    { picks: ['k586', 'k505', 'k601'], integrator: null, quote: null, where: 'room' },
    { picks: ['k586', 'k505', 'k601'], integrator: 'k601', quote, where: 'room' },
    { picks: [L1, L2], integrator: null, quote: null, where: 'room' },
    { picks: [B, L1], integrator: B, quote: null, where: 'room' },
    { picks: ['k505'], integrator: null, quote: null, where: 'topic', here: 'k586' },
    { picks: ['k505'], integrator: 'k505', quote: null, where: 'topic', here: 'k586' },
  ];
  for (const c of cases) {
    const input = base(c);
    const p = C.plan(input);
    const md = c.picks.map((k) => `${tok(k, C.nameOf(k, snap, B))} 做一件事`).join('，') || '一句话';
    const sent = M.plainMentions(md);
    const got = C.sayPayload(sent, files, input, p);
    const want = oldPayload(C.quoted(sent, quote && c.quote ? c.quote : null), c.picks, p.integrator, c.quote ? { topic_key: 'k12', seq: 4 } : null, c.where === 'room');
    const { text: gt, files: gf, ...gRest } = got;
    const { text: wt, ...wRest } = want;
    assert.deepEqual(gRest, wRest, JSON.stringify(c));
    assert.deepEqual(gf, files);
    assert.equal(gt, wt);
    assert.deepEqual(Object.keys(got).sort(), Object.keys({ ...want, files }).sort());
    for (const k of c.picks) assert.ok(gt.includes(`@${C.nameOf(k, snap, B)}`));
    assert.ok(!gt.includes('covey-mention'));
  }
});

test('mentionAt 放宽：中文后紧挨着也弹，字母数字后（邮箱）不弹，胶囊后面可以接着 @', () => {
  assert.deepEqual(R.mentionAt('请@T5', 4), { query: 'T5', start: 1 });
  assert.deepEqual(R.mentionAt('请@', 2), { query: '', start: 1 });
  assert.deepEqual(R.mentionAt('帮我 @夜', 5), { query: '夜', start: 3 });
  assert.deepEqual(R.mentionAt('@', 1), { query: '', start: 0 });
  assert.deepEqual(R.mentionAt('好，@管', 4), { query: '管', start: 2 });
  assert.equal(R.mentionAt('邮箱a@b', 5), null);
  assert.equal(R.mentionAt('x1@', 3), null);
  assert.equal(R.mentionAt('a_b@c', 5), null);
  assert.equal(R.mentionAt('@夜航 改', 6), null);
  // 编辑器里胶囊用占位字：胶囊后面直接打 @ 要弹，查询词里不带占位字
  assert.deepEqual(R.mentionAt(`${R.OBJ}@T`, 3), { query: 'T', start: 1 });
  assert.deepEqual(R.mentionAt(`${R.OBJ}${R.OBJ} @`, 4), { query: '', start: 3 });
  assert.equal(R.mentionAt(`@${R.OBJ}`, 2), null);
});

test('胶囊的样子：话题 T 号、管家、负责人（专项头像），认不得的 key 不当已知', () => {
  assert.deepEqual(C.mentionInfo('k586', snap, B), { key: 'k586', kind: 'topic', label: 'T586', number: 586, title: 'Golden 作答' });
  assert.deepEqual(C.mentionInfo(B, snap, B), { key: B, kind: 'butler', label: '管家' });
  assert.deepEqual(C.mentionInfo(L1, snap, B), { key: L1, kind: 'lead', label: '夜航改版 负责人', avatar: 'wolf' });
  assert.deepEqual(C.mentionInfo(L2, snap, B), { key: L2, kind: 'lead', label: '习题专项 负责人' });
  assert.ok(C.knownKey('k505', snap, B) && C.knownKey(L2, snap, B) && C.knownKey(B, snap, B));
  assert.ok(!C.knownKey('gone', snap, B) && !C.knownKey('', snap, B));
  const list = C.candidates(snap);
  assert.deepEqual(list.find((c) => c.key === L1).avatar, 'wolf');
  assert.equal(list.find((c) => c.key === 'k586').number, 586);
  // 同一位可以 @ 两次：候选里只排除话题页里的自己
  assert.ok(C.candidates(snap, ['k586']).every((c) => c.key !== 'k586'));
});

test('去向的结构化写法：协作写汇总、协助，直达和经管家转的写 to', () => {
  const outbox = [{ seq: 1, op_id: 'o1', kind: 'say', topic_key: 'k586', project_key: null, payload: { text: '两位', room: true, to: ['k586', 'k505', 'k601'] }, state: 'done', message: '', created_at: new Date(990_000).toISOString() },
    { seq: 2, op_id: 'o2', kind: 'say', topic_key: 'k12', project_key: null, payload: { text: '单个', room: true, to: ['k12'] }, state: 'done', message: '', created_at: new Date(991_000).toISOString() }];
  const rows = R.buildRoom({ turns: [], outbox, snap, butler: B });
  assert.deepEqual(rows.find((r) => r.key === 'ob-o1').routeView, { to: [], integrator: 'k586', helpers: ['k505', 'k601'] });
  assert.equal(rows.find((r) => r.key === 'ob-o1').route, '→ T586 汇总 · 协助 T505、T601');
  assert.deepEqual(rows.find((r) => r.key === 'ob-o2').routeView, { to: ['k12'] });
});
