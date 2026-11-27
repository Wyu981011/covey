/**
 * 内存水位和库连接的保护（T876）。纯逻辑，不带 Nest 装饰器，单测直接导入（scripts/perf-server.test.mjs）。
 *
 * 为什么要：妙搭 FaaS 一个实例 1 GiB 内存，平台却给 Node 设了 --max-old-space-size=3072：堆涨过 1 GiB 时是整个实例被 cgroup 杀掉，
 * 不是 V8 先回收。平台不让改 NODE_OPTIONS 时（或改了也没生效），只能应用自己看水位让路；平台包的连接池只有 7 条（单集群最多 15 条，
 * 换令牌时会翻倍），一次整份快照就并发 7 条查询，几个标签页加上 Covey 一批 500 条的写入能把池占满，Covey 的推送和回执排在后面。
 *
 * - pressure()：常驻内存占容器上限（读不到就用 V8 堆上限）的比例，≥ HIGH 是 high、≥ CRITICAL 是 critical，最多每秒读一次。
 *   high：不再挂起等待（取件、回执马上按库里的返回），新附件和图片先回 503 让对方稍后重传；critical：页面的取数也回 503，
 *   只留 Covey 的推送、回执和取件（它们让页面有新状态，又都是小请求）。
 * - Gate：库查询的闸门，按车道限并发：page（浏览器 /api）、sync（Covey /openapi）各有上限，两边加起来小于连接池，谁都占不满；
 *   排队有上限和最长等待，超了回 503（不无限堆在内存里）。车道从 AsyncLocalStorage 取，中间件按路径设（workbench.module.ts）。
 * - Batcher：同一时刻好几个挂着等回执的请求，各自每 250 毫秒查一次库，合成一条 `op_id in (...)` 查询。
 */
import { AsyncLocalStorage } from 'async_hooks';
import { heapLimitMb, memLimitMb, rssMb } from './workbench.limits';

export type Pressure = 'ok' | 'high' | 'critical';
export const HIGH = 0.7;
export const CRITICAL = 0.85;
const SAMPLE_MS = 1000;

export interface MemReader {
  rss: () => number;
  limit: () => number;
  now: () => number;
}
const realReader: MemReader = {
  rss: rssMb,
  limit: (): number => memLimitMb() || heapLimitMb(),
  now: (): number => Date.now(),
};

export class MemoryGuard {
  private at = -Infinity;
  private level: Pressure = 'ok';
  /** 水位变过几次（日志用）；last 是上次变的时刻和读数 */
  changes = 0;
  last: { level: Pressure; rss: number; limit: number } = { level: 'ok', rss: 0, limit: 0 };

  private readonly read: MemReader;
  private readonly onChange: (l: Pressure, rss: number, limit: number) => void;

  constructor(read: MemReader = realReader, onChange: (l: Pressure, rss: number, limit: number) => void = () => undefined) {
    this.read = read;
    this.onChange = onChange;
  }

  pressure(): Pressure {
    const now: number = this.read.now();
    if (now - this.at < SAMPLE_MS) return this.level;
    this.at = now;
    const rss: number = this.read.rss();
    const limit: number = this.read.limit();
    const ratio: number = limit > 0 ? rss / limit : 0;
    const level: Pressure = ratio >= CRITICAL ? 'critical' : ratio >= HIGH ? 'high' : 'ok';
    if (level !== this.level) {
      this.level = level;
      this.changes += 1;
      this.last = { level, rss, limit };
      this.onChange(level, rss, limit);
    }
    return level;
  }
}

/** 进程里共用的一份；水位变了记一行（日志里看得见实例快到上限了） */
export const memory = new MemoryGuard(realReader, (level: Pressure, rss: number, limit: number): void => {
  // eslint-disable-next-line no-console
  console.warn(`[workbench] memory ${level}: rss ${rss} MB of ${limit} MB`);
});

export type Lane = 'page' | 'sync';
const laneStore = new AsyncLocalStorage<Lane>();

/** 在 lane 车道里跑 fn（中间件用；fn 里发起的查询都算这个车道） */
export function inLane<T>(lane: Lane, fn: () => T): T {
  return laneStore.run(lane, fn);
}

export function currentLane(): Lane {
  return laneStore.getStore() ?? 'page';
}

/** 请求路径属于哪个车道：/openapi/ 是 Covey，其余是页面 */
export function laneOfPath(path: string): Lane {
  return /(^|\/)openapi\//u.test(path) ? 'sync' : 'page';
}

/** 闸门拒收（排队满了、等太久）：控制器把它变成 503 */
export class GateBusy extends Error {
  readonly lane: Lane;
  readonly why: 'queue' | 'wait';

  constructor(lane: Lane, why: 'queue' | 'wait') {
    super(why === 'queue' ? '服务端忙，稍后再试' : '服务端忙（库查询排队太久），稍后再试');
    this.lane = lane;
    this.why = why;
  }
}

