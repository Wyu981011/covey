// T616：边写边渲染的输入框发出去的 Markdown（tidyMarkdown）：空段落并成一个空行、结尾不留空行，代码块里原样
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const src = readFileSync(new URL('../client/src/cv/RichText.tsx', import.meta.url), 'utf8');
const body = src.slice(src.indexOf('export function tidyMarkdown'), src.indexOf('/** 输入框的编辑区要给外面的'));
const js = ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const { tidyMarkdown } = await import(`data:text/javascript,${encodeURIComponent(js)}`);

test('空段落并成一个空行，结尾空行去掉', () => {
  assert.equal(tidyMarkdown('要改：\n\n- 一\n- 二\n\n\n\n**粗**\n\n'), '要改：\n\n- 一\n- 二\n\n**粗**');
});
test('代码块里的空行原样留着', () => {
  assert.equal(tidyMarkdown('```\na\n\n\nb\n```\n\n\n'), '```\na\n\n\nb\n```');
});
test('空的就是空串', () => {
  assert.equal(tidyMarkdown('\n\n'), '');
});

// T789（主人截图 T774）：发完一段多行长消息，输入框清空了却还卡在近半屏高。Composer 在 useLayoutEffect 里按编辑区的 scrollHeight 定高；
// RichText 把外面换的字（发出后清空、换话题的草稿）写进编辑器要早于它，才量得到新字的高。React 先跑子组件的 layout effect、再跑父组件的，
// 所有 layout effect 跑完才跑 useEffect：所以这一步必须是 RichText 里的 useLayoutEffect，RichText 必须是 Composer 画出来的子组件
/** 包住 marker 的那个 hook 叫什么（marker 前面最近的 useEffect( / useLayoutEffect(） */
const hookAround = (code, marker) => {
  const at = code.indexOf(marker);
  assert.ok(at > 0, `找不到 ${marker}`);
  const before = code.slice(0, at);
  const eff = before.lastIndexOf('useEffect(');
  const lay = before.lastIndexOf('useLayoutEffect(');
  return lay > eff ? 'useLayoutEffect' : 'useEffect';
};
test('外面换的字先写进编辑器、Composer 再量高：发出后清空，输入框回到一行高', () => {
  assert.equal(hookAround(src, 'editor.commands.setContent(value'), 'useLayoutEffect', 'RichText 同步外部 value 要在 layout effect 里');
  const composer = readFileSync(new URL('../client/src/cv/Composer.tsx', import.meta.url), 'utf8');
  assert.equal(hookAround(composer, 'el.style.height = `${Math.min(el.scrollHeight'), 'useLayoutEffect', 'Composer 量高度在 layout effect 里');
  assert.match(composer, /<RichText\b/u, 'RichText 是 Composer 画出来的子组件（子组件的 layout effect 先跑）');
});
