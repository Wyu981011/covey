# 自托管：网页和 Covey 跑在同一台机器上

没有妙搭（个人版飞书、Lark 国际版），或想让数据只留在自己机器上时，用这一种。网页是一个 Node 进程，由 Covey 的 Manager 拉起和看护，只监听本机 `127.0.0.1`；Covey 通过回环地址推数据、取网页上的操作。登录不用账号密码：在网页上点“用飞书登录”，去飞书私聊里点「允许」。

和妙搭版是同一份代码（`web/`），只是构建入口不同：自托管构建不带任何妙搭平台的包，页面不加载平台的监控、埋点和水印脚本。

## 要先有

1. Covey 已经装好、在跑（`./install` 或手工安装），你能在飞书私聊里和机器人说话。
2. 本机有 **Node 22 以上**和 npm（只用来装依赖和构建；npm 12 也行）。
3. 磁盘约 1.5 GB（依赖约 1 GB）。

## 三步装好

在 Covey 代码目录里：

```bash
# 1. 构建：把 web/ 拷到一个新目录，装依赖、构建（第一次几分钟），最后打印 COVEY_WEB_SELFHOST_DIR
bash web/deploy/selfhost/build.sh /absolute/path/to/covey-web

# 2. 备好开放接口密钥和 Covey 的网页配置，并打印要设的开关
python3 -B -m covey.service.web_selfhost --dir /absolute/path/to/covey-web/dist-selfhost

# 3. 照第 2 步打印的开关改服务清单，重新注册服务（Covey docs/configuration.md「改开关三步」）
#    COVEY_WEB=1  COVEY_WEB_CONFIG=<数据根>/web/web.json  COVEY_WEB_SELFHOST=1  COVEY_WEB_SELFHOST_DIR=/absolute/path/to/covey-web/dist-selfhost
```

第 2 步写的东西都在 Covey 数据根的 `web/` 下（目录权限 700）：

| 文件 | 是什么 |
| --- | --- |
| `web-openapi.key` | 开放接口密钥，随机生成，权限 600；已经有就不覆盖 |
| `web.json` | Covey 的网页配置：`base_url` 是 `http://127.0.0.1:18650/openapi`，`key_file` 指上面的密钥，`page_url` 是飞书卡片上「打开网页」打开的地址 |
| `db/` | 网页的库（进程内 PGlite），网页进程第一次起来时建 |
| `logs/selfhost.log` | 网页进程的输出，超过 10 MB 轮转 |
| `database-url` | 可选：放一行外部 Postgres 的连接串就改用外部库，见下面「数据和备份」 |

端口不想用 18650：第 2 步加 `--port 18651`，开关里多设 `COVEY_WEB_SELFHOST_PORT=18651`。

重新注册服务后，Manager 几秒内拉起网页进程，`manager.log` 里有一行 `web selfhost started pid=… port=18650`；Bridge 一两分钟内把私聊里最近的话题推上去。

## 打开网页和登录

本机浏览器打开 `http://127.0.0.1:18650/`：

1. 点“用飞书登录”，网页显示 4 位对照码。
2. 飞书私聊里来一张「网页登录确认」卡，写着浏览器、系统、来源（本机浏览器和 ssh 转发来的写“本机”，经 Tailscale 或反向代理来的写对方地址）、对照码和发起时间。
3. 核对对照码和网页上的一样，点「允许」。网页几秒内自动进入看板。不是你发起的就点「不是我」。

- 登录 30 天有效，cookie 是 HttpOnly 的，页面脚本读不到。
- 设置页最下面「已登录的浏览器」列出每个登录过的浏览器；点「全部登出」后所有浏览器（包括当前这个）都要重新登录。
- 防刷卡：同一来源 30 秒内只能发起一次，同时等你确认的登录最多 5 个；确认卡 5 分钟内有效，过期再点什么也不做。
- 网页放到公网（反向代理）后，谁都能点“用飞书登录”让你收到确认卡：没在登录就点「不是我」，来源地址不认识也别点允许。

## 从别的设备打开

