// 自托管的纯逻辑：对照码、UA 解析、频控、cookie、令牌哈希、密钥比较（server/selfhost/auth.logic.ts、config.ts）
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, utimesSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  CODE_ALPHABET, CODE_LENGTH, LoginLimiter, agentLabel, bearerOk, buildCookie, clearCookie, isLoopback, loginStateOf,
  newLoginCode, newToken, parseCookies, parseUserAgent, safeEqual, sha256Hex,
} from '../server/selfhost/auth.logic.ts';
import { isApiPath, isLoginRoute, isOpenapiPath } from '../server/selfhost/guards.ts';
import { KeySource, databaseUrlOf, loadConfig } from '../server/selfhost/config.ts';

test('对照码：4 位，只用不易混淆的字符', () => {
  assert.equal(CODE_LENGTH, 4);
  for (const bad of '0O1ILZ5S8B2') assert.ok(!CODE_ALPHABET.includes(bad), bad);
  for (let i = 0; i < 500; i += 1) assert.match(newLoginCode(), /^[ACDEFGHJKMNPQRTUVWXY3467]{4}$/u);
  assert.equal(newLoginCode(() => 0), 'AAAA');
  assert.equal(new Set(Array.from({ length: 50 }, () => newLoginCode())).size > 40, true);
});

