/**
 * 多参与者协作的契约，网页一侧（docs/web.md「协作与三层记忆」；规则的原件是 Covey 的 core/collab.py，
 * 对照测试 tests/test_collab.py 逐条搬到了 scripts/collab.test.mjs）。
 * - route：主人这句话交给谁、谁汇总。大厅不 @ 交给管家；单 @ 直达（可以是普通话题）；多 @ 是协作，汇总方按引用、主人的选择、
 *   第一个点到的普通话题（输入框写明、可以改）定；只点了负责人由管家归口；协助方超过 3 位发起前就拒。
 * - 两张状态表的词、首版限额；推来的协作条目和一轮的 collab 字段按这里认（collabOf、turnCollabOf），认不出的不画。
 * 纯数据和函数，前后端和测试共用，所以只从 api.interface 取类型，不引别的模块。
 */
import type { CollabAsk, CollabEvidence, CollabReply, CollabRoot, CollabView, TurnCollab } from './api.interface';

/** 参与者的角色 */
export type Role = 'butler' | 'lead' | 'topic';
export const BUTLER: Role = 'butler';
export const LEAD: Role = 'lead';
export const TOPIC: Role = 'topic';

/** 主人在哪说的：大厅（飞书私聊顶层）或一个话题（话题页、话题串） */
export type Where = 'room' | 'topic';
export const ROOM: Where = 'room';
export const IN_TOPIC: Where = 'topic';

/** route 交给哪：照原来交给管家、照原来直达一位、协作、管家归口一次、不发（带原因） */
export type RouteTo = 'desk' | 'direct' | 'collab' | 'router' | 'refused';
export const DESK: RouteTo = 'desk';
export const DIRECT: RouteTo = 'direct';
export const COLLAB: RouteTo = 'collab';
export const ROUTER: RouteTo = 'router';
export const REFUSED: RouteTo = 'refused';

/** 首版限额（同 core/collab.py） */
export const HELPERS_DEFAULT = 2;
export const HELPERS_NAMED = 3;
export const ASKS_PER_HELPER = 2;
export const QUEUE_SECONDS = 600;
export const WINDOW_SECONDS = 1800;
export const tooMany = (m: number): string => `一次最多请 ${HELPERS_NAMED} 位协助，这次点了 ${m} 位：先少点几位`;

/** 一次协作：咨询还在外面时 open，汇总方交了结论 done，主人停了 cancelled */
export const OPEN = 'open';
export const DONE = 'done';
export const CANCELLED = 'cancelled';
export const COLLAB_TRANSITIONS: Record<string, readonly string[]> = { [OPEN]: [DONE, CANCELLED], [DONE]: [], [CANCELLED]: [] };
/** 协作本身在界面上的词（docs/glossary.md 状态词） */
export const COLLAB_WORDS: Record<string, string> = { [OPEN]: '在做', [DONE]: '做完', [CANCELLED]: '已停止' };

/** 一次咨询：待校验 → 排队 → 已接手 → 已答复 → 已被汇总方读取；或未接手、失败、到期、已取消 */
export const CHECKING = 'checking';
export const QUEUED = 'queued';
export const TAKEN = 'taken';
export const REPLIED = 'replied';
export const READ = 'read';
export const NOT_TAKEN = 'not_taken';
export const FAILED = 'failed';
export const EXPIRED = 'expired';
export const ASK_TRANSITIONS: Record<string, readonly string[]> = {
  [CHECKING]: [QUEUED, NOT_TAKEN, FAILED, CANCELLED],
  [QUEUED]: [TAKEN, NOT_TAKEN, FAILED, EXPIRED, CANCELLED],
  [TAKEN]: [REPLIED, FAILED, EXPIRED, CANCELLED],
  [REPLIED]: [READ],
  [READ]: [],
  [NOT_TAKEN]: [],
  [FAILED]: [],
  [EXPIRED]: [],
  [CANCELLED]: [],
};
export const ASK_WORDS: Record<string, string> = {
  [CHECKING]: '待校验', [QUEUED]: '排队', [TAKEN]: '已接手', [REPLIED]: '已答复', [READ]: '已被汇总方读取',
  [NOT_TAKEN]: '未接手', [FAILED]: '失败', [EXPIRED]: '到期', [CANCELLED]: '已取消',
};
/** 还能停的咨询（排着队或在跑）：停这件事停的就是它们 */
export const ASK_LIVE: ReadonlySet<string> = new Set<string>([CHECKING, QUEUED, TAKEN]);

/** table 允许 current 走到 next 时返回 next，否则抛错（终态不回退） */
export function moved(table: Record<string, readonly string[]>, current: string, next: string): string {
  if (!(table[current] ?? []).includes(next)) throw new Error(`${current} → ${next} is not a transition`);
  return next;
}

