-- 网页工作台的 10 张表（妙搭全栈应用的库）。由 deploy.py 执行，不要手工改了再执行。
--
-- 谁能看：
--   service_role（应用服务端：Covey 经开放接口推数据、取发件箱，网页 /api 背后的系统账号）全权；
--   登录用户只认主人：app.user_id 等于主人的妙搭用户 ID（<OWNER_UID>，部署时由 deploy.py 用
--   lark-cli apps +user-id-convert 换出来填进去）。只有 outbox（网页发出去的话）和附件两张表主人能写，
--   其余主人只能读；不给 anon，不给别的登录用户。
-- 平台约定：每张表带四个审计列（_created_at、_created_by、_updated_at、_updated_by）；表名不带 schema 前缀；
--   +db-execute 只在第一句是 BEGIN 时把整段当一个事务，所以 deploy.py 执行前会去掉整行注释，并检查首句是 BEGIN、末句是 COMMIT。
-- 重复执行安全：表和索引用 IF NOT EXISTS，策略先 DROP POLICY IF EXISTS 再建。
BEGIN;

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key varchar(128) NOT NULL UNIQUE,
  title text NOT NULL DEFAULT '',
  status varchar(16) NOT NULL DEFAULT '在做',
  rev varchar(64) NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at double precision NOT NULL DEFAULT 0,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE projects IS 'Covey 推来的专项';

CREATE TABLE IF NOT EXISTS topics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key varchar(128) NOT NULL UNIQUE,
  project_key varchar(128),
  number integer,
  title text NOT NULL DEFAULT '',
  state varchar(16) NOT NULL DEFAULT '空闲',
  unseen boolean NOT NULL DEFAULT false,
  rev varchar(64) NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at double precision NOT NULL DEFAULT 0,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE topics IS 'Covey 推来的话题（含管家和专项负责人）';
CREATE INDEX IF NOT EXISTS idx_topics_project_key ON topics(project_key);
CREATE INDEX IF NOT EXISTS idx_topics_state ON topics(state);
-- 快照增量（?since=）按它找变过的话题，页面开着时每秒一次（T876）
CREATE INDEX IF NOT EXISTS idx_topics_touched ON topics(_updated_at);

CREATE TABLE IF NOT EXISTS turns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key varchar(160) NOT NULL UNIQUE,
  topic_key varchar(128) NOT NULL,
  seq integer NOT NULL DEFAULT 0,
  role varchar(16) NOT NULL DEFAULT 'agent',
  status varchar(16) NOT NULL DEFAULT 'done',
  body text NOT NULL DEFAULT '',
  rev varchar(64) NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE turns IS 'Covey 推来的每一轮（你说的和它答的）';
CREATE INDEX IF NOT EXISTS idx_turns_topic_key ON turns(topic_key);
CREATE INDEX IF NOT EXISTS idx_turns_touched ON turns(_updated_at);

CREATE TABLE IF NOT EXISTS questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key varchar(160) NOT NULL UNIQUE,
  topic_key varchar(128) NOT NULL,
  turn_key varchar(160),
  state varchar(16) NOT NULL DEFAULT 'open',
  rev varchar(64) NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE questions IS 'Covey 推来的等你回答的问题';
CREATE INDEX IF NOT EXISTS idx_questions_topic_key ON questions(topic_key);
CREATE INDEX IF NOT EXISTS idx_questions_state ON questions(state);

CREATE TABLE IF NOT EXISTS outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seq bigserial,
  op_id varchar(64) NOT NULL UNIQUE,
  kind varchar(16) NOT NULL,
  topic_key varchar(128),
  project_key varchar(128),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  state varchar(16) NOT NULL DEFAULT 'new',
  message text NOT NULL DEFAULT '',
  acked_at TIMESTAMP(3) WITH TIME ZONE,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE outbox IS '网页发出的操作（说一句、答题、停止……），Covey 取走执行后回执';
CREATE INDEX IF NOT EXISTS idx_outbox_seq ON outbox(seq);
CREATE INDEX IF NOT EXISTS idx_outbox_state ON outbox(state);
CREATE INDEX IF NOT EXISTS idx_outbox_topic_key ON outbox(topic_key);

