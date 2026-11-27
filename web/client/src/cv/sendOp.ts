import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { OutboxRequest, OutboxResponse, RoomResponse, TurnsResponse } from '@shared/api.interface';
import { fetchOutboxStatus, postOutbox } from '@client/src/api/workbench';
import { MEMORY_KEY, QUOTA_KEY, ROOM_KEY, SETTINGS_KEY, SNAPSHOT_KEY, TIDY_KEY, UPGRADE_KEY, turnsKey } from '@client/src/hooks/use-workbench';
import { errorText } from '@client/src/lib/workbench-format';
import { opWords, type OpPhase } from './opWords';
import { expectation, isMemoryPullKey, pullPlan, settle, trackReceipt, type Pull, type TrackDeps, type View } from './opTrack';

/* 发件箱的操作统一从这里发、在这里等回执和拉数据（T647 P1-C2，T765 F1）：说法在 opWords.ts，等法和拉数据的节奏在 opTrack.ts，
 * 各处不再自己写一套。发成功的操作都由 trackOp 跟踪：问回执、回执后重取这个话题的轮次和快照。 */

/** 发一条操作的结果：done、failed 带 Covey 的回执；unsent 是请求没发出去；timeout 是等满了还没回音（操作还在发件箱里）。
 * settled：回执后拉数据（话题的轮次、快照、预期的新状态）走完了没有；只有 done、failed 有，值是有没有看到预期的新状态 */
export interface OpResult {
  phase: Extract<OpPhase, 'done' | 'failed' | 'unsent' | 'timeout'>;
  message: string;
  settled?: Promise<boolean>;
}

/* ---------- 跟踪器的小仓库：谁发的、等到哪一步，按 op_id 读（按钮锁到有结果、气泡写回执都读它） ---------- */

/** waiting 已发出等回执，done、failed 是 Covey 的回执，timeout 是等满了没回音；settled 是回执后的取数走完了 */
export interface Tracked {
  opId: string;
  phase: 'waiting' | 'done' | 'failed' | 'timeout';
  message: string;
  settled: boolean;
  at: number;
}
const tracked = new Map<string, Tracked>();
const listeners = new Set<() => void>();
const KEEP_TRACKED = 80;
function setTracked(t: Tracked): void {
  tracked.delete(t.opId);
  tracked.set(t.opId, t);
  while (tracked.size > KEEP_TRACKED) tracked.delete(tracked.keys().next().value as string);
  listeners.forEach((l: () => void) => l());
}
const patchTracked = (opId: string, patch: Partial<Tracked>): void => {
  const cur: Tracked | undefined = tracked.get(opId);
  if (cur) setTracked({ ...cur, ...patch });
};

/** 不进组件时读一条：有没有跟踪过 */
export const trackedOf = (opId: string): Tracked | undefined => tracked.get(opId);

/** 一条发出去的操作现在走到哪了（没有跟踪过是 undefined） */
export function useTrackedOp(opId: string | undefined): Tracked | undefined {
  return useSyncExternalStore(
    (cb: () => void) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => (opId ? tracked.get(opId) : undefined),
  );
}

/* ---------- 接真请求和缓存 ---------- */

const no = { cancelRefetch: false } as const;

/**
 * 取一份：这份数据有页面在用才取（active），上一次取数还在路上就不取消它（cancelRefetch: false）。
 * 在路上的那次是回执到之前开始的，带回来的可能还是旧的：等它回来再取一次，保证拿到的比这一刻新。
 */
async function pullOf(qc: QueryClient, p: Pull): Promise<void> {
  const key: readonly unknown[] =
    p.t === 'snapshot' ? SNAPSHOT_KEY
    : p.t === 'turns' ? turnsKey(p.key)
    : p.t === 'room' ? ROOM_KEY
    : p.t === 'settings' ? SETTINGS_KEY
    : p.t === 'tidy' ? TIDY_KEY
    : p.t === 'upgrade' ? UPGRADE_KEY
    : p.t === 'quota' ? QUOTA_KEY
    : MEMORY_KEY;
  // 记忆只取 memory:index（和旧键 memory），带 rev 的数据键不取（见 isMemoryPullKey）
  const filters =
    p.t === 'memory'
      ? ({ queryKey: key, type: 'active', predicate: (q: { queryKey: readonly unknown[] }): boolean => isMemoryPullKey(q.queryKey) } as const)
      : ({ queryKey: key, type: 'active' } as const);
  const inflight: boolean = qc.getQueryCache().find(filters)?.state.fetchStatus === 'fetching';
  await qc.refetchQueries(filters, no);
  if (inflight) await qc.refetchQueries(filters, no);
}

