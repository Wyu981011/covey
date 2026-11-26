/* 「账号与额度」（数据约定 v42，Covey 推的设置条目 quota）：从条目算出表里每一格写什么、颜色、旧不旧，折起来的来源一行写什么，
 * 侧栏胶囊说什么。纯函数，单测在 scripts/quota.test.mjs。时间都是秒；几点几分按上海时区写，和别处一样。 */
import type { QuotaAccount, QuotaData, QuotaPool, QuotaResponse, QuotaSource, QuotaWindow } from '@shared/api.interface';
import { canDo } from './v34';

/** 设置页里的页签；Covey 有额度来源才有 */
export const QUOTA_TAB = { key: 'quota', label: '账号与额度' } as const;

/** 剩余不到这个比例就红 */
export const TIGHT = 0.2;
/** 剩余不超过这个比例算用完（agy 的口径：1% 以下） */
export const SPENT = 0.01;

/** 这个 Covey 有「账号与额度」：认 quota_refresh 操作，也推过来源 */
export const quotaOn = (ops: readonly string[] | null | undefined, r: QuotaResponse | null | undefined): boolean =>
  canDo(ops, 'quota_refresh') && (r?.data?.sources?.length ?? 0) > 0;

const TZ = 'Asia/Shanghai';
const dayKey = (sec: number): string => new Date(sec * 1000).toLocaleDateString('zh-CN', { timeZone: TZ });
const WEEK: readonly string[] = ['日', '一', '二', '三', '四', '五', '六'];

export const hm = (sec: number): string =>
  new Date(sec * 1000).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: TZ });

/** 一个时刻怎么写：今天写 19:05，别的天写周几（一周内），再远写 月-日 */
export function whenWords(sec: number, now: number): string {
  if (!(sec > 0)) return '';
  if (dayKey(sec) === dayKey(now)) return hm(sec);
  const weekday: string = WEEK[new Date(new Date(sec * 1000).toLocaleString('en-US', { timeZone: TZ })).getDay()];
  if (Math.abs(sec - now) < 6.5 * 86400) return `周${weekday}`;
  return new Date(sec * 1000).toLocaleDateString('zh-CN', { timeZone: TZ, month: 'numeric', day: 'numeric' }).replace('/', '-');
}

/** “6 小时前”这样的话，悬停说读数多旧 */
export function agoWords(sec: number, now: number): string {
  const s: number = Math.max(0, now - sec);
  if (s < 90) return '刚刚';
  if (s < 5400) return `${Math.round(s / 60)} 分钟前`;
  if (s < 36 * 3600) return `${Math.round(s / 3600)} 小时前`;
  return `${Math.round(s / 86400)} 天前`;
}

/** 一格：none 读不到（写“—”、不画条）；out 用完；bar 画条；pct 是剩余百分比（0~100）；at 是时刻或“平均” */
export interface Cell {
  kind: 'none' | 'out' | 'bar';
  pct: number | null;
  at: string;
  stale: boolean;
  tight: boolean;
  /** 悬停：读数是什么时候的、为什么写“—” */
  title: string;
}
const NONE = (title = ''): Cell => ({ kind: 'none', pct: null, at: '', stale: false, tight: false, title });

/** 同一种窗口有几个（网关的“Fable 周”和“周”）取剩得最少的；都读不到取第一个 */
export function pickWindow(pool: QuotaPool, kind: '5h' | '7d'): QuotaWindow | null {
  const of: QuotaWindow[] = pool.windows.filter((w: QuotaWindow) => w.kind === kind);
  const read: QuotaWindow[] = of.filter((w: QuotaWindow) => w.left !== null);
  if (read.length) return read.reduce((a: QuotaWindow, b: QuotaWindow) => ((b.left as number) < (a.left as number) ? b : a));
  return of[0] ?? null;
}

/** 这个池因为 state 用完，该写在哪一列：读数里已经用完的那个窗口，没有就写在 5 小时那一列 */
function outKind(pool: QuotaPool): '5h' | '7d' | null {
  if (pool.state !== 'spent' && pool.state !== 'cooling') return null;
  const spent: QuotaWindow | undefined = pool.windows.find((w: QuotaWindow) => (w.kind === '5h' || w.kind === '7d') && w.left !== null && w.left <= SPENT);
  return spent ? (spent.kind as '5h' | '7d') : '5h';
}

