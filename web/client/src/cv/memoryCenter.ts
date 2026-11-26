/**
 * 记忆中心（数据约定 v43，MemoryCenter.tsx）的纯函数：拉哪些键、条目归到哪个页签和范围、体检只留非 0 项、每行的灰字（去重）、
 * 17 个 memory_edit 动作的 payload（带 v: 43，动一条时带 base = 条目 rev 做乐观锁）、⌘K 用 memory:index.titles 秒搜、
 * 预览和导入的整理。不碰 DOM、不引别的模块（只有类型）：单测 scripts/memory-center.test.mjs。
 *
 * 做减法（FINAL-SPEC 修订 11）：主导航只有 5 个页签（待审核、规矩、决定、资料、记录），「导入」在顶栏；体检只画非 0 项，
 * 全 0 时一行“暂无异常”；决定默认只看在办的；灰字不重复页签已经说了的，规矩不写“带过 N 轮”；行尾只留「改」和 ⋯。
 */
import type {
  MemoryEditPayloadV43,
  MemoryEntry,
  MemoryGlobalData,
  MemoryHealth,
  MemoryImportItem,
  MemoryIndex,
  MemoryKind,
  MemoryLogItem,
  MemoryPreview,
  MemoryProjectData,
  MemoryReviewItem,
  MemoryScope,
  MemoryScopeSummary,
  MemoryTab,
  MemoryTopicsData,
} from '@shared/api.interface';

/* ---------- 页签 ---------- */
export const TABS: readonly MemoryTab[] = ['review', 'rules', 'decisions', 'notes', 'log'];
export const TAB_WORD: Record<MemoryTab, string> = { review: '待审核', rules: '规矩', decisions: '决定', notes: '资料', log: '记录' };
export const KIND_TAB: Record<MemoryKind, MemoryTab> = { rule: 'rules', decision: 'decisions', note: 'notes' };
export const TAB_KIND: Partial<Record<MemoryTab, MemoryKind>> = { rules: 'rule', decisions: 'decision', notes: 'note' };
export const KIND_WORD: Record<MemoryKind, string> = { rule: '规矩', decision: '决定', note: '资料' };
export const isTab = (v: unknown): v is MemoryTab => typeof v === 'string' && (TABS as readonly string[]).includes(v);

/** 第一眼：有待审核默认停在待审核，否则规矩 */
export const defaultTab = (idx: Pick<MemoryIndex, 'counts'> | null | undefined): MemoryTab => ((idx?.counts.pending ?? 0) > 0 ? 'review' : 'rules');

/** 每个页签顶上至多一行说明（≤30 字）；待审核、记录不写 */
export const TAB_NOTE: Partial<Record<MemoryTab, string>> = {
  rules: '每一轮都全文带上',
  decisions: '在办的决定每轮都带，办完就不带',
  notes: '和这一轮相关才带，每轮至多 5 条',
};

/** 记忆中心的 memory:index（形状不对、不是 v43 的一律当没有） */
export function isMemoryIndex(d: unknown): d is MemoryIndex {
  const o = d as Partial<MemoryIndex> | null;
  return !!o && typeof o === 'object' && o.version === 43 && !!o.counts && Array.isArray(o.scopes) && !!o.revs && typeof o.revs === 'object';
}

/* ---------- 拉哪些键 ---------- */
export interface KeyRev {
  key: string;
  rev: string;
}
/** 页面要的数据键（按 index.revs 的 rev 取，没变就用缓存）：全局、话题汇总、各专项一直要；预览只在打开预览时、导入页只在打开导入时 */
export function keysToLoad(idx: Pick<MemoryIndex, 'revs'> | null | undefined, want: { previews?: boolean; importPage?: number | null } = {}): KeyRev[] {
  if (!idx) return [];
  const out: KeyRev[] = [];
  for (const [key, rev] of Object.entries(idx.revs)) {
    if (!rev || key === 'memory:index') continue;
    if (key === 'memory:global' || key === 'memory:topics' || key.startsWith('memory:p:')) out.push({ key, rev });
    else if (key === 'memory:previews' && want.previews) out.push({ key, rev });
    else if (want.importPage !== undefined && want.importPage !== null && key === `memory:import:${want.importPage}`) out.push({ key, rev });
  }
  return out.sort((a: KeyRev, b: KeyRev) => a.key.localeCompare(b.key));
}
export const projectKeyOf = (key: string): string => (key.startsWith('memory:p:') ? key.slice('memory:p:'.length) : '');

