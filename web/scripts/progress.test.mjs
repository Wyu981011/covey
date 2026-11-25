// 专项的「进度」标签（v40，client/src/cv/progressData.ts）：目标检查表分栏（做完 / 正在做 / 将要做 / 等你）、尾巴、解锁反查、依赖图（成环不死循环）、
// “等你”按缺口文字推断、近 10 条决定和里程碑，服务端怎么过滤 Covey 推来的三样。跑：npm run test:progress
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as G from '../client/src/cv/progressData.ts';
import * as S from '../server/modules/workbench/workbench.v4.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const it = (id, extra = {}) => ({ id, criterion: `标准 ${id}`, topic: '', needs: [], evidence: '', gap: '', state: 'open', at: 100, ...extra });
const topic = (key, tone, extra = {}) => ({ key, number: Number(key.slice(1)), title: key, kind: 'topic', project_key: 'p1', state: '', unseen: false, updated_at: 1, tone, ...extra });
const topics = (...list) => new Map(list.map((t) => [t.key, t]));
const ids = (list) => list.map((x) => x.item.id);

test('六种分栏：满足的做完、缺口要主人的等你、在等别的、卡住、交付话题在跑或已结束、可开始', () => {
  const b = G.board(
    [
      it('c1', { state: 'done', at: 300 }),
      it('c2', { state: 'dropped', gap: '主人说不做了', at: 200 }),
      it('c3', { gap: '只差主人点头', topic: 't7' }),
      it('c4', { needs: ['c5'], topic: 't7' }),
      it('c5', { state: 'blocked', gap: '等外部接口', topic: 't8' }),
      it('c6', { topic: 't8' }),
      it('c7', { topic: 't9' }),
      it('c8', { topic: 'gone' }),
      it('c9', { needs: ['c1'] }),
    ],
    topics(topic('t7', 'running', { running: { step_label: '在跑测试', step_kind: 'command', plan_doing: '跑全量', plan_done: 2, plan_total: 5, started_at: 1 } }), topic('t8', 'running'), topic('t9', 'done')),
  );
  const at = Object.fromEntries(b.placed.map((x) => [x.item.id, [x.col, x.why]]));
  assert.deepEqual(at, {
    c1: ['done', 'met'],
    c2: ['done', 'dropped'],
    c3: ['owner', 'owner'],
    c4: ['next', 'needs'],
    c5: ['next', 'blocked'],
    c6: ['doing', 'live'],
    c7: ['doing', 'ended'],
    c8: ['doing', 'lost'],
    c9: ['next', 'ready'],
  });
  assert.deepEqual(b.counts, { done: 2, doing: 3, next: 3, owner: 1 });
  assert.deepEqual(b.byId.get('c4').waiting, ['c5']);
  assert.deepEqual(['c3', 'c4', 'c5', 'c9'].map((id) => G.stateWord(b.byId.get(id))), ['等你', '在等', '卡住', '可开始']);
  assert.equal(G.stateWord(b.byId.get('c2')), '不做了');
  // 在跑的交付话题：此刻那一步和第几步
  assert.deepEqual(G.topicNow(b.byId.get('c3').topic), { live: true, word: '在做', phase: '跑全量', done: 2, total: 5 });
  assert.equal(G.topicNow(b.byId.get('c7').topic).live, false);
  // 话题结束了、条目还没满足：待负责人核对；停住了、已停止的照实说
  assert.equal(G.endedWords(b.byId.get('c7').topic), '话题已结束 · 待负责人核对');
  assert.equal(G.endedWords(topic('t5', 'stopped')), '话题停住了 · 待负责人核对');
  assert.equal(G.endedWords(topic('t6', 'cancelled')), '话题已停止 · 待负责人核对');
  // 已完成按 at 倒序（at 是条目最后改动）
  assert.deepEqual(ids(b.done), ['c1', 'c2']);
});

test('尾巴：做完了、缺口还没清的；不做了的不算', () => {
  const b = G.board([it('c1', { state: 'done', gap: '主人顺手验收' }), it('c2', { state: 'done' }), it('c3', { state: 'dropped', gap: '不做了' })], new Map());
  assert.deepEqual(ids(b.tails), ['c1']);
});

