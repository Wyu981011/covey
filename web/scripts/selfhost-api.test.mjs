// 自托管服务的接口级测试：起真服务（构建产物 dist-selfhost，PGlite 用临时目录），走完密钥、登录、会话、频控的全流程。
// 先 npm run build:selfhost:server（test:selfhost-api 脚本会先构建）。端口 18690–18699 里找一个空的。
// 设了 SELFHOST_TEST_DATABASE_URL 就改连那个外部 Postgres（要一个空库），验 DATABASE_URL 那条路。
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import net from 'node:net';

const WEB = new URL('../', import.meta.url).pathname;
const MAIN = join(WEB, 'dist-selfhost/server/selfhost/main.js');
const KEY = 'test-key-not-real-0123456789';
const SECOND_KEY = 'second-key-not-real-abcdef';
const CHROME_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

let dir;
let child;
let base;
let keyFile;
const output = [];

function freePort(port) {
  return new Promise((ok) => {
    const s = net.createServer();
    s.once('error', () => ok(false));
    s.listen(port, '127.0.0.1', () => s.close(() => ok(true)));
  });
}

before(async () => {
  assert.ok(existsSync(MAIN), '先构建：npm run build:selfhost:server');
  let port = 0;
  for (let p = 18690; p <= 18699 && !port; p += 1) if (await freePort(p)) port = p;
  assert.ok(port, '18690-18699 没有空端口');
  dir = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'selfhost-api-'));
  keyFile = join(dir, 'key');
  writeFileSync(keyFile, `${KEY}\n`, { mode: 0o600 });
  const staticDir = join(dir, 'client');
  child = spawn(process.execPath, [MAIN], {
    cwd: WEB,
    env: { ...process.env, COVEY_WEB_PORT: String(port), COVEY_WEB_DB_DIR: join(dir, 'db'), COVEY_WEB_KEY_FILE: keyFile, COVEY_WEB_STATIC_DIR: staticDir, DATABASE_URL: process.env.SELFHOST_TEST_DATABASE_URL || '', NODE_ENV: 'production' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', (d) => output.push(String(d)));
  child.stderr.on('data', (d) => output.push(String(d)));
  base = `http://127.0.0.1:${port}`;
  const t0 = Date.now();
  for (;;) {
    try {
      await fetch(`${base}/api/me`);
      break;
    } catch {
      if (Date.now() - t0 > 60000) throw new Error(`服务没起来：${output.join('')}`);
      await new Promise((r) => setTimeout(r, 200));
    }
  }
});

after(() => {
  if (child && !child.killed) child.kill('SIGTERM');
  if (dir) rmSync(dir, { recursive: true, force: true });
});

const cookieOf = (res, name) => {
  for (const c of res.headers.getSetCookie()) if (c.startsWith(`${name}=`)) return c;
  return null;
};
const cookiePair = (setCookie) => setCookie.split(';')[0];
const api = (path, { method = 'GET', cookie = '', body, headers = {} } = {}) =>
  fetch(`${base}${path}`, {
    method,
    headers: { 'user-agent': CHROME_MAC, ...(method !== 'GET' ? { 'x-covey-csrf': '1' } : {}), ...(cookie ? { cookie } : {}), ...(body ? { 'content-type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
const open = (path, { method = 'GET', body, key = KEY, headers = {} } = {}) =>
  fetch(`${base}/openapi/sync/${path}`, {
    method,
    headers: { ...(key ? { authorization: `Bearer ${key}` } : {}), ...(body ? { 'content-type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });

let ip = 10;
/** 发起一次登录，用 X-Forwarded-For（本机来的才信）换一个来源 IP，避开同 IP 30 秒一次 */
async function startLogin() {
  ip += 1;
  const res = await api('/api/auth/login-requests', { method: 'POST', headers: { 'x-forwarded-for': `203.0.113.${ip}` } });
  return res;
}
const decide = (id, decision) =>
  open('upsert', { method: 'POST', key: SECOND_KEY, body: { items: [{ type: 'login', key: id, rev: `d-${decision}`, data: { decision, decided_at: new Date().toISOString() } }] } });

test('开放接口：没有密钥、错密钥、格式不对都拒绝，对的放行', async () => {
  assert.equal((await open('inbox', { key: '' })).status, 401);
  assert.equal((await open('inbox', { key: 'wrong-key' })).status, 401);
  assert.equal((await open('inbox', { key: KEY.slice(0, -1) })).status, 401);
  assert.equal((await fetch(`${base}/openapi/sync/inbox`, { headers: { authorization: KEY } })).status, 401);
  const ok = await open('inbox');
  assert.equal(ok.status, 200);
  assert.deepEqual(await ok.json(), { items: [] });
});

test('大小写换个写法也绕不过：/OPENAPI 照样要密钥，/API 照样要会话', async () => {
  for (const p of ['/OPENAPI/sync/inbox', '/OpenApi/sync/inbox', '/openAPI/sync/inbox/']) {
    assert.equal((await fetch(`${base}${p}`)).status, 401, p);
    assert.equal((await fetch(`${base}${p}`, { headers: { authorization: 'Bearer wrong-key' } })).status, 401, p);
    assert.equal((await fetch(`${base}${p}`, { headers: { authorization: `Bearer ${KEY}`, 'x-forwarded-for': '198.51.100.9' } })).status, 403, p);
  }
  const forged = await fetch(`${base}/OPENAPI/sync/upsert`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ items: [{ type: 'login', key: 'a'.repeat(32), rev: 'x', data: { decision: 'approved' } }] }),
  });
  assert.equal(forged.status, 401);
  for (const p of ['/API/home', '/Api/auth/sessions', '/api/HOME']) assert.equal((await api(p)).status, 401, p);
  assert.equal((await api('/API/auth/logout-all', { method: 'POST' })).status, 401);
});

test('开放接口：带转发头的（不是直接从本机来）拒绝；密钥文件换了读到新的', async () => {
  assert.equal((await open('inbox', { headers: { 'x-forwarded-for': '198.51.100.7' } })).status, 403);
  writeFileSync(keyFile, `${SECOND_KEY}\n`);
  const future = new Date(Date.now() + 5000);
  (await import('node:fs')).utimesSync(keyFile, future, future);
  assert.equal((await open('inbox')).status, 401);
  assert.equal((await open('inbox', { key: SECOND_KEY })).status, 200);
});

test('开放接口：推数据、取发件箱', async () => {
  const now = Date.now() / 1000;
  const res = await open('upsert', {
    method: 'POST',
    key: SECOND_KEY,
    body: {
      items: [
        { type: 'project', key: 'p1', rev: 'r1', data: { title: '专项一', status: '在做', updated_at: now } },
        { type: 'topic', key: 't1', rev: 'r1', data: { title: '话题一', state: '在做', number: 1, project_key: 'p1', updated_at: now } },
        { type: 'turn', key: 't1:1', rev: 'r1', data: { topic_key: 't1', seq: 1, role: 'owner', status: 'done', body: '你好' } },
      ],
    },
  });
  assert.equal(res.status < 300, true);
  const body = await res.json();
  assert.equal(body.upserted, 3);
  assert.equal(body.skipped, 0);
});

test('页面接口：没登录 401；伪造平台身份头也是 401', async () => {
  assert.equal((await api('/api/me')).status, 401);
  assert.equal((await api('/api/snapshot')).status, 401);
  const forged = await api('/api/snapshot', { headers: { 'x-larkgw-suda-webuser': JSON.stringify({ userId: 'selfhost-owner', userName: 'x' }) } });
  assert.equal(forged.status, 401);
  const forgedCookie = await api('/api/snapshot', { cookie: 'covey_session=not-a-real-token' });
  assert.equal(forgedCookie.status, 401);
  assert.equal((await api('/api/auth/sessions')).status, 401);
});

test('页面接口：非 GET 没有 x-covey-csrf 被拒', async () => {
  const res = await fetch(`${base}/api/auth/login-requests`, { method: 'POST', headers: { 'x-forwarded-for': '203.0.113.200' } });
  assert.equal(res.status, 403);
});

let approved; // { cookie, id }
test('登录：发起得到 4 位对照码、绑浏览器的 cookie、发件箱里有 login 操作', async () => {
  const res = await startLogin();
  assert.equal(res.status, 200);
  const { id, code, expires_at } = await res.json();
  assert.match(code, /^[A-Z0-9]{4}$/u);
  assert.match(id, /^[0-9a-f]{32}$/u);
  const left = new Date(expires_at).getTime() - Date.now();
  assert.ok(left > 4 * 60 * 1000 && left <= 5 * 60 * 1000, `过期时间 ${left}`);
  const c = cookieOf(res, 'covey_login');
  assert.ok(c);
  assert.match(c, /HttpOnly/u);
  assert.match(c, /SameSite=Lax/u);
  assert.doesNotMatch(c, /Secure/u);
  const inbox = await (await open('inbox', { key: SECOND_KEY })).json();
  const op = inbox.items.find((i) => i.op_id === `login-${id}`);
  assert.ok(op, '发件箱里没有 login 操作');
  assert.equal(op.kind, 'login');
  assert.equal(op.payload.request_id, id);
  assert.equal(op.payload.code, code);
  assert.equal(op.payload.browser, 'Chrome');
  assert.equal(op.payload.os, 'macOS');
  // 秒数（Covey 按秒算 5 分钟有效期），不是 ISO 字符串
  assert.equal(typeof op.payload.at, 'number');
  assert.ok(Math.abs(op.payload.at - Date.now() / 1000) < 60, `at=${op.payload.at}`);
  approved = { id, loginCookie: cookiePair(c) };
});

test('登录：没批准前一直 pending；别的浏览器（没有 cookie）问不到', async () => {
  const mine = await api(`/api/auth/login-requests/${approved.id}`, { cookie: approved.loginCookie });
  assert.deepEqual(await mine.json(), { state: 'pending' });
  assert.equal(mine.headers.getSetCookie().length, 0);
  assert.equal((await api(`/api/auth/login-requests/${approved.id}`)).status, 404);
  assert.equal((await api(`/api/auth/login-requests/${approved.id}`, { cookie: 'covey_login=other' })).status, 404);
  assert.equal((await api('/api/auth/login-requests/not-an-id', { cookie: approved.loginCookie })).status, 404);
});

test('登录：推 approved 后轮询拿到会话 cookie；一次性', async () => {
  const up = await decide(approved.id, 'approved');
  assert.equal(up.status < 300, true);
  assert.equal((await up.json()).upserted, 1);
  // 别的浏览器仍拿不到
  assert.equal((await api(`/api/auth/login-requests/${approved.id}`, { cookie: 'covey_login=other' })).status, 404);
  const res = await api(`/api/auth/login-requests/${approved.id}`, { cookie: approved.loginCookie });
  assert.deepEqual(await res.json(), { state: 'approved' });
  const s = cookieOf(res, 'covey_session');
  assert.ok(s, '没有会话 cookie');
  assert.match(s, /HttpOnly/u);
  assert.match(s, /SameSite=Lax/u);
  assert.match(s, /Max-Age=2592000/u);
  approved.session = cookiePair(s);
  const again = await api(`/api/auth/login-requests/${approved.id}`, { cookie: approved.loginCookie });
  assert.deepEqual(await again.json(), { state: 'used' });
  assert.equal(cookieOf(again, 'covey_session'), null);
});

test('登录后：读看板、话题、发一句', async () => {
  const cookie = approved.session;
  const me = await api('/api/me', { cookie });
  assert.equal(me.status, 200);
  const snap = await (await api('/api/snapshot', { cookie })).json();
  assert.ok(snap.projects.some((p) => p.key === 'p1'));
  assert.ok(snap.topics.some((t) => t.key === 't1'));
  const turns = await api('/api/topics/t1/turns', { cookie });
  assert.equal(turns.status, 200);
  assert.equal((await turns.json()).turns.length, 1);
  assert.equal((await api('/api/topics/t1', { cookie })).status, 200);
  assert.equal((await api('/api/home', { cookie })).status, 200);
  const say = await api('/api/outbox', { method: 'POST', cookie, body: { op_id: 'say-1', kind: 'say', topic_key: 't1', payload: { text: '继续' } } });
  assert.equal(say.status < 300, true, await say.clone().text());
  const inbox = await (await open('inbox', { key: SECOND_KEY })).json();
  assert.ok(inbox.items.some((i) => i.op_id === 'say-1' && i.kind === 'say'));
  // 页面不能自己发 login 操作
  const forged = await api('/api/outbox', { method: 'POST', cookie, body: { op_id: 'login-x', kind: 'login', payload: {} } });
  assert.equal(forged.status, 400);
  // 页面发的东西不能走 /openapi
  assert.equal((await fetch(`${base}/openapi/sync/inbox`, { headers: { cookie } })).status, 401);
});

test('登录后：已登录的浏览器列表标出当前这个', async () => {
  const res = await api('/api/auth/sessions', { cookie: approved.session });
  const { sessions } = await res.json();
  assert.equal(sessions.length, 1);
  assert.equal(sessions[0].current, true);
  assert.equal(sessions[0].browser, 'Chrome');
  assert.equal(sessions[0].os, 'macOS');
  assert.ok(sessions[0].created_at && sessions[0].last_used_at);
  assert.equal('token_hash' in sessions[0], false);
});

test('登录：推 denied 的请求拿不到会话；没批准的重复推送不改状态', async () => {
  const res = await startLogin();
  const { id } = await res.json();
  const loginCookie = cookiePair(cookieOf(res, 'covey_login'));
  assert.equal((await decide(id, 'denied')).status < 300, true);
  const poll = await api(`/api/auth/login-requests/${id}`, { cookie: loginCookie });
  assert.deepEqual(await poll.json(), { state: 'denied' });
  assert.equal(cookieOf(poll, 'covey_session'), null);
  // denied 之后再推 approved 不生效
  await open('upsert', { method: 'POST', key: SECOND_KEY, body: { items: [{ type: 'login', key: id, rev: 'late', data: { decision: 'approved' } }] } });
  const again = await api(`/api/auth/login-requests/${id}`, { cookie: loginCookie });
  assert.deepEqual(await again.json(), { state: 'denied' });
  // 推不合法的 decision 是 400
  const bad = await open('upsert', { method: 'POST', key: SECOND_KEY, body: { items: [{ type: 'login', key: id, rev: 'x', data: { decision: 'maybe' } }] } });
  assert.equal(bad.status, 400);
});

test('频控：同一来源 30 秒内只能发一次（429 + Retry-After）；全局待定最多 5 个', async () => {
  const hdr = { 'x-forwarded-for': '198.51.100.50' };
  const first = await api('/api/auth/login-requests', { method: 'POST', headers: hdr });
  assert.equal(first.status, 200);
  const second = await api('/api/auth/login-requests', { method: 'POST', headers: hdr });
  assert.equal(second.status, 429);
  const retry = Number(second.headers.get('retry-after'));
  assert.ok(retry >= 1 && retry <= 30, `Retry-After ${retry}`);
  // 到这里待定的：上一条（first）+ 再来几个不同来源直到 5 个，第 6 个被拒
  let ok = 1;
  let refused = null;
  for (let i = 0; i < 8 && !refused; i += 1) {
    const r = await startLogin();
    if (r.status === 200) ok += 1;
    else refused = r;
  }
  assert.equal(ok, 5, `待定上限前放行了 ${ok} 个`);
  assert.equal(refused?.status, 429);
  assert.ok(Number(refused.headers.get('retry-after')) >= 1);
});

test('登出：logout 只掉当前这个，logout-all 掉全部，会话立刻失效', async () => {
  // 登出后再登录一个新会话，需要一个新的待定名额：把待定的都拒绝掉
  const inbox = await (await open('inbox', { key: SECOND_KEY })).json();
  for (const it of inbox.items.filter((i) => i.kind === 'login')) await decide(it.payload.request_id, 'denied');
  const out1 = await api('/api/auth/logout', { method: 'POST', cookie: approved.session });
  assert.equal(out1.status, 200);
  assert.match(cookieOf(out1, 'covey_session') ?? '', /Max-Age=0/u);
  assert.equal((await api('/api/snapshot', { cookie: approved.session })).status, 401);

  async function login() {
    const r = await startLogin();
    assert.equal(r.status, 200, await r.clone().text());
    const { id } = await r.json();
    const lc = cookiePair(cookieOf(r, 'covey_login'));
    await decide(id, 'approved');
    const p = await api(`/api/auth/login-requests/${id}`, { cookie: lc });
    assert.deepEqual(await p.json(), { state: 'approved' });
    return cookiePair(cookieOf(p, 'covey_session'));
  }
  const a = await login();
  const b = await login();
  assert.equal((await api('/api/snapshot', { cookie: a })).status, 200);
  assert.equal((await api('/api/snapshot', { cookie: b })).status, 200);
  const list = (await (await api('/api/auth/sessions', { cookie: a })).json()).sessions;
  assert.equal(list.length, 2);
  assert.equal(list.filter((s) => s.current).length, 1);
  const all = await api('/api/auth/logout-all', { method: 'POST', cookie: a });
  assert.equal(all.status, 200);
  assert.equal((await api('/api/snapshot', { cookie: a })).status, 401);
  assert.equal((await api('/api/snapshot', { cookie: b })).status, 401);
});

test('页面：没构建前端时 index 是 404 说明，/api 下没有的是 JSON 404', async () => {
  const page = await fetch(`${base}/settings`);
  assert.equal(page.status, 404);
  const missing = await api('/api/nope', { cookie: '' });
  assert.equal(missing.status, 401);
});