/* ---------- 合成一池 ---------- */
export interface Pool {
  entries: MemoryEntry[];
  review: MemoryReviewItem[];
  log: MemoryLogItem[];
  /** 专项 id → 专项名 */
  projects: Record<string, string>;
  /** 话题 key → T 号和标题 */
  topics: Record<string, { number?: number; title: string }>;
}
export function poolOf(global: MemoryGlobalData | null | undefined, topics: MemoryTopicsData | null | undefined, projects: (MemoryProjectData | null | undefined)[]): Pool {
  const entries: MemoryEntry[] = [...(global?.entries ?? [])];
  const pnames: Record<string, string> = {};
  for (const p of projects) {
    if (!p) continue;
    const id: string = p.key.startsWith('p:') ? p.key.slice(2) : p.key;
    pnames[id] = p.title;
    for (const e of p.entries ?? []) entries.push(e.project_key ? e : { ...e, project_key: id });
  }
  const tnames: Pool['topics'] = {};
  for (const t of topics?.topics ?? []) {
    tnames[t.topic_key] = { number: t.topic_number, title: t.title };
    for (const e of t.entries ?? []) entries.push(e.topic_key ? e : { ...e, topic_key: t.topic_key, topic_number: e.topic_number ?? t.topic_number });
  }
  // 同一条可能出现在两处（专项里的话题条目），按 key 去重，先来的留着
  const seen = new Set<string>();
  const uniq: MemoryEntry[] = entries.filter((e: MemoryEntry) => (seen.has(e.key) ? false : (seen.add(e.key), true)));
  return { entries: uniq, review: global?.review ?? [], log: global?.log ?? [], projects: pnames, topics: tnames };
}

/* ---------- 范围 ---------- */
/** 'all' 全部、'global' 全局、'topics' 话题、'p:<专项 id>' 某个专项（含它的话题？不含：话题条目归“话题”） */
export type ScopeFilter = string;
export const scopeOfEntry = (e: Pick<MemoryEntry, 'scope' | 'project_key'>): string =>
  e.scope === 'global' ? 'global' : e.scope === 'topic' ? 'topics' : `p:${e.project_key ?? ''}`;
export const inScope = (e: Pick<MemoryEntry, 'scope' | 'project_key'>, scope: ScopeFilter): boolean => scope === 'all' || scopeOfEntry(e) === scope;
/** 待审核按建议的去处归范围 */
export const reviewScope = (r: MemoryReviewItem): string =>
  r.suggest.scope === 'global' ? 'global' : r.suggest.scope === 'topic' ? 'topics' : `p:${r.suggest.project_key ?? ''}`;

export interface ScopeOption {
  value: ScopeFilter;
  label: string;
  /** 待审核数（有才画红点和数） */
  pending: number;
  /** 规矩放不下 */
  over: boolean;
}
/** 范围下拉：全部、全局、话题、各专项（按 index.scopes 的顺序） */
export function scopeOptions(idx: Pick<MemoryIndex, 'scopes' | 'counts'> | null | undefined): ScopeOption[] {
  const out: ScopeOption[] = [{ value: 'all', label: '全部范围', pending: idx?.counts.pending ?? 0, over: false }];
  for (const s of idx?.scopes ?? []) {
    out.push({ value: s.key, label: s.key === 'global' ? '全局' : s.key === 'topics' ? '话题' : s.title || s.key, pending: s.counts.pending, over: roomOf(s).tone === 'over' });
  }
  return out;
}

