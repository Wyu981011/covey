/* 专项的「进度」标签（v39，docs/web.md 专项条目）：把负责人的目标检查表分成 做完 / 正在做 / 将要做 / 等你，算解锁、尾巴、依赖图，
 * 取近 10 条决定和里程碑。全是纯函数，不碰页面；第一期只用现有数据，不加字段（“等你”按缺口文字推断，第二期换成 waiting_on）。 */
import type { ChecklistItem, MemoryItem, ProjectNote, QuestionView, SnapshotProject, SnapshotTopic } from '@shared/api.interface';
import { STATES } from './look.gen';
import { byAsked, isRunningTone, isWaiting, toneOf } from './lib';

/** 一条放在哪一栏：done 做完（含不做了）、doing 正在做、next 将要做、owner 等你 */
export type Col = 'done' | 'doing' | 'next' | 'owner';
/** 为什么放在那一栏：met 满足、dropped 不做了、owner 缺口说要主人、needs 在等别的条目、blocked 卡住、
 * live 交付话题在跑、ended 交付话题已结束、lost 交付话题不在网页上、ready 可开始 */
export type Why = 'met' | 'dropped' | 'owner' | 'needs' | 'blocked' | 'live' | 'ended' | 'lost' | 'ready';

export const COLS: readonly Col[] = ['done', 'doing', 'next', 'owner'];
/** 栏名用状态词表的说法（docs/ui.md：不再用“已完成”“完成”） */
export const COL_WORD: Record<Col, string> = { done: '做完', doing: '正在做', next: '将要做', owner: '等你' };
export const COL_ICON: Record<Col, string> = { done: '✓', doing: '▶', next: '○', owner: '!' };

/** 满足了：done 或 dropped（Covey project_checklist.MET，收尾门禁放行的两种） */
export const isMet = (state: string | undefined): boolean => state === 'done' || state === 'dropped';
/** 缺口里说下一步在主人手上（第一期按文字推断）：只差主人、等主人、要主人、需要主人 */
export const OWNER_GAP = /(只差|等|要|需要)主人/u;

export interface Placed {
  item: ChecklistItem;
  col: Col;
  why: Why;
  /** needs 里还没满足的 */
  waiting: string[];
  /** 等着这一条的条目（needs 反查） */
  unlocks: string[];
  /** 交付话题（在快照里找到才有） */
  topic?: SnapshotTopic;
  /** 做完了、缺口还没清的尾巴 */
  tail: boolean;
}

const idNum = (id: string): number => Number(id.slice(1)) || 0;
export const byId = (a: string, b: string): number => idNum(a) - idNum(b);

/** 交付话题此刻：在不在跑（排队、等你也算没结束）、状态词、那一步、第几步 */
export interface TopicNow {
  live: boolean;
  word: string;
  phase: string;
  done: number;
  total: number;
}
export function topicNow(t: SnapshotTopic | undefined): TopicNow {
  if (!t) return { live: false, word: '', phase: '', done: 0, total: 0 };
  const tone = toneOf(t);
  const live: boolean = isRunningTone(tone) || tone === 'queued' || tone === 'waiting';
  // running 只在真的在做时才读：推送里没在跑的话题也可能带着上一轮留下的 running
  const run = t.running && isRunningTone(tone) ? t.running : null;
  const phase: string = (run?.plan_doing || t.progress?.phase || run?.step_label || '').trim();
  const total: number = run?.plan_total || t.progress?.plan_total || 0;
  const done: number = run?.plan_total ? run.plan_done : (t.progress?.plan_done ?? 0);
  return { live, word: STATES[tone].word, phase, done: Math.min(done, total), total };
}

/** 交付话题结束了、条目还没满足时卡上那句：停住了、已停止的照实说，其余是已结束；都待负责人核对 */
export function endedWords(t: SnapshotTopic | undefined): string {
  const tone = t ? toneOf(t) : 'done';
  return `话题${tone === 'stopped' || tone === 'cancelled' ? STATES[tone].word : '已结束'} · 待负责人核对`;
}

