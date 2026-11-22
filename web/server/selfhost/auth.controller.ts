import { Controller, Get, HttpCode, HttpException, HttpStatus, NotFoundException, Param, Post, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService, RateLimited, type SessionInfo } from './auth.service';
import {
  LOGIN_COOKIE,
  LOGIN_TTL_MS,
  SESSION_COOKIE,
  SESSION_TTL_MS,
  buildCookie,
  clearCookie,
  isSecureRequest,
  parseCookies,
  type LoginState,
} from './auth.logic';

/** 登录用的接口。前三个不需要登录（auth.middleware.ts 放行），其余要有效会话 */
@Controller('api/auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('login-requests')
  @HttpCode(200)
  async start(@Req() req: Request, @Res({ passthrough: true }) res: Response): Promise<{ id: string; code: string; expires_at: string }> {
    try {
      const r = await this.auth.start(req.ip ?? '', req.headers['user-agent']);
      res.setHeader('Set-Cookie', buildCookie(LOGIN_COOKIE, r.secret, { maxAgeSec: LOGIN_TTL_MS / 1000, secure: isSecureRequest(req), path: '/api/auth' }));
      res.setHeader('Cache-Control', 'no-store');
      return { id: r.id, code: r.code, expires_at: r.expires_at };
    } catch (e) {
      if (e instanceof RateLimited) {
        res.setHeader('Retry-After', String(e.retryAfter));
        throw new HttpException(e.reason === 'ip' ? '发得太频繁，稍后再试' : '同时等待确认的登录请求太多，稍后再试', HttpStatus.TOO_MANY_REQUESTS);
      }
      throw e;
    }
  }

  @Get('login-requests/:id')
  async poll(@Req() req: Request, @Res({ passthrough: true }) res: Response, @Param('id') id: string): Promise<{ state: LoginState }> {
    res.setHeader('Cache-Control', 'no-store');
    const secret: string = parseCookies(req.headers.cookie)[LOGIN_COOKIE] ?? '';
    const state: LoginState | null = await this.auth.state(id, secret);
    if (!state) throw new NotFoundException('没有这个登录请求');
    if (state !== 'approved') return { state };
    const token: string | null = await this.auth.redeem(id, secret, req.ip ?? '', req.headers['user-agent']);
    if (!token) return { state: 'used' };
    res.setHeader('Set-Cookie', [
      buildCookie(SESSION_COOKIE, token, { maxAgeSec: SESSION_TTL_MS / 1000, secure: isSecureRequest(req) }),
      clearCookie(LOGIN_COOKIE, { secure: isSecureRequest(req), path: '/api/auth' }),
    ]);
    return { state: 'approved' };
  }

  @Get('sessions')
  async sessions(@Req() req: Request): Promise<{ sessions: SessionInfo[] }> {
    return { sessions: await this.auth.list(String((req as Request & { sessionId?: string }).sessionId ?? '')) };
  }

  @Post('logout')
  @HttpCode(200)
  async logout(@Req() req: Request, @Res({ passthrough: true }) res: Response): Promise<{ ok: true }> {
    await this.auth.logout(String((req as Request & { sessionId?: string }).sessionId ?? ''));
    res.setHeader('Set-Cookie', clearCookie(SESSION_COOKIE, { secure: isSecureRequest(req) }));
    return { ok: true };
  }

  @Post('logout-all')
  @HttpCode(200)
  async logoutAll(@Req() req: Request, @Res({ passthrough: true }) res: Response): Promise<{ ok: true; removed: number }> {
    const removed: number = await this.auth.logoutAll();
    res.setHeader('Set-Cookie', clearCookie(SESSION_COOKIE, { secure: isSecureRequest(req) }));
    return { ok: true, removed };
  }
}
