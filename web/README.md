# Covey 网页工作台

Covey 的配套网页应用：私聊里的专项、话题、每一轮和等你回答的问题都在网页上看得到，也能在网页上说话、答题、停话题、开新话题、改设置。网页是主工作台，飞书管提醒和快速回复，两边读写同一份记录。能做什么、Covey 怎么和它同步，见 [docs/web.md](../docs/web.md)。

## 部署

| 你的情况 | 怎么部署 |
| --- | --- |
| 飞书企业开通了妙搭（能建全栈应用） | **一键部署到你自己的妙搭**（推荐）：网址、加密、飞书登录都由妙搭提供，人在外面用手机飞书点开就能用。见 [deploy/miaoda/README.md](deploy/miaoda/README.md) |
| 没有妙搭（个人版飞书、Lark 国际版），或想让数据只留在自己机器上 | **自托管**：网页和 Covey 跑在同一台机器上，由 Covey 的 Manager 看护，飞书私聊里点「允许」登录。本机直接打开，别的设备经 ssh 转发、Tailscale 或自己的 https 反向代理打开。见 [deploy/selfhost/README.md](deploy/selfhost/README.md) |

一键部署到妙搭（先只看不做，确认后真做）：

```bash
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --dry-run
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --yes
```

自托管（构建、备好密钥和配置，再按打印的开关改 Covey 的服务清单）：

```bash
bash web/deploy/selfhost/build.sh /absolute/path/to/covey-web
python3 -B -m covey.service.web_selfhost --dir /absolute/path/to/covey-web/dist-selfhost
```

## 谁能看

- 网页只给主人用。妙搭版：表从建好那一刻起就只有主人能读（发件和附件只有主人能写），应用的可见范围设成只有你。自托管版：页面接口都要会话，会话只能靠飞书私聊里点「允许」换来，伪造的平台身份头一律丢掉。
- Covey 推数据、取发件箱走开放接口，密钥只存在本机的密钥文件里（权限 600），不进日志和配置以外的地方。自托管版的开放接口只收本机直接来的请求。
- 日志默认不记请求体和返回体（`.env` 的 `LOG_REQUEST_BODY`、`LOG_RESPONSE_BODY`），对话内容不进日志。

## 本地开发和检查

要 Node 22 及以上。在 `web/` 下：

```bash
npm ci
npm run lint                     # eslint、类型检查、stylelint
npm run test:collab              # 单测：scripts/*.test.mjs，package.json 里 test: 开头的都是（见下）
npm run build:server             # 妙搭版服务端（NestJS）构建到 dist/server
MIAODA_APP_TYPE=3 npm run build:client   # 妙搭版前端（Vite + React）构建到 dist/client，和妙搭上的构建一致
npm run build:selfhost           # 自托管版：服务端和前端构建到 dist-selfhost/
```

单测一共 22 组 223 条：工作台 19 组 175 条（`test:graph` 到 `test:v34`），自托管 3 组 48 条（`test:selfhost-logic` 12 条，纯逻辑；`test:selfhost-tls` 10 条，公网 HTTPS 的证书；`test:selfhost-api` 26 条，先构建自托管服务端，再起真服务把密钥、登录、会话、频控、登出和公网 HTTPS 走一遍）。

部署脚本的测试（不连飞书，用假的 lark-cli 和本机 git 仓库），在 covey 仓库根目录：

```bash
python3 -B -m unittest discover -s web/deploy/miaoda/tests
```

## 目录

| 目录 | 是什么 |
| --- | --- |
| `client/` | 前端：`client/src/cv/` 是工作台的页面和组件，`client/src/components/ui/` 是基础组件 |
| `server/` | 服务端：`server/modules/workbench/` 是网页的 `/api` 和给 Covey 的 `/openapi/sync/*` |
| `shared/` | 前后端共用的类型和数据约定（和 Covey 的 `core/web_sync.py` 对应） |
| `scripts/` | 单测，以及妙搭平台生成的构建、启动脚本（`build.sh`、`run.sh` 等） |
| `deploy/miaoda/` | 一键部署到妙搭：`deploy.py`、建表 `schema.sql`、测试 |
| `deploy/selfhost/` | 自托管：构建脚本 `build.sh` 和说明；服务端入口在 `server/selfhost/`，前端的登录页和垫片在 `client/src/selfhost/` |
| `licenses/` | 字体等第三方许可 |

## 许可

代码随 covey 仓库用 MIT 许可（见仓库根目录的 LICENSE）。字体 Inter、JetBrains Mono 是 SIL Open Font License 1.1，头像的来源见 [licenses/README.md](licenses/README.md)。依赖里的 `@lark-apaas/*` 是飞书妙搭发布在公开 npm 上的包。

## 维护说明

`web/` 是网页工作台唯一的源码：改网页就改这里，提 issue 或 PR 都行。部署到妙搭时由 `deploy/miaoda/deploy.py` 把这里的代码推到你自己应用的仓库，不要反过来在应用仓库里改；自托管由 `deploy/selfhost/build.sh` 从这里构建。两种部署共用 `client/src/cv/` 和 `server/modules/workbench/`：改它们时两种构建都要过（`build:server`、`MIAODA_APP_TYPE=3 build:client`、`build:selfhost`）。
