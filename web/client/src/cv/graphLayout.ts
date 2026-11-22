/**
 * 专项全图的布局和连线（T550 评审第 9 条）：纯函数，不碰 React，scripts/graph-layout.test.mjs 直接测它。
 *
 * - 话题按看板的分组排成几组（等你、停住了、在做、有结果、排队/空闲、做完），组的顺序固定，空组不画；做完默认折成一张分组卡。
 * - “你”在负责人正上方，交代是一条短竖线；派活先到一条竖直主干，再在每组标题行的高度水平拐进组框，一组一条分支；
 *   等你的回线从等你组的顶边出发，走画布最上方的通道回到“你”的顶边。所以线和线不相交，也不穿过卡片。
 * - 缩放分三档：完整卡、紧凑行（一行“● T552 … · 13 分”）、只剩分组卡。
 *
 * 只用标准语法（类型能被直接擦掉），不在运行时 import 别的模块：测试用 node 直接跑这个文件。
 */

export type GroupKey = 'waiting' | 'stopped' | 'running' | 'result' | 'queued' | 'done';
/** 从上到下的顺序 */
export const GROUP_ORDER: readonly GroupKey[] = ['waiting', 'stopped', 'running', 'result', 'queued', 'done'];

/**
 * 话题归哪一组：跟 Covey 看板走（v6 的 board：同 tone 的 key，空串＝不在看板上）。
 * 停住了、有结果只算看板上列着的，不在看板上的和做完、已停止一起折起来。
 */
export function groupOf(tone: string, board: string | undefined): GroupKey {
  const listed: boolean = typeof board !== 'string' || board === tone;
  if (tone === 'waiting') return 'waiting';
  if (tone === 'stopped') return listed ? 'stopped' : 'done';
  if (tone === 'running' || tone === 'stuck') return 'running';
  if (tone === 'result') return listed ? 'result' : 'done';
  if (tone === 'queued' || tone === 'idle') return 'queued';
  return 'done';
}

/** 0 完整卡，1 紧凑行（等你仍是完整卡），2 除等你外都折成分组卡 */
export type Dense = 0 | 1 | 2;