/* ---------- 页签里的条目 ---------- */
export type DecisionView = 'open' | 'all' | 'done';
export const LIVE: readonly string[] = ['active', 'pending'];
const atOf = (e: Pick<MemoryEntry, 'origin'>): number => (typeof e.origin?.at === 'number' ? e.origin.at : 0);
const byNew = (a: MemoryEntry, b: MemoryEntry): number => atOf(b) - atOf(a) || a.code.localeCompare(b.code);

/** 决定在不在办：只认 in_progress（Bridge 判的，FINAL-SPEC 修订 5） */
export const isOpenDecision = (e: Pick<MemoryEntry, 'kind' | 'status' | 'in_progress'>): boolean => e.kind === 'decision' && e.status === 'active' && !!e.in_progress;
const isDoneDecision = (e: Pick<MemoryEntry, 'kind' | 'status' | 'in_progress'>): boolean =>
  e.kind === 'decision' && (e.status === 'done' || (e.status === 'active' && !e.in_progress));

/** 一个页签（规矩、决定、资料）在某个范围下的条目，新的在前；query 按标题、正文、短码筛（不分大小写） */
export function tabEntries(pool: Pick<Pool, 'entries'>, tab: MemoryTab, scope: ScopeFilter, view: DecisionView = 'open', query = ''): MemoryEntry[] {
  const kind: MemoryKind | undefined = TAB_KIND[tab];
  if (!kind) return [];
  const q: string = query.trim().toLowerCase();
  return pool.entries
    .filter((e: MemoryEntry) => e.kind === kind && inScope(e, scope))
    .filter((e: MemoryEntry) => {
      if (kind !== 'decision') return e.status === 'active';
      return view === 'open' ? isOpenDecision(e) : view === 'done' ? isDoneDecision(e) : isOpenDecision(e) || isDoneDecision(e);
    })
    .filter((e: MemoryEntry) => !q || `${e.title}\n${e.text}\n${e.code}`.toLowerCase().includes(q))
    .sort(byNew);
}
/** 收起的（归档、作废）：列表底下“已收起 N 条”，点开能放回 */
export function shelved(pool: Pick<Pool, 'entries'>, tab: MemoryTab, scope: ScopeFilter): MemoryEntry[] {
  const kind: MemoryKind | undefined = TAB_KIND[tab];
  if (!kind) return [];
  return pool.entries.filter((e: MemoryEntry) => e.kind === kind && inScope(e, scope) && (e.status === 'archived' || e.status === 'void')).sort(byNew);
}
/** 决定三档各几条（切换按钮上的数） */
export function decisionCounts(pool: Pick<Pool, 'entries'>, scope: ScopeFilter): Record<DecisionView, number> {
  const ds: MemoryEntry[] = pool.entries.filter((e: MemoryEntry) => e.kind === 'decision' && inScope(e, scope));
  const open: number = ds.filter(isOpenDecision).length;
  const done: number = ds.filter(isDoneDecision).length;
  return { open, done, all: open + done };
}
export function reviewItems(pool: Pick<Pool, 'review'>, scope: ScopeFilter): MemoryReviewItem[] {
  return pool.review.filter((r: MemoryReviewItem) => scope === 'all' || reviewScope(r) === scope).sort((a: MemoryReviewItem, b: MemoryReviewItem) => b.created_at - a.created_at);
}

/* ---------- 体检：只画非 0 项 ---------- */
export const HEALTH_WORD: Record<keyof MemoryHealth, string> = {
  dup: '重复', conflict: '矛盾', vague: '过后读不懂', stale: '可能过期', idle: '很久没用', over_cap: '规矩超额', repo_rule: '该进仓库规范', skill: '可做成技能',
};
const HEALTH_ORDER: (keyof MemoryHealth)[] = ['conflict', 'dup', 'over_cap', 'stale', 'vague', 'idle', 'repo_rule', 'skill'];
export interface HealthRow {
  key: keyof MemoryHealth;
  word: string;
  n: number;
  /** 涉及的条目 key（矛盾是一对一对的，摊平） */
  refs: string[];
}
export function healthRows(h: MemoryHealth | null | undefined): HealthRow[] {
  const out: HealthRow[] = [];
  for (const k of HEALTH_ORDER) {
    const v = h?.[k];
    if (!Array.isArray(v) || !v.length) continue;
    const refs: string[] = (v as (string | string[])[]).flatMap((x: string | string[]) => (Array.isArray(x) ? x : [x])).filter((x: string) => typeof x === 'string' && !!x);
    out.push({ key: k, word: HEALTH_WORD[k], n: v.length, refs: [...new Set(refs)] });
  }
  return out;
}
/** 全 0 时的一行 */
export const HEALTH_OK = '暂无异常';

