import { Global, Module } from '@nestjs/common';
import type { DynamicModule } from '@nestjs/common';
import { DRIZZLE_DATABASE } from './platform-shim';
import type { SelfhostDb } from './db';
import { STATIC_DIR } from './view.controller';

/** 库（PGlite 或外部 Postgres 的包装）和前端目录，全局可注入：workbench 的服务照旧 @Inject(DRIZZLE_DATABASE) */
@Global()
@Module({})
export class SelfhostDataModule {
  static forRoot(db: SelfhostDb, staticDir: string): DynamicModule {
    return {
      module: SelfhostDataModule,
      global: true,
      providers: [
        { provide: DRIZZLE_DATABASE, useValue: db },
        { provide: STATIC_DIR, useValue: staticDir },
      ],
      exports: [DRIZZLE_DATABASE, STATIC_DIR],
    };
  }
}
