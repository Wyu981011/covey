/* 主记忆页（v37，设置页「记忆」，MainMemory.tsx）的纯函数：筛选和搜索、字数（和 Covey 的 clean_text 一样数）、配额的状态、
   草稿能不能存、发给 Covey 的 memory_edit 载荷、几处说法。没有 DOM、没有请求，scripts/main-memory.test.mjs 测它们。 */
import type { MainMemoryData, MainMemoryEntry, MainMemoryGroup, MemoryEditPayload } from '@shared/api.interface';

/** 筛选：全部、全局，或某个工作区（w:<名字>） */
export type ScopeFilter = 'all' | 'global' | `w:${string}`;

/** 和 Covey 存的一样：空白（含换行）收成一个空格、去掉首尾 */
export const cleanText = (text: string): string => text.split(/\s+/u).filter(Boolean).join(' ');

/** 字数按 Covey 数的：收好空白以后的字符数（emoji、中文都算一个） */
export const charCount = (text: string): number => Array.from(cleanText(text)).length;

export interface DraftCheck {
  ok: boolean;
  /** 不能存时的一句话（空、超长）；能存是空串 */
  why: string;
  count: number;
}

/** 草稿能不能存：不能是空的、不能超过 limit 字 */
export function checkDraft(text: string, limit: number): DraftCheck {
  const count: number = charCount(text);
  if (!count) return { ok: false, why: '正文是空的', count };
  if (count > limit) return { ok: false, why: `超出 ${count - limit} 字（最多 ${limit} 字）`, count };
  return { ok: true, why: '', count };
}

/** 筛选下拉的选项：全部、全局，再是有条目的工作区 */
export function scopeOptions(groups: readonly MainMemoryGroup[]): { value: ScopeFilter; label: string; count: number }[] {
  const out: { value: ScopeFilter; label: string; count: number }[] = [
    { value: 'all', label: '全部', count: groups.reduce((n: number, g: MainMemoryGroup) => n + g.entries.length, 0) },
  ];
  for (const g of groups) {
    out.push(g.scope === 'global'
      ? { value: 'global', label: '全局', count: g.entries.length }
      : { value: `w:${g.workspace}`, label: g.workspace, count: g.entries.length });
  }
  return out;
}

const matches = (e: MainMemoryEntry, q: string): boolean =>
  !q || e.text.toLowerCase().includes(q) || (e.why ?? '').toLowerCase().includes(q) || e.origin.toLowerCase().includes(q)
  || (e.quote ?? '').toLowerCase().includes(q) || (e.topic ?? '').toLowerCase().includes(q);

/** 按筛选和搜索留下的组和条目；搜索不分大小写，查正文、原因、来源和原话。组没剩条目时：有搜索词就不列，没有就照列（空组也要能新建） */
export function filterGroups(groups: readonly MainMemoryGroup[], scope: ScopeFilter, query: string): MainMemoryGroup[] {
  const q: string = query.trim().toLowerCase();
  return groups
    .filter((g: MainMemoryGroup) => scope === 'all' || (scope === 'global' ? g.scope === 'global' : g.scope === 'workspace' && scope === `w:${g.workspace}`))
    .map((g: MainMemoryGroup) => ({ ...g, entries: g.entries.filter((e: MainMemoryEntry) => matches(e, q)) }))
    .filter((g: MainMemoryGroup) => !q || g.entries.length > 0);
}

/** 正文里搜索词的位置，给高亮用：[[开始, 结束]]，不分大小写 */
export function hitRanges(text: string, query: string): [number, number][] {
  const q: string = query.trim().toLowerCase();
  if (!q) return [];
  const lower: string = text.toLowerCase();
  const out: [number, number][] = [];
  let at: number = lower.indexOf(q);
  while (at >= 0) {
    out.push([at, at + q.length]);
    at = lower.indexOf(q, at + q.length);
  }
  return out;
}

export type Room = 'ok' | 'near' | 'full' | 'over';

/** 一组的配额：ok；near 用了八成以上；full 有放不下的（下一轮不带）；over 常驻的就超了上限（照样都带，再记的放不下） */
export function roomOf(g: Pick<MainMemoryGroup, 'used' | 'limit' | 'left'>): Room {
  if (g.left > 0) return 'full';
  if (g.used > g.limit) return 'over';
  if (g.used >= 0.8 * g.limit) return 'near';
  return 'ok';
}

/** 配额一行的说法 */
export function roomWords(g: Pick<MainMemoryGroup, 'used' | 'limit' | 'left'>): string {
  const room: Room = roomOf(g);
  if (room === 'full') return `放不下 ${g.left} 条：下一轮不带它们（标灰的，是最近没用到的）。原则可以标常驻一直带上；用不着的删掉或作废`;
  if (room === 'over') return '常驻的已超过上限，照样都带上；这一组再记的会放不下';
  if (room === 'near') return '快满了：再记新的，最近没用到的会放不下';
  return '下一轮都带上';
}

/** 配额条的宽度（百分比，最多 100） */
export const roomPercent = (g: Pick<MainMemoryGroup, 'used' | 'limit'>): number => (g.limit > 0 ? Math.min(100, Math.round((g.used / g.limit) * 100)) : 0);

