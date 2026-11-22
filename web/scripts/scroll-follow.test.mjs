// 对话区跟随到底的防回归检查（T603：在做的话题持续刷新时，滚轮往上滑失败）。跑：npm run test:scroll
// 模拟一个滚动区：在做的一轮每次刷新多出一段内容，跟随时程序拉到底；你在中间往上滚，断言不被拉回、总览不被程序的滚动收起。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as F from '../client/src/cv/scrollFollow.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');

/** 一个滚动区，照 Conversation.tsx 的接法驱动 scrollFollow：浏览器的滚动事件是异步的，这里在每次改 top 后立刻派发 */
class Feed {
  constructor({ height, client, follow = true }) {
    this.height = height;
    this.client = client;
    this.top = follow ? Math.max(0, height - client) : 0;
    this.s = F.start(follow, this.top);
    this.userAt = -1e9;
    this.now = 0;
    this.overview = 'expanded';
  }
  get m() { return { top: this.top, height: this.height, client: this.client }; }
  get distance() { return F.distance(this.m); }
  apply(step) {
    this.s = step.s;
    if (step.overview) this.overview = step.overview === 'compact' ? 'compact' : 'expanded';
  }
  setTop(v) {
    const t = Math.max(0, Math.min(v, this.height - this.client));
    const changed = t !== this.top;
    this.top = t;
    return changed;
  }
  fire() { this.apply(F.scrolled(this.s, this.m, this.now - this.userAt < 800)); }
  /** 在做的一轮刷新：内容变长，跟随时程序拉到底（Conversation.tsx 的 pull） */
  grow(by) {
    this.now += 2000;
    this.height += by;
    if (!this.s.follow) return;
    const before = this.top;
    if (this.setTop(this.height)) {
      this.s = F.pulled(this.s, before, this.top);
      this.fire();
    }
  }
  /** 滚轮：先有 wheel 事件（intent），浏览器再分几帧平滑滚过去，每帧一个滚动事件；中途可能插进一次刷新 */
  wheel(dy, { frames = 4, refreshAt = -1, refreshBy = 40 } = {}) {
    this.now += 16;
    this.userAt = this.now;
    this.apply(F.intent(this.s, dy < 0 ? 'up' : 'down', this.m));
    for (let i = 0; i < frames; i += 1) {
      this.now += 16;
      if (i === refreshAt) this.grow(refreshBy), (this.userAt = this.now);
      if (this.setTop(this.top + dy / frames)) this.fire();
    }
  }
  /** 拖滚动条：没有 wheel 事件，只有按下和一串滚动事件 */
  drag(to) {
    this.now += 16;
    this.userAt = this.now;
    const step = (to - this.top) / 5;
    for (let i = 0; i < 5; i += 1) {
      this.now += 16;
      this.userAt = this.now;
      if (this.setTop(this.top + step)) this.fire();
    }
  }
}

test('在做的话题持续刷新时往上滚：位置不被拉回，出现「回到最新」', () => {
  const f = new Feed({ height: 2400, client: 500 });
  for (let i = 0; i < 3; i += 1) f.grow(60);
  assert.equal(f.distance, 0, '跟随时新内容贴底');
  // 一格滚轮只有 60px，还在 NEAR_BOTTOM 里：旧代码这里仍算“在底部”，下一次刷新就拉回去
  f.wheel(-60, { refreshAt: 1 });
  const top = f.top;
  assert.equal(f.s.follow, false, '往上滚马上停止跟随');
  for (let i = 0; i < 10; i += 1) f.grow(80);
  assert.equal(f.top, top, '持续刷新不改你的位置');
  assert.ok(F.showLatest(f.s, f.m), '离开底部有「回到最新」');
});

test('往下滚回底部附近恢复跟随', () => {
  const f = new Feed({ height: 2400, client: 500 });
  f.wheel(-400);
  f.grow(100);
  assert.equal(f.s.follow, false);
  f.wheel(f.distance - 30);
  assert.ok(f.distance < F.NEAR_BOTTOM);
  assert.equal(f.s.follow, true, '回到底部附近恢复跟随');
  f.grow(100);
  assert.equal(f.distance, 0, '恢复后新内容又贴底');
  assert.equal(F.showLatest(f.s, f.m), false);
});

test('拖滚动条往上：停止跟随；拖回底：恢复', () => {
  const f = new Feed({ height: 3000, client: 600 });
  f.drag(1000);
  assert.equal(f.s.follow, false);
  f.grow(200);
  assert.equal(f.top, 1000);
  f.drag(f.height - f.client);
  assert.equal(f.s.follow, true);
});

