import { Inject, Injectable, Logger } from '@nestjs/common';
import { sql } from 'drizzle-orm';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from './platform-shim';
import { asRows } from '../modules/workbench/workbench.util';
import {
  LOGIN_TTL_MS,
  LoginLimiter,
  SESSION_TTL_MS,
  agentLabel,
  loginStateOf,
  newId,
  newLoginCode,
  newToken,
  parseUserAgent,
  plainIp,
  sha256Hex,
  type LoginState,
} from './auth.logic';

export interface LoginStarted {
  id: string;
  code: string;
  expires_at: string;
  /** 只在发起的浏览器里存成 cookie，库里只有它的 sha256 */
  secret: string;
}

export interface SessionInfo {
  id: string;
  browser: string;
  os: string;
  ip: string;
  created_at: string;
  last_used_at: string;
  current: boolean;
}

export class RateLimited extends Error {
  constructor(
    readonly retryAfter: number,
    readonly reason: 'ip' | 'pending',
  ) {
    super('rate limited');
  }
}

interface SessionRow {
  id: string;
  last_used_at: Date | string;
}

@Injectable()
export class AuthService {
  private readonly logger = new Logger(AuthService.name);
  private readonly limiter = new LoginLimiter();

  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}

  /** 发起登录：写 login_requests，并往发件箱写一条 login 操作，由 Covey 取走后给主人发确认卡 */
  async start(from: string, userAgent: string | undefined, now: number = Date.now()): Promise<LoginStarted> {
    const ip: string = plainIp(from);
    await this.db.execute(sql`delete from login_requests where expires_at < now() - interval '1 day'`);
    const pendingRow = asRows<{ n: number }>(
      await this.db.execute(sql`select count(*)::int as n from login_requests where state = 'pending' and expires_at > now()`),
    )[0];
    const verdict = this.limiter.check(ip, Number(pendingRow?.n ?? 0), now);
    if (verdict.ok === false) throw new RateLimited(verdict.retryAfter, verdict.reason);
    this.limiter.record(ip, now);
    const id: string = newId();
    const code: string = newLoginCode();
    const secret: string = newToken();
    const agent = parseUserAgent(userAgent);
    const expiresAt: Date = new Date(now + LOGIN_TTL_MS);
    await this.db.execute(sql`insert into login_requests(id, code, browser_hash, browser, os, ip, expires_at)
      values (${id}, ${code}, ${sha256Hex(secret)}, ${agent.browser}, ${agent.os}, ${ip}, ${expiresAt.toISOString()}::timestamptz)`);
    // at：发起时间，秒（Covey 的 app/web_login.py 按它算 5 分钟有效期）；ip：发起的来源，确认卡上给主人看（本机来的写“本机”）
    const payload: string = JSON.stringify({ request_id: id, code, browser: agent.browser, os: agent.os, ip, at: Math.floor(now / 1000) });
    await this.db.execute(sql`insert into outbox(op_id, kind, payload) values (${`login-${id}`}, 'login', ${payload}::jsonb)
      on conflict (op_id) do nothing`);
    this.logger.log(`登录请求 ${id.slice(0, 8)}：${agentLabel(agent)}`);
    return { id, code, expires_at: expiresAt.toISOString(), secret };
  }

  /** 一条登录请求现在的状态；cookie 里的 secret 对不上返回 null（当它不存在） */
  async state(id: string, secret: string, now: number = Date.now()): Promise<LoginState | null> {
    const row = await this.load(id, secret);
    return row ? loginStateOf(row.state, row.expires_at.getTime(), now) : null;
  }

  /** approved 且对得上发起的浏览器：把请求标成 used 并签一个会话，返回会话令牌；否则 null。标 used 是原子的，同一请求只能签一次 */
  async redeem(id: string, secret: string, from: string, userAgent: string | undefined, now: number = Date.now()): Promise<string | null> {
    const ip: string = plainIp(from);
    const claimed = asRows<{ browser: string; os: string }>(
      await this.db.execute(sql`update login_requests set state = 'used', _updated_at = now()
        where id = ${id} and state = 'approved' and expires_at > now() and browser_hash = ${sha256Hex(secret)}
        returning browser, os`),
    )[0];
    if (!claimed) return null;
    const token: string = newToken();
    const expiresAt: Date = new Date(now + SESSION_TTL_MS);
    await this.db.execute(sql`insert into web_sessions(id, token_hash, browser, os, ip, expires_at)
      values (${newId()}, ${sha256Hex(token)}, ${claimed.browser}, ${claimed.os}, ${ip}, ${expiresAt.toISOString()}::timestamptz)`);
    return token;
  }

  private async load(id: string, secret: string): Promise<{ state: string; expires_at: Date } | null> {
    if (!/^[0-9a-f]{32}$/u.test(id) || !secret) return null;
    const row = asRows<{ state: string; expires_at: Date | string }>(
      await this.db.execute(sql`select state, expires_at from login_requests where id = ${id} and browser_hash = ${sha256Hex(secret)}`),
    )[0];
    return row ? { state: row.state, expires_at: new Date(row.expires_at) } : null;
  }

  /** 会话令牌换会话 id；过期的、没有的返回 null。最近使用时间一分钟内不重复写 */
  async verify(token: string): Promise<string | null> {
    if (!token) return null;
    const row = asRows<SessionRow>(
      await this.db.execute(sql`select id, last_used_at from web_sessions where token_hash = ${sha256Hex(token)} and expires_at > now()`),
    )[0];
    if (!row) return null;
    if (Date.now() - new Date(row.last_used_at).getTime() > 60_000) {
      await this.db.execute(sql`update web_sessions set last_used_at = now(), _updated_at = now() where id = ${row.id}`);
    }
    return row.id;
  }

  async list(currentId: string): Promise<SessionInfo[]> {
    const rows = asRows<{ id: string; browser: string; os: string; ip: string; created_at: Date | string; last_used_at: Date | string }>(
      await this.db.execute(sql`select id, browser, os, ip, _created_at as created_at, last_used_at
        from web_sessions where expires_at > now() order by last_used_at desc`),
    );
    return rows.map((r) => ({
      id: r.id,
      browser: r.browser,
      os: r.os,
      ip: r.ip,
      created_at: new Date(r.created_at).toISOString(),
      last_used_at: new Date(r.last_used_at).toISOString(),
      current: r.id === currentId,
    }));
  }

  async logout(id: string): Promise<void> {
    await this.db.execute(sql`delete from web_sessions where id = ${id}`);
  }

  async logoutAll(): Promise<number> {
    return asRows<{ n: number }>(await this.db.execute(sql`delete from web_sessions returning 1 as n`)).length;
  }
}
