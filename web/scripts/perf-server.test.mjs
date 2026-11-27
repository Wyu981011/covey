// T876：服务端的上限、内存水位、库查询闸门、回执合批、文件存储的退回（纯逻辑，假库假时钟）。npm run test:perf
import test from 'node:test';
import assert from 'node:assert/strict';
import { bodyBytes, bodyLimit, imageBytes, partBytes, parseBytes, memLimitMb, LEGACY_IMAGE_BYTES, LEGACY_PART_BYTES } from '../server/modules/workbench/workbench.limits.ts';
import { Batcher, Gate, GateBusy, MemoryGuard, gated, inLane, laneOfPath, currentLane } from '../server/modules/workbench/workbench.guard.ts';
import { MAX_HELD, heldNow, setPressureForTest, wake, waitFor } from '../server/modules/workbench/workbench.wake.ts';
import { BlobPlace, FAIL_OFF, PlatformBlobs, SIGN_REUSE_SECONDS, imagePath, missingColumn, partPath } from '../server/modules/workbench/workbench.blobs.ts';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MIB = 1024 * 1024;

test('请求体上限：没设是 8mb，认得出的 BODY_SIZE_LIMIT 照用，认不出退回默认', () => {
  assert.equal(bodyLimit({}), '8mb');
  assert.equal(bodyBytes({}), 8 * MIB);
  assert.equal(bodyLimit({ BODY_SIZE_LIMIT: '10mb' }), '10mb');
  assert.equal(bodyBytes({ BODY_SIZE_LIMIT: '512KB' }), 512 * 1024);
  assert.equal(bodyLimit({ BODY_SIZE_LIMIT: 'lots' }), '8mb');
  assert.equal(parseBytes('1048576'), MIB);
  assert.equal(parseBytes('0'), null);
});

test('一张图、附件一段：1 MiB 的旧上限下和以前一样，8mb 时放大到 4 MiB，base64 后整个请求仍在上限里', () => {
  assert.equal(imageBytes(MIB), LEGACY_IMAGE_BYTES);
  assert.equal(partBytes(MIB), LEGACY_PART_BYTES);
  for (const body of [2 * MIB, 8 * MIB, 64 * MIB]) {
    const img = imageBytes(body);
    const part = partBytes(body);
    assert.ok(img <= 4 * MIB && part <= 4 * MIB, '封顶 4 MiB');
    assert.ok(Math.ceil(img / 3) * 4 + 1024 < body, '图片的 base64 放得进请求体');
    assert.ok(Math.ceil(part / 3) * 4 + 1024 < body, '一段的 base64 放得进请求体');
    assert.equal(part % (64 * 1024), 0);
  }
  assert.equal(partBytes(8 * MIB), 4 * MIB);
  // 12 MB 是 FaaS 的硬顶：即便 BODY_SIZE_LIMIT 设得更大，一段 base64 后也远小于它
  assert.ok((Math.ceil(partBytes(64 * MIB) / 3) * 4) < 12 * 1000 * 1000);
});

test('容器内存上限：读 cgroup，max 或读不到是 0（只读一次）', () => {
  const v = memLimitMb((p) => (p.endsWith('memory.max') ? '1073741824\n' : ''));
  assert.ok(v === 1024 || v >= 0);
});

test('内存水位：按常驻/上限分 ok、high、critical，最多每秒读一次，变了才回调', () => {
  let rss = 300;
  let now = 0;
  const seen = [];
  const g = new MemoryGuard({ rss: () => rss, limit: () => 1000, now: () => now }, (l) => seen.push(l));
  assert.equal(g.pressure(), 'ok');
  rss = 750;
  assert.equal(g.pressure(), 'ok', '一秒内用上次的读数');
  now += 1000;
  assert.equal(g.pressure(), 'high');
  rss = 900;
  now += 1000;
  assert.equal(g.pressure(), 'critical');
  rss = 100;
  now += 1000;
  assert.equal(g.pressure(), 'ok');
  assert.deepEqual(seen, ['high', 'critical', 'ok']);
  const none = new MemoryGuard({ rss: () => 999, limit: () => 0, now: () => 0 });
  assert.equal(none.pressure(), 'ok', '读不到上限不拦');
});

test('车道：/openapi/ 是 Covey，其余是页面；中间件设的车道在异步里一直带着', async () => {
  assert.equal(laneOfPath('/app/app_x/openapi/sync/upsert'), 'sync');
  assert.equal(laneOfPath('/openapi/sync/inbox'), 'sync');
  assert.equal(laneOfPath('/app/app_x/api/snapshot'), 'page');
  assert.equal(currentLane(), 'page');
  await inLane('sync', async () => {
    await sleep(1);
    assert.equal(currentLane(), 'sync');
  });
});

