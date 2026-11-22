import { Module } from '@nestjs/common';
import { AuthController } from './auth.controller';
import { AuthService } from './auth.service';

/** 登录：发起、轮询、会话列表、登出（一个文件一个模块：eslint 的 nestjs-typed 只认文件里的第一个模块） */
@Module({ controllers: [AuthController], providers: [AuthService], exports: [AuthService] })
export class SelfhostAuthModule {}
