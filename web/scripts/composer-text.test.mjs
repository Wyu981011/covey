// 输入框的 Markdown 编辑（T616）：列表续行、Tab 缩进。跑：npm run test:composer
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as C from '../client/src/cv/composerText.ts';

/** 光标用 | 标出 */
const at = (s) => ({ value: s.replace('|', ''), pos: s.indexOf('|') });
const show = (r) => (r ? r.value.slice(0, r.start) + '|' + r.value.slice(r.start) : null);
const enter = (s) => { const { value, pos } = at(s); return show(C.listEnter(value, pos, pos)); };
const tab = (s, out = false) => { const { value, pos } = at(s); return show(C.listIndent(value, pos, pos, out)); };

test('无序列表续行', () => {
  assert.equal(enter('- 一|'), '- 一\n- |');
  assert.equal(enter('* 一|'), '* 一\n* |');
  assert.equal(enter('  - 子|'), '  - 子\n  - |');
});

test('有序列表编号加一', () => {
  assert.equal(enter('1. 一|'), '1. 一\n2. |');
  assert.equal(enter('9) 九|'), '9) 九\n10) |');
});

test('勾选框续成空的', () => {
  assert.equal(enter('- [x] 做完|'), '- [x] 做完\n- [ ] |');
});

test('行中间按 Enter 把后半段带到下一项', () => {
  assert.equal(enter('- 前|后'), '- 前\n- |后');
});

test('空项再按 Enter 结束列表', () => {
  assert.equal(enter('- 一\n- |'), '- 一\n|');
  assert.equal(enter('1. 一\n2. |\n'), '1. 一\n|\n');
});

test('不是列表、或光标在符号里，交给浏览器', () => {
  assert.equal(enter('普通一句|'), null);
  assert.equal(enter('-|- 一'), null);
  assert.equal(enter('-不是列表|'), null);
});

test('Tab 缩进到上一项的内容开头，Shift+Tab 退回', () => {
  assert.equal(tab('- 一\n- |二'), '- 一\n  - |二');
  assert.equal(tab('1. 一\n2. |二'), '1. 一\n   2. |二');
  assert.equal(tab('- 一\n  - |二', true), '- 一\n- |二');
  assert.equal(tab('- 一\n    - |二', true), '- 一\n- |二');
});

test('第一项、或不是列表时 Tab 不处理', () => {
  assert.equal(tab('- |一'), null);
  assert.equal(tab('文字|'), null);
  assert.equal(tab('- |一', true), null);
});

test('选中几行一起缩进', () => {
  const v = '- 一\n- 二\n- 三';
  const r = C.listIndent(v, v.indexOf('二'), v.length, false);
  assert.equal(r.value, '- 一\n  - 二\n  - 三');
  assert.equal(r.end, r.value.length);
});

test('发送键和文件大小', () => {
  assert.equal(C.sendKey('MacIntel'), '⌘+Enter');
  assert.equal(C.sendKey('Linux x86_64'), 'Ctrl+Enter');
  assert.equal(C.fmtSize(500), '500 B');
  assert.equal(C.fmtSize(12 * 1024), '12 KB');
  assert.equal(C.fmtSize(3.4 * 1024 * 1024), '3.4 MB');
});
