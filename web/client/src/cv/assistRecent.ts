/** 设置页「辅助模型」下面的“后台活最近一次”（T884）：每个后台功能最近一次用了谁、成没成、原因、耗时、什么时候。纯函数（npm run test:assist） */
import type { SettingsAssistRecent } from '@shared/api.interface';
import { ago } from './topicText';

/** 没调模型的原因（core/assist.py NOT_ASKED）：设置里选了不用、选的用不了、刚失败过、被冷却 */
const NOT_ASKED: Set<string> = new Set(['none', 'not_allowed', 'no_backend', 'broken', 'cooling', 'refusal_gate', 'not_one_shot', 'unusable', 'not_enabled']);

/** ok 成了；bad 调了没成（红字）；off 没调模型（灰字） */
export type RecentTone = 'ok' | 'bad' | 'off';

export interface RecentLine {
  key: string;
  /** 功能 */
  feature: string;
  /** 用了谁：Harness · 模型；没问到谁是 — */
  who: string;
  /** 结果 */
  result: string;
  tone: RecentTone;
  /** 原因（成功是空串） */
  why: string;
  /** 耗时 */
  took: string;
  /** 时间（“3 分钟前”，主人点的加“· 你点的”） */
  when: string;
}

export function tookWords(ms: number): string {
  if (!ms || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} 毫秒`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} 秒`;
}

export function recentLine(r: SettingsAssistRecent, now: number): RecentLine {
  const notAsked: boolean = !r.ok && NOT_ASKED.has(r.code);
  return {
    key: r.feature,
    feature: r.label,
    who: r.name ? `${r.name}${r.model ? ` · ${r.model}` : ''}` : '—',
    result: r.ok ? '成功' : notAsked ? '没调模型' : '没成',
    tone: r.ok ? 'ok' : notAsked ? 'off' : 'bad',
    why: r.ok ? '' : r.words,
    took: notAsked ? '—' : tookWords(r.ms),
    when: `${ago(r.at, now) || '—'}${r.manual ? ' · 你点的' : ''}`,
  };
}

export const recentLines = (rows: readonly SettingsAssistRecent[] | undefined, now: number): RecentLine[] =>
  (rows ?? []).map((r: SettingsAssistRecent) => recentLine(r, now));
