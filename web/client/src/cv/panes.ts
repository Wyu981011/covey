/**
 * 两侧栏拖动调宽（T741，PaneHandle.tsx 是把手）：左侧栏、话题页的进度栏、专项页和看板的右栏各记一个宽度，
 * 存在这台浏览器上（localStorage 的 covey.pane*）。宽度经 <html> 上的 CSS 变量（--pane-*）交给样式表（panes.css），
 * 拖动时只改变量、不重画；样式表里另按视口宽兜一个上限，窗口变窄时主区不被挤没。
 */
import { pref, setPref } from './lib';

export interface PaneSpec {
  /** 本地偏好的名字（covey.<pref>） */
  pref: string;
  /** 样式表读的 CSS 变量 */
  cssVar: string;
  /** 面板在把手哪一边：left 是把手左边的面板（左侧栏），right 是把手右边的（右栏） */
  edge: 'left' | 'right';
  min: number;
  max: number;
  /** 没调过时的宽度，和样式表里的默认一样 */
  def: number;
  /** 读屏和悬停提示里叫它什么 */
  label: string;
}

export const SIDE_PANE: PaneSpec = { pref: 'paneSide', cssVar: '--pane-side', edge: 'left', min: 200, max: 400, def: 248, label: '左侧栏' };
export const TOPIC_RAIL: PaneSpec = { pref: 'paneTopicRail', cssVar: '--pane-topic-rail', edge: 'right', min: 240, max: 520, def: 300, label: '进度栏' };
export const PROJECT_RAIL: PaneSpec = { pref: 'paneProjectRail', cssVar: '--pane-project-rail', edge: 'right', min: 260, max: 560, def: 324, label: '专项右栏' };
export const BOARD_RAIL: PaneSpec = { pref: 'paneBoardRail', cssVar: '--pane-board-rail', edge: 'right', min: 260, max: 520, def: 316, label: '看板右栏' };
export const PANES: readonly PaneSpec[] = [SIDE_PANE, TOPIC_RAIL, PROJECT_RAIL, BOARD_RAIL];

/** 中间的对话区至少留这么宽：拖的时候按它定面板最多能多宽 */
export const MAIN_MIN = 480;
/** 键盘 ← → 一次挪多少，按住 Shift 是四倍 */
export const KEY_STEP = 16;

/** 夹在 [min, max] 里，也不超过 room（这次拖动时主区还能让出来的最大宽度）；room 比 min 还小时给 min */
export function clampWidth(spec: PaneSpec, w: number, room: number = Infinity): number {
  const hi: number = Math.max(spec.min, Math.min(spec.max, room));
  return Math.round(Math.min(hi, Math.max(spec.min, w)));
}

/** 记下的值：空、不是正数（被改坏了）是 null，即用默认；超出范围的夹回范围里 */
export function parseWidth(spec: PaneSpec, raw: string): number | null {
  if (!raw.trim()) return null;
  const n: number = Number(raw);
  return Number.isFinite(n) && n > 0 ? clampWidth(spec, n) : null;
}

/** 拖到哪儿：dx 是指针从按下起往右移了多少。左侧栏随指针右移变宽，右栏随指针左移变宽 */
export const dragWidth = (spec: PaneSpec, start: number, dx: number, room: number = Infinity): number =>
  clampWidth(spec, spec.edge === 'left' ? start + dx : start - dx, room);

/** 键盘：← → 把分界挪 KEY_STEP（Shift 四倍），Home、End 到最窄、最宽；别的键是 null（不处理） */
export function keyWidth(spec: PaneSpec, w: number, key: string, shift: boolean, room: number = Infinity): number | null {
  const step: number = KEY_STEP * (shift ? 4 : 1);
  // 分界往右挪：左侧栏变宽、右栏变窄
  const right: number = spec.edge === 'left' ? step : -step;
  if (key === 'ArrowRight') return clampWidth(spec, w + right, room);
  if (key === 'ArrowLeft') return clampWidth(spec, w - right, room);
  if (key === 'Home') return clampWidth(spec, spec.min, room);
  if (key === 'End') return clampWidth(spec, spec.max, room);
  return null;
}

/** 这台浏览器上记的宽度；没记过是 null */
export const savedWidth = (spec: PaneSpec): number | null => parseWidth(spec, pref(spec.pref, ''));

/** 记下（null 是忘掉，回到默认） */
export const saveWidth = (spec: PaneSpec, w: number | null): void => setPref(spec.pref, w === null ? '' : String(w));

/** 让样式表用这个宽度（null 是去掉变量，用样式表的默认） */
export function showWidth(spec: PaneSpec, w: number | null, root: HTMLElement = document.documentElement): void {
  if (w === null) root.style.removeProperty(spec.cssVar);
  else root.style.setProperty(spec.cssVar, `${w}px`);
}

/** 打开页面时把记下的宽度放上：在首屏画出来之前调，免得先按默认画再跳一下 */
export function showSavedPanes(root: HTMLElement = document.documentElement): void {
  for (const spec of PANES) {
    const w: number | null = savedWidth(spec);
    if (w !== null) showWidth(spec, w, root);
  }
}
