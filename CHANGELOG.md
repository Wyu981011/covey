# 更新记录 / Changelog

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。还没有发布过版本号，改动都记在 Unreleased 里。
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No version has been released yet; everything goes under Unreleased.

## [Unreleased]

### Added 新增

- 仓库门面：`CODE_OF_CONDUCT.md`、`CHANGELOG.md`、`THIRD_PARTY_NOTICES.md`；`pyproject.toml` 补全项目元数据。
- CI 增加网页工作台（`web/`）的检查和构建作业，测试矩阵加入 Python 3.13，并开启 Dependabot 每周检查 GitHub Actions 和 `web/` 的 npm 依赖。
- `scripts/README.md`：列出 `scripts/` 里每个脚本的用途，分使用者用和维护者用。
- Antigravity：扩展钩子 `agy_turn`。它可以给本机的每一轮定运行环境；某个 agy 进程因额度用完、限流或没登录而失败时，它给出另一个环境，这一轮就在那里接着同一个对话。核心不认识账号，几个 Google 账号怎么轮换由扩展决定（[docs/harnesses.md](docs/harnesses.md#antigravity)）。

### Changed 变更

- `scripts/setup_harness_bridge.sh` 标为已弃用，运行时在 stderr 提示改用 `./install`。
- 头像图片只在 `covey/assets/avatars/` 留一份，网页构建、开发和部署前由脚本拷入。
- `web/.env` 改名为 `web/.env.example`，构建和部署时按它生成 `.env`。
- 根目录和 `web/` 的 `.gitignore` 补上环境文件、密钥、构建产物和编辑器缓存。
- README 的快速开始补上 Node.js 和 npm 的前提。
- 网页工作台同步：全量补扫只重建输入变了、或网页还没收下的话题（任务和问题记录、话题自己的文件、看板分组、加入的专项、协作、回带、到点回来看、代发草稿），没变的不再整份重读；每个话题最迟 15–30 分钟仍重建一次兜底。传完的产物只在上传账本变了（重新上传）时重读（[docs/web.md](docs/web.md#推)）。

### Fixed 修复

- Python 3.13：产物路径是符号链接环时，仍按“无法解析”处理（3.13 的 `Path.resolve()` 不再抛错）。
- 网络盘上一个话题的 `topic.json` 读挂住时，不再挡住所有卡片点击和私聊消息：路由读 `topic.json`、别名和工作区列表不再持全局锁，话题编号读过一次就不再读盘（[docs/architecture.md](docs/architecture.md#主要记录与锁)）。

### Added (English)

- Project files: `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`; complete project metadata in `pyproject.toml`.
- CI: a job that lints, tests and builds the web workbench (`web/`), Python 3.13 in the test matrix, and weekly Dependabot checks for GitHub Actions and the npm dependencies of `web/`.
- `scripts/README.md`: what each script in `scripts/` is for, split into user and maintainer scripts.
- Antigravity: the `agy_turn` extension hook. It can give each turn on this machine its environment and, when an agy process fails on a spent quota, a limit or a sign-in, another one in which the same conversation goes on. The core knows no accounts; an extension decides how several Google accounts take turns ([docs/harnesses.md](docs/harnesses.md#antigravity)).

### Changed (English)

- `scripts/setup_harness_bridge.sh` is deprecated and says so on stderr; use `./install`.
- The avatar images live only in `covey/assets/avatars/`; scripts copy them into `web/` before its dev, build and deploy.
- `web/.env` is now `web/.env.example`; builds and deploys generate `.env` from it.
- `.gitignore` (root and `web/`) now covers environment files, keys, build output and editor caches.
- The README quick start lists Node.js and npm as requirements.
- Web workbench sync: the full pass builds again only a topic whose inputs changed (its job and question records, its own files, its board group, the projects it joined, collaborations, relays, 到点回来看 and drafts) or whose items the page has not taken; one that did not change is not read again, and every topic is still built again within 15-30 minutes. A settled upload's artifacts are read again only when its ledger changed (重新上传) ([docs/web.md](docs/web.md#推)).

### Fixed (English)

- Python 3.13: an artifact path that is a symlink loop is still reported as one that cannot be resolved (3.13's `Path.resolve()` no longer raises).
- A read of one topic's `topic.json` that hangs on the network disk no longer holds up every card click and private message: routes read `topic.json`, the aliases and the workspace list without a process-wide lock, and a topic's number is read from disk once ([docs/architecture.md](docs/architecture.md#主要记录与锁)).
