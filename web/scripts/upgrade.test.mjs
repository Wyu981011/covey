// 数据约定 v39（covey docs/web.md）：版本与更新。Covey 推的设置条目 upgrade 怎么理、页面上每句话怎么写、按钮能不能点，
// 发件 upgrade 的校验。跑：npm run test:upgrade
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as U from '../client/src/cv/upgrade.ts';
import * as K from '../client/src/cv/opTrack.ts';
import * as S from '../server/modules/workbench/workbench.upgrade.ts';
import { OUTBOX_KINDS, SETTINGS_KEYS, isSettingsKey } from '../shared/api.interface.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const read = (name) => readFileSync(join(CV, name), 'utf8');
const NOW = Date.parse('2026-11-25T19:00:00+08:00') / 1000;

/** Covey 推来的一份（数据约定 v39 的例子） */
const pushed = (over = {}) => ({
  live: '606a55f9-dcd796d7',
  latest: '606a55f9-86030173',
  available: true,
  bridge: true,
  web: { kind: 'miaoda', current: false, manual: false },
  count: 12,
  changes: [{ repo: 'covey-internal', sha: '86030173e56ef701', subject: './install upgrade 顺带更新网页工作台 (T778)', at: NOW - 600 }],
  checked_at: NOW - 120,
  checking: false,
  error: '',
  blocked: '',
  running: null,
  last: null,
  ...over,
});
const view = (over) => S.upgradeOf(pushed(over));

test('新操作和新的设置条目网页认得：发件 upgrade，settings 的 upgrade', () => {
  assert.ok(OUTBOX_KINDS.includes('upgrade'));
  assert.ok(SETTINGS_KEYS.includes('upgrade'));
  assert.equal(isSettingsKey('upgrade'), true);
});

test('发件 upgrade：不带话题和专项，payload 只有 action，只能是 check 或 run', () => {
  assert.deepEqual(S.upgradeShape({ action: 'check' }, '', ''), { action: 'check' });
  assert.deepEqual(S.upgradeShape({ action: 'run' }, '', ''), { action: 'run' });
  assert.match(S.upgradeShape({ action: 'run' }, 'abc', '').error, /不带 topic_key/u);
  assert.match(S.upgradeShape({ action: 'run' }, '', 'p1').error, /不带 topic_key/u);
  assert.match(S.upgradeShape({ action: 'run', ref: 'HEAD' }, '', '').error, /只有 action/u);
  assert.match(S.upgradeShape({ action: 'rollback' }, '', '').error, /check 或 run/u);
  assert.match(S.upgradeShape({}, '', '').error, /check 或 run/u);
});

test('Covey 推来的条目理成页面要的形状：坏的字段当没有，不认得的提交丢掉', () => {
  assert.equal(S.upgradeOf(null), undefined);
  assert.equal(S.upgradeOf([]), undefined);
  assert.equal(S.upgradeOf({ available: true }), undefined); // 连现网 release 都没有：不画
  const d = view({ web: 'miaoda', running: 'yes', last: { message: '没有 state' }, checked_at: -5, count: 'many',
    changes: [{ repo: 'covey', sha: 'not-a-sha', subject: 'x' }, ...pushed().changes, 7] });
  assert.equal(d.web, null);
  assert.equal(d.running, null);
  assert.equal(d.last, null);
  assert.equal(d.checked_at, 0);
  assert.equal(d.changes.length, 1);
  assert.equal(d.changes[0].sha, '86030173e56e'); // 最多 12 位
  assert.equal(d.count, 1); // count 不对时至少是列出来的个数
  const many = view({ count: 30, changes: Array.from({ length: 30 }, (_, i) => ({ repo: 'covey', sha: `abcd${String(i).padStart(4, '0')}`, subject: `c${i}`, at: NOW })) });
  assert.equal(many.changes.length, S.UPGRADE_CHANGES);
  assert.equal(many.count, 30);
  const tail = Array.from({ length: 40 }, (_, i) => `line ${i}`);
  const done = view({ last: { state: 'partial', message: '网页没更新上', at: NOW - 60, log: '/absolute/x.log', tail: [...tail, 3] } });
  assert.equal(done.last.tail.length, S.UPGRADE_TAIL);
  assert.equal(done.last.tail.at(-1), 'line 39'); // 留最后几行
  assert.equal(done.last.log, '/absolute/x.log');
});

test('只在 Covey 认 upgrade、也推过条目时出现；旧 Covey 没有 ops，一律不画', () => {
  const r = { rev: '1', data: view(), at: '' };
  assert.equal(U.upgradeOn(undefined, r), false);
  assert.equal(U.upgradeOn(['say', 'memory_edit'], r), false);
  assert.equal(U.upgradeOn(['say', 'upgrade'], null), false);
  assert.equal(U.upgradeOn(['say', 'upgrade'], r), true);
});

test('设置旁的小标记：在升级写“更新中”，有新版本写“有新版本”，最新时不画', () => {
  assert.equal(U.upgradeMark(null), '');
  assert.equal(U.upgradeMark(view()), '有新版本');
  assert.equal(U.upgradeMark(view({ available: false })), '');
  assert.equal(U.upgradeMark(view({ running: { op_id: 'o', started_at: NOW, log: '' } })), '更新中');
});

