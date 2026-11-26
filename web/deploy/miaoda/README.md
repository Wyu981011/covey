# 一键部署到你自己的妙搭

把 `web/` 部署成你飞书里的一个妙搭全栈应用，并写好 Covey 的网页配置。部署好以后，网页的网址、https 和飞书登录都由妙搭提供，人在外面用手机飞书点开就能用，不用自己准备服务器和域名。

## 要先有

1. **飞书企业开通了妙搭**，你能在妙搭里建全栈应用、开数据库。没有的话脚本第一步就会告诉你，改用自托管。
2. **本机有** `python3`（3.10 及以上）、`git`、`lark-cli`（`npm i -g @larksuite/cli`），以及 **npm 11 或更低**。
   - 妙搭的初始化（`lark-cli apps +init` 里用 npx 拉模板）还不认 npm 12 起的 `npm pack --json` 输出，会报“npm pack 未返回 filename”。
   - 脚本发现是 npm 12 会先停下：`npm i -g npm@11` 或把 npm 11 放到 PATH 前面后重跑即可。
   - 妙搭在云上构建，本机不用装网页的 Node 依赖。
   - **lark-cli 要认发布命令的 `--apply-reason`**（第 7 步 `apps +release-create` 会带它）。脚本不比版本号，开头先跑 `lark-cli apps +release-create --help` 看有没有这个参数，`--dry-run` 也会查。旧版没有：脚本在任何写操作之前就停下，退出码 2，提示本机 lark-cli 的版本，什么都不会建、不会推；运行 `lark-cli update`（或 `npm i -g @larksuite/cli@latest`）后重跑同一条命令。要是没有这一步，旧版会在第 3 步把代码推上去、到第 7 步才报 `unknown flag: --apply-reason`，留下“代码推了、没发布”的半截状态。脚本不会替你升级 lark-cli，也不会在旧版上去掉这个参数硬发。`--only-chat-tab` 不发布，不查。
3. **lark-cli 用你自己（Covey 的主人）的飞书账号登录过，且有妙搭权限**：

   ```bash
   lark-cli auth login --domain apps
   ```

   妙搭应用属于登录的人，部署出来的网页只认这个人。Covey 用的是哪个飞书应用都可以：lark-cli 和 Covey 用同一个应用时，脚本会核对登录的人就是 Covey 记的主人；不是同一个应用时，就按登录的人当主人并提示你确认。用非默认 profile 的话，登录和部署都加 `--profile <名字>`。
4. **Covey 的状态目录**（里面有 `bot-identity.json`，记着主人是谁）。不知道在哪，看 Covey 的 `docs/operations.md`「找到数据根」。

## 两步

```bash
# 只看不做：列出要做的事和每条命令，不调用任何会写入的接口
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --dry-run

# 真做
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --yes
```

脚本依次做：

1. 建全栈应用 “Covey 网页工作台”（`--name` 可改）
2. 开数据库
3. 拉应用的代码仓库，把 `web/` 覆盖进去（平台自己的文件保留，`client/`、`server/`、`shared/` 里的模板残留删掉），提交并推到 `sprint/default`
4. 建 10 张表，从建好那一刻起只有你能读（发件和附件只有你能写）；库是 dev/online 两套时，在 dev 建好后发布到 online
5. 把你的妙搭用户 ID 写进应用环境变量 `COVEY_OWNER_USER_ID`（dev 和 online），网页靠它认主人
6. 建开放接口密钥 `covey-sync`，只写进本机的密钥文件（权限 600），不打印
7. 发布，拿到线上地址
8. 可见范围设成只有你
9. 写 Covey 的网页配置 `web.json`（`base_url` 指向应用的 `/openapi`，`key_file` 指向密钥文件，`page_url` 是网页地址，飞书卡片上的「打开网页」用它）

