// 快照什么时候取整份（T876 校准）、切回前台和网络恢复、回执前的乐观更新、附件按服务端的段大小切。纯函数和假时钟，不碰网络。
// 跑：npm run test:calib
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as S from '../client/src/cv/snapshotMerge.ts';
import * as K from '../client/src/cv/opTrack.ts';
import * as U from '../client/src/cv/uploadParts.ts';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src');
const read = (rel) => readFileSync(join(SRC, rel), 'utf8');
const MIN = 60_000;

/** 假的页面：照 use-workbench.ts 的 fetchSnapshotMerged 走一遍（plan → 取 → 失败记 reconnect / 整份记时刻） */
function page() {
  const p = { c: S.calibStart(), cursor: null, has: false, log: [] };
  p.fetch = (now, { fail = false, gap = false, oldServer = false } = {}) => {
    const plan = S.planSnapshot(p.cursor, p.has, p.c, now);
    p.c = plan.next;
    if (fail) {
      p.c = S.calibFailed(p.c);
      p.log.push('fail');
      return;
    }
    p.cursor = oldServer ? null : `c@${now}`;
    p.has = true;
    let full = plan.since === null;
    if (!full && gap) full = true; // 并不进去，再取一份整份
    if (full) p.c = S.calibGotFull(p.c, now);
    p.log.push(full ? `full:${plan.reason ?? 'gap'}` : 'inc');
  };
  return p;
}

test('第一次取整份；之后每秒都是增量，一小时里只有 30 分钟兜底的那一次整份（不再每分钟一份）', () => {
  const p = page();
  for (let t = 0; t <= 60 * MIN; t += 1000) p.fetch(t);
  const full = p.log.filter((x) => x.startsWith('full'));
  assert.deepEqual(full, ['full:first', 'full:backstop', 'full:backstop']);
  assert.equal(p.log.length, 3601);
  assert.equal(S.FULL_BACKSTOP_MS, 30 * MIN);
});

test('旧服务端（不给游标）：每次都是整份，和以前一样', () => {
  const p = page();
  for (let t = 0; t < 5000; t += 1000) p.fetch(t, { oldServer: true });
  assert.deepEqual(p.log, Array(5).fill('full:first'));
});

test('断线重连：取失败以后，第一次成功的那次是整份；连着失败几次也只补一次整份', () => {
  const p = page();
  p.fetch(0);
  p.fetch(1000);
  p.fetch(2000, { fail: true });
  p.fetch(3000, { fail: true });
  p.fetch(4000);
  p.fetch(5000);
  assert.deepEqual(p.log, ['full:first', 'inc', 'fail', 'fail', 'full:reconnect', 'inc']);
});

test('增量并不进去（断档）当场再取整份，兜底的 30 分钟从这次重算', () => {
  const p = page();
  p.fetch(0);
  p.fetch(10 * MIN, { gap: true });
  p.fetch(35 * MIN);
  p.fetch(40 * MIN);
  assert.deepEqual(p.log, ['full:first', 'full:gap', 'inc', 'full:backstop']);
});

test('网络恢复（online）：下一次取整份，之后照常增量', () => {
  const p = page();
  p.fetch(0);
  p.c = S.calibOnline(p.c);
  p.fetch(1000);
  p.fetch(2000);
  assert.deepEqual(p.log, ['full:first', 'full:online', 'inc']);
});

test('切到后台又回来：待满 30 秒的那次整份校准，不满 30 秒照常增量；连着几次 hidden 从第一次算', () => {
  const p = page();
  p.fetch(0);
  p.c = S.calibHidden(p.c, 1000);
  p.c = S.calibVisible(p.c, 1000 + 29_000);
  p.fetch(31_000);
  assert.deepEqual(p.log, ['full:first', 'inc']);
  p.c = S.calibHidden(p.c, 40_000);
  p.c = S.calibHidden(p.c, 60_000);
  p.c = S.calibVisible(p.c, 40_000 + S.AWAY_FULL_MS);
  assert.equal(p.c.hiddenAt, null);
  assert.equal(p.c.pending, 'back');
  p.fetch(71_000);
  p.fetch(72_000);
  assert.deepEqual(p.log.slice(2), ['full:back', 'inc']);
});

