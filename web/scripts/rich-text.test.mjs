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
