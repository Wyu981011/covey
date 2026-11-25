import type { SnapshotTopic, StepView, TurnView } from '@shared/api.interface';

import { STATES, TONE_KEYS, type ToneKey } from './look.gen';

export type { ToneKey } from './look.gen';

/** v4 及更早的数据没有 tone，只有中文 state：只在这里换一次，别处一律看 tone */
const V4_STATE: Record<string, ToneKey> = { 等你: 'waiting', 在做: 'running', 失败: 'stopped', 已停止: 'cancelled', 空闲: 'idle' };

/** 话题此刻的状态（数据约定 v5 的 tone，core/look.py STATES 的 key） */
export function toneOf(t: Pick<SnapshotTopic, 'state' | 'unseen'> & { tone?: string | null }): ToneKey {
  if (t.tone && (TONE_KEYS as readonly string[]).includes(t.tone)) return t.tone as ToneKey;
  if (t.state === '做完') return t.unseen ? 'result' : 'done';
  return V4_STATE[t.state] ?? 'idle';
}
export const toneWord = (k: ToneKey): string => STATES[k].word;
/** 在跑（含可能卡住） */
export const isRunningTone = (k: ToneKey): boolean => k === 'running' || k === 'stuck';
export const isWaiting = (t: Parameters<typeof toneOf>[0]): boolean => toneOf(t) === 'waiting';
export const isRunning = (t: Parameters<typeof toneOf>[0]): boolean => isRunningTone(toneOf(t));
/** 旧样式的短类名（.gn.run、.a-chip.wait 这类）：网页里老组件的 CSS 还按它写 */
export function legacyCls(k: ToneKey): 'wait' | 'run' | 'done' | 'fail' | 'stop' {
  if (k === 'waiting' || k === 'stuck') return 'wait';
  if (k === 'running') return 'run';
  if (k === 'stopped') return 'fail';
  if (k === 'result') return 'done';
  return 'stop';
}
/** 排序用：要你处理的在前（look 的 PRESSING），其余按背景 */
export const TONE_RANK: Record<ToneKey, number> = { waiting: 0, stopped: 1, stuck: 1, running: 2, result: 3, queued: 4, done: 5, cancelled: 6, idle: 7 };
/** 做完了（看过没看过都算） */
export const isFinished = (t: Parameters<typeof toneOf>[0]): boolean => ['result', 'done'].includes(toneOf(t));

export const harnessKind = (h: string): 'cx' | 'cl' => (/codex/iu.test(h) ? 'cx' : 'cl');
export const harnessName = (h: string): string => (h ? (/codex/iu.test(h) ? 'Codex' : /claude/iu.test(h) ? 'Claude Code' : h) : '');
/** “Claude Code · Opus 5.5”：模型用 Covey 推的可读名（v7 model_name），旧数据没有时才用原值 */
export const engineText = (t: { harness?: string; model?: string; model_name?: string } | null | undefined): string =>
  t ? [harnessName(t.harness ?? ''), t.model_name ?? t.model ?? ''].filter(Boolean).join(' · ') : '';

