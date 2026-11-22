/** 整理专项的建议：类型来自共享接口（v16），这里是网页自己的词和看板面板的纯函数（npm run test:tidy） */
import type { TidyData, TidyKind, TidyProposal } from '@shared/api.interface';
export type { TidyKind, TidyState, TidyTopic, TidyProposal, TidyData } from '@shared/api.interface';

/** 已定的建议，Covey 没给 note 时的兜底词 */
export const TIDY_WORD: Record<string, string> = { done: '已照办', declined: '不用', failed: '没做成', expired: '已过时', never: '以后不再提议' };

/** 话题多于这个数就折叠：先列前 3 个，其余折成“还有 N 个话题” */
export const TIDY_SHOW_ALL = 4;

/** 定好的那一行末尾的结果词：照办了按种类说做成了什么，其余按状态 */
const DONE_WORD: Record<TidyKind, string> = { create: '已建', split: '已拆出', merge: '已合并', join: '已归进', leave: '已移出', rename: '已改名', fold: '已收起' };
const STATE_WORD: Record<string, string> = { declined: '不用', never: '不再提议', failed: '没做成', expired: '已过时' };

/** ok 照办了；bad 没做成（红字，要你看一眼）；off 不用、过时 */
export type TidyTone = 'ok' | 'bad' | 'off';
export function outcome(p: Pick<TidyProposal, 'kind' | 'state'>): { word: string; tone: TidyTone } {
  if (p.state === 'done') return { word: DONE_WORD[p.kind] ?? TIDY_WORD.done, tone: 'ok' };
  if (p.state === 'failed') return { word: STATE_WORD.failed, tone: 'bad' };
  return { word: STATE_WORD[p.state] ?? TIDY_WORD[p.state] ?? '', tone: 'off' };
}

/** 一条建议此刻的样子：id 加状态。点「知道了」记下当时全部的样子；出现没记过的（新建议、状态变了）面板再出来 */
export const mark = (p: Pick<TidyProposal, 'id' | 'state'>): string => `${p.id}:${p.state}`;

export interface TidyLook {
  /** 要你定的，Covey 的顺序 */
  open: TidyProposal[];
  /** 定好了的（照办、不用、没做成、过时） */
  settled: TidyProposal[];
  /** 定好了的里没做成几条 */
  failed: number;
  /** 要你定的是哪几条：收起记在这一批名下，来了新的再展开 */
  batch: string;
  marks: string[];
  running: { done: number; total: number } | null;
}

export function look(d: TidyData): TidyLook {
  const open: TidyProposal[] = d.proposals.filter((p: TidyProposal) => p.state === 'open');
  const settled: TidyProposal[] = d.proposals.filter((p: TidyProposal) => p.state !== 'open');
  return {
    open,
    settled,
    failed: settled.filter((p: TidyProposal) => p.state === 'failed').length,
    batch: open.map((p: TidyProposal) => p.id).sort().join(','),
    marks: d.proposals.map(mark),
    running: d.running ?? null,
  };
}

/** 面板画不画：一条建议都没有不画（正在整理的进度在「整理」按钮旁）；有要你定的总是画；都定好了的，点过「知道了」、
    没在整理、也没有新样子就不画 */
export function shown(l: TidyLook, gone: readonly string[]): boolean {
  if (l.open.length) return true;
  if (!l.settled.length) return false;
  if (l.running) return true;
  const seen = new Set<string>(gone);
  return l.marks.some((m: string) => !seen.has(m));
}

/** 有没有要你定的不在 ids 里（ids：你点收起时要你定的那几条） */
const fresh = (l: TidyLook, ids: readonly string[]): boolean => l.open.some((p: TidyProposal) => !ids.includes(p.id));

/** 一进看板是展开还是收成一行：要你定的展开，除非你点收起时它们都已经在了（folded：那时的 batch；其中有的后来定掉了也还是
    收着）；都定好了、只在整理时收成一行 */
export function startOpen(l: TidyLook, folded: string): boolean {
  return fresh(l, folded ? folded.split(',') : []);
}

/** 这次进看板以后你点过的：展开或收起，和那时要你定的是哪几条 */
export interface TidyChoice {
  open: boolean;
  ids: string[];
}
export const choice = (l: TidyLook, open: boolean): TidyChoice => ({ open, ids: l.open.map((p: TidyProposal) => p.id) });

/** 现在展开吗：这次没点过就照 startOpen；点过展开（或在这里定过一条）的一直展开，定完最后一条也不突然收起；点过收起的，
    来了没见过的要你定的再展开 */
export function isOpen(l: TidyLook, picked: TidyChoice | null, folded: string): boolean {
  if (!picked) return startOpen(l, folded);
  return picked.open || fresh(l, picked.ids);
}

/** 「知道了」记下的样子：这次的全部，加上以前记过的（最多 MARKS_KEPT 条，新的在前） */
export const MARKS_KEPT = 200;
export function remember(l: TidyLook, gone: readonly string[]): string[] {
  return [...new Set<string>([...l.marks, ...gone])].slice(0, MARKS_KEPT);
}

export const runWords = (r: { done: number; total: number }): string => `正在整理（${r.done}/${r.total}）`;

export interface TidyWords {
  /** 要你定 N 条、都定好了，或只在整理时的进度 */
  state: string;
  /** 收成一行时：第一条的标题 */
  head: string;
  /** 收成一行时：“等 N 条”（定好了的才说，要你定的条数已在 state 里） */
  more: string;
  /** 收成一行、手机上不写标题时：定好了几条（“5 条”） */
  count: string;
  /** 正在整理的进度（不是 state 时） */
  run: string;
  /** 都定好了时没做成几条：红字，要你看一眼 */
  failed: string;
}

/** 面板说什么：收成一行时整句都用，展开时标题栏用 state、run、failed */
export function panelWords(l: TidyLook): TidyWords {
  const asking: boolean = l.open.length > 0;
  const list: TidyProposal[] = asking ? l.open : l.settled;
  const run: string = l.running ? runWords(l.running) : '';
  if (!list.length) return { state: run, head: '', more: '', count: '', run: '', failed: '' };
  return {
    state: asking ? `要你定 ${list.length} 条` : '都定好了',
    head: list[0].headline,
    more: !asking && list.length > 1 ? `等 ${list.length} 条` : '',
    count: asking ? '' : `${list.length} 条`,
    run,
    failed: !asking && l.failed ? `${l.failed} 条没做成` : '',
  };
}

/** 「知道了」能不能点：都定好了、没在整理 */
export const dismissible = (l: TidyLook): boolean => !l.open.length && !l.running && l.settled.length > 0;