export function cellOf(source: QuotaSource, pool: QuotaPool, kind: '5h' | '7d', now: number): Cell {
  const w: QuotaWindow | null = pickWindow(pool, kind);
  const oldSource: boolean = source.collected_at > 0 && now - source.collected_at > 2 * source.ttl;
  const out: boolean = outKind(pool) === kind;
  if (oldSource) return NONE(`读数太旧（${agoWords(source.collected_at, now)}）`);
  const back: number = pool.available_at ?? w?.resets_at ?? 0;
  if (!w || w.left === null) {
    return out ? { kind: 'out', pct: 0, at: back ? `${whenWords(back, now)} 恢复` : '', stale: false, tight: false, title: '' } : NONE(w ? '读不到' : '');
  }
  const checked: number = w.checked_at ?? source.collected_at;
  if (!out && w.resets_at && w.resets_at <= now && checked < w.resets_at) return NONE('已重置，还没有新读数');
  const stale: boolean = source.failing || (checked > 0 && now - checked > source.stale_after);
  const title: string = stale ? (checked > 0 ? `${agoWords(checked, now)}的读数${source.failing ? '，上次读取没成功' : ''}` : '上次读取没成功') : '';
  if (out || w.left <= SPENT) {
    const at: number = pool.available_at ?? w.resets_at ?? 0;
    return { kind: 'out', pct: 0, at: at ? `${whenWords(at, now)} 恢复` : '', stale, tight: false, title };
  }
  return {
    kind: 'bar',
    pct: Math.round(w.left * 100),
    at: w.resets_at ? whenWords(w.resets_at, now) : '',
    stale,
    tight: w.left < TIGHT,
    title,
  };
}

/** 账号的名字：登录的邮箱（完整），读不到才用来源给的名字 */
export const nameOf = (a: QuotaAccount): string => a.login || a.name;

/** 整行的话（要重新登录、暂停、到期）；有读数可画的是空串 */
export function rowNote(a: QuotaAccount): string {
  if (a.state === 'login_required') return '要重新登录';
  if (a.state === 'paused') return '已暂停';
  if (a.state === 'expired') return '已到期';
  return '';
}

/** 号在不在用：agy 只有一个池时，在用的号名字前一个蓝点；两个池时蓝点标在模型名前（poolActive） */
export const accountActive = (a: QuotaAccount): boolean => a.pools.length === 1 && a.pools[0].active;

/** 来源折成一行时某一列的平均：只算读得到的号，没有就是“—” */
export function avgCell(source: QuotaSource, kind: '5h' | '7d', now: number): Cell {
  const cells: Cell[] = source.accounts
    .map((a: QuotaAccount) => (a.pools[0] && !rowNote(a) ? cellOf(source, a.pools[0], kind, now) : NONE()))
    .filter((c: Cell) => c.kind !== 'none');
  if (!cells.length) return NONE();
  const pct: number = Math.round(cells.reduce((sum: number, c: Cell) => sum + (c.pct ?? 0), 0) / cells.length);
  return { kind: 'bar', pct, at: '平均', stale: cells.every((c: Cell) => c.stale), tight: pct < TIGHT * 100, title: '' };
}

/** 一个号有没有事：冷却、用完，或有一格剩不到 20%（红点） */
export function accountWarn(source: QuotaSource, a: QuotaAccount, now: number): boolean {
  if (a.state === 'spent' || a.state === 'cooling') return true;
  return a.pools.some((p: QuotaPool) =>
    (['5h', '7d'] as const).some((k: '5h' | '7d') => {
      const c: Cell = cellOf(source, p, k, now);
      return c.tight || c.kind === 'out';
    }),
  );
}

/** 组名后的红点：有号有事 */
export const sourceWarn = (source: QuotaSource, now: number): boolean => source.accounts.some((a: QuotaAccount) => accountWarn(source, a, now));

/** 展开还是折起：用户点过听用户的，否则 Covey 说展开（expand）就展开 */
export const isOpen = (source: QuotaSource, picked: boolean | undefined): boolean => (picked === undefined ? source.expand : picked);

/** 组名旁的小字：agy 写“N 个号 · 用完自动顺延”；展开的别的来源写“N 个号”；折起的写“k/n 个能用” */
export function groupNote(source: QuotaSource, open: boolean): string {
  const n: number = source.accounts.length;
  if (source.kind === 'agy') return `${n} 个号 · 用完自动顺延`;
  if (open) return `${n} 个号`;
  return source.total > 0 ? `${source.usable}/${source.total} 个能用` : source.failing ? '读不到' : '';
}

/** 侧栏胶囊：某个来源整体见底，或有号要重新登录；都没有是空串（不画）。点了到这一页 */
export function capsuleOf(data: QuotaData | null | undefined): string {
  if (!data) return '';
  const low: QuotaSource | undefined = data.sources.find((s: QuotaSource) => s.low);
  if (low) return `${low.title} 额度见底${low.dry && low.next_available_at ? ` · ${hm(low.next_available_at)} 恢复` : ''}`;
  const first = data.relogin[0];
  if (!first) return '';
  const same: number = data.relogin.filter((r: { source: string }) => r.source === first.source).length;
  return `${first.source} 有 ${same} 个号要重新登录`;
}

/** 表上方的红条：哪个来源的哪个号要重新登录；没有是空串 */
export const reloginLine = (data: QuotaData): string => data.relogin.map((r: { source: string; name: string }) => `${r.source} · ${r.name} 要重新登录`).join('；');

/** 标题行右边的读数时刻；没有读过是空串 */
export const readWords = (data: QuotaData): string => (data.read_at > 0 ? hm(data.read_at) : '');