test('跟随拉到底不算你往下滚：总览不被收起（T603 的根因）', () => {
  // 内容只比滚动区高一点：总览一收起，滚动区就滚不动了
  const f = new Feed({ height: 487, client: 456 });
  f.top = 0;
  f.s = F.start(true, 0);
  f.userAt = f.now; // 你刚动过滚轮
  f.grow(40); // 刷新，程序拉到底（71px）
  assert.equal(f.overview, 'expanded', '程序的滚动不能收起总览');
  assert.equal(f.s.downBy, 0);
});

test('总览收起后滚动区滚不动了，往上滚仍能展开', () => {
  const f = new Feed({ height: 600, client: 600 });
  f.overview = 'compact';
  f.wheel(-100); // 滚不动，没有滚动事件
  assert.equal(f.overview, 'expanded');
});

test('你往下滚才收起总览，滚回顶上展开', () => {
  const f = new Feed({ height: 3000, client: 500, follow: false });
  f.wheel(200);
  assert.equal(f.overview, 'compact');
  f.wheel(-300);
  assert.equal(f.top, 0);
  assert.equal(f.overview, 'expanded');
});

test('内容只多出一点时不收起总览（收起后滚不动会被夹回顶上又展开，来回跳）', () => {
  const f = new Feed({ height: 487, client: 316, follow: false });
  f.wheel(171);
  assert.equal(f.distance, 0);
  assert.equal(f.overview, 'expanded');
});

test('点「回到最新」：平滑滚动途中不断跟随，到了继续贴底', () => {
  const f = new Feed({ height: 3000, client: 500 });
  f.wheel(-1500);
  assert.equal(f.s.follow, false);
  f.s = F.home(f.s);
  const to = f.height - f.client;
  for (let i = 1; i <= 6; i += 1) {
    f.now += 50;
    if (f.setTop(f.top + (to - f.top) / (7 - i))) f.fire(); // 不是你的输入
    assert.equal(f.s.follow, true, `平滑滚动第 ${i} 帧仍在跟随`);
  }
  f.grow(100);
  assert.equal(f.distance, 0);
  // 途中你又往上滚：打断
  f.wheel(-300);
  f.s = F.home(f.s);
  f.wheel(-100);
  assert.equal(f.s.follow, false);
  assert.equal(f.s.homing, false);
});

test('到底了还往下滚：恢复跟随（不会再有滚动事件）', () => {
  const f = new Feed({ height: 3000, client: 500 });
  f.wheel(-30);
  assert.equal(f.s.follow, false);
  f.wheel(30);
  assert.equal(f.distance, 0);
  f.wheel(100);
  assert.equal(f.s.follow, true);
});

test('点开一轮让内容变长：不在底部附近就停止跟随', () => {
  const f = new Feed({ height: 2000, client: 500 });
  f.height += 900; // 点开第 1 轮
  f.s = F.clickedResize(f.s, f.m);
  assert.equal(f.s.follow, false);
  f.grow(100);
  assert.notEqual(f.distance, 0);
});

test('Conversation.tsx 接法：用 scrollFollow，不再自己按 800ms 窗口判断收起，也没有旧的 atBottom', () => {
  const src = readFileSync(join(CV, 'Conversation.tsx'), 'utf8');
  assert.match(src, /from '\.\/scrollFollow'/u);
  assert.doesNotMatch(src, /atBottom/u);
  assert.match(src, /F\.pulled\(/u, '程序拉到底要记进 ownTop');
  assert.match(src, /onWheel=\{onWheel\}/u);
  assert.match(src, /回到最新/u);
  // 全站：别处不能再写“设 scrollTop 到 scrollHeight”的自动贴底
  for (const name of ['TopicPage.tsx', 'ButlerPage.tsx', 'ProjectPage.tsx', 'Timeline.tsx', 'Waterfall.tsx', 'TopicOverview.tsx']) {
    assert.doesNotMatch(readFileSync(join(CV, name), 'utf8'), /scrollTop\s*=\s*[^=;]*scrollHeight/u, `${name} 自己贴底`);
  }
});

test('键盘方向', () => {
  assert.equal(F.keyDir('PageUp'), 'up');
  assert.equal(F.keyDir(' ', true), 'up');
  assert.equal(F.keyDir(' '), 'down');
  assert.equal(F.keyDir('a'), null);
});
