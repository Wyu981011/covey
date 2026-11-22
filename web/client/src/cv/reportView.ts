import type { Lane, Plan, ReportModel, Round } from './reportData';

/** 报告页三块要显示什么，从 buildReport 的结果再算一层（纯函数）：时间轴的窗口、分组和合并的段，预计 vs 实际的结论，token 的结论 */

/** 连着的两轮隔不到这么久算同一段 */
export const MERGE_GAP = 180;
/** 时间轴上“做完”默认只显示最近几个 */
export const DONE_SHOWN = 6;
/** 等你超过这么久才在横线上写字 */
export const WAIT_LABEL = 3600;
/** 明显超出（或提前）：差 10 分钟以上且 20% 以上 */
export const OVER_SEC = 600;
export const OVER_PCT = 0.2;

export interface Seg {
  s: number;
  e: number;
  /** 合进来几轮 */
  k: number;
  live: boolean;
  failed: boolean;
}

export interface Window {
  key: string;
  label: string;
  w0: number;
  w1: number;
}

const DAY = 86400;

function dayStart(v: number): number {
  const d = new Date(v * 1000);
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

/** 可选的时间段：最近 24 小时、全部，跨了几天时每天一个 */
export function windows(t0: number, now: number): Window[] {
  const out: Window[] = [{ key: '24h', label: '最近 24 小时', w0: Math.max(t0, now - DAY), w1: now }];
  if (now - t0 > DAY) {
    const hours: number = Math.round((now - t0) / 3600);
    out.push({ key: 'all', label: `全部 ${hours} 小时`, w0: t0, w1: now });
  }
  const days: number[] = [];
  for (let d = dayStart(t0); d <= now; d += DAY) days.push(d);
  if (days.length > 1) {
    for (const d of days) {
      const date = new Date(d * 1000);
      out.push({ key: `d${d}`, label: `${date.getMonth() + 1}/${date.getDate()}`, w0: Math.max(d, t0), w1: Math.min(d + DAY, now) });
    }
  }
  return out;
}

/** 一个话题的轮次合成段：隔不到 MERGE_GAP 的连着几轮算一段；没做成的单独一段 */
export function segments(rounds: Round[]): Seg[] {
  const out: Seg[] = [];
  for (const r of [...rounds].sort((a, b) => a.s - b.s)) {
    const last: Seg | undefined = out[out.length - 1];
    if (last && r.s - last.e < MERGE_GAP && !r.failed && !last.failed) {
      last.e = Math.max(last.e, r.e);
      last.k += 1;
      last.live = last.live || r.live || r.hold;
    } else {
      out.push({ s: r.s, e: r.e, k: 1, live: r.live || r.hold, failed: r.failed });
    }
  }
  return out;
}

const overlaps = (s: number, e: number, w0: number, w1: number): boolean => e >= w0 && s <= w1;

/** 话题现在在做还是等你（快照里的状态），这类排最上 */
export const isLive = (l: Lane): boolean => l.state === '在做' || l.state === '等你' || l.rounds.some((r: Round) => r.live || r.hold);
/** 没正经跑过：一轮都没有，或者停掉了且每轮都没做成 */
export const isIdle = (l: Lane): boolean => !l.rounds.length || (l.state === '已停止' && l.rounds.every((r: Round) => r.failed));
export const lastAt = (l: Lane): number => Math.max(0, ...l.rounds.map((r: Round) => r.e));

export interface TimelineGroups {
  live: Lane[];
  done: Lane[];
  /** 做完的、这段时间没动静的 */
  older: Lane[];
  idle: Lane[];
}

/** 时间轴的分组：负责人不在里面；在做（含等你）的总在，做完的按最近动静排，窗口里没动静的归“更早做完” */
export function groupLanes(lanes: Lane[], w: Window): TimelineGroups {
  const out: TimelineGroups = { live: [], done: [], older: [], idle: [] };
  for (const l of lanes) {
    if (l.lead) continue;
    if (isIdle(l) && !isLive(l)) out.idle.push(l);
    else if (isLive(l)) out.live.push(l);
    else if (l.rounds.some((r: Round) => overlaps(r.s, r.e, w.w0, w.w1)) || l.waits.some((x) => overlaps(x.s, x.e, w.w0, w.w1))) out.done.push(l);
    else out.older.push(l);
  }
  const recent = (a: Lane, b: Lane): number => lastAt(b) - lastAt(a);
  out.live.sort(recent);
  out.done.sort(recent);
  out.older.sort(recent);
  return out;
}

export interface Overrun {
  plan: Plan;
  lane: Lane;
  d: number;
  pct: number;
  over: boolean;
  under: boolean;
  /** 超得最多的那一轮 */
  worst: Round | null;
  /** 那一轮回答的第一句 */
  why: string;
}

/** 回答开头的第一句：到第一个句号、问号、叹号或换行，去掉 Markdown 记号，最多 60 字 */
export function firstSentence(text: string | null | undefined): string {
  const plain: string = (text ?? '').replace(/[#*`>|]/g, '').replace(/\s+/g, ' ').trim();
  const m: RegExpMatchArray | null = plain.match(/^(.+?[。！？!?])/);
  const one: string = (m ? m[1] : plain.split(/\n/)[0]).trim();
  return one.length > 60 ? `${one.slice(0, 59)}…` : one;
}

export interface PlanSummary {
  rows: Overrun[];
  over: Overrun[];
  under: Overrun[];
  within: Overrun[];
  /** 跑过但一轮都没估出来的话题 */
  never: Lane[];
  overSec: number;
  underSec: number;
}

export function planSummary(model: ReportModel): PlanSummary {
  const byKey = new Map<string, Lane>(model.lanes.map((l: Lane) => [l.key, l]));
  const rows: Overrun[] = [];
  for (const p of model.plans) {
    const lane: Lane | undefined = byKey.get(p.key);
    if (!lane || p.plan <= 0) continue;
    const d: number = p.act - p.plan;
    const pct: number = d / p.plan;
    const est: Round[] = lane.rounds.filter((r: Round) => (r.turn.estimate_seconds ?? 0) > 0);
    const worst: Round | null = est.reduce<Round | null>((a, r) => (!a || r.seconds - (r.turn.estimate_seconds ?? 0) > a.seconds - (a.turn.estimate_seconds ?? 0) ? r : a), null);
    rows.push({ plan: p, lane, d, pct, over: d > OVER_SEC && pct > OVER_PCT, under: -d > OVER_SEC && -pct > OVER_PCT, worst, why: firstSentence(worst?.turn.head) });
  }
  const over: Overrun[] = rows.filter((r) => r.over).sort((a, b) => b.d - a.d);
  const under: Overrun[] = rows.filter((r) => r.under).sort((a, b) => a.d - b.d);
  const within: Overrun[] = rows.filter((r) => !r.over && !r.under);
  const estimated = new Set<string>(rows.map((r) => r.lane.key));
  const never: Lane[] = model.lanes.filter((l: Lane) => !l.lead && l.rounds.length && !isIdle(l) && !estimated.has(l.key)).sort((a, b) => a.label.localeCompare(b.label, 'zh', { numeric: true }));
  return {
    rows,
    over,
    under,
    within,
    never,
    overSec: over.reduce((s: number, r) => s + r.d, 0),
    underSec: -under.reduce((s: number, r) => s + r.d, 0),
  };
}