/** 假库：记同时在跑几条、各车道最多几条 */
function fakeDb(ms = 5) {
  const st = { now: 0, max: 0, byLane: { page: 0, sync: 0 }, maxLane: { page: 0, sync: 0 }, calls: 0 };
  return {
    st,
    execute(q) {
      const lane = q?.lane ?? currentLane();
      st.calls += 1;
      st.now += 1;
      st.byLane[lane] += 1;
      st.max = Math.max(st.max, st.now);
      st.maxLane[lane] = Math.max(st.maxLane[lane], st.byLane[lane]);
      return sleep(typeof q?.ms === 'number' ? q.ms : ms).then(() => {
        st.now -= 1;
        st.byLane[lane] -= 1;
        return q?.rows ?? [];
      });
    },
  };
}

test('闸门：各车道不超上限，两条车道加起来不超连接池；排满、等太久回 GateBusy', async () => {
  const db = fakeDb(5);
  const g = new Gate({ caps: { page: 4, sync: 2 }, queueMax: 1000, waitMs: 5000 });
  const gdb = gated(db, g);
  const page = Array.from({ length: 60 }, () => inLane('page', () => gdb.execute({})));
  const sync = Array.from({ length: 30 }, () => inLane('sync', () => gdb.execute({})));
  await Promise.all([...page, ...sync]);
  assert.equal(db.st.calls, 90);
  assert.ok(db.st.maxLane.page <= 4, `page 最多 ${db.st.maxLane.page}`);
  assert.ok(db.st.maxLane.sync <= 2, `sync 最多 ${db.st.maxLane.sync}`);
  assert.ok(db.st.max <= 6, `合计最多 ${db.st.max}`);
  assert.equal(g.total, 0);

  const small = new Gate({ caps: { page: 1, sync: 1 }, queueMax: 1, waitMs: 30 });
  const sdb = gated(fakeDb(80), small);
  const a = inLane('page', () => sdb.execute({}));
  const b = inLane('page', () => sdb.execute({}));
  await assert.rejects(inLane('page', () => sdb.execute({})), (e) => e instanceof GateBusy && e.why === 'queue');
  await assert.rejects(b, (e) => e instanceof GateBusy && e.why === 'wait');
  await a;
  // 拒收时可以换成别的错误（模块里换成 Nest 的 503）
  const mapped = gated(fakeDb(80), new Gate({ caps: { page: 1, sync: 1 }, queueMax: 0, waitMs: 10 }), () => 'page', (e) => new Error('503:' + e.why));
  const first = mapped.execute({});
  await assert.rejects(mapped.execute({}), /503:queue/);
  await first;
});

test('多标签压测：6 个标签每秒一份快照（各 7 条并行查询）+ 回执挂等 + Covey 一批 500 条，连接不超 6 条、Covey 的写不被饿死', async () => {
  const db = fakeDb(4);
  const g = new Gate({ caps: { page: 4, sync: 2 }, queueMax: 400, waitMs: 15000 });
  const gdb = gated(db, g);
  const snapshot = () => inLane('page', () => Promise.all(Array.from({ length: 7 }, () => gdb.execute({}))));
  const tabs = [];
  for (let round = 0; round < 3; round += 1) for (let t = 0; t < 6; t += 1) tabs.push(snapshot());
  let syncDone = 0;
  const t0 = Date.now();
  const covey = inLane('sync', async () => {
    for (let i = 0; i < 500; i += 4) {
      await Promise.all(Array.from({ length: 4 }, () => gdb.execute({}).then(() => { syncDone += 1; })));
    }
  });
  await Promise.all([...tabs, covey]);
  assert.equal(syncDone, 500);
  assert.ok(db.st.max <= 6, `同时最多 ${db.st.max} 条连接`);
  assert.ok(Date.now() - t0 < 10000);
  assert.equal(g.refused.page + g.refused.sync, 0);
});

test('回执合批：同一时刻的多次 get 合成一次查询，各拿各的；查询失败一起失败', async () => {
  let fetched = [];
  const b = new Batcher(async (keys) => {
    fetched.push(keys);
    return new Map(keys.filter((k) => k !== 'none').map((k) => [k, { op_id: k, state: 'done' }]));
  }, 5);
  const got = await Promise.all(['a', 'b', 'a', 'none'].map((k) => b.get(k)));
  assert.equal(fetched.length, 1);
  assert.deepEqual(fetched[0].sort(), ['a', 'b', 'none']);
  assert.equal(got[0].op_id, 'a');
  assert.equal(got[3], undefined);
  const bad = new Batcher(async () => { throw new Error('db down'); }, 1);
  await assert.rejects(bad.get('x'), /db down/);
});

