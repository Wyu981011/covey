/**
 * 公网 HTTPS 用的证书：自签证书的生成（只用 node:crypto，手写 DER，不加依赖）、保证它在、读自己给的证书、算指纹。
 * 纯函数加文件操作；不依赖 Nest，单测和 tls-cli 直接用。
 */
import { X509Certificate, createHash, createPrivateKey, generateKeyPairSync, randomBytes, sign } from 'node:crypto';
import type { KeyObject } from 'node:crypto';
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { isIP } from 'node:net';
import { join } from 'node:path';

export const VALID_DAYS = 397;
/** 离过期不到这么多天就重建 */
export const RENEW_BEFORE_DAYS = 30;
const DAY_MS = 86400 * 1000;

// ---------------------------------------------------------------- DER

function len(n: number): Buffer {
  if (n < 0x80) return Buffer.from([n]);
  const bytes: number[] = [];
  for (let v = n; v > 0; v = Math.floor(v / 256)) bytes.unshift(v & 0xff);
  return Buffer.from([0x80 | bytes.length, ...bytes]);
}

function tlv(tag: number, ...parts: Buffer[]): Buffer {
  const body: Buffer = Buffer.concat(parts);
  return Buffer.concat([Buffer.from([tag]), len(body.length), body]);
}

const seq = (...p: Buffer[]): Buffer => tlv(0x30, ...p);
const set = (...p: Buffer[]): Buffer => tlv(0x31, ...p);

function oid(dotted: string): Buffer {
  const parts: number[] = dotted.split('.').map(Number);
  const out: number[] = [parts[0] * 40 + parts[1]];
  for (const n of parts.slice(2)) {
    const chunk: number[] = [n & 0x7f];
    for (let v = Math.floor(n / 128); v > 0; v = Math.floor(v / 128)) chunk.unshift((v & 0x7f) | 0x80);
    out.push(...chunk);
  }
  return tlv(0x06, Buffer.from(out));
}

/** 正整数：最高位是 1 要补 0x00，去掉多余的前导 0 */
function uint(bytes: Buffer): Buffer {
  let b: Buffer = bytes;
  while (b.length > 1 && b[0] === 0 && b[1] < 0x80) b = b.subarray(1);
  return tlv(0x02, b[0] >= 0x80 ? Buffer.concat([Buffer.from([0]), b]) : b);
}

function utcTime(d: Date): Buffer {
  const p = (n: number): string => String(n).padStart(2, '0');
  const s = `${p(d.getUTCFullYear() % 100)}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}Z`;
  return tlv(0x17, Buffer.from(s, 'ascii'));
}

/** IPv4 / IPv6（不带方括号，可带 ::）的网络字节序；不是 IP 返回 null */
export function ipBytes(text: string): Buffer | null {
  const v: number = isIP(text);
  if (v === 4) return Buffer.from(text.split('.').map(Number));
  if (v !== 6) return null;
  let s: string = text.split('%')[0];
  // 末尾的 IPv4 写法（::ffff:1.2.3.4）换成两组十六进制
  const m = /^(.*:)(\d+)\.(\d+)\.(\d+)\.(\d+)$/u.exec(s);
  if (m) {
    const [a, b, c, d] = [m[2], m[3], m[4], m[5]].map(Number);
    s = `${m[1]}${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`;
  }
  const [head, tail] = s.split('::');
  const left: string[] = head ? head.split(':') : [];
  const right: string[] = tail === undefined ? [] : tail ? tail.split(':') : [];
  const fill: string[] = tail === undefined ? [] : Array<string>(8 - left.length - right.length).fill('0');
  const out = Buffer.alloc(16);
  [...left, ...fill, ...right].forEach((g, i) => out.writeUInt16BE(parseInt(g, 16), i * 2));
  return out;
}

const OID_ECDSA_SHA256 = '1.2.840.10045.4.3.2';

function name(cn: string): Buffer {
  return seq(set(seq(oid('2.5.4.3'), tlv(0x0c, Buffer.from(cn.slice(0, 64), 'utf8')))));
}

function extension(id: string, critical: boolean, value: Buffer): Buffer {
  return seq(oid(id), ...(critical ? [tlv(0x01, Buffer.from([0xff]))] : []), tlv(0x04, value));
}

