/**
 * 网页上的协作（包 E，docs/web.md「协作与三层记忆」）：纯函数。
 * - 点名：大厅和话题页在正文里打 @ 点几位（管家、没结束的专项的负责人、普通话题，按 T 号和标题搜），点到的成为正文里的胶囊（cv/mention.ts）；
 *   参与者是正文里的胶囊，按第一次插入的先后；只认胶囊，不从正文里手打的 @ 或 T 号猜。
 * - 交给谁、谁汇总：照 shared/collab.ts 的 route（Covey core/collab.py 的移植），输入框写明“这件事由 T3 汇总 [更换]”；
 *   后面再加人不偷偷改掉已经写出来的汇总方，移除人时重算。
 * - 协作往返和协助方的回执：协作条目放进对话的哪里、每次咨询怎么说。
 */
import type { CollabAsk, CollabView, SayFile, SayQuote, SnapshotProject, SnapshotResponse, SnapshotTopic, TurnView } from '@shared/api.interface';
import {
  ASK_LIVE, ASK_WORDS, BUTLER, COLLAB, COLLAB_WORDS, DESK, DIRECT, IN_TOPIC, LEAD, REFUSED, ROOM, ROUTER, TOPIC, route,
  type Participant, type QuoteOf, type Route,
} from '@shared/collab';
import { leadName, members, type Member, type RoomTurn } from './room';
import { mentionKeys } from './mention';

/** 点名框里的一位：参与者 + 界面上的名字 */
export interface Candidate extends Participant {
  /** 管家、“夜航改版 负责人”、“T12” */
  name: string;
  /** 话题的标题（管家、负责人为空） */
  title: string;
  /** 收起、停住的负责人，已停止、做完的话题：灰着，点了也照样能点 */
  dim: boolean;
  /** 话题的状态词（state），列表里写在右边 */
  state: string;
  /** 头像：负责人是它专项的固定头像名；话题是它的 T 号 */
  avatar?: string;
  number?: number | null;
}

/** 胶囊和头像条上画一位要的：种类、名字、头像（和 RoomBits 的 RoleAvatar 对上） */
export interface MentionInfo {
  key: string;
  kind: 'butler' | 'lead' | 'topic';
  /** 管家、“夜航改版 负责人”、“T12” */
  label: string;
  avatar?: string;
  number?: number | null;
  /** 话题的标题 */
  title?: string;
}

/** 快照里认得这个 key（管家、负责人、话题） */
export const knownKey = (key: string, snap: SnapshotResponse | undefined, butler: string | null): boolean => !!key && !!snap
  && (key === (butler ?? snap.butler_key) || snap.projects.some((p: SnapshotProject) => p.lead_topic_key === key) || snap.topics.some((t: SnapshotTopic) => t.key === key));

/** 一个 key 在界面上怎么画：快照里没有的当话题 */
export function mentionInfo(key: string, snap: SnapshotResponse | undefined, butler: string | null): MentionInfo {
  const who: Participant = participantOf(key, snap, butler);
  const label: string = nameOf(key, snap, butler);
  if (who.role === BUTLER) return { key, kind: 'butler', label };
  if (who.role === LEAD) {
    const p: SnapshotProject | undefined = snap?.projects.find((x: SnapshotProject) => x.lead_topic_key === key || x.key === who.project);
    return { key, kind: 'lead', label, ...(p?.avatar ? { avatar: p.avatar } : {}) };
  }
  const t: SnapshotTopic | undefined = snap?.topics.find((x: SnapshotTopic) => x.key === key);
  return { key, kind: 'topic', label, number: t?.number ?? null, ...(t?.title ? { title: t.title } : {}) };
}

const tNo = (t: SnapshotTopic): string => (t.number ? `T${t.number}` : t.title || '话题');

/** 一个 key 是谁：管家、负责人或话题；快照里没有的当话题 */
export function participantOf(key: string, snap: SnapshotResponse | undefined, butler: string | null): Participant {
  if (key && key === (butler ?? snap?.butler_key)) return { key, role: BUTLER };
  const p: SnapshotProject | undefined = snap?.projects.find((x: SnapshotProject) => x.lead_topic_key === key);
  if (p) return { key, role: LEAD, project: p.key };
  const t: SnapshotTopic | undefined = snap?.topics.find((x: SnapshotTopic) => x.key === key);
  if (t?.kind === 'butler') return { key, role: BUTLER };
  if (t?.kind === 'lead') return { key, role: LEAD, project: t.project_key ?? '' };
  return { key, role: TOPIC, project: t?.project_key ?? '' };
}

