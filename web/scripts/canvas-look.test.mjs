// 外槽 + 圆角画布、浅色的字和侧栏 T 号（T753）：样式表里这几条规则还在、没被改回去。跑：npm run test:canvas
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const cv = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const { default: postcss } = await import('postcss');

/** 按顶层的逗号拆选择器：:is(a,b) 里的逗号不拆 */
const split = (selector) => {
  const parts = [];
  let depth = 0;
  let cur = '';
  for (const ch of selector) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (ch === ',' && depth === 0) {
      parts.push(cur.trim());
      cur = '';
    } else cur += ch;
  }
  return [...parts, cur.trim()];
};

/** 一份样式表里每条规则的完整选择器（嵌套的 & 换成外层的）→ 它的声明 */
const rules = (file) => {
  const out = [];
  const full = (r) => {
    const own = split(r.selector);
    if (r.parent?.type !== 'rule') return own;
    const outer = full(r.parent);
    return outer.flatMap((o) => own.map((s) => (s.includes('&') ? s.replaceAll('&', o) : `${o} ${s}`)));
  };
  postcss.parse(readFileSync(join(cv, file), 'utf8')).walkRules((r) => {
    const decls = {};
    r.each((d) => { if (d.type === 'decl') decls[d.prop] = d.value; });
    out.push({ selectors: full(r), decls });
  });
  return out;
};
/** 选择器里有 selector 的那几条规则的声明，后写的盖前写的 */
const at = (list, selector) => Object.assign({}, ...list.filter((r) => r.selectors.includes(selector)).map((r) => r.decls));

test('浅色不用 antialiased：Mac 上它削细浅底深字的常规体；深色照旧开，浅色里彩底白字的小块也照旧开', () => {
  const css = rules('covey.css');
  assert.equal(at(css, '.cv')['-webkit-font-smoothing'], 'antialiased', '深色（默认）开');
  assert.equal(at(css, '.cv.light')['-webkit-font-smoothing'], 'auto');
  assert.equal(at(css, '.cv.light')['-moz-osx-font-smoothing'], 'auto');
  const white = css.find((r) => r.selectors.some((s) => s.startsWith('.cv.light :is(') && s.includes('.a-tbadge') && s.includes('.btn.pri')));
  assert.ok(white, '实心 T 号、主按钮这些彩底白字在浅色里另写');
  assert.equal(white.decls['-webkit-font-smoothing'], 'antialiased');
});

test('浅色界面正文灰（--t2）加深到 #353a46', () => {
  assert.equal(at(rules('covey.css'), '.cv.light')['--t2'], '#353a46');
});

test('句子和标题里的数字用比例数字，表格和代码里的仍等宽；根上默认还是等宽', () => {
  const css = rules('covey.css');
  assert.equal(at(css, '.cv')['font-variant-numeric'], 'tabular-nums');
  const prose = css.find((r) => r.decls['font-variant-numeric'] === 'normal');
  assert.ok(prose, '有一条比例数字的规则');
  for (const part of ['.mdans .prose', '.um-tx', '.ov2-head', '.hd h1', '.a-tt']) assert.ok(prose.selectors[0].includes(part), part);
  assert.equal(at(css, '.cv .mdans .prose :is(table,pre,code)')['font-variant-numeric'], 'tabular-nums');
});

test('电脑上主区是一块圆角画布：四周留 8px、圆角 12px、--bg 换成画布色；侧栏铺在外槽上；手机不变', () => {
  const css = rules('layout-a.css');
  const main = at(css, '.cv:not(.m) .main');
  assert.equal(main.margin, '8px 8px 8px 0');
  assert.equal(main['border-radius'], '12px');
  assert.equal(main.overflow, 'clip', '画布里铺满的东西（页头的渐变）不越过圆角');
  assert.equal(main.background, 'var(--bg)');
  assert.equal(main['--bg'], 'var(--s1)', '画布是面板色，画布里拿 --bg 当遮罩的跟着换');
  assert.equal(at(rules('covey.css'), '.cv.light')['--s1'], '#ffffff', '浅色是白画布');
  assert.equal(at(css, '.cv:not(.m):not(.light)')['--side'], '#060709', '深色电脑上外槽压暗，比画布暗一截');
  assert.equal(at(css, '.cv:not(.m) .app').background, 'var(--side)', '外槽就是侧栏的底色，侧栏状态点的遮罩（--side）对得上');
  const side = at(css, '.cv:not(.m) .side');
  assert.equal(side.background, 'transparent');
  assert.equal(side['border-right'], '0');
  assert.equal(at(css, '.cv:not(.m) :is(.a-rail,.rp)').background, 'transparent', '右栏并进画布');
  assert.ok(!css.some((r) => r.selectors.some((s) => /\.cv\.m\b/u.test(s) && /\.main\b/u.test(s)) && r.decls['border-radius']), '手机不画圆角画布');
});

