// 专项报告页（T533 方案 A）的数据：node --test scripts/report-view.test.mjs
// 轮次起止往回推、连着几轮合成一段、时间轴分组、预计 vs 实际的结论。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildReport } from '../client/src/cv/reportData.ts';
import { firstSentence, groupLanes, planSummary, segments, windows } from '../client/src/cv/reportView.ts';

const NOW = 1_800_000_000;
const H = 3600;
let seq = 0;
const turn = (key, number, f) => ({
  topic_key: key, number, title: `话题${number}`, kind: 'topic', harness: 'claude', seq: ++seq, role: 'agent', status: 'done',
  started_at: f.e, ended_at: f.e, seconds: 0, usage: null, artifacts: 0, artifact: null, estimate_seconds: null, head: null, ...f,
});
const topic = (key, number, state) => ({ key, number, title: `话题${number}`, state, joined_at: null });

test('历史里来的轮次开始和结束同一刻：按用时往回推，不缩成一个点', () => {
  const rep = { project_key: 'p', turns: [turn('a', 1, { e: NOW - H, seconds: 600 })], questions: [] };
  const m = buildReport(rep, [topic('a', 1, '做完')], undefined, NOW, NOW - 10 * H);
  const r = m.lanes.find((l) => l.key === 'a').rounds[0];
  assert.equal(r.e - r.s, 600);
});

test('隔不到 3 分钟的几轮合成一段，没做成的单独一段', () => {
  const r = (s, e, failed = false) => ({ s, e, failed, live: false, hold: false });
  const segs = segments([r(0, 100), r(150, 300), r(500, 600), r(610, 700, true)]);
  assert.deepEqual(segs.map((g) => [g.s, g.e, g.k, g.failed]), [[0, 300, 2, false], [500, 600, 1, false], [610, 700, 1, true]]);
});

test('时间轴分组：在做的总在，做完的按最近动静，窗口外的归更早，停掉没跑成的单列', () => {
  const rep = {
    project_key: 'p',
    turns: [
      turn('run', 1, { e: NOW, status: 'running', started_at: NOW - 600 }),
      turn('d1', 2, { e: NOW - 2 * H, seconds: 300 }),
      turn('d2', 3, { e: NOW - H, seconds: 300 }),
      turn('old', 4, { e: NOW - 30 * H, seconds: 300 }),
      turn('stop', 5, { e: NOW - 3 * H, status: 'failed' }),
    ],
    questions: [],
  };
  const topics = [topic('run', 1, '在做'), topic('d1', 2, '做完'), topic('d2', 3, '做完'), topic('old', 4, '做完'), topic('stop', 5, '已停止'), topic('none', 6, '已停止')];
  const m = buildReport(rep, topics, undefined, NOW, NOW - 40 * H);
  const w = windows(m.t0, NOW)[0];
  assert.equal(w.key, '24h');
  const g = groupLanes(m.lanes, w);
  assert.deepEqual(g.live.map((l) => l.label), ['T1']);
  assert.deepEqual(g.done.map((l) => l.label), ['T3', 'T2']);
  assert.deepEqual(g.older.map((l) => l.label), ['T4']);
  assert.deepEqual(g.idle.map((l) => l.label).sort(), ['T5', 'T6']);
  assert.ok(windows(m.t0, NOW).some((o) => o.key === 'all'), '跨了一天以上才有“全部”');
});

test('预计 vs 实际：明显超出要差 10 分钟且 20%，按超出排，原因取超得最多那一轮回答的第一句', () => {
  const rep = {
    project_key: 'p',
    turns: [
      turn('big', 1, { e: NOW - 5 * H, seconds: 1200, estimate_seconds: 1200 }),
      turn('big', 1, { e: NOW - 4 * H, seconds: 4800, estimate_seconds: 2100, head: '## 看板清单的 11 条全部改完，已部署上线。下面是细节' }),
      turn('mid', 2, { e: NOW - 3 * H, seconds: 3000, estimate_seconds: 2000 }),
      turn('small', 3, { e: NOW - 2 * H, seconds: 900, estimate_seconds: 600 }),
      turn('early', 4, { e: NOW - H, seconds: 1200, estimate_seconds: 2400 }),
      turn('none', 5, { e: NOW - H, seconds: 300 }),
    ],
    questions: [],
  };
  const topics = ['big', 'mid', 'small', 'early', 'none'].map((k, i) => topic(k, i + 1, '做完'));
  const s = planSummary(buildReport(rep, topics, undefined, NOW, NOW - 10 * H));
  assert.deepEqual(s.over.map((r) => r.lane.label), ['T1', 'T2']);
  assert.deepEqual(s.under.map((r) => r.lane.label), ['T4']);
  assert.deepEqual(s.within.map((r) => r.lane.label), ['T3'], '多 5 分钟不点名');
  assert.deepEqual(s.never.map((l) => l.label), ['T5']);
  assert.equal(s.over[0].worst.n, 2);
  assert.equal(s.over[0].why, '看板清单的 11 条全部改完，已部署上线。');
  assert.equal(s.overSec, 2700 + 1000);
});

test('第一句：去掉 Markdown 记号，太长截到 60 字', () => {
  assert.equal(firstSentence('**网页设置页**已经上线，线上验收通过。最后…'), '网页设置页已经上线，线上验收通过。');
  assert.equal(firstSentence(null), '');
  assert.equal(firstSentence('字'.repeat(80)).length, 60);
});
