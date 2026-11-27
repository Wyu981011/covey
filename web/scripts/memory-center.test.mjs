// 记忆中心（数据约定 v43，client/src/cv/memoryCenter.ts）的纯函数：拉哪些键、条目归页签和范围、决定默认只看在办、体检只留非 0 项、
// 灰字去重、17 个动作的 payload（过服务端 checkMemoryEdit 的 v43 校验）、⌘K 标题秒搜、预览、导入、记录。数据用
// tests/golden/web_memory_v43.json（合成数据）。跑：npm run test:memcenter
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as C from '../client/src/cv/memoryCenter.ts';
import * as P from '../client/src/cv/progressData.ts';
import { checkMemoryEdit } from '../server/modules/workbench/workbench.memory-edit.ts';
import { MEMORY_EDIT_ACTIONS_V43, MEMORY_TABS } from '../shared/api.interface.ts';

const golden = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'tests', 'golden', 'web_memory_v43.json'), 'utf8'));
const K = golden.keys;
const idx = K['memory:index'];
const pool = () => C.poolOf(K['memory:global'], K['memory:topics'], [K['memory:p:demo01']]);
const passes = (p) => assert.doesNotThrow(() => checkMemoryEdit(p, {}), JSON.stringify(p));

test('页签：5 个，顺序同契约 MEMORY_TABS；导入不是页签；有待审核默认停在待审核', () => {
  assert.deepEqual([...C.TABS], [...MEMORY_TABS]);
  assert.deepEqual(C.TABS.map((t) => C.TAB_WORD[t]), ['待审核', '规矩', '决定', '资料', '记录']);
  assert.equal(C.TABS.includes('import'), false);
  assert.equal(C.defaultTab(idx), 'review');
  assert.equal(C.defaultTab({ counts: { ...idx.counts, pending: 0 } }), 'rules');
  assert.equal(C.defaultTab(null), 'rules');
  for (const t of C.TABS) assert.ok(!C.TAB_NOTE[t] || Array.from(C.TAB_NOTE[t]).length <= 30, t);
});

test('index：认 v43 的，v37 的形状和缺字段的不认', () => {
  assert.equal(C.isMemoryIndex(idx), true);
  assert.equal(C.isMemoryIndex({ on: true, groups: [] }), false);
  assert.equal(C.isMemoryIndex({ ...idx, version: 37 }), false);
  assert.equal(C.isMemoryIndex(null), false);
});

test('拉哪些键：全局、话题、专项一直拉；预览、导入页打开才拉；index 自己和没有 rev 的不拉', () => {
  const base = C.keysToLoad(idx).map((k) => k.key);
  assert.deepEqual(base, ['memory:global', 'memory:p:demo01', 'memory:topics']);
  const all = C.keysToLoad(idx, { previews: true, importPage: 0 }).map((k) => k.key);
  assert.deepEqual(all, ['memory:global', 'memory:import:0', 'memory:p:demo01', 'memory:previews', 'memory:topics']);
  assert.deepEqual(C.keysToLoad(idx, { importPage: 3 }).map((k) => k.key), base, '没有的导入页不拉');
  assert.equal(C.keysToLoad(idx).find((k) => k.key === 'memory:global').rev, 'gv1');
  assert.deepEqual(C.keysToLoad(null), []);
  assert.deepEqual(C.keysToLoad({ revs: { 'memory:global': '' } }), []);
});

test('合成一池：三处的条目都在，话题条目补上话题 key 和 T 号，专项名和话题名能查', () => {
  const p = pool();
  assert.equal(p.entries.length, 5);
  assert.equal(p.review.length, 3);
  assert.equal(p.log.length, 2);
  assert.equal(p.projects.demo01, '演示专项');
  assert.deepEqual(p.topics.t001, { number: 12, title: '演示话题' });
  const dup = C.poolOf(K['memory:global'], null, [{ key: 'p:x1y2z3', title: 'X', entries: [K['memory:global'].entries[0]] }]);
  assert.equal(dup.entries.length, 2, '同 key 只留一条');
});