/** 一条的标签：原则、知识条目的种类，或候选 */
export function kindLabel(e: Pick<MainMemoryEntry, 'kind' | 'knowledge_kind'>, kinds: MainMemoryData['kinds'] = []): string {
  if (e.kind === 'principle') return '原则';
  if (e.kind === 'candidate') return '候选';
  const k = (kinds ?? []).find((x: { value: string; text: string }) => x.value === e.knowledge_kind);
  return k ? `知识 · ${k.text}` : '知识';
}

/** 行上的字数：正文自己的字数（和编辑框里数的一样）；旧版 Covey 没推 size 就按正文数 */
export const sizeOf = (e: Pick<MainMemoryEntry, 'text' | 'size'>): number => (typeof e.size === 'number' ? e.size : charCount(e.text));

/** 行上字数的说明：正文几字，占这一组额度几字（额度还算编号、标注） */
export const sizeTitle = (e: Pick<MainMemoryEntry, 'text' | 'size' | 'chars'>): string => `正文 ${sizeOf(e)} 字；占这一组的额度 ${e.chars} 字（额度还算每条的编号和标注）`;

/** 谁说的 */
export const byWords = (by: MainMemoryEntry['by']): string => (by === 'owner' ? '你说的' : '它总结的');

/** 几时记的：今天写“今天 14:02”，今年写“11/20”，更早写“2025/11/20”（秒级时间戳，按页面所在时区） */
export function whenWords(at: number, now: number = Date.now() / 1000): string {
  if (!at) return '';
  const d = new Date(at * 1000);
  const n = new Date(now * 1000);
  const pad = (v: number): string => String(v).padStart(2, '0');
  if (d.toDateString() === n.toDateString()) return `今天 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.getFullYear() === n.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()}`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/** 页面级回执：办好的操作回给主人的一句话，条目可能已经从列表里消失，所以挂在列表上方 */
export interface Notice {
  id: number;
  message: string;
}

/** 办好了要在页面上方留回执的操作：行会消失或换 id 的（删、作废、记下、不用、改、新建）；常驻只在行上写 */
export const noticeAction = (payload: Pick<MemoryEditPayload, 'action'>): boolean => payload.action !== 'pin' && payload.action !== 'unpin';

/** 新建一条的载荷 */
export function addPayload(what: 'principle' | 'knowledge', scope: string, text: string, knowledgeKind = 'fact', why = ''): MemoryEditPayload {
  const workspace: string = scope === 'global' ? '' : scope.replace(/^w:/u, '');
  const p: MemoryEditPayload = { action: 'add', what, scope: scope === 'global' ? 'global' : 'workspace', text: cleanText(text) };
  if (workspace) p.workspace = workspace;
  if (what === 'knowledge') {
    p.knowledge_kind = knowledgeKind;
    if (cleanText(why)) p.why = cleanText(why);
  }
  return p;
}

/** 改一条的载荷：base 是改之前看到的正文（Covey 核对，别处刚改过就不覆盖） */
export function editPayload(e: Pick<MainMemoryEntry, 'key' | 'text' | 'kind' | 'knowledge_kind' | 'why'>, text: string, knowledgeKind?: string, why?: string): MemoryEditPayload {
  const p: MemoryEditPayload = { action: 'edit', key: e.key, text: cleanText(text), base: e.text };
  if (e.kind === 'knowledge') {
    if (knowledgeKind && knowledgeKind !== e.knowledge_kind) p.knowledge_kind = knowledgeKind;
    if (why !== undefined && cleanText(why) !== (e.why ?? '')) p.why = cleanText(why);
  }
  return p;
}

/** 草稿和原来的比有没有改动（未保存提醒用） */
export function edited(e: Pick<MainMemoryEntry, 'text' | 'kind' | 'knowledge_kind' | 'why'>, text: string, knowledgeKind?: string, why?: string): boolean {
  if (cleanText(text) !== e.text) return true;
  if (e.kind !== 'knowledge') return false;
  return (knowledgeKind !== undefined && knowledgeKind !== e.knowledge_kind) || (why !== undefined && cleanText(why) !== (e.why ?? ''));
}

/** 预览下拉的选项：Covey 推了预览的工作区，默认的在前 */
export function previewOptions(data: Pick<MainMemoryData, 'previews' | 'default'>): string[] {
  const names: string[] = Object.keys(data.previews ?? {});
  const d: string = data.default ?? '';
  return d && names.includes(d) ? [d, ...names.filter((n: string) => n !== d)] : names;
}

/** 新建时“记在哪”的选项：全局，再是全部工作区（默认的在前） */
export function placeOptions(data: Pick<MainMemoryData, 'workspaces' | 'default'>): { value: string; label: string }[] {
  const names: string[] = data.workspaces ?? [];
  const d: string = data.default ?? '';
  const order: string[] = d && names.includes(d) ? [d, ...names.filter((n: string) => n !== d)] : names;
  return [{ value: 'global', label: '全局（所有话题和管家）' }, ...order.map((n: string) => ({ value: `w:${n}`, label: `工作区 ${n}` }))];
}
