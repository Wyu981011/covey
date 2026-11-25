/* 专项的「简报」标签（v40，docs/web.md 专项条目）：背景、目标、动作（每个动作下面是它对应的话题）、任务图、session 的位置和影响、右栏。
 * 全是纯函数，不碰页面，全在网页上现算：动作的状态、“自动”那一行、位置和影响都不存、不进提示词。
 *
 * 动作状态的规则（和 Covey core/project_actions.py state 一套，按顺序判断）：
 *   条目的下一步在主人手上，或有话题在等主人 → 等你；有话题在跑 → 在做；条目都满足 → 做完；
 *   条目没满足、话题都结束了 → 待核对；还没有话题 → 将要做。
 * 动作没有条目时不算“做完”：话题都结束了是待核对，还没有话题是将要做。 */
import type { BriefAction, ChecklistItem, ProjectGap, SnapshotProject, SnapshotResponse, SnapshotTopic } from '@shared/api.interface';
import { STATES, type ToneKey } from './look.gen';
import { isRunningTone, shortWhen, toneOf } from './lib';
import { byId, cut, isMet, ownerWaits, topicNow } from './progressData';

/* ---- 动作状态 ---- */
export type ActState = 'owner' | 'doing' | 'check' | 'done' | 'next';
/** 词用状态词表的说法（docs/ui.md：不用“已完成”“完成”）；待核对和将要做是简报自己的词 */
export const ACT_WORD: Record<ActState, string> = { owner: '等你', doing: '在做', check: '待核对', done: '做完', next: '将要做' };
export const ACT_ICON: Record<ActState, string> = { owner: '!', doing: '▶', check: '◐', done: '✓', next: '○' };
/** 样式类后缀（brief.css 的 .pb-s-*） */
export const ACT_CLS: Record<ActState, string> = { owner: 'wait', doing: 'run', check: 'check', done: 'done', next: 'next' };
/** 统计和分段条里的顺序：要紧的在前 */
export const ACT_ORDER: readonly ActState[] = ['owner', 'doing', 'check', 'next', 'done'];

/** 话题一行的图标、样式类（同样稿的 TONE） */
export const TONE_ICON: Record<ToneKey, string> = { waiting: '!', stopped: '⚠', stuck: '⚠', result: '✓', running: '▶', queued: '⋯', done: '✓', cancelled: '■', idle: '○' };
export const TONE_CLS: Record<ToneKey, string> = { waiting: 'wait', stopped: 'stop', stuck: 'wait', result: 'done', running: 'run', queued: 'next', done: 'done', cancelled: 'next', idle: 'next' };
export const toneWordOf = (t: SnapshotTopic): string => STATES[toneOf(t)].word;

/* ---- 一条检查表条目此刻的样子 ---- */
export type ItemKind = 'done' | 'wait' | 'stop' | 'next' | 'gone';
export const ITEM_ICON: Record<ItemKind, string> = { done: '✓', wait: '!', stop: '⏸', next: '○', gone: '–' };
export const ITEM_WORD: Record<ItemKind, string> = { done: '满足', wait: '等你', stop: '卡住', next: '没满足', gone: '不做了' };
export function itemKind(it: ChecklistItem): ItemKind {
  if (it.state === 'dropped') return 'gone';
  if (it.state === 'done') return 'done';
  if (ownerWaits(it)) return 'wait';
  return it.state === 'blocked' ? 'stop' : 'next';
}
/** 页面和任务图上叫它的名字：负责人写的短标题，没有就用完成标准 */
export const itemName = (it: ChecklistItem): string => it.title || it.criterion;

