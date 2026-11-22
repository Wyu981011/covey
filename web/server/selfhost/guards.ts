/** 自托管服务最前面的几道 express 中间件：丢掉平台头、校验开放接口密钥、校验会话和 CSRF */
import type { NextFunction, Request, RequestHandler, Response } from 'express';
import type { AuthService } from './auth.service';
import type { KeySource } from './config';
import { CSRF_HEADER, OWNER_ID, SESSION_COOKIE, bearerOk, isLoopback, parseCookies } from './auth.logic';

function deny(res: Response, status: number, code: string, message: string): void {
  res.status(status).json({ error: { code, message, timestamp: Date.now() } });
}

/** 公网 HTTPS 监听上的请求：main.ts 在转给 Express 前标上 */
export type PublicRequest = Request & { coveyPublic?: boolean };

export const isHealthPath = (path: string): boolean => /^\/healthz\/?$/iu.test(path);

/** 所有响应都带：不许被嵌进别的页面、不许猜内容类型、跨站不带来源。不加 HSTS：自签证书加了浏览器就不给“继续访问” */
export const securityHeaders: RequestHandler = (_req: Request, res: Response, next: NextFunction) => {
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Content-Security-Policy', "frame-ancestors 'none'");
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'same-origin');
  next();
};

/** 公网监听上：/openapi/* 一律 403（不论密钥），/healthz 当没有（404，不让它落到页面回退上） */
export const publicGuard: RequestHandler = (req: Request, res: Response, next: NextFunction) => {
  if (!(req as PublicRequest).coveyPublic) return next();
  if (isOpenapiPath(req.path)) return deny(res, 403, 'FORBIDDEN', '开放接口不对公网开放');
  if (isHealthPath(req.path)) return deny(res, 404, 'NOT_FOUND', '没有这个接口');
  next();
};

/** 收到的 x-larkgw-* 一律丢掉：自托管的身份只认自己签的会话，平台注入的头谁都能伪造 */
export const stripPlatformHeaders: RequestHandler = (req: Request, _res: Response, next: NextFunction) => {
  for (const name of Object.keys(req.headers)) {
    if (name.toLowerCase().startsWith('x-larkgw-')) delete req.headers[name];
  }
  next();
};

/**
 * 路径前缀按不分大小写比：Express 的路由默认不分大小写，/OPENAPI/sync/inbox 一样会走到开放接口的控制器，
 * 这里要是分大小写，换个写法就绕过了密钥（/API 同理）。
 */
export const isOpenapiPath = (path: string): boolean => /^\/openapi(\/|$)/iu.test(path);
export const isApiPath = (path: string): boolean => /^\/api(\/|$)/iu.test(path);

/** /openapi/*：Bearer 密钥（定长比较）+ 只收回环来源（有转发头的也算非回环，除非 allowRemote） */
export function openapiGuard(keys: KeySource, allowRemote: boolean): RequestHandler {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!isOpenapiPath(req.path)) return next();
    if (!allowRemote) {
      const forwarded: boolean = Boolean(req.headers['x-forwarded-for'] || req.headers['forwarded'] || req.headers['x-real-ip']);
      if (!isLoopback(req.socket.remoteAddress) || forwarded) return deny(res, 403, 'FORBIDDEN', '开放接口只收本机来源');
    }
    if (!bearerOk(req.headers.authorization, keys.current())) return deny(res, 401, 'UNAUTHORIZED', '密钥不对');
    next();
  };
}

/** 登录前就要能用的接口：发起登录、轮询登录结果 */
export function isLoginRoute(method: string, path: string): boolean {
  if (method === 'POST' && /^\/api\/auth\/login-requests\/?$/iu.test(path)) return true;
  return method === 'GET' && /^\/api\/auth\/login-requests\/[^/]+\/?$/iu.test(path);
}

/** /api/*：非 GET 要带 x-covey-csrf: 1；除登录接口外都要有效会话，有效就把主人填进 req.userContext */
export function apiGuard(auth: AuthService): RequestHandler {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!isApiPath(req.path)) return next();
    if (req.method !== 'GET' && req.method !== 'HEAD' && req.method !== 'OPTIONS' && req.headers[CSRF_HEADER] !== '1') {
      return deny(res, 403, 'FORBIDDEN', `缺请求头 ${CSRF_HEADER}: 1`);
    }
    if (isLoginRoute(req.method, req.path)) return next();
    const token: string = parseCookies(req.headers.cookie)[SESSION_COOKIE] ?? '';
    auth
      .verify(token)
      .then((sessionId: string | null) => {
        if (!sessionId) return deny(res, 401, 'UNAUTHORIZED', '请先登录');
        const r = req as Request & { sessionId?: string; userContext?: Record<string, unknown> };
        r.sessionId = sessionId;
        r.userContext = { userId: OWNER_ID, userName: '' };
        res.setHeader('Cache-Control', 'no-store');
        next();
      })
      .catch(next);
  };
}