export interface LTopic {
  key: string;
  group: GroupKey;
  /** 组内从小到大排：等你按开始等的时间、在做按开始时间、做完按结束时间倒序（调用方算好） */
  sort: number;
  /** 排序相同的时候按 T 号 */
  number: number;
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
export type NodeKind = 'you' | 'lead' | 'card' | 'row' | 'fold' | 'empty';
export interface GNode extends Box {
  key: string;
  kind: NodeKind;
  group?: GroupKey;
}
export interface GFrame extends Box {
  group: GroupKey;
  n: number;
  /** 组标题行的中线 */
  headY: number;
}
export type EdgeKind = 'delegate' | 'stub' | 'trunk' | 'branch' | 'wait' | 'flow';
export type Pt = [number, number];
export interface GEdge {
  key: string;
  /** flow 是叠在派活线上的流光（负责人 → 在做组），不算一条线 */
  kind: EdgeKind;
  pts: Pt[];
  group?: GroupKey;
}
export interface GLabel {
  kind: 'delegate' | 'dispatch' | 'wait';
  x: number;
  y: number;
  /** center：以 (x, y) 为中心；left：(x, y) 是左边中点 */
  anchor: 'center' | 'left';
}
export interface GraphLayout {
  nodes: GNode[];
  frames: GFrame[];
  edges: GEdge[];
  labels: GLabel[];
  W: number;
  H: number;
  dense: Dense;
  compact: boolean;
}

export interface LayoutOpts {
  compact: boolean;
  dense: Dense;
  /** 点过的组：默认折着的（做完、第 2 档的组）点了展开，默认展开的点了折起 */
  toggled?: ReadonlySet<GroupKey>;
  hasLead?: boolean;
}

const CARD_W = 252;
const CARD_H = 108;
const CARD_GAP = 16;
const ROW_H = 36;
const ROW_GAP = 8;
const COL_GAP = 24;
const PAD = 12;
const HEAD = 36;
const FOLD_H = 64;

interface Geo {
  you: Box;
  lead: Box;
  trunkX: number;
  areaX: number;
  top: number;
  groupGap: number;
  /** 手机上组框占满一行 */
  frameW: number | null;
  rowW: number;
  foldW: number;
  foldH: number;
}
const DESKTOP: Geo = {
  you: { x: 24, y: 40, w: 150, h: 46 },
  lead: { x: 24, y: 142, w: 232, h: 96 },
  trunkX: 304,
  areaX: 344,
  top: 40,
  groupGap: 28,
  frameW: null,
  rowW: CARD_W,
  foldW: CARD_W,
  foldH: FOLD_H,
};
const MOBILE_W = 360;
const MOBILE: Geo = {
  you: { x: 24, y: 10, w: 120, h: 36 },
  lead: { x: 24, y: 76, w: MOBILE_W - 48, h: 84 },
  trunkX: 12,
  areaX: 24,
  top: 188,
  groupGap: 16,
  frameW: MOBILE_W - 36,
  rowW: MOBILE_W - 36 - 2 * PAD,
  foldW: MOBILE_W - 36,
  foldH: 52,
};

const byOrder = (a: LTopic, b: LTopic): number => a.sort - b.sort || a.number - b.number || (a.key < b.key ? -1 : 1);

function folded(g: GroupKey, dense: Dense, toggled: ReadonlySet<GroupKey>): boolean {
  const byDefault: boolean = g === 'done' || (dense === 2 && g !== 'waiting');
  return toggled.has(g) ? !byDefault : byDefault;
}

export function layout(topics: readonly LTopic[], opts: LayoutOpts): GraphLayout {
  const compact: boolean = opts.compact;
  const dense: Dense = compact ? (Math.max(1, opts.dense) as Dense) : opts.dense;
  const toggled: ReadonlySet<GroupKey> = opts.toggled ?? new Set<GroupKey>();
  const G: Geo = compact ? MOBILE : DESKTOP;
  const you: GNode = { key: 'you', kind: 'you', ...G.you };
  const lead: GNode = { key: 'lead', kind: 'lead', ...G.lead };
  const nodes: GNode[] = [you, lead];
  const frames: GFrame[] = [];
  const edges: GEdge[] = [];
  const labels: GLabel[] = [];
  /** 每组接分支的那个框（组框或分组卡）和分支的高度 */
  const heads: { group: GroupKey | null; box: Box; y: number }[] = [];
  let y: number = G.top;
  let right: number = G.areaX;

  for (const g of GROUP_ORDER) {
    const list: LTopic[] = topics.filter((t: LTopic) => t.group === g).sort(byOrder);
    if (!list.length) continue;
    if (heads.length) y += G.groupGap;
    if (folded(g, dense, toggled)) {
      const box: GNode = { key: `fold:${g}`, kind: 'fold', group: g, x: G.areaX, y, w: G.foldW, h: G.foldH };
      nodes.push(box);
      heads.push({ group: g, box, y: y + box.h / 2 });
      y += box.h;
      right = Math.max(right, box.x + box.w);
      continue;
    }
    const full: boolean = !compact && list.length <= 18 && (dense === 0 || g === 'waiting');
    const cw: number = full ? CARD_W : G.rowW;
    const ch: number = full ? CARD_H : ROW_H;
    const gap: number = full ? CARD_GAP : ROW_GAP;
    const cols: number = compact ? 1 : Math.min(3, Math.ceil(list.length / (full ? 6 : 8)));
    const rows: number = Math.ceil(list.length / cols);
    const fw: number = G.frameW ?? 2 * PAD + cols * cw + (cols - 1) * COL_GAP;
    const fh: number = HEAD + rows * ch + (rows - 1) * gap + PAD;
    const frame: GFrame = { group: g, n: list.length, x: G.areaX, y, w: fw, h: fh, headY: y + 18 };
    frames.push(frame);
    list.forEach((t: LTopic, i: number) => {
      const c: number = i % cols;
      const r: number = Math.floor(i / cols);
      nodes.push({ key: t.key, kind: full ? 'card' : 'row', group: g, x: G.areaX + PAD + c * (cw + COL_GAP), y: y + HEAD + r * (ch + gap), w: cw, h: ch });
    });
    heads.push({ group: g, box: frame, y: frame.headY });
    y += fh;
    right = Math.max(right, frame.x + frame.w);
  }
  if (!heads.length) {
    const w: number = G.frameW ?? CARD_W + 40;
    const box: GNode = { key: 'empty', kind: 'empty', x: G.areaX, y, w, h: 120 };
    nodes.push(box);
    heads.push({ group: null, box, y: y + (compact ? 24 : box.h / 2) });
    y += box.h;
    right = Math.max(right, box.x + w);
  }

  const youC: number = you.x + you.w / 2;
  // 交代：“你”的底边中点竖直往下进负责人顶边
  edges.push({ key: 'delegate', kind: 'delegate', pts: [[youC, you.y + you.h], [youC, lead.y]] });
  labels.push({ kind: 'delegate', x: youC, y: (you.y + you.h + lead.y) / 2, anchor: 'center' });
  // 派活：负责人 → 主干 → 每组一条分支
  const stubY: number = lead.y + lead.h / 2;
  const stubX: number = compact ? lead.x : lead.x + lead.w;
  edges.push({ key: 'stub', kind: 'stub', pts: [[stubX, stubY], [G.trunkX, stubY]] });
  const ys: number[] = [stubY, ...heads.map((h: { y: number }) => h.y)];
  const top: number = Math.min(...ys);
  const bottom: number = Math.max(...ys);
  if (bottom > top) edges.push({ key: 'trunk', kind: 'trunk', pts: [[G.trunkX, top], [G.trunkX, bottom]] });
  for (const h of heads) {
    edges.push({ key: `branch:${h.group ?? 'empty'}`, kind: 'branch', group: h.group ?? undefined, pts: [[G.trunkX, h.y], [h.box.x, h.y]] });
    if (h.group === 'running') edges.push({ key: 'flow:running', kind: 'flow', group: 'running', pts: [[stubX, stubY], [G.trunkX, stubY], [G.trunkX, h.y], [h.box.x, h.y]] });
  }
  if (!compact) labels.push({ kind: 'dispatch', x: lead.x, y: lead.y + lead.h + 16, anchor: 'left' });
  // 等你：从等你组的顶边往上到顶部通道，往左到“你”的中线，再往下进“你”的顶边（手机上不画，“你”卡上写等你几个）
  const wait = heads.find((h: { group: GroupKey | null }) => h.group === 'waiting');
  if (wait && !compact) {
    const lane = 12;
    const wx: number = wait.box.x + Math.min(wait.box.w / 2, CARD_W / 2 + PAD);
    edges.push({ key: 'wait', kind: 'wait', group: 'waiting', pts: [[wx, wait.box.y], [wx, lane], [youC, lane], [youC, you.y]] });
    labels.push({ kind: 'wait', x: (youC + wx) / 2, y: lane, anchor: 'center' });
  }
  const W: number = compact ? MOBILE_W : right + 40;
  const H: number = Math.max(y, lead.y + lead.h + (compact ? 0 : 28)) + (compact ? 20 : 40);
  return { nodes, frames, edges, labels, W, H, dense, compact };
}

/** 直角折线加圆角 */
export function roundedPath(pts: readonly Pt[], r = 8): string {
  if (!pts.length) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i += 1) {
    const [x, y] = pts[i];
    if (i === pts.length - 1) {
      d += ` L${x},${y}`;
      break;
    }
    const [px, py] = pts[i - 1];
    const [nx, ny] = pts[i + 1];
    const a: number = Math.min(r, Math.hypot(x - px, y - py) / 2, Math.hypot(nx - x, ny - y) / 2);
    const ux: number = Math.sign(x - px);
    const uy: number = Math.sign(y - py);
    const vx: number = Math.sign(nx - x);
    const vy: number = Math.sign(ny - y);
    d += ` L${x - ux * a},${y - uy * a} Q${x},${y} ${x + vx * a},${y + vy * a}`;
  }
  return d;
}