test('解锁反查：做完的写放出了谁，正在做的写做完后解锁谁，解锁预告说可开始还是还在等', () => {
  const b = G.board(
    [it('c1', { state: 'done' }), it('c2', { needs: ['c1'], topic: 't1' }), it('c3', { needs: ['c2'] }), it('c4', { needs: ['c2', 'c5'] }), it('c5'), it('c6', { state: 'done', needs: ['c2'] })],
    topics(topic('t1', 'running')),
  );
  assert.deepEqual(b.byId.get('c1').unlocks, ['c2']);
  assert.deepEqual(b.byId.get('c2').unlocks, ['c3', 'c4', 'c6']);
  assert.deepEqual(b.previews, [{ from: 'c2', to: [{ id: 'c3', after: 'ready', rest: [] }, { id: 'c4', after: 'waits', rest: ['c5'] }, { id: 'c6', after: 'met', rest: [] }] }]);
});

test('依赖图：只画有依赖的，一串一行、横向按深度，同一深度往下排；成环不死循环', () => {
  const g = G.depGraph([it('c1', { state: 'done' }), it('c2', { needs: ['c1'] }), it('c3', { needs: ['c1'] }), it('c4', { needs: ['c3'] }), it('c5'), it('c6', { needs: ['c7'] }), it('c7')]);
  assert.deepEqual(g.nodes, [
    { id: 'c1', x: 0, y: 0 },
    { id: 'c2', x: 1, y: 0 },
    { id: 'c3', x: 1, y: 1 },
    { id: 'c4', x: 2, y: 0 },
    { id: 'c6', x: 1, y: 2 },
    { id: 'c7', x: 0, y: 2 },
  ]);
  assert.deepEqual([g.cols, g.rows, g.lone], [3, 3, 1]);
  assert.deepEqual(g.edges.filter((e) => e.live).map((e) => `${e.from}>${e.to}`), ['c1>c2', 'c1>c3']);
  // 成环：c1 → c2 → c3 → c1，自己等自己也不算边
  const loop = G.depGraph([it('c1', { needs: ['c3', 'c1'] }), it('c2', { needs: ['c1'] }), it('c3', { needs: ['c2'] })]);
  assert.equal(loop.nodes.length, 3);
  assert.equal(loop.edges.length, 3);
  assert.ok(loop.nodes.every((n) => Number.isInteger(n.x) && n.x >= 0 && n.x <= loop.nodes.length));
  assert.equal(new Set(loop.nodes.map((n) => `${n.x},${n.y}`)).size, 3);
  const b = G.board([it('c1', { needs: ['c2'] }), it('c2', { needs: ['c1'] })], new Map());
  assert.deepEqual(b.placed.map((x) => x.col), ['next', 'next']);
  assert.deepEqual(G.depGraph([]), { nodes: [], edges: [], cols: 0, rows: 0, lone: 0 });
});

test('等你按缺口文字推断：本专项 c14、c16 的缺口原文命中，c4、c9、c18、c20 不命中', () => {
  const hit = {
    c14: '只差主人操作：设置卡「配置 › 新话题」固定为 Claude GreenCloud Opus 5.5 xhigh（T67 13:35 核对仍全空）。研报专项的 T77、T81 换豆包工作配置要主人在话题卡点“换配置”，不归本专项；本专项 T74、T76、T78 已做完不用换，T82 的活已由 T85 接手也不用换',
    c16: 'T70 #871 已做完机器人侧：权限 im:chat.tabs:read / write_only 生效，list_tabs 回读标签 is_built_in=true、url 指向网页应用，说明在 chat-tabs.md。只差主人在飞书客户端实测内嵌打开；仍跳浏览器就回 T70 查 H5 安全域名',
  };
  const miss = {
    c4: '主人 11-25 13:43 定排进 T85 部署后的下一批；c20 部署完再开话题做（不默认给 Codex）',
    c9: '主人 14:13 在 T86 确认按 E 做（不改用同事网关），443 先不开。T86 #929 在离线开发 E（第 1/5 步：摸清隧道服务和监控），之后写分流器和单测、临时端口 13499 实测、监控兼容多连接。切换要等空闲，不和 T85 部署同时做，由负责人叫 T86 回来切；监控上线和切换都先问主人',
    c18: 'T87 只调研、出方案和样稿，不改源码、不部署；14:1x 已补主人的量化追踪文档作参考、要求三栏结构。主人定形态后再派实施（上线要部署时先问主人）',
    c20: 'T85 13:17 前置核对都过了：预检 ok=true，两边远端一致，T76 SHA 一致。还在等空闲：T86 #929 在开发 E，T87 在调研；T50、T80 不在本专项。T86、T87 都结束后由负责人叫 T85 回来查是否空闲；T85 部署和 T86 的 E 切换分开做。部署后两条额度线路的 Codex 验收，等 11-26 00:00 额度重置后补测',
  };
  for (const [id, gap] of Object.entries(hit)) assert.ok(G.OWNER_GAP.test(gap), id);
  for (const [id, gap] of Object.entries(miss)) assert.ok(!G.OWNER_GAP.test(gap), id);
  const b = G.board([it('c14', { state: 'blocked', gap: hit.c14, topic: 't67' }), it('c20', { gap: miss.c20, topic: 't85' })], topics(topic('t67', 'done'), topic('t85', 'done')));
  assert.deepEqual([b.byId.get('c14').col, b.byId.get('c20').col], ['owner', 'doing']);
});

