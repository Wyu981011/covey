/* 网页发给 Covey 的操作发出去以后怎么等、等到什么再拉什么（T765 F1）：全是纯函数，网络、定时器、缓存都从 deps 传进来，
 * 所以节奏和状态能在单测里用假时钟走一遍（scripts/op-track.test.mjs）。接真请求和 react-query 的在 sendOp.ts。
 *
 * 一条操作的两段：
 *  1. 等回执：小间隔问 /api/outbox/:opId（250 毫秒起，几次后 500 毫秒，一分钟后 1 秒）；带 wait 的新服务端挂着等、有回执马上回，
 *     旧服务端不认 wait 就马上回，照间隔再问。
 *  2. 回执到了以后拉数据：先把这条操作碰到的话题轮次（大厅取大厅）和快照各取一次，之后约 3 秒内每 500 毫秒只取这个话题的轮次，
 *     直到看到预期的新状态（你的那一轮出现了、问题收起了、话题停了…）。
 * 取数一律“上一次还没回来就跳过”（cancelRefetch: false，在 sendOp.ts 的 pull 里）：CUA 第一版每 300 毫秒取整份快照并取消在途请求，
 * 单次取数一超过 300 毫秒就永远落不了地，反而慢到 11–14 秒。 */
import type { OutboxRequest, RoomResponse, SnapshotResponse, TurnsResponse } from '@shared/api.interface';
import { OP_WAIT_MS } from './opWords';

/** 带给服务端的 wait（秒）：新服务端最多挂这么久等回执，旧服务端不认、马上回 */
export const SERVER_WAIT_S = 5;

/** 第 i 次问回执之前隔多久：头 4 次 250 毫秒，到约 11 秒是 500 毫秒，之后 1 秒 */
export const pollGap = (i: number): number => (i < 4 ? 250 : i < 20 ? 500 : 1000);

/** 回执到了以后，取这个话题的轮次最多再取多久、隔多久 */
export const SETTLE_MS = 3000;
export const SETTLE_GAP_MS = 500;
/** 没有“预期的新状态”可看的操作，回执后再补取几次（Covey 回执前后推的新数据落库有先后） */
export const SETTLE_BLIND = 2;

/** 要取的数据：一个话题的轮次、大厅、快照、设置、整理建议、主记忆 */
export type Pull =
  | { t: 'turns'; key: string }
  | { t: 'room' }
  | { t: 'snapshot' }
  | { t: 'settings' }
  | { t: 'tidy' }
  | { t: 'memory' };

export const pullId = (p: Pull): string => (p.t === 'turns' ? `turns:${p.key}` : p.t);

/**
 * 这条操作回执以后要取的：先一次取齐 all，之后每 500 毫秒只取 follow（话题轮次、大厅，或者设置、整理建议、主记忆）。seen 的操作不用取。
 * turnsActive：这个话题的页面开着。没开着（看板上答题、不管了）取话题轮次没有用，改取快照（增量，很小）看卡片有没有消失。
 */
export function pullPlan(body: Pick<OutboxRequest, 'kind' | 'topic_key' | 'payload'>, turnsActive = true): { all: Pull[]; follow: Pull[] } {
  const kind: string = body.kind;
  if (kind === 'seen') return { all: [], follow: [] };
  const own: Pull[] = [];
  if (body.topic_key) own.push({ t: 'turns', key: body.topic_key });
  if (body.payload?.room === true) own.push({ t: 'room' });
  if (kind === 'settings') return { all: [{ t: 'settings' }], follow: [] };
  if (kind === 'memory_edit') return { all: [{ t: 'memory' }], follow: [] };
  if (kind === 'tidy' || kind === 'tidy_decide') return { all: [{ t: 'tidy' }, { t: 'snapshot' }], follow: [{ t: 'tidy' }] };
  if (kind === 'forget' || kind === 'memory_fix') return { all: [{ t: 'snapshot' }], follow: [] };
  if (kind === 'launch') return { all: [{ t: 'snapshot' }], follow: [{ t: 'snapshot' }] };
  return { all: [...own, { t: 'snapshot' }], follow: turnsActive ? own : [...own, { t: 'snapshot' }] };
}

/** 看缓存里“预期的新状态”到了没有：每个视图是这几份数据此刻在缓存里的样子 */
export interface View {
  turns?: TurnsResponse;
  room?: RoomResponse;
  snap?: SnapshotResponse;
}
export type Expect = (v: View) => boolean;

const bodyOf = (p: Record<string, unknown> | undefined, k: string): string => (typeof p?.[k] === 'string' ? (p[k] as string).trim() : '');
const isRunning = (t: TurnsResponse): boolean => t.topic.state === '在做' || t.turns.some((x) => x.status === 'running');

/**
 * 这条操作做完以后页面上该有的样子（没有就是 null：回执后只补取几次）。before 是发出时缓存里已有的轮次 key；
 * receipt 是 Covey 的回执原文（开新话题要从里面读 T 号）。
 * say：多了一条你的轮次（正文同你说的，带附件的正文后面有附件块，所以按开头比）；大厅里是 ob-<op_id> 或同样的你的轮次。
 * answer：问题收起（不处理同）；撤销不处理：问题又开着。stop：话题不在跑了。recover：开了新一轮或话题在做。dismiss：不在看板上。launch：快照里有这个 T 号。
 */