test('顶上那一句和版本行', () => {
  assert.equal(U.upgradeHeadline(view()), '有 12 个更新');
  assert.equal(U.upgradeHeadline(view({ available: false })), '已经是最新');
  assert.equal(U.upgradeHeadline(view({ checked_at: 0, available: false })), '还没检查过更新');
  assert.equal(U.upgradeHeadline(view({ checking: true })), '正在检查更新…');
  assert.equal(U.upgradeHeadline(view({ count: 0, changes: [], bridge: false })), '网页有新版本'); // Bridge 已是新版、只差网页
  assert.equal(U.upgradeHeadline(view({ running: { op_id: 'o', started_at: NOW, log: '' } })), '正在更新');
  assert.equal(U.versionLine(view()), '现在 606a55f9-dcd796d7 → 最新 606a55f9-86030173');
  assert.equal(U.versionLine(view({ latest: '' })), '现在 606a55f9-dcd796d7');
  assert.equal(U.versionLine(view({ latest: '606a55f9-dcd796d7' })), '现在 606a55f9-dcd796d7');
});

test('「全部更新」能不能点：在升级、在查、被拦着、没有更新时都不能，并写原因', () => {
  assert.deepEqual(U.runState(view()), { ok: true, why: '' });
  assert.equal(U.runState(view({ running: { op_id: 'o', started_at: NOW, log: '' } })).ok, false);
  assert.equal(U.runState(view({ checking: true })).ok, false);
  assert.deepEqual(U.runState(view({ blocked: '检出里有没提交的改动' })), { ok: false, why: '检出里有没提交的改动' });
  assert.deepEqual(U.runState(view({ available: false })), { ok: false, why: '已经是最新' });
  assert.deepEqual(U.runState(view({ available: false, checked_at: 0 })), { ok: false, why: '先检查更新' });
  assert.equal(U.canCheck(view()), true);
  assert.equal(U.canCheck(view({ checking: true })), false);
  assert.equal(U.canCheck(view({ running: { op_id: 'o', started_at: NOW, log: '' } })), false);
});

test('点「全部更新」前问的那句：机器人会不会重启、网页会怎样，只说这次真会发生的', () => {
  assert.equal(U.confirmWords(view()), '机器人会重启几秒，在跑的任务不中断；网页会重新发布，要几分钟，之后刷新页面。');
  assert.equal(U.confirmWords(view({ web: { kind: 'selfhost', current: false, manual: false } })),
    '机器人会重启几秒，在跑的任务不中断；网页会重新构建，要几分钟，之后刷新页面。');
  assert.equal(U.confirmWords(view({ web: { kind: 'miaoda', current: true, manual: false } })), '机器人会重启几秒，在跑的任务不中断。');
  assert.equal(U.confirmWords(view({ web: { kind: 'miaoda', current: false, manual: true } })), '机器人会重启几秒，在跑的任务不中断。');
  assert.equal(U.confirmWords(view({ bridge: false })), '网页会重新发布，要几分钟，之后刷新页面。');
});

test('网页会不会跟着更新', () => {
  assert.match(U.webLine(view()), /重新发布到妙搭/u);
  assert.match(U.webLine(view({ web: { kind: 'selfhost', current: false, manual: false } })), /本机重新构建/u);
  assert.match(U.webLine(view({ web: { kind: 'miaoda', current: true, manual: false } })), /已经是新版/u);
  assert.match(U.webLine(view({ web: { kind: 'selfhost', current: false, manual: true } })), /不会跟着更新/u);
  assert.equal(U.webLine(view({ web: null })), '');
});

test('上次更新的结果：做完、只更新了机器人、没更新成；后两种标红', () => {
  assert.equal(U.lastLine(view(), NOW), null);
  const at = NOW - 600;
  assert.deepEqual(U.lastLine(view({ last: { state: 'done', message: '升级好了', at } }), NOW), { text: '上次更新好了（10 分钟前）：升级好了', bad: false });
  const part = U.lastLine(view({ last: { state: 'partial', message: '妙搭发布在等审批', at } }), NOW);
  assert.equal(part.bad, true);
  assert.match(part.text, /^上次只更新了机器人，网页没更新上（10 分钟前）：妙搭发布在等审批$/u);
  assert.equal(U.lastLine(view({ last: { state: 'failed', message: '', at: 0 } }), NOW).text, '上次没更新成');
  assert.equal(U.checkedLine(view(), NOW), '上次检查 2 分钟前');
  assert.equal(U.checkedLine(view({ checked_at: 0 }), NOW), '');
  assert.equal(U.moreChanges(view()), 11);
});

test('发出 upgrade 以后重取版本条目（Covey 回执前推了检查结果，开始升级后 running 随后到）', () => {
  assert.deepEqual(K.pullPlan({ kind: 'upgrade', payload: { action: 'check' } }), { all: [{ t: 'upgrade' }], follow: [{ t: 'upgrade' }] });
  assert.equal(K.pullId({ t: 'upgrade' }), 'upgrade');
});

test('页面接线：先问一句再更新，按钮走操作追踪；设置页和侧栏只在 Covey 认 upgrade 时取条目', () => {
  const panel = read('Upgrade.tsx');
  assert.match(panel, /确认更新/u);
  assert.match(panel, /kind: 'upgrade', payload: \{ action: 'run' \}/u);
  assert.match(panel, /kind: 'upgrade', payload: \{ action: 'check' \}/u);
  assert.match(panel, /useOutboxOp\('upgrade:run'\)/u);
  assert.match(panel, /onClick=\{\(\) => setAsking\(true\)\}/u); // 「全部更新」只打开确认，不直接发
  const settings = read('Settings.tsx');
  assert.match(settings, /canDo\(snap\?\.data\.ops, 'upgrade'\)/u);
  assert.match(settings, /useUpgrade\(upgradable\)/u);
  const shell = read('Shell.tsx');
  assert.match(shell, /canDo\(ops, 'upgrade'\)/u);
  assert.match(shell, /useUpgrade\(on\)/u);
});