test('在后台时失败、回来又记了 back：只补一次整份，理由取先记下的', () => {
  const p = page();
  p.fetch(0);
  p.c = S.calibHidden(p.c, 1000);
  p.fetch(2000, { fail: true }); // 后台时网页操作回执后的取数失败（opTrack 的 pull 不看前后台）
  p.c = S.calibVisible(p.c, 100_000);
  p.fetch(100_500);
  p.fetch(101_500);
  assert.deepEqual(p.log, ['full:first', 'fail', 'full:reconnect', 'inc']);
});

test('planSnapshot 领走待校准理由；这次失败了靠 calibFailed 再记上，理由不丢', () => {
  const c = { ...S.calibStart(), lastFullAt: 0, pending: 'back' };
  const plan = S.planSnapshot('cur', true, c, 1000);
  assert.deepEqual([plan.since, plan.reason, plan.next.pending], [null, 'back', null]);
  assert.equal(S.calibFailed(plan.next).pending, 'reconnect');
  const inc = S.planSnapshot('cur', true, { ...c, pending: null, lastFullAt: 1000 }, 2000);
  assert.deepEqual([inc.since, inc.reason], ['cur', null]);
  assert.equal(S.planSnapshot('cur', false, S.calibStart(), 0).reason, 'first', '缓存里没有上一份');
});

