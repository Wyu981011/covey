// v26：Covey 推的用量快照（sync_state name='usage' 的 data）里按天的那部分（history）→ /api/usage 的 UsageResponse。
// 纯函数，服务端用，scripts/usage.test.mjs 直接测。
import type { UsageDay, UsageFigures, UsageHarness, UsageResponse, UsageSpan } from './api.interface';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/u;
type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : {});
const list = (v: unknown): Rec[] => (Array.isArray(v) ? v.map(rec) : []);
const count = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);
const text = (v: unknown): string => (typeof v === 'string' ? v : '');

/** 一组数（一天、一段时间）：认不得、负的当 0 */
function figures(x: Rec): UsageFigures {
  return {
    tasks: count(x.tasks), topics: count(x.topics), tokens: count(x.tokens), input: count(x.input), cache: count(x.cache),
    output: count(x.output), untracked: count(x.untracked),
  };
}

/** 快照 → 用量页；没有 history（旧 Covey）或一天都没有是 null */
export function usageFromSnapshot(u: unknown): UsageResponse | null {
  const top: Rec = rec(u);
  const h: Rec = rec(top.history);
  const days: UsageDay[] = list(h.days).filter((x: Rec) => DATE_RE.test(text(x.date)))
    .map((x: Rec): UsageDay => ({ date: text(x.date), ...figures(x) }));
  if (!days.length) return null;
  const spans: UsageSpan[] = list(h.spans).filter((x: Rec) => count(x.days) > 0).map((x: Rec): UsageSpan => ({
    days: count(x.days), since: DATE_RE.test(text(x.since)) ? text(x.since) : '', ...figures(x),
    harnesses: list(x.harnesses).map((y: Rec): UsageHarness => ({
      title: text(y.title), tasks: count(y.tasks), tokens: count(y.tokens), input: count(y.input), cache: count(y.cache), untracked: count(y.untracked),
    })),
  }));
  const first: string = text(h.first);
  return { at: typeof top.at === 'number' ? top.at : null, days, spans, first: DATE_RE.test(first) ? first : null };
}