/** 一条放哪栏（任务书第六节，按顺序判断） */
function placeOne(item: ChecklistItem, items: Map<string, ChecklistItem>, topics: Map<string, SnapshotTopic>): Pick<Placed, 'col' | 'why' | 'waiting' | 'topic'> {
  const topic: SnapshotTopic | undefined = item.topic ? topics.get(item.topic) : undefined;
  const waiting: string[] = item.needs.filter((n: string) => items.has(n) && !isMet(items.get(n)?.state));
  if (item.state === 'dropped') return { col: 'done', why: 'dropped', waiting, topic };
  if (item.state === 'done') return { col: 'done', why: 'met', waiting, topic };
  if (OWNER_GAP.test(item.gap)) return { col: 'owner', why: 'owner', waiting, topic };
  if (waiting.length) return { col: 'next', why: 'needs', waiting, topic };
  if (item.state === 'blocked') return { col: 'next', why: 'blocked', waiting, topic };
  if (item.topic) return { col: 'doing', why: !topic ? 'lost' : topicNow(topic).live ? 'live' : 'ended', waiting, topic };
  return { col: 'next', why: 'ready', waiting, topic };
}

/** 解锁预告里的一条：做完 from 以后，to 会怎样（已满足、可开始，还是还在等别的） */
export interface Unlock {
  id: string;
  after: 'met' | 'ready' | 'waits';
  /** after 是 waits 时还在等的 */
  rest: string[];
}
export interface Preview {
  from: string;
  to: Unlock[];
}

export interface Board {
  placed: Placed[];
  byId: Map<string, Placed>;
  /** 做完：按 at 倒序（at 是条目最后改动，不是完成时间） */
  done: Placed[];
  doing: Placed[];
  next: Placed[];
  owner: Placed[];
  tails: Placed[];
  counts: Record<Col, number>;
  /** 正在做、等你的条目做完会放出什么 */
  previews: Preview[];
  /** 检查表最后一次改动（各条 at 的最大值），没有是 0 */
  changedAt: number;
}

export function board(list: readonly ChecklistItem[] | undefined, topics: Map<string, SnapshotTopic>): Board {
  const items = new Map<string, ChecklistItem>((list ?? []).map((it: ChecklistItem) => [it.id, it]));
  const unlocks = new Map<string, string[]>();
  for (const it of items.values()) {
    for (const n of it.needs) if (items.has(n) && n !== it.id) unlocks.set(n, [...(unlocks.get(n) ?? []), it.id]);
  }
  const placed: Placed[] = [...items.values()].map((item: ChecklistItem): Placed => {
    const at = placeOne(item, items, topics);
    return { item, ...at, unlocks: (unlocks.get(item.id) ?? []).sort(byId), tail: item.state === 'done' && !!item.gap };
  });
  const of = (c: Col): Placed[] => placed.filter((x: Placed) => x.col === c);
  const done: Placed[] = of('done').sort((a: Placed, b: Placed) => b.item.at - a.item.at || byId(a.item.id, b.item.id));
  const byKey = new Map<string, Placed>(placed.map((x: Placed) => [x.item.id, x]));
  const previews: Preview[] = placed
    .filter((x: Placed) => (x.col === 'doing' || x.col === 'owner') && x.unlocks.length)
    .map((x: Placed): Preview => ({
      from: x.item.id,
      to: x.unlocks.map((u: string): Unlock => {
        const target: Placed | undefined = byKey.get(u);
        if (!target || isMet(target.item.state)) return { id: u, after: 'met', rest: [] };
        const rest: string[] = target.waiting.filter((n: string) => n !== x.item.id);
        return { id: u, after: rest.length ? 'waits' : 'ready', rest };
      }),
    }));
  return {
    placed,
    byId: byKey,
    done,
    doing: of('doing'),
    next: of('next'),
    owner: of('owner'),
    tails: done.filter((x: Placed) => x.tail),
    counts: { done: done.length, doing: of('doing').length, next: of('next').length, owner: of('owner').length },
    previews,
    changedAt: Math.max(0, ...placed.map((x: Placed) => x.item.at || 0)),
  };
}

