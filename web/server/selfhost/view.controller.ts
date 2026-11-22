import { Controller, Get, Inject, NotFoundException, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

export const STATIC_DIR = 'SELFHOST_STATIC_DIR';

/** 单页应用的回退：页面路径都给 index.html；/api、/openapi、/assets 下没有的是真的 404 */
@Controller()
export class SelfhostViewController {
  constructor(@Inject(STATIC_DIR) private readonly dir: string) {}

  @Get(['/', '*'])
  page(@Req() req: Request, @Res() res: Response): void {
    if (/^\/(api|openapi|assets)(\/|$)/iu.test(req.path)) throw new NotFoundException('没有这个接口');
    const index: string = join(this.dir, 'index.html');
    if (!existsSync(index)) throw new NotFoundException('前端还没构建：先 npm run build:selfhost');
    res.setHeader('Cache-Control', 'no-cache');
    res.sendFile(index);
  }
}