/** 一位参与者：稳定的话题 id 和它的角色；project 是负责人自己的专项、专项话题所在的专项 */
export interface Participant {
  key: string;
  role: Role;
  project?: string;
}

/** 引用：引的是谁的话；属于哪次协作（collab）时要带那次协作的汇总方 */
export interface QuoteOf {
  of: Participant;
  collab?: string;
  integrator?: Participant | null;
}

/** 主人说的一句：点到的人（mentions，按点的顺序，不从正文里猜）、引用、主人选的汇总方 */
export interface Entry {
  where?: Where;
  here?: Participant | null;
  mentions?: readonly Participant[];
  quote?: QuoteOf | null;
  integrator?: Participant | null;
}

export interface Route {
  to: RouteTo;
  /** 交付归谁（desk、router、refused 为空） */
  owner: string;
  /** 协作：其余被问的；router：点到的负责人 */
  helpers: string[];
  /** 这句话属于的协作（引用了协作里的话） */
  collab: string;
  /** 汇总方是第一个点到的普通话题：输入框写明，可以改 */
  shown_default: boolean;
  /** refused：为什么 */
  reason: string;
}

const made = (to: RouteTo, owner = '', helpers: string[] = [], collab = '', shownDefault = false, reason = ''): Route => ({
  to, owner, helpers, collab, shown_default: shownDefault, reason,
});

function unique(list: readonly (Participant | null | undefined)[]): Participant[] {
  const seen = new Set<string>();
  const kept: Participant[] = [];
  for (const p of list) {
    if (p && !seen.has(p.key)) {
      seen.add(p.key);
      kept.push(p);
    }
  }
  return kept;
}

/** owner 汇总、others 协助的协作；没有别人（这句话也不属于哪次协作）时就是直达 owner */
function collabRoute(owner: Participant, others: readonly (Participant | null | undefined)[], collab = '', shownDefault = false): Route {
  const helpers: string[] = unique(others).map((p: Participant) => p.key).filter((k: string) => k !== owner.key);
  if (helpers.length > HELPERS_NAMED) return made(REFUSED, '', [], '', false, tooMany(helpers.length));
  if (!helpers.length && !collab) return owner.role === BUTLER ? made(DESK) : made(DIRECT, owner.key);
  return made(COLLAB, owner.key, helpers, collab, shownDefault);
}

/**
 * 交付归谁（同 core/collab.py 的 route，第一条适用的规则说了算）：
 * 1. 引用了一次协作里的话：那次协作，它的汇总方；点到的人再问一次。
 * 2. 主人选了汇总方：那一位，其余协助。
 * 3. 在话题里：这个话题汇总，点到的人协助（没点人就是原来那样直达它）。
 * 4. 大厅、没点人：引用的那位（管家的话是管家），否则管家。
 * 5. 点了一位：照原来交给它（管家就是管家）。
 * 6. 点了几位：引用的话题汇总；否则第一个点到的普通话题（输入框写明、可以改）；否则点到的管家；否则管家归口一次（只有负责人）。
 * 协助方超过 HELPERS_NAMED：不发。
 */
export function route(entry: Entry): Route {
  const mentions: Participant[] = unique(entry.mentions ?? []);
  const quote: QuoteOf | null = entry.quote ?? null;
  if (quote && quote.collab) {
    if (!quote.integrator) throw new Error('a quote of a collaboration needs its integrator');
    return collabRoute(quote.integrator, mentions, quote.collab);
  }
  if (entry.integrator) return collabRoute(entry.integrator, [entry.here ?? null, ...mentions]);
  if ((entry.where ?? ROOM) === IN_TOPIC) {
    if (!entry.here) throw new Error('a message in a topic needs the topic');
    return collabRoute(entry.here, mentions);
  }
  if (!mentions.length) {
    if (!quote || quote.of.role === BUTLER) return made(DESK);
    return made(DIRECT, quote.of.key);
  }
  if (mentions.length === 1) return mentions[0].role === BUTLER ? made(DESK) : made(DIRECT, mentions[0].key);
  if (quote && quote.of.role === TOPIC) return collabRoute(quote.of, mentions);
  const topics: Participant[] = mentions.filter((p: Participant) => p.role === TOPIC);
  if (topics.length) return collabRoute(topics[0], mentions, '', true);
  const butlers: Participant[] = mentions.filter((p: Participant) => p.role === BUTLER);
  if (butlers.length) return collabRoute(butlers[0], mentions);
  if (mentions.length > HELPERS_NAMED) return made(REFUSED, '', [], '', false, tooMany(mentions.length));
  return made(ROUTER, '', mentions.map((p: Participant) => p.key));
}

/* ---- 推来的数据：只认得形状对的，字数有上限（服务端读库时用，页面拿到的已经是这个形状） ---- */