网页进程只听 `127.0.0.1`，别的设备直接连不上，这是故意的。按你的情况选一种：

| 情况 | 做法 | `page_url` 写什么 |
| --- | --- | --- |
| 偶尔用，自己的电脑能 ssh 到这台机器 | `ssh -N -L 18650:127.0.0.1:18650 <这台机器>`，然后在自己电脑上打开 `http://127.0.0.1:18650/` | 不用改 |
| 手机、电脑都想随时打开（推荐） | 两边都装 [Tailscale](https://tailscale.com/) 并登录同一个账号，在这台机器上 `tailscale serve --bg 18650`，打开它打印的 `https://<机器名>.<tailnet>.ts.net/` | 那个 `https://…ts.net/` 地址 |
| 有自己的域名和公网入口 | 用 Caddy、nginx 等反向代理到 `127.0.0.1:18650`，上 https（见下） | 你的 `https://` 域名 |

改 `page_url`：重跑第 2 步并加 `--page-url https://…/`（只改 `web.json` 里这一项，密钥不变），Bridge 下一次读配置就用新地址。

反向代理要点：

- 一定上 https。
- 把 `X-Forwarded-For`、`X-Forwarded-Proto` 传过去：网页进程只信本机来的这两个头，用它们认来源（频控按它）和 https（`X-Forwarded-Proto: https` 时登录 cookie 带 `Secure`）。
- `/openapi/` 不要对外：网页进程拒绝带转发头（经代理）来的 `/openapi` 请求，而且不管从哪来都要密钥；代理上再挡一道更稳。

```caddyfile
covey.example.com {
	@openapi path /openapi /openapi/*
	respond @openapi 403
	reverse_proxy 127.0.0.1:18650
}
```

```nginx
location /openapi/ { return 403; }
location / {
    proxy_pass http://127.0.0.1:18650;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}
```

不要把 18650 端口直接开到公网，也不要让网页进程听 `0.0.0.0`：那样登录 cookie 走明文。

## 谁能看

- 页面接口（`/api/*`）都要有效会话；会话只能靠飞书私聊里点「允许」换来。妙搭网关注入的身份头（`x-larkgw-*`）一律丢掉，伪造它没用。
- 页面的写请求要带 `x-covey-csrf: 1` 头，别的网站的页面带不了，跨站请求被拒。
- 开放接口（`/openapi/*`）只收本机直接来的请求，并且要带 `Authorization: Bearer <密钥>`（定长比较）。路径前缀不分大小写地拦（Express 的路由不分大小写，`/OPENAPI/…` 一样要密钥）。ssh 转发、不加转发头的 TCP 代理来的请求看起来也是本机来的，这时只靠密钥挡。密钥文件换了不用重启：网页进程按修改时间重读，Covey 读配置失败时也会重读。
- 库里只存登录令牌和会话令牌的 sha256，不存原值。

## 数据和备份

网页库里几乎都是 Covey 推上去的副本：专项、话题、每一轮、问题都以 Covey 的记录为准。

- **库坏了或删了**：停掉网页进程（关掉 `COVEY_WEB_SELFHOST` 或让进程退出），删 `<数据根>/web/db/`，进程重新起来时建空库；再删 Covey 状态目录里的 `web/sent.json` 并重启 Bridge，Bridge 会把所有内容重推一遍（不删的话最多一天后也会全量重推一次）。丢的只有登录会话（重新登录）和还没被 Covey 取走的几秒内的网页操作。
- **想备份**：备份 `<数据根>/web/` 即可（`web.json`、密钥和库）。库目录要在网页进程停着的时候拷，在跑时拷可能不一致。
- **用外部 Postgres**：把连接串写进 `<数据根>/web/database-url`（一行，权限 600，例如 `postgres://covey:密码@127.0.0.1:5432/covey`），让网页进程退出、Manager 拉起后就连外部库，表在第一次连上时自动建（和 `deploy/miaoda/schema.sql` 同样的 10 张表，加登录用的 `login_requests`、`web_sessions`）。备份用 `pg_dump`。手工运行时也可以直接设环境变量 `DATABASE_URL`。
- 同一个 `db/` 目录只能有一个网页进程打开：不要同时起两个。

## 升级

拉到新版 Covey 代码后：

```bash
bash web/deploy/selfhost/build.sh /absolute/path/to/covey-web --restart
```

它把新的 `web/` 拷过去重新构建（`package-lock.json` 没变时不重装依赖），然后让正在跑的网页进程退出，Manager 几秒内拉起新版。新加的表在进程起来时自动建。

## 排障

| 现象 | 先看 |
| --- | --- |
| 打不开 `http://127.0.0.1:18650/` | `manager.log` 里有没有 `web selfhost started`；`web selfhost not started: node 不在服务的 PATH 里` 是服务清单的 `PATH` 里没有 node；`… 不存在` 是 `COVEY_WEB_SELFHOST_DIR` 不对或没构建 |
| 进程反复退出 | `<数据根>/web/logs/selfhost.log` 的最后几行；端口被占用时换端口（第 2 步 `--port` 和开关一起改） |
| 点了“用飞书登录”私聊里没有卡 | Bridge 要开着 `COVEY_WEB=1` 且 `COVEY_WEB_CONFIG` 指向第 2 步的 `web.json`；`curl -s http://127.0.0.1:18650/api/me` 回 401 说明网页进程活着 |
| 卡上点了「允许」，卡写“没有送到网页” | 网页进程没在跑或密钥对不上（卡上写了原因），起来后再点一次 |
| 卡写“已失效” | 网页上这次登录已经过期或处理过了，在网页上重新点“用飞书登录” |

## 手工运行（不经 Manager）

```bash
cd /absolute/path/to/covey-web
COVEY_WEB_PORT=18650 COVEY_WEB_DB_DIR=/absolute/path/to/data/web/db COVEY_WEB_KEY_FILE=/absolute/path/to/data/web/web-openapi.key \
  node dist-selfhost/server/selfhost/main.js
```

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `COVEY_WEB_HOST` | `127.0.0.1` | 监听地址。Manager 固定用 `127.0.0.1` |
| `COVEY_WEB_PORT` | `18650` | 端口 |
| `COVEY_WEB_DB_DIR` | `./data/db` | PGlite 的数据目录 |
| `COVEY_WEB_KEY_FILE` | 空 | 开放接口密钥文件；没设时读 `COVEY_WEB_OPENAPI_KEY`；都没有时 `/openapi` 全部拒绝 |
| `DATABASE_URL`、`COVEY_WEB_DATABASE_URL_FILE` | 空 | 外部 Postgres 的连接串，或放连接串的文件；都没有就用 PGlite |
| `COVEY_WEB_STATIC_DIR` | `dist-selfhost/client` | 前端文件目录 |
| `COVEY_WEB_OPENAPI_ALLOW_REMOTE` | 空 | `1`：`/openapi` 也收非本机、经代理来的请求（仍要密钥）。Covey 和网页不在同一台机器时才用，前面必须是 https |
| `COVEY_WEB_PARENT_PID` | 空 | Manager 设成自己的 pid：Manager 不在了网页进程自己退出 |

## 开发和检查

在 `web/` 下（依赖装好后）：

```bash
npm run build:selfhost             # 服务端到 dist-selfhost/server，前端到 dist-selfhost/client
npm run test:selfhost-logic        # 纯逻辑：对照码、频控、cookie、密钥比较、配置
npm run test:selfhost-api          # 接口：起真服务（PGlite 临时目录），走完密钥、登录、会话、频控、登出
npm run start:selfhost             # 本地起服务（环境变量同上）
```

入口在 `server/selfhost/`（`main.ts`、登录 `auth.*.ts`、守卫 `guards.ts`、库 `db.ts`、表 `schema.ts`）和 `client/src/selfhost/`（登录页、已登录的浏览器、替代平台包的几个垫片）。`workbench` 的代码两种部署共用，不为自托管改：自托管入口把 `@lark-apaas/fullstack-nestjs-core` 指到本地垫片 `server/selfhost/platform-shim.ts`，其他 `@lark-apaas/*` 一律不加载。