const sleep = (ms: number): Promise<void> => new Promise<void>((r: () => void) => window.setTimeout(r, ms));

function depsFor(qc: QueryClient, body: Pick<OutboxRequest, 'topic_key'>): { deps: TrackDeps; before: Set<string> } {
  const turns = (): TurnsResponse | undefined => (body.topic_key ? qc.getQueryData<TurnsResponse>(turnsKey(body.topic_key)) : undefined);
  const room = (): RoomResponse | undefined => qc.getQueryData<RoomResponse>(ROOM_KEY);
  const before = new Set<string>([...(turns()?.turns ?? []), ...(room()?.turns ?? [])].map((t: { key: string }) => t.key));
  return {
    before,
    deps: {
      now: Date.now,
      sleep,
      status: (opId: string, waitSec: number) => fetchOutboxStatus(opId, waitSec),
      pull: (p: Pull) => pullOf(qc, p),
      view: (): View => ({ turns: turns(), room: room(), snap: qc.getQueryData(SNAPSHOT_KEY) }),
    },
  };
}

/**
 * 发成功的操作交给它：问回执（opTrack.trackReceipt），回执一到就返回（done、failed、timeout），同时开始拉数据（opTrack.settle：
 * 这个话题的轮次、大厅、快照各取一次，之后约 3 秒内每 500 毫秒只取这个话题的轮次，直到看到预期的新状态）；返回值的 settled 是那段取数。
 * 结果也写进小仓库（useTrackedOp）。gone() 为真（组件卸了）就不再问回执；ms 是最长等多久。
 */
export async function trackOp(qc: QueryClient, body: OutboxRequest, o: { gone?: () => boolean; ms?: number } = {}): Promise<OpResult> {
  const { deps, before } = depsFor(qc, body);
  setTracked({ opId: body.op_id, phase: 'waiting', message: '', settled: false, at: Date.now() });
  const r = await trackReceipt(deps, body.op_id, { ms: o.ms, gone: o.gone });
  if (r.phase === 'timeout') {
    patchTracked(body.op_id, { phase: 'timeout', settled: true });
    return { phase: 'timeout', message: '' };
  }
  patchTracked(body.op_id, { phase: r.phase, message: r.message });
  const turnsActive: boolean = !body.topic_key || !!qc.getQueryCache().find({ queryKey: turnsKey(body.topic_key), type: 'active' });
  const settled: Promise<boolean> = settle(deps, pullPlan(body, turnsActive), r, expectation(body, before, r.message)).catch(() => false);
  void settled.then(() => patchTracked(body.op_id, { settled: true }));
  return { phase: r.phase, message: r.message, settled };
}

/** 发一条操作并等回执；onSent 在请求发出去（写进网页库）以后调一次（界面从“发送中”换成“等 Covey”） */
export async function sendOp(body: OutboxRequest, qc: QueryClient, onSent?: () => void, gone?: () => boolean, ms?: number): Promise<OpResult> {
  try {
    await postOutbox(body);
  } catch (e) {
    return { phase: 'unsent', message: errorText(e) };
  }
  onSent?.();
  return trackOp(qc, body, { gone, ms });
}

/**
 * 发一条操作（POST /api/outbox）：发成功就交给跟踪器等回执、再拉这个话题和快照；结果在小仓库里（useTrackedOp(opId)），调用方按 op_id 读。
 * 不再每次发完把话题和快照都 invalidate 一遍（CUA 第一版那样取整份快照反而慢）。
 */
export const useSendOutbox = () => {
  const qc: QueryClient = useQueryClient();
  return useMutation<OutboxResponse, Error, OutboxRequest>({
    mutationFn: (body: OutboxRequest) => postOutbox(body),
    retry: false,
    onSuccess: (_res: OutboxResponse, vars: OutboxRequest) => {
      void trackOp(qc, vars);
    },
  });
};