test('use-workbench：校准状态是模块变量；前后台、网络恢复只挂一份监听，卸下时摘掉；切回前台取快照、开着的话题和大厅，不取消在途请求', () => {
  const src = read('hooks/use-workbench.ts');
  assert.match(src, /let calib: Calib = calibStart\(\);/u);
  assert.match(src, /const plan = planSnapshot\(snapCursor, /u);
  assert.match(src, /calib = calibFailed\(calib\)/u);
  assert.match(src, /document\.addEventListener\('visibilitychange', onVisibility\)/u);
  assert.match(src, /document\.removeEventListener\('visibilitychange', onVisibility\)/u);
  assert.match(src, /window\.addEventListener\('online', onOnline\)/u);
  assert.match(src, /window\.removeEventListener\('online', onOnline\)/u);
  assert.match(src, /if \(watchers === 1 && /u);
  assert.match(src, /useEffect\(\(\) => watchPage\(qc\), \[qc\]\)/u);
  assert.match(src, /refetchQueries\(\{ queryKey: \['turns'\], type: 'active' \}, no\)/u);
  assert.match(src, /refetchQueries\(\{ queryKey: ROOM_KEY, type: 'active' \}, no\)/u);
  assert.match(src, /const no = \{ cancelRefetch: false \} as const;/u);
  assert.doesNotMatch(src, /refetchIntervalInBackground: true/u, '后台不轮询');
  assert.doesNotMatch(read('cv/snapshotMerge.ts'), /FULL_EVERY_MS|sinceFor/u, '每分钟整份的老办法不回来');
});

/* ---------- 乐观更新 ---------- */
const topic = (key, extra = {}) => ({ key, title: key, updated_at: 1, state: '做完', kind: 'topic', unseen: false, ...extra });
const snap = (topics) => ({ synced_at: 's', butler_key: null, projects: [], topics, questions: [] });

test('乐观更新只做 seen 和 dismiss：seen 把 unseen 置 false、有结果没看换成 done；dismiss 把 board 置空串；别的操作不改', () => {
  const t = topic('a', { unseen: true, tone: 'result', board: 'result' });
  assert.deepEqual(K.optimisticTopic({ kind: 'seen' }, t), { ...t, unseen: false, tone: 'done' });
  assert.equal(K.optimisticTopic({ kind: 'seen' }, topic('b', { tone: 'done' })), null, '已经看过');
  assert.deepEqual(K.optimisticTopic({ kind: 'dismiss' }, t), { ...t, board: '' });
  assert.equal(K.optimisticTopic({ kind: 'dismiss' }, topic('c', { board: '' })), null, '已经不在看板上');
  assert.equal(K.optimisticTopic({ kind: 'dismiss' }, topic('d')), null, '没开看板（不推 board）');
  for (const kind of ['say', 'answer', 'stop', 'recover', 'launch', 'switch']) assert.equal(K.optimisticTopic({ kind }, t), null, kind);
});

test('放进快照只换这一个话题的对象，别的沿用；缓存里没有快照、没有这个话题、不用改都是 null', () => {
  const a = topic('a', { unseen: true, tone: 'result' });
  const b = topic('b');
  const s = snap([b, a]);
  const got = K.applyOptimistic(s, { kind: 'seen', topic_key: 'a' });
  assert.equal(got.snap.topics[0], b);
  assert.equal(got.snap.topics[1].unseen, false);
  assert.equal(got.mark.was, a);
  assert.equal(got.mark.placed, got.snap.topics[1]);
  assert.equal(s.topics[1], a, '原来的快照不动');
  assert.equal(K.applyOptimistic(undefined, { kind: 'seen', topic_key: 'a' }), null);
  assert.equal(K.applyOptimistic(s, { kind: 'seen', topic_key: 'zz' }), null);
  assert.equal(K.applyOptimistic(s, { kind: 'seen', topic_key: 'b' }), null);
  assert.equal(K.applyOptimistic(s, { kind: 'seen' }), null);
});

test('改回：缓存里还是放进去的那个对象才换回；增量期间推来了它的新状态、或取过整份，以推来的为准', () => {
  const a = topic('a', { board: 'stopped', tone: 'stopped' });
  const got = K.applyOptimistic(snap([a]), { kind: 'dismiss', topic_key: 'a' });
  // 增量并进来别的话题（mergeSnapshot 沿用没变的对象）：放进去的还在，改回
  const merged = S.mergeSnapshot(got.snap, { ...snap([topic('x')]), partial: true, keys: ['x', 'a'], cursor: 'c' });
  const back = K.undoOptimistic(merged, got.mark);
  assert.equal(back.topics.find((t) => t.key === 'a'), a);
  // Covey 推来了 a 的新状态：不改回
  const pushed = S.mergeSnapshot(got.snap, { ...snap([topic('a', { board: '' })]), partial: true, keys: ['a'], cursor: 'c' });
  assert.equal(K.undoOptimistic(pushed, got.mark), null);
  assert.equal(K.undoOptimistic(undefined, got.mark), null);
});

test('什么时候改回：没办成要；等满了没回音要；组件卸了才停问的不算；办成了不改回', () => {
  assert.equal(K.shouldUndo('failed', false), true);
  assert.equal(K.shouldUndo('timeout', false), true);
  assert.equal(K.shouldUndo('timeout', true), false);
  assert.equal(K.shouldUndo('done', false), false);
});

test('发件跟踪接上乐观更新：trackOp 先放、回执后按 shouldUndo 改回；seen 走 sendQuiet（看板、话题页都换了）', () => {
  const so = read('cv/sendOp.ts');
  assert.match(so, /const mark: Optimistic \| null = putOptimistic\(qc, body\);/u);
  assert.match(so, /if \(mark && shouldUndo\(r\.phase, !!o\.gone\?\.\(\)\)\) dropOptimistic\(qc, mark\);/u);
  assert.match(so, /export function sendQuiet\(qc: QueryClient, body: OutboxRequest\): void/u);
  for (const f of ['cv/Board.tsx', 'cv/Conversation.tsx']) {
    const src = read(f);
    assert.match(src, /sendQuiet\(qc, \{ op_id: newOpId\(\), kind: 'seen'/u, f);
    assert.doesNotMatch(src, /postOutboxQuiet\(\{ op_id: newOpId\(\), kind: 'seen'/u, f);
  }
  // seen 回执后不取数；dismiss 回执后只取这个话题和增量快照
  assert.deepEqual(K.pullPlan({ kind: 'seen', topic_key: 'a', payload: {} }), { all: [], follow: [] });
  assert.deepEqual(K.pullPlan({ kind: 'dismiss', topic_key: 'a', payload: {} }, true).follow.map(K.pullId), ['turns:a']);
});

/* ---------- 附件分段 ---------- */
test('附件分段：新服务端给 part_bytes 且段数对得上就照它切，最后一段可以短；旧服务端、对不上照 512 KiB', () => {
  const K512 = 512 * 1024;
  const size = 10 * 1024 * 1024 + 7;
  const MB4 = 4 * 1024 * 1024;
  assert.equal(U.partBytesOf({ parts: 3, part_bytes: MB4 }, size), MB4);
  assert.equal(U.partBytesOf({ parts: Math.ceil(size / K512) }, size), K512, '旧服务端不带 part_bytes');
  assert.equal(U.partBytesOf({ parts: 2, part_bytes: MB4 }, size), K512, '段数对不上');
  assert.equal(U.partBytesOf({ parts: 3, part_bytes: 0 }, size), K512);
  assert.equal(U.partBytesOf({ parts: 3, part_bytes: 1.5 }, size), K512);
  const ranges = [0, 1, 2].map((n) => U.partRange(n, MB4, size));
  assert.deepEqual(ranges, [[0, MB4], [MB4, 2 * MB4], [2 * MB4, size]]);
  assert.equal(ranges.reduce((s, [a, b]) => s + (b - a), 0), size, '拼起来正好是整个文件');
  const att = read('cv/attachments.ts');
  assert.match(att, /const each: number = partBytesOf\(started, f\.size\);/u);
  assert.doesNotMatch(att, /n \* UPLOAD_PART_BYTES/u);
});

// T876：首屏预取按集合、只补缺的和过期的（cv/warmup.ts）
import { needsWarm, warmList, warmSig, WARM_STALE_MS } from '../client/src/cv/warmup.ts';

test('预取：要紧的在前，最多 24 个；顺序变了集合签名不变；只补缺的和超过 5 分钟的', () => {
  const t = (key, state, at, extra = {}) => ({ key, state, updated_at: at, unseen: false, kind: 'topic', ...extra });
  const topics = [t('a', '空闲', 10), t('b', '在做', 5), t('c', '等你', 1), t('d', '空闲', 20, { unseen: true })];
  const list = warmList(topics);
  assert.deepEqual(list.slice(0, 3).sort(), ['b', 'c', 'd']);
  assert.equal(list[3], 'a');
  const swapped = warmList([t('a', '空闲', 10), t('b', '在做', 30), t('c', '等你', 1), t('d', '空闲', 20, { unseen: true })]);
  assert.notDeepEqual(swapped, list, '在做的话题推进了，顺序变了');
  assert.equal(warmSig(swapped), warmSig(list), '集合没变，effect 不重跑');
  const many = Array.from({ length: 40 }, (_, i) => t(`k${i}`, '在做', i));
  assert.equal(warmList(many).length, 24);
  assert.equal(needsWarm(undefined, 1000), true);
  assert.equal(needsWarm(0, 1000), true);
  assert.equal(needsWarm(1000, 1000 + WARM_STALE_MS - 1), false);
  assert.equal(needsWarm(1000, 1000 + WARM_STALE_MS + 1), true);
});

test('快照响应不完整（空串、截断的 JSON 被当成字符串、缺 topics）不当快照', () => {
  assert.equal(S.isSnapshot(''), false);
  assert.equal(S.isSnapshot('{"topics":[1,'), false);
  assert.equal(S.isSnapshot(null), false);
  assert.equal(S.isSnapshot({ projects: [], questions: [] }), false);
  assert.equal(S.isSnapshot({ topics: [], projects: [], questions: [], synced_at: null }), true);
});
