// 快照按增量取（T765 D2，数据约定 v38）：什么时候带 since、增量怎么并进上一份、并不进去怎么办。
// 跑：npm run test:snapmerge
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as S from '../client/src/cv/snapshotMerge.ts';

const topic = (key, updated, extra = {}) => ({ key, title: key, updated_at: updated, state: '空闲', kind: 'topic', ...extra });
const snap = (topics, extra = {}) => ({ synced_at: 's', butler_key: null, projects: [], topics, questions: [], ...extra });

test('什么时候带 since：有游标、缓存里有上一份、没有待校准的理由、离上次整份不满 30 分钟（各种理由见 calib.test.mjs）', () => {
  const c = { ...S.calibStart(), lastFullAt: 1000 };
  assert.equal(S.planSnapshot(null, false, c, 1000).since, null);
  assert.equal(S.planSnapshot(undefined, true, c, 1000).since, null, '旧服务端：没有 cursor，永远整份');
  assert.equal(S.planSnapshot('2026-11-25T10:00:00.000Z', true, c, 1000 + 59_000).since, '2026-11-25T10:00:00.000Z');
  assert.equal(S.planSnapshot('2026-11-25T10:00:00.000Z', true, c, 1000 + 10 * 60_000).since, '2026-11-25T10:00:00.000Z', '不再每分钟整份');
  assert.equal(S.planSnapshot('2026-11-25T10:00:00.000Z', true, c, 1000 + S.FULL_BACKSTOP_MS).since, null);
});

test('整份（没有 partial，旧服务端或没带 since）直接替换', () => {
  const res = snap([topic('a', 3)], { cursor: 'c2' });
  assert.equal(S.mergeSnapshot(snap([topic('b', 1)], { cursor: 'c1' }), res), res);
  assert.equal(S.mergeSnapshot(undefined, res), res);
});

test('增量：变过的盖掉旧的，没变的留着，不在 keys 里的拿掉，顺序照 keys，游标换成新的', () => {
  const a = topic('a', 1, { title: '旧 a' });
  const b = topic('b', 2);
  const c = topic('c', 3);
  const prev = snap([c, b, a], { cursor: 'c1', synced_at: 'old' });
  const res = snap([topic('a', 9, { title: '新 a' }), topic('d', 8)], {
    partial: true, keys: ['a', 'd', 'c'], cursor: 'c2', synced_at: 'new', questions: [{ token: 'q' }], projects: [{ key: 'p' }], asks: { waiting: 1 },
  });
  const m = S.mergeSnapshot(prev, res);
  assert.deepEqual(m.topics.map((t) => t.key), ['a', 'd', 'c']);
  assert.equal(m.topics[0].title, '新 a');
  assert.equal(m.topics[2], c, '没变的话题沿用原来的对象');
  assert.equal(m.cursor, 'c2');
  assert.equal(m.synced_at, 'new');
  assert.deepEqual(m.questions, [{ token: 'q' }]);
  assert.deepEqual(m.projects, [{ key: 'p' }]);
  assert.deepEqual(m.asks, { waiting: 1 });
  assert.equal('partial' in m || 'keys' in m, false, '合出来的和整份一样');
});

test('增量里什么都没变：沿用上一份的话题数组（依赖它的组件不白重算）', () => {
  const t = [topic('a', 2), topic('b', 1)];
  const prev = snap(t, { cursor: 'c1' });
  const m = S.mergeSnapshot(prev, snap([], { partial: true, keys: ['a', 'b'], cursor: 'c2' }));
  assert.equal(m.topics, t);
  // 顺序变了（updated_at 变了的话题本身会在 res.topics 里）就换新数组
  const m2 = S.mergeSnapshot(prev, snap([topic('b', 5)], { partial: true, keys: ['b', 'a'], cursor: 'c2' }));
  assert.deepEqual(m2.topics.map((x) => x.key), ['b', 'a']);
});

test('并不进去就返回 null（调用方改取整份）：没有上一份、没带 keys、keys 里有话题上一份和响应里都没有', () => {
  const res = snap([topic('a', 1)], { partial: true, keys: ['a'], cursor: 'c' });
  assert.equal(S.mergeSnapshot(undefined, res), null);
  assert.equal(S.mergeSnapshot(snap([], { cursor: 'c0' }), { ...res, keys: undefined }), null);
  assert.equal(S.mergeSnapshot(snap([topic('z', 1)], { cursor: 'c0' }), { ...res, keys: ['a', 'missing'] }), null);
});

test('服务端：since、cursor、keys、partial 和 wait 都在，不带参数时和以前一样', () => {
  const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'server', 'modules', 'workbench');
  const q = readFileSync(join(dir, 'workbench.query.service.ts'), 'utf8');
  assert.match(q, /async snapshot\(sinceRaw: string \| null = null\)/u);
  assert.match(q, /partial: true as const, keys:/u);
  assert.match(q, /make_interval\(secs => \$\{CURSOR_OVERLAP_S\}\)/u);
  assert.match(q, /select topic_key from turns where _updated_at > /u);
  const inbox = readFileSync(join(dir, 'workbench.sync.service.ts'), 'utf8');
  assert.match(inbox, /return \{ items, waited: true \}/u);
  assert.match(inbox, /if \(waitMs === null\) return \{ items: await fetchRows\(\) \}/u);
  const ctl = readFileSync(join(dir, 'workbench.openapi.controller.ts'), 'utf8');
  assert.match(ctl, /INBOX_WAIT_MAX = 10/u);
  assert.match(readFileSync(join(dir, 'workbench.controller.ts'), 'utf8'), /OUTBOX_WAIT_MAX = 8/u);
});

test('游标不放进缓存的快照里（它每次都变，放进去会让用快照的页面每秒重画一遍）', () => {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'hooks', 'use-workbench.ts'), 'utf8');
  assert.match(src, /let snapCursor: string \| null = null;/u);
  assert.match(src, /const \{ cursor: _cursor, \.\.\.data \} = out;/u);
  assert.match(src, /planSnapshot\(snapCursor, !!qc\.getQueryData<SnapshotResponse>\(SNAPSHOT_KEY\), calib, Date\.now\(\)\)/u);
});
