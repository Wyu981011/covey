// 必须最先：把妙搭平台包指到本地垫片，之后加载的 workbench 代码才不会碰平台
import './register-hook';
import 'reflect-metadata';
import { createServer as createHttp } from 'node:http';
import type { Server, IncomingMessage, ServerResponse } from 'node:http';
import { createServer as createHttps } from 'node:https';
import type { Server as SecureServer } from 'node:tls';
import { NestFactory } from '@nestjs/core';
import { Logger } from '@nestjs/common';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { loadConfig, KeySource } from './config';
import { openDb } from './db';
import { OWNER_ID } from './auth.logic';
import { AuthService } from './auth.service';
import { apiGuard, openapiGuard, publicGuard, securityHeaders, stripPlatformHeaders, type PublicRequest } from './guards';
import { backupHandler, healthHandler, type HealthState, type PublicHealth } from './routes';
import { ensureSelfSigned, loadProvided, type TlsMaterial } from './tls';
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
  const health: HealthState = { db: db.kind, startedAt: new Date().toISOString(), public: null };
  app.use(securityHeaders);
  app.use(stripPlatformHeaders);
  app.use(publicGuard);
  app.use(healthHandler(health));
  app.use(openapiGuard(keys, cfg.allowRemoteOpenapi));
  app.use(backupHandler(db, cfg.backupMaxBytes));
  app.useBodyParser('json', { limit: '2mb' });
  app.useBodyParser('urlencoded', { extended: true, limit: '2mb' });
  app.use(apiGuard(app.get(AuthService)));
  app.useStaticAssets(cfg.staticDir, { index: false, maxAge: '1h', setHeaders: (res, path) => {
    if (path.includes('/assets/')) res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
  } });
  if (!keys.current()) log.warn('没有开放接口密钥（COVEY_WEB_KEY_FILE 或 COVEY_WEB_OPENAPI_KEY）：/openapi 会拒绝所有请求');
  await app.init();
  // 不用 app.listen：回环（HTTP）和公网（HTTPS）两个服务器共用同一个 Express 应用，公网那个给请求标 coveyPublic
  const handler = app.getHttpAdapter().getInstance() as (req: IncomingMessage, res: ServerResponse) => void;
  const servers: Server[] = [];
  const loopback: Server = createHttp(handler);
  await listenOn(loopback, cfg.port, cfg.host);
  servers.push(loopback);
  log.log(`网页工作台（自托管）：http://${cfg.host}:${cfg.port}`);
  if (cfg.publicNames.length > 0) {
    const pub: PublicHealth = {
      host: cfg.publicHost, port: cfg.publicPort, names: cfg.publicNames,
      tls: cfg.tlsCert || cfg.tlsKey ? 'provided' : 'self-signed', fingerprint: '', not_after: '', listening: false, error: '',
    };
    health.public = pub;
    try {
      const tls: TlsMaterial = loadTls(cfg);
      pub.fingerprint = tls.fingerprint;
      pub.not_after = tls.notAfter.toISOString();
      const https: Server = createHttps({ cert: tls.cert, key: tls.key, minVersion: 'TLSv1.2' }, (req, res) => {
        (req as PublicRequest).coveyPublic = true;
        handler(req, res);
      });
      await listenOn(https, cfg.publicPort, cfg.publicHost);
      servers.push(https);
      pub.listening = true;
      log.log(`公网 HTTPS：https://${cfg.publicHost}:${cfg.publicPort}（${tls.mode === 'provided' ? '自己的证书' : '自签证书'}，指纹 ${tls.fingerprint}，到 ${pub.not_after.slice(0, 10)}）`);
      renewTls(cfg, https as unknown as SecureServer, pub, log);
    } catch (e) {
      pub.error = e instanceof Error ? e.message : String(e);
      log.error(`公网 HTTPS 没开：${pub.error}（本机回环照常）`);
    }
  }
  // 不用 Nest 的 enableShutdownHooks：它关完应用会重发信号结束进程，PGlite 来不及关库。这里先关应用、再关库、再退出
  let stopping = false;
  const stop = (why: string): void => {
    if (stopping) return;
    stopping = true;
    log.log(`停止：${why}`);
    setTimeout(() => process.exit(0), 8000).unref(); // 关不完也在 Manager 的 SIGKILL 之前退出
    void Promise.all(servers.map((sv) => closeServer(sv)))
      .then(() => app.close())
      .then(() => db.close())
      .catch((e: unknown) => log.error(`关闭出错：${String(e)}`))
      .then(() => process.exit(0));
  };
  process.once('SIGTERM', () => stop('SIGTERM'));
  process.once('SIGINT', () => stop('SIGINT'));
  followParent(stop);
}

/**
 * 进程一直开着时证书也不过期：每 tlsCheckSeconds（默认一天）再准备一次证书，指纹变了就 setSecureContext 就地换上，
 * 新连接用新证书，已有连接不断。自签的在离过期 30 天内重建（ensureSelfSigned 的规则）；自己的证书按文件重读（续期后自动换上）。
 * 出错只记日志、照用旧证书，/healthz 的 public.error 写原因，下次再试。
 */
function renewTls(cfg: ReturnType<typeof loadConfig>, server: SecureServer, pub: PublicHealth, log: Logger): void {
  const timer = setInterval(() => {
    try {
      const next: TlsMaterial = loadTls(cfg);
      pub.error = '';
      if (next.fingerprint === pub.fingerprint) return;
      server.setSecureContext({ cert: next.cert, key: next.key, minVersion: 'TLSv1.2' });
      pub.fingerprint = next.fingerprint;
      pub.not_after = next.notAfter.toISOString();
      log.log(`公网证书已换上新的：指纹 ${next.fingerprint}，到 ${pub.not_after.slice(0, 10)}`);
    } catch (e) {
      pub.error = `证书检查失败，照用旧证书：${e instanceof Error ? e.message : String(e)}`;
      log.error(pub.error);
    }
  }, cfg.tlsCheckSeconds * 1000);
  timer.unref();
}

/** 自己的证书（两个一起给）或在 COVEY_WEB_TLS_DIR 里保证有一张自签证书 */
function loadTls(cfg: ReturnType<typeof loadConfig>): TlsMaterial {
  if (cfg.tlsCert || cfg.tlsKey) {
    if (!cfg.tlsCert || !cfg.tlsKey) throw new Error('COVEY_WEB_TLS_CERT 和 COVEY_WEB_TLS_KEY 要一起给');
    return loadProvided(cfg.tlsCert, cfg.tlsKey);
  }
  return ensureSelfSigned(cfg.tlsDir, cfg.publicNames);
}

function listenOn(server: Server, port: number, host: string): Promise<void> {
  return new Promise((ok, fail) => {
    server.once('error', fail);
    server.listen(port, host, () => {
      server.off('error', fail);
      ok();
    });
  });
}

/** 关监听，并立刻断开空闲的长连接（浏览器的 keep-alive），不然 close 要等它们超时 */
function closeServer(server: Server): Promise<void> {
  return new Promise((ok) => {
    server.close(() => ok());
    server.closeIdleConnections();
  });
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