test('令牌：够长、不重复；库里存 sha256', () => {
  const a = newToken();
  assert.ok(a.length >= 43);
  assert.notEqual(a, newToken());
  assert.equal(sha256Hex('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});

test('UA 解析：浏览器和系统', () => {
  const mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';
  assert.equal(agentLabel(parseUserAgent(mac)), 'Chrome · macOS');
  const edge = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0';
  assert.deepEqual(parseUserAgent(edge), { browser: 'Edge', os: 'Windows' });
  const ff = 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0';
  assert.deepEqual(parseUserAgent(ff), { browser: 'Firefox', os: 'Linux' });
  const safari = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
  assert.deepEqual(parseUserAgent(safari), { browser: 'Safari', os: 'iOS' });
  const andr = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0.0.0 Mobile Safari/537.36';
  assert.deepEqual(parseUserAgent(andr), { browser: 'Chrome', os: 'Android' });
  assert.deepEqual(parseUserAgent(undefined), { browser: '未知浏览器', os: '未知系统' });
  assert.equal(parseUserAgent('curl/8.5.0').browser, 'curl');
  assert.ok(agentLabel(parseUserAgent('x'.repeat(5000))).length < 40);
});

test('频控：同一 IP 30 秒一次、全局待定最多 5 个，被拒的不顺延窗口', () => {
  const l = new LoginLimiter();
  assert.deepEqual(l.check('1.1.1.1', 0, 1000), { ok: true });
  l.record('1.1.1.1', 1000);
  const v = l.check('1.1.1.1', 0, 11000);
  assert.equal(v.ok, false);
  assert.equal(v.reason, 'ip');
  assert.equal(v.retryAfter, 20);
  assert.deepEqual(l.check('2.2.2.2', 0, 11000), { ok: true });
  assert.deepEqual(l.check('1.1.1.1', 0, 31000), { ok: true });
  const p = l.check('3.3.3.3', 5, 50000);
  assert.equal(p.ok, false);
  assert.equal(p.reason, 'pending');
  assert.ok(p.retryAfter >= 1);
  assert.deepEqual(l.check('3.3.3.3', 4, 50000), { ok: true });
});

test('cookie：HttpOnly、SameSite=Lax、https 才加 Secure，30 天', () => {
  const c = buildCookie('covey_session', 'a b/c', { maxAgeSec: 2592000 });
  assert.match(c, /^covey_session=a%20b%2Fc; Path=\/; HttpOnly; SameSite=Lax; Max-Age=2592000$/u);
  assert.ok(!c.includes('Secure'));
  assert.ok(buildCookie('x', 'y', { secure: true }).includes('; Secure'));
  assert.ok(clearCookie('x').includes('Max-Age=0'));
  assert.deepEqual(parseCookies('a=1; covey_session=a%20b; bad; =x; a=2'), { a: '1', covey_session: 'a b' });
  assert.deepEqual(parseCookies(undefined), {});
});

test('登录请求的状态：过期、拒绝、用过', () => {
  assert.equal(loginStateOf('pending', 2000, 1000), 'pending');
  assert.equal(loginStateOf('pending', 2000, 2000), 'expired');
  assert.equal(loginStateOf('approved', 2000, 1000), 'approved');
  assert.equal(loginStateOf('approved', 2000, 3000), 'expired');
  assert.equal(loginStateOf('denied', 2000, 3000), 'denied');
  assert.equal(loginStateOf('used', 2000, 3000), 'used');
});

test('密钥比较：定长、没配一律拒绝、Bearer 格式', () => {
  assert.equal(safeEqual('abc', 'abc'), true);
  assert.equal(safeEqual('abc', 'abd'), false);
  assert.equal(safeEqual('abc', 'abcd'), false);
  assert.equal(bearerOk('Bearer k1', 'k1'), true);
  assert.equal(bearerOk('bearer k1', 'k1'), true);
  assert.equal(bearerOk('Bearer k2', 'k1'), false);
  assert.equal(bearerOk('k1', 'k1'), false);
  assert.equal(bearerOk('Bearer ', 'k1'), false);
  assert.equal(bearerOk(undefined, 'k1'), false);
  assert.equal(bearerOk('Bearer ', ''), false);
  assert.equal(bearerOk('Bearer x', ''), false);
});

test('回环判断', () => {
  for (const a of ['127.0.0.1', '::1', '::ffff:127.0.0.1', '127.1.2.3']) assert.equal(isLoopback(a), true, a);
  for (const a of ['198.51.100.1', '203.0.113.2', '::ffff:198.51.100.1', '', undefined, '128.0.0.1']) assert.equal(isLoopback(a), false, String(a));
});

test('不需登录的只有发起和轮询登录', () => {
  assert.equal(isLoginRoute('POST', '/api/auth/login-requests'), true);
  assert.equal(isLoginRoute('GET', '/api/auth/login-requests/abc'), true);
  assert.equal(isLoginRoute('GET', '/api/auth/sessions'), false);
  assert.equal(isLoginRoute('POST', '/api/auth/logout'), false);
  assert.equal(isLoginRoute('POST', '/api/auth/login-requests/abc'), false);
  assert.equal(isLoginRoute('GET', '/api/me'), false);
});

test('路径前缀不分大小写：Express 的路由不分，守卫也不能分（/OPENAPI、/Api 换个写法不能绕过）', () => {
  for (const p of ['/openapi/sync/inbox', '/OPENAPI/sync/inbox', '/OpenApi/sync/upsert', '/openapi', '/OPENAPI/']) assert.equal(isOpenapiPath(p), true, p);
  for (const p of ['/openapix/sync', '/assets/openapi', '/']) assert.equal(isOpenapiPath(p), false, p);
  for (const p of ['/api/home', '/API/home', '/Api/topics/x', '/api', '/API/']) assert.equal(isApiPath(p), true, p);
  for (const p of ['/apix', '/app/api', '/']) assert.equal(isApiPath(p), false, p);
  assert.equal(isLoginRoute('POST', '/API/auth/login-requests'), true);
  assert.equal(isLoginRoute('GET', '/API/AUTH/sessions'), false);
});

test('KeySource：读文件、文件换了读到新的、文件没了当没配；环境变量兜底', () => {
  const dir = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'kf-'));
  try {
    const f = join(dir, 'key');
    writeFileSync(f, 'old-key\n');
    const ks = new KeySource({ COVEY_WEB_KEY_FILE: f });
    assert.equal(ks.current(), 'old-key');
    writeFileSync(f, 'new-key\n');
    utimesSync(f, new Date(Date.now() + 5000), new Date(Date.now() + 5000));
    assert.equal(ks.current(), 'new-key');
    rmSync(f);
    assert.equal(ks.current(), '');
    assert.equal(new KeySource({ COVEY_WEB_OPENAPI_KEY: ' envkey ' }).current(), 'envkey');
    assert.equal(new KeySource({}).current(), '');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('外部库：DATABASE_URL 优先，没设时读连接串文件（文件没有或为空就用进程内 PGlite）；默认只听 127.0.0.1', () => {
  const dir = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'db-'));
  try {
    const f = join(dir, 'database-url');
    assert.equal(databaseUrlOf({ COVEY_WEB_DATABASE_URL_FILE: f }), '');
    writeFileSync(f, ' postgres://u:p@127.0.0.1:5432/covey \n', { mode: 0o600 });
    assert.equal(databaseUrlOf({ COVEY_WEB_DATABASE_URL_FILE: f }), 'postgres://u:p@127.0.0.1:5432/covey');
    assert.equal(databaseUrlOf({ DATABASE_URL: 'postgres://direct/db', COVEY_WEB_DATABASE_URL_FILE: f }), 'postgres://direct/db');
    writeFileSync(f, '\n');
    assert.equal(databaseUrlOf({ COVEY_WEB_DATABASE_URL_FILE: f }), '');
    const cfg = loadConfig({});
    assert.equal(cfg.host, '127.0.0.1');
    assert.equal(cfg.port, 18650);
    assert.equal(cfg.databaseUrl, '');
    assert.equal(cfg.allowRemoteOpenapi, false);
    assert.equal(loadConfig({ COVEY_WEB_PORT: '70000' }).port, 18650);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