/** 界面上怎么叫它：管家、“夜航改版 负责人”、“T12”（full 时话题带标题） */
export function nameOf(key: string, snap: SnapshotResponse | undefined, butler: string | null, full = false): string {
  const who: Participant = participantOf(key, snap, butler);
  if (who.role === BUTLER) return '管家';
  if (who.role === LEAD) {
    const p: SnapshotProject | undefined = snap?.projects.find((x: SnapshotProject) => x.lead_topic_key === key || x.key === who.project);
    return leadName(p?.title ?? '');
  }
  const t: SnapshotTopic | undefined = snap?.topics.find((x: SnapshotTopic) => x.key === key);
  if (!t) return '话题';
  return full && t.number ? `T${t.number} ${t.title}` : tNo(t);
}

/** 能点名的：管家、没结束的专项的负责人（成员栏那几位），再是普通话题（最近动过的在前）；except 里的不列（话题页里的自己） */
export function candidates(snap: SnapshotResponse | undefined, except: readonly string[] = []): Candidate[] {
  if (!snap) return [];
  const skip = new Set<string>(except);
  const out: Candidate[] = members(snap).filter((m: Member) => !skip.has(m.key)).map((m: Member): Candidate => {
    const avatar: string | undefined = m.kind === 'lead' ? snap.projects.find((p: SnapshotProject) => p.key === m.project)?.avatar : undefined;
    return { key: m.key, role: m.kind === 'butler' ? BUTLER : LEAD, project: m.project, name: m.name, title: '', dim: m.dim, state: '', ...(avatar ? { avatar } : {}) };
  });
  const topics: SnapshotTopic[] = snap.topics.filter((t: SnapshotTopic) => t.kind === 'topic' && !skip.has(t.key))
    .sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at);
  for (const t of topics) {
    out.push({
      key: t.key, role: TOPIC, project: t.project_key ?? '', name: tNo(t), title: t.title,
      dim: t.state === '已停止' || t.state === '做完', state: t.state, number: t.number,
    });
  }
  return out;
}

/** 点名框按打的字找：T 号（T12、t12、12）先找那一个；再找名字、标题里有这几个字的（不分大小写）。空着时列成员和最近的话题 */
export function searchCandidates(list: Candidate[], query: string, max = 8): Candidate[] {
  const q: string = query.trim().toLowerCase();
  if (!q) {
    const people: Candidate[] = list.filter((c: Candidate) => c.role !== TOPIC);
    return [...people, ...list.filter((c: Candidate) => c.role === TOPIC).slice(0, Math.max(0, max - people.length))];
  }
  const num: RegExpMatchArray | null = /^t?\s*(\d{1,6})$/u.exec(q);
  const exact: Candidate[] = num ? list.filter((c: Candidate) => c.role === TOPIC && c.name.toLowerCase() === `t${num[1]}`) : [];
  const hit: Candidate[] = list.filter((c: Candidate) => !exact.includes(c)
    && (c.name.toLowerCase().includes(q) || c.title.toLowerCase().includes(q) || (!!num && c.name.toLowerCase().startsWith(`t${num[1]}`))));
  return [...exact, ...hit].slice(0, max);
}

/** 结构化引用（payload.quote），另带输入框上显示的几个字 */
export interface QuoteRef extends SayQuote {
  /** 引用块里写谁说的：“T12 标题”“管家”“这次协作” */
  who: string;
  /** 引用的那段（拼进正文的 Markdown 引用块；空就不拼） */
  text: string;
  /** 引的是哪一条（界面上认出是哪条用） */
  key: string;
}

