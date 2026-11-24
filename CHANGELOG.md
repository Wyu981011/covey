# 更新记录 / Changelog

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。还没发布的改动记在 Unreleased 里；每个版本先列中文，再列英文。
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Changes not yet released go under Unreleased; each release lists them in Chinese first, then in English.

## [Unreleased]

### Added 新增

- 专项负责人能单独选和换 Harness、模型、思考预算，和管家、话题一样：设置卡「配置」页多一段“专项负责人”（新建专项用它，默认跟管家一样），管家开专项时点名的优先；已有的专项点专项卡上的「换配置」，或在网页负责人的对话下面换。只列能接 Bridge 工具的 Harness，负责人在哪个上都只读，工作区不变（[docs/projects.md](docs/projects.md#负责人用哪个-harness)）。网页数据约定 v36。
- Pi 和 DeepSeek Harness 也能当管家和专项负责人：Pi 用它自带的 MCP 接 Bridge 工具，负责人那一轮只留 read、grep、find、ls；DeepSeek Harness 用自带的 `dsh-mcp-client`，负责人那一轮用 read-only 权限预设。核心的五个 Harness 在设置卡「配置」的管家、专项负责人两段都能选了。管家没选 Harness 时的顺序不变（Claude Code → Codex → Antigravity，然后才是它们）。

### Fixed 修复

- 网页工作台：输入框里 @ 一位名字很长的（长名字的专项负责人、长标题的话题），胶囊不再折成两行、撑高变形、右边空一块：名字只占一行，放不下就截断（话题截标题，负责人截专项名，T 号和“负责人”一直在），悬停看全名；胶囊和后面的字在同一条基线上，带胶囊的行和别的行一样高。手机上长胶囊不再把输入框撑出屏幕；你那句下面的去向放不下时换到下一行、名字太长截断，不再顶出气泡。

### Added (English)

- A project's lead chooses and changes its Harness, model and budget like the butler and a topic: the 设置 card's 配置 has a 专项负责人 section (new projects; follows the butler by default), a Harness the butler names when it opens a project comes first, and an existing lead changes through 换配置 on its 专项卡 or the web page. Only Harnesses that take the Bridge's tools are offered; the lead stays read-only and keeps its workspace. Web data contract v36.
- Pi and DeepSeek Harness can be the butler and a project's lead: Pi takes the Bridge's tools through its built-in MCP and a lead's turn keeps only read, grep, find and ls; DeepSeek Harness takes them through its bundled `dsh-mcp-client` and a lead's turn runs on its read-only permission preset. All five core Harnesses are on the 设置 card's butler and lead sections now; a butler with none named still falls back Claude Code, Codex, Antigravity first.

### Fixed (English)

- Web page: the composer's @ pill for a long name (the lead of a long-named project, a topic with a long title) no longer wraps into two lines, grows taller and leaves a gap on its right. The name stays on one line and is cut short when it has no room (a topic's title or a lead's project name; the T number and 负责人 always show), the full name shows on hover, the pill sits on the text's baseline, and a line with a pill is as tall as the others. On a phone a long pill no longer pushes the composer off the screen, and the route under your message moves to its own line and cuts long names instead of running out of the bubble.

## [0.1.0] - 2026-11-23

首个公开版本。功能介绍见 [README](README.md)；下面是发布前最后一段时间的改动。
First public release. [README.en.md](README.en.md) describes what Covey does; below are the changes of the last stretch before it.

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

- 定时回看（到点回来看）：话题归进专项（或升级成专项）时删掉它已有的预约；`revisits` 线程、看板和网页不再处理、展示不是普通话题的预约，并顺手删掉存量的；你亲自推进了一轮、约定的时间已过且没再约新的，旧预约也自动撤掉（时间没到的保留）。
- 网页工作台数据约定 v35：话题的 `revisit` 加 `set_at`、`running`，新操作 `revisit_cancel`；网页看板和话题总览的「Covey 定时回看」一行主语改成 Covey，带「取消」。飞书看板同样改成“Covey 将于 … 自动回看”。
- Python 3.13：产物路径是符号链接环时，仍按“无法解析”处理（3.13 的 `Path.resolve()` 不再抛错）。
- 网络盘上一个话题的 `topic.json` 读挂住时，不再挡住所有卡片点击和私聊消息：路由读 `topic.json`、别名和工作区列表不再持全局锁，话题编号读过一次就不再读盘（[docs/architecture.md](docs/architecture.md#主要记录与锁)）。
- 飞书 SDK 长连接收到的事件先落盘，处理完才删：Bridge 停止、重启或崩溃时还没处理完的消息和点击，下次启动时先接着处理，不会丢。
- 一轮结束后的收尾只由 Bridge 跑，而且只跑一次，任务进程不再自己跑；在重启间隙里结束的任务，下次启动时补上收尾。
- 记录存储读盘时不再持锁：网络盘上的读挂住时，别的请求先用上一次读到的结果回答，写也不再等读。
- 网页工作台同步：正在跑、在问、刚结束的话题一秒内到网页，不用等全量补扫；三个同步线程每一步都不再打开文件。

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

- 定时回看 (到点回来看): a topic that joins or becomes a project loses its revisit; the `revisits` thread, the 看板 and the web page no longer handle or show one of a topic that is not ordinary, and remove the ones already left; an owner's turn that ended done and set no new one also clears a revisit whose time has passed (one not yet due stays).
- Web data contract v35: a topic's `revisit` gains `set_at` and `running`, and a new `revisit_cancel` operation; the page's rows now say who looks ("Covey 将于 … 自动回看") and have a 取消 button; the Feishu 看板 says the same.
- Python 3.13: an artifact path that is a symlink loop is still reported as one that cannot be resolved (3.13's `Path.resolve()` no longer raises).
- A read of one topic's `topic.json` that hangs on the network disk no longer holds up every card click and private message: routes read `topic.json`, the aliases and the workspace list without a process-wide lock, and a topic's number is read from disk once ([docs/architecture.md](docs/architecture.md#主要记录与锁)).
- Events the Feishu SDK connection takes in stay on disk until they are handled: a message or click not yet handled when the Bridge stops, restarts or crashes is handled first at the next start, not lost.
- A turn's end runs in the Bridge only, and once; a task runner no longer runs it. A task that ends in a restart's gap gets its end at the next start.
- The record store holds no lock while it reads the disk: when a read hangs on a network disk, other requests answer from the last result, and a write never waits on a read.
- Web workbench sync: a topic that runs, asks or just ended reaches the page within a second, without waiting for the full pass; the three sync threads open no file on each step.

[Unreleased]: https://github.com/ericxk/covey/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ericxk/covey/releases/tag/v0.1.0
