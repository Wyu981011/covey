import { Body, Controller, Get, Post, Query, Res } from '@nestjs/common';
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
  SyncUpsertRequest,
  SyncUpsertResponse,
} from '@shared/api.interface';
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
  ) {}

  @Post('upsert')
  upsert(@Body() body: SyncUpsertRequest): Promise<SyncUpsertResponse> {
    return this.svc.upsert(body);
  }

  /** v19：一张图的一份（缩略图或大图） */
  @Post('image')
  image(@Body() body: ImageUploadRequest): Promise<{ ok: true }> {
    return this.images.upload(body);
  }

  /** v19：哪些图已经有了 */
  @Post('images/have')
  have(@Body() body: ImageHaveRequest): Promise<ImageHaveResponse> {
    return this.images.have(body);
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
