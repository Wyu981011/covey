// 话题页换配置（T616，Covey v20）：初值、有没有变化、网页上换不了的情况；面板不被裁掉、不被挡住（T97）。跑：npm run test:switch
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as S from '../client/src/cv/switchConfig.ts';

const m = (key, extra = {}) => ({
  key, harness: key.split(':')[0], harness_title: key.split(':')[0], provider: '', provider_title: '自带', label: key,
  budgets: [{ value: 'high', text: '高' }, { value: 'low', text: '低' }], default_budget: 'high', start_budget: 'high',
  redaction: true, work_modes: [], ...extra,
});
const D = {
  models: [m('claude:opus'), m('codex:gpt', { redaction: false, work_modes: ['auto', 'fast'], start_budget: 'low' })],
  workspaces: [{ name: 'covey', device: '', harnesses: [] }, { name: 'ws-root', device: '', harnesses: [] }],
  run_modes: [{ value: 'direct', text: '原目录' }, { value: 'worktree', text: '独立 worktree' }],
  preselect: { model: 'claude:opus', effort: 'high', work_mode: '', redaction: 'off', workspace: 'covey', run_mode: 'direct' },
};
const C = { model: 'claude:opus', effort: 'high', work_mode: '', workspace: 'covey', run_mode: 'direct', redaction: 'on' };

test('初值补成模型能选的', () => {
  assert.deepEqual(S.fromConfig(D, C), C);
  assert.equal(S.fromConfig(D, { ...C, effort: 'max' }).effort, 'high');
  const g = S.fromConfig(D, { ...C, model: 'codex:gpt', effort: 'zzz' });
  assert.deepEqual([g.effort, g.work_mode, g.redaction], ['low', 'auto', 'off']);
  assert.equal(S.fromConfig(D, { ...C, model: 'gone:x' }).model, 'gone:x');
});

test('没动过不算变化，只补齐也不算', () => {
  const base = S.fromConfig(D, { ...C, effort: 'max' });
  assert.deepEqual(S.changedFields(base, { ...base }), []);
  assert.deepEqual(S.changedFields(base, { ...base, effort: 'low', workspace: 'ws-root' }), ['effort', 'workspace']);
});

test('换不了的情况', () => {
  const base = S.fromConfig(D, C);
  assert.equal(S.switchBlock(D, base, { ...base, effort: 'low' }, false), '');
  assert.equal(S.switchBlock(D, base, { ...base, effort: 'low' }, true), '在做时不能换，先停止');
  assert.match(S.switchBlock(D, base, { ...base, run_mode: 'worktree' }, false), /飞书的换配置卡/u);
  const wt = { ...base, run_mode: 'worktree' };
  assert.equal(S.switchBlock(D, wt, { ...wt, effort: 'low' }, false), '');
  assert.match(S.switchBlock(D, wt, { ...wt, workspace: 'ws-root' }, false), /飞书的换配置卡/u);
  assert.equal(S.switchBlock(D, wt, { ...wt, run_mode: 'direct' }, false), '');
  const gone = { ...base, model: 'gone:x' };
  assert.match(S.switchBlock(D, gone, gone, false), /重选模型/u);
});

// v36：专项负责人的换配置（同飞书专项卡上的「换配置」）：只列能当负责人的模型（bridge_tools），不查 worktree，在做时等它做完
const L = {
  ...D,
  models: [m('claude:opus', { bridge_tools: true }), m('codex:gpt', { redaction: false, bridge_tools: true }), m('pi:gpt')],
};

test('负责人的目录只留能当负责人的模型', () => {
  assert.deepEqual(S.leadData(L).models.map((x) => x.key), ['claude:opus', 'codex:gpt']);
  assert.deepEqual(S.leadData(D).models, []);
  // 别的字段原样（面板的工作区、运行方式等照旧从它取）
  assert.equal(S.leadData(L).workspaces, L.workspaces);
  assert.equal(L.models.length, 3);
});

test('负责人换不了的情况', () => {
  const base = S.fromConfig(L, C);
  assert.equal(S.switchBlock(L, base, { ...base, effort: 'low' }, false, true), '');
  assert.equal(S.switchBlock(L, base, { ...base, model: 'codex:gpt' }, false, true), '');
  assert.equal(S.switchBlock(L, base, { ...base, effort: 'low' }, true, true), '负责人在做时不能换，等它做完');
  assert.equal(S.switchBlock(L, base, { ...base, model: 'pi:gpt' }, false, true), S.LEAD_ONLY);
  // 负责人现在的模型不能当负责人（Harness 换过能力）：没改也说清为什么
  const pi = S.fromConfig(L, { ...C, model: 'pi:gpt' });
  assert.equal(S.switchBlock(L, pi, pi, false, true), S.LEAD_ONLY);
  assert.match(S.switchBlock(L, base, { ...base, model: 'gone:x' }, false, true), /重选模型/u);
  // 工作区、运行方式面板上不画，不查 worktree（Covey 那边拒绝换）
  const wt = { ...base, run_mode: 'worktree' };
  assert.equal(S.switchBlock(L, wt, { ...wt, effort: 'low' }, false, true), '');
  // 普通话题照旧：不看 bridge_tools
  assert.equal(S.switchBlock(L, base, { ...base, model: 'pi:gpt' }, false), '');
  assert.equal(S.switchBlock(L, base, { ...base, model: 'pi:gpt' }, false, false), '');
});

