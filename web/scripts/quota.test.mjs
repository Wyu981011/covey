// 数据约定 v42（covey docs/web.md 账号与额度）：Covey 推的设置条目 quota 怎么理、表里每一格写什么和什么颜色、折起来的来源一行写什么、
// 侧栏胶囊什么时候出现，发件 quota_refresh 的校验。跑：npm run test:quota
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as Q from '../client/src/cv/quota.ts';
import * as K from '../client/src/cv/opTrack.ts';
import * as S from '../server/modules/workbench/workbench.quota.ts';
import { OUTBOX_KINDS, SETTINGS_KEYS, isSettingsKey } from '../shared/api.interface.ts';

const CV = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const read = (name) => readFileSync(join(CV, name), 'utf8');
// 2026-11-26 14:32（上海）
const NOW = Date.parse('2026-11-26T14:32:00+08:00') / 1000;
const at = (h, m = 0, days = 0) => Date.parse(`2026-11-26T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+08:00`) / 1000 + days * 86400;

const win = (kind, left, over = {}) => ({ kind, label: kind === '5h' ? '5 小时' : '周', left, resets_at: at(19, 5), checked_at: NOW - 60, ...over });
const pool = (windows, over = {}) => ({ key: '', label: '', active: false, state: 'ok', available_at: null, windows, ...over });
const acct = (name, pools, over = {}) => ({ name, state: 'ok', available_at: null, pools, ...over });
const source = (over = {}) => ({
  id: 'gw', kind: 'gateway', title: 'Claude 网关', collected_at: NOW - 30, ttl: 600, stale_after: 600, read_at: NOW - 30, failing: false,
  usable: 7, total: 8, next_available_at: null, low: false, dry: false, expand: false, relogin: [], accounts: [], ...over,
});

test('新操作和新的设置条目网页认得：发件 quota_refresh，settings 的 quota', () => {
  assert.ok(OUTBOX_KINDS.includes('quota_refresh'));
  assert.ok(SETTINGS_KEYS.includes('quota'));
  assert.equal(isSettingsKey('quota'), true);
});

test('发件 quota_refresh：不带话题和专项，payload 是空的', () => {
  assert.deepEqual(S.quotaRefreshShape({}, '', ''), { ok: true });
  assert.match(S.quotaRefreshShape({}, 't1', '').error, /不带 topic_key/u);
  assert.match(S.quotaRefreshShape({}, '', 'p1').error, /不带 topic_key/u);
  assert.match(S.quotaRefreshShape({ all: true }, '', '').error, /空的/u);
});

test('Covey 推来的条目理成页面要的形状：读不到是 null 不是 0，坏的字段当没有，只留 https 链接和像邮箱的登录', () => {
  assert.equal(S.quotaOf(null), undefined);
  assert.equal(S.quotaOf([]), undefined);
  assert.deepEqual(S.quotaOf({ sources: [] }).sources, []); // 没有来源也照给：页面据此收起这一页
  const d = S.quotaOf({
    at: NOW, read_at: NOW, relogin: [{ source: 'VPS', name: 'V2' }, { name: '' }, 5],
    refresh: { at: NOW - 100, busy: true, cooldown: 300 },
    sources: [
      { id: 'agy', kind: 'agy', title: 'agy', collected_at: NOW, ttl: 600, stale_after: 3600, accounts: [
        { name: '主号', login: 'main@example.com', state: 'ok', pools: [{ key: 'gemini', label: 'Gemini', active: true, state: 'ok', windows: [
          { kind: '5h', label: '5 小时', left: null }, { kind: '7d', left: 3 }, { kind: 'weird', left: 0.5 }, 7] }] },
        { name: '副号', login: 'not an email', state: 'nope', pools: [] }, { login: 'x@y.example.com' }] },
      { id: 'gw', kind: 'mystery', title: '', link: 'http://insecure.example.com', failing: 'yes', accounts: 'many' }, 'nope'],
  });
  assert.equal(d.sources.length, 2);
  const [agy, gw] = d.sources;
  assert.equal(agy.accounts.length, 2); // 没有名字的号丢掉
  const [main, spare] = agy.accounts;
  assert.equal(main.login, 'main@example.com');
  assert.equal(spare.login, undefined); // 不像邮箱的不留
  assert.equal(spare.state, 'unknown');
  assert.deepEqual(main.pools[0].windows.map((w) => [w.kind, w.left]), [['5h', null], ['7d', 1], ['other', 0.5]]);
  assert.equal(main.pools[0].active, true);
  assert.equal(gw.kind, 'command');
  assert.equal(gw.title, 'gw');
  assert.equal(gw.link, undefined);
  assert.equal(gw.failing, false);
  assert.deepEqual(gw.accounts, []);
  assert.deepEqual(d.relogin, [{ source: 'VPS', name: 'V2' }]);
  assert.deepEqual(d.refresh, { at: NOW - 100, busy: true, cooldown: 300 });
  assert.equal(S.quotaOf({ sources: [{ id: 'x', link: 'https://ops.example.com/a' }] }).sources[0].link, 'https://ops.example.com/a');
  const many = S.quotaOf({ sources: Array.from({ length: 30 }, (_, i) => ({ id: `s${i}` })) });
  assert.equal(many.sources.length, S.QUOTA_MAX.sources);
});