/** 秒 → “18 分 52 秒”“1 小时 13 分” */
export function fmtDur(sec: number | null | undefined, withSec = true): string {
  if (sec === null || sec === undefined || !Number.isFinite(sec)) return '—';
  const s: number = Math.max(0, Math.round(sec));
  const h: number = Math.floor(s / 3600);
  const m: number = Math.floor((s % 3600) / 60);
  const r: number = s % 60;
  if (h > 0) return `${h} 小时 ${m} 分`;
  if (m > 0) return withSec ? `${m} 分 ${String(r).padStart(2, '0')} 秒` : `${m} 分`;
  return `${r} 秒`;
}
/** 一步的时长，短写：0.4 秒 / 12 秒 / 6 分 / 1 小时 5 分（ui.md 第 7 节：中文单位，数字和单位之间留空格） */
export function fmtShort(sec: number): string {
  const s: number = Math.max(0, sec);
  if (s < 10) return `${s.toFixed(1)} 秒`;
  if (s < 60) return `${Math.round(s)} 秒`;
  if (s < 3600) return `${Math.round(s / 60)} 分`;
  const m: number = Math.round(s / 60);
  return m % 60 ? `${Math.floor(m / 60)} 小时 ${m % 60} 分` : `${m / 60} 小时`;
}
export function fmtTok(n: number | null | undefined): string {
  if (!n) return '0';
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e8 ? 0 : 1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}K`;
  return String(Math.round(n));
}
export const hhmm = (sec: number | null | undefined): string => {
  if (!sec) return '';
  return new Date(sec * 1000).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' });
};
export const nowSec = (): number => Date.now() / 1000;

/** 今天写 23:10，不是今天写 11-17 23:10（docs/ui.md 第 7 节） */
export function shortWhen(sec: number | null | undefined, now: number = nowSec()): string {
  if (!sec) return '';
  const day = (x: number): string => new Date(x * 1000).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).replace(/\//gu, '-');
  return day(sec) === day(now) ? hhmm(sec) : `${day(sec)} ${hhmm(sec)}`;
}

/** 网页超过这么久没收到 Covey 的同步，就说“N 分钟没同步”（docs/ui.md 第 7 节：3 分钟，灰字，不用橙色） */
export const STALE_MS = 3 * 60 * 1000;
/** Covey 停推的那句灰字：同步在 3 分钟内是空串；“5 分钟没同步”“2 小时没同步”“3 天没同步”；从没同步过是“还没同步” */
export function staleWords(at: string | number | null | undefined, nowMs: number = Date.now()): string {
  if (at === null || at === undefined || at === '') return '还没同步';
  const t: number = typeof at === 'number' ? (at < 1e12 ? at * 1000 : at) : Date.parse(at);
  if (!Number.isFinite(t)) return '还没同步';
  const age: number = nowMs - t;
  if (age <= STALE_MS) return '';
  const m: number = Math.floor(age / 60000);
  if (m < 60) return `${m} 分钟没同步`;
  if (m < 48 * 60) return `${Math.floor(m / 60)} 小时没同步`;
  return `${Math.floor(m / 1440)} 天没同步`;
}

export function waitText(sec: number): string {
  const m: number = Math.max(1, Math.round(sec / 60));
  if (m >= 24 * 60) return `${Math.floor(m / 1440)} 天 ${Math.floor((m % 1440) / 60)} 小时`;
  return m >= 60 ? `${Math.floor(m / 60)} 小时 ${m % 60} 分钟` : `${m} 分钟`;
}

export const STEP_CLS: Record<string, string> = {
  read: 'read', search: 'read', edit: 'write', command: 'bash', subagent: 'sub', think: 'think', web: 'web', other: '',
};
export const STEP_VERB: Record<string, string> = {
  read: '读', search: '搜', edit: '改', command: '跑', subagent: '子代理', think: '思考', web: '查网页', other: '',
};

/** 一轮的“工具 N · 思考 N” */
export function turnStats(t: TurnView): { tools: number; thinks: number; seconds: number | null } | null {
  if (!t.steps || !t.steps.length) return null;
  const thinks: number = t.steps.filter((s: StepView) => s.kind === 'think').length;
  const seconds: number | null = t.seconds ?? (t.started_at && t.ended_at ? t.ended_at - t.started_at : null);
  return { tools: t.steps.length - thinks, thinks, seconds };
}

export const isLive = (t: SnapshotTopic): boolean => isRunning(t);

/** 在做 / 等你 在前，其余按最近 */
type Ord = { updated_at: number; number: number | null; key: string };
const tie = (a: Ord, b: Ord): number => (b.number ?? 0) - (a.number ?? 0) || a.key.localeCompare(b.key);
/** 侧栏稳定排序。等你：问得最早的在前（不会随同步抖）；在做：编号大的在前（在做的话题每次同步 updated_at 都变，不能拿它排）；其余：最近活动在前，同秒按编号、再按 key */
export const byAsked = (a: Ord, b: Ord): number => a.updated_at - b.updated_at || tie(a, b);
export const byNumberDesc = (a: Ord, b: Ord): number => tie(a, b);
export const byRecent = (a: Ord, b: Ord): number => b.updated_at - a.updated_at || tie(a, b);
/** 侧栏排专项先后用的“最近活动”（T779）：在跑的（含可能卡住）不算，它的 updated_at 每次同步都变，拿它排，几个都有话题在跑的专项会整块来回换位 */
export const steadyAt = (t: SnapshotTopic): number => (isRunning(t) ? 0 : t.updated_at);

/** 上下文窗口：limit 为 0 或缺失时没有窗口，不能算百分比 */
export const ctxLimitOk = (c: { limit: number } | null | undefined): boolean => !!c && Number.isFinite(c.limit) && c.limit > 0;
export const fmtWindow = (limit: number): string => (limit >= 1e6 ? `${limit / 1e6}M` : `${Math.round(limit / 1000)}K`);

export const byUpdated = (a: { updated_at: number }, b: { updated_at: number }): number => b.updated_at - a.updated_at;

export function topicHref(t: { key: string; project_key: string | null; kind?: string }): string {
  if (t.kind === 'butler') return '/butler';
  return `/topics/${encodeURIComponent(t.key)}`;
}

/** 搜索词是不是一个 T 号（T514、t 514）：是就给出编号 */
export function topicNumberOf(q: string): number | null {
  const m: RegExpMatchArray | null = /^\s*[tT]\s*(\d{1,6})\s*$/u.exec(q);
  return m ? Number(m[1]) : null;
}

/** 以前只记在这台浏览器上的「先放着」（covey.later，一列轮次 key）。T647 P1-C3 起并成会告诉 Covey 的「不管了」，
 * 这份不再读：打开页面时删掉，免得旧缓存悄悄把话题从要你处理里藏起来 */
export const LEGACY_KEYS: readonly string[] = ['covey.later'];
export function dropLegacy(storage: Pick<Storage, 'getItem' | 'removeItem'> | null | undefined): string[] {
  const gone: string[] = [];
  if (!storage) return gone;
  for (const k of LEGACY_KEYS) {
    try {
      if (storage.getItem(k) !== null) {
        storage.removeItem(k);
        gone.push(k);
      }
    } catch {
      /* 隐私模式：读写都可能抛 */
    }
  }
  return gone;
}

/** 开着看板（Covey 推话题的 board，v6）：只有这时「不管了」才有用（Covey 把话题从看板拿掉，要你处理跟着少一件） */
export const boardOn = (topics: readonly { board?: string }[]): boolean => topics.some((t: { board?: string }) => typeof t.board === 'string');

/** 本地偏好 */
export function pref(name: string, fallback: string): string {
  try {
    return window.localStorage.getItem(`covey.${name}`) ?? fallback;
  } catch {
    return fallback;
  }
}
export function setPref(name: string, v: string): void {
  try {
    window.localStorage.setItem(`covey.${name}`, v);
  } catch {
    /* 隐私模式 */
  }
}
