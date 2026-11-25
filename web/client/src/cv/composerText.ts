/**
 * 输入框里的 Markdown 编辑（T616）：列表续行、Tab 缩进列表项，以及 Enter 是发送还是换行（T761）。纯函数，不碰 DOM：Composer.tsx 把文字和光标喂进来，按结果改写。
 * 防回归：scripts/composer-text.test.mjs。
 *
 * - 光标在列表项（`- `、`* `、`+ `、`1. `、`1) `、`- [ ] `）的内容里按 Enter：断开这一行，下一行续同样的符号，编号加一，勾选框续成空的。
 * - 空的一项再按 Enter：去掉这一项的符号，列表到此结束。
 * - Tab：选中的各行里是列表项的，缩进到上一项的内容开头（成为它的子项）；Shift+Tab 退回上一级。选中的行没有列表项时不处理（交给浏览器）。
 */

export interface TextEdit {
  value: string;
  start: number;
  end: number;
}

/** 列表项：缩进、符号（含编号）、编号、勾选框 */
const ITEM = /^([ \t]*)([-*+]|(\d{1,9})([.)]))[ \t]+(\[[ xX]\][ \t]+)?/u;

interface Item {
  indent: string;
  /** 符号连同后面的空格和勾选框 */
  marker: string;
  /** 内容从这一行的第几个字开始 */
  content: number;
}

function itemOf(line: string): Item | null {
  const m: RegExpExecArray | null = ITEM.exec(line);
  if (!m) return null;
  return { indent: m[1], marker: m[0].slice(m[1].length), content: m[0].length };
}

const lineStartOf = (value: string, at: number): number => value.lastIndexOf('\n', at - 1) + 1;
const lineEndOf = (value: string, at: number): number => {
  const i: number = value.indexOf('\n', at);
  return i < 0 ? value.length : i;
};

/** 下一项的符号：编号加一，勾选框续成空的 */
function nextMarker(line: string): string {
  const m: RegExpExecArray | null = ITEM.exec(line);
  if (!m) return '';
  const bullet: string = m[3] ? `${Number(m[3]) + 1}${m[4]}` : m[2];
  return `${m[1]}${bullet} ${m[5] ? '[ ] ' : ''}`;
}

/** Enter：列表续行或结束列表；不是列表项（或有选区、光标在符号里）返回 null，交给浏览器换行 */
export function listEnter(value: string, start: number, end: number): TextEdit | null {
  if (start !== end) return null;
  const ls: number = lineStartOf(value, start);
  const le: number = lineEndOf(value, start);
  const line: string = value.slice(ls, le);
  const item: Item | null = itemOf(line);
  if (!item || start - ls < item.content) return null;
  if (!line.slice(item.content).trim()) {
    // 空的一项：去掉符号，列表结束（光标留在这一行行首）
    const v: string = value.slice(0, ls) + value.slice(le);
    return { value: v, start: ls, end: ls };
  }
  const insert: string = `\n${nextMarker(line)}`;
  const v: string = value.slice(0, start) + insert + value.slice(end);
  const at: number = start + insert.length;
  return { value: v, start: at, end: at };
}

/** 往上找第一个缩进比 width 小（outdent）或不大于 width（indent）的列表项 */
function parentItem(lines: string[], i: number, width: number, strict: boolean): Item | null {
  for (let k: number = i - 1; k >= 0; k -= 1) {
    const it: Item | null = itemOf(lines[k]);
    if (!it) {
      if (!lines[k].trim()) continue;
      // 列表项的续行（缩进过的正文）不打断列表；顶格的正文打断
      if (/^[ \t]/u.test(lines[k])) continue;
      return null;
    }
    const w: number = it.indent.length;
    if (strict ? w < width : w <= width) return it;
  }
  return null;
}

/** Tab / Shift+Tab：缩进或退回选中各行里的列表项；没有一行能动时返回 null */
export function listIndent(value: string, start: number, end: number, outdent: boolean): TextEdit | null {
  const from: number = lineStartOf(value, start);
  const to: number = lineEndOf(value, Math.max(start, end > start && value[end - 1] === '\n' ? end - 1 : end));
  const lines: string[] = value.split('\n');
  // 选中的是第几行到第几行
  const first: number = value.slice(0, from).split('\n').length - 1;
  const last: number = value.slice(0, to).split('\n').length - 1;
  let changed = false;
  let firstDelta = 0;
  let total = 0;
  for (let i: number = first; i <= last; i += 1) {
    const it: Item | null = itemOf(lines[i]);
    if (!it) continue;
    const w: number = it.indent.length;
    let next: number;
    if (outdent) {
      if (w === 0) continue;
      const parent: Item | null = parentItem(lines, i, w, true);
      next = parent ? parent.indent.length : 0;
    } else {
      const parent: Item | null = parentItem(lines, i, w, false);
      if (!parent) continue;
      next = parent.indent.length + parent.marker.replace(/\[[ xX]\][ \t]+$/u, '').length;
      if (next <= w) continue;
    }
    const delta: number = next - w;
    lines[i] = ' '.repeat(next) + lines[i].slice(w);
    if (i === first) firstDelta = delta;
    total += delta;
    changed = true;
  }
  if (!changed) return null;
  const v: string = lines.join('\n');
  // 光标不能退到行首之前
  const s: number = Math.max(from, start + firstDelta);
  return { value: v, start: s, end: start === end ? s : Math.max(s, end + total) };
}

/** 一次按键里定 Enter 做什么要看的部分（React 的和编辑器的按键事件都有） */
export interface EnterKey {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing?: boolean;
  keyCode?: number;
}

/**
 * Enter 在输入框里做什么，和飞书聊天一样（T761）：
 * - 收着时（sendOnEnter）：Enter 发送；Shift / Ctrl / ⌘ / Alt + Enter 换行。
 * - 放大后、触屏手机上：几种 Enter 都换行，只有发送钮发。
 * 换行都是另起一段（列表里续下一项、空项结束列表、代码块里换行），和以前的 Enter 一样：下一行行首打“- ”“1. ”“# ”照样变样子。
 * 以前 Shift+Enter 是段内的软换行，软换行后面打的“* ”不在段首，不变列表（T761 主人贴图后那条就是这样）。
 * 'send' 发送；'break' 换行；null 不是 Enter，或在组字（中文输入法选字时的回车，Safari 上是 keyCode 229），交给编辑器。
 */
export function enterAction(e: EnterKey, sendOnEnter: boolean): 'send' | 'break' | null {
  if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return null;
  const plain: boolean = !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey;
  return plain && sendOnEnter ? 'send' : 'break';
}

/** 源码框里在光标处换一行（Ctrl / ⌘ + Enter 浏览器自己不换） */
export function lineBreak(value: string, start: number, end: number): TextEdit {
  return { value: `${value.slice(0, start)}\n${value.slice(end)}`, start: start + 1, end: start + 1 };
}

/** 发送键和换行键的说法（提示行、问题面板、发送钮的说明共用） */
export const SEND_KEY = 'Enter';
export const BREAK_KEY = 'Shift+Enter';
/** 输入框下面那行小字：收着时、放大后 */
export const ENTER_HINT = `${SEND_KEY} 发送 · ${BREAK_KEY} 换行`;
export const BIG_HINT = '放大时 Enter 换行，点发送钮发出';

/** 文件大小：12 KB、3.4 MB */
export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}