test('侧栏的 T 号是同色浅底彩字，选中的那个是实心底白字；颜色从 --tc 来，别处照旧实心', () => {
  const side = rules('sidebar.css');
  const tint = at(side, '.cv .a-side .a-tlogo .a-tbadge:not(.none)');
  assert.match(tint.background, /color-mix\(.*var\(--tc\)/u);
  assert.match(tint.color, /color-mix\(.*var\(--tc\)/u);
  const on = at(side, '.cv .a-side .a-tp.on .a-tlogo .a-tbadge:not(.none)');
  assert.equal(on.background, 'var(--tc)');
  assert.equal(on.color, '#fff');
  const light = at(side, '.cv.light .a-side .a-tlogo .a-tbadge:not(.none)');
  assert.match(light.background, /color-mix\(.*var\(--tc\).*transparent\)/u, '和透明混，融进外槽（和白混会比外槽还亮）');
  assert.equal(light['-webkit-font-smoothing'], 'auto', '浅底深字不削细');
  assert.equal(at(side, '.cv.light .a-side .a-tp.on .a-tlogo .a-tbadge:not(.none)').background, 'var(--tc)');
  assert.equal(at(rules('badge.css'), '.cv .a-tbadge').background, 'var(--tc)', '别处是实心块');
  assert.match(readFileSync(join(cv, 'RoleAvatar.tsx'), 'utf8'), /'--tc': color/u, 'TopicBadge 把颜色放进 --tc');
});

test('输入框下沿的上下文用量有一条细进度条，过八成变橙', () => {
  const css = rules('composer.css');
  assert.equal(at(css, '.cv .cp-ctxbar').width, '32px');
  assert.equal(at(css, '.cv .cp-ctxbar i').background, 'var(--a1)');
  assert.equal(at(css, '.cv .cp-ctxbar.full i').background, 'var(--wait)');
  const src = readFileSync(join(cv, 'Conversation.tsx'), 'utf8');
  assert.match(src, /pct >= 80 \? ' full' : ''/u);
});

// T789：T753 给电脑端输入框加了 overflow:hidden 收底座圆角，换配置面板（.cfg-pop，浮在输入框上方）被整块裁掉：点配置胶囊箭头翻上、面板看不见。
// 从底座往外浮的面板：换配置 .cfg-pop（.cfg 里）、由谁汇总的菜单 .rc-menu（.cp-chip > .rc-wrap 里）；它们到输入框之间的每一层都不能裁
const CLIPS = ['overflow', 'overflow-x', 'overflow-y', 'clip-path', 'contain'];
const POP_HOSTS = ['composer', 'cfg', 'cp-chip', 'rc-wrap'];
/** 这条声明会不会裁掉伸出盒子的子元素：overflow 只有 visible 不裁，clip-path 只有 none，contain 带 paint（strict、content 含它）才裁 */
const clips = (prop, value) => (prop === 'contain' ? /paint|strict|content/u.test(value) : prop === 'clip-path' ? value !== 'none' : value !== 'visible');
/** 选择器最后一段（真正被选中的那个元素）带哪些 class */
const lastClasses = (selector) => (selector.split(/[\s>+~]+/u).filter(Boolean).pop() ?? '').replace(/:not\([^)]*\)/gu, '').match(/\.[\w-]+/gu)?.map((c) => c.slice(1)) ?? [];
test('输入框和底座不裁往外浮的面板（T789：换配置面板被 .composer 的 overflow:hidden 裁掉）', () => {
  const files = readdirSync(cv).filter((f) => f.endsWith('.css'));
  const bad = [];
  for (const f of files) {
    for (const r of rules(f)) {
      for (const s of r.selectors) {
        const cls = lastClasses(s);
        const host = cls.some((c) => POP_HOSTS.includes(c)) || (cls.includes('bar') && /\.composer\b/u.test(s));
        if (!host) continue;
        for (const p of CLIPS) {
          const v = r.decls[p];
          if (v && clips(p, v)) bad.push(`${f}: ${s} { ${p}: ${v} }`);
        }
      }
    }
  }
  assert.deepEqual(bad, [], '这些规则会把浮出去的面板裁掉');
  // 底座靠自己的圆角收边（外框 18px 减 1px 边框），不靠裁切
  const css = rules('composer.css');
  assert.equal(at(css, '.cv:not(.m) .composer')['border-radius'], '18px');
  assert.equal(at(css, '.cv:not(.m) .composer .bar')['border-radius'], '0 0 17px 17px');
  // 面板确实浮在输入框外面（不是改成在里面展开绕过去的）
  const pop = at(css, '.cv .cfg-pop');
  assert.equal(pop.position, 'absolute');
  assert.equal(pop.bottom, 'calc(100% + 8px)');
  // 打开后按输入框的框固定定位（ConfigBar + popPlace.ts），高度不超过输入框上沿到视口顶（放大编辑时对话区里放不下，T789）
  const fixed = at(css, '.cv .cfg-pop.fixed');
  assert.equal(fixed.position, 'fixed');
  assert.match(fixed['max-height'], /var\(--room/u);
  assert.match(readFileSync(join(cv, 'ConfigBar.tsx'), 'utf8'), /popPlace\(host\.getBoundingClientRect\(\)/u);
});

test('换配置面板放不下时，「取消」「确认更换」那一行贴在面板底上，不被挤出滚动区（T833，fork Wyu981011/covey 的 1ca78f3）', () => {
  const css = rules('composer.css');
  const foot = at(css, '.cv .cfg-foot');
  assert.equal(foot.position, 'sticky');
  assert.equal(foot.bottom, '0');
  assert.equal(foot.background, 'var(--s1)', '贴底时盖住下面滚过去的字');
  // 面板自己的下内边距归零，留白由贴底的那一行出：不然贴底的行和面板底之间漏一条滚动的字
  assert.match(at(css, '.cv .cfg-pop').padding, / 0$/u);
});
