import { Module } from '@nestjs/common';
import { WorkbenchController } from './workbench.controller';
import { WorkbenchOpenApiController } from './workbench.openapi.controller';
import { WorkbenchImagesService } from './workbench.images.service';
import { WorkbenchQueryService } from './workbench.query.service';
import { WorkbenchSyncService } from './workbench.sync.service';
import { WorkbenchUploadsService } from './workbench.uploads.service';

@Module({
  controllers: [WorkbenchController, WorkbenchOpenApiController],
  providers: [WorkbenchQueryService, WorkbenchSyncService, WorkbenchImagesService, WorkbenchUploadsService],
})
export class WorkbenchModule {}
