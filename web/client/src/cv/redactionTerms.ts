/* 脱敏词表的批量编辑（Covey 数据约定 v14，T567）：一行一个词，和 Covey 推来的词表比出这次加了哪些、删了哪些。
   规则和 Covey 的 core/redaction.py row_problem 一致：每行去首尾空白、中间空格保留、空行不算；至少 2 个字、最多 max_length 个字、
   不能有 Tab 和控制字符、不能写 =>（替身词自动生成）；“不区分大小写”开着时 Foo 和 foo 算同一个词，留第一次出现的写法。
   只改大小写（foo → Foo）算删一个加一个，Covey 先删后加。最后以 Covey 的回执为准。 */

export type LineState = 'keep' | 'add' | 'dup' | 'bad';
export interface TermLine {
  /** 文本框里的第几行（从 1 起） */
  line: number;
  text: string;
  state: LineState;
  /** bad 的原因，不含词本身 */
  why: string;
  /** dup：和第几行重复 */
  dupOf: number;
}
export interface TermPlan {
  lines: TermLine[];
  add: string[];
  remove: string[];
  dups: number;
  bad: number;
  /** 保存后词表有几个词 */
  total: number;
  over: boolean;
  changed: boolean;
  canSave: boolean;
}

const CONTROL = /[\u0000-\u001f\u007f]/;
export const chars = (s: string): number => Array.from(s).length;
const folder = (ignoreCase: boolean) => (s: string): string => (ignoreCase ? s.toLowerCase() : s);

export function problem(term: string, maxLength: number): string {
  if (chars(term) < 2) return '至少要 2 个字';
  if (chars(term) > maxLength) return `不能超过 ${maxLength} 个字`;
  if (CONTROL.test(term)) return '不能有 Tab 或控制字符';
  if (term.includes('=>')) return '替身词自动生成，不用写 =>';
  return '';
}

export function planTerms(text: string, original: string[], ignoreCase: boolean, maxTerms: number, maxLength: number): TermPlan {
  const fold = folder(ignoreCase);
  const exact = new Set<string>(original);
  const seen = new Map<string, number>();
  const kept = new Set<string>();
  const lines: TermLine[] = [];
  const add: string[] = [];
  text.split(/\r?\n/).forEach((raw: string, i: number) => {
    const t: string = raw.trim();
    if (!t) return;
    const line: number = i + 1;
    const why: string = problem(t, maxLength);
    if (why) {
      lines.push({ line, text: t, state: 'bad', why, dupOf: 0 });
      return;
    }
    const first: number | undefined = seen.get(fold(t));
    if (first !== undefined) {
      lines.push({ line, text: t, state: 'dup', why: '', dupOf: first });
      return;
    }
    seen.set(fold(t), line);
    if (exact.has(t)) {
      kept.add(t);
      lines.push({ line, text: t, state: 'keep', why: '', dupOf: 0 });
    } else {
      add.push(t);
      lines.push({ line, text: t, state: 'add', why: '', dupOf: 0 });
    }
  });
  const remove: string[] = original.filter((t: string) => !kept.has(t));
  const bad: number = lines.filter((l: TermLine) => l.state === 'bad').length;
  const dups: number = lines.filter((l: TermLine) => l.state === 'dup').length;
  const total: number = seen.size;
  const over: boolean = total > maxTerms;
  const changed: boolean = add.length > 0 || remove.length > 0;
  return { lines, add, remove, dups, bad, total, over, changed, canSave: changed && !bad && !over };
}

/** 去掉文本框第 line 行（列表里点 ✕） */
export function dropLine(text: string, line: number): string {
  return text.split(/\r?\n/).filter((_: string, i: number) => i + 1 !== line).join('\n');
}

/** 把几行接到文本框末尾（列表里加词、撤回删除） */
export function appendLines(text: string, more: string): string {
  const head: string = text.replace(/\s+$/, '');
  const tail: string = more.replace(/^\s+|\s+$/g, '');
  if (!tail) return text;
  return head ? `${head}\n${tail}` : tail;
}
