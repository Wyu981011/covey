import { Body, Controller, Get, Inject, Post, Query, Res } from '@nestjs/common';
import type { Response } from 'express';
import type {
  ImageHaveRequest,
  ImageHaveResponse,
  ImageUploadRequest,
  InboxResponse,
  OpenUploadInfo,
  OpenUploadPart,
  SyncAckRequest,
  SyncAckResponse,
  SyncLimits,
  SyncUpsertRequest,
  SyncUpsertResponse,
} from '@shared/api.interface';
import type { BlobPlace } from './workbench.blobs';
import { bodyBytes, heapLimitMb, imageBytes, memLimitMb, rssMb } from './workbench.limits';
import { IMAGE_BLOBS, UPLOAD_BLOBS } from './workbench.tokens';
import { WorkbenchImagesService } from './workbench.images.service';
import { WorkbenchSyncService } from './workbench.sync.service';
import { WorkbenchUploadsService } from './workbench.uploads.service';
import { waitSeconds } from './workbench.wake';

/** 取件最多挂多久（秒）：Covey 带 wait 时的上限 */
const INBOX_WAIT_MAX = 10;

@Controller('openapi/sync')
export class WorkbenchOpenApiController {
  constructor(
    private readonly svc: WorkbenchSyncService,
    private readonly images: WorkbenchImagesService,
    private readonly uploads: WorkbenchUploadsService,
    @Inject(IMAGE_BLOBS) private readonly imageBlobs: BlobPlace,
    @Inject(UPLOAD_BLOBS) private readonly uploadBlobs: BlobPlace,
  ) {}

  /** v44：这个服务端的上限和内存读数（Covey 照它放大批次和图片；内存的数看 NODE_OPTIONS 生效没有） */
  private limits(): SyncLimits {
    const body: number = bodyBytes();
    return {
      body_bytes: body,
      image_bytes: imageBytes(body),
      store: this.imageBlobs.mode === 'file' && this.uploadBlobs.mode === 'file' ? 'file' : 'db',
      heap_limit_mb: heapLimitMb(),
      rss_mb: rssMb(),
      mem_limit_mb: memLimitMb(),
    };
  }

  @Post('upsert')
  async upsert(@Body() body: SyncUpsertRequest): Promise<SyncUpsertResponse> {
    return { ...(await this.svc.upsert(body)), limits: this.limits() };
  }

  /** v19：一张图的一份（缩略图或大图） */
  @Post('image')
  image(@Body() body: ImageUploadRequest): Promise<{ ok: true }> {
    return this.images.upload(body);
  }

  /** v19：哪些图已经有了 */
  @Post('images/have')
  async have(@Body() body: ImageHaveRequest): Promise<ImageHaveResponse> {
    return { ...(await this.images.have(body)), limits: this.limits() };
  }

  /** v44（T876）：把还只在库里（bytea）的历史图片搬进文件存储，一次最多 50 行。只手动调，Covey 不调。
   *  drop 不是 true 时只复制（bytea 留着，不丢）；drop=true 在读回核对大小以后才清 bytea */
  @Post('blobs/backfill')
  backfill(@Body() body: { limit?: number; drop?: boolean }): Promise<{ copied: number; dropped: number; left: number; errors: number; store: 'file' | 'db' }> {
    return this.images.backfill(Number(body?.limit ?? 20), body?.drop === true);
  }

  /** v20：输入框的一个附件（传完、没过期的才给；不带路径参数，方便给密钥按路由放行） */
  @Get('upload')
  upload(@Query('id') id?: string): Promise<OpenUploadInfo> {
    return this.uploads.info(id ?? '');
  }

  /** v20：附件的第 n 段（base64） */
  @Get('upload/part')
  uploadPart(@Query('id') id?: string, @Query('n') n?: string): Promise<OpenUploadPart> {
    return this.uploads.getPart(id ?? '', Number(n ?? -1));
  }

  @Get('inbox')
  inbox(@Res({ passthrough: true }) res: Response, @Query('after') after?: string, @Query('limit') limit?: string, @Query('wait') wait?: string): Promise<InboxResponse> {
    const a: number = Number(after ?? 0) || 0;
    const l: number = Math.min(Math.max(Number(limit ?? 100) || 100, 1), 500);
    // wait（秒，可选，≤10）：没有新操作时挂着等；Covey 断开了就不再等（响应还没发出就 close，是连接断了）
    let closed = false;
    res.once('close', () => { closed = true; });
    return this.svc.inbox(a, l, wait === undefined ? null : waitSeconds(wait, INBOX_WAIT_MAX) * 1000, () => closed);
  }

  @Post('ack')
  ack(@Body() body: SyncAckRequest): Promise<SyncAckResponse> {
    return this.svc.ack(body);
  }
}