/* ---- 话题身上读出来的几样（Bridge 垫的阶段不是模型写的，不给人看，同 docs/ui.md 停住的卡） ---- */
const PLACEHOLDER: readonly string[] = ['准备处理本轮请求', '检查任务要求与已有状态', '尚无记录'];
const clean = (s: string | undefined): string => (s ?? '').replace(/\s+/gu, ' ').trim();
export const phaseOf = (t: SnapshotTopic): string => {
  const p: string = clean(t.progress?.phase);
  return PLACEHOLDER.includes(p) ? '' : p;
};
export const nextStepOf = (t: SnapshotTopic): string => {
  const n: string = clean(t.progress?.next_step);
  return !n || PLACEHOLDER.includes(n) || n.startsWith('无') ? '' : n;
};
/** 话题此刻在等主人：状态是等你、有题没答、或检查点写了 requires_user */
export const waitsOwner = (t: SnapshotTopic, asked: ReadonlySet<string>): boolean => toneOf(t) === 'waiting' || asked.has(t.key) || !!clean(t.progress?.waiting);
/** 话题在跑（含可能卡住）或排着队 */
export const isDoing = (t: SnapshotTopic): boolean => isRunningTone(toneOf(t)) || toneOf(t) === 'queued';
/** 话题没结束：在跑、排队或在等主人 */
const isLive = (t: SnapshotTopic, asked: ReadonlySet<string>): boolean => isDoing(t) || waitsOwner(t, asked);
/** 第几步：在跑的带那一步的标题，别的只写第几步（网页拿不到结束话题的步骤标题） */
export function stepLine(t: SnapshotTopic): string {
  const now = topicNow(t);
  if (!now.total) return '';
  const doing: string = isDoing(t) ? clean(t.running?.plan_doing) : '';
  return `第 ${now.done}/${now.total} 步${doing ? `「${cut(doing, 18)}」` : ''}`;
}
/** 最后结论：话题最新一轮是它自己答的、已经结束时那一句（≤120 字），不用在跑那一轮中途的话 */
export const lastWord = (t: SnapshotTopic): string => (t.latest_role !== 'owner' && t.latest_status !== 'running' ? clean(t.latest) : '');

/* ---- 一个专项的简报 ---- */
export interface BriefCtx {
  items: Map<string, ChecklistItem>;
  /** 谁在等它（needs 反查） */
  rev: Map<string, string[]>;
  topics: Map<string, SnapshotTopic>;
  asked: ReadonlySet<string>;
  /** 话题引用（key 或 T 号）换成 key；网页上没有的原样返回 */
  keyOf: (ref: string) => string;
}

export interface ActionView {
  action: BriefAction;
  /** 动作号：id 里的数字（a3 是 3）。id 不复用，所以和负责人嘴里的“动作 3”一直对得上；挪走 dropped 的以后号码也不重排 */
  n: number;
  state: ActState;
  items: ChecklistItem[];
  unmet: ChecklistItem[];
  met: number;
  /** 网页上找得到的话题：没结束的在前，其余新的在前 */
  topics: SnapshotTopic[];
  /** 报缺口的话题在这个动作里的缺口 */
  gaps: ProjectGap[];
  /** 程序写的一句：哪个话题在动、哪条没满足 */
  auto: string;
}

export interface OwnerRow {
  kind: 'item' | 'topic';
  /** 所在动作号，没挂动作是 0 */
  n: number;
  item?: ChecklistItem;
  topic?: SnapshotTopic;
  /** 要你做什么：条目的缺口，话题在等的那道题 */
  text: string;
}
export interface FeedRow {
  at: number;
  who: 'auto' | 'lead';
  topic?: SnapshotTopic;
  text: string;
}

export interface Brief {
  /** 负责人写了背景或动作（没有就退回第一期的三栏） */
  has: boolean;
  background: string;
  goal: string;
  /** 没 dropped 的动作，按 id 的数字排 */
  actions: ActionView[];
  counts: Record<ActState, number>;
  /** 本专项的话题 */
  members: SnapshotTopic[];
  liveN: number;
  met: number;
  total: number;
  /** 本专项里没挂到任何检查表条目上的话题 */
  unmapped: SnapshotTopic[];
  /** 没挂到任何动作的缺口 */
  strayGaps: ProjectGap[];
  /** 负责人最后改动作的时刻，没有是 0 */
  changedAt: number;
  owner: OwnerRow[];
  feed: FeedRow[];
  graph: BriefGraph;
  ctx: BriefCtx;
  /** 话题 key → 它交付、参与的条目 id（topic 和 topics 里的，按 id 排） */
  deliver: Map<string, string[]>;
  /** 话题 key → 它挂在哪些动作上 */
  byTopic: Map<string, ActionView[]>;
}

const numOf = (id: string): number => Number(id.slice(1)) || 0;
const uniq = <T>(list: readonly T[]): T[] => [...new Set(list)];

/** 一条的话题引用：topic 是主要的，topics 是参与的（去重，同 Covey topics_of） */
export const topicRefs = (it: Pick<ChecklistItem, 'topic' | 'topics'>): string[] => uniq([it.topic, ...(it.topics ?? [])].filter(Boolean));

