/** workbench 模块里自己的注入令牌（T876）：过了闸门的库（workbench.guard.ts 的 gated），图片、附件各自的存放状态（workbench.blobs.ts） */
export const WB_DB = 'WORKBENCH_GATED_DB';
export const IMAGE_BLOBS = 'WORKBENCH_IMAGE_BLOBS';
export const UPLOAD_BLOBS = 'WORKBENCH_UPLOAD_BLOBS';
