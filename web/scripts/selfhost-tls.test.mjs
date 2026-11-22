// 公网 HTTPS 的证书：生成、SAN、重建条件、权限、指纹、自己的证书、tls-cli（server/selfhost/tls.ts、tls-cli.ts）
// 命令行那条要先构建：npm run build:selfhost:server（test:selfhost-tls 脚本会先构建）。
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { X509Certificate, createHash, createPrivateKey } from 'node:crypto';
import { chmodSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ensureSelfSigned, fingerprint, generateSelfSigned, ipBytes, loadProvided, normalizeNames } from '../server/selfhost/tls.ts';

const WEB = new URL('../', import.meta.url).pathname;
const CLI = join(WEB, 'dist-selfhost/server/selfhost/tls-cli.js');
const DAY = 86400 * 1000;
const dirs = [];
const tmp = () => {
  const d = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'selfhost-tls-'));
  dirs.push(d);
  return d;
};
test.after(() => dirs.forEach((d) => rmSync(d, { recursive: true, force: true })));
const mode = (p) => statSync(p).mode & 0o777;

test('ipBytes：IPv4、IPv6（含 ::）、非 IP', () => {
  assert.deepEqual([...ipBytes('203.0.113.7')], [203, 0, 113, 7]);
  assert.deepEqual([...ipBytes('::1')], [...Array(15).fill(0), 1]);
  assert.deepEqual([...ipBytes('2001:db8::8a2e:370:7334')], [0x20, 1, 0x0d, 0xb8, 0, 0, 0, 0, 0, 0, 0x8a, 0x2e, 3, 0x70, 0x73, 0x34]);
  assert.deepEqual([...ipBytes('::ffff:1.2.3.4')].slice(10), [0xff, 0xff, 1, 2, 3, 4]);
  assert.equal(ipBytes('example.com'), null);
  assert.equal(ipBytes('1.2.3'), null);
});

test('normalizeNames：去空白、去重、保持顺序', () => {
  assert.deepEqual(normalizeNames([' a.example ', '', 'b.example', 'a.example']), ['a.example', 'b.example']);
});

test('自签证书：SAN 含 IPv4、IPv6、域名，CN 是第一个名字，被 Node 自检通过', () => {
  const names = ['203.0.113.7', '2001:db8::1', 'web.example.com'];
  const now = new Date();
  const { certPem, keyPem } = generateSelfSigned(names, now);
  const x = new X509Certificate(certPem);
  assert.ok(x.checkIP('203.0.113.7'));
  assert.ok(x.checkIP('2001:db8::1'));
  assert.ok(x.checkHost('web.example.com'));
  assert.ok(!x.checkIP('203.0.113.8'));
  assert.ok(!x.checkHost('other.example.com'));
  assert.equal(x.subject, 'CN=203.0.113.7');
  assert.equal(x.issuer, x.subject);
  assert.ok(x.verify(x.publicKey), '自签：用自己的公钥验签');
  assert.ok(x.checkPrivateKey(createPrivateKey(keyPem)));
  assert.equal(x.ca, false);
  assert.deepEqual(x.keyUsage, ['1.3.6.1.5.5.7.3.1']); // Node 的 keyUsage 属性列的是 EKU
  assert.equal(x.publicKey.asymmetricKeyType, 'ec');
  assert.equal(x.publicKey.asymmetricKeyDetails.namedCurve, 'prime256v1');
  const days = (new Date(x.validTo) - now) / DAY;
  assert.ok(days > 396.9 && days < 397.1, `有效期 ${days} 天`);
  assert.ok(new Date(x.validFrom) < now, 'notBefore 退了一小时');
  assert.ok(parseInt(x.serialNumber.slice(0, 2), 16) < 0x80, '序列号是正数');
});

test('自签证书：两次生成序列号和密钥都不一样；没有名字报错', () => {
  const a = new X509Certificate(generateSelfSigned(['127.0.0.1']).certPem);
  const b = new X509Certificate(generateSelfSigned(['127.0.0.1']).certPem);
  assert.notEqual(a.serialNumber, b.serialNumber);
  assert.notEqual(a.fingerprint256, b.fingerprint256);
  assert.throws(() => generateSelfSigned([]), /没有公网地址/u);
});

test('指纹：DER 的 SHA-256，大写、冒号分隔，和 Node 自己算的一致', () => {
  const { certPem } = generateSelfSigned(['198.51.100.2']);
  const fp = fingerprint(certPem);
  assert.match(fp, /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/u);
  assert.equal(fp, new X509Certificate(certPem).fingerprint256);
  const der = Buffer.from(certPem.replace(/-----[^-]+-----|\s/gu, ''), 'base64');
  assert.equal(fp.replaceAll(':', '').toLowerCase(), createHash('sha256').update(der).digest('hex'));
});

test('ensureSelfSigned：新目录生成，权限 700/600/644，没有残留临时文件', () => {
  const dir = join(tmp(), 'tls');
  const m = ensureSelfSigned(dir, ['203.0.113.7']);
  assert.equal(m.generated, true);
  assert.equal(m.mode, 'self-signed');
  assert.equal(mode(dir), 0o700);
  assert.equal(mode(join(dir, 'key.pem')), 0o600);
  assert.equal(mode(join(dir, 'cert.pem')), 0o644);
  assert.deepEqual(readdirSync(dir).sort(), ['cert.pem', 'key.pem']);
  assert.equal(m.fingerprint, fingerprint(readFileSync(join(dir, 'cert.pem'), 'utf8')));
  assert.deepEqual(m.names, ['203.0.113.7']);
});