export interface OutboxOp {
  /** 现在走到哪；还没发过是 null */
  phase: OpPhase | null;
  /** Covey 的回执或没发出去的原因 */
  message: string;
  /** 给人看的那一行（opWords） */
  line: string;
  /** 在发或在等回执 */
  busy: boolean;
  /** keep：组件卸了也接着等回执（调用方要回执另记，如 RecoverBits 写在停住的那一轮下面） */
  run: (body: OutboxRequest, keep?: boolean) => Promise<OpResult>;
  reset: () => void;
}

/* 同一件事在页面上有几处按钮（停住的一轮、右栏的总览、看板卡都有“接着做”“不管了”）：点了一处，别处也要锁、也写同一句话。
 * 按 shareKey 共用一份状态；办好、没办成、没回音的状态留 60 秒（Covey 的新状态推回来按钮自己就变了），之后放开。 */
interface Shared {
  phase: OpPhase;
  message: string;
}
const shared = new Map<string, Shared>();
const sharedListeners = new Set<() => void>();
const SHARED_KEEP_MS = 60000;
function putShared(key: string, v: Shared | null): void {
  if (v) shared.set(key, v);
  else shared.delete(key);
  sharedListeners.forEach((l: () => void) => l());
  if (v && v.phase !== 'sending' && v.phase !== 'waiting') {
    window.setTimeout(() => {
      if (shared.get(key) === v) putShared(key, null);
    }, SHARED_KEEP_MS);
  }
}
const useSharedOp = (key: string | undefined): Shared | undefined =>
  useSyncExternalStore(
    (cb: () => void) => {
      sharedListeners.add(cb);
      return () => sharedListeners.delete(cb);
    },
    () => (key ? shared.get(key) : undefined),
  );

/**
 * 一个按钮一条操作：发出去、等回执、办好了拉数据；状态和那句话按 opWords 写。组件卸了就不再等。busy 一直到回执（或等满）才放开。
 * shareKey：同一件事在页面上有几处按钮时给同一个 key，它们共用状态（点一处，处处锁住、写同一句话；这时卸了也接着等回执，别处还要读它）
 */
export function useOutboxOp(shareKey?: string): OutboxOp {
  const qc: QueryClient = useQueryClient();
  const [own, setOwn] = useState<Shared | null>(null);
  const common: Shared | undefined = useSharedOp(shareKey);
  const alive = useRef<boolean>(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const put = (p: OpPhase | null, m = ''): void => {
    if (shareKey) {
      putShared(shareKey, p ? { phase: p, message: m } : null);
      return;
    }
    if (!alive.current) return;
    setOwn(p ? { phase: p, message: m } : null);
  };
  const run = async (body: OutboxRequest, keep = false): Promise<OpResult> => {
    put('sending');
    const r: OpResult = await sendOp(body, qc, () => put('waiting'), () => !keep && !shareKey && !alive.current);
    put(r.phase, r.message);
    return r;
  };
  const cur: Shared | null = shareKey ? (common ?? null) : own;
  const phase: OpPhase | null = cur?.phase ?? null;
  const message: string = cur?.message ?? '';
  return {
    phase,
    message,
    line: phase ? opWords(phase, message) : '',
    busy: phase === 'sending' || phase === 'waiting',
    run,
    reset: () => put(null),
  };
}

/**
 * 发一条不属于对话的操作（纠正记忆、停一次协作），等 Covey 的回执，结果用 toast 说：
 * done 写它回的那句，failed 写原因（旧版 Covey 不认这个操作也是这里说），等满了说操作还在发件箱里。
 */
/** sendAndWait 带着页面的 QueryClient：组件里 `const sendWait = useSendAndWait();` 再 `await sendWait(body, '已发出：…')` */
export function useSendAndWait(): (body: OutboxRequest, sent: string) => Promise<'done' | 'failed' | 'new'> {
  const qc: QueryClient = useQueryClient();
  return (body: OutboxRequest, sent: string) => sendAndWait(qc, body, sent);
}

export async function sendAndWait(qc: QueryClient, body: OutboxRequest, sent: string): Promise<'done' | 'failed' | 'new'> {
  const r: OpResult = await sendOp(body, qc, () => toast.message(sent));
  const line: string = opWords(r.phase, r.message);
  if (r.phase === 'done') {
    toast.success(line);
    return 'done';
  }
  if (r.phase === 'timeout') {
    toast.message(line);
    return 'new';
  }
  toast.error(line);
  return 'failed';
}
