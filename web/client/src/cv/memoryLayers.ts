/**
 * 三层记忆的读法（包 E，docs/web.md「协作与三层记忆」，方案 6.4“面板的主轴改为现在怎么用”）：纯函数。
 * - 主轴是长期约定｜当前决定｜历史记录（layer）；每层里再按一轮带它的那一段（part，Covey core/memory.py）分开：
 *   主人的话是已确认的规则、你定的当前决定，别人记的是待核对参考，不冒充主人的要求；风格行单列“写法”。
 * - “你说的 / 它总结的”只作来源标签和筛选：跟着 asserted_by（旧数据看 said_by）；没有出处的主人原话（level 不是 owner）照样说明。
 * - 旧数据没有 layer：面板照旧画（isLayered 为 false）；新旧混着的，没分层的放进“还没分层”。没有 part 的按 level 分。
 */
import type { MemoryApplies, MemoryItem, MemoryOrigin } from '@shared/api.interface';

export type LayerKey = 'rule' | 'decision' | 'history' | 'other';
export type PartKey = 'confirmed' | 'reference' | 'style' | 'decision' | 'decision_ref' | 'history' | 'other';
export type Who = 'all' | 'you' | 'ai';

export const LAYER_TITLE: Record<LayerKey, string> = { rule: '长期约定', decision: '当前决定', history: '历史记录', other: '还没分层' };
const PART: Record<PartKey, { title: string; hint: string }> = {
  confirmed: { title: '已确认的规则', hint: '你说过、一直照着做的' },
  reference: { title: '待核对参考', hint: '负责人或话题整理的口径，不是你的原话，用之前先核对' },
  style: { title: '写法', hint: '回复和产物的写法' },
  decision: { title: '你定的', hint: '这一批的批准、配置和分工，做完或被替代就退到历史' },
  decision_ref: { title: '待核对参考', hint: '负责人或话题记下的决定、分工，不是你的原话' },
  history: { title: '历史记录', hint: '做完、被替代的，和原来的问答，查依据时看' },
  other: { title: '还没分层', hint: '旧的记忆，Covey 还没给它分层' },
};
export const VALID_WORD: Record<string, string> = { active: '有效', done: '做完', superseded: '被替代', void: '作废' };
const PARTY: Record<string, string> = { owner: '你', butler: '管家', lead: '负责人', topic: '话题', bridge: 'Covey' };

const LAYERS = new Set<string>(['rule', 'decision', 'history']);
const layerOf = (m: MemoryItem): LayerKey => (typeof m.layer === 'string' && LAYERS.has(m.layer) ? (m.layer as LayerKey) : 'other');

/** 推来的记忆有没有分层：一条都没有就照旧画 */
export const isLayered = (list: readonly MemoryItem[]): boolean => list.some((m: MemoryItem) => layerOf(m) !== 'other');

/** 来源等级：有 level 就照它；旧数据退回“你说的”这个标记（旧的 owner、owner_answer、owner_fix 才写它） */
export const levelOf = (m: MemoryItem): 'owner' | 'agent' => (m.level ? (m.level === 'owner' ? 'owner' : 'agent') : m.said_by === '你说的' ? 'owner' : 'agent');

/** 是不是主人的话（来源标签）：跟着 asserted_by，旧数据看 said_by */
export const isOwners = (m: MemoryItem): boolean => (typeof m.asserted_by === 'string' && m.asserted_by ? m.asserted_by === 'owner' : m.said_by === '你说的');

/** 它在哪一段：有 part（Covey 推的）照 part，没有按来源等级；风格行单列 */
export function partOf(m: MemoryItem): PartKey {
  const layer: LayerKey = layerOf(m);
  if (layer === 'history' || layer === 'other') return layer;
  if (layer === 'rule' && m.kind === 'style') return 'style';
  const ref: boolean = typeof m.part === 'string' && m.part ? m.part === 'reference' : levelOf(m) !== 'owner';
  if (layer === 'rule') return ref ? 'reference' : 'confirmed';
  return ref ? 'decision_ref' : 'decision';
}

/** 还算不算数：没写 valid 的当有效 */
export const isLive = (m: MemoryItem): boolean => !m.valid || m.valid === 'active';

/** 来源标签（你说的 / 它总结的）和一句细的：谁说的、谁记下的、有没有对上原话 */
export function sourceOf(m: MemoryItem): { you: boolean; tag: string; detail: string } {
  const you: boolean = isOwners(m);
  const said: string = typeof m.asserted_by === 'string' ? m.asserted_by : '';
  const rec: string = typeof m.recorded_by === 'string' ? m.recorded_by : '';
  let detail: string;
  if (you && levelOf(m) === 'owner') detail = rec && rec !== 'owner' && rec !== 'bridge' ? `你说的，${PARTY[rec] ?? rec}记下` : '你说的，按原话记下';
  else if (you) detail = '你说的，还没找到原话的出处';
  else detail = `${PARTY[said] ?? PARTY[rec] ?? '它'}总结的`;
  return { you, tag: you ? '你说的' : '它总结的', detail };
}

/** 专项的话题下一轮带不带它（Covey 推了 carried 才说） */
export function carriedWord(m: MemoryItem): string {
  if (m.carried === true) return '话题下一轮会带上';
  if (m.carried === false) return isLive(m) && layerOf(m) !== 'history' ? '话题下一轮不带（超出这一段的篇幅）' : '话题下一轮不带';
  return '';
}

