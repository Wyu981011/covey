# 更新记录 / Changelog

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。还没发布的改动记在 Unreleased 里；每个版本先列中文，再列英文。
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Changes not yet released go under Unreleased; each release lists them in Chinese first, then in English.

## [Unreleased]

### Added 新增

- 网页工作台：左侧栏和右栏（话题页的进度栏、专项页和看板的右栏）能拖动调宽，双击分界线回到默认，宽度记在这台浏览器上；字体参考 Codex 桌面版改成系统界面字体在前（Mac 上 SF Pro 和苹方，等宽 SF Mono；Windows 上 Segoe UI 和微软雅黑），网页自带的 Inter、JetBrains Mono 退为兜底，中文引号用中文字体画，粗体统一到 600。
- 专项负责人能单独选和换 Harness、模型、思考预算，和管家、话题一样：设置卡「配置」页多一段“专项负责人”（新建专项用它，默认跟管家一样），管家开专项时点名的优先；已有的专项点专项卡上的「换配置」，或在网页负责人的对话下面换。只列能接 Bridge 工具的 Harness，负责人在哪个上都只读，工作区不变（[docs/projects.md](docs/projects.md#负责人用哪个-harness)）。网页数据约定 v36。
- Pi 和 DeepSeek Harness 也能当管家和专项负责人：Pi 用它自带的 MCP 接 Bridge 工具，负责人那一轮只留 read、grep、find、ls；DeepSeek Harness 用自带的 `dsh-mcp-client`，负责人那一轮用 read-only 权限预设。核心的五个 Harness 在设置卡「配置」的管家、专项负责人两段都能选了。管家没选 Harness 时的顺序不变（Claude Code → Codex → Antigravity，然后才是它们）。
- 记忆自己长（`COVEY_MEMORY_LEARN=1`，要 `COVEY_MEMORY=1`）：一轮结束后 Bridge 自己读主人的话，引用核对过的长期要求直接记下（通用的、工作区的记成原则），答案卡上能“不对”；记下这一轮用到了哪几条，放不下时最近用过的先带；晚间汇总的“你反复说的”先生效（它总结的）；新增“整理记忆”，收起专项里办完的、被替代的、很久没用的当前决定（能撤销），把反复的选择提炼成约定；把 Codex、Claude Code 自己记的偏好收进候选；每轮的记忆块能用 `bin/covey_memory.py search` 按需查放不下的和答过的题。

### Fixed 修复

- 同一个任务不会再被两个任务进程跑：预先拉起的任务进程刚接手，Bridge 就当它没起来、2 秒后又起了一个，第二个在启动后端前因保存结果对不上失败，发出的失败卡占了回帖的幂等键，真正跑完的那个的回复被拦下（同事在 ByteFuse 上多次遇到）。现在 Bridge 先写好任务进程的 `runner.json` 再交接，任务进程看到写的是自己就不再写一遍；读 `runner.json` 一时失败会隔一会儿再读；看着像退出了，再起之前会再确认它真不在、任务真没开始（记录、`done.json`、保存结果都看），还活着就接着看，不会把它的任务标成中断；目录里有活着的任务进程时，不清它的文件、不再起第二个。
- 同时跑的任务数不再写死 10：默认 32，服务清单里设 `COVEY_MAX_WORKERS` 可改（最多 512）；其中 2 个名额只留给管家和专项负责人，普通话题占满其余的时私聊和专项照常回应。排队时“并发已满（最多 N 个任务）”写的就是这个数。
- 执行过程里 Antigravity 和 Codex 的每一步不再满屏是 `set -euo pipefail for v in http_proxy…`、光秃秃的 `schedule`：Antigravity 的命令写模型自己写的 toolSummary（agy 的流里没有，Bridge 从本机 agy 会话库里只读查出来），定时等待写回来做什么、多久以后；Codex 等没有说明字段的写命令第一行的 `# 注释`；都没有时显示去掉开头样板（strict 模式、清代理循环、赋值、cd、timeout、bash -c）以后真正在跑的命令。桥接规则要求 toolSummary 和这行注释用你的语言写。飞书任务卡、状态行和网页的过程一样。
- 代答话题和开了脱敏的一轮不再读写 Harness 自带的记忆：Claude Code 关自动记忆，Codex 关 memories 并把代答线程标成不进记忆，联系人的话不会变成其他会话里的规矩。
- 记忆核对“主人原话”时只认主人答的和补充的，不再把问题卡的题面当成他说的话（题面里的“要不要再”也不再当成纠正）。
- 网页工作台看板顶上写“N 件事要你处理 · N 停住了”，下面却一张停住了的卡都没有：专项的成员话题在看板上折进专项的格子，推给网页的 `board` 是空的。现在每个算进“要你处理”的停住了，网页都画成卡（看板起算以前停的也是）；手上的事置顶时，专项格子被 Pin 着显示别的话题，成员的停住了也照样列出来。开了 `COVEY_PROJECT_AUTOWAKE=1` 时，专项成员话题停住了归负责人（回执会叫醒它），看板、手上的事、早晚汇总和网页都不再算进“要你处理”；可能卡住照样算。
- 网页工作台：话题换了配置、下一轮还没跑时，输入框下沿那行和话题页页头不再把新的 Harness 和换之前那一轮的模型拼在一起（换到 Antigravity · Gemini 4 Neon 后显示“Antigravity · Opus”）；话题的模型和 Harness、工作区一样，取它现在绑的。
- 网页工作台：输入框里 @ 一位名字很长的（长名字的专项负责人、长标题的话题），胶囊不再折成两行、撑高变形、右边空一块：名字只占一行，放不下就截断（话题截标题，负责人截专项名，T 号和“负责人”一直在），悬停看全名；胶囊和后面的字在同一条基线上，带胶囊的行和别的行一样高。手机上长胶囊不再把输入框撑出屏幕；你那句下面的去向放不下时换到下一行、名字太长截断，不再顶出气泡。

### Added (English)

- Web page: the left sidebar and the right rails (a topic's progress rail, a project's and the board's) can be dragged wider or narrower, a double click on the divider restores the default, and the widths stay in the browser. Fonts follow the Codex desktop app: the system UI font first (SF Pro and PingFang with SF Mono on a Mac, Segoe UI and Microsoft YaHei on Windows), the bundled Inter and JetBrains Mono as fallbacks, Chinese quotation marks drawn in the Chinese font, and bold unified at 600.
- A project's lead chooses and changes its Harness, model and budget like the butler and a topic: the 设置 card's 配置 has a 专项负责人 section (new projects; follows the butler by default), a Harness the butler names when it opens a project comes first, and an existing lead changes through 换配置 on its 专项卡 or the web page. Only Harnesses that take the Bridge's tools are offered; the lead stays read-only and keeps its workspace. Web data contract v36.
- Pi and DeepSeek Harness can be the butler and a project's lead: Pi takes the Bridge's tools through its built-in MCP and a lead's turn keeps only read, grep, find and ls; DeepSeek Harness takes them through its bundled `dsh-mcp-client` and a lead's turn runs on its read-only permission preset. All five core Harnesses are on the 设置 card's butler and lead sections now; a butler with none named still falls back Claude Code, Codex, Antigravity first.
- Memory that learns by itself (`COVEY_MEMORY_LEARN=1`, with `COVEY_MEMORY=1`): after a turn the Bridge reads the owner's own words and writes down what he asks from now on (quote-checked; general and workspace ones as principles), with 不对 on the answer card; which lines a turn used is noted and orders what fits; the evening digest's repeated corrections take effect at once as 它总结的; a nightly 整理记忆 puts away a project's decisions that are done, replaced or unused (undoable) and distills rules from repeated choices; what Codex and Claude Code noted of the owner on their own comes in as candidates; a turn looks up what its memory block could not carry with `bin/covey_memory.py search`.

### Fixed (English)

- One job is never run by two task runners: right after a prestarted runner took its job, the Bridge could take it for one that never started and start a second one 2 s later; that one failed at the job's saved results before its backend started, and its failure card took the reply's idempotency key, so the reply of the runner that did finish was refused (seen several times on ByteFuse). The Bridge now writes a prestarted runner's `runner.json` before the handoff and the runner leaves a file that already names it alone; a read of `runner.json` that fails is made again a moment later; before a runner that looked gone is started again the Bridge asks once more whether it is gone and its job never began (the record, `done.json` and the saved results), and goes on watching one that is alive instead of marking its job interrupted; a run directory with a live runner keeps its files and gets no second runner.
- The tasks that run at once are no longer at most 10, written in: 32 by default, `COVEY_MAX_WORKERS` in the service's manifest sets it (at most 512); 2 of those slots are kept for the butler's and the projects' leads' turns, so ordinary topics filling the rest never keep the private chat or a project waiting. A queued task's "并发已满（最多 N 个任务）" says that number.
- 执行过程 of Antigravity and Codex turns no longer reads `set -euo pipefail for v in http_proxy…` step under step and a bare `schedule`: an Antigravity command leads with the toolSummary its model wrote (agy's stream leaves it out; the Bridge reads it, read only, from agy's conversation database on this machine), its timer says what it comes back to do and when; a command with no such field (Codex's) leads with the comment it begins with; without either a step reads as what it runs, past its wrappers and setup lines (strict mode, the proxy loop, assignments, cd, timeout, bash -c). The bridge rules ask for the toolSummary and that comment in the owner's language. The task card, its status line and the web page read alike.
- A 代答 turn and a redacted one no longer read or write the Harness's own memory: Claude Code's auto memory off, Codex's memories off and the 代答 thread marked out of them, so a contact's words never become a rule of other sessions.
- The memory's check of the owner's words takes only what he answered and added, never a question card's own words.
- The web page's board said "N things need you · N stopped" and drew no stopped card: a project's member topics are folded into the project's cell on the board, so their `board` was empty. Every stop 要你处理 counts is now a card on the page (one that ended before the board's rules too), and 手上的事's pinned board lists a member's stop while its project's pinned cell shows another thread. With `COVEY_PROJECT_AUTOWAKE=1` a member topic's stop is its lead's (its receipt wakes the lead): the 看板, 手上的事, 早晚汇总 and the web page no longer count it among 要你处理; a member that may be stuck still counts.
- Web page: after a topic's 换配置 and before its next turn, the line under the composer and the topic page's head no longer join the new Harness with the model of the turn before the switch ("Antigravity · Opus" after a switch to Antigravity · Gemini 4 Neon). A topic's model is the one it is bound to now, like its Harness and workspace.
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