test('页签与范围：规矩、资料只看 active；决定默认只看在办，能切全部、已办', () => {
  const p = pool();
  assert.deepEqual(C.tabEntries(p, 'rules', 'all').map((e) => e.code).sort(), ['RK7M2Q', 'RT4P8D']);
  assert.deepEqual(C.tabEntries(p, 'rules', 'global').map((e) => e.code), ['RK7M2Q']);
  assert.deepEqual(C.tabEntries(p, 'rules', 'topics').map((e) => e.code), ['RT4P8D']);
  assert.deepEqual(C.tabEntries(p, 'notes', 'all').map((e) => e.code).sort(), ['NQ3X9A', 'NT6B3Y']);
  assert.deepEqual(C.tabEntries(p, 'decisions', 'all').map((e) => e.code), ['DB2H5W']);
  assert.deepEqual(C.tabEntries(p, 'decisions', 'p:demo01').map((e) => e.code), ['DB2H5W']);
  assert.deepEqual(C.tabEntries(p, 'decisions', 'global').map((e) => e.code), []);
  const closed = { ...p, entries: p.entries.map((e) => (e.kind === 'decision' ? { ...e, in_progress: false } : e)) };
  assert.deepEqual(C.tabEntries(closed, 'decisions', 'all', 'open'), [], '办完的默认不显示');
  assert.deepEqual(C.tabEntries(closed, 'decisions', 'all', 'done').map((e) => e.code), ['DB2H5W']);
  assert.deepEqual(C.tabEntries(closed, 'decisions', 'all', 'all').map((e) => e.code), ['DB2H5W']);
  assert.deepEqual(C.decisionCounts(closed, 'all'), { open: 0, done: 1, all: 1 });
  assert.deepEqual(C.decisionCounts(p, 'all'), { open: 1, done: 0, all: 1 });
  assert.deepEqual(C.tabEntries(p, 'review', 'all'), [], '待审核、记录不是条目页签');
  assert.deepEqual(C.tabEntries(p, 'rules', 'all', 'open', 'rk7').map((e) => e.code), ['RK7M2Q'], '按短码筛');
  assert.deepEqual(C.tabEntries(p, 'notes', 'all', 'open', '超时').map((e) => e.code), ['NT6B3Y'], '按正文筛');
  const archived = { ...p, entries: p.entries.map((e) => (e.code === 'NQ3X9A' ? { ...e, status: 'archived' } : e)) };
  assert.deepEqual(C.tabEntries(archived, 'notes', 'all').map((e) => e.code), ['NT6B3Y']);
  assert.deepEqual(C.shelved(archived, 'notes', 'all').map((e) => e.code), ['NQ3X9A'], '归档的收在“已收起”里能放回');
});

test('范围下拉：全部、全局、话题、各专项，带待审核数', () => {
  const o = C.scopeOptions(idx);
  assert.deepEqual(o.map((x) => x.value), ['all', 'global', 'topics', 'p:demo01']);
  assert.deepEqual(o.map((x) => x.label), ['全部范围', '全局', '话题', '演示专项']);
  assert.equal(o[0].pending, 3);
  assert.equal(o[1].pending, 3);
  assert.equal(C.reviewItems(pool(), 'global').length, 3);
  assert.equal(C.reviewItems(pool(), 'p:demo01').length, 0);
});

test('体检：只画非 0 项；全 0（{}）时一行“暂无异常”；矛盾按对数', () => {
  const rows = C.healthRows(idx.health);
  assert.deepEqual(rows.map((r) => [r.word, r.n]), [['矛盾', 1], ['重复', 2], ['可能过期', 1]]);
  assert.deepEqual(rows[0].refs, ['global:g4d5e6', 'review:conflict:b2']);
  assert.deepEqual(C.healthRows({}), []);
  assert.deepEqual(C.healthRows({ dup: [], idle: [] }), [], '空数组也算 0');
  assert.deepEqual(C.healthRows(undefined), []);
  assert.equal(C.HEALTH_OK, '暂无异常');
});