test('时刻怎么写：今天写几点几分，别的天写周几', () => {
  assert.equal(Q.whenWords(at(19, 5), NOW), '19:05');
  assert.equal(Q.whenWords(at(9, 0, 1), NOW), '周五'); // 2026-11-27 是周五
  assert.equal(Q.whenWords(at(9, 0, 3), NOW), '周日');
  assert.equal(Q.whenWords(at(9, 0, 20), NOW), '12-16');
  assert.equal(Q.whenWords(0, NOW), '');
  assert.equal(Q.agoWords(NOW - 6 * 3600, NOW), '6 小时前');
  assert.equal(Q.agoWords(NOW - 20, NOW), '刚刚');
});

test('一格：百分比、细条、时刻；剩余不到 20% 红；用完写“用完”和“HH:MM 恢复”；读不到写“—”', () => {
  const s = source();
  const ok = Q.cellOf(s, pool([win('5h', 0.64, { resets_at: at(19, 5) })]), '5h', NOW);
  assert.deepEqual([ok.kind, ok.pct, ok.at, ok.tight, ok.stale], ['bar', 64, '19:05', false, false]);
  const week = Q.cellOf(s, pool([win('7d', 0.71, { resets_at: at(9, 0, 1) })]), '7d', NOW);
  assert.equal(week.at, '周五');
  const tight = Q.cellOf(s, pool([win('5h', 0.12)]), '5h', NOW);
  assert.deepEqual([tight.kind, tight.pct, tight.tight], ['bar', 12, true]);
  assert.equal(Q.cellOf(s, pool([win('5h', 0.2)]), '5h', NOW).tight, false); // 正好 20% 不红
  const out = Q.cellOf(s, pool([win('5h', 0, { resets_at: at(17, 10) })], { state: 'spent', available_at: at(17, 10) }), '5h', NOW);
  assert.deepEqual([out.kind, out.pct, out.at, out.tight], ['out', 0, '17:10 恢复', false]);
  const none = Q.cellOf(s, pool([win('5h', null)]), '5h', NOW);
  assert.deepEqual([none.kind, none.pct, none.at], ['none', null, '']); // 读不到：不画条、不写 0
  assert.equal(Q.cellOf(s, pool([]), '7d', NOW).kind, 'none');
  assert.equal(Q.cellOf(s, pool([win('5h', 1)], { state: 'ok' }), '7d', NOW).kind, 'none'); // 没有这个窗口
});

test('号 state 是用完而读数里没有哪个窗口为 0：写在 5 小时那一列；读数里为 0 的窗口写在它那一列', () => {
  const s = source();
  const spent = pool([], { state: 'spent', available_at: at(17, 10) });
  assert.equal(Q.cellOf(s, spent, '5h', NOW).at, '17:10 恢复');
  assert.equal(Q.cellOf(s, spent, '7d', NOW).kind, 'none');
  const weekOut = pool([win('5h', 0.6), win('7d', 0, { resets_at: at(9, 0, 2) })], { state: 'spent', available_at: at(9, 0, 2) });
  assert.equal(Q.cellOf(s, weekOut, '5h', NOW).kind, 'bar');
  assert.equal(Q.cellOf(s, weekOut, '7d', NOW).at, '周六 恢复');
});