export function briefCtx(list: readonly ChecklistItem[] | undefined, snap: Pick<SnapshotResponse, 'topics' | 'questions'>): BriefCtx {
  const items = new Map<string, ChecklistItem>((list ?? []).map((it: ChecklistItem) => [it.id, it]));
  const rev = new Map<string, string[]>();
  for (const it of items.values()) {
    for (const n of it.needs) if (items.has(n) && n !== it.id) rev.set(n, [...(rev.get(n) ?? []), it.id]);
  }
  for (const [k, v] of rev) rev.set(k, v.sort(byId));
  const topics = new Map<string, SnapshotTopic>();
  const byNumber = new Map<number, string>();
  for (const t of snap.topics) {
    if (t.kind !== 'topic') continue;
    topics.set(t.key, t);
    if (t.number) byNumber.set(t.number, t.key);
  }
  const keyOf = (ref: string): string => {
    if (topics.has(ref)) return ref;
    const m: RegExpExecArray | null = /^[Tt]?(\d{1,6})$/u.exec(ref.trim());
    return (m && byNumber.get(Number(m[1]))) || ref;
  };
  return { items, rev, topics, asked: new Set<string>(snap.questions.map((q: { topic_key: string }) => q.topic_key)), keyOf };
}

/** 动作的状态（规则见文件头） */
export function actionState(its: readonly ChecklistItem[], ses: readonly SnapshotTopic[], asked: ReadonlySet<string>): ActState {
  if (its.some((it: ChecklistItem) => !isMet(it.state) && ownerWaits(it)) || ses.some((t: SnapshotTopic) => waitsOwner(t, asked))) return 'owner';
  if (ses.some(isDoing)) return 'doing';
  if (its.length && its.every((it: ChecklistItem) => isMet(it.state))) return 'done';
  return ses.length ? 'check' : 'next';
}

/** 程序写的一句：哪个话题在动（第几步），或最近哪个话题几点做了什么；哪几条没满足；话题都结束了时请负责人核对 */
export function autoLine(state: ActState, its: readonly ChecklistItem[], ses: readonly SnapshotTopic[], asked: ReadonlySet<string>, now: number): string {
  const byNew: SnapshotTopic[] = [...ses].sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at);
  const live: SnapshotTopic[] = byNew.filter((t: SnapshotTopic) => isLive(t, asked));
  const parts: string[] = live.map((t: SnapshotTopic) => {
    const now2 = topicNow(t);
    return `T${t.number} ${waitsOwner(t, asked) ? STATES.waiting.word : toneWordOf(t)}${now2.total ? ` 第 ${now2.done}/${now2.total} 步` : ''}`;
  });
  if (!live.length && byNew.length) parts.push(`最近 T${byNew[0].number} ${shortWhen(byNew[0].updated_at, now)} ${toneWordOf(byNew[0])}`);
  const unmet: ChecklistItem[] = its.filter((it: ChecklistItem) => !isMet(it.state));
  if (unmet.length) parts.push(`还没满足 ${unmet.map((it: ChecklistItem) => `${it.id}${itemKind(it) === 'wait' ? '（等你）' : itemKind(it) === 'stop' ? '（卡住）' : ''}`).join('、')}`);
  else if (its.length) parts.push(`检查表 ${its.length} 条都满足`);
  if (state === 'check') parts.push('话题都结束了，等负责人核对');
  return parts.join(' · ');
}

/** 一个动作下面显示哪些话题：没结束的都显示，再补到最近 2 个；其余收成一排 T 号。做完的动作只留 T 号 */
export function sessionsOf(v: ActionView, asked: ReadonlySet<string>): { shown: SnapshotTopic[]; rest: SnapshotTopic[] } {
  if (v.state === 'done') return { shown: [], rest: v.topics };
  const shown: SnapshotTopic[] = v.topics.filter((t: SnapshotTopic) => isLive(t, asked));
  const others: SnapshotTopic[] = v.topics.filter((t: SnapshotTopic) => !shown.includes(t));
  shown.push(...others.slice(0, Math.max(0, 2 - shown.length)));
  return { shown, rest: v.topics.filter((t: SnapshotTopic) => !shown.includes(t)) };
}
/** 更早的几个话题按状态数一数：“做完 4、停住了 1” */
export function restWords(rest: readonly SnapshotTopic[]): string {
  const n = new Map<string, number>();
  for (const t of rest) n.set(toneWordOf(t), (n.get(toneWordOf(t)) ?? 0) + 1);
  return [...n].map(([k, v]: [string, number]) => `${k} ${v}`).join('、');
}

