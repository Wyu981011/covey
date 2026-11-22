/**
 * 自托管登录与开放接口密钥的纯逻辑：对照码、UA 解析、频控、cookie、令牌哈希、定长比较。
 * 只用 node 内置模块、不用装饰器和枚举，scripts/selfhost-*.test.mjs 直接导入它做单测。
 */
import { createHash, randomBytes, randomInt, timingSafeEqual } from 'node:crypto';

/** 对照码：4 位，去掉容易看混的 0/O、1/I/L、2/Z、5/S、8/B */
export const CODE_ALPHABET = 'ACDEFGHJKMNPQRTUVWXY3467';
export const CODE_LENGTH = 4;
export const LOGIN_TTL_MS = 5 * 60 * 1000;
export const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
export const IP_WINDOW_MS = 30 * 1000;
export const MAX_PENDING = 5;
export const LOGIN_COOKIE = 'covey_login';
export const SESSION_COOKIE = 'covey_session';
export const CSRF_HEADER = 'x-covey-csrf';
export const OWNER_ID = 'selfhost-owner';

export function newLoginCode(rand: (n: number) => number = (n) => randomInt(n)): string {
  let out = '';
  for (let i = 0; i < CODE_LENGTH; i += 1) out += CODE_ALPHABET[rand(CODE_ALPHABET.length)];
  return out;
}

/** 128 位随机，hex：登录请求的 id、会话的 id */
export function newId(): string {
  return randomBytes(16).toString('hex');
}

/** 256 位随机，base64url：浏览器 cookie 里的令牌 */
export function newToken(): string {
  return randomBytes(32).toString('base64url');
}

