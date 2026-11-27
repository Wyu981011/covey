-- T876（数据约定 v44）：图片和附件的字节放妙搭文件存储，库里只存路径；快照增量按 _updated_at 找变过的话题。
-- 只加列和索引，不动已有数据；新网页在没跑这段的库上照旧把字节存进 bytea（自动退回），跑完以后新的图片和附件才进文件存储。
-- 已有的妙搭部署：在 dev 环境执行，再发布到 online（多环境应用 online 禁 DDL）：
--   lark-cli apps +db-execute --app-id <应用> --environment dev --sql - --yes < migrations/20261127-t876-blobs.sql
--   lark-cli apps +db-env-diff --app-id <应用>        # 只应看到这几列、两个索引和 upload_parts.data 可空
--   lark-cli apps +db-env-migrate --app-id <应用> --yes
-- 撤回（新网页照样能用，退回 bytea）：ALTER TABLE images DROP COLUMN thumb_path, DROP COLUMN full_path; 等，
--   有路径、没有 bytea 的行要先回迁（或等它们 90 天过期），否则那些图读不到。
BEGIN;
ALTER TABLE images ADD COLUMN IF NOT EXISTS thumb_path text;
ALTER TABLE images ADD COLUMN IF NOT EXISTS full_path text;
ALTER TABLE upload_parts ADD COLUMN IF NOT EXISTS path text;
ALTER TABLE upload_parts ADD COLUMN IF NOT EXISTS bytes integer;
ALTER TABLE upload_parts ALTER COLUMN data DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_topics_touched ON topics(_updated_at);
CREATE INDEX IF NOT EXISTS idx_turns_touched ON turns(_updated_at);
COMMIT;
