// 短标签不折行、不被压缩的防回归检查（covey docs/ui.md 4.1）。跑：npm run test:tags
// 1. tags.css 里那条公共规则还在，并且是 white-space:nowrap + flex-shrink:0；
// 2. 必须覆盖的短标签类都在表里（问题卡的序号和徽标、状态胶囊、T 号、计数……）；
// 3. 别处的样式没有把表里的类改回能折行、能压缩；
// 4. 页面代码里新出现的“像短标签的”类名（…tag、…pill、…badge、…cnt、…tno、…flag）都在表里；
// 5. 问题卡选项是三列：序号列固定宽，徽标单独一列，不占文字的位置。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const css = (name) => postcss.parse(readFileSync(join(CV, name), 'utf8'));
const MUST = ['.tag', '.pill', '.opt > .n', '.a-tn', '.a-tno', '.nb-tno', '.a-cnt', '.a-badge', '.td-tag', '.st-tag', '.short'];
const LOOKS_SHORT = /^(?:[a-z0-9]+-)*(?:tag|pill|badge|cnt|tno|flag)$/u;

function shortRule() {
  let found = null;
  css('tags.css').walkRules((r) => {
    if (r.selector.includes(':where(')) found = r;
  });
  return found;
}

function shortList() {
  const r = shortRule();
  const inner = r.selector.slice(r.selector.indexOf(':where(') + 7, r.selector.lastIndexOf(')'));
  return inner.split(',').map((s) => s.replace(/\s+/gu, ' ').trim()).filter(Boolean);
}

test('公共规则：不折行、不被压缩', () => {
  const r = shortRule();
  assert.ok(r, 'tags.css 里找不到 :where(...) 那条短标签规则');
  const decl = Object.fromEntries(r.nodes.filter((n) => n.type === 'decl').map((d) => [d.prop, d.value]));
  assert.equal(decl['white-space'], 'nowrap');
  assert.equal(decl['flex-shrink'], '0');
});

test('必须覆盖的短标签都在表里', () => {
  const list = shortList();
  for (const m of MUST) assert.ok(list.includes(m), `短标签表里少了 ${m}`);
});

test('别处没有把短标签改回能折行、能压缩', () => {
  const simple = new Set(shortList().filter((s) => /^\.[\w-]+$/u.test(s)).map((s) => s.slice(1)));
  const bad = [];
  for (const f of readdirSync(CV).filter((n) => n.endsWith('.css') && n !== 'tags.css')) {
    css(f).walkRules((r) => {
      const last = r.selector.split(',').map((s) => s.trim().split(/[\s>+~]+/u).pop() ?? '');
      const hits = last.filter((s) => s.split('.').slice(1).some((c) => simple.has(c.replace(/[:[].*$/u, ''))));
      if (!hits.length) return;
      r.walkDecls((d) => {
        if (d.prop === 'white-space' && !/nowrap|pre/u.test(d.value)) bad.push(`${f}: ${r.selector} { white-space:${d.value} }`);
        if (d.prop === 'flex-shrink' && d.value.trim() !== '0') bad.push(`${f}: ${r.selector} { flex-shrink:${d.value} }`);
        if (d.prop === 'flex' && /^(1|auto)\b/u.test(d.value.trim())) bad.push(`${f}: ${r.selector} { flex:${d.value} }`);
      });
    });
  }
  assert.deepEqual(bad, []);
});

test('页面代码里像短标签的类名都在表里', () => {
  const list = new Set(shortList().map((s) => s.replace(/^.*\./u, '')));
  const miss = new Set();
  for (const f of readdirSync(CV).filter((n) => n.endsWith('.tsx'))) {
    const src = readFileSync(join(CV, f), 'utf8');
    for (const m of src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/gu)) {
      for (const tok of (m[1] ?? m[2] ?? '').replace(/\$\{[^}]*\}/gu, ' ').split(/\s+/u)) {
        if (LOOKS_SHORT.test(tok) && !list.has(tok)) miss.add(`${f}: ${tok}`);
      }
    }
  }
  assert.deepEqual([...miss], [], '新的短标签类名要加进 tags.css 的表（或改用 class="short"）');
});

test('问题卡选项：序号列固定宽，徽标单独一列', () => {
  let grid = null;
  let tagCol = null;
  css('tags.css').walkRules((r) => {
    if (r.selector === '.cv .opt') grid = r;
    if (r.selector === '.cv .opt > .tag') tagCol = r;
  });
  assert.ok(grid, '.cv .opt 规则不见了');
  const cols = grid.nodes.find((d) => d.prop === 'grid-template-columns')?.value ?? '';
  assert.match(cols, /^\d+px minmax\(0, ?1fr\) auto$/u);
  assert.equal(tagCol?.nodes.find((d) => d.prop === 'grid-column')?.value, '3');
});