10. 以**机器人身份**（`lark-cli --as bot`）在你和机器人的私聊顶栏建「工作台」标签，点开在飞书里内嵌打开网页（见下面的[私聊顶栏的「工作台」标签](#私聊顶栏的工作台标签)）。这一步做不成只提示，不影响前面 9 步

做完后在 Covey 这边打开网页工作台：服务清单里设 `COVEY_WEB=1` 和 `COVEY_WEB_CONFIG=<脚本打印的 web.json 路径>`，再重新注册服务（Covey `docs/configuration.md`「改开关三步」）。一两分钟内网页上就有你私聊里最近的话题。

## 私聊顶栏的「工作台」标签

发布拿到线上地址后，脚本读 `<Covey 状态目录>/owner-chat.json` 里的 `chat_id`（你和机器人私聊过一次就有），用机器人调飞书「会话标签页」接口：

- 没有「工作台」标签：`POST /open-apis/im/v1/chats/{chat_id}/chat_tabs` 建一个网址类型的标签，`tab_config.is_built_in` 为 `true`，飞书在窗口内嵌打开，不跳外部浏览器；
- 已经有：网址变了、或 `is_built_in` 不是 `true`，用 `.../chat_tabs/update_tabs` 原地更新；已经一致就什么都不做。重跑不会建出第二个。

**用哪个 profile。** 妙搭部署用你本人登录的 lark-cli profile（`--profile`），建标签要用 Covey 机器人自己的应用，可能不是同一个：脚本读 `<Covey 状态目录>/bot-identity.json` 的 `profile`（并核对那个 profile 的应用和 `app_id` 一致），认不出或对不上就不做并要你用 `--bot-profile <名字>` 指定，不会猜。

**权限。** 机器人的飞书应用要有 `im:chat.tabs:write_only`（操作群会话标签页，免审核）。它已在 Covey 的默认权限清单里：升级 Bridge 后「飞书应用待补」卡会提示补这一项，点「扫码自动补齐」就行（见 [docs/feishu-app.md](../../../docs/feishu-app.md)）。不另要 `im:chat.tabs:read`：建和更新的响应里就带会话当前全部标签；脚本先试着拉取现有标签（机器人能读群时多半成功），读不了就用进度文件里记的 `tab_id`，两样都没有才新建，建完发现同名旧标签会提醒你删多的。手工建过「工作台」标签、机器人又读不了标签时，加 `--tab-id <旧标签的 tab_id>` 避免建出第二个。

**降级。** 还没和机器人私聊过（没有 `owner-chat.json`）、机器人缺权限、接口报错或认不出 profile 时，脚本打印原因和补救命令，**不中断**部署、不改 `web.json`，退出码照旧。补齐后（或老部署第一次补建）单独做这一步，不碰妙搭：

```bash
# 看要做什么（不调标签接口）
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --only-chat-tab --dry-run
# 真做；网址取进度文件或 web.json，也可 --page-url 指定；--bot-profile、--chat-id、--tab-id 见 --help
python3 web/deploy/miaoda/deploy.py --covey-state /absolute/path/to/covey-state --only-chat-tab --yes
```

**位置。** 建/更新后，脚本用 `POST …/chat_tabs/sort_tabs` 把「工作台」排到「消息」后面（第 2 位，在 Pin、文件等之前）。该接口要求 `tab_ids` 含会话里**全部**标签的 ID（从左到右的顺序），「消息」标签固定第一；权限同样只要 `im:chat.tabs:write_only`。完整列表取自建/更新（或已一致时的拉取）的响应，所以不要读权限；只挪「工作台」，其余标签相对顺序不变，已经在第 2 位就不调。响应里没有完整列表、或排序报错时，脚本打印原因，标签保持原位，退出码仍是 0；之后用 `--only-chat-tab --yes` 补排。不想动位置加 `--keep-tab-order`。

不想要标签时加 `--skip-chat-tab`。

## 固定到飞书主导航

私聊顶栏的标签不需要这一步。想把工作台也固定到飞书左侧主导航（作为一个“网页应用”），要在 Covey 机器人那个飞书应用的开发者后台手工做（脚本结尾也会打印这几步）：

1. 应用能力 → 添加应用能力 → 添加「网页应用」。
2. 应用能力 → 网页应用 → 网页应用配置：「桌面端主页」和「移动端主页」都填脚本打印的网页地址（`page_url`）。不要加 `lk_jump_to_browser` 参数，否则会跳外部浏览器。
3. 版本管理与发布 → 创建版本并发布；租户要审核时等管理员通过，可用范围至少含你自己。
4. 发布后在飞书客户端的工作台里找到它，再固定到主导航（固定是客户端里的用户操作）。

**为什么不自动做。** 飞书开放接口里没有「添加应用能力」「设网页应用主页」；开发者后台自己的内部接口虽然能抓到（`feishu/app_console.py` 用无头浏览器以主人身份调的就是这类），但网页应用的那几个接口没有公开文档、没法在不发版的情况下验证，而它又必须建新版本并发布（还可能触发管理员审核）。所以默认不碰机器人的线上应用，只写手工步骤。

## 生成的文件

默认都在 `<Covey 状态目录>/web/` 下（`--out-dir` 可改）：

| 文件 | 内容 |
| --- | --- |
| `miaoda-deploy.json` | 进度：应用 ID、做完了哪几步、最近一次发布、私聊「工作台」标签的 `tab_id`。不含密钥 |
| `web-openapi.key` | 开放接口密钥，权限 600 |
| `web.json` | Covey 的网页配置：`base_url`（开放接口）、`key_file`、`page_url`（网页地址，飞书卡片上的「打开网页」按钮用它） |
| `repo/<应用 ID>/` | 应用代码仓库的本地副本 |

## 重跑和出错

- **重跑是安全的**：做过的步骤会跳过；代码没变、这一版也发布过，就不再发布。中途失败，修好原因后重跑，会接着往下做。
- **没有妙搭**（提示用不了这项妙搭能力）：这个飞书企业没开通妙搭全栈应用或数据库。找管理员开通，或改用自托管。
- **没权限或登录过期**：运行上面的 `lark-cli auth login --domain apps`，再重跑。
- **登录的不是主人**：妙搭应用属于登录的人，要用 Covey 主人的账号登录。
- **发布在等审批**（退出码 3）：你们企业的妙搭发布要审批。按提示找审批负责人，通过后重跑。
- **密钥文件丢了**：密钥只在创建时给一次。去妙搭后台重置 `covey-sync` 这把密钥，把新密钥写进密钥文件（权限 600）。
- **接手一个已有的应用**：`--app-id app_… --adopt-existing`。它会覆盖那个应用的代码、改它的库和可见范围，只用在你确定的应用上。库里已有部分表时，脚本会停下，确认后加 `--reapply-schema`。

## 建表脚本

`schema.sql` 是 10 张表的定义：

- 每张表带妙搭要求的四个审计列；
- 策略只有两类：应用服务端（service_role）全权，登录用户只认主人；
- `<OWNER_UID>` 由脚本换成你的妙搭用户 ID。

平台的 `+db-execute` 只在第一句是 `BEGIN` 时才把整段当一个事务，所以脚本执行前会去掉整行注释，并检查首句是 `BEGIN`、末句是 `COMMIT`。

## 测试

不连飞书，用假的 lark-cli 和本机的 git 仓库。在 covey 仓库根目录运行：

```bash
python3 -B -m unittest discover -s web/deploy/miaoda/tests
```