/** 输入框里这句话的点名状态 */
export interface PlanInput {
  where: 'room' | 'topic';
  /** 话题页：这个话题 */
  here: string | null;
  /** 点到的人，按点的顺序 */
  picks: string[];
  /** 主人选的汇总方（点了[更换]，或后来加了人时留住的那位）；没有是 null */
  integrator: string | null;
  quote: QuoteRef | null;
  snap: SnapshotResponse | undefined;
  butler: string | null;
  /** 认得的协作（引用协作里的话时找它的汇总方） */
  collabs: readonly CollabView[];
}

export interface Plan {
  route: Route | null;
  /** 发件行的 topic_key：大厅是交付归的那位（管家归口、交给管家是管家），话题页是这个话题；不发时 null */
  topicKey: string | null;
  /** 交付归谁（空：管家照原来判断、或管家归口） */
  owner: string;
  helpers: string[];
  /** 这句话属于的协作（回复这次协作） */
  collab: string;
  /** 输入框上的一句：“这件事由 T3 汇总”“由管家归口…”“交给 T5”；没点人也没引用时为空 */
  line: string;
  /** 能不能[更换]汇总方，换成谁 */
  change: boolean;
  choices: string[];
  /** 发起前就拦下的原因（协助方太多） */
  blocked: string;
  /** 要带上的 payload.integrator（和 route 的默认不同才带） */
  integrator: string | null;
  /** 发送钮的 title：完整的去向，“由 T586 汇总，请 T505、T601 协助”；单人、没点人时空 */
  title: string;
  /** 底栏那颗小胶囊：collab 多人协作“由 T586 汇总”、router“由管家归口”、bad 协助方太多、reply 回复这次协作（写在引用条上，底栏不画）；没有就空 */
  chip: '' | 'collab' | 'router' | 'bad' | 'reply';
}

/** 引用的是谁的话；属于一次协作时带上它的汇总方（汇总方不认得就不当协作引用） */
function quoteOf(q: QuoteRef | null, input: PlanInput): QuoteOf | null {
  if (!q) return null;
  const of: Participant = participantOf(q.topic_key, input.snap, input.butler);
  const c: CollabView | undefined = q.collab ? input.collabs.find((x: CollabView) => x.key === q.collab) : undefined;
  if (!c) return { of };
  return { of, collab: c.key, integrator: participantOf(c.integrator, input.snap, input.butler) };
}

function routeOf(input: PlanInput, integrator: string | null): Route | null {
  const { snap, butler } = input;
  const who = (k: string): Participant => participantOf(k, snap, butler);
  try {
    return route({
      where: input.where === 'topic' ? IN_TOPIC : ROOM,
      here: input.here ? who(input.here) : null,
      mentions: input.picks.map(who),
      quote: quoteOf(input.quote, input),
      integrator: integrator ? who(integrator) : null,
    });
  } catch {
    return null;
  }
}