/** 按宽度截（中文算 2、其余算 1）：SVG 的字没有 CSS 省略号；全文在 title 里 */
export function fitText(s: string, units: number): string {
  let used = 0;
  let out = '';
  for (const ch of Array.from(s)) {
    used += (ch.codePointAt(0) ?? 0) > 0xff ? 2 : 1;
    if (used > units) return `${out}…`;
    out += ch;
  }
  return out;
}

/* ---- 任务图：一个动作一行，有依赖的条目按先后从左往右，没依赖的填空格；防环；没挂动作的条目单独一行 ---- */
export const GBOX = { LW: 176, NW: 156, NH: 30, XG: 22, YG: 8, LP: 8 } as const;
export interface GNode {
  id: string;
  x: number;
  y: number;
}
export interface GLane {
  /** 动作 id，没挂动作的那一行是空串 */
  id: string;
  y: number;
  h: number;
}
export interface GEdge {
  from: string;
  to: string;
}
export interface BriefGraph {
  nodes: GNode[];
  edges: GEdge[];
  lanes: GLane[];
  cols: number;
  width: number;
  height: number;
}

export function graphOf(items: ReadonlyMap<string, ChecklistItem>, lanesIn: readonly { id: string; items: readonly string[] }[]): BriefGraph {
  const { LW, NW, NH, XG, YG, LP } = GBOX;
  const needsOf = (c: string): string[] => (items.get(c)?.needs ?? []).filter((n: string) => items.has(n) && n !== c);
  const edges: GEdge[] = [];
  for (const c of items.keys()) for (const n of needsOf(c)) edges.push({ from: n, to: c });
  const linked = new Set<string>(edges.flatMap((e: GEdge) => [e.from, e.to]));
  // 深度：最长的前置链。正在算的又被走到就是成环，当 0，不再往下走
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const dep = (c: string): number => {
    const known: number | undefined = depth.get(c);
    if (known !== undefined) return known;
    if (visiting.has(c)) return 0;
    visiting.add(c);
    const d: number = Math.max(0, ...needsOf(c).map((n: string) => dep(n) + 1));
    visiting.delete(c);
    depth.set(c, d);
    return d;
  };
  for (const c of items.keys()) dep(c);
  const cols: number = Math.max(4, ...[...depth.values()].map((d: number) => d + 1));
  // 每个条目只画一次：在第一个包含它的动作那一行；不在任何动作里的放最后一行
  const placed = new Set<string>();
  const lanes: { id: string; cs: string[] }[] = lanesIn.map((l) => {
    const cs: string[] = l.items.filter((c: string) => items.has(c) && !placed.has(c));
    cs.forEach((c: string) => placed.add(c));
    return { id: l.id, cs };
  });
  const loose: string[] = [...items.keys()].filter((c: string) => !placed.has(c));
  if (loose.length) lanes.push({ id: '', cs: loose });
  const nodes: GNode[] = [];
  const box: GLane[] = [];
  let y: number = LP;
  for (const lane of lanes) {
    const cells = new Set<string>();
    const spot = new Map<string, [number, number]>();
    for (const c of lane.cs.filter((x: string) => linked.has(x)).sort((a: string, b: string) => (depth.get(a) ?? 0) - (depth.get(b) ?? 0) || byId(a, b))) {
      const col: number = depth.get(c) ?? 0;
      let r = 0;
      while (cells.has(`${r},${col}`)) r += 1;
      cells.add(`${r},${col}`);
      spot.set(c, [col, r]);
    }
    // 没有依赖的条目填空格：逐行从左到右
    for (const c of lane.cs.filter((x: string) => !linked.has(x)).sort(byId)) {
      let r = 0;
      while (Array.from({ length: cols }, (_, k: number) => k).every((k: number) => cells.has(`${r},${k}`))) r += 1;
      const col: number = Array.from({ length: cols }, (_, k: number) => k).find((k: number) => !cells.has(`${r},${k}`)) as number;
      cells.add(`${r},${col}`);
      spot.set(c, [col, r]);
    }
    const rows: number = Math.max(0, ...[...spot.values()].map(([, r]: [number, number]) => r)) + 1;
    for (const [c, [col, r]] of spot) nodes.push({ id: c, x: LW + col * (NW + XG), y: y + r * (NH + YG) });
    box.push({ id: lane.id, y, h: rows * (NH + YG) - YG });
    y += rows * (NH + YG) - YG + LP * 2;
  }
  return { nodes, edges, lanes: box, cols, width: LW + cols * (NW + XG) - XG + 4, height: y - LP };
}

