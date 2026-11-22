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

test('长短：眼前这条最长；鼠标指着时它和邻近几条依次变长', () => {
  assert.equal(J.tickLength(3, 3, null), J.LEN.active);
  assert.equal(J.tickLength(0, 3, null), J.LEN.base);
  const near = [5, 6, 7, 8, 9].map((i) => J.tickLength(i, 0, 5));
  assert.deepEqual(near, [J.LEN.near[0], J.LEN.near[1], J.LEN.near[2], J.LEN.near[3], J.LEN.base]);
  assert.ok(J.LEN.near[0] > J.LEN.near[1] && J.LEN.near[1] > J.LEN.near[2] && J.LEN.near[2] > J.LEN.base);
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