/** 这句话交给谁、谁汇总、输入框上写什么、payload 带不带 integrator */
export function plan(input: PlanInput): Plan {
  const r: Route | null = routeOf(input, input.integrator);
  const name = (k: string): string => nameOf(k, input.snap, input.butler);
  const empty: Plan = {
    route: r, topicKey: null, owner: '', helpers: [], collab: '', line: '', change: false, choices: [], blocked: '', integrator: null, title: '', chip: '',
  };
  if (!r) return empty;
  if (r.to === REFUSED) return { ...empty, line: r.reason, blocked: r.reason, title: r.reason, chip: 'bad' };
  const topicKey: string | null = input.where === 'topic' ? input.here : r.to === DESK || r.to === ROUTER ? input.butler : r.owner;
  const named: boolean = input.picks.length > 0 || !!input.quote;
  let line = '';
  let change = false;
  let choices: string[] = [];
  if (r.to === COLLAB && r.collab) {
    line = `回复这次协作，由 ${name(r.owner)} 汇总${r.helpers.length ? `，再问 ${r.helpers.map(name).join('、')}` : ''}`;
  } else if (r.to === COLLAB) {
    line = `这件事由 ${name(r.owner)}${r.owner === input.here ? '（这个话题）' : ''} 汇总`;
    change = true;
    choices = [...(input.here ? [input.here] : []), ...input.picks].filter((k: string, i: number, all: string[]) => k !== r.owner && all.indexOf(k) === i);
  } else if (r.to === ROUTER) {
    line = '由管家归口：只点了负责人，管家先找出这件事归谁';
    change = true;
    choices = [...input.picks];
  } else if (r.to === DIRECT && named && !(input.where === 'topic' && r.owner === input.here)) {
    line = `交给 ${name(r.owner)}${input.quote && input.picks.length ? '，引用的那段一起带上' : ''}`;
  } else if (r.to === DESK && named) {
    line = '交给管家';
  }
  // payload.integrator：主人选了、而且和不选时 route 给的不一样才带（回复协作时由那次协作的汇总方接，不带）
  let integrator: string | null = null;
  if (input.integrator && !r.collab) {
    const plain: Route | null = routeOf(input, null);
    if (!plain || plain.owner !== input.integrator) integrator = input.integrator;
  }
  const helped: string = r.helpers.map(name).join('、');
  const title: string = r.to === COLLAB
    ? `${r.collab ? '回复这次协作，' : ''}由 ${name(r.owner)} 汇总${helped ? `，${r.collab ? '再问' : '请'} ${helped}${r.collab ? '' : ' 协助'}` : ''}`
    : r.to === ROUTER ? `由管家归口：先找出这件事归 ${helped} 里的谁`
      : r.to === DIRECT && named ? `交给 ${name(r.owner)}`
        : '';
  const chip: Plan['chip'] = r.to === COLLAB ? (r.collab ? 'reply' : 'collab') : r.to === ROUTER ? 'router' : '';
  return { route: r, topicKey, owner: r.owner, helpers: r.helpers, collab: r.collab, line, change, choices, blocked: '', integrator, title, chip };
}

/**
 * 正文变了以后的名单：正文里新出现的胶囊按 addPick 加（后加人不偷偷改已经写出的汇总方），删光的按 removePick 移出
 * （它是选定的汇总方就退回默认）。名单顺序是第一次插入的先后，不是正文里的位置。
 */
export function syncPicks(input: PlanInput, md: string): { picks: string[]; integrator: string | null } {
  const now: string[] = mentionKeys(md);
  let cur: { picks: string[]; integrator: string | null } = { picks: input.picks, integrator: input.integrator };
  for (const k of input.picks) {
    if (!now.includes(k)) cur = removePick({ ...input, ...cur }, k);
  }
  for (const k of now) {
    if (!cur.picks.includes(k)) cur = addPick({ ...input, ...cur }, k);
  }
  return cur;
}

/** 加一位：已经写出“由 X 汇总”的，加人后 route 若会换人，就把 X 留住（后面再加人不偷偷改掉汇总方） */
export function addPick(input: PlanInput, key: string): { picks: string[]; integrator: string | null } {
  if (!key || input.picks.includes(key) || key === input.here) return { picks: input.picks, integrator: input.integrator };
  const picks: string[] = [...input.picks, key];
  if (input.integrator) return { picks, integrator: input.integrator };
  const before: Plan = plan(input);
  const after: Plan = plan({ ...input, picks });
  const keep: boolean = before.route?.to === COLLAB && !before.collab && after.route?.to === COLLAB && after.owner !== before.owner;
  return { picks, integrator: keep ? before.owner : null };
}

/** 移掉一位：它是选定的汇总方就退回默认，重算；输入框写的字不动（草稿不在这里） */
export function removePick(input: PlanInput, key: string): { picks: string[]; integrator: string | null } {
  return { picks: input.picks.filter((k: string) => k !== key), integrator: input.integrator === key ? null : input.integrator };
}

const QUOTE_CHARS = 300;
/** 引用块（同大厅的引用）：“> 引用 T12 标题：”接引用的那段；没有那段就不拼 */
export function quoted(text: string, quote: QuoteRef | null): string {
  const body: string = text.trim();
  const part: string = (quote?.text ?? '').replace(/\r/gu, '').replace(/\n{3,}/gu, '\n\n').trim();
  if (!quote || !part) return body;
  const clipped: string = part.length > QUOTE_CHARS ? `${part.slice(0, QUOTE_CHARS)}…` : part;
  return `> 引用 ${quote.who}：\n${clipped.split('\n').map((l: string) => `> ${l}`).join('\n')}\n\n${body}`;
}