export function sha256Hex(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

/** 定长比较：先各取 sha256 再比，长度不同、内容不同都花一样的时间 */
export function safeEqual(a: string, b: string): boolean {
  const ha: Buffer = createHash('sha256').update(a, 'utf8').digest();
  const hb: Buffer = createHash('sha256').update(b, 'utf8').digest();
  return timingSafeEqual(ha, hb);
}

export interface Agent {
  browser: string;
  os: string;
}

/** 从 User-Agent 粗略认出浏览器和系统，认不出是“未知浏览器”“未知系统”。顺序有讲究：Edge、Opera 的 UA 里也有 Chrome */
export function parseUserAgent(ua: string | undefined): Agent {
  const s: string = String(ua ?? '').slice(0, 400);
  let browser = '未知浏览器';
  if (/\b(Edg|EdgA|EdgiOS)\//u.test(s)) browser = 'Edge';
  else if (/\b(OPR|Opera)\//u.test(s)) browser = 'Opera';
  else if (/\b(Firefox|FxiOS)\//u.test(s)) browser = 'Firefox';
  else if (/\b(Chrome|CriOS|Chromium)\//u.test(s)) browser = 'Chrome';
  else if (/\bSafari\//u.test(s) && /\bVersion\//u.test(s)) browser = 'Safari';
  else if (/curl\//iu.test(s)) browser = 'curl';
  let os = '未知系统';
  if (/\b(iPhone|iPad|iPod)\b/u.test(s)) os = 'iOS';
  else if (/\bAndroid\b/u.test(s)) os = 'Android';
  else if (/\bWindows\b/u.test(s)) os = 'Windows';
  else if (/\b(Macintosh|Mac OS X)\b/u.test(s)) os = 'macOS';
  else if (/\bCrOS\b/u.test(s)) os = 'ChromeOS';
  else if (/\bLinux\b|\bX11\b/u.test(s)) os = 'Linux';
  return { browser, os };
}

export function agentLabel(a: Agent): string {
  return `${a.browser} · ${a.os}`;
}

export type LimitVerdict = { ok: true } | { ok: false; retryAfter: number; reason: 'ip' | 'pending' };

/** 发起登录的频控：同一来源 IP 在窗口内只能发一次；全局同时待定的不超过上限。IP 的记录在内存里，不跨重启（重启后至多多放一次） */
export class LoginLimiter {
  private readonly last = new Map<string, number>();

  private readonly ipWindowMs: number;
  private readonly maxPending: number;

  constructor(ipWindowMs: number = IP_WINDOW_MS, maxPending: number = MAX_PENDING) {
    this.ipWindowMs = ipWindowMs;
    this.maxPending = maxPending;
  }

  /** pending：库里现在没过期、没处理的登录请求数 */
  check(ip: string, pending: number, now: number): LimitVerdict {
    const prev: number | undefined = this.last.get(ip);
    if (prev !== undefined && now - prev < this.ipWindowMs) {
      return { ok: false, retryAfter: Math.max(1, Math.ceil((this.ipWindowMs - (now - prev)) / 1000)), reason: 'ip' };
    }
    if (pending >= this.maxPending) return { ok: false, retryAfter: Math.ceil(this.ipWindowMs / 1000), reason: 'pending' };
    return { ok: true };
  }

  /** 放行了才记，被拒的不顺延窗口 */
  record(ip: string, now: number): void {
    this.last.set(ip, now);
    if (this.last.size > 1000) {
      for (const [k, t] of this.last) if (now - t >= this.ipWindowMs) this.last.delete(k);
    }
  }
}

export interface CookieOptions {
  maxAgeSec?: number;
  secure?: boolean;
  path?: string;
}

/** 都是 HttpOnly + SameSite=Lax；https 时加 Secure */
export function buildCookie(name: string, value: string, opt: CookieOptions = {}): string {
  const parts: string[] = [`${name}=${encodeURIComponent(value)}`, `Path=${opt.path ?? '/'}`, 'HttpOnly', 'SameSite=Lax'];
  if (opt.maxAgeSec !== undefined) parts.push(`Max-Age=${Math.max(0, Math.floor(opt.maxAgeSec))}`);
  if (opt.secure) parts.push('Secure');
  return parts.join('; ');
}

export function clearCookie(name: string, opt: CookieOptions = {}): string {
  return buildCookie(name, '', { ...opt, maxAgeSec: 0 });
}

export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const piece of String(header ?? '').split(';')) {
    const i: number = piece.indexOf('=');
    if (i <= 0) continue;
    const k: string = piece.slice(0, i).trim();
    if (!k || k in out) continue;
    try {
      out[k] = decodeURIComponent(piece.slice(i + 1).trim());
    } catch {
      out[k] = piece.slice(i + 1).trim();
    }
  }
  return out;
}

export type LoginState = 'pending' | 'approved' | 'denied' | 'expired' | 'used';

/** 库里的状态加上有没有过期，得出页面看到的状态：没处理完的过期就是 expired；denied、used 不管过没过期 */
export function loginStateOf(state: string, expiresAt: number, now: number): LoginState {
  if (state === 'denied' || state === 'used') return state;
  if (now >= expiresAt) return 'expired';
  return state === 'approved' ? 'approved' : 'pending';
}

export function isLoopback(addr: string | undefined): boolean {
  const a: string = String(addr ?? '');
  return a === '::1' || a === '127.0.0.1' || /^127\.\d+\.\d+\.\d+$/u.test(a) || /^::ffff:127\.\d+\.\d+\.\d+$/iu.test(a);
}

/** 存库和给主人看的来源 IP：去掉 IPv4 映射前缀（::ffff:127.0.0.1 → 127.0.0.1），最长 64 字 */
export function plainIp(addr: string | undefined): string {
  return String(addr ?? '').replace(/^::ffff:(?=\d+\.\d+\.\d+\.\d+$)/iu, '').slice(0, 64);
}

/** 请求带的是不是 `Authorization: Bearer <key>` 且密钥对（密钥没配或为空一律不对） */
export function bearerOk(header: string | undefined, key: string): boolean {
  if (!key) return false;
  const m: RegExpExecArray | null = /^Bearer[ \t]+(\S+)[ \t]*$/iu.exec(String(header ?? ''));
  return m ? safeEqual(m[1], key) : false;
}
