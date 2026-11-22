/**
 * 对话区跟随到底（T603）：在做的一轮持续刷新时，新内容贴底；你往上翻就不再拉你回去。
 *
 * 纯函数，不碰 DOM：Conversation.tsx 把滚动区的数字和“你做了什么”喂进来，按结果滚动、收起或展开总览。
 * 防回归：scripts/scroll-follow.test.mjs。
 *
 * 规则：
 * - 跟随时（follow），新内容来了程序把滚动区拉到底；这次滚动是程序自己的（ownTop），不算你滚的。
 * - 你表示要往上看（滚轮向上、触控板往上推、手指往下拖、↑ / PageUp / Home）马上停止跟随，不等滚过一段距离。
 * - 你自己滚（含拖滚动条）往下回到底部附近（NEAR_BOTTOM 以内）再恢复跟随；点「回到最新」也恢复。
 * - 话题页的总览只跟你滚的走：你往下滚收起（内容多出不到 COMPACT_ROOM 不收），滚到顶、或在顶上还往上滚时展开；程序的滚动不动它。
 */

export const NEAR_BOTTOM = 80;
/** 你往下滚过这么多才收起总览 */
export const COMPACT_AFTER = 24;
/**
 * 内容比滚动区多出这么多才收起总览：总览收起约省 200px，多出的不够时一收起就全放得下、滚动区滚不动，
 * 浏览器把 scrollTop 夹回 0，又被当成“滚到顶”展开，来回跳
 */
export const COMPACT_ROOM = 240;
/** 离顶这么近算在顶上 */
export const AT_TOP = 4;

export interface Metrics {
  /** scrollTop */
  top: number;
  /** scrollHeight */
  height: number;
  /** clientHeight */
  client: number;
}

export interface Follow {
  follow: boolean;
  /** 上一次滚动事件时的 scrollTop */
  lastTop: number;
  /** 程序刚把 scrollTop 设成的值，等它的滚动事件来了认出来；没有就是 null */
  ownTop: number | null;
  /** 点了「回到最新」、正平滑滚过去：途中的滚动事件不打断跟随 */
  homing: boolean;
  /** 你连续往下滚了多少，够 COMPACT_AFTER 就收起总览 */
  downBy: number;
}

export type Cause = 'own' | 'user' | 'other';
export type Overview = 'compact' | 'expand' | null;
export interface Step {
  s: Follow;
  cause: Cause;
  overview: Overview;
}

export const distance = (m: Metrics): number => Math.max(0, m.height - m.top - m.client);
const atBottom = (m: Metrics): boolean => distance(m) <= 1;

export const start = (follow: boolean, top: number = 0): Follow => ({ follow, lastTop: top, ownTop: null, homing: false, downBy: 0 });

/**
 * 你在滚动区里做了一个有方向的动作（滚轮、触控板、手指拖、翻页键），在它滚起来之前。
 * up：停止跟随；已经在顶上（或根本滚不动）时展开总览，否则收起后滚不动就再也展不开。
 * down：已经在底（滚不动了）就恢复跟随，因为不会再有滚动事件。
 */
export function intent(s: Follow, dir: 'up' | 'down', m: Metrics): Step {
  if (dir === 'up') {
    return { s: { ...s, follow: false, homing: false, ownTop: null, downBy: 0 }, cause: 'user', overview: m.top <= AT_TOP ? 'expand' : null };
  }
  return { s: { ...s, follow: s.follow || atBottom(m), homing: false, ownTop: null }, cause: 'user', overview: null };
}

/**
 * 一次滚动事件。user：最近有你的输入（滚轮、触摸、按键、按下滚动条），由调用方按时间窗判断。
 * 程序自己设的 scrollTop（ownTop）优先认出来，哪怕你刚动过滚轮：这就是 T603 的 bug，
 * 跟随拉到底被当成“你往下滚”，总览收起，滚动区变得滚不动，往上滚就失败了。
 */
export function scrolled(s: Follow, m: Metrics, user: boolean): Step {
  const delta: number = m.top - s.lastTop;
  const d: number = distance(m);
  if (s.ownTop !== null && Math.abs(m.top - s.ownTop) < 2) {
    return { s: { ...s, lastTop: m.top, ownTop: null }, cause: 'own', overview: null };
  }
  if (s.homing) {
    const done: boolean = d < NEAR_BOTTOM;
    return { s: { ...s, lastTop: m.top, follow: true, homing: !done, ownTop: null }, cause: 'own', overview: null };
  }
  if (user) {
    let follow: boolean = s.follow;
    if (delta < 0 && d > 1) follow = false;
    else if (delta >= 0 && d < NEAR_BOTTOM) follow = true;
    let downBy: number = delta > 0 ? s.downBy + delta : 0;
    let overview: Overview = null;
    if (m.top <= AT_TOP) {
      downBy = 0;
      overview = 'expand';
    } else if (downBy > COMPACT_AFTER && m.height - m.client > COMPACT_ROOM) overview = 'compact';
    return { s: { ...s, lastTop: m.top, follow, downBy, ownTop: null }, cause: 'user', overview };
  }
  // 别的（内容变短被浏览器夹回、跳到某一轮、滚动锚定）：只按位置判断，且不动总览
  const follow: boolean = d < NEAR_BOTTOM && (s.follow || d <= 1);
  return { s: { ...s, lastTop: m.top, follow }, cause: 'other', overview: null };
}

/** 程序把 scrollTop 从 before 设成了 after（after 是设完读回来的值）。没变就不会有滚动事件，不记 */
export const pulled = (s: Follow, before: number, after: number): Follow =>
  Math.abs(after - before) < 1 ? s : { ...s, ownTop: after };

/** 点「回到最新」 */
export const home = (s: Follow): Follow => ({ ...s, follow: true, homing: true, ownTop: null, downBy: 0 });

/** 跳到某一轮（链接带 seq）或别的不是贴底的程序定位 */
export const unfollow = (s: Follow): Follow => ({ ...s, follow: false, homing: false });

/** 刚点了滚动区里的东西（展开一轮、展开全文），内容随之变了：不在底部附近就停止跟随，免得下一次刷新把你拉走 */
export const clickedResize = (s: Follow, m: Metrics): Follow => (s.follow && distance(m) >= NEAR_BOTTOM ? { ...s, follow: false } : s);

/** 「回到最新」按钮：没在跟随，而且下面还有东西 */
export const showLatest = (s: Follow, m: Metrics): boolean => !s.follow && !s.homing && distance(m) > 1;

/** 键盘上哪些键是往上、往下看 */
export const keyDir = (key: string, shift: boolean = false): 'up' | 'down' | null => {
  if (key === 'ArrowUp' || key === 'PageUp' || key === 'Home' || (key === ' ' && shift)) return 'up';
  if (key === 'ArrowDown' || key === 'PageDown' || key === 'End' || key === ' ') return 'down';
  return null;
};