/* ---------- 每行的灰字（去重） ---------- */
export const BY_WORD: Record<string, string> = {
  owner: '你说的', lead: '负责人记的', butler: '管家记的', learn: '自动学的', import: '导入的', bridge: 'Covey 记的', web: '你在网页记的',
};
/** 谁说的：主人原话是“你说的”，别的写谁记的 */
export const saidWord = (e: Pick<MemoryEntry, 'said' | 'by'>): string => (e.said === 'owner' ? '你说的' : BY_WORD[e.by] ?? '它总结的');
const tno = (n: number | undefined): string => (typeof n === 'number' && n > 0 ? `T${n}` : '');
/** 条目在哪个范围的说法：全局、专项名、T12 */
export function placeWord(e: Pick<MemoryEntry, 'scope' | 'project_key' | 'topic_number' | 'topic_key'>, pool: Pick<Pool, 'projects' | 'topics'>): string {
  if (e.scope === 'global') return '全局';
  if (e.scope === 'project') return pool.projects[e.project_key ?? ''] || '专项';
  return tno(e.topic_number ?? pool.topics[e.topic_key ?? '']?.number) || '话题';
}
/**
 * 一行的灰字，最多 3 项，不重复页签和范围已经说了的：
 * - 谁说的（你说的 / 负责人记的…）；
 * - 范围：只在看“全部范围”时写（选了某个范围，页面顶上已经写了）；
 * - 出处话题 T 号：和范围的 T 号一样就不写；
 * - 决定在“全部”里写在办 / 已办（只看在办时不写）；资料核过的写“核过 MM-DD”。
 * 规矩不写“带过 N 轮”，也不写“规矩”二字（页签已说）。
 */