/** 画布能完整放进 cw × ch 的缩放，上限 1 */
export function fitZoom(L: GraphLayout, cw: number, ch: number): number {
  if (L.compact) return Math.min(1, (cw - 8) / L.W);
  return Math.min(1, (cw - 32) / L.W, (ch - 32) / L.H);
}

/** 手动缩放到 z 时用哪一档：完整卡里 14px 的字小于 11px 就换紧凑行，再小就只剩分组卡 */
export const denseFor = (z: number): Dense => (z >= 0.75 ? 0 : z >= 0.5 ? 1 : 2);

/** “适应”：先试完整卡，放不下（字会小于 11px）换紧凑行，还放不下（小于 0.5 倍）再折成分组卡 */
export function fitLayout(build: (d: Dense) => GraphLayout, cw: number, ch: number): { L: GraphLayout; z: number } {
  let L: GraphLayout = build(0);
  let z: number = fitZoom(L, cw, ch);
  if (L.compact || z >= 0.75) return { L, z };
  L = build(1);
  z = fitZoom(L, cw, ch);
  if (z >= 0.5) return { L, z };
  L = build(2);
  return { L, z: Math.max(0.3, fitZoom(L, cw, ch)) };
}

/* ---- 验收用：线段相交、线穿卡、卡重叠 ---- */