/** 去空白、去重，保持顺序 */
export function normalizeNames(names: readonly string[]): string[] {
  const seen = new Set<string>();
  for (const n of names) {
    const t: string = String(n).trim();
    if (t) seen.add(t);
  }
  return [...seen];
}

export interface GeneratedCert {
  certPem: string;
  keyPem: string;
}

/** 生成一张自签证书（EC P-256、SHA-256、397 天）。notBefore 退一小时，容忍手机和服务器的时钟差 */
export function generateSelfSigned(names: readonly string[], now: Date = new Date()): GeneratedCert {
  const list: string[] = normalizeNames(names);
  if (list.length === 0) throw new Error('没有公网地址，无法生成证书');
  const { publicKey, privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const spki: Buffer = publicKey.export({ type: 'spki', format: 'der' });
  const sanItems: Buffer[] = list.map((n) => {
    const ip: Buffer | null = ipBytes(n);
    return ip ? tlv(0x87, ip) : tlv(0x82, Buffer.from(n, 'ascii'));
  });
  const exts: Buffer = seq(
    extension('2.5.29.19', true, seq()), // basicConstraints: CA:FALSE
    extension('2.5.29.15', true, Buffer.from([0x03, 0x02, 0x07, 0x80])), // keyUsage: digitalSignature
    extension('2.5.29.37', false, seq(oid('1.3.6.1.5.5.7.3.1'))), // EKU: serverAuth
    extension('2.5.29.17', false, seq(...sanItems)),
  );
  const serial: Buffer = randomBytes(16);
  serial[0] &= 0x7f; // 正数
  if (serial[0] === 0) serial[0] = 1;
  const algo: Buffer = seq(oid(OID_ECDSA_SHA256));
  const subject: Buffer = name(list[0]);
  const tbs: Buffer = seq(
    tlv(0xa0, uint(Buffer.from([2]))), // v3
    uint(serial),
    algo,
    subject,
    seq(utcTime(new Date(now.getTime() - 3600 * 1000)), utcTime(new Date(now.getTime() + VALID_DAYS * DAY_MS))),
    subject,
    spki,
    tlv(0xa3, exts),
  );
  const sig: Buffer = sign('sha256', tbs, privateKey); // EC 默认就是 DER 编码的 ECDSA-Sig-Value
  const der: Buffer = seq(tbs, algo, tlv(0x03, Buffer.from([0]), sig));
  const certPem = `-----BEGIN CERTIFICATE-----\n${(der.toString('base64').match(/.{1,64}/gu) ?? []).join('\n')}\n-----END CERTIFICATE-----\n`;
  const keyPem: string = privateKey.export({ type: 'pkcs8', format: 'pem' }) as string;
  return { certPem, keyPem };
}

// ---------------------------------------------------------------- 读和查

/** 证书 DER 的 SHA-256，大写十六进制、冒号分隔（和浏览器证书详情里的“SHA-256 指纹”一样） */
export function fingerprint(certPem: string): string {
  const raw: Buffer = new X509Certificate(certPem).raw;
  return (createHash('sha256').update(raw).digest('hex').toUpperCase().match(/../gu) ?? []).join(':');
}

export interface TlsMaterial {
  mode: 'self-signed' | 'provided';
  certPath: string;
  keyPath: string;
  cert: string;
  key: string;
  fingerprint: string;
  notAfter: Date;
  /** 自签：就是传进来的名字；自己的证书：证书 SAN 里读到的 */
  names: string[];
  generated: boolean;
}

function notAfterOf(x: X509Certificate): Date {
  return new Date(x.validTo);
}

/** 证书的 SAN 数量、每个名字都盖得住、CN 是第一个名字 */
function coversNames(x: X509Certificate, names: readonly string[]): boolean {
  const entries: string[] = (x.subjectAltName ?? '').split(/,\s*/u).filter(Boolean);
  if (entries.length !== names.length) return false;
  if (!new RegExp(`(^|\\n)CN=${names[0].slice(0, 64).replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}($|\\n)`, 'u').test(x.subject)) return false;
  return names.every((n) => (isIP(n) ? Boolean(x.checkIP(n)) : Boolean(x.checkHost(n))));
}

function usable(certPath: string, keyPath: string, names: readonly string[], now: Date): TlsMaterial | null {
  try {
    const cert: string = readFileSync(certPath, 'utf8');
    const key: string = readFileSync(keyPath, 'utf8');
    const x = new X509Certificate(cert);
    const priv: KeyObject = createPrivateKey(key);
    if (!x.checkPrivateKey(priv)) return null;
    if (notAfterOf(x).getTime() - now.getTime() < RENEW_BEFORE_DAYS * DAY_MS) return null;
    if (new Date(x.validFrom).getTime() > now.getTime() + DAY_MS) return null;
    if (!coversNames(x, names)) return null;
    return { mode: 'self-signed', certPath, keyPath, cert, key, fingerprint: fingerprint(cert), notAfter: notAfterOf(x), names: [...names], generated: false };
  } catch {
    return null;
  }
}

function writeAtomic(path: string, data: string, mode: number): void {
  const tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, data, { mode });
  chmodSync(tmp, mode);
  renameSync(tmp, path);
}