export function metaLine(e: MemoryEntry, ctx: { scope: ScopeFilter; view?: DecisionView; pool: Pick<Pool, 'projects' | 'topics'> }): string[] {
  const out: string[] = [saidWord(e)];
  const place: string = placeWord(e, ctx.pool);
  if (ctx.scope === 'all') out.push(place);
  const from: string = tno(e.origin?.topic_number);
  if (from && from !== place) out.push(`来自 ${from}`);
  if (e.kind === 'decision' && ctx.view && ctx.view !== 'open') out.push(isOpenDecision(e) ? '在办' : '已办');
  if (e.kind === 'note' && e.verified_at) out.push(`核过 ${mmdd(e.verified_at)}`);
  return out;
}
export const mmdd = (sec: number): string =>
  new Date(sec * 1000).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).replace(/\//gu, '-');

/* ---------- 配额（只在规矩页、每个范围一条） ---------- */
export interface Room {
  used: number;
  limit: number;
  tone: 'ok' | 'near' | 'over';
  words: string;
}
export function roomOf(s: Pick<MemoryScopeSummary, 'rules'>): Room {
  const r = s.rules;
  const ratio: number = Math.max(r.item_limit > 0 ? r.items / r.item_limit : 0, r.char_limit > 0 ? r.chars / r.char_limit : 0);
  const tone: Room['tone'] = ratio > 1 ? 'over' : ratio >= 0.8 ? 'near' : 'ok';
  const extra: number = Math.max(0, r.items - r.item_limit);
  const words: string = `${r.items}/${r.item_limit} 条 · ${r.chars.toLocaleString('en-US')}/${r.char_limit.toLocaleString('en-US')} 字${tone === 'over' ? (extra ? ` · 超出 ${extra} 条，放不下的只列标题` : ' · 超出字数，放不下的只列标题') : ''}`;
  return { used: r.chars, limit: r.char_limit, tone, words };
}

/* ---------- 17 个动作 ---------- */
type Extra = Omit<MemoryEditPayloadV43, 'v' | 'action' | 'keys'>;
const clean = (p: MemoryEditPayloadV43): MemoryEditPayloadV43 => {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') out[k] = v;
  if (!('keys' in out)) out.keys = [];
  return out as unknown as MemoryEditPayloadV43;
};
export const op = (action: MemoryEditPayloadV43['action'], keys: string[], extra: Extra = {}): MemoryEditPayloadV43 => clean({ v: 43, action, keys, ...extra });
/** 去处：范围和它的专项或话题 */
export interface Place {
  scope: MemoryScope;
  project_key?: string;
  topic_key?: string;
}
const placeOf = (p: Place): Extra => ({ scope: p.scope, ...(p.scope === 'project' ? { project_key: p.project_key } : {}), ...(p.scope === 'topic' ? { topic_key: p.topic_key } : {}) });

export const addOp = (d: { title: string; text: string; kind: MemoryKind; why?: string } & Place): MemoryEditPayloadV43 =>
  op('add', [], { title: d.title.trim(), text: d.text.trim(), kind: d.kind, why: d.why?.trim(), ...placeOf(d) });
/** 改：带 kind（决定正文能到 600 字，服务端按它数）和 base（乐观锁） */
export const editOp = (e: Pick<MemoryEntry, 'key' | 'kind' | 'rev'>, d: { title: string; text: string; why?: string }): MemoryEditPayloadV43 =>
  op('edit', [e.key], { title: d.title.trim(), text: d.text.trim(), why: d.why?.trim(), kind: e.kind, base: e.rev });
export const moveOp = (e: Pick<MemoryEntry, 'key' | 'rev'>, to: Place): MemoryEditPayloadV43 => op('move', [e.key], { ...placeOf(to), base: e.rev });
export const archiveOp = (e: Pick<MemoryEntry, 'key' | 'rev'>): MemoryEditPayloadV43 => op('archive', [e.key], { base: e.rev });
export const restoreOp = (e: Pick<MemoryEntry, 'key' | 'rev'>): MemoryEditPayloadV43 => op('restore', [e.key], { base: e.rev });
export const voidOp = (e: Pick<MemoryEntry, 'key' | 'rev'>, why?: string): MemoryEditPayloadV43 => op('void', [e.key], { why, base: e.rev });
/** 提到更大的范围：话题 → 它的专项（没有专项就全局），专项 → 全局 */
export function promoteTarget(e: Pick<MemoryEntry, 'scope' | 'project_key'>, topicProject?: string): Place | null {
  if (e.scope === 'global') return null;
  if (e.scope === 'topic') return topicProject || e.project_key ? { scope: 'project', project_key: topicProject || e.project_key } : { scope: 'global' };
  return { scope: 'global' };
}
export const promoteOp = (e: Pick<MemoryEntry, 'key' | 'rev' | 'repos'>, to: Place): MemoryEditPayloadV43 =>
  op('promote', [e.key], { ...placeOf(to), ...(e.repos?.length ? { repos: e.repos.slice(0, 10) } : {}), base: e.rev });
/** 采纳：可以先改标题、正文、类别、范围 */
export const acceptOp = (r: MemoryReviewItem, d: Partial<{ title: string; text: string; kind: MemoryKind } & Place> = {}): MemoryEditPayloadV43 => {
  const title: string | undefined = d.title !== undefined && d.title.trim() !== r.title ? d.title.trim() : undefined;
  const text: string | undefined = d.text !== undefined && d.text.trim() !== r.text ? d.text.trim() : undefined;
  const kind: MemoryKind = d.kind ?? r.suggest.kind;
  const place: Place = d.scope ? { scope: d.scope, project_key: d.project_key, topic_key: d.topic_key } : { scope: r.suggest.scope, project_key: r.suggest.project_key };
  return op('accept', [r.key], { title, text, kind, ...placeOf(place) });
};
export const rejectOp = (r: Pick<MemoryReviewItem, 'key'>): MemoryEditPayloadV43 => op('reject', [r.key]);
/** 全部采纳 / 全部不要：带上眼前这几条的 key（不发空数组：发出去之后才来的不算你看过） */
export const allOp = (action: 'accept_all' | 'reject_all', items: Pick<MemoryReviewItem, 'key'>[]): MemoryEditPayloadV43 =>
  op(action, items.map((r: Pick<MemoryReviewItem, 'key'>) => r.key).slice(0, 200));
/** 矛盾：左边是已有的那条（conflict_with），右边是新来的 */
export const keepOp = (side: 'keep_left' | 'keep_right' | 'keep_both', r: Pick<MemoryReviewItem, 'key' | 'conflict_with'>): MemoryEditPayloadV43 =>
  op(side, [r.conflict_with ?? '', r.key].filter(Boolean));
export const importOp = (fps: string[], d?: { kind?: MemoryKind } & Partial<Place>): MemoryEditPayloadV43 =>
  op('import', fps.slice(0, 200), d?.scope ? { kind: d.kind, ...placeOf(d as Place) } : { kind: d?.kind });
export const ignoreOp = (fps: string[]): MemoryEditPayloadV43 => op('ignore', fps.slice(0, 200));
export const undoOp = (token: string): MemoryEditPayloadV43 => op('undo', [], { undo_token: token });

/** 字数（和 Covey 一样按字符数） */
export const charCount = (s: string): number => Array.from(s).length;
/** 标题、正文、原因的上限（index.limits 没有就用契约的 40/200/600） */
export function limitsOf(idx: Pick<MemoryIndex, 'limits'> | null | undefined, kind: MemoryKind): { title: number; text: number; why: number } {
  const l = idx?.limits;
  return { title: l?.title ?? 40, text: kind === 'decision' ? (l?.decision_text ?? 600) : (l?.text ?? 200), why: 200 };
}
/** 编辑框能不能存：返回原因，能存是空串 */
export function draftProblem(d: { title: string; text: string; why?: string }, lim: { title: number; text: number; why: number }): string {
  if (!d.title.trim()) return '要写标题';
  if (!d.text.trim()) return '要写正文';
  if (charCount(d.title.trim()) > lim.title) return `标题最多 ${lim.title} 字`;
  if (charCount(d.text.trim()) > lim.text) return `正文最多 ${lim.text} 字`;
  if (d.why && charCount(d.why.trim()) > lim.why) return `原因最多 ${lim.why} 字`;
  return '';
}

/* ---------- ⌘K：标题表秒搜 ---------- */
export interface TitleHit {
  code: string;
  title: string;
  key: string;
}
/** 短码完全一样的最前，再短码开头、标题包含；最多 n 条 */
export function searchTitles(titles: MemoryIndex['titles'] | null | undefined, query: string, n = 8): TitleHit[] {
  const q: string = query.trim().toLowerCase();
  if (!q || !titles) return [];
  const scored: [number, TitleHit][] = [];
  for (const row of titles) {
    if (!Array.isArray(row) || row.length < 3) continue;
    const [code, title, key] = row;
    const c: string = String(code).toLowerCase();
    const t: string = String(title).toLowerCase();
    const s: number = c === q ? 0 : c.startsWith(q) ? 1 : t.startsWith(q) ? 2 : t.includes(q) ? 3 : -1;
    if (s >= 0) scored.push([s, { code: String(code), title: String(title), key: String(key) }]);
  }
  return scored.sort((a, b) => a[0] - b[0]).slice(0, n).map((x) => x[1]);
}
/** 短码在哪个页签（R 规矩、D 决定、N 资料） */
export const tabOfCode = (code: string): MemoryTab => ({ R: 'rules', D: 'decisions', N: 'notes' } as Record<string, MemoryTab>)[code.charAt(0).toUpperCase()] ?? 'rules';
/** 记忆中心里某一条的链接 */
export const codeHref = (code: string): string => `/memory?code=${encodeURIComponent(code)}`;

/* ---------- 下一轮带什么（memory:previews） ---------- */
export interface PreviewSection {
  key: 'rules' | 'decisions' | 'notes' | 'listed';
  word: string;
  rows: { code: string; title: string; why: string }[];
}
export function previewSections(p: MemoryPreview, titleOf: (code: string) => string): PreviewSection[] {
  const row = (code: string, why: string) => ({ code, title: titleOf(code) || code, why });
  return [
    { key: 'rules' as const, word: '规矩', rows: p.rules.map((c: string) => row(c, '规矩全带')) },
    { key: 'decisions' as const, word: '决定', rows: p.decisions.map((c: string) => row(c, '在办')) },
    { key: 'notes' as const, word: '资料', rows: p.notes.map((n: { code: string; sim: number }) => row(n.code, `相关 ${n.sim.toFixed(2)}`)) },
    { key: 'listed' as const, word: '没带全文，只列标题', rows: p.listed.map((c: string) => row(c, '')) },
  ].filter((s: PreviewSection) => s.rows.length);
}
/** 短码 → 标题：先查已经拉到的条目，再查 ⌘K 的标题表 */
export function titleIndex(entries: Pick<MemoryEntry, 'code' | 'title'>[], titles: MemoryIndex['titles'] | null | undefined): Map<string, string> {
  const m = new Map<string, string>();
  for (const row of titles ?? []) if (Array.isArray(row) && row[0]) m.set(String(row[0]), String(row[1] ?? ''));
  for (const e of entries) m.set(e.code, e.title);
  return m;
}

/* ---------- 导入（memory:import:<页>） ---------- */
export const HARNESS_WORD: Record<string, string> = { claude_code: 'Claude Code', codex: 'Codex', antigravity: 'Antigravity' };
/** 默认勾不勾：新的、不重复、不是旧仓库的才勾 */
export const importChecked = (it: Pick<MemoryImportItem, 'state' | 'dup_of' | 'old_repo'>): boolean => it.state === 'new' && !it.dup_of && !it.old_repo;
export interface ImportGroup {
  label: string;
  items: MemoryImportItem[];
}
/** 按来源分组：“Claude Code · demo-repo”；组内新的在前 */
export function importGroups(items: MemoryImportItem[]): ImportGroup[] {
  const groups = new Map<string, MemoryImportItem[]>();
  for (const it of items) {
    const label: string = [HARNESS_WORD[it.harness] ?? it.harness, it.repo || it.bucket].filter(Boolean).join(' · ');
    groups.set(label, [...(groups.get(label) ?? []), it]);
  }
  const rank = (it: MemoryImportItem): number => (it.state === 'new' ? 0 : it.state === 'imported' ? 1 : 2);
  return [...groups.entries()].map(([label, rows]) => ({ label, items: [...rows].sort((a, b) => rank(a) - rank(b)) }));
}
export const IMPORT_STATE_WORD: Record<MemoryImportItem['state'], string> = { new: '', imported: '已导入', ignored: '留在原工具' };
/** 每行的灰字：类型 · 建议去处 · 已在记忆里 / 旧仓库 */
export function importMeta(it: MemoryImportItem, pool: Pick<Pool, 'projects'>): string[] {
  const to: string = `${KIND_WORD[it.suggest.kind]}·${it.suggest.scope === 'global' ? '全局' : it.suggest.scope === 'project' ? pool.projects[it.suggest.project_key ?? ''] || '专项' : '话题'}`;
  return [it.file_tail, `建议记成${to}`, it.dup_of ? '已在记忆里' : '', it.old_repo ? '旧仓库' : '', IMPORT_STATE_WORD[it.state]].filter(Boolean);
}

/* ---------- 记录 ---------- */
export const ACTION_WORD: Record<string, string> = {
  add: '记下', edit: '改了', move: '换了范围', archive: '归档', restore: '放回', void: '作废', accept: '采纳', reject: '不要',
  accept_all: '全部采纳', reject_all: '全部不要', keep_left: '留旧的', keep_right: '留新的', keep_both: '两条都留', promote: '提到更大范围',
  import: '导入', ignore: '留在原工具', undo: '撤销',
};
export const WHO_WORD: Record<string, string> = { owner: '你', lead: '负责人', butler: '管家', learn: '自动学习', import: '导入', bridge: 'Covey', web: '你' };
export function logLine(l: MemoryLogItem): { who: string; action: string; title: string; because: string } {
  const because: string = l.because ? [tno(l.because.topic_number), l.because.quote ? `“${l.because.quote}”` : ''].filter(Boolean).join(' ') : '';
  return { who: WHO_WORD[l.who] ?? l.who, action: ACTION_WORD[l.action] ?? l.action, title: l.title, because };
}

/* ---------- 待审核 ---------- */
export const REVIEW_WORD: Record<string, string> = {
  learn: '从你的话里学到', candidate: '晚间候选', lead: '负责人提的', import: '导入的', conflict: '和已有的矛盾', tidy: '整理建议', class3: '同类问了 3 次', migrate: '迁移时带过来的',
};
export const FLAG_WORD: Record<string, string> = { vague: '过后可能读不懂', dynamic: '写的是会变的现状', repeat: '说过不止一次', old_repo: '旧仓库' };
export function reviewMeta(r: MemoryReviewItem, pool: Pick<Pool, 'projects'>): string[] {
  const to: string = r.suggest.scope === 'global' ? '全局' : r.suggest.scope === 'project' ? pool.projects[r.suggest.project_key ?? ''] || '专项' : '话题';
  return [REVIEW_WORD[r.type] ?? r.type, `建议记成${KIND_WORD[r.suggest.kind]}·${to}`, tno(r.from?.topic_number), ...(r.flags ?? []).map((f: string) => FLAG_WORD[f] ?? f)].filter(Boolean);
}

/* ---------- 链接进来：/memory?code=…&scope=… ---------- */
/** 找短码对应的条目（它的页签、要不要切到“全部决定”才看得见） */
export function locate(pool: Pick<Pool, 'entries'>, code: string): { entry: MemoryEntry; tab: MemoryTab; view: DecisionView } | null {
  const e: MemoryEntry | undefined = pool.entries.find((x: MemoryEntry) => x.code.toLowerCase() === code.toLowerCase());
  if (!e) return null;
  const tab: MemoryTab = KIND_TAB[e.kind];
  return { entry: e, tab, view: e.kind === 'decision' && !isOpenDecision(e) ? 'all' : 'open' };
}

/* ---------- 专项页、话题页右栏的精简清单（MemoryList） ---------- */
export interface Brief {
  rules: MemoryEntry[];
  decisions: MemoryEntry[];
  notes: number;
  counts: { rules: number; decisions: number; notes: number };
}
/** 一组条目的精简看法：规矩和在办决定各至多 n 条，资料只给个数 */
export function briefOf(entries: MemoryEntry[] | null | undefined, n = 6): Brief {
  const live: MemoryEntry[] = (entries ?? []).filter((e: MemoryEntry) => e.status === 'active');
  const rules: MemoryEntry[] = live.filter((e: MemoryEntry) => e.kind === 'rule').sort(byNew);
  const decisions: MemoryEntry[] = live.filter(isOpenDecision).sort(byNew);
  const notes: number = live.filter((e: MemoryEntry) => e.kind === 'note').length;
  return { rules: rules.slice(0, n), decisions: decisions.slice(0, n), notes, counts: { rules: rules.length, decisions: decisions.length, notes } };
}
export const briefLine = (b: Brief): string =>
  [b.counts.rules ? `规矩 ${b.counts.rules}` : '', b.counts.decisions ? `在办决定 ${b.counts.decisions}` : '', b.counts.notes ? `资料 ${b.counts.notes}` : ''].filter(Boolean).join(' · ');