test('没有 checklist 字段时不报错：空表，视图写“还没有目标检查表”', () => {
  const b = G.board(undefined, new Map());
  assert.deepEqual([b.placed, b.tails, b.previews, b.changedAt], [[], [], [], 0]);
  assert.deepEqual(G.depGraph(undefined).nodes, []);
  assert.deepEqual(G.ownerDecisions(undefined, []), []);
  assert.deepEqual(G.milestoneDays(undefined), []);
  assert.match(readFileSync(join(CV, 'ProjectProgress.tsx'), 'utf8'), /这个专项还没有目标检查表/u);
});

test('等你带里的话题：本专项等你的话题、有题没答的话题和负责人；别的专项的不算', () => {
  const snap = {
    topics: [
      topic('t1', 'waiting', { updated_at: 5 }),
      topic('t2', 'running', { updated_at: 3 }),
      topic('t3', 'waiting', { project_key: 'p2' }),
      { ...topic('l1', 'idle', { updated_at: 4 }), kind: 'lead' },
    ],
    questions: [{ token: 'q1', topic_key: 't2' }, { token: 'q2', topic_key: 't2' }, { token: 'q3', topic_key: 'l1' }],
  };
  assert.deepEqual(G.waitingTopics(snap, { key: 'p1', lead_topic_key: 'l1' }).map((w) => [w.topic.key, w.questions]), [['t2', 2], ['l1', 1], ['t1', 0]]);
});

test('近 10 条决定：专项记忆里主人答过的，新的在前，拆成问题和选择，话题号对到快照', () => {
  const mem = [
    ...Array.from({ length: 12 }, (_, i) => ({ id: `m${i}`, text: `主人答：第 ${i} 题？→选 ${i}（推荐）`, kind: 'decision', source: 'owner_answer', at: 1000 + i, origin: { topic: 't7' } })),
    { id: 'x1', text: '主人答：负责人记的', kind: 'decision', source: 'lead', at: 5000 },
    { id: 'x2', text: '对账一致才算完', kind: 'constraint', source: 'owner_answer', at: 5000 },
    { id: 'x3', text: '主人定：用新库', kind: 'decision', source: 'owner_answer', at: '1970-01-01T00:20:00Z', origin: { topic_number: 9 } },
  ];
  const d = G.ownerDecisions(mem, [topic('t7', 'done')]);
  assert.equal(d.length, 10);
  assert.deepEqual([d[0].id, d[1].id, d[9].id], ['x3', 'm11', 'm3']);
  assert.deepEqual([d[1].question, d[1].answer, d[1].number], ['第 11 题？', '选 11', 7]);
  assert.deepEqual([d[0].question, d[0].answer, d[0].number, d[0].at], ['用新库', '', 9, 1200]);
});