/** 一条此刻的状态词：满足（检查表自己的说法）、不做了、在做、等你、在等、卡住、可开始 */
export function stateWord(x: Pick<Placed, 'col' | 'why'>): string {
  if (x.why === 'dropped') return '不做了';
  if (x.col === 'done') return '满足';
  if (x.col === 'doing') return '在做';
  if (x.col === 'owner') return '等你';
  return x.why === 'needs' ? '在等' : x.why === 'blocked' ? '卡住' : '可开始';
}

/** 等你带里的话题：本专项（成员和负责人）tone 为 waiting 的，和有 open 问题的（同看板的“等你”） */
export interface WaitTopic {
  topic: SnapshotTopic;
  questions: number;
}
export function waitingTopics(snap: { topics: SnapshotTopic[]; questions: QuestionView[] }, p: Pick<SnapshotProject, 'key' | 'lead_topic_key'>): WaitTopic[] {
  const asked = new Map<string, number>();
  for (const q of snap.questions) asked.set(q.topic_key, (asked.get(q.topic_key) ?? 0) + 1);
  return snap.topics
    .filter((t: SnapshotTopic) => (t.kind === 'topic' && t.project_key === p.key) || (t.kind === 'lead' && (t.key === p.lead_topic_key || t.project_key === p.key)))
    .filter((t: SnapshotTopic) => isWaiting(t) || asked.has(t.key))
    .sort(byAsked)
    .map((t: SnapshotTopic): WaitTopic => ({ topic: t, questions: asked.get(t.key) ?? 0 }));
}