test('灰字去重：不写页签名，规矩不写“带过 N 轮”；只在“全部范围”时写范围；出处和范围同一个 T 号不重复', () => {
  const p = pool();
  const rule = p.entries.find((e) => e.code === 'RK7M2Q');
  const all = C.metaLine(rule, { scope: 'all', pool: p });
  assert.deepEqual(all, ['你说的', '全局', '来自 T12']);
  assert.deepEqual(C.metaLine(rule, { scope: 'global', pool: p }), ['你说的', '来自 T12'], '选了范围就不再写范围');
  const topicRule = p.entries.find((e) => e.code === 'RT4P8D');
  assert.deepEqual(C.metaLine(topicRule, { scope: 'all', pool: p }), ['你说的', 'T12'], 'T12 不重复');
  const dec = p.entries.find((e) => e.code === 'DB2H5W');
  assert.deepEqual(C.metaLine(dec, { scope: 'all', view: 'open', pool: p }), ['负责人记的', '演示专项', '来自 T12']);
  assert.deepEqual(C.metaLine(dec, { scope: 'all', view: 'all', pool: p }).at(-1), '在办');
  const note = p.entries.find((e) => e.code === 'NQ3X9A');
  assert.equal(C.metaLine(note, { scope: 'global', pool: p })[0], '自动学的');
  for (const e of p.entries) {
    const line = C.metaLine(e, { scope: 'all', view: 'all', pool: p }).join(' · ');
    assert.doesNotMatch(line, /带过|规矩|资料|决定记录|常驻|长期约定|当前决定|待核对参考/u, line);
    assert.ok(C.metaLine(e, { scope: 'all', view: 'all', pool: p }).length <= 4);
  }
});

test('配额：80% 以下中性，80%~100% near，超额 over 并写放不下只列标题', () => {
  assert.equal(C.roomOf(idx.scopes[0]).tone, 'ok');
  assert.equal(C.roomOf({ rules: { items: 25, chars: 100, item_limit: 30, char_limit: 3000 } }).tone, 'near');
  const over = C.roomOf({ rules: { items: 32, chars: 3100, item_limit: 30, char_limit: 3000 } });
  assert.equal(over.tone, 'over');
  assert.match(over.words, /超出 2 条，放不下的只列标题/u);
  assert.match(C.roomOf(idx.scopes[0]).words, /^1\/30 条 · 20\/3,000 字$/u);
});

