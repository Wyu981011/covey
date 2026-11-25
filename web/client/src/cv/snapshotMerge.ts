/* 快照按增量取（T765 D2，数据约定 v38）：带 ?since=<上次的 cursor> 只返回这之后变过的话题和现在所有话题的 key，
 * 页面把它按 key 并进上一份。旧服务端不认 since、响应里没有 partial，就是整份，直接替换。纯函数，单测在 scripts/snapshot-merge.test.mjs。 */
import type { SnapshotResponse, SnapshotTopic } from '@shared/api.interface';

/** 距离上一次整份快照超过这么久，这次就取整份：增量只是省流量，整份兜住推丢的、改过没进游标的任何边角 */
export const FULL_EVERY_MS = 60000;

/**
 * 这次取快照带不带 since：上一份有游标、整份是不久前取的才带；否则（第一次、旧服务端没给过游标、该整份了）是 null。
 * since 是游标原样，不要自己算时间。
 */
export function sinceFor(prev: Pick<SnapshotResponse, 'cursor'> | undefined, lastFullAt: number, now: number): string | null {
  if (!prev?.cursor) return null;
  return now - lastFullAt < FULL_EVERY_MS ? prev.cursor : null;
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
