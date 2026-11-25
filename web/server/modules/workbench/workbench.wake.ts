/**
 * 同一个进程里的“有动静了”：发件箱写入时叫醒挂着等取件的请求，回执写入时叫醒挂着等回执的请求。
 * 多个实例时叫不醒别的实例，挂着的请求自己每隔一小会儿查一次库（waitFor 的 step），所以这只是提前，不是依赖。
 */
export type WakeChannel = 'inbox' | 'ack';

const waiting = new Map<WakeChannel, Set<() => void>>([
  ['inbox', new Set()],
  ['ack', new Set()],
]);
/** 同时挂着的请求上限：多了就不挂（马上按当时的库返回），免得长请求占满连接 */
const MAX_HELD = 24;
let held = 0;

export function wake(channel: WakeChannel): void {
  for (const w of [...(waiting.get(channel) ?? [])]) w();
}

/** 睡 ms 毫秒，或被 wake(channel) 提前叫醒 */
function nap(channel: WakeChannel, ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    const set: Set<() => void> = waiting.get(channel) ?? new Set();
    const done = (): void => {
      clearTimeout(timer);
      set.delete(done);
      resolve();
    };
    const timer: NodeJS.Timeout = setTimeout(done, ms);
    set.add(done);
  });
}

/**
 * 最多等 waitMs 毫秒，直到 check() 给出结果（非 null）；每隔 stepMs 毫秒查一次，被 wake(channel) 叫醒也马上查。
 * 超时返回 last（最后一次查的结果）。waitMs <= 0、挂着的请求太多或 aborted() 为真就只查一次。
 */
export async function waitFor<T>(
  channel: WakeChannel,
  waitMs: number,
  stepMs: number,
  check: () => Promise<T | null>,
  last: () => T,
  aborted: () => boolean = () => false,
): Promise<T> {
  const first: T | null = await check();
  if (first !== null) return first;
  if (waitMs <= 0 || held >= MAX_HELD) return last();
  held += 1;
  try {
    const end: number = Date.now() + waitMs;
    while (!aborted()) {
      const left: number = end - Date.now();
      if (left <= 0) break;
      await nap(channel, Math.min(stepMs, left));
      if (aborted()) break;
      const got: T | null = await check();
      if (got !== null) return got;
    }
    return last();
  } finally {
    held -= 1;
  }
}

/** ?wait=<秒> 的取值：不是数、小于等于 0 都当不等；超过 max 按 max */
export function waitSeconds(raw: unknown, max: number): number {
  const n: number = typeof raw === 'string' || typeof raw === 'number' ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.min(n, max) : 0;
}
