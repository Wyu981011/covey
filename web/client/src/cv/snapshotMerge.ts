/* 快照按增量取（T765 D2，数据约定 v38）：带 ?since=<上次的 cursor> 只返回这之后变过的话题和现在所有话题的 key，
 * 页面把它按 key 并进上一份。旧服务端不认 since、响应里没有 partial，就是整份，直接替换。纯函数，单测在 scripts/snapshot-merge.test.mjs。
 *
 * 什么时候取整份（T876 校准，单测在 scripts/calib.test.mjs）：以前写的是“每分钟回整份一次兜底”，现在只在有理由时取——
 * 第一次（缓存里没有、或服务端从没给过游标）、并不进去（keys 里有话题上一份和响应里都没有，增量断了档）、上一次取快照失败后
 * 的第一次（断线重连）、浏览器报网络恢复（online）、页面在后台待了 AWAY_FULL_MS 以上又切回前台；另留 FULL_BACKSTOP_MS 的长兜底。
 * 状态（上一次整份的时刻、待校准的原因、切到后台的时刻）由 hooks/use-workbench.ts 的模块变量拿着，这里只算。 */
import type { SnapshotResponse, SnapshotTopic } from '@shared/api.interface';

/**
 * 长兜底：没有别的理由时，距上一次整份满 30 分钟也取一次整份。增量靠服务端按 _updated_at 找变过的话题，照不到的边角
 * （话题删了又用同一个 key 建回、库里改了数据却没动 _updated_at）靠它半小时内补齐，代价是半小时一份整份（几百 KB）。
 * 去掉：改成 Infinity（只剩上面那几种理由）。
 */
export const FULL_BACKSTOP_MS = 30 * 60 * 1000;
/** 页面在后台待了这么久，切回前台的第一次取整份：后台时轮询停着，其间的变化增量也拿得到，整份是防它断档 */
export const AWAY_FULL_MS = 30 * 1000;

/** 取整份的理由：first 第一次（或服务端不给游标），gap 增量并不进去，reconnect 上一次失败了，online 网络恢复，back 从后台回来，backstop 长兜底 */
export type CalibReason = 'first' | 'gap' | 'reconnect' | 'online' | 'back' | 'backstop';

export interface Calib {
  /** 上一次拿到整份的时刻（毫秒）；0 是还没有 */
  lastFullAt: number;
  /** 下一次取快照要整份的理由（断线重连、网络恢复、从后台回来）；null 是没有 */
  pending: CalibReason | null;
  /** 页面切到后台的时刻；null 是在前台 */
  hiddenAt: number | null;
}

export const calibStart = (): Calib => ({ lastFullAt: 0, pending: null, hiddenAt: null });

/**
 * 这次取快照怎么取：since 是增量的游标（null 是取整份），reason 是取整份的理由（增量时 null），next 是领走待校准理由以后的状态
 * （这次失败了由 calibFailed 再记上 reconnect，所以不会丢）。cursor 是上一份响应的游标，hasPrev 是缓存里有没有上一份。
 * since 是游标原样，不要自己算时间。
 */
export function planSnapshot(cursor: string | null | undefined, hasPrev: boolean, c: Calib, now: number): { since: string | null; reason: CalibReason | null; next: Calib } {
  if (!hasPrev || !cursor) return { since: null, reason: 'first', next: { ...c, pending: null } };
  if (c.pending) return { since: null, reason: c.pending, next: { ...c, pending: null } };
  if (now - c.lastFullAt >= FULL_BACKSTOP_MS) return { since: null, reason: 'backstop', next: c };
  return { since: cursor, reason: null, next: c };
}

/** 拿到了一份整份（直接取的，或并不进去再取的） */
export const calibGotFull = (c: Calib, now: number): Calib => ({ ...c, lastFullAt: now });
/** 这次取快照失败了（断线、网关 429、服务端 5xx）：下一次成功的那次取整份 */
export const calibFailed = (c: Calib): Calib => ({ ...c, pending: c.pending ?? 'reconnect' });
/** 浏览器报网络恢复（online 事件） */
export const calibOnline = (c: Calib): Calib => ({ ...c, pending: c.pending ?? 'online' });
/** 页面切到后台（visibilitychange 到 hidden）：记下时刻，连着几次只记第一次 */
export const calibHidden = (c: Calib, now: number): Calib => ({ ...c, hiddenAt: c.hiddenAt ?? now });
/** 页面回到前台：在后台待满 AWAY_FULL_MS 就记下 back，下一次取整份；没满照常增量 */
export function calibVisible(c: Calib, now: number): Calib {
  const away: boolean = c.hiddenAt !== null && now - c.hiddenAt >= AWAY_FULL_MS;
  return { ...c, hiddenAt: null, pending: away ? (c.pending ?? 'back') : c.pending };
}

/**
 * 把一次响应并进上一份：不是增量（没有 partial）就是它自己；增量时变过的话题盖掉旧的、没变的留着、不在 keys 里的拿掉，
 * 话题的顺序照 keys（服务端按 updated_at 倒序）；projects、questions、asks、同步时间照响应的（它们每次都是整份）。
 * 并不出来（没有上一份、响应没带 keys、keys 里有话题上一份和响应里都没有）返回 null：调用方改取整份。
 * 合出来的是一份和整份一样的数据（没有 partial、keys），游标是这次响应的。
 */
export function mergeSnapshot(prev: SnapshotResponse | undefined, res: SnapshotResponse): SnapshotResponse | null {
  if (!res.partial) return res;
  if (!prev || !res.keys) return null;
  const byKey = new Map<string, SnapshotTopic>(prev.topics.map((t: SnapshotTopic) => [t.key, t]));
  for (const t of res.topics) byKey.set(t.key, t);
  const topics: SnapshotTopic[] = [];
  for (const k of res.keys) {
    const t: SnapshotTopic | undefined = byKey.get(k);
    if (!t) return null;
    topics.push(t);
  }
  // 没有话题变过、顺序也没变：沿用上一份的数组，别让依赖它的组件白重算
  const same: boolean = !res.topics.length && topics.length === prev.topics.length && topics.every((t: SnapshotTopic, i: number) => t === prev.topics[i]);
  const { partial: _partial, keys: _keys, ...rest } = res;
  return { ...rest, topics: same ? prev.topics : topics };
}
