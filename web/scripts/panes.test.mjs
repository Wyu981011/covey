// 两侧栏拖动调宽（T741）的纯函数：夹在范围里、主区让不出来时不超、记下的值读回、拖动和键盘的方向、Home/End。跑：npm run test:panes
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as P from '../client/src/cv/panes.ts';

const { SIDE_PANE: SIDE, TOPIC_RAIL: RAIL } = P;

test('默认宽度和样式表一致，范围包住默认', () => {
  for (const s of P.PANES) {
    assert.ok(s.min <= s.def && s.def <= s.max, `${s.pref} 的默认 ${s.def} 不在 [${s.min}, ${s.max}]`);
    assert.match(s.cssVar, /^--pane-/u);
  }
  assert.equal(SIDE.def, 248);
  assert.equal(RAIL.def, 300);
  assert.equal(new Set(P.PANES.map((s) => s.pref)).size, P.PANES.length, '每块面板记自己的宽度');
});

test('夹在 [min, max] 里；主区让不出来时不超过 room，room 比 min 还小也给 min', () => {
  assert.equal(P.clampWidth(SIDE, 100), SIDE.min);
  assert.equal(P.clampWidth(SIDE, 9999), SIDE.max);
  assert.equal(P.clampWidth(SIDE, 300.4), 300);
  assert.equal(P.clampWidth(SIDE, 380, 320), 320);
  assert.equal(P.clampWidth(SIDE, 380, 150), SIDE.min);
});

test('记下的值：空和坏值用默认（null），超范围夹回去', () => {
  assert.equal(P.parseWidth(SIDE, ''), null);
  assert.equal(P.parseWidth(SIDE, '  '), null);
  assert.equal(P.parseWidth(SIDE, 'abc'), null);
  assert.equal(P.parseWidth(SIDE, '-20'), null);
  assert.equal(P.parseWidth(SIDE, '0'), null);
  assert.equal(P.parseWidth(SIDE, '320'), 320);
  assert.equal(P.parseWidth(SIDE, '9000'), SIDE.max);
  assert.equal(P.parseWidth(RAIL, '120'), RAIL.min);
});

test('拖动方向：左侧栏随指针右移变宽，右栏随指针左移变宽', () => {
  assert.equal(P.dragWidth(SIDE, 248, 52), 300);
  assert.equal(P.dragWidth(SIDE, 248, -100), SIDE.min);
  assert.equal(P.dragWidth(RAIL, 300, -60), 360);
  assert.equal(P.dragWidth(RAIL, 300, 40), 260);
  assert.equal(P.dragWidth(RAIL, 300, -400, 420), 420);
});

test('键盘：← → 挪分界（Shift 四倍），Home、End 到最窄最宽，别的键不处理', () => {
  assert.equal(P.keyWidth(SIDE, 248, 'ArrowRight', false), 248 + P.KEY_STEP);
  assert.equal(P.keyWidth(SIDE, 300, 'ArrowLeft', true), 300 - 4 * P.KEY_STEP);
  assert.equal(P.keyWidth(SIDE, 210, 'ArrowLeft', true), SIDE.min);
  // 右栏：分界往右挪是变窄
  assert.equal(P.keyWidth(RAIL, 300, 'ArrowRight', false), 300 - P.KEY_STEP);
  assert.equal(P.keyWidth(RAIL, 300, 'ArrowLeft', false), 300 + P.KEY_STEP);
  assert.equal(P.keyWidth(SIDE, 248, 'Home', false), SIDE.min);
  assert.equal(P.keyWidth(SIDE, 248, 'End', false), SIDE.max);
  assert.equal(P.keyWidth(SIDE, 248, 'End', false, 330), 330);
  assert.equal(P.keyWidth(SIDE, 248, 'Enter', false), null);
});

test('没有浏览器存储时（单测、隐私模式）读不到记下的宽度，不报错', () => {
  assert.equal(P.savedWidth(SIDE), null);
  assert.doesNotThrow(() => P.saveWidth(SIDE, 300));
});