export interface GateOptions {
  caps: Record<Lane, number>;
  /** 每条车道最多排多少个 */
  queueMax: number;
  /** 排队最久多少毫秒 */
  waitMs: number;
}
/** page 4 条 + sync 2 条 = 6 条，比平台包的 7 条池少 1 条，留给平台自己的查询 */
export const GATE_DEFAULTS: GateOptions = { caps: { page: 4, sync: 2 }, queueMax: 400, waitMs: 15000 };

interface Waiter {
  go: () => void;
  timer: NodeJS.Timeout | null;
}

export class Gate {
  readonly inflight: Record<Lane, number> = { page: 0, sync: 0 };
  /** 观测：各车道同时在跑的最多几条、排过队的次数、拒过几次 */
  readonly peak: Record<Lane, number> = { page: 0, sync: 0 };
  readonly queued: Record<Lane, number> = { page: 0, sync: 0 };
  readonly refused: Record<Lane, number> = { page: 0, sync: 0 };
  private readonly queues: Record<Lane, Waiter[]> = { page: [], sync: [] };

  readonly opts: GateOptions;

  constructor(opts: GateOptions = GATE_DEFAULTS) {
    this.opts = opts;
  }

  get total(): number {
    return this.inflight.page + this.inflight.sync;
  }

  async run<T>(lane: Lane, fn: () => PromiseLike<T> | T): Promise<T> {
    if (this.inflight[lane] >= this.opts.caps[lane]) await this.wait(lane);
    this.inflight[lane] += 1;
    if (this.inflight[lane] > this.peak[lane]) this.peak[lane] = this.inflight[lane];
    try {
      return await fn();
    } finally {
      this.inflight[lane] -= 1;
      this.next(lane);
    }
  }

  private wait(lane: Lane): Promise<void> {
    const q: Waiter[] = this.queues[lane];
    if (q.length >= this.opts.queueMax) {
      this.refused[lane] += 1;
      return Promise.reject(new GateBusy(lane, 'queue'));
    }
    this.queued[lane] += 1;
    return new Promise<void>((resolve, reject) => {
      const w: Waiter = { go: resolve, timer: null };
      w.timer = setTimeout(() => {
        const i: number = q.indexOf(w);
        if (i >= 0) q.splice(i, 1);
        this.refused[lane] += 1;
        reject(new GateBusy(lane, 'wait'));
      }, this.opts.waitMs);
      q.push(w);
    });
  }

  private next(lane: Lane): void {
    if (this.inflight[lane] >= this.opts.caps[lane]) return;
    const w: Waiter | undefined = this.queues[lane].shift();
    if (!w) return;
    if (w.timer) clearTimeout(w.timer);
    w.go();
  }
}

/** 进程里共用的闸门 */
export const gate = new Gate();

/** 服务只用 db.execute（妙搭的 drizzle 和自托管的包装都是）：包一层，每条查询先过闸门，车道看当前请求 */
export interface Executes {
  execute(query: unknown): PromiseLike<unknown>;
}
export function gated<D extends Executes>(db: D, g: Gate = gate, lane: () => Lane = currentLane, busy: (e: GateBusy) => Error = (e) => e): D {
  return new Proxy(db, {
    get(target: D, prop: string | symbol, receiver: unknown): unknown {
      if (prop === 'execute') {
        return (query: unknown): Promise<unknown> =>
          g.run(lane(), () => target.execute(query)).catch((e: unknown) => {
            throw e instanceof GateBusy ? busy(e) : e;
          });
      }
      return Reflect.get(target, prop, receiver);
    },
  });
}

/**
 * 把同一时刻的很多次 get(key) 合成一次 fetch(keys)：第一个 get 之后等 delayMs 毫秒收齐，一次查完，各自拿自己的。
 * fetch 失败时这一批都失败（调用方照旧处理）。
 */
export class Batcher<K, V> {
  private pending: Map<K, { resolve: (v: V | undefined) => void; reject: (e: unknown) => void }[]> = new Map();
  private timer: NodeJS.Timeout | null = null;
  /** 观测：发过几次 fetch、合并了几次 get */
  fetches = 0;
  gets = 0;

  private readonly fetch: (keys: K[]) => Promise<Map<K, V>>;
  private readonly delayMs: number;

  constructor(fetch: (keys: K[]) => Promise<Map<K, V>>, delayMs = 15) {
    this.fetch = fetch;
    this.delayMs = delayMs;
  }

  get(key: K): Promise<V | undefined> {
    this.gets += 1;
    return new Promise<V | undefined>((resolve, reject) => {
      const list = this.pending.get(key) ?? [];
      list.push({ resolve, reject });
      this.pending.set(key, list);
      if (!this.timer) this.timer = setTimeout(() => void this.flush(), this.delayMs);
    });
  }

  private async flush(): Promise<void> {
    const batch = this.pending;
    this.pending = new Map();
    this.timer = null;
    this.fetches += 1;
    try {
      const got: Map<K, V> = await this.fetch([...batch.keys()]);
      for (const [k, list] of batch) for (const w of list) w.resolve(got.get(k));
    } catch (e) {
      for (const list of batch.values()) for (const w of list) w.reject(e);
    }
  }
}