const KEY = /^[A-Za-z0-9_.:-]{1,128}$/u;
const s = (v: unknown, max: number): string => (typeof v === 'string' ? v.slice(0, max) : '');
const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const o = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const keyOf = (v: unknown): string => (typeof v === 'string' && KEY.test(v) ? v : '');

/** 一轮的 collab：{key, role}，role 只认 integrator、helper */
export function turnCollabOf(v: unknown): TurnCollab | undefined {
  const d: Record<string, unknown> = o(v);
  const key: string = keyOf(d.key);
  if (!key || (d.role !== 'integrator' && d.role !== 'helper')) return undefined;
  return { key, role: d.role };
}

function evidenceOf(v: unknown): CollabEvidence[] {
  const list: unknown[] = typeof v === 'string' ? [v] : Array.isArray(v) ? v : [];
  const out: CollabEvidence[] = [];
  for (const x of list.slice(0, 20)) {
    if (typeof x === 'string') {
      if (x.trim()) out.push({ text: x.slice(0, 2000) });
      continue;
    }
    const d: Record<string, unknown> = o(x);
    const text: string = s(d.text, 2000) || s(d.title, 2000) || s(d.name, 2000) || s(d.summary, 2000);
    const link: string = s(d.link, 2000) || s(d.url, 2000);
    const topic: string = keyOf(d.topic_key);
    if (!text && !link && !topic) continue;
    out.push({
      text: text || link || '出处',
      ...(/^https?:\/\//iu.test(link) ? { link } : {}),
      ...(topic ? { topic_key: topic } : {}),
      ...(n(d.seq) > 0 ? { seq: n(d.seq) } : {}),
    });
  }
  return out;
}

function replyOf(v: unknown): CollabReply | null {
  if (typeof v === 'string') return v.trim() ? { text: v.slice(0, 32000), evidence: [] } : null;
  const d: Record<string, unknown> = o(v);
  const text: string = s(d.text, 32000);
  const evidence: CollabEvidence[] = evidenceOf(d.evidence);
  if (!text && !evidence.length) return null;
  const topic: string = keyOf(d.topic_key);
  return {
    text,
    evidence,
    ...(topic ? { topic_key: topic } : {}),
    ...(n(d.seq) > 0 ? { seq: n(d.seq) } : {}),
    ...(n(d.at) > 0 ? { at: n(d.at) } : {}),
  };
}

function askOf(v: unknown, i: number): CollabAsk | null {
  const d: Record<string, unknown> = o(v);
  const from: string = keyOf(d.from);
  const to: string = keyOf(d.to);
  if (!to) return null;
  const late: Record<string, unknown> = o(d.late);
  return {
    id: s(d.id, 128) || `ask-${i}`,
    from,
    to,
    number: d.number === 2 ? 2 : 1,
    state: s(d.state, 24) || CHECKING,
    text: s(d.text, 8000),
    reply: replyOf(d.reply),
    reason: s(d.reason, 400),
    ...(s(d.words, 24) ? { words: s(d.words, 24) } : {}),
    ...(s(late.text, 4000) ? { late: { text: s(late.text, 4000), ...(n(late.at) > 0 ? { at: n(late.at) } : {}) } } : {}),
  };
}

function rootOf(v: unknown): CollabRoot {
  if (typeof v === 'string') return v ? { message_id: v.slice(0, 160) } : {};
  const d: Record<string, unknown> = o(v);
  return {
    ...(s(d.message_id, 160) ? { message_id: s(d.message_id, 160) } : {}),
    ...(s(d.job, 160) || s(d.job_key, 160) ? { job: s(d.job, 160) || s(d.job_key, 160) } : {}),
  };
}

/** 一条协作条目；没有汇总方的不认（null） */
export function collabOf(key: string, v: unknown): CollabView | null {
  const d: Record<string, unknown> = o(v);
  const integrator: string = keyOf(d.integrator);
  const k: string = keyOf(key) || keyOf(d.key);
  if (!k || !integrator) return null;
  const helpers: string[] = [...new Set((Array.isArray(d.helpers) ? d.helpers : []).map(keyOf).filter(Boolean))].slice(0, 8);
  const asks: CollabAsk[] = (Array.isArray(d.asks) ? d.asks : []).slice(0, 24).map(askOf).filter((x): x is CollabAsk => x !== null);
  const rev: unknown = d.goal_rev;
  return {
    key: k,
    root: rootOf(d.root),
    integrator,
    helpers,
    state: s(d.state, 24) || OPEN,
    ...(typeof rev === 'string' || typeof rev === 'number' ? { goal_rev: String(rev).slice(0, 64) } : {}),
    created_at: n(d.created_at),
    updated_at: n(d.updated_at),
    asks,
  };
}

/** 这次协作还有能停的咨询（开着、有排队或在跑的） */
export const stoppable = (c: Pick<CollabView, 'state' | 'asks'>): boolean => c.state === OPEN && c.asks.some((a: CollabAsk) => ASK_LIVE.has(a.state));