test('17 个动作：payload 都带 v: 43，都过服务端 v43 校验；动一条的带 base = 条目 rev', () => {
  const p = pool();
  const rule = p.entries.find((e) => e.code === 'RK7M2Q');
  const topicNote = p.entries.find((e) => e.code === 'NT6B3Y');
  const dec = p.entries.find((e) => e.code === 'DB2H5W');
  const [learn, conflict] = p.review;
  const made = [
    C.addOp({ title: '提交前先跑测试', text: '提交前先跑相关测试。', kind: 'rule', scope: 'global' }),
    C.editOp(rule, { title: rule.title, text: '改过的正文', why: '' }),
    C.moveOp(rule, { scope: 'project', project_key: 'demo01' }),
    C.archiveOp(rule),
    C.restoreOp(rule),
    C.voidOp(dec, '决定已作废'),
    C.acceptOp(learn),
    C.rejectOp(learn),
    C.allOp('accept_all', p.review),
    C.allOp('reject_all', p.review),
    C.keepOp('keep_left', conflict),
    C.keepOp('keep_right', conflict),
    C.keepOp('keep_both', conflict),
    C.promoteOp(topicNote, C.promoteTarget(topicNote, 'demo01')),
    C.importOp(['fp-0001']),
    C.ignoreOp(['fp-0003']),
    C.undoOp('u-0001'),
  ];
  assert.deepEqual(made.map((x) => x.action).sort(), [...MEMORY_EDIT_ACTIONS_V43].sort());
  for (const x of made) {
    assert.equal(x.v, 43);
    assert.ok(Array.isArray(x.keys));
    passes(x);
  }
  assert.equal(made[1].base, 'rrk7m2q');
  assert.equal(made[1].kind, 'rule', '改的时候带 kind，服务端按它数正文上限');
  assert.equal(made[2].base, 'rrk7m2q');
  assert.equal(made[3].base, 'rrk7m2q');
  assert.deepEqual(made[10].keys, ['global:g4d5e6', 'review:conflict:b2'], '左边是已有的，右边是新来的');
  assert.deepEqual(made[8].keys, ['review:learn:a1', 'review:conflict:b2', 'review:tidy:c3'], '全部采纳带上眼前这几条的 key');
  assert.deepEqual(made[13].keys, ['topic:t001:n4e5f6']);
  assert.equal(made[13].scope, 'project');
  assert.equal(made[13].project_key, 'demo01');
  assert.equal('why' in made[1], false, '空的不带');
  // 决定正文能到 600 字
  passes(C.editOp(dec, { title: dec.title, text: '字'.repeat(600) }));
  assert.throws(() => checkMemoryEdit(C.editOp(rule, { title: rule.title, text: '字'.repeat(201) }), {}), /200/u);
  // 采纳前改了标题、范围
  const acc = C.acceptOp(learn, { title: '回复先说结论再说原因', kind: 'rule', scope: 'project', project_key: 'demo01' });
  assert.equal(acc.title, '回复先说结论再说原因');
  assert.equal(acc.project_key, 'demo01');
  assert.equal(C.acceptOp(learn, { title: learn.title }).title, undefined, '没改的不带');
  passes(acc);
});

test('往上提：话题 → 专项（没有专项就全局），专项 → 全局，全局不能再提', () => {
  assert.deepEqual(C.promoteTarget({ scope: 'topic', project_key: 'demo01' }), { scope: 'project', project_key: 'demo01' });
  assert.deepEqual(C.promoteTarget({ scope: 'topic' }), { scope: 'global' });
  assert.deepEqual(C.promoteTarget({ scope: 'project', project_key: 'demo01' }), { scope: 'global' });
  assert.equal(C.promoteTarget({ scope: 'global' }), null);
});

test('编辑框：标题、正文必填，按 index.limits 数字（决定 600）', () => {
  const l = C.limitsOf(idx, 'rule');
  assert.deepEqual(l, { title: 40, text: 200, why: 200 });
  assert.equal(C.limitsOf(idx, 'decision').text, 600);
  assert.equal(C.limitsOf(null, 'decision').text, 600);
  assert.equal(C.draftProblem({ title: '', text: 'x' }, l), '要写标题');
  assert.equal(C.draftProblem({ title: 'x', text: ' ' }, l), '要写正文');
  assert.equal(C.draftProblem({ title: '字'.repeat(41), text: 'x' }, l), '标题最多 40 字');
  assert.equal(C.draftProblem({ title: 'x', text: '字'.repeat(201) }, l), '正文最多 200 字');
  assert.equal(C.draftProblem({ title: 'x', text: 'y', why: '字'.repeat(201) }, l), '原因最多 200 字');
  assert.equal(C.draftProblem({ title: 'x', text: 'y' }, l), '');
  assert.equal(C.charCount('😀测试'), 3);
});