/** 适用范围和条件，写成一句；没有是空串 */
export function appliesText(a: MemoryApplies | undefined): string {
  if (typeof a === 'string') return a.trim();
  if (!a || typeof a !== 'object') return '';
  const named: [string, string][] = [['scope', '范围'], ['when', '条件'], ['except', '例外']];
  const out: string[] = [];
  for (const [k, label] of named) if (typeof a[k] === 'string' && (a[k] as string).trim()) out.push(`${label}：${(a[k] as string).trim()}`);
  for (const [k, v] of Object.entries(a)) if (!named.some(([x]) => x === k) && typeof v === 'string' && v.trim()) out.push(v.trim());
  return out.join('；');
}

export interface Part {
  key: PartKey;
  title: string;
  hint: string;
  /** 还有效的，最近的在前 */
  live: MemoryItem[];
  /** 做完、被替代、作废的，默认收着 */
  gone: MemoryItem[];
}
export interface Layer {
  key: LayerKey;
  title: string;
  parts: Part[];
  /** 这一层还有效的条数 */
  count: number;
}

const secOf = (v: number | string | null | undefined): number => {
  if (typeof v === 'number') return v > 1e12 ? v / 1000 : v;
  const t: number = typeof v === 'string' ? Date.parse(v) : NaN;
  return Number.isFinite(t) ? t / 1000 : 0;
};
const byAt = (a: MemoryItem, b: MemoryItem): number => secOf(b.at) - secOf(a.at);

/** 按谁说的筛 */
export function pick(list: readonly MemoryItem[], who: Who): MemoryItem[] {
  return who === 'all' ? [...list] : list.filter((m: MemoryItem) => isOwners(m) === (who === 'you'));
}

/**
 * 几层：长期约定（已确认的规则、待核对参考，有风格行时另有写法）、当前决定（你定的、待核对参考）、历史记录三层总在，“还没分层”有才有。
 * 每段里有效的在前（最近的在上），做完、被替代、作废的收在 gone；历史记录本来就是做完和被替代的，都直接列。
 */
export function layers(list: readonly MemoryItem[], who: Who = 'all'): Layer[] {
  const shown: MemoryItem[] = pick(list, who);
  const part = (key: PartKey): Part => {
    const items: MemoryItem[] = shown.filter((m: MemoryItem) => partOf(m) === key);
    const flat: boolean = key === 'history';
    return { key, ...PART[key], live: (flat ? items : items.filter(isLive)).sort(byAt), gone: flat ? [] : items.filter((m: MemoryItem) => !isLive(m)).sort(byAt) };
  };
  const style: Part = part('style');
  const out: Layer[] = [
    { key: 'rule', title: LAYER_TITLE.rule, parts: [part('confirmed'), part('reference'), ...(style.live.length || style.gone.length ? [style] : [])], count: 0 },
    { key: 'decision', title: LAYER_TITLE.decision, parts: [part('decision'), part('decision_ref')], count: 0 },
    { key: 'history', title: LAYER_TITLE.history, parts: [part('history')], count: 0 },
  ];
  const other: Part = part('other');
  if (other.live.length || other.gone.length) out.push({ key: 'other', title: LAYER_TITLE.other, parts: [other], count: 0 });
  for (const l of out) l.count = l.parts.reduce((n: number, p: Part) => n + p.live.length, 0);
  return out;
}

/** 全部、你说的、它总结的各几条（筛选按钮上的数） */
export function whoCounts(list: readonly MemoryItem[]): Record<Who, number> {
  const you: number = list.filter(isOwners).length;
  return { all: list.length, you, ai: list.length - you };
}

/** 专项的话题下一轮会带上几条（Covey 推了 carried 才有数） */
export function carriedCount(list: readonly MemoryItem[]): number | null {
  return list.some((m: MemoryItem) => typeof m.carried === 'boolean') ? list.filter((m: MemoryItem) => m.carried === true).length : null;
}

/** 一条能做的纠正：作废（只有专项记忆，同专项卡上的“删”）、改条件、只限当次、确认长期；失效了的都不能 */
export function fixesFor(m: MemoryItem, scope: 'project' | 'topic'): { forget: boolean; scope: boolean; once: boolean; confirm: boolean } {
  const ok: boolean = !!m.id && isLive(m);
  const layer: LayerKey = layerOf(m);
  const shaped: boolean = layer === 'rule' || layer === 'decision';
  return {
    // 作废同专项卡上的“删”：历史记录里做完、被替代的也能删；已经作废的不能
    forget: !!m.id && m.valid !== 'void' && scope === 'project',
    scope: ok && shaped,
    once: ok && shaped,
    // 已确认的规则（主人原话、对上了出处）不用再确认；别的（待核对参考、你定的当前决定、没出处的原话）都能由你确认成长期
    confirm: ok && shaped && !(partOf(m) === 'confirmed' && levelOf(m) === 'owner'),
  };
}

/** “查看原文”能去哪：出处有话题（和第几轮）、消息 id 或题才有 */
export function originOf(m: MemoryItem): MemoryOrigin | null {
  const o: MemoryOrigin | undefined = m.origin;
  if (!o) return null;
  return o.topic || o.message_id || o.question ? o : null;
}

/** 主人的原话（出处里带了才有） */
export const quoteOf = (m: MemoryItem): string => (typeof m.origin?.quote === 'string' ? m.origin.quote.trim() : '');

/** 被替代的那条换成了哪条（同一份记忆里找得到才给） */
export function replacedBy(m: MemoryItem, list: readonly MemoryItem[]): MemoryItem | undefined {
  return m.superseded_by ? list.find((x: MemoryItem) => x.id === m.superseded_by) : undefined;
}

/** 一行摘要：去掉每条都有的“主人答：”“主人定：”开头（小标已经说了是谁的话）；全文不动 */
export const summary = (text: string): string => text.replace(/^\s*主人(?:回答|答|定|说)\s*[:：]\s*/u, '');
