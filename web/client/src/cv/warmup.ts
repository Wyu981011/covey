/* 预热话题轮次什么时候开始（P1-9）：话题页、大厅马上开始；记忆中心、设置这类非话题页让出首屏，3 秒后再开始，
 * 免得 24 个话题请求抢在记忆首屏数据前面占满并发连接。 */
export const WARMUP_LATE_MS = 3000;
export const warmupDelay = (pathname: string): number => (/^\/(memory|settings)(\/|$)/u.test(pathname) ? WARMUP_LATE_MS : 0);

/* 首屏预取哪些话题的轮次（T876）。纯函数，单测在 scripts/calib.test.mjs。
 *
 * 以前：要紧的话题（等你、在做、没看过、管家，加最近 8 个，共 24 个）按 updated_at 排好、拼成一个字符串当 effect 的依赖。在做的话题
 * 每推一步 updated_at 就变、顺序就变，字符串一变 effect 重跑，把 24 个里超过 5 秒没取的全再取一遍：现网看板前台 2 分钟 303 个请求里
 * 220 个是它（每 8–10 秒一串 19 个）。
 * 现在：依赖是这组话题的集合（排序后的 key），顺序变了不重跑；重跑时只取缓存里还没有、或取过已超过 WARM_STALE_MS 的。
 * 点进话题时 useTurns 自己按 after 增量补齐，预取只为点进去时马上有东西，不需要常新。 */
import type { SnapshotTopic } from '@shared/api.interface';

/** 预取过的话题多久以后才再预取 */
export const WARM_STALE_MS = 5 * 60 * 1000;
export const WARM_MAX = 24;

/** 要预取的话题 key，要紧的在前：等你、在做、没看过、管家，再加最近的 8 个，共最多 WARM_MAX 个 */
export function warmList(topics: readonly SnapshotTopic[]): string[] {
  const ts: SnapshotTopic[] = [...topics].sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at);
  const hot: SnapshotTopic[] = ts.filter((t: SnapshotTopic) => t.state === '等你' || t.state === '在做' || t.unseen || t.kind === 'butler');
  const rest: SnapshotTopic[] = ts.filter((t: SnapshotTopic) => !hot.includes(t)).slice(0, 8);
  return [...hot, ...rest].slice(0, WARM_MAX).map((t: SnapshotTopic) => t.key);
}

/** effect 的依赖：这组话题的集合（和顺序无关） */
export const warmSig = (keys: readonly string[]): string => [...keys].sort().join(',');

/** 这一个要不要预取：缓存里没有，或上次拿到数据已超过 WARM_STALE_MS（updatedAt 是 react-query 的 dataUpdatedAt，0 是没有） */
export const needsWarm = (updatedAt: number | undefined, now: number): boolean => !updatedAt || now - updatedAt > WARM_STALE_MS;