/* ---- 选中一个话题：它交付的条目、一路往前的前置、一路往后被它解锁的 ---- */
/** 从 start 一路走 next 能到的条目，不含 skip（成环不死循环） */
function closure(start: readonly string[], next: (c: string) => readonly string[], skip: ReadonlySet<string>): Set<string> {
  const seen = new Set<string>();
  const todo: string[] = [...start];
  while (todo.length) {
    const c = todo.pop() as string;
    for (const x of next(c)) {
      if (!seen.has(x) && !skip.has(x)) {
        seen.add(x);
        todo.push(x);
      }
    }
  }
  return seen;
}

export interface Trace {
  self: Set<string>;
  up: Set<string>;
  down: Set<string>;
  /** 它所在的动作 id（挂在动作上的，加上它交付的条目所在的） */
  acts: string[];
}
export function traceOf(b: Brief, key: string): Trace {
  const self = new Set<string>(b.deliver.get(key) ?? []);
  const needs = (c: string): string[] => (b.ctx.items.get(c)?.needs ?? []).filter((n: string) => b.ctx.items.has(n) && n !== c);
  const rev = (c: string): string[] => b.ctx.rev.get(c) ?? [];
  const acts: string[] = uniq([
    ...(b.byTopic.get(key) ?? []).map((v: ActionView) => v.action.id),
    ...b.actions.filter((v: ActionView) => v.action.items.some((c: string) => self.has(c))).map((v: ActionView) => v.action.id),
  ]);
  return { self, up: closure([...self], needs, self), down: closure([...self], rev, self), acts };
}

/** 任务图上一条连线要不要亮：从前置走到它交付的，或从它交付的走到被它解锁的 */
export function edgeOn(t: Trace, e: GEdge): boolean {
  return ((t.up.has(e.from) || t.self.has(e.from)) && (t.self.has(e.to) || t.up.has(e.to))) || ((t.self.has(e.from) || t.down.has(e.from)) && t.down.has(e.to));
}

/* ---- 一个话题在项目里的位置和影响 ---- */
export interface Position {
  /** 它交付的条目；空就是还没挂到条目上 */
  mine: string[];
  up: string[];
  upMore: string[];
  down: string[];
  downMore: string[];
  acts: ActionView[];
  /** 对所在动作、后面的条目、整个专项的影响，一句一条 */
  effects: string[];
  /** session 行里那一句：交付 c20✓ · 前置 c17✓ · 解锁 c15✓ */
  line: string;
}