test('旧读数数字灰、悬停说多旧；已重置还没有新读数写“—”；太旧的来源整份写“—”；读取没成功的灰', () => {
  const agy = source({ kind: 'agy', stale_after: 3600 });
  const old = Q.cellOf(agy, pool([win('7d', 0.93, { checked_at: NOW - 6 * 3600, resets_at: at(9, 0, 2) })]), '7d', NOW);
  assert.deepEqual([old.kind, old.stale, old.title], ['bar', true, '6 小时前的读数']);
  assert.equal(Q.cellOf(agy, pool([win('5h', 1, { checked_at: NOW - 600 })]), '5h', NOW).stale, false); // 10 分钟前不算旧
  const reset = Q.cellOf(agy, pool([win('5h', 0.3, { checked_at: at(10), resets_at: at(13) })]), '5h', NOW);
  assert.deepEqual([reset.kind, reset.title], ['none', '已重置，还没有新读数']);
  const stale = source({ collected_at: NOW - 3000, ttl: 600 });
  assert.equal(Q.cellOf(stale, pool([win('5h', 0.5, { checked_at: NOW - 3000 })]), '5h', NOW).kind, 'none'); // 超过两倍 ttl
  const failing = source({ failing: true });
  assert.equal(Q.cellOf(failing, pool([win('5h', 0.5)]), '5h', NOW).stale, true);
});

test('同一种窗口有几个取剩得最少的', () => {
  const p = pool([win('7d', 0.9), win('7d', 0.3, { label: 'Fable 周' }), win('5h', 0.5)]);
  assert.equal(Q.pickWindow(p, '7d').left, 0.3);
  assert.equal(Q.pickWindow(pool([win('7d', null), win('7d', 0.4)]), '7d').left, 0.4);
  assert.equal(Q.pickWindow(pool([]), '5h'), null);
});

test('号的名字：登录邮箱完整写出来，读不到才用名字；要重新登录、暂停、到期是整行的话', () => {
  assert.equal(Q.nameOf(acct('主号', [], { login: 'main@example.com' })), 'main@example.com');
  assert.equal(Q.nameOf(acct('主号', [])), '主号');
  assert.equal(Q.rowNote(acct('V2', [], { state: 'login_required' })), '要重新登录');
  assert.equal(Q.rowNote(acct('V2', [], { state: 'paused' })), '已暂停');
  assert.equal(Q.rowNote(acct('V2', [], { state: 'expired' })), '已到期');
  assert.equal(Q.rowNote(acct('V2', [pool([win('5h', 0.5)])])), '');
  assert.equal(Q.accountActive(acct('a', [pool([], { key: 'gemini', active: true })])), true);
  assert.equal(Q.accountActive(acct('a', [pool([], { key: 'gemini', active: true }), pool([], { key: '3p' })])), false); // 两个池：蓝点在池名前
});

test('折起来的来源：各列取平均，k/n 个能用，有冷却或低额度的号时一个红点；展开的别的来源写“N 个号”，agy 写“用完自动顺延”', () => {
  const accounts = [
    acct('A1', [pool([win('5h', 0.78), win('7d', 0.9)])]),
    acct('A2', [pool([win('5h', 0.22), win('7d', 0.5)])]),
    acct('A3', [pool([win('5h', null), win('7d', 0.1)])]),
    acct('A4', [pool([], { state: 'cooling', available_at: at(15) })], { state: 'cooling' }),
    acct('A5', [], { state: 'login_required' }),
  ];
  const s = source({ accounts });
  const five = Q.avgCell(s, '5h', NOW);
  assert.deepEqual([five.kind, five.pct, five.at], ['bar', 33, '平均']); // (78 + 22 + 0 用完) / 3：读不到的、要重新登录的不算
  assert.equal(Q.avgCell(s, '7d', NOW).pct, 50);
  assert.equal(Q.avgCell(source({ accounts: [] }), '5h', NOW).kind, 'none');
  assert.equal(Q.sourceWarn(s, NOW), true);
  assert.equal(Q.sourceWarn(source({ accounts: [acct('A1', [pool([win('5h', 0.78), win('7d', 0.9)])])] }), NOW), false);
  assert.equal(Q.groupNote(s, false), '7/8 个能用');
  assert.equal(Q.groupNote(s, true), '7/8 个能用'); // 网关展开了也写几个能用
  assert.equal(Q.groupNote(source({ kind: 'command', accounts }), true), '5 个号');
  assert.equal(Q.groupNote(source({ kind: 'agy', accounts: [acct('a', []), acct('b', [])] }), true), '2 个号 · 用完自动顺延');
  assert.equal(Q.isOpen(source({ expand: true }), undefined), true);
  assert.equal(Q.isOpen(source({ expand: true }), false), false); // 点过的听点的
  assert.equal(Q.isOpen(source(), undefined), false);
});

