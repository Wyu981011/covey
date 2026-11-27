/**
 * 同一个进程里的“有动静了”：发件箱写入时叫醒挂着等取件的请求，回执写入时叫醒挂着等回执的请求。
 * 多个实例时叫不醒别的实例，挂着的请求自己每隔一小会儿查一次库（waitFor 的 step），所以这只是提前，不是依赖。
 * 挂着睡的时候（nap）不占库连接：每次 check 只发一条查询，查完就还给连接池（T876 的单测核对过）。
 */
import { memory, type Pressure } from './workbench.guard';

export type WakeChannel = 'inbox' | 'ack';

const waiting = new Map<WakeChannel, Set<() => void>>([
  ['inbox', new Set()],
  ['ack', new Set()],
]);
/** 同时挂着的请求上限，每条通道各算：多了就不挂（马上按当时的库返回）。取件只有 Covey 在等；回执是页面上每个在等的操作 */
export const MAX_HELD: Record<WakeChannel, number> = { inbox: 4, ack: 16 };
const held: Record<WakeChannel, number> = { inbox: 0, ack: 0 };
/** 内存水位（workbench.guard.ts）：单测换成假的 */
let pressure: () => Pressure = () => memory.pressure();
export function setPressureForTest(fn: () => Pressure): void {
  pressure = fn;
}
export function heldNow(channel: WakeChannel): number {
  return held[channel];
}

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
 * 超时返回 last（最后一次查的结果）。waitMs <= 0、这条通道挂着的请求太多、内存水位不是 ok 或 aborted() 为真就只查一次。
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
  if (waitMs <= 0 || held[channel] >= MAX_HELD[channel] || pressure() !== 'ok') return last();
  held[channel] += 1;
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
    held[channel] -= 1;
  }
}

/** ?wait=<秒> 的取值：不是数、小于等于 0 都当不等；超过 max 按 max */
export function waitSeconds(raw: unknown, max: number): number {
  const n: number = typeof raw === 'string' || typeof raw === 'number' ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.min(n, max) : 0;
}