CREATE TABLE IF NOT EXISTS sync_state (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(64) NOT NULL UNIQUE,
  value jsonb NOT NULL DEFAULT '{}'::jsonb,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE sync_state IS '同步时间、设置页、用量等整块数据';

CREATE TABLE IF NOT EXISTS images (
  id varchar(64) PRIMARY KEY,
  mime varchar(32) NOT NULL,
  w integer NOT NULL DEFAULT 0,
  h integer NOT NULL DEFAULT 0,
  thumb_data bytea,
  full_data bytea,
  thumb_path text,
  full_path text,
  expires_at TIMESTAMP(3) WITH TIME ZONE NOT NULL,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE images IS 'Covey 推来的图片（一轮的缩略图和大图），消息之后 90 天过期；字节在妙搭文件存储（*_path），存不了时在 *_data';
CREATE INDEX IF NOT EXISTS idx_images_expires ON images(expires_at);
-- 2026-11-27 T876 之前建的库没有路径列：重套 schema.sql 时补上（见 migrations/20261127-t876-blobs.sql）
ALTER TABLE images ADD COLUMN IF NOT EXISTS thumb_path text;
ALTER TABLE images ADD COLUMN IF NOT EXISTS full_path text;

CREATE TABLE IF NOT EXISTS uploads (
  id varchar(32) PRIMARY KEY,
  name varchar(255) NOT NULL,
  mime varchar(128) NOT NULL,
  size bigint NOT NULL,
  parts integer NOT NULL,
  done boolean NOT NULL DEFAULT false,
  expires_at TIMESTAMP(3) WITH TIME ZONE NOT NULL,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE uploads IS '网页输入框传的附件（每个文件一行），传完 7 天后过期';
CREATE INDEX IF NOT EXISTS idx_uploads_expires ON uploads(expires_at);

CREATE TABLE IF NOT EXISTS upload_parts (
  upload_id varchar(32) NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
  n integer NOT NULL,
  data bytea,
  path text,
  bytes integer,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  PRIMARY KEY (upload_id, n)
);
COMMENT ON TABLE upload_parts IS '附件的分段（每段原始字节不超过 start 回的 part_bytes）；字节在妙搭文件存储（path），存不了时在 data';
ALTER TABLE upload_parts ADD COLUMN IF NOT EXISTS path text;
ALTER TABLE upload_parts ADD COLUMN IF NOT EXISTS bytes integer;
ALTER TABLE upload_parts ALTER COLUMN data DROP NOT NULL;

CREATE TABLE IF NOT EXISTS collabs (
  key varchar(128) PRIMARY KEY,
  integrator varchar(128) NOT NULL DEFAULT '',
  state varchar(24) NOT NULL DEFAULT 'open',
  rev text NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at double precision NOT NULL DEFAULT 0,
  _created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
  _updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  _updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
COMMENT ON TABLE collabs IS 'Covey 推来的协作（一次多参与者的往返：汇总方、协助方、每次咨询和答复）';
CREATE INDEX IF NOT EXISTS idx_collabs_integrator ON collabs(integrator);
CREATE INDEX IF NOT EXISTS idx_collabs_updated ON collabs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_collabs_touched ON collabs(_updated_at);

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE images ENABLE ROW LEVEL SECURITY;
ALTER TABLE uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE upload_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_bypass_policy ON projects;
DROP POLICY IF EXISTS service_role_bypass_policy ON topics;
DROP POLICY IF EXISTS service_role_bypass_policy ON turns;
DROP POLICY IF EXISTS service_role_bypass_policy ON questions;
DROP POLICY IF EXISTS service_role_bypass_policy ON outbox;
DROP POLICY IF EXISTS service_role_bypass_policy ON sync_state;
DROP POLICY IF EXISTS service_role_bypass_policy ON images;
DROP POLICY IF EXISTS service_role_bypass_policy ON uploads;
DROP POLICY IF EXISTS service_role_bypass_policy ON upload_parts;
DROP POLICY IF EXISTS service_role_bypass_policy ON collabs;
CREATE POLICY service_role_bypass_policy ON projects TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON topics TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON turns TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON questions TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON outbox TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON sync_state TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON images TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON uploads TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON upload_parts TO service_role USING (true);
CREATE POLICY service_role_bypass_policy ON collabs TO service_role USING (true);

DROP POLICY IF EXISTS "只有主人能看" ON projects;
DROP POLICY IF EXISTS "只有主人能看" ON topics;
DROP POLICY IF EXISTS "只有主人能看" ON turns;
DROP POLICY IF EXISTS "只有主人能看" ON questions;
DROP POLICY IF EXISTS "只有主人能看" ON sync_state;
DROP POLICY IF EXISTS "只有主人能看" ON images;
DROP POLICY IF EXISTS "只有主人能看" ON collabs;
DROP POLICY IF EXISTS "只有主人能读写" ON outbox;
DROP POLICY IF EXISTS "只有主人能读写" ON uploads;
DROP POLICY IF EXISTS "只有主人能读写" ON upload_parts;
CREATE POLICY "只有主人能看" ON projects AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON topics AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON turns AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON questions AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON sync_state AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON images AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能看" ON collabs AS PERMISSIVE FOR SELECT TO authenticated USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能读写" ON outbox AS PERMISSIVE FOR ALL TO authenticated
  USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>') WITH CHECK (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能读写" ON uploads AS PERMISSIVE FOR ALL TO authenticated
  USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>') WITH CHECK (current_setting('app.user_id', TRUE) = '<OWNER_UID>');
CREATE POLICY "只有主人能读写" ON upload_parts AS PERMISSIVE FOR ALL TO authenticated
  USING (current_setting('app.user_id', TRUE) = '<OWNER_UID>') WITH CHECK (current_setting('app.user_id', TRUE) = '<OWNER_UID>');

COMMIT;