/** say 的 payload：话（带引用块）、附件；点了人才带 to（按点的顺序），选了不同的汇总方才带 integrator，引用了才带 quote */
export function sayPayload(text: string, files: SayFile[], input: PlanInput, p: Plan): Record<string, unknown> {
  const q: QuoteRef | null = input.quote;
  return {
    text: quoted(text, q),
    ...(input.where === 'room' ? { room: true } : {}),
    ...(files.length ? { files } : {}),
    ...(input.picks.length ? { to: [...input.picks] } : {}),
    ...(p.integrator ? { integrator: p.integrator } : {}),
    ...(q ? { quote: { topic_key: q.topic_key, ...(q.seq ? { seq: q.seq } : {}), ...(q.collab && p.collab ? { collab: q.collab } : {}) } } : {}),
  };
}

/** 发出去的话在大厅里写交给了谁：“→ T5 汇总 · 协助 T7、夜航改版 负责人” */
export function collabRoute(integrator: string, helpers: readonly string[], snap: SnapshotResponse | undefined, butler: string | null): string {
  const name = (k: string): string => nameOf(k, snap, butler);
  return `→ ${name(integrator)} 汇总${helpers.length ? ` · 协助 ${helpers.map(name).join('、')}` : ''}`;
}

/* ---- 协作往返 ---- */

export interface AskLine {
  id: string;
  /** “T5 → T7” */
  from: string;
  to: string;
  /** 谁问谁（key，画头像用；问的人空着是汇总方） */
  fromKey: string;
  toKey: string;
  /** 咨询、澄清 */
  what: string;
  state: string;
  /** 状态词（core/collab.py 的 ASK_WORDS） */
  word: string;
  live: boolean;
  text: string;
  ask: CollabAsk;
}

/** 一次协作的每次咨询，按发出的顺序 */
export function askLines(c: CollabView, snap: SnapshotResponse | undefined, butler: string | null): AskLine[] {
  const name = (k: string): string => (k ? nameOf(k, snap, butler) : nameOf(c.integrator, snap, butler));
  return c.asks.map((a: CollabAsk): AskLine => ({
    id: a.id, from: name(a.from), to: name(a.to), fromKey: a.from || c.integrator, toKey: a.to, what: a.number === 2 ? '澄清' : '咨询', state: a.state,
    word: a.words || (ASK_WORDS[a.state] ?? a.state), live: ASK_LIVE.has(a.state), text: a.text, ask: a,
  }));
}

/** 协作标题行的几个字：谁汇总、谁协助、状态、几次咨询答了几次 */
export function collabHead(c: CollabView, snap: SnapshotResponse | undefined, butler: string | null): {
  integrator: string; helpers: string[]; word: string; asks: number; replied: number; live: number;
} {
  return {
    integrator: nameOf(c.integrator, snap, butler),
    helpers: c.helpers.map((k: string) => nameOf(k, snap, butler)),
    word: COLLAB_WORDS[c.state] ?? c.state,
    asks: c.asks.length,
    replied: c.asks.filter((a: CollabAsk) => !!a.reply).length,
    live: c.asks.filter((a: CollabAsk) => ASK_LIVE.has(a.state)).length,
  };
}

/** 按 key 合并两份协作（后来的覆盖先来的），最近动过的在前 */
export function mergeCollabs(prev: readonly CollabView[] | undefined, next: readonly CollabView[] | undefined): CollabView[] {
  const by = new Map<string, CollabView>();
  for (const c of prev ?? []) by.set(c.key, c);
  for (const c of next ?? []) by.set(c.key, c);
  return [...by.values()].sort((a: CollabView, b: CollabView) => b.updated_at - a.updated_at);
}

/* ---- 大厅、话题页：协作往返、协助方的回执放进对话的哪里 ---- */

const timeOf = (t: TurnView): number | null => t.started_at ?? t.ended_at ?? null;

function pseudo(kind: 'collab' | 'receipt', c: string, here: string, at: number, extra: Partial<RoomTurn> = {}): RoomTurn {
  return {
    key: `${kind}-${c}`, seq: 0, role: 'event', status: 'done', body: '', job_id: null, started_at: at || null, ended_at: at || null,
    artifacts: [], topic_key: here, room_at: at, synth: kind, ref: c, ...extra,
  };
}

