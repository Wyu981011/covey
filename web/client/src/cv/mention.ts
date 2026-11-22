/**
 * 正文里的 @ 胶囊（大厅多参与者协作的交互改造，T642）：纯函数。
 * - 胶囊在草稿（Markdown）里存成 `[@T586](covey-mention:<key>)`：刷新、换对话回来还在；源码模式看到的就是它，删掉就是移出这一位。
 * - 参与者 = 正文里所有胶囊去重，按第一次插入的先后（草稿读回时按正文顺序）；某位的胶囊删光就移出。
 * - 发出去：记号转成纯文字 `@T586`、`@管家`、`@习题专项 负责人`；手打的“@T586”纯文字不算参与者。
 * 代码块和行内代码里的记号不认（只当字）。
 */

export const SCHEME = 'covey-mention:';

/** 一枚记号：label 里转义过 \ [ ]；key 是 encodeURIComponent 之后再把括号编掉的，好让 `[^)\s]` 能找到它的结尾 */
const TOKEN_SRC = String.raw`\[@((?:\\.|[^\]\\\n])*)\]\(covey-mention:([^)\s]*)\)`;
/** 代码块（围栏到围栏、没收尾就到末尾）和行内代码：里面的记号只当字 */
const CODE_RE = /(^|\n)(```|~~~)[\s\S]*?(?:\n\2[^\n]*|$)|`[^`\n]*`/gu;

export interface MentionRef {
  key: string;
  label: string;
}

const escLabel = (s: string): string => s.replace(/[\\[\]]/gu, '\\$&');
const unescLabel = (s: string): string => s.replace(/\\(.)/gu, '$1');
const encKey = (k: string): string => encodeURIComponent(k).replace(/[()]/gu, (c: string) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
const decKey = (k: string): string => {
  try {
    return decodeURIComponent(k);
  } catch {
    return k;
  }
};

/** 一枚胶囊在 Markdown 里的写法 */
export const mentionToken = (key: string, label: string): string => `[@${escLabel(label)}](${SCHEME}${encKey(key)})`;

/** 从一段 Markdown 的开头读一枚记号（给编辑器的 markdownTokenizer 用）；开头不是记号就是 null */
export function tokenAtStart(src: string): { raw: string; key: string; label: string } | null {
  const m: RegExpExecArray | null = new RegExp(`^${TOKEN_SRC}`, 'u').exec(src);
  return m ? { raw: m[0], label: unescLabel(m[1]), key: decKey(m[2]) } : null;
}

/** 代码以外的部分用 fn 改写，代码原样留着 */
function outsideCode(md: string, fn: (plain: string) => string): string {
  let out = '';
  let at = 0;
  for (const m of md.matchAll(CODE_RE)) {
    out += fn(md.slice(at, m.index)) + m[0];
    at = m.index + m[0].length;
  }
  return out + fn(md.slice(at));
}

/** 正文里所有胶囊，按正文顺序（同一位出现几次就几条） */
export function mentionsIn(md: string): MentionRef[] {
  const out: MentionRef[] = [];
  outsideCode(md, (plain: string) => {
    for (const m of plain.matchAll(new RegExp(TOKEN_SRC, 'gu'))) out.push({ key: decKey(m[2]), label: unescLabel(m[1]) });
    return plain;
  });
  return out;
}

/** 正文里有哪几位，去重，按正文顺序（草稿读回来时用） */
export const mentionKeys = (md: string): string[] => [...new Set<string>(mentionsIn(md).map((m: MentionRef) => m.key))];

/**
 * 参与者：上一次的名单里还在正文里的留着（顺序不变，不按正文位置），正文里新出现的按正文顺序接在后面；
 * 某位的胶囊删光了就不在了。prev 为空（刷新后从草稿读回）就是正文顺序。
 */
export function participants(prev: readonly string[], md: string): string[] {
  const now: string[] = mentionKeys(md);
  return [...prev.filter((k: string) => now.includes(k)), ...now.filter((k: string) => !prev.includes(k))];
}

/** 发出去的正文：记号换成纯文字 @T586、@管家、@习题专项 负责人 */
export const plainMentions = (md: string): string => outsideCode(
  md,
  (plain: string) => plain.replace(new RegExp(TOKEN_SRC, 'gu'), (_m: string, label: string) => `@${unescLabel(label)}`),
);

/** 把某一位的所有胶囊从正文里删掉（“移出这次”）；前后的空格收一收，别的字不动 */
export const dropMention = (md: string, key: string): string => outsideCode(
  md,
  (plain: string) => plain.replace(new RegExp(`${TOKEN_SRC}( ?)`, 'gu'), (m: string, _label: string, k: string, trail: string, offset: number, whole: string) => {
    if (decKey(k) !== key) return m;
    const prev: string = offset === 0 ? '' : whole[offset - 1];
    // 前面是空白或行首：连后面那个空格一起收；前面是英文数字：留一个空格免得两个词粘住；前面是中文或标点：不留
    return !prev || /\s/u.test(prev) ? '' : /[A-Za-z0-9]/u.test(prev) ? trail : '';
  }),
);

/** 胶囊的属性：key 是话题（管家、负责人）的 key，kind 和 label 是插入时的样子，avatar、number 画头像用；刷新后从草稿读回时只有 key 和 label，样子由 env 补上 */
export interface MentionAttrs {
  key: string;
  kind: 'butler' | 'lead' | 'topic';
  label: string;
  avatar?: string;
  number?: number | null;
}