type Seg = [Pt, Pt];
export function segments(L: GraphLayout): { key: string; seg: Seg }[] {
  const out: { key: string; seg: Seg }[] = [];
  for (const e of L.edges) {
    if (e.kind === 'flow') continue;
    for (let i = 1; i < e.pts.length; i += 1) out.push({ key: e.key, seg: [e.pts[i - 1], e.pts[i]] });
  }
  return out;
}

const inside = (v: number, a: number, b: number): boolean => v > Math.min(a, b) + 1e-6 && v < Math.max(a, b) - 1e-6;

/** 两条横竖线段在两者内部相交（T 形接头、共用端点不算） */
export function crosses(a: Seg, b: Seg): boolean {
  const av: boolean = a[0][0] === a[1][0];
  const bv: boolean = b[0][0] === b[1][0];
  if (av === bv) {
    // 平行：同一条线上重叠才算
    if (av) return a[0][0] === b[0][0] && Math.max(Math.min(a[0][1], a[1][1]), Math.min(b[0][1], b[1][1])) < Math.min(Math.max(a[0][1], a[1][1]), Math.max(b[0][1], b[1][1]));
    return a[0][1] === b[0][1] && Math.max(Math.min(a[0][0], a[1][0]), Math.min(b[0][0], b[1][0])) < Math.min(Math.max(a[0][0], a[1][0]), Math.max(b[0][0], b[1][0]));
  }
  const [v, h] = av ? [a, b] : [b, a];
  return inside(v[0][0], h[0][0], h[1][0]) && inside(h[0][1], v[0][1], v[1][1]);
}

/** 线段穿过盒子内部（只碰边不算） */
export function pierces(s: Seg, b: Box): boolean {
  const [p, q] = s;
  if (p[0] === q[0]) return p[0] > b.x && p[0] < b.x + b.w && Math.max(Math.min(p[1], q[1]), b.y) < Math.min(Math.max(p[1], q[1]), b.y + b.h);
  return p[1] > b.y && p[1] < b.y + b.h && Math.max(Math.min(p[0], q[0]), b.x) < Math.min(Math.max(p[0], q[0]), b.x + b.w);
}

export const overlaps = (a: Box, b: Box): boolean => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** 版面的毛病，一条一句；空数组＝没毛病 */
export function problems(L: GraphLayout): string[] {
  const out: string[] = [];
  const segs = segments(L);
  for (let i = 0; i < segs.length; i += 1)
    for (let j = i + 1; j < segs.length; j += 1) if (crosses(segs[i].seg, segs[j].seg)) out.push(`线交叉：${segs[i].key} × ${segs[j].key}`);
  for (const s of segs) for (const n of L.nodes) if (pierces(s.seg, n)) out.push(`线穿卡：${s.key} 穿过 ${n.key}`);
  for (const s of segs) for (const f of L.frames) if (s.key !== `branch:${f.group}` && s.key !== 'wait' && pierces(s.seg, f)) out.push(`线穿组框：${s.key} 穿过 ${f.group}`);
  // 盒子：组框里的卡和别的卡比，组框和组框外的盒子比
  const loose: Box[] = [...L.nodes.filter((n: GNode) => n.kind !== 'card' && n.kind !== 'row'), ...L.frames];
  const cards: GNode[] = L.nodes.filter((n: GNode) => n.kind === 'card' || n.kind === 'row');
  for (let i = 0; i < loose.length; i += 1) for (let j = i + 1; j < loose.length; j += 1) if (overlaps(loose[i], loose[j])) out.push(`框重叠：${i} × ${j}`);
  for (let i = 0; i < cards.length; i += 1) for (let j = i + 1; j < cards.length; j += 1) if (overlaps(cards[i], cards[j])) out.push(`卡重叠：${cards[i].key} × ${cards[j].key}`);
  for (const c of cards) {
    const f: GFrame | undefined = L.frames.find((x: GFrame) => x.group === c.group);
    if (!f || c.x < f.x || c.y < f.y + HEAD - 1 || c.x + c.w > f.x + f.w || c.y + c.h > f.y + f.h) out.push(`卡出了组框：${c.key}`);
  }
  for (const b of [...L.nodes, ...L.frames]) if (b.x < 0 || b.y < 0 || b.x + b.w > L.W || b.y + b.h > L.H) out.push(`出了画布：${'key' in b ? b.key : b.group}`);
  return out;
}
