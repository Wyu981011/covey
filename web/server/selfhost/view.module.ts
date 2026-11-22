import { Module } from '@nestjs/common';
import { SelfhostViewController } from './view.controller';

/** 单页应用的回退：根模块里放在最后，它的 `*` 路由要排在所有接口之后 */
@Module({ controllers: [SelfhostViewController] })
export class SelfhostViewModule {}