export function positionOf(b: Brief, key: string): Position {
  const { items } = b.ctx;
  const tr: Trace = traceOf(b, key);
  const mine: string[] = [...tr.self].sort(byId);
  const kind = (c: string): ItemKind => itemKind(items.get(c) as ChecklistItem);
  const mark = (c: string): string => `${c}${ITEM_ICON[kind(c)]}`;
  const up: string[] = uniq(mine.flatMap((c: string) => items.get(c)?.needs ?? [])).filter((x: string) => items.has(x) && !tr.self.has(x)).sort(byId);
  const down: string[] = uniq(mine.flatMap((c: string) => b.ctx.rev.get(c) ?? [])).filter((x: string) => !tr.self.has(x)).sort(byId);
  const upMore: string[] = [...tr.up].filter((x: string) => !up.includes(x)).sort(byId);
  const downMore: string[] = [...tr.down].filter((x: string) => !down.includes(x)).sort(byId);
  const acts: ActionView[] = tr.acts.map((id: string) => b.actions.find((v: ActionView) => v.action.id === id) as ActionView);
  const waitsOf = (x: string): string[] => (items.get(x)?.needs ?? []).filter((w: string) => items.has(w) && !isMet(items.get(w)?.state) && !tr.self.has(w));
  const effects: string[] = [];
  for (const v of acts) {
    const head = `动作 ${v.n}「${cut(v.action.title, 14)}」`;
    if (!v.items.length) {
      effects.push(`${head}：还没有检查表条目`);
      continue;
    }
    const line = `${head}：检查表 ${v.met}/${v.items.length} 满足`;
    const mineUnmet: string[] = v.unmet.filter((it: ChecklistItem) => tr.self.has(it.id)).map((it: ChecklistItem) => it.id);
    const left: string[] = v.unmet.filter((it: ChecklistItem) => !tr.self.has(it.id)).map((it: ChecklistItem) => it.id);
    if (!v.unmet.length) effects.push(`${line}，动作做完`);
    else if (mineUnmet.length) effects.push(`${line}；它的 ${mineUnmet.join('、')} 满足后，${left.length ? `只差 ${left.join('、')}` : '这个动作就做完了'}`);
    else effects.push(`${line}，还差 ${left.join('、')}（不是它交付的）`);
  }
  const mineOpen: boolean = mine.some((c: string) => !isMet(items.get(c)?.state));
  for (const x of down) {
    const by: SnapshotTopic | undefined = b.ctx.topics.get(b.ctx.keyOf(items.get(x)?.topic ?? ''));
    const waits: string[] = waitsOf(x);
    if (isMet(items.get(x)?.state)) effects.push(`解锁的 ${x} 已经满足${by ? `（T${by.number} 做的）` : ''}`);
    else if (mineOpen) effects.push(`它的条目满足后，${x} ${waits.length ? `还在等 ${waits.join('、')}` : '就可以开始'}`);
    else effects.push(`${x} 的这个前置已满足${waits.length ? `，还在等 ${waits.join('、')}` : '，可以开始了'}`);
  }
  const metMine: number = mine.filter((c: string) => isMet(items.get(c)?.state)).length;
  effects.push(`整个专项：目标检查表 ${b.met}/${b.total} 满足${mine.length ? `，其中 ${metMine} 条是它交付的` : ''}`);
  const line: string = mine.length
    ? `交付 ${mine.map(mark).join('、')}${up.length ? ` · 前置 ${up.map(mark).join('、')}` : ''}${down.length ? ` · 解锁 ${down.map(mark).join('、')}` : ' · 不解锁别的条目'}`
    : acts.length
      ? `只挂在${acts.map((v: ActionView) => `动作 ${v.n}`).join('、')}，没对应检查表条目`
      : '还没挂到动作和检查表条目上';
  return { mine, up, upMore, down, downMore, acts, effects, line };
}

