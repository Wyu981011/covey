/* 对话区左边的刻度导航（T621）用的纯函数：刻度间距、长短，哪一条是眼前这条，预览卡放在哪。不引别的模块，npm run test:rail 直接跑。 */

/** 一条刻度：对话里你说的一句（管家、负责人页）或一轮（话题页） */
export interface Mark {
  /** 跳过去时找的 data-seq */
  seq: number;
  /** 卡片标题：你说的那句（话题页是这一轮的概括） */
  title: string;
  /** 卡片正文：它怎么答的，取开头 */
  body: string;
  /** 卡片右上角：第几轮、几点 */
  meta: string;
  /** 不是你说的（Covey 自己接着做的一轮、负责人或管家转来的）：刻度淡一点 */
  quiet?: boolean;
}

/** 两条刻度的间距（px）：条数少时宽松，多了压紧，最紧 GAP_MIN */
export const GAP_MAX = 10;
export const GAP_MIN = 3;
export function gap(n: number, room: number): number {
  if (n <= 1) return GAP_MAX;
  return Math.max(GAP_MIN, Math.min(GAP_MAX, Math.floor(room / n)));
}

/** 刻度的长度（px）：眼前这条最长，鼠标指着的那条也一样长（颜色不同）。
 *  T779 去掉了“旁边几条依次变长”的放大镜：每挪一条就有七条一起伸缩，看着一直在跳 */
export const LEN = { base: 10, hover: 26, active: 26 };
export function tickLength(i: number, active: number, hover: number | null): number {
  if (hover !== null && i === hover) return LEN.hover;
  return i === active ? LEN.active : LEN.base;
}

/** 已经指着一条时，鼠标要越过它的上下边多少像素才换到旁边那条（不超过半条间距） */
export const STICK = 3;

/**
 * 鼠标指着第几条（T779）：y 是鼠标在刻度区里的纵坐标，每条占 g 高，共 n 条。
 * 已经指着 prev 时，鼠标还在它上下各外扩 STICK 的范围里就不换：刻度只有 3~10px 高，手一抖、按下到松开挪了一两像素，
 * 预览卡就换成了旁边那条，点下去跳到的也不是看着的那条。
 */
export function pickIndex(y: number, g: number, n: number, prev: number | null): number {
  const raw: number = Math.max(0, Math.min(n - 1, Math.floor(y / g)));
  if (prev === null || prev === raw || prev < 0 || prev >= n) return raw;
  const s: number = Math.min(STICK, g / 2);
  return y >= prev * g - s && y < (prev + 1) * g + s ? prev : raw;
}

/** 视口里“眼前这条”的基准线：滚动区顶上往下这么多比例处。跳过去的那条居中摆，基准线放在正中它才算眼前这条 */
export const READ_LINE = 0.5;

/**
 * 眼前这条：顶边在基准线以上的最后一条。tops 是每条在滚动内容里的位置，没画出来的（话题页收起的更早几轮）是 null。
 * 贴着底部时就是最后一条画出来的；一条都没过基准线时是第一条画出来的。
 */
export function activeIndex(tops: (number | null)[], view: { top: number; client: number; height: number }): number {
  let first = -1;
  let last = -1;
  let hit = -1;
  const line: number = view.top + view.client * READ_LINE;
  tops.forEach((t: number | null, i: number) => {
    if (t === null) return;
    if (first < 0) first = i;
    last = i;
    if (t <= line) hit = i;
  });
  if (last < 0) return tops.length - 1;
  if (view.height - view.top - view.client < 4) return last;
  return hit >= 0 ? hit : first;
}

/** 预览卡的顶边：和指着的刻度对齐（卡片标题那一行对着刻度），不出滚动区上下沿 */
export function cardTop(tickY: number, cardH: number, boxH: number, pad = 8): number {
  const want: number = tickY - 22;
  return Math.max(pad, Math.min(want, boxH - cardH - pad));
}

/** 一行字：去掉 Markdown 记号、压成一行，超长截断 */
export function oneLine(s: string, max: number): string {
  const t: string = (s || '')
    .replace(/```[\s\S]*?(```|$)/gu, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/gu, '$1')
    .replace(/^\s*(#{1,6}|[-*+]|\d+[.)]|>)\s+/gmu, '')
    .replace(/[*`~|]+/gu, '')
    .replace(/\s+/gu, ' ')
    .trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}