/** 放到时刻 at 该在的位置：最后一个不晚于它的行后面 */
function insertAt(rows: RoomTurn[], row: RoomTurn, at: number): void {
  let i: number = rows.length;
  while (i > 0) {
    const t: number | null = timeOf(rows[i - 1]);
    if (t === null || t <= at) break;
    i -= 1;
  }
  rows.splice(i, 0, row);
}

/**
 * 话题页的对话里放进协作：
 * - 这个话题汇总的：一块“协作往返”，放在发起它的那句话后面（那一轮带 collab 或消息 id 对得上根请求），对不上就按协作开始的时刻放；
 * - 这个话题协助的：答咨询的那几行（collab.role = helper，含回执行）收成一行回执，放在第一行的位置，不当它自己的一轮画。
 * 没有协作时原样返回。
 */
export function topicRows(turns: TurnView[], collabs: readonly CollabView[], here: string): RoomTurn[] {
  const rows: RoomTurn[] = turns.map((t: TurnView): RoomTurn => ({ ...t, topic_key: t.topic_key ?? here, room_at: timeOf(t) ?? 0 }));
  if (!collabs.length && !turns.some((t: TurnView) => t.collab)) return rows;
  const by = new Map<string, CollabView>(collabs.map((c: CollabView) => [c.key, c]));
  const out: RoomTurn[] = [];
  const receipts = new Map<string, RoomTurn>();
  const placed = new Set<string>();
  for (const t of rows) {
    const c = t.collab;
    if (c?.role === 'helper') {
      let r: RoomTurn | undefined = receipts.get(c.key);
      if (!r) {
        r = pseudo('receipt', c.key, here, t.room_at, { rows: [], seq: t.seq });
        receipts.set(c.key, r);
        out.push(r);
      }
      r.rows = [...(r.rows ?? []), t];
      continue;
    }
    const mine: CollabView | undefined = [...by.values()].find((x: CollabView) => x.integrator === here && !placed.has(x.key)
      && ((c?.role === 'integrator' && c.key === x.key) || (!!t.message_id && t.message_id === x.root.message_id)));
    if (mine) {
      placed.add(mine.key);
      const block: RoomTurn = pseudo('collab', mine.key, here, t.room_at);
      if (t.role === 'owner') out.push(t, block);
      else out.push(block, t);
      continue;
    }
    out.push(t);
  }
  for (const c of collabs) {
    if (c.integrator === here && !placed.has(c.key)) insertAt(out, pseudo('collab', c.key, here, c.created_at), c.created_at);
    else if (c.integrator !== here && c.helpers.includes(here) && !receipts.has(c.key)) {
      insertAt(out, pseudo('receipt', c.key, here, c.created_at, { rows: [] }), c.created_at);
    }
  }
  return out;
}

/**
 * 大厅里放进协作往返：在发起它的那句话后面（网页发的按根请求 web-<op_id> 对上发件行，其余按带 collab 或消息 id 的你那一行），
 * 那句话写“→ T5 汇总 · 协助 …”；对不上的按协作开始的时刻放。最后从 1 重新编号（同 buildRoom）。
 */
export function roomCollabs(rows: RoomTurn[], collabs: readonly CollabView[], snap: SnapshotResponse | undefined, butler: string | null): RoomTurn[] {
  if (!collabs.length) return rows;
  const out: RoomTurn[] = [...rows];
  for (const c of [...collabs].sort((a: CollabView, b: CollabView) => a.created_at - b.created_at)) {
    const mid: string = c.root.message_id ?? '';
    const op: string = mid.startsWith('web-') ? mid.slice(4) : '';
    let i: number = op ? out.findIndex((r: RoomTurn) => r.key === `ob-${op}`) : -1;
    if (i < 0) {
      i = out.findIndex((r: RoomTurn) => r.role === 'owner' && !r.synth
        && ((r.collab?.key === c.key) || (!!mid && r.message_id === mid)));
    }
    const targets: string[] = [c.integrator, ...c.helpers];
    if (i >= 0) {
      out[i] = { ...out[i], route: collabRoute(c.integrator, c.helpers, snap, butler), routeView: { to: [], integrator: c.integrator, helpers: [...c.helpers] }, targets };
      out.splice(i + 1, 0, pseudo('collab', c.key, c.integrator, out[i].room_at, { targets }));
      continue;
    }
    const block: RoomTurn = pseudo('collab', c.key, c.integrator, c.created_at, { targets });
    let j: number = out.length;
    while (j > 0 && out[j - 1].room_at > c.created_at) j -= 1;
    out.splice(j, 0, block);
  }
  return out.map((t: RoomTurn, k: number) => ({ ...t, seq: k + 1 }));
}