test('⌘K：标题表秒搜，短码完全一样的最前，不分大小写，最多 n 条', () => {
  assert.deepEqual(C.searchTitles(idx.titles, '测试').map((h) => h.code), ['RK7M2Q']);
  assert.deepEqual(C.searchTitles(idx.titles, 'nq3x9a').map((h) => h.code), ['NQ3X9A']);
  assert.deepEqual(C.searchTitles(idx.titles, 'demo').map((h) => h.code), ['RT4P8D']);
  assert.equal(C.searchTitles(idx.titles, '').length, 0);
  assert.equal(C.searchTitles(null, 'x').length, 0);
  const many = Array.from({ length: 30 }, (_, i) => [`R${i}`, `规矩 ${i}`, `global:g${i}`]);
  assert.equal(C.searchTitles(many, '规矩', 8).length, 8);
  assert.deepEqual(C.searchTitles([['RAB', 'x', 'k1'], ['RA', 'y', 'k2']], 'ra').map((h) => h.code), ['RA', 'RAB'], '完全一样的在前');
  assert.equal(C.tabOfCode('DB2H5W'), 'decisions');
  assert.equal(C.tabOfCode('nt6b3y'), 'notes');
  assert.equal(C.codeHref('RK7M2Q'), '/memory?code=RK7M2Q');
  const hit = C.locate(pool(), 'rk7m2q');
  assert.equal(hit.tab, 'rules');
  assert.equal(C.locate(pool(), 'NOPE'), null);
});

test('预览：四段（规矩、决定、资料、只列标题），短码换成标题，空段不画', () => {
  const p = pool();
  const titles = C.titleIndex(p.entries, idx.titles);
  const [first, fresh] = K['memory:previews'].previews;
  const s = C.previewSections(first, (c) => titles.get(c) ?? '');
  assert.deepEqual(s.map((x) => x.word), ['规矩', '决定', '资料', '没带全文，只列标题']);
  assert.equal(s[0].rows[0].title, '提交前先跑测试');
  assert.equal(s[2].rows[0].why, '相关 0.82');
  assert.deepEqual(C.previewSections(fresh, (c) => titles.get(c) ?? '').map((x) => x.key), ['rules']);
});

test('导入：按来源分组，新的在前；默认一条都不勾（主按钮写“先勾选要导入的”）', () => {
  const items = K['memory:import:0'].items;
  const g = C.importGroups(items);
  assert.deepEqual(g.map((x) => x.label), ['Claude Code · demo-repo', 'Codex · demo-repo', 'Antigravity · demo-repo']);
  assert.deepEqual(items.filter(C.importChecked).map((i) => i.fingerprint), []);
  assert.match(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv', 'MemoryCenter.tsx'), 'utf8'), /先勾选要导入的/u);
  assert.ok(C.importMeta(items[1], pool()).includes('已在记忆里'));
  assert.ok(C.importMeta(items[2], pool()).includes('旧仓库'));
  assert.ok(C.importMeta(items[0], pool()).includes('建议记成规矩·全局'));
});

test('记录与待审核的说法：谁、做了什么、因为哪句话；待审核写来源和建议去处', () => {
  const [a, b] = K['memory:global'].log;
  assert.deepEqual(C.logLine(a), { who: '你', action: '采纳', title: '提交前先跑测试', because: 'T12 “提交之前先跑测试”' });
  assert.equal(C.logLine(b).because, '');
  for (const act of MEMORY_EDIT_ACTIONS_V43) assert.ok(C.ACTION_WORD[act], act);
  // Bridge 写进变更记录的全部动作都有中文词，记录页不露英文动词（你confirm）
  const bridge = ['add', 'edit', 'archive', 'restore', 'void', 'settle', 'supersede', 'kind', 'confirm', 'move', 'undo', 'accept', 'reject', 'keep_left', 'keep_right', 'keep_both'];
  const core = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'covey');
  for (const f of ['core/memstore.py', 'core/memory_review.py', 'app/web_memory.py', 'app/memory_tidy.py']) {
    let src = '';
    try { src = readFileSync(join(core, f), 'utf8'); } catch { continue; }
    for (const m of src.matchAll(/\baction="([a-z_]+)"/gu)) bridge.push(m[1]);
  }
  for (const act of new Set(bridge)) {
    assert.ok(C.ACTION_WORD[act], `动作 ${act} 缺中文词`);
    assert.doesNotMatch(C.ACTION_WORD[act], /^[a-z_]+$/u, act);
  }
  assert.equal(C.logLine({ at: 1, who: 'owner', action: 'confirm', refs: [], title: '同事机器' }).action, '确认了');
  const [learn, conflict] = K['memory:global'].review;
  assert.deepEqual(C.reviewMeta(learn, pool()), ['从你的话里学到', '建议记成规矩·全局', 'T12', '说过不止一次']);
  assert.deepEqual(C.reviewMeta(conflict, pool()).slice(0, 2), ['和已有的矛盾', '建议记成资料·全局']);
});

