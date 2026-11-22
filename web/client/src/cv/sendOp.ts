import { useEffect, useRef, useState } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { OutboxRequest, OutboxStatus } from '@shared/api.interface';
import { fetchOutboxStatus, postOutbox } from '@client/src/api/workbench';
import { ROOM_KEY, SNAPSHOT_KEY, turnsKey } from '@client/src/hooks/use-workbench';
import { errorText } from '@client/src/lib/workbench-format';
import { OP_TRIES, OP_WAIT_MS, opDelay, opWords, type OpPhase } from './opWords';

/* 发件箱的操作统一从这里发、在这里等回执（T647 P1-C2）：说法在 opWords.ts，各处不再自己写一套。 */

const sleep = (ms: number): Promise<void> => new Promise<void>((r: () => void) => window.setTimeout(r, ms));

/** 发一条操作的结果：done、failed 带 Covey 的回执；unsent 是请求没发出去；timeout 是等满了还没回音（操作还在发件箱里） */
export interface OpResult {
  phase: Extract<OpPhase, 'done' | 'failed' | 'unsent' | 'timeout'>;
  message: string;
}

/** 等 opId 的回执：先密后疏地问，问到 done/failed 就返回；问不到（网络抖）接着问；等满 ms（默认 OP_WAIT_MS）是 timeout。gone() 为真就不等了 */
export async function waitOp(opId: string, gone: () => boolean = () => false, ms: number = OP_WAIT_MS): Promise<OpResult> {
  const tries: number = ms === OP_WAIT_MS ? OP_TRIES : Math.ceil(OP_TRIES * (ms / OP_WAIT_MS));
  for (let i = 0; i < tries; i += 1) {
    await sleep(opDelay(i));
    if (gone()) break;
    let r: OutboxStatus;
    try {
      r = await fetchOutboxStatus(opId);
    } catch {
      continue;
    }
    if (r.state === 'done' || r.state === 'failed') return { phase: r.state, message: r.message || '' };
  }
  return { phase: 'timeout', message: '' };
}

/** 发一条操作并等回执；onSent 在请求发出去以后调一次（界面从“发送中”换成“等 Covey”） */
export async function sendOp(body: OutboxRequest, onSent?: () => void, gone?: () => boolean, ms?: number): Promise<OpResult> {
  try {
    await postOutbox(body);
  } catch (e) {
    return { phase: 'unsent', message: errorText(e) };
  }
  onSent?.();
  return waitOp(body.op_id, gone, ms);
}

/** 办好了：刷新这条操作碰到的话题、大厅和快照（Covey 回执前已推了新数据） */
export function refreshAfter(qc: QueryClient, body: Pick<OutboxRequest, 'topic_key' | 'payload'>): void {
  if (body.topic_key) void qc.invalidateQueries({ queryKey: turnsKey(body.topic_key) });
  if (body.payload?.room === true) void qc.invalidateQueries({ queryKey: ROOM_KEY });
  void qc.invalidateQueries({ queryKey: SNAPSHOT_KEY });
}

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

/** 一个按钮一条操作：发出去、等回执、办好了刷新数据；状态和那句话按 opWords 写。组件卸了就不再等 */
export function useOutboxOp(): OutboxOp {
  const qc: QueryClient = useQueryClient();
  const [phase, setPhase] = useState<OpPhase | null>(null);
  const [message, setMessage] = useState<string>('');
  const alive = useRef<boolean>(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const put = (p: OpPhase | null, m = ''): void => {
    if (!alive.current) return;
    setPhase(p);
    setMessage(m);
  };
  const run = async (body: OutboxRequest, keep = false): Promise<OpResult> => {
    put('sending');
    const r: OpResult = await sendOp(body, () => put('waiting'), () => !keep && !alive.current);
    if (r.phase === 'done') refreshAfter(qc, body);
    put(r.phase, r.message);
    return r;
  };
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
export async function sendAndWait(body: OutboxRequest, sent: string): Promise<'done' | 'failed' | 'new'> {
  const r: OpResult = await sendOp(body, () => toast.message(sent));
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