export function expectation(body: Pick<OutboxRequest, 'op_id' | 'kind' | 'topic_key' | 'payload'>, before: ReadonlySet<string>, receipt = ''): Expect | null {
  const p: Record<string, unknown> | undefined = body.payload;
  switch (body.kind) {
    case 'say': {
      const text: string = bodyOf(p, 'text');
      const mine = (turns: ReadonlyArray<{ key: string; role: string; body: string }> | undefined): boolean =>
        !!turns?.some((t) => !before.has(t.key) && (t.key === `ob-${body.op_id}` || (t.role === 'owner' && (text ? t.body.trim().startsWith(text) : true))));
      return (v: View): boolean => mine(v.turns?.turns) || mine(v.room?.turns);
    }
    case 'answer': {
      const token: string = bodyOf(p, 'token');
      // 话题页开着看话题里的问题；看板上答的话看快照里还开着的问题（快照只带开着的）
      const open = (v: View): boolean | null =>
        v.turns ? !!v.turns.question && v.turns.question.token === token && v.turns.question.state === 'open'
          : v.snap ? v.snap.questions.some((q) => q.token === token) : null;
      if (p?.restore === true) return (v: View): boolean => open(v) === true;
      return (v: View): boolean => open(v) === false;
    }
    case 'stop':
      if (p?.collab) return null;
      return (v: View): boolean => !!v.turns && !isRunning(v.turns);
    case 'recover': {
      const action: string = bodyOf(p, 'action');
      if (action === 'stop_auto_retry') return null;
      return (v: View): boolean => !!v.turns && (v.turns.topic.state === '在做' || v.turns.turns.some((t) => !before.has(t.key)));
    }
    case 'dismiss':
      return (v: View): boolean => {
        const t = v.snap?.topics.find((x) => x.key === body.topic_key);
        return !!v.snap && (!t || !t.board);
      };
    case 'launch': {
      const num: number = Number(/T(\d+)/u.exec(receipt)?.[1] ?? 0);
      return num ? (v: View): boolean => !!v.snap?.topics.some((t) => t.number === num && t.kind === 'topic') : null;
    }
    default:
      return null;
  }
}

/** 跟踪一条操作要用到的外面的东西：时钟、睡觉、问回执、取数、读缓存 */
export interface TrackDeps {
  now: () => number;
  sleep: (ms: number) => Promise<void>;
  /** 问一次回执；waitSec 是带给服务端的 wait。网络出错就抛 */
  status: (opId: string, waitSec: number) => Promise<{ state: string; message?: string }>;
  /** 取一份数据；上一次还没回来就跳过（不取消它） */
  pull: (p: Pull) => Promise<void>;
  /** 读缓存里这几份数据此刻的样子（预期的新状态用） */
  view: () => View;
}

export interface TrackResult {
  /** timeout：等满了还没回音（不是失败） */
  phase: 'done' | 'failed' | 'timeout';
  message: string;
}

/**
 * 等回执：先隔 pollGap(0) 再问第一次，之后问完隔 pollGap(i) 再问（问的时间算在间隔里，新服务端挂着等时不会连着打）。
 * done、failed 马上返回；问不到（网络抖）接着问；等满 ms 是 timeout；gone() 为真（组件卸了）也按 timeout 返回，不再问。
 */
export async function trackReceipt(
  d: Pick<TrackDeps, 'now' | 'sleep' | 'status'>,
  opId: string,
  o: { ms?: number; gone?: () => boolean; waitSec?: number } = {},
): Promise<TrackResult> {
  const ms: number = o.ms ?? OP_WAIT_MS;
  const t0: number = d.now();
  let started: number = t0;
  for (let i = 0; d.now() - t0 < ms; i += 1) {
    await d.sleep(Math.max(0, pollGap(i) - (d.now() - started)));
    if (o.gone?.()) break;
    started = d.now();
    try {
      const r = await d.status(opId, o.waitSec ?? SERVER_WAIT_S);
      if (r.state === 'done' || r.state === 'failed') return { phase: r.state, message: r.message ?? '' };
    } catch {
      /* 取不到就接着问 */
    }
  }
  return { phase: 'timeout', message: '' };
}

/** 一次取一组；有一份取失败了不影响别的 */
const pullAll = (d: Pick<TrackDeps, 'pull'>, ps: Pull[]): Promise<unknown> => Promise.all(ps.map((p: Pull) => d.pull(p).catch(() => undefined)));

/**
 * 回执到了以后拉数据：先取齐 plan.all；办成的操作再看预期的新状态到了没有，没到就每 500 毫秒取 plan.follow，最长 SETTLE_MS。
 * 没有预期的（expect 为 null）补取 SETTLE_BLIND 次就停。没办成的取一次就够（让发件行和失败原因出来）。返回有没有看到预期的新状态
 */
export async function settle(
  d: Pick<TrackDeps, 'now' | 'sleep' | 'pull' | 'view'>,
  plan: { all: Pull[]; follow: Pull[] },
  result: TrackResult,
  expect: Expect | null,
): Promise<boolean> {
  await pullAll(d, plan.all);
  if (result.phase !== 'done' || !plan.follow.length) return !expect || expect(d.view());
  if (expect && expect(d.view())) return true;
  const t0: number = d.now();
  for (let k = 0; d.now() - t0 < SETTLE_MS && (expect || k < SETTLE_BLIND); k += 1) {
    await d.sleep(SETTLE_GAP_MS);
    await pullAll(d, plan.follow);
    if (expect && expect(d.view())) return true;
  }
  return !expect;
}
