# Covey 网页工作台

Covey 的配套网页应用：私聊里的专项、话题、每一轮和等你回答的问题都在网页上看得到，也能在网页上说话、答题、停话题、开新话题、改设置。网页是主工作台，飞书管提醒和快速回复，两边读写同一份记录。能做什么、Covey 怎么和它同步，见 [docs/web.md](../docs/web.md)。

## 部署

| 你的情况 | 怎么部署 |
| --- | --- |
| 飞书企业开通了妙搭（能建全栈应用） | **一键部署到你自己的妙搭**（推荐）：网址、加密、飞书登录都由妙搭提供，人在外面用手机飞书点开就能用。见 [deploy/miaoda/README.md](deploy/miaoda/README.md) |
| 没有妙搭（个人版飞书、Lark 国际版），或想让数据只留在自己机器上 | 自托管：和 Covey 装在一起，正在做 |

一键部署到妙搭（先只看不做，确认后真做）：

```bash
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --dry-run
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --yes
```

## 谁能看

- 网页只给主人用：表从建好那一刻起就只有主人能读（发件和附件只有主人能写），应用的可见范围设成只有你。
- Covey 推数据、取发件箱走开放接口，密钥只存在本机的密钥文件里（权限 600），不进日志和配置以外的地方。
- 日志默认不记请求体和返回体（`.env` 的 `LOG_REQUEST_BODY`、`LOG_RESPONSE_BODY`），对话内容不进日志。

## 本地开发和检查

要 Node 22 及以上。在 `web/` 下：

```bash
npm ci
npm run lint                     # eslint、类型检查、stylelint
npm run test:collab              # 单测：scripts/*.test.mjs，一共 15 组，package.json 里 test: 开头的都是
npm run build:server             # 服务端（NestJS）构建到 dist/server
MIAODA_APP_TYPE=3 npm run build:client   # 前端（Vite + React）构建到 dist/client，和妙搭上的构建一致
```

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
| `licenses/` | 字体等第三方许可 |

## 许可

代码随 covey 仓库用 MIT 许可（见仓库根目录的 LICENSE）。字体 Inter、JetBrains Mono 是 SIL Open Font License 1.1，头像的来源见 [licenses/README.md](licenses/README.md)。依赖里的 `@lark-apaas/*` 是飞书妙搭发布在公开 npm 上的包。

## 维护说明

现阶段 `web/` 由维护者从网页工作台的开发仓库同步过来（同步时去掉平台元数据和模板残留、做脱敏核查）。要改网页，请提 issue 或 PR，合进开发仓库后会再同步到这里。