/* ---- 汇总：一个专项的简报 ---- */
export function briefOf(p: Pick<SnapshotProject, 'key' | 'goal' | 'checklist' | 'background' | 'actions' | 'gaps'>, snap: Pick<SnapshotResponse, 'topics' | 'questions'>, now: number): Brief {
  const ctx: BriefCtx = briefCtx(p.checklist, snap);
  const { items, asked } = ctx;
  const members: SnapshotTopic[] = snap.topics.filter((t: SnapshotTopic) => t.kind === 'topic' && t.project_key === p.key);
  const open: BriefAction[] = (p.actions ?? []).filter((a: BriefAction) => a.state !== 'dropped').sort((a: BriefAction, b: BriefAction) => numOf(a.id) - numOf(b.id));
  // 话题 key → 它交付、参与的条目；话题 key → 它在哪些动作里
  const deliver = new Map<string, string[]>();
  for (const it of items.values()) {
    for (const r of topicRefs(it)) {
      const k: string = ctx.keyOf(r);
      deliver.set(k, uniq([...(deliver.get(k) ?? []), it.id]).sort(byId));
    }
  }
  const byTopic = new Map<string, ActionView[]>();
  const actions: ActionView[] = open.map((a: BriefAction): ActionView => {
    const its: ChecklistItem[] = a.items.map((c: string) => items.get(c)).filter((it): it is ChecklistItem => !!it);
    const keys: string[] = uniq(a.topics.map(ctx.keyOf));
    const ses: SnapshotTopic[] = keys.map((k: string) => ctx.topics.get(k)).filter((t): t is SnapshotTopic => !!t)
      .sort((x: SnapshotTopic, y: SnapshotTopic) => Number(!isLive(x, asked)) - Number(!isLive(y, asked)) || y.updated_at - x.updated_at);
    const state: ActState = actionState(its, ses, asked);
    const unmet: ChecklistItem[] = its.filter((it: ChecklistItem) => !isMet(it.state));
    const gaps: ProjectGap[] = (p.gaps ?? []).filter((g: ProjectGap) => keys.includes(ctx.keyOf(g.thread)));
    const v: ActionView = { action: a, n: numOf(a.id), state, items: its, unmet, met: its.length - unmet.length, topics: ses, gaps, auto: autoLine(state, its, ses, asked, now) };
    for (const k of keys) byTopic.set(k, [...(byTopic.get(k) ?? []), v]);
    return v;
  });
  const hooked = new Set<string>(actions.flatMap((v: ActionView) => v.topics.map((t: SnapshotTopic) => t.key)));
  const strayGaps: ProjectGap[] = (p.gaps ?? []).filter((g: ProjectGap) => !hooked.has(ctx.keyOf(g.thread)));
  const counts: Record<ActState, number> = { owner: 0, doing: 0, check: 0, done: 0, next: 0 };
  for (const v of actions) counts[v.state] += 1;
  const list: ChecklistItem[] = [...items.values()];
  const met: number = list.filter((it: ChecklistItem) => isMet(it.state)).length;
  const laneOf = (c: string): number => actions.find((v: ActionView) => v.action.items.includes(c))?.n ?? 0;
  const owner: OwnerRow[] = [
    ...list.filter((it: ChecklistItem) => !isMet(it.state) && ownerWaits(it)).map((it: ChecklistItem): OwnerRow => ({ kind: 'item', n: laneOf(it.id), item: it, text: it.gap })),
    ...members.filter((t: SnapshotTopic) => waitsOwner(t, asked)).map((t: SnapshotTopic): OwnerRow => ({ kind: 'topic', n: byTopic.get(t.key)?.[0]?.n ?? 0, topic: t, text: clean(t.progress?.waiting) })),
  ];
  const numbered = (aa: readonly ActionView[]): string => aa.map((v: ActionView) => `动作 ${v.n}`).join('、');
  const feed: FeedRow[] = [
    ...[...members].filter((t: SnapshotTopic) => byTopic.has(t.key)).sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at).slice(0, 7).map((t: SnapshotTopic): FeedRow => {
      const aa: ActionView[] = byTopic.get(t.key) as ActionView[];
      const now2 = topicNow(t);
      return {
        at: t.updated_at,
        who: 'auto',
        topic: t,
        text: `${toneWordOf(t)}${now2.total && toneOf(t) === 'running' ? ` 第 ${now2.done}/${now2.total} 步` : ''} → ${numbered(aa)}：${aa.map((v: ActionView) => ACT_WORD[v.state]).join('、')}`,
      };
    }),
    ...[...actions].filter((v: ActionView) => v.action.at > 0).sort((a: ActionView, b: ActionView) => b.action.at - a.action.at).slice(0, 3)
      .map((v: ActionView): FeedRow => ({ at: v.action.at, who: 'lead', text: `改了动作 ${v.n}「${cut(v.action.title, 12)}」` })),
  ].sort((a: FeedRow, b: FeedRow) => b.at - a.at).slice(0, 8);
  const graph: BriefGraph = graphOf(items, actions.map((v: ActionView) => ({ id: v.action.id, items: v.action.items })));
  return {
    has: !!p.background || actions.length > 0,
    background: p.background ?? '',
    goal: p.goal,
    actions,
    counts,
    members,
    liveN: members.filter(isDoing).length,
    met,
    total: list.length,
    unmapped: members.filter((t: SnapshotTopic) => !deliver.has(t.key)),
    strayGaps,
    changedAt: Math.max(0, ...actions.map((v: ActionView) => v.action.at)),
    owner,
    feed,
    graph,
    ctx,
    deliver,
    byTopic,
  };
}

/* ---- 和负责人说：引用放进负责人对话的输入框（原来的草稿接在后面，同第一期 withQuote） ---- */
export const quoteAction = (v: Pick<ActionView, 'n' | 'state' | 'action'>): string =>
  `关于动作 ${v.n}「${cut(v.action.title, 30)}」· ${ACT_WORD[v.state]}${v.action.note ? ` · ${cut(v.action.note, 60)}` : ''}`;
export const quoteTopic = (t: Pick<SnapshotTopic, 'number' | 'title'>): string => `关于 T${t.number}「${cut(t.title, 30)}」`;
