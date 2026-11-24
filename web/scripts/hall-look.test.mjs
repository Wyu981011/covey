// 大厅和飞书私聊区呼应（T645）的纯函数：话题头像（T 号）的颜色、产物折叠的标题和开合、服务端收产物时留哪些字段。跑：npm run test:hall
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TOPIC_COLORS, TOPIC_STEP, topicColor } from '../client/src/cv/look.gen.ts';
import { artifactFold, fileSize } from '../client/src/cv/artifactList.ts';
import { artifactsOf } from '../shared/api.interface.ts';

const look = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv', 'look.json'), 'utf8'));

test('T 号头像的颜色表就是 covey look.json 的 topics（不手抄）', () => {
  assert.deepEqual([...TOPIC_COLORS], look.topics.colors);
  assert.equal(TOPIC_STEP, look.topics.step);
  assert.equal(TOPIC_COLORS.length, 12);
});

test('取色和 covey core/look.py topic_color 一样：号码 × 5 模 12', () => {
  // 飞书示意图里的 T7 是石板灰（7 × 5 = 35，模 12 是 11）
  assert.equal(topicColor(7), '#475569');
  assert.equal(topicColor(638), TOPIC_COLORS[(638 * 5) % 12]);
  assert.equal(topicColor(12345), TOPIC_COLORS[(12345 * 5) % 12]);
});

test('相邻号码颜色一定不同，连着 12 个不重样', () => {
  for (let n = 1; n < 2000; n += 1) assert.notEqual(topicColor(n), topicColor(n + 1), `T${n} 和 T${n + 1}`);
  for (const start of [1, 600, 9990]) {
    const seen = new Set(Array.from({ length: 12 }, (_, i) => topicColor(start + i)));
    assert.equal(seen.size, 12, `从 T${start} 起`);
  }
});

test('没有号码不给颜色（画一个灰的 T）', () => {
  assert.equal(topicColor(null), null);
  assert.equal(topicColor(undefined), null);
  assert.equal(topicColor(Number.NaN), null);
  assert.equal(topicColor(-1), null);
  assert.equal(topicColor(0), null, '0 是没有号码（covey topic_color(0) 也是 -1）');
});

const up = (name, size = 2048, link = `https://example.feishu.cn/file/${name}`) => ({ name, link, size });

test('没有产物不画折叠', () => {
  assert.equal(artifactFold([]), null);
  assert.equal(artifactFold(undefined), null);
  assert.equal(artifactFold([{ name: '' }]), null);
});

test('都传好了：标题是个数和第一个文件，“等”只在不止一个时写；默认收着', () => {
  assert.deepEqual(artifactFold([up('login-page.diff'), up('REPORT.md')]), { title: '产物 2 个 · login-page.diff 等', bad: '', open: false });
  assert.deepEqual(artifactFold([up('REPORT.md')]), { title: '产物 1 个 · REPORT.md', bad: '', open: false });
});

test('还在传：标题写上传中，不提没传上的', () => {
  const f = artifactFold([up('a.md'), { name: 'b.zip', uploading: true }]);
  assert.deepEqual(f, { title: '产物 2 个 · 上传中', bad: '', open: false });
});

test('有传不上的：标题后面写几个未上传，默认展开（和飞书答案卡一样）', () => {
  const f = artifactFold([up('a.md'), { name: 'big.bin', error: '仅支持非空且不超过 200 MB 的文件' }]);
  assert.deepEqual(f, { title: '产物 2 个 · a.md 等', bad: '1 个未上传', open: true });
});

test('从没传过的旧产物：写未上传，但不自己展开', () => {
  assert.deepEqual(artifactFold([{ name: 'old.md' }]), { title: '产物 1 个 · old.md', bad: '1 个未上传', open: false });
});

test('第一个文件名太长时截断', () => {
  const long = `${'很长的文件名'.repeat(10)}.md`;
  const f = artifactFold([up(long)]);
  assert.ok(f.title.endsWith('…'));
  assert.ok(f.title.length < 60);
});

test('文件大小写法同飞书卡片：MB 一位小数，KB 至少 1', () => {
  assert.equal(fileSize(2048), '2 KB');
  assert.equal(fileSize(10), '1 KB');
  assert.equal(fileSize(5 * 1024 * 1024 + 300000), '5.3 MB');
  assert.equal(fileSize(undefined), '');
});

test('服务端收产物：只留认得的字段，链接只认 https，没名字的不要', () => {
  const got = artifactsOf([
    { name: ' REPORT.md ', link: 'https://example.feishu.cn/file/a', size: 3400.4, extra: '/abs/path' },
    { name: 'x.md', link: 'javascript:alert(1)', size: -1 },
    { name: 'y.md', link: 'http://example.com/y', error: '  上传失败  ' },
    { name: 'z.md', uploading: true },
    { name: '' },
    'bad',
    null,
  ]);
  assert.deepEqual(got, [
    { name: 'REPORT.md', link: 'https://example.feishu.cn/file/a', size: 3400 },
    { name: 'x.md' },
    { name: 'y.md', error: '上传失败' },
    { name: 'z.md', uploading: true },
  ]);
  assert.deepEqual(artifactsOf(undefined), []);
  assert.deepEqual(artifactsOf({ name: 'a' }), []);
  assert.equal(artifactsOf(Array.from({ length: 80 }, (_, i) => ({ name: `f${i}` }))).length, 50);
});

test('在做的状态点是转圈（T749）：侧栏 T 号块角上的和列表里的同一条规则；减少动态效果时不转、画回实心点', async () => {
  const { default: postcss } = await import('postcss');
  const css = postcss.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv', 'unify.css'), 'utf8'));
  const decls = (pick) => {
    const out = {};
    css.walkRules((r) => {
      if (!pick(r)) return;
      r.walkDecls((d) => { out[d.prop] = d.value; });
    });
    return out;
  };
  const inReduce = (r) => r.parent?.type === 'atrule' && /prefers-reduced-motion:\s*reduce/u.test(r.parent.params);
  const spin = decls((r) => !inReduce(r) && r.selector.split(',').map((s) => s.trim()).includes('.cv .dot.tone-running'));
  assert.match(spin.animation ?? '', /\bspin\b.*infinite/u);
  assert.match(spin.border ?? '', /2px solid/u, '线宽 2px：1.5px 会被 Chrome 取整成 1px');
  const corner = decls((r) => !inReduce(r) && r.selector.trim() === '.cv .a-tlogo .dot.tone-running');
  assert.equal(corner.background, 'var(--side)', '侧栏角上的转圈中间填侧栏底色，压住下面的 T 号块');
  const still = decls((r) => inReduce(r) && r.selector.includes('.cv .dot.tone-running'));
  assert.equal(still.animation, 'none');
  assert.equal(still.background, 'var(--c)');
});