test('侧栏胶囊：只在某个来源整体见底或有号要重新登录时出现，否则空串；设置页签只在认 quota_refresh 且有来源时出现', () => {
  const fine = { at: NOW, read_at: NOW, relogin: [], sources: [source()], refresh: { at: 0, busy: false, cooldown: 300 } };
  assert.equal(Q.capsuleOf(fine), '');
  assert.equal(Q.capsuleOf(null), '');
  const dry = { ...fine, sources: [source({ title: 'agy', low: true, dry: true, next_available_at: at(17, 10) })] };
  assert.equal(Q.capsuleOf(dry), 'agy 额度见底 · 17:10 恢复');
  assert.equal(Q.capsuleOf({ ...fine, sources: [source({ title: 'agy', low: true })] }), 'agy 额度见底'); // 能用的号只是剩得少：没有恢复时刻
  const login = { ...fine, relogin: [{ source: '我的 VPS', name: 'V2' }, { source: '我的 VPS', name: 'V3' }, { source: 'agy', name: 'a@b.example.com' }] };
  assert.equal(Q.capsuleOf(login), '我的 VPS 有 2 个号要重新登录');
  assert.equal(Q.capsuleOf({ ...login, sources: [source({ low: true, title: 'X' })] }), 'X 额度见底'); // 两样都有：先说见底
  assert.equal(Q.reloginLine(login), '我的 VPS · V2 要重新登录；我的 VPS · V3 要重新登录；agy · a@b.example.com 要重新登录');
  const r = { rev: '1', data: fine, at: '' };
  assert.equal(Q.quotaOn(undefined, r), false); // 旧 Covey 没有 ops
  assert.equal(Q.quotaOn(['say', 'upgrade'], r), false);
  assert.equal(Q.quotaOn(['say', 'quota_refresh'], null), false);
  assert.equal(Q.quotaOn(['say', 'quota_refresh'], { ...r, data: { ...fine, sources: [] } }), false); // 来源都没了：收起
  assert.equal(Q.quotaOn(['say', 'quota_refresh'], r), true);
  assert.equal(Q.readWords(fine), '14:32');
  assert.equal(Q.readWords({ ...fine, read_at: 0 }), '');
});

test('发出 quota_refresh 以后重取条目（Covey 回执前推了“正在读取”，读完新的快照随后到）', () => {
  assert.deepEqual(K.pullPlan({ kind: 'quota_refresh', payload: {} }), { all: [{ t: 'quota' }], follow: [{ t: 'quota' }] });
  assert.equal(K.pullId({ t: 'quota' }), 'quota');
});

test('页面接线：只有一个「刷新」按钮，没有暂停、只用这个号、查全部账号；设置页和侧栏只在 Covey 认 quota_refresh 时取条目', () => {
  const panel = read('Quota.tsx');
  assert.match(panel, /kind: 'quota_refresh', payload: \{\}/u);
  assert.match(panel, /useOutboxOp\('quota:refresh'\)/u);
  assert.match(panel, /disabled=\{busy\}/u);
  for (const word of ['暂停', '只用这个号', '查全部账号', '运维台↗']) {
    assert.equal(panel.includes(word), word === '运维台↗', word);
  }
  assert.equal((panel.match(/<button/gu) ?? []).length, 1);
  assert.match(panel, /rel="noopener noreferrer"/u); // 运维台链接
  const settings = read('Settings.tsx');
  assert.match(settings, /canDo\(snap\?\.data\.ops, 'quota_refresh'\)/u);
  assert.match(settings, /useQuota\(quotable\)/u);
  const shell = read('Shell.tsx');
  assert.match(shell, /canDo\(ops, 'quota_refresh'\)/u);
  assert.match(shell, /useQuota\(on\)/u);
  assert.match(shell, /to="\/settings\/quota"/u);
});