test('最近里程碑按天归组，新的在前', () => {
  const day = 86400;
  const base = Date.parse('2026-11-25T12:00:00+08:00') / 1000;
  const days = G.milestoneDays([
    { id: 'a', at: base - day, kind: 'milestone', text: '昨天' },
    { id: 'b', at: base, kind: 'milestone', text: '今天上午' },
    { id: 'c', at: base + 3600, kind: 'finish', text: '今天下午' },
  ]);
  assert.deepEqual(days.map((g) => [g.day, g.rows.map((r) => r.id)]), [['11-25', ['c', 'b']], ['11-24', ['a']]]);
});

test('带着这条和负责人讨论：引用是“关于 c20「标准前 40 字」· 状态 · 缺口前 60 字”，原来的草稿接在后面', () => {
  const b = G.board([it('c20', { criterion: '一'.repeat(45), gap: '二'.repeat(70), topic: 't1' })], topics(topic('t1', 'running')));
  const q = G.quoteOf(b.byId.get('c20'));
  assert.equal(q, `关于 c20「${'一'.repeat(40)}…」· 在做 · ${'二'.repeat(60)}…`);
  assert.equal(G.withQuote(q, '先等一下'), `${q}\n先等一下`);
  assert.equal(G.withQuote(q, '  '), `${q}\n`);
  assert.equal(G.quoteOf({ item: it('c1', { state: 'done' }), col: 'done', why: 'met' }), '关于 c1「标准 c1」· 满足');
  assert.deepEqual(Object.values(G.COL_WORD), ['做完', '正在做', '将要做', '等你']);
  // 按钮调 setDraft(负责人的 key, 引用 + 原草稿) 再回到专项的对话视图；发送走现有的 say
  const src = readFileSync(join(CV, 'ProjectProgress.tsx'), 'utf8');
  assert.match(src, /setDraft\(lead\.key, withQuote\(quoteOf\(/u);
  assert.match(src, /带着这条和负责人讨论/u);
});

test('服务端只收数组，按类型过滤：state 只认 open、done、blocked、dropped，坏的那条不要，一条不剩就当没推', () => {
  assert.equal(S.checklistOf(undefined), undefined);
  assert.equal(S.checklistOf({ items: [] }), undefined);
  assert.equal(S.checklistOf([{ id: 'c1', criterion: '', state: 'open' }]), undefined);
  const got = S.checklistOf([
    { id: 'c1', criterion: ' 新库能写 ', topic: 'tk', needs: ['c2', 'bad', 3], evidence: 'a1b2c3d', gap: '', state: 'done', at: 12.5, job: 'k' },
    { id: 'c2', criterion: '对账', state: 'waiting' },
    { id: 'x3', criterion: '不是条目', state: 'open' },
    { id: 'c1', criterion: '重复的', state: 'open' },
    { id: 'c4', criterion: '对账一致', state: 'blocked', at: 'soon' },
    'c5',
  ]);
  assert.deepEqual(got, [
    { id: 'c1', criterion: '新库能写', topic: 'tk', needs: ['c2'], evidence: 'a1b2c3d', gap: '', state: 'done', at: 12.5 },
    { id: 'c4', criterion: '对账一致', topic: '', needs: [], evidence: '', gap: '', state: 'blocked', at: 0 },
  ]);
  assert.equal(S.projectNotesOf('x'), undefined);
  assert.deepEqual(S.projectNotesOf([{ id: 'n1', at: 5, kind: 'milestone', text: '上线' }, { id: 'n2', text: '' }, { text: '只有正文' }]), [
    { id: 'n1', at: 5, kind: 'milestone', text: '上线' },
    { id: '', at: 0, kind: 'note', text: '只有正文' },
  ]);
  assert.equal(S.projectNotesOf(Array.from({ length: 14 }, (_, i) => ({ id: `n${i}`, text: `第 ${i} 条` }))).length, 10);
});

test('专项页：「进度」放在全图和报告之间，路由 /progress，手机上同样一个标签', () => {
  const page = readFileSync(join(CV, 'ProjectPage.tsx'), 'utf8');
  assert.match(page, /\['graph', '\/graph', '全图'\], \['progress', '\/progress', '进度'\], \['report', '\/report', '报告'\]/u);
  assert.match(page, /rest\.startsWith\('\/progress'\)/u);
});