test('右栏精简：规矩和在办决定各至多 n 条，资料只给数', () => {
  const p = pool();
  const b = C.briefOf(p.entries, 6);
  assert.deepEqual(b.counts, { rules: 2, decisions: 1, notes: 2 });
  assert.equal(C.briefLine(b), '规矩 2 · 在办决定 1 · 资料 2');
  assert.equal(C.briefLine(C.briefOf([])), '');
  assert.equal(C.briefOf(p.entries, 1).rules.length, 1);
});

test('消费方：有 v43 专项条目就读决定记录（kind=decision），没有就照旧读 v37 的主人答', () => {
  const entries = K['memory:p:demo01'].entries;
  const topics = [{ key: 't001', number: 12 }];
  const d = P.projectDecisions([], entries, topics, 10);
  assert.equal(d.length, 1);
  assert.equal(d[0].question, '记忆中心先上线只读页');
  assert.match(d[0].answer, /^记忆中心第一版先只做查看和审核/u);
  assert.equal(d[0].number, 12);
  assert.equal(d[0].id, 'decision:demo01:d7f8a9');
  const old = [{ id: 'p1', kind: 'decision', source: 'owner_answer', text: '主人答：先做哪个→先做网页', at: 5, origin: { topic: 't001' } }];
  assert.deepEqual(P.projectDecisions(old, null, topics, 10).map((x) => [x.question, x.answer]), [['先做哪个', '先做网页']], 'v43 没有时走 v37');
  assert.deepEqual(P.projectDecisions(old, undefined, topics, 10).length, 1, '还没取到也先画 v37');
  assert.deepEqual(P.projectDecisions(old, [], topics, 10), [], '拿到了 v43 但是空的：不再读 v37');
  const arrow = [{ ...entries[0], key: 'decision:demo01:x', text: '主人答：用哪版→B 版（推荐）', status: 'done' }];
  assert.deepEqual(P.entryDecisions(arrow, topics).map((x) => [x.question, x.answer]), [['用哪版', 'B 版']]);
  assert.deepEqual(P.entryDecisions([{ ...entries[0], status: 'void' }], topics), [], '作废的不算');
  assert.deepEqual(P.entryDecisions([{ ...entries[0], kind: 'rule' }], topics), [], '只读决定');
});

test('页头数字：选了范围就写那个范围的数，全部范围写总数（CUA C3：切专项后页头与专项右栏一致）', () => {
  assert.deepEqual(C.headCounts(idx, 'all'), { rule: 1, decision: 1, note: 2 });
  assert.deepEqual(C.headCounts(idx, 'p:demo01'), { rule: 0, decision: 1, note: 0 });
  assert.deepEqual(C.headCounts(idx, 'global'), { rule: 1, decision: 0, note: 1 });
  assert.deepEqual(C.headCounts(idx, 'p:gone'), { rule: 1, decision: 1, note: 2 }, '没有这个范围时退回总数');
});

