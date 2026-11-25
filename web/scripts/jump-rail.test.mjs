// 对话区刻度导航（T621）的纯函数：眼前这条怎么定、刻度间距和长短、预览卡不出界。跑：npm run test:rail
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as J from '../client/src/cv/jumpMarks.ts';

test('眼前这条：顶边过了基准线的最后一条', () => {
  const tops = [0, 400, 800, 1200];
  // 视口 600 高，基准线在 top+300
  assert.equal(J.activeIndex(tops, { top: 0, client: 600, height: 2000 }), 0);
  assert.equal(J.activeIndex(tops, { top: 300, client: 600, height: 2000 }), 1);
  assert.equal(J.activeIndex(tops, { top: 700, client: 600, height: 2000 }), 2);
});

test('贴着底部就是最后一条，哪怕它还没过基准线', () => {
  assert.equal(J.activeIndex([0, 400, 800, 1350], { top: 800, client: 600, height: 1400 }), 3);
});

test('话题页收起的更早几轮（null）跳过；一条都没过线时是第一条画出来的', () => {
  assert.equal(J.activeIndex([null, null, 500, 900], { top: 0, client: 600, height: 2000 }), 2);
  assert.equal(J.activeIndex([null, null, 100, 900], { top: 0, client: 600, height: 2000 }), 2);
  assert.equal(J.activeIndex([null, null], { top: 0, client: 600, height: 2000 }), 1);
});

test('间距：少时宽松，多了压紧，不小于 GAP_MIN', () => {
  assert.equal(J.gap(5, 600), J.GAP_MAX);
  assert.equal(J.gap(100, 600), 6);
  assert.equal(J.gap(500, 600), J.GAP_MIN);
});

test('长短：眼前这条最长；鼠标指着的那条一样长，旁边的不跟着变（T779 去掉放大镜）', () => {
  assert.equal(J.tickLength(3, 3, null), J.LEN.active);
  assert.equal(J.tickLength(0, 3, null), J.LEN.base);
  assert.deepEqual([4, 5, 6, 7].map((i) => J.tickLength(i, 0, 5)), [J.LEN.base, J.LEN.hover, J.LEN.base, J.LEN.base]);
  assert.equal(J.tickLength(0, 0, 5), J.LEN.active);
  assert.ok(J.LEN.hover > J.LEN.base && J.LEN.active > J.LEN.base);
});

test('指着哪条：没指着时按高度落在哪条就是哪条，出界的夹到两头', () => {
  assert.equal(J.pickIndex(0, 10, 5, null), 0);
  assert.equal(J.pickIndex(25, 10, 5, null), 2);
  assert.equal(J.pickIndex(-4, 10, 5, null), 0);
  assert.equal(J.pickIndex(80, 10, 5, null), 4);
});

test('指着哪条：已经指着一条时，越过它的边 STICK 像素才换，手抖一两像素不换', () => {
  // 指着第 2 条（20~30）：往下挪到 31、32 还是它，过了 33 才换第 3 条；往上同理
  assert.equal(J.pickIndex(31, 10, 5, 2), 2);
  assert.equal(J.pickIndex(32.9, 10, 5, 2), 2);
  assert.equal(J.pickIndex(33, 10, 5, 2), 3);
  assert.equal(J.pickIndex(17, 10, 5, 2), 2);
  assert.equal(J.pickIndex(16.9, 10, 5, 2), 1);
  // 一下挪远了直接换过去
  assert.equal(J.pickIndex(45, 10, 5, 2), 4);
});

test('指着哪条：刻度压得很密时，粘住的范围不超过半条间距，照样一条一条挪得过去', () => {
  // 间距 3：粘 1.5px；指着第 10 条（30~33），33~34.5 还是它，34.5 起换第 11 条
  assert.equal(J.pickIndex(34, 3, 100, 10), 10);
  assert.equal(J.pickIndex(34.5, 3, 100, 10), 11);
  assert.equal(J.pickIndex(28.6, 3, 100, 10), 10);
  assert.equal(J.pickIndex(28.4, 3, 100, 10), 9);
  // 之前指着的那条已经不在了（条数变少）：按高度重算
  assert.equal(J.pickIndex(5, 3, 2, 10), 1);
});

test('预览卡不出滚动区', () => {
  assert.equal(J.cardTop(5, 100, 600), 8);
  assert.equal(J.cardTop(300, 100, 600), 278);
  assert.equal(J.cardTop(590, 100, 600), 492);
});

test('一行字：去掉 Markdown 记号、压成一行、截断', () => {
  assert.equal(J.oneLine('## 结论\n- **改好了** `a.ts`\n1. 第二', 100), '结论 改好了 a.ts 第二');
  assert.equal(J.oneLine('看 [文档](https://x) 和 ![图](y)', 100), '看 文档 和 图');
  assert.equal(J.oneLine('一二三四五六', 3), '一二三…');
  assert.equal(J.oneLine('frontier_llm 不动', 100), 'frontier_llm 不动');
});
