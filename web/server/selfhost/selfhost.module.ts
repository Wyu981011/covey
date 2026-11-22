import { Module } from '@nestjs/common';
import type { DynamicModule } from '@nestjs/common';
import { APP_FILTER } from '@nestjs/core';
import { GlobalExceptionFilter } from '../common/filters/exception.filter';
import { WorkbenchModule } from '../modules/workbench/workbench.module';
import { SelfhostAuthModule } from './auth.module';
import { SelfhostDataModule } from './data.module';
import type { SelfhostDb } from './db';
import { SelfhostViewModule } from './view.module';

/** 自托管的根模块：数据、登录、workbench 的现有模块，最后是页面回退 */
@Module({})
export class SelfhostAppModule {}

export function selfhostAppModule(db: SelfhostDb, staticDir: string): DynamicModule {
  return {
    module: SelfhostAppModule,
    imports: [SelfhostDataModule.forRoot(db, staticDir), SelfhostAuthModule, WorkbenchModule, SelfhostViewModule],
    providers: [{ provide: APP_FILTER, useClass: GlobalExceptionFilter }],
  };
}