/* ---- 依赖图：只画有依赖关系的条目，一个连通分量一组，横向按深度，同一深度的往下排；算深度防环 ---- */
export interface DepNode {
  id: string;
  /** 第几列（深度） */
  x: number;
  /** 第几行（整张图里） */
  y: number;
}
export interface DepEdge {
  from: string;
  to: string;
  /** 前置已满足、后面的还没满足（蓝色连线） */
  live: boolean;
}
export interface DepGraph {
  nodes: DepNode[];
  edges: DepEdge[];
  cols: number;
  rows: number;
  /** 不和谁有依赖的条目数 */
  lone: number;
}
export function depGraph(list: readonly ChecklistItem[] | undefined): DepGraph {
  const items = new Map<string, ChecklistItem>((list ?? []).map((it: ChecklistItem) => [it.id, it]));
  const needsOf = (id: string): string[] => (items.get(id)?.needs ?? []).filter((n: string) => items.has(n) && n !== id);
  const edges: DepEdge[] = [];
  for (const it of items.values()) {
    for (const n of needsOf(it.id)) edges.push({ from: n, to: it.id, live: isMet(items.get(n)?.state) && !isMet(it.state) });
  }
  const ids: string[] = [...new Set(edges.flatMap((e: DepEdge) => [e.from, e.to]))].sort(byId);
  // 连通分量（并查集）
  const parent = new Map<string, string>(ids.map((id: string) => [id, id]));
  const find = (x: string): string => {
    let r: string = x;
    while (parent.get(r) !== r) r = parent.get(r) as string;
    return r;
  };
  for (const e of edges) parent.set(find(e.from), find(e.to));
  // 深度：最长的前置链。正在算的又被走到就是成环，当 0，不再往下走
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const dep = (id: string): number => {
    const known: number | undefined = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const d: number = Math.max(0, ...needsOf(id).map((n: string) => dep(n) + 1));
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  ids.forEach(dep);
  const groups = new Map<string, string[]>();
  for (const id of ids) groups.set(find(id), [...(groups.get(find(id)) ?? []), id]);
  const comps: string[][] = [...groups.values()].sort((a: string[], b: string[]) => b.length - a.length || idNum(a[0]) - idNum(b[0]));
  const nodes: DepNode[] = [];
  let row = 0;
  for (const comp of comps) {
    const lanes = new Map<number, number>();
    for (const id of comp) {
      const x: number = depth.get(id) ?? 0;
      const lane: number = lanes.get(x) ?? 0;
      lanes.set(x, lane + 1);
      nodes.push({ id, x, y: row + lane });
    }
    row += Math.max(...lanes.values());
  }
  return { nodes, edges, cols: nodes.length ? Math.max(...nodes.map((n: DepNode) => n.x)) + 1 : 0, rows: row, lone: items.size - ids.length };
}

/* ---- 右栏 ---- */
const sec = (at: number | string | undefined): number => {
  if (typeof at === 'number') return Number.isFinite(at) ? at : 0;
  const ms: number = Date.parse(at ?? '');
  return Number.isNaN(ms) ? 0 : ms / 1000;
};

/** 主人答过的一条决定（专项记忆里 kind=decision、source=owner_answer） */
export interface Decision {
  id: string;
  at: number;
  /** 哪个话题问的：T 号（不知道是 null）和 key */
  number: number | null;
  topicKey: string;
  /** “主人答：问题→选择”拆成问题和选择；拆不开时 answer 是空串 */
  question: string;
  answer: string;
  text: string;
}
export function ownerDecisions(memory: readonly MemoryItem[] | undefined, topics: readonly SnapshotTopic[], n = 10): Decision[] {
  const numbers = new Map<string, number | null>(topics.map((t: SnapshotTopic) => [t.key, t.number]));
  return (memory ?? [])
    .filter((m: MemoryItem) => m.kind === 'decision' && m.source === 'owner_answer' && m.text)
    .map((m: MemoryItem): Decision => {
      const body: string = m.text.replace(/^\s*(\[decision\]\s*)?主人(答|定)\s*[:：]\s*/u, '').replace(/（推荐）/gu, '');
      const cut: number = body.indexOf('→');
      const topicKey: string = m.origin?.topic ?? '';
      return {
        id: m.id ?? '',
        at: sec(m.at ?? m.origin?.at),
        number: m.origin?.topic_number ?? numbers.get(topicKey) ?? null,
        topicKey,
        question: (cut >= 0 ? body.slice(0, cut) : body).trim(),
        answer: cut >= 0 ? body.slice(cut + 1).trim() : '',
        text: m.text,
      };
    })
    .sort((a: Decision, b: Decision) => b.at - a.at || a.id.localeCompare(b.id))
    .slice(0, n);
}

/** 哪天：MM-DD（北京时间，同 lib.ts shortWhen，docs/ui.md 第 7 节） */
export const dayOf = (at: number): string =>
  new Date(at * 1000).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).replace(/\//gu, '-');
/** 最近里程碑按天归组：新的一天在前，组内新的在前（对应主人文档里的「进度记录」） */
export function milestoneDays(notes: readonly ProjectNote[] | undefined): { day: string; rows: ProjectNote[] }[] {
  const out: { day: string; rows: ProjectNote[] }[] = [];
  for (const n of [...(notes ?? [])].sort((a: ProjectNote, b: ProjectNote) => b.at - a.at)) {
    const day: string = n.at ? dayOf(n.at) : '';
    const last = out[out.length - 1];
    if (last && last.day === day) last.rows.push(n);
    else out.push({ day, rows: [n] });
  }
  return out;
}

/* ---- 和负责人讨论 ---- */
export const cut = (s: string, n: number): string => {
  const chars: string[] = Array.from(s.trim());
  return chars.length <= n ? chars.join('') : `${chars.slice(0, n).join('')}…`;
};
/** 引用：关于 c20「标准前 40 字」· 状态 · 缺口前 60 字（没有缺口就不写这一段） */
export function quoteOf(x: Pick<Placed, 'item' | 'col' | 'why'>): string {
  const gap: string = x.item.gap ? ` · ${cut(x.item.gap, 60)}` : '';
  return `关于 ${x.item.id}「${cut(x.item.criterion, 40)}」· ${stateWord(x)}${gap}`;
}
/** 引用放在前面，原来的草稿接在下一行 */
export const withQuote = (quote: string, draft: string): string => (draft.trim() ? `${quote}\n${draft}` : `${quote}\n`);