/** 一组：你说的几句 + 回答（event 行、补出来的行单独一组）。协作往返、回执前面的话先成一组，好让它们排在那句话后面 */
export interface Group {
  owner: TurnView[];
  agent: TurnView | null;
  n: number;
}

export function groupTurns(rows: TurnView[]): Group[] {
  const out: Group[] = [];
  let owner: TurnView[] = [];
  let n = 0;
  for (const t of rows) {
    const synth: string | undefined = (t as RoomTurn).synth;
    // v19：主人编辑的那一行已经并进原消息那一行，不再单画
    if (t.role === 'owner') {
      if (!t.merged) owner.push(t);
    } else if (t.role === 'event') {
      if ((synth === 'collab' || synth === 'receipt') && owner.length) {
        out.push({ owner, agent: null, n: 0 });
        owner = [];
      }
      out.push({ owner: [], agent: t, n: 0 });
    } else {
      n += 1;
      out.push({ owner, agent: t, n });
      owner = [];
    }
  }
  if (owner.length) out.push({ owner, agent: null, n: 0 });
  return out;
}

/** 协助方话题里的一行回执：协助的是哪次协作、汇总方是谁、问的什么、自己答的什么 */
export interface Receipt {
  collab: string;
  /** 汇总方的 key、名字（协作条目还没到时为空） */
  integrator: string;
  name: string;
  /** 已协助（答完了）、正在协助（排着队或在跑）、没接手（未接手、失败、到期、已取消） */
  phase: 'done' | 'live' | 'off';
  word: string;
  /** 汇总方问的（第一次咨询） */
  asked: string;
  /** 这个话题答的：答咨询那一轮的正文，没有就用协作条目里的答复 */
  answer: string;
  /** 没接手、失败、到期、取消的原因 */
  reason: string;
  seq: number;
}

export function receiptOf(row: RoomTurn, c: CollabView | undefined, here: string, snap: SnapshotResponse | undefined, butler: string | null): Receipt {
  const mine: CollabAsk[] = (c?.asks ?? []).filter((a: CollabAsk) => a.to === here);
  const last: CollabAsk | undefined = mine[mine.length - 1];
  const agent: TurnView | undefined = [...(row.rows ?? [])].reverse().find((t: TurnView) => t.role !== 'owner' && t.role !== 'event');
  const running: boolean = !!agent && agent.status === 'running';
  const phase: Receipt['phase'] = running || (!!last && ASK_LIVE.has(last.state)) ? 'live'
    : last && !last.reply && !['replied', 'read'].includes(last.state) ? 'off' : 'done';
  const answer: string = agent && agent.status !== 'running' && agent.body.trim() ? agent.body : last?.reply?.text ?? '';
  return {
    collab: row.ref ?? '',
    integrator: c?.integrator ?? '',
    name: c ? nameOf(c.integrator, snap, butler) : '',
    phase,
    word: last ? ASK_WORDS[last.state] ?? last.state : running ? '在做' : '',
    asked: mine[0]?.text ?? '',
    answer,
    reason: last?.reason ?? '',
    seq: row.seq,
  };
}

/** 去看这次协作：汇总方是普通话题就去它的话题页，管家、负责人的在大厅 */
export function collabHref(c: Pick<CollabView, 'key' | 'integrator'>, snap: SnapshotResponse | undefined, butler: string | null): string {
  const who: Participant = participantOf(c.integrator, snap, butler);
  const q = `collab=${encodeURIComponent(c.key)}`;
  return who.role === TOPIC ? `/topics/${encodeURIComponent(c.integrator)}?${q}` : `/butler?${q}`;
}