test('长轮询：睡着时不占库连接；每条通道各自限挂起数；内存不是 ok 时不挂', async () => {
  const db = fakeDb(2);
  setPressureForTest(() => 'ok');
  let checks = 0;
  const p = waitFor('inbox', 300, 50, async () => { checks += 1; await db.execute({}); return null; }, () => 'timeout');
  await sleep(25);
  assert.equal(db.st.now, 0, 'nap 期间没有在跑的查询');
  assert.equal(heldNow('inbox'), 1);
  assert.equal(await p, 'timeout');
  assert.ok(checks >= 3 && checks <= 8, `查了 ${checks} 次`);
  assert.equal(heldNow('inbox'), 0);

  // 挂满 inbox 不影响 ack
  const holds = Array.from({ length: MAX_HELD.inbox }, () => waitFor('inbox', 200, 50, async () => null, () => 'held'));
  await sleep(5);
  const t0 = Date.now();
  assert.equal(await waitFor('inbox', 200, 50, async () => null, () => 'now'), 'now');
  assert.ok(Date.now() - t0 < 50, '满了马上返回');
  const ackHeld = waitFor('ack', 100, 50, async () => null, () => 'ack-held');
  await sleep(5);
  assert.equal(heldNow('ack'), 1);
  wake('ack');
  assert.equal(await ackHeld, 'ack-held');
  await Promise.all(holds);

  setPressureForTest(() => 'high');
  const t1 = Date.now();
  assert.equal(await waitFor('ack', 500, 50, async () => null, () => 'no-hold'), 'no-hold');
  assert.ok(Date.now() - t1 < 50);
  setPressureForTest(() => 'ok');
});

test('文件存储：签名地址进程里复用、过期或 403 重签；404 是没有；put 回平台给的路径', async () => {
  let now = 0;
  const signs = [];
  const fs = {
    async upload(buf, o) { return { filePath: '/' + o.filePath }; },
    async createSignedUrl(p, s) { signs.push([p, s]); return `https://tos/${p}?sig=${signs.length}`; },
    async remove() { return []; },
  };
  const hits = [];
  const fetchUrl = async (u) => {
    hits.push(u);
    if (u.includes('missing')) return { ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0) };
    if (u.endsWith('sig=1') && u.includes('stale')) return { ok: false, status: 403, arrayBuffer: async () => new ArrayBuffer(0) };
    return { ok: true, status: 200, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  };
  const b = new PlatformBlobs(fs, fetchUrl, () => now);
  assert.equal(await b.put('covey/images/x-thumb.webp', Buffer.from('a'), 'image/webp'), '/covey/images/x-thumb.webp');
  assert.deepEqual([...(await b.get('/a'))], [1, 2, 3]);
  await b.get('/a');
  assert.equal(signs.length, 1, '有效期内不再签');
  now += SIGN_REUSE_SECONDS * 1000 + 1;
  await b.get('/a');
  assert.equal(signs.length, 2, '过了复用期重签');
  assert.deepEqual([...(await b.get('/stale'))], [1, 2, 3], '403 重签一次');
  assert.equal(await b.get('/missing'), null);
});

test('退回 bytea：没有文件存储、库没有路径列、连着失败几次都走库；路径不含主人信息', () => {
  let now = 0;
  const logs = [];
  const none = new BlobPlace(null);
  assert.equal(none.usable(), false);
  assert.equal(none.mode, 'db');
  const p = new BlobPlace({ put: async () => '', get: async () => null, remove: async () => undefined }, (m) => logs.push(m), () => now);
  assert.equal(p.mode, 'file');
  for (let i = 0; i < FAIL_OFF; i += 1) p.failed('存图', new Error('boom'));
  assert.equal(p.usable(), false, '连着失败就歇一阵');
  assert.equal(logs.length, 1, '同样的错只记一次');
  now += 11 * 60 * 1000;
  assert.equal(p.usable(), true);
  p.ok();
  assert.equal(p.mode, 'file');
  p.noColumns();
  assert.equal(p.usable(), false);
  assert.equal(missingColumn({ code: '42703' }), true);
  assert.equal(missingColumn({ cause: { code: '42703' } }), true);
  assert.equal(missingColumn({ code: '42P01' }), false);
  assert.match(imagePath('ab'.repeat(16), 'thumb', 'image/webp'), /^covey\/images\/[0-9a-f]{32}-thumb\.webp$/u);
  assert.equal(partPath('c'.repeat(32), 3), `covey/uploads/${'c'.repeat(32)}/3.part`);
});