test('ensureSelfSigned：条件都满足就不重建，并把权限收回去', () => {
  const dir = join(tmp(), 'tls');
  const first = ensureSelfSigned(dir, ['203.0.113.7', 'web.example.com']);
  chmodSync(join(dir, 'key.pem'), 0o644);
  const again = ensureSelfSigned(dir, ['203.0.113.7', ' web.example.com ']);
  assert.equal(again.generated, false);
  assert.equal(again.fingerprint, first.fingerprint);
  assert.equal(mode(join(dir, 'key.pem')), 0o600);
});

test('ensureSelfSigned：缺文件、读不出、名字变了、顺序变了、快过期、私钥对不上都重建', () => {
  const dir = join(tmp(), 'tls');
  const names = ['203.0.113.7'];
  const first = ensureSelfSigned(dir, names);
  const rebuilt = (why, n = names, now = new Date()) => {
    const m = ensureSelfSigned(dir, n, now);
    assert.equal(m.generated, true, why);
    return m;
  };
  rmSync(join(dir, 'cert.pem'));
  let m = rebuilt('缺 cert');
  assert.notEqual(m.fingerprint, first.fingerprint);
  writeFileSync(join(dir, 'cert.pem'), 'not a certificate');
  m = rebuilt('读不出');
  m = rebuilt('名字多一个', ['203.0.113.7', 'web.example.com']);
  assert.equal(ensureSelfSigned(dir, ['203.0.113.7', 'web.example.com']).generated, false);
  rebuilt('名字顺序变了（CN 跟着变）', ['web.example.com', '203.0.113.7']);
  rebuilt('名字少一个', ['web.example.com']);
  // 离过期 30 天内：用 now 往后拨 370 天（397-370=27 天）
  assert.equal(ensureSelfSigned(dir, ['web.example.com'], new Date(Date.now() + 360 * DAY)).generated, false, '还剩 37 天不重建');
  rebuilt('快过期', ['web.example.com'], new Date(Date.now() + 370 * DAY));
  // 私钥换成别的
  const other = generateSelfSigned(['web.example.com']);
  writeFileSync(join(dir, 'key.pem'), other.keyPem);
  rebuilt('私钥对不上', ['web.example.com']);
  rmSync(join(dir, 'key.pem'));
  rebuilt('缺 key', ['web.example.com']);
});

test('loadProvided：读自己的证书；坏文件、对不上、过期给出原因', () => {
  const dir = tmp();
  const { certPem, keyPem } = generateSelfSigned(['web.example.com', '203.0.113.9']);
  writeFileSync(join(dir, 'c.pem'), certPem);
  writeFileSync(join(dir, 'k.pem'), keyPem);
  const m = loadProvided(join(dir, 'c.pem'), join(dir, 'k.pem'));
  assert.equal(m.mode, 'provided');
  assert.equal(m.fingerprint, fingerprint(certPem));
  assert.deepEqual(m.names.sort(), ['203.0.113.9', 'web.example.com']);
  assert.ok(m.notAfter > new Date());
  assert.throws(() => loadProvided(join(dir, 'nope.pem'), join(dir, 'k.pem')), /读不了证书/u);
  assert.throws(() => loadProvided(join(dir, 'c.pem'), join(dir, 'nope.pem')), /读不了私钥/u);
  writeFileSync(join(dir, 'bad.pem'), 'x');
  assert.throws(() => loadProvided(join(dir, 'bad.pem'), join(dir, 'k.pem')), /不是 PEM 证书/u);
  assert.throws(() => loadProvided(join(dir, 'c.pem'), join(dir, 'bad.pem')), /不是 PEM 私钥/u);
  writeFileSync(join(dir, 'k2.pem'), generateSelfSigned(['x.example.com']).keyPem);
  assert.throws(() => loadProvided(join(dir, 'c.pem'), join(dir, 'k2.pem')), /对不上/u);
  assert.throws(() => loadProvided(join(dir, 'c.pem'), join(dir, 'k.pem'), new Date(Date.now() + 400 * DAY)), /已在 .* 过期/u);
});

test('tls-cli：输出一行 JSON，第二次 generated=false，名字变了重建；缺参数退出 1', () => {
  assert.ok(existsSync(CLI), '先构建：npm run build:selfhost:server');
  const dir = join(tmp(), 'tls');
  const run = (...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8' });
  const a = run('--dir', dir, '--names', '203.0.113.7,web.example.com');
  assert.equal(a.status, 0, a.stderr);
  assert.equal(a.stdout.trim().split('\n').length, 1);
  const j = JSON.parse(a.stdout);
  assert.deepEqual(Object.keys(j).sort(), ['cert', 'fingerprint', 'generated', 'key', 'names', 'not_after']);
  assert.equal(j.generated, true);
  assert.equal(j.cert, join(dir, 'cert.pem'));
  assert.equal(j.key, join(dir, 'key.pem'));
  assert.deepEqual(j.names, ['203.0.113.7', 'web.example.com']);
  assert.match(j.fingerprint, /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/u);
  assert.equal(j.fingerprint, fingerprint(readFileSync(j.cert, 'utf8')));
  assert.ok(new Date(j.not_after) > new Date());
  const b = JSON.parse(run('--dir', dir, '--names', '203.0.113.7,web.example.com').stdout);
  assert.equal(b.generated, false);
  assert.equal(b.fingerprint, j.fingerprint);
  const c = JSON.parse(run('--dir', dir, '--names', '198.51.100.1').stdout);
  assert.equal(c.generated, true);
  const bad = run('--dir', dir);
  assert.equal(bad.status, 1);
  assert.match(bad.stderr, /缺 --names/u);
  assert.equal(run('--names', 'a').status, 1);
});
