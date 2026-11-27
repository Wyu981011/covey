// 话题页换配置（T616，Covey v20）：初值、有没有变化、网页上换不了的情况；面板读不懂机器人的数据时不让整页崩（T97 11-27）。跑：npm run test:switch
import { test } from 'node:test';
import assert from 'node:assert/strict';
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

/* ---------- T97 11-27：一点切换模型网页就崩 ----------
 * 机器人升到上游 T864 以后推的模型目录只有 models、preselect（线上妙搭库 11-27 14:50 导出的那份就是这个形状），
 * 同一次升级里网页没发布上，线上旧网页的换配置面板一画就读 data.workspaces.find，根上的错误边界把整页换成「页面出错了」。 */
const G = await import('../client/src/cv/panelGuard.ts');
const React = (await import('react')).default;
const { renderToStaticMarkup } = await import('react-dom/server');
const { readFileSync } = await import('node:fs');
const V43 = {
  models: [m('claude:opus', { bridge_tools: true }), m('claude:fable', { bridge_tools: true })],
  preselect: { model: 'claude:opus', effort: 'high', redaction: 'off', work_mode: '' },
};
// 旧网页（线上 536a8819）client/src/cv/launch.ts 的 workspaceOf，一字照抄：LaunchPanel 每画一次都经 onDevice 调它
const oldWorkspaceOf = (d, name) => d.workspaces.find((w) => w.name === name);
const crashOf = (f) => {
  try {
    f();
  } catch (e) {
    return e;
  }
  return null;
};
const CRASH = "Cannot read properties of undefined (reading 'find')";
/** <PanelGuard> 展开成它里面的 ErrorBoundary 元素和一个实例（node 里没有 DOM，照 React 的顺序手动走 getDerivedStateFromError → render） */
const guardOf = (props, child = 'panel') => {
  const el = React.createElement(G.PanelGuard, props, child);
  const eb = el.type(el.props);
  return { eb, inst: new eb.type(eb.props) };
};
const buttonOf = (node) => [node.props.children].flat(Infinity).find((c) => c?.type === 'button');

test('复现：线上那份模型目录喂给旧网页的读法，抛的就是页面上那句（T97 11-27）', () => {
  assert.ok(!('workspaces' in V43) && !('run_modes' in V43) && !('workspace' in V43.preselect));
  const e = crashOf(() => oldWorkspaceOf(V43, V43.preselect.workspace));
  assert.ok(e instanceof TypeError);
  assert.equal(e.message, CRASH);
});

test('换配置面板里抛这个错：面板里写明原因和怎么办、给「关闭」，不往上抛（整页不再换成「页面出错了」）', () => {
  const e = crashOf(() => oldWorkspaceOf(V43, ''));
  let closed = 0;
  const { eb, inst } = guardOf({ what: '换配置面板', elsewhere: '在飞书话题里点「换配置」', onClose: () => { closed += 1; } });
  assert.equal(renderToStaticMarkup(inst.render()), 'panel', '没出错原样画面板');
  inst.state = eb.type.getDerivedStateFromError(e);
  const html = renderToStaticMarkup(inst.render());
  assert.match(html, /role="alert"/u);
  assert.match(html, /换配置面板打不开/u);
  assert.match(html, /多半是网页比机器人旧：刷新页面；还不行就在飞书话题里点「换配置」/u);
  assert.match(html, /<button[^>]*>关闭<\/button>/u);
  const fb = eb.props.fallbackRender({ error: e, resetErrorBoundary: () => assert.fail('有 onClose 时不该重画') });
  buttonOf(fb).props.onClick();
  assert.equal(closed, 1, '「关闭」收起面板');
  assert.equal(G.guardText('换配置面板', e), `换配置面板读不懂机器人发来的数据（${CRASH}），多半是网页比机器人旧：刷新页面。`);
});

test('配置栏那一层：小号一行“配置栏出错了”加「重试」，重试就重画；换了话题自己重画', () => {
  const e = new TypeError(CRASH);
  const { eb } = guardOf({ what: '配置栏', compact: true, resetKey: 'topic-a' });
  assert.deepEqual(eb.props.resetKeys, ['topic-a']);
  let reset = 0;
  const fb = eb.props.fallbackRender({ error: e, resetErrorBoundary: () => { reset += 1; } });
  const html = renderToStaticMarkup(fb);
  assert.match(html, /^<span class="guard sm" role="alert" title="配置栏读不懂机器人发来的数据/u);
  assert.match(html, /配置栏出错了<button[^>]*>重试<\/button><\/span>$/u);
  buttonOf(fb).props.onClick();
  assert.equal(reset, 1);
  // 报错不是 Error、是空的、太长：都写得出一句
  assert.match(G.guardText('x', 'boom'), /（boom）/u);
  assert.match(G.guardText('x', null), /（未知错误）/u);
  assert.equal(G.guardText('x', new Error('a'.repeat(500))).match(/a+/u)[0].length, 200);
});

test('配置栏、换配置面板、开新话题的选项都包在 PanelGuard 里', () => {
  const read = (f) => readFileSync(new URL(`../client/src/cv/${f}`, import.meta.url), 'utf8');
  const bar = read('ConfigBar.tsx');
  assert.match(bar, /<PanelGuard what="换配置面板"[^>]*onClose=\{\(\) => setOpen\(false\)\}>\s*<LaunchPanel /u);
  assert.match(bar, /export const ConfigBar: React\.FC<BarProps> = \(props\) => \(\s*<PanelGuard what="配置栏" compact resetKey=\{props\.topic\?\.key\}>\s*<Bar \{\.\.\.props\} \/>/u);
  assert.doesNotMatch(bar, /export const Bar\b/u, '只导出包好的那个');
  const comp = read('Composer.tsx');
  const uses = [...comp.matchAll(/<Launch(?:Panel|Line|Note) box=/gu)];
  assert.equal(uses.length, 6, "手机 3 处、电脑 3 处");
  for (const u of uses) {
    const before = comp.slice(0, u.index);
    assert.ok(before.lastIndexOf('<PanelGuard what={LAUNCH_WHAT}') > before.lastIndexOf('</PanelGuard>'), `第 ${u.index} 个字处的 ${u[0]} 没包在 PanelGuard 里`);
  }
});

test('线上那份模型目录（新 Covey）进换配置的纯函数不抛：初值、变化、能不能确认、负责人', () => {
  const c = { model: 'claude:opus', effort: 'high', work_mode: '', redaction: 'off' };
  const base = S.fromConfig(V43, c);
  assert.deepEqual(S.changedFields(base, base), []);
  assert.deepEqual(S.changedFields(base, { ...base, model: 'claude:fable' }), ['model']);
  assert.equal(S.switchBlock(V43, base, { ...base, model: 'claude:fable' }, false), '');
  assert.equal(S.switchBlock(V43, base, { ...base, model: 'claude:fable' }, false, true), '');
  assert.equal(S.leadData(V43).models.length, 2);
});