test('一轮下“带了 N 条记忆”：用到的和带入的两份清单不按下标配对，标题查 memory:index.titles，查不到只留短码', () => {
  const titles = [['R7K2', '提交前先跑测试', 'k1'], ['D3MX9', '部署走灰度', 'k2'], ['Q1W2', '旧仓库不要动', 'k3']];
  // 用到的是后半段那条：不能被配成 codes[0]
  const r = C.turnMemoryRows({ used: [{ code: 'D3MX9', title: '部署走灰度' }], codes: ['R7K2', 'D3MX9', 'Q1W2', 'ZZZZ'] }, titles);
  assert.deepEqual(r.used, [{ code: 'D3MX9', title: '部署走灰度' }]);
  assert.deepEqual(r.carried, [{ code: 'R7K2', title: '提交前先跑测试' }, { code: 'Q1W2', title: '旧仓库不要动' }, { code: 'ZZZZ', title: '' }]);
  // 旧 Bridge：used 只有标题（code 空），不渲染成链接，也不影响 codes 的列出；没有 titles 就只给短码
  const old = C.turnMemoryRows({ used: [{ code: '', title: '只有标题' }], codes: ['R7K2'] }, null);
  assert.deepEqual(old.used, [{ code: '', title: '只有标题' }]);
  assert.deepEqual(old.carried, [{ code: 'R7K2', title: '' }]);
  // used 空、codes 非空也有内容可展开
  assert.equal(C.turnMemoryRows({ used: [], codes: ['R7K2'] }, titles).carried.length, 1);
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv', 'AnswerFoot.tsx'), 'utf8');
  assert.match(src, /codes\.length > 0/u);
  assert.doesNotMatch(src, /mem\.codes\[i\]/u);
  assert.doesNotMatch(src, /\{mem\.used\.length \? \(\s*<button/u);
});

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src');
const mk = (over) => ({ key: 'r', type: 'migrate', title: '', text: '', suggest: { kind: 'rule', scope: 'project', project_key: 'demo01' }, created_at: 1, ...over });

test('待审核角标和默认页签不算迁移项：pending - (counts.migrate ?? 0)，旧 Bridge 没有这个字段就当 0', () => {
  assert.equal(C.todoPending({ pending: 90, migrate: 90 }), 0);
  assert.equal(C.todoPending({ pending: 93, migrate: 90 }), 3);
  assert.equal(C.todoPending({ pending: 5 }), 5);
  assert.equal(C.todoPending({ pending: 2, migrate: 9 }), 0);
  assert.equal(C.todoPending(undefined), 0);
  const c = (counts) => ({ counts: { rule: 0, decision: 0, note: 0, ...counts } });
  assert.equal(C.defaultTab(c({ pending: 90, migrate: 90 })), 'rules');
  assert.equal(C.defaultTab(c({ pending: 91, migrate: 90 })), 'review');
  assert.equal(C.defaultTab(c({ pending: 4 })), 'review');
  assert.equal(C.scopeOptions({ scopes: [], counts: { rule: 0, decision: 0, note: 0, pending: 90, migrate: 90 } })[0].pending, 0);
  assert.match(readFileSync(join(SRC, 'cv', 'Shell.tsx'), 'utf8'), /todoPending\(mem\.index\?\.counts\)/u);
});

test('待审核里的迁移项按专项折成组：组头一行，组里没有一键批量；标题是正文开头就不重复画', () => {
  const rows = [mk({ key: 'a', text: '长文 A' }), mk({ key: 'b', text: '长文 B' }), mk({ key: 'c', suggest: { kind: 'rule', scope: 'global' } }), mk({ key: 'd', type: 'learn' })];
  const { todo, groups } = C.reviewSplit(rows, { projects: { demo01: '推理服务快速部署' } });
  assert.deepEqual(todo.map((r) => r.key), ['d']);
  assert.deepEqual(groups.map((g) => [g.label, g.rows.length]), [['推理服务快速部署', 2], ['全局', 1]]);
  assert.equal(C.groupLine(groups[0]), '推理服务快速部署：2 条负责人约束在按规矩带');
  assert.equal(C.titleShown({ title: '提交前先跑测试', text: '提交前先跑测试，再推送' }), false);
  assert.equal(C.titleShown({ title: '提交前先跑测试…', text: '提交前先跑测试，再推送' }), false);
  assert.equal(C.titleShown({ title: '测试规矩', text: '提交前先跑测试' }), true);
  assert.equal(C.titleShown({ title: '只有标题', text: '' }), true);
  const src = readFileSync(join(SRC, 'cv', 'MemoryCenter.tsx'), 'utf8');
  const grp = src.slice(src.indexOf('const MigrateGroup'), src.indexOf('const ReviewTab'));
  assert.doesNotMatch(grp, /全部采纳|全部不要|allOp/u);
  assert.match(src, /allOp\(a, rows\)/u);
});

test('决定页：页头“决定 N”和分段“全部”同口径（都从条目算），“已办”改叫“不在办”；撤销失败有页面提示', () => {
  const entries = [
    { key: 'd1', code: 'D1', kind: 'decision', status: 'active', in_progress: true, title: 'a', text: 'a', scope: 'global' },
    { key: 'd2', code: 'D2', kind: 'decision', status: 'done', title: 'b', text: 'b', scope: 'global' },
    { key: 'd3', code: 'D3', kind: 'decision', status: 'active', in_progress: false, title: 'c', text: 'c', scope: 'global' },
    { key: 'd4', code: 'D4', kind: 'decision', status: 'archived', title: 'd', text: 'd', scope: 'global' },
  ];
  const p = { entries, review: [], log: [], projects: {}, topics: {} };
  const dc = C.decisionCounts(p, 'all');
  const index = { scopes: [], counts: { rule: 1, decision: 99, note: 2, pending: 0 } };
  assert.equal(C.headCounts(index, 'all', p).decision, dc.all);
  assert.equal(C.headCounts(index, 'all', p).decision, dc.open + dc.done);
  assert.equal(C.headCounts(index, 'all').decision, 99, '条目还没读到时先用 index 里的数');
  assert.equal(C.headCounts(index, 'all', { entries: [] }).decision, 99);
  const src = readFileSync(join(SRC, 'cv', 'MemoryCenter.tsx'), 'utf8');
  assert.match(src, /done: '不在办'/u);
  assert.doesNotMatch(src, /done: '已办'/u);
  assert.match(src, /headCounts\(index, scope, pool\)/u);
  assert.match(src, /id\.startsWith\('undo:'\)\) toast\.error/u);
});

test('首屏：非话题页（记忆中心、设置）晚 3 秒再预热话题，话题页和大厅马上开始', async () => {
  const W = await import('../client/src/cv/warmup.ts');
  assert.equal(W.warmupDelay('/'), 0);
  assert.equal(W.warmupDelay('/topics/abc'), 0);
  assert.equal(W.warmupDelay('/memory'), 3000);
  assert.equal(W.warmupDelay('/memory/review'), 3000);
  assert.equal(W.warmupDelay('/settings/memory'), 3000);
  assert.equal(W.warmupDelay('/memoryx'), 0);
  assert.match(readFileSync(join(SRC, 'cv', 'Shell.tsx'), 'utf8'), /useWarmup\(warmupDelay\(loc\.pathname\)\)/u);
  assert.match(readFileSync(join(SRC, 'hooks', 'use-workbench.ts'), 'utf8'), /delayMs \+ 150 \* i/u);
});

test('390px：范围下拉右侧留够放箭头的空，.mc-link 点按区不小于 40px', () => {
  const css = readFileSync(join(SRC, 'cv', 'memorycenter.css'), 'utf8');
  const phone = css.slice(css.indexOf('@media (max-width:640px)'));
  assert.match(phone, /\.cv \.mc-sel\{[^}]*padding-right:30px/u);
  assert.match(phone, /\.cv \.mc-link,\.cv \.mc-seg button\{min-height:40px;min-width:40px/u);
});
