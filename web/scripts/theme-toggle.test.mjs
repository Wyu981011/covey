// 深色、浅色切换（T842，client/src/cv/theme.ts）：常驻的图标按钮，电脑上在侧栏底部（展开、收起和手机抽屉都有），
// 手机在顶栏最右，任何页面都能点；设置页不再另有一块「外观」。跑：npm run test:theme
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { themeFlip } from '../client/src/cv/theme.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const read = (name) => readFileSync(join(CV, name), 'utf8');

/** 一段源码里从 from（一个开标签）开始、到和它配对的闭标签为止：按同名标签的开闭数层数 */
const block = (src, from, tag) => {
  const start = src.indexOf(from);
  assert.ok(start >= 0, `找得到 ${from}`);
  const re = new RegExp(`<${tag}[\\s>]|</${tag}>`, 'gu');
  re.lastIndex = start;
  let depth = 0;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    depth += m[0].startsWith('</') ? -1 : 1;
    if (depth === 0) return src.slice(start, m.index + m[0].length);
  }
  return src.slice(start);
};

test('图标画点了以后换成的那一种：深色时太阳、点了换成浅色；浅色时月亮、点了换成深色', () => {
  assert.deepEqual(themeFlip(false), { next: true, label: '换成浅色', icon: 'sun' });
  assert.deepEqual(themeFlip(true), { next: false, label: '换成深色', icon: 'moon' });
  // 点两下回到原来那种
  assert.equal(themeFlip(themeFlip(false).next).next, false);
  assert.equal(themeFlip(themeFlip(true).next).next, true);
});

test('按钮的叫法照 docs/ui.md 第 6 节：动词开头、2 到 5 个字、不带 emoji', () => {
  for (const light of [false, true]) {
    const { label } = themeFlip(light);
    assert.match(label, /^换成/u);
    assert.ok([...label].length >= 2 && [...label].length <= 5, label);
    assert.doesNotMatch(label, /\p{Extended_Pictographic}/u);
  }
});

test('按钮把叫法写进 title 和 aria-label，点一下照 themeFlip 换、照旧经 setLight 记在这台浏览器上', () => {
  const src = read('ThemeToggle.tsx');
  assert.match(src, /type="button"/u);
  assert.match(src, /title=\{f\.label\}/u);
  assert.match(src, /aria-label=\{f\.label\}/u);
  assert.match(src, /onClick=\{\(\) => setLight\(f\.next\)\}/u);
  assert.match(src, /themeFlip\(ui\.light\)/u);
  // 图标只是装饰，读屏读按钮的叫法
  assert.match(src, /<Sun aria-hidden="true" \/>/u);
  assert.match(src, /<Moon aria-hidden="true" \/>/u);
  const store = read('store.ts');
  assert.match(store, /setPref\('theme', v \? 'light' : 'dark'\)/u);
});

test('侧栏底部常驻：展开、收起、手机抽屉都画，不挑 mini 或 drawer', () => {
  const src = read('Shell.tsx');
  const foot = block(src, '<div className="sidefoot">', 'div');
  assert.match(foot, /^\s*<ThemeToggle \/>$/mu, '单独一行，前面没有 mini ? 或 drawer ? 的条件');
  assert.ok(foot.indexOf('<ThemeToggle />') > foot.indexOf('<Settings />'), '在设置后面');
  assert.ok(foot.indexOf('<ThemeToggle />') < foot.indexOf('<Avatar />'), '在头像前面');
});

test('手机顶栏最右常驻：每一页的 Head（汉堡和返回两种）都画', () => {
  const src = read('Shell.tsx');
  const head = src.slice(src.indexOf('export const Head'), src.indexOf('// 两侧栏拖过的宽度'));
  const mobile = block(head, "<div className={`mtop", 'div');
  assert.match(mobile, /\{right\}\s*\{\/\*[^*]*\*\/\}\s*<ThemeToggle \/>\s*<\/div>$/u, '在 right 后面、顶栏最后一个');
  // 电脑上的页面头不另放：侧栏底部那个一直在
  const desktop = block(head, '<div className="hd">', 'div');
  assert.doesNotMatch(desktop, /ThemeToggle/u);
});

test('设置页不再另有一块「外观」', () => {
  const src = read('Settings.tsx');
  assert.doesNotMatch(src, /Appearance/u);
  assert.doesNotMatch(src, /外观/u);
  assert.doesNotMatch(src, /setLight/u);
});

/** 按顶层的逗号拆选择器：:is(a,b) 里的逗号不拆（同 canvas-look.test.mjs） */
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

/** covey.css 里每条规则展开嵌套后的完整选择器（.cv{} 里的规则前面自动带 .cv）→ 它的声明；后写的盖前写的 */
const cssAt = async (selector) => {
  const { default: postcss } = await import('postcss');
  const out = [];
  const full = (r) => {
    const own = split(r.selector);
    if (r.parent?.type !== 'rule') return own;
    return full(r.parent).flatMap((o) => own.map((s) => (s.includes('&') ? s.replaceAll('&', o) : `${o} ${s}`)));
  };
  postcss.parse(read('covey.css')).walkRules((r) => {
    if (r.parent?.type === 'atrule') return; // 媒体查询里的不算常态
    const decls = {};
    r.each((d) => { if (d.type === 'decl') decls[d.prop] = d.value; });
    out.push({ selectors: full(r), decls });
  });
  return Object.assign({}, ...out.filter((r) => r.selectors.includes(selector)).map((r) => r.decls));
};

test('样式：盖过 .cv button 的 color:inherit，有悬停和键盘焦点；收起的侧栏竖排；手机上点按区 40px', async () => {
  const base = await cssAt('.cv .theme-tg');
  assert.equal(base.color, 'var(--t3)', '.cv .theme-tg（两个类）压过 .cv button（一类一元素）的 color:inherit');
  assert.equal(base.border, '0');
  assert.equal(base.width, '32px');
  assert.deepEqual(await cssAt('.cv .cv .theme-tg'), {}, '.cv{} 嵌套块里的规则不再自带 .cv（否则成了 .cv .cv，一条都不生效）');
  assert.equal((await cssAt('.cv .theme-tg:hover')).color, 'var(--t1)');
  assert.equal((await cssAt('.cv .theme-tg:focus-visible')).outline, '2px solid var(--a1)');
  assert.equal((await cssAt('.cv .sidefoot .theme-tg'))['margin-left'], 'auto', '侧栏底部靠右，头像前面');
  const mini = await cssAt('.cv .side.mini .sidefoot');
  assert.equal(mini['flex-direction'], 'column', '收起的侧栏 56px 宽，竖排');
  assert.equal(mini.height, 'auto');
  const miniBtn = await cssAt('.cv .side.mini .sidefoot .theme-tg');
  assert.equal(miniBtn.order, '-1', '叠在设置上面');
  for (const sel of ['.cv .side.mini .sidefoot .theme-tg', '.cv .mtop .theme-tg', '.cv .drawer-side .sidefoot .theme-tg']) {
    const d = await cssAt(sel);
    assert.equal(d.width, '40px', sel);
    assert.equal(d.height, '40px', sel);
  }
  assert.equal((await cssAt('.cv .mtop .theme-tg:hover')).color, 'var(--t1)', '顶栏的颜色写在后面，悬停另写一条');
});