/** 保证 dir 里有一张盖住 names 的、至少还有 30 天有效期的自签证书：不满足就重建。目录 700，key.pem 600，cert.pem 644 */
export function ensureSelfSigned(dir: string, names: readonly string[], now: Date = new Date()): TlsMaterial {
  const list: string[] = normalizeNames(names);
  if (list.length === 0) throw new Error('没有公网地址，无法准备证书');
  const certPath: string = join(dir, 'cert.pem');
  const keyPath: string = join(dir, 'key.pem');
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  chmodSync(dir, 0o700);
  const have: TlsMaterial | null = existsSync(certPath) && existsSync(keyPath) ? usable(certPath, keyPath, list, now) : null;
  if (have) {
    // 已有的证书也把权限收回正确的值
    chmodSync(keyPath, 0o600);
    chmodSync(certPath, 0o644);
    return have;
  }
  const made: GeneratedCert = generateSelfSigned(list, now);
  try {
    writeAtomic(keyPath, made.keyPem, 0o600);
    writeAtomic(certPath, made.certPem, 0o644);
  } catch (e) {
    rmSync(`${keyPath}.${process.pid}.tmp`, { force: true });
    rmSync(`${certPath}.${process.pid}.tmp`, { force: true });
    throw e;
  }
  const x = new X509Certificate(made.certPem);
  return { mode: 'self-signed', certPath, keyPath, cert: made.certPem, key: made.keyPem, fingerprint: fingerprint(made.certPem), notAfter: notAfterOf(x), names: list, generated: true };
}

/** 自己的证书链和私钥（PEM）：读不出、私钥和证书对不上、已过期就抛错，原因写在消息里 */
export function loadProvided(certPath: string, keyPath: string, now: Date = new Date()): TlsMaterial {
  let cert: string;
  let key: string;
  try {
    cert = readFileSync(certPath, 'utf8');
  } catch (e) {
    throw new Error(`读不了证书 ${certPath}：${(e as NodeJS.ErrnoException).code ?? String(e)}`);
  }
  try {
    key = readFileSync(keyPath, 'utf8');
  } catch (e) {
    throw new Error(`读不了私钥 ${keyPath}：${(e as NodeJS.ErrnoException).code ?? String(e)}`);
  }
  let x: X509Certificate;
  try {
    x = new X509Certificate(cert);
  } catch {
    throw new Error(`${certPath} 不是 PEM 证书`);
  }
  let priv: KeyObject;
  try {
    priv = createPrivateKey(key);
  } catch {
    throw new Error(`${keyPath} 不是 PEM 私钥（带口令的私钥不支持）`);
  }
  if (!x.checkPrivateKey(priv)) throw new Error('私钥和证书对不上');
  const notAfter: Date = notAfterOf(x);
  if (notAfter.getTime() <= now.getTime()) throw new Error(`证书已在 ${notAfter.toISOString()} 过期`);
  const names: string[] = (x.subjectAltName ?? '')
    .split(/,\s*/u)
    .map((s) => s.replace(/^(DNS|IP Address):/u, '').trim())
    .filter(Boolean);
  return { mode: 'provided', certPath, keyPath, cert, key, fingerprint: fingerprint(cert), notAfter, names, generated: false };
}