test('面板最高到对话区上沿，留一点空；再矮也留得下标题和确认那一行', () => {
  // 面板下沿在 760，对话区上沿在 60：最高 760 - 60 - 8
  assert.equal(S.popRoom(760, 60), 692);
  assert.equal(S.popRoom(760.9, 60.2), 692, '取整往下，不多出半个像素被裁');
  // 手机矮屏（390×560）：面板下沿 377，对话区从话题头下面的 52 起，原来 60vh = 336 的面板顶上被话题头盖住 11px
  assert.equal(S.popRoom(377, 52), 317);
  // 输入框放大以后上面几乎没地方：不缩成一条
  assert.equal(S.popRoom(150, 60), S.POP_MIN);
  assert.equal(S.popRoom(0, 60), S.POP_MIN);
});

// 样式表：client/src/cv 下全部 .css，嵌套的 & 换成外层选择器（v2.css、v3.css 是嵌套写的）
const cv = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const { default: postcss } = await import('postcss');
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
const sheets = readdirSync(cv).filter((f) => f.endsWith('.css'));
const rules = sheets.flatMap((file) => {
  const out = [];
  const full = (r) => {
    const own = split(r.selector);
    if (r.parent?.type !== 'rule') return own;
    const outer = full(r.parent);
    return outer.flatMap((o) => own.map((x) => (x.includes('&') ? x.replaceAll('&', o) : `${o} ${x}`)));
  };
  postcss.parse(readFileSync(join(cv, file), 'utf8')).walkRules((r) => {
    if (r.parent?.type === 'atrule' && r.parent.name === 'keyframes') return;
    const decls = {};
    r.each((d) => { if (d.type === 'decl') decls[d.prop] = d.value; });
    out.push({ file, selectors: full(r), decls });
  });
  return out;
});
/** 选择器最后一段（最右边的那个元素）是不是带 cls 这个类；伪元素（::before）不算那个元素本身 */
const lands = (selector, cls) => {
  const last = selector.split(/[\s>+~]+/u).filter(Boolean).pop() ?? '';
  return !last.includes('::') && new RegExp(`\\.${cls}(?![\\w-])`, 'u').test(last.replace(/:(?:not|is|where|has)\([^)]*\)/gu, ''));
};
const at = (selector) => Object.assign({}, ...rules.filter((r) => r.selectors.includes(selector)).map((r) => r.decls));

test('换配置面板浮在输入框上面：输入框和配置栏那一行都不许裁掉溢出（T753 给输入框加 overflow:hidden，电脑上面板整块看不见，T97）', () => {
  const clip = /\b(hidden|clip|auto|scroll)\b/u;
  for (const cls of ['composer', 'bar', 'cfg']) {
    for (const r of rules) {
      for (const sel of r.selectors.filter((x) => lands(x, cls))) {
        for (const prop of ['overflow', 'overflow-x', 'overflow-y']) {
          assert.doesNotMatch(r.decls[prop] ?? '', clip, `${r.file} 的 ${sel} 设了 ${prop}:${r.decls[prop]}`);
        }
      }
    }
  }
  // 选择器判断本身：带类的元素算，它里面的元素和伪元素不算
  assert.ok(lands('.cv:not(.m) .composer', 'composer'));
  assert.ok(lands('.cv div.composer', 'composer'));
  assert.ok(!lands('.cv .composer .bar', 'composer'));
  assert.ok(!lands('.composer::before', 'composer'));
  assert.ok(!lands('.cv:not(.composer) .x', 'composer'));
});

test('圆角还是底座自己画：去掉 overflow:hidden 以后底座的灰底不露出输入框的圆角', () => {
  assert.equal(at('.cv:not(.m) .composer')['border-radius'], '18px');
  assert.equal(at('.cv:not(.m) .composer .bar')['border-radius'], '0 0 17px 17px');
  assert.equal(at('.cv:not(.m) .composer .cp-drop')['border-radius'], '17px');
});

test('面板最高不过对话区上沿（--cfg-room），放不下时确认那一行贴在面板底上', () => {
  assert.match(at('.cv .cfg-pop')['max-height'], /var\(--cfg-room/u);
  assert.match(at('.cv .mcfg .cfg-pop')['max-height'], /var\(--cfg-room/u);
  assert.equal(at('.cv .cfg-pop')['overflow-y'], 'auto');
  const foot = at('.cv .cfg-foot');
  assert.equal(foot.position, 'sticky');
  assert.equal(foot.bottom, '0');
  assert.equal(foot.background, 'var(--s1)', '有底色：滚上去的选项不透出来');
});

// T789：换配置面板按输入框的框固定定位（对话区 overflow:hidden，放大编辑时 absolute 的面板上半截被裁掉）
const P = await import('../client/src/cv/popPlace.ts');
test('面板贴着输入框上沿往上、和输入框一样宽，最多高到视口顶', () => {
  // 电脑 1440×900：输入框上沿 794，左 278 宽 800
  assert.deepEqual(P.popPlace({ top: 794, left: 278, width: 800 }, 900), { left: 278, width: 800, bottom: 114, room: 778 });
  // 放大编辑：输入框上沿 270（对话区里上面只剩 50 像素），面板照样能有 254 像素高，不靠对话区给地方
  assert.deepEqual(P.popPlace({ top: 270, left: 290, width: 800 }, 900), { left: 290, width: 800, bottom: 638, room: 254 });
  // 手机的配置栏一行，间隔 6
  assert.deepEqual(P.popPlace({ top: 690.4, left: 10, width: 370 }, 844, 6), { left: 10, width: 370, bottom: 160, room: 676 });
});

test('输入框跑出视口时面板不跟着跑出去：上沿按视口夹住，地方不会是负的', () => {
  assert.equal(P.popPlace({ top: -40, left: 0, width: 300 }, 800).room, 0);
  assert.equal(P.popPlace({ top: -40, left: 0, width: 300 }, 800).bottom, 808);
  assert.equal(P.popPlace({ top: 1200, left: 0, width: 300 }, 800).bottom, 8);
});
