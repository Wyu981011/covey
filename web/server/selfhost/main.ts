// 必须最先：把妙搭平台包指到本地垫片，之后加载的 workbench 代码才不会碰平台
import './register-hook';
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { Logger } from '@nestjs/common';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { loadConfig, KeySource } from './config';
import { openDb } from './db';
import { OWNER_ID } from './auth.logic';
import { AuthService } from './auth.service';
import { apiGuard, openapiGuard, stripPlatformHeaders } from './guards';
import { selfhostAppModule } from './selfhost.module';

async function bootstrap(): Promise<void> {
  const log = new Logger('Selfhost');
  const cfg = loadConfig();
  const keys = new KeySource();
  // 自托管下主人是固定的一个人（会话有效就是主人），workbench 控制器里的 mustBeOwner 照旧比这个值
  process.env.COVEY_OWNER_USER_ID = OWNER_ID;
  const db = await openDb(cfg);
  const app = await NestFactory.create<NestExpressApplication>(selfhostAppModule(db, cfg.staticDir), { bodyParser: false });
  // 本机反代（tailscale serve、nginx）带来的 X-Forwarded-*：只信回环来的，req.ip 和 req.secure 才对
  app.set('trust proxy', 'loopback');
  app.disable('x-powered-by');
  app.use(stripPlatformHeaders);
  app.use(openapiGuard(keys, cfg.allowRemoteOpenapi));
  app.useBodyParser('json', { limit: '2mb' });
  app.useBodyParser('urlencoded', { extended: true, limit: '2mb' });
  app.use(apiGuard(app.get(AuthService)));
  app.useStaticAssets(cfg.staticDir, { index: false, maxAge: '1h', setHeaders: (res, path) => {
    if (path.includes('/assets/')) res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
  } });
  if (!keys.current()) log.warn('没有开放接口密钥（COVEY_WEB_KEY_FILE 或 COVEY_WEB_OPENAPI_KEY）：/openapi 会拒绝所有请求');
  await app.listen(cfg.port, cfg.host);
  log.log(`网页工作台（自托管）：http://${cfg.host}:${cfg.port}`);
  // 不用 Nest 的 enableShutdownHooks：它关完应用会重发信号结束进程，PGlite 来不及关库。这里先关应用、再关库、再退出
  let stopping = false;
  const stop = (why: string): void => {
    if (stopping) return;
    stopping = true;
    log.log(`停止：${why}`);
    setTimeout(() => process.exit(0), 8000).unref(); // 关不完也在 Manager 的 SIGKILL 之前退出
    void app
      .close()
      .then(() => db.close())
      .catch((e: unknown) => log.error(`关闭出错：${String(e)}`))
      .then(() => process.exit(0));
  };
  process.once('SIGTERM', () => stop('SIGTERM'));
  process.once('SIGINT', () => stop('SIGINT'));
  followParent(stop);
}

/**
 * Manager 拉起时给 COVEY_WEB_PARENT_PID（它自己的 pid）。Manager 被强杀时收不到它的 SIGTERM，
 * 这里发现父进程换了就自己退出，免得一直占着端口、让下一个 Manager 拉起的进程起不来。手工启动不设它，不跟。
 */
function followParent(stop: (why: string) => void): void {
  const parent: number = Number(process.env.COVEY_WEB_PARENT_PID || 0);
  if (!Number.isInteger(parent) || parent <= 1) return;
  const timer = setInterval(() => {
    if (process.ppid !== parent) {
      clearInterval(timer);
      stop(`父进程 ${parent} 不在了`);
    }
  }, 3000);
  timer.unref();
}

void bootstrap();
