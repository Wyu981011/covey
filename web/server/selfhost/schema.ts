/**
 * 自托管库的表：和 deploy/miaoda/schema.sql 同样的 10 张业务表（没有妙搭的 user_profile 审计列和行级权限，
 * 谁能看由服务端的登录和开放接口密钥决定），再加登录用的 login_requests、web_sessions。
 * 都是 CREATE ... IF NOT EXISTS，每次启动执行一遍。
 */
const TS = 'timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP';

export const SCHEMA: string[] = [
  `CREATE TABLE IF NOT EXISTS projects (
    key varchar(128) PRIMARY KEY, title text NOT NULL DEFAULT '', status varchar(16) NOT NULL DEFAULT '在做',
    rev varchar(64) NOT NULL DEFAULT '', data jsonb NOT NULL DEFAULT '{}'::jsonb, updated_at double precision NOT NULL DEFAULT 0,
    _created_at ${TS}, _updated_at ${TS})`,
  `CREATE TABLE IF NOT EXISTS topics (
    key varchar(128) PRIMARY KEY, project_key varchar(128), number integer, title text NOT NULL DEFAULT '',
    state varchar(16) NOT NULL DEFAULT '空闲', unseen boolean NOT NULL DEFAULT false, rev varchar(64) NOT NULL DEFAULT '',
    data jsonb NOT NULL DEFAULT '{}'::jsonb, updated_at double precision NOT NULL DEFAULT 0,
    _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_topics_project_key ON topics(project_key)',
  'CREATE INDEX IF NOT EXISTS idx_topics_state ON topics(state)',
  `CREATE TABLE IF NOT EXISTS turns (
    key varchar(160) PRIMARY KEY, topic_key varchar(128) NOT NULL, seq integer NOT NULL DEFAULT 0,
    role varchar(16) NOT NULL DEFAULT 'agent', status varchar(16) NOT NULL DEFAULT 'done', body text NOT NULL DEFAULT '',
    rev varchar(64) NOT NULL DEFAULT '', data jsonb NOT NULL DEFAULT '{}'::jsonb, _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_turns_topic_key ON turns(topic_key, seq)',
  `CREATE TABLE IF NOT EXISTS questions (
    key varchar(160) PRIMARY KEY, topic_key varchar(128) NOT NULL, turn_key varchar(160), state varchar(16) NOT NULL DEFAULT 'open',
    rev varchar(64) NOT NULL DEFAULT '', data jsonb NOT NULL DEFAULT '{}'::jsonb, _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_questions_topic_key ON questions(topic_key)',
  'CREATE INDEX IF NOT EXISTS idx_questions_state ON questions(state)',
  `CREATE TABLE IF NOT EXISTS outbox (
    seq bigserial, op_id varchar(64) PRIMARY KEY, kind varchar(16) NOT NULL, topic_key varchar(128), project_key varchar(128),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb, state varchar(16) NOT NULL DEFAULT 'new', message text NOT NULL DEFAULT '',
    acked_at timestamptz(3), _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_outbox_seq ON outbox(seq)',
  'CREATE INDEX IF NOT EXISTS idx_outbox_state ON outbox(state)',
  `CREATE TABLE IF NOT EXISTS sync_state (
    name varchar(64) PRIMARY KEY, value jsonb NOT NULL DEFAULT '{}'::jsonb, _created_at ${TS}, _updated_at ${TS})`,
  `CREATE TABLE IF NOT EXISTS images (
    id varchar(64) PRIMARY KEY, mime varchar(32) NOT NULL, w integer NOT NULL DEFAULT 0, h integer NOT NULL DEFAULT 0,
    thumb_data bytea, full_data bytea, expires_at timestamptz(3) NOT NULL, _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_images_expires ON images(expires_at)',
  `CREATE TABLE IF NOT EXISTS uploads (
    id varchar(32) PRIMARY KEY, name varchar(255) NOT NULL, mime varchar(128) NOT NULL, size bigint NOT NULL, parts integer NOT NULL,
    done boolean NOT NULL DEFAULT false, expires_at timestamptz(3) NOT NULL, _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_uploads_expires ON uploads(expires_at)',
  `CREATE TABLE IF NOT EXISTS upload_parts (
    upload_id varchar(32) NOT NULL REFERENCES uploads(id) ON DELETE CASCADE, n integer NOT NULL, data bytea NOT NULL,
    _created_at ${TS}, _updated_at ${TS}, PRIMARY KEY (upload_id, n))`,
  `CREATE TABLE IF NOT EXISTS collabs (
    key varchar(128) PRIMARY KEY, integrator varchar(128) NOT NULL DEFAULT '', state varchar(24) NOT NULL DEFAULT 'open',
    rev text NOT NULL DEFAULT '', data jsonb NOT NULL DEFAULT '{}'::jsonb, updated_at double precision NOT NULL DEFAULT 0,
    _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_collabs_integrator ON collabs(integrator)',
  'CREATE INDEX IF NOT EXISTS idx_collabs_updated ON collabs(updated_at DESC)',
  // 登录：飞书点“允许”换一个浏览器会话。state：pending、approved、denied、used；库里只存令牌的 sha256
  `CREATE TABLE IF NOT EXISTS login_requests (
    id varchar(32) PRIMARY KEY, code varchar(8) NOT NULL, state varchar(12) NOT NULL DEFAULT 'pending',
    browser_hash varchar(64) NOT NULL, browser varchar(64) NOT NULL DEFAULT '', os varchar(64) NOT NULL DEFAULT '',
    ip varchar(64) NOT NULL DEFAULT '', expires_at timestamptz(3) NOT NULL, decided_at timestamptz(3),
    _created_at ${TS}, _updated_at ${TS})`,
  'CREATE INDEX IF NOT EXISTS idx_login_requests_state ON login_requests(state, expires_at)',
  `CREATE TABLE IF NOT EXISTS web_sessions (
    id varchar(32) PRIMARY KEY, token_hash varchar(64) NOT NULL UNIQUE, browser varchar(64) NOT NULL DEFAULT '',
    os varchar(64) NOT NULL DEFAULT '', ip varchar(64) NOT NULL DEFAULT '', expires_at timestamptz(3) NOT NULL,
    last_used_at ${TS}, _created_at ${TS}, _updated_at ${TS})`,
];
