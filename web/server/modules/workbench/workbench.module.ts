import { Logger, Module, ServiceUnavailableException } from '@nestjs/common';
import type { MiddlewareConsumer, NestModule } from '@nestjs/common';
import type { NextFunction, Request, Response } from 'express';
import { DRIZZLE_DATABASE, FileService } from '@lark-apaas/fullstack-nestjs-core';
import { WorkbenchController } from './workbench.controller';
import { WorkbenchOpenApiController } from './workbench.openapi.controller';
import { WorkbenchImagesService } from './workbench.images.service';
import { WorkbenchQueryService } from './workbench.query.service';
import { WorkbenchSyncService } from './workbench.sync.service';
import { WorkbenchUploadsService } from './workbench.uploads.service';
import { BlobPlace, PlatformBlobs, type FileServiceLike } from './workbench.blobs';
import { gated, GateBusy, inLane, laneOfPath, memory, type Executes } from './workbench.guard';
import { IMAGE_BLOBS, UPLOAD_BLOBS, WB_DB } from './workbench.tokens';

const log = new Logger('Workbench');

/** 内存到了 critical（workbench.guard.ts）时先让出来的页面请求：整份快照、统计、报告、搜索、取图、传附件。
 *  别的（增量快照、轮次、发件、回执、Covey 的推送和取件）照常，页面不至于整个打不开 */
const HEAVY = /\/api\/(snapshot$|stats$|search$|images\/|uploads|projects\/[^/]+\/report$)/u;

/** 每个请求进自己的车道（库查询的闸门按车道限并发）；内存 critical 时重请求回 503 */
function laneMiddleware(req: Request, res: Response, next: NextFunction): void {
  const path: string = (req.originalUrl || req.url || '').split('?')[0];
  const lane = laneOfPath(path);
  if (lane === 'page' && memory.pressure() === 'critical' && (HEAVY.test(path) && !(path.endsWith('/snapshot') && 'since' in (req.query ?? {})))) {
    res.status(503).setHeader('Retry-After', '5');
    res.json({ statusCode: 503, message: '服务端内存紧张，稍后再试' });
    return;
  }
  inLane(lane, () => next());
}

/** 平台的文件存储（妙搭）包成 BlobStore；自托管没有它（垫片里是个空类，没人提供），图片和附件照旧存库里 */
function blobsOf(fs: FileService | undefined, what: string): BlobPlace {
  const store = fs && typeof (fs as unknown as FileServiceLike).upload === 'function' ? new PlatformBlobs(fs as unknown as FileServiceLike) : null;
  if (!store) log.log(`${what}：没有文件存储，存本应用库`);
  return new BlobPlace(store, (m: string) => log.warn(m));
}

@Module({
  controllers: [WorkbenchController, WorkbenchOpenApiController],
  providers: [
    {
      provide: WB_DB,
      useFactory: (db: Executes): Executes => gated(db, undefined, undefined, (e: GateBusy) => new ServiceUnavailableException(e.message)),
      inject: [DRIZZLE_DATABASE],
    },
    { provide: IMAGE_BLOBS, useFactory: (fs?: FileService) => blobsOf(fs, '图片'), inject: [{ token: FileService, optional: true }] },
    { provide: UPLOAD_BLOBS, useFactory: (fs?: FileService) => blobsOf(fs, '附件'), inject: [{ token: FileService, optional: true }] },
    WorkbenchQueryService,
    WorkbenchSyncService,
    WorkbenchImagesService,
    WorkbenchUploadsService,
  ],
})
export class WorkbenchModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    consumer.apply(laneMiddleware).forRoutes('*');
  }
}
