/** 自托管服务自己的两个小接口：/healthz（本机体检）和 /openapi/selfhost/backup（网页库快照）。plain express，在 Nest 路由之前注册 */
import type { Request, RequestHandler, Response } from 'express';
import type { SelfhostDb } from './db';
import { isLoopback } from './auth.logic';
import { isHealthPath } from './guards';

export interface PublicHealth {
  host: string;
  port: number;
  names: string[];
  tls: 'self-signed' | 'provided';
  fingerprint: string;
  not_after: string;
  listening: boolean;
  error: string;
}

export interface HealthState {
  db: SelfhostDb['kind'];
  startedAt: string;
  /** 没开公网是 null；开了但证书准备不了时 listening=false、error 写原因 */
  public: PublicHealth | null;
}

export const isBackupPath = (path: string): boolean => /^\/openapi\/selfhost\/backup\/?$/iu.test(path);

/**
 * GET /healthz：不要会话，只给本机直连（Covey 的体检）：公网监听上的请求在 publicGuard 里已经 404；
 * 经本机反代（tailscale serve、nginx 转到回环端口）来的、带转发头的也当没有，和开放接口一样只认直连
 */
export function healthHandler(state: HealthState): RequestHandler {
  return (req: Request, res: Response, next) => {
    if (req.method !== 'GET' || !isHealthPath(req.path)) return next();
    const forwarded: boolean = Boolean(req.headers['x-forwarded-for'] || req.headers['forwarded'] || req.headers['x-real-ip']);
    if (forwarded || !isLoopback(req.socket.remoteAddress)) {
      res.status(404).json({ error: { code: 'NOT_FOUND', message: '没有这个接口', timestamp: Date.now() } });
      return;
    }
    res.setHeader('Cache-Control', 'no-store');
    res.json({ ok: true, pid: process.pid, db: state.db, started_at: state.startedAt, public: state.public });
  };
}

/** GET /openapi/selfhost/backup：放在 openapiGuard 之后（密钥、本机直连已经验过）。外部库 409，超限 413 */
export function backupHandler(db: SelfhostDb, maxBytes: number): RequestHandler {
  return (req: Request, res: Response, next) => {
    if (req.method !== 'GET' || !isBackupPath(req.path)) return next();
    const fail = (status: number, code: string, message: string): void => {
      res.status(status).json({ error: { code, message, timestamp: Date.now() } });
    };
    db.dump()
      .then((buf: Buffer | null) => {
        if (!buf) return fail(409, 'EXTERNAL_DB', '外部 Postgres 用 pg_dump 备份');
        if (buf.length > maxBytes) return fail(413, 'TOO_LARGE', `库快照 ${buf.length} 字节，超过上限 ${maxBytes}`);
        res.setHeader('Content-Type', 'application/gzip');
        res.setHeader('Cache-Control', 'no-store');
        res.setHeader('Content-Length', String(buf.length));
        res.end(buf);
      })
      .catch(next);
  };
}
