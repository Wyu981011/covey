# 一键部署到你自己的妙搭

把 `web/` 部署成你飞书里的一个妙搭全栈应用，并写好 Covey 的网页配置。部署好以后，网页的网址、https 和飞书登录都由妙搭提供，人在外面用手机飞书点开就能用，不用自己准备服务器和域名。

## 要先有

1. **飞书企业开通了妙搭**，你能在妙搭里建全栈应用、开数据库。没有的话脚本第一步就会告诉你，改用自托管。
2. **本机有** `python3`（3.10 及以上）、`git`、`lark-cli`（`npm i -g @larksuite/cli`），以及 **npm 11 或更低**。
   - 妙搭的初始化（`lark-cli apps +init` 里用 npx 拉模板）还不认 npm 12 起的 `npm pack --json` 输出，会报“npm pack 未返回 filename”。
   - 脚本发现是 npm 12 会先停下：`npm i -g npm@11` 或把 npm 11 放到 PATH 前面后重跑即可。
   - 妙搭在云上构建，本机不用装网页的 Node 依赖。
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
9. 写 Covey 的网页配置 `web.json`（`base_url` 指向应用的 `/openapi`，`key_file` 指向密钥文件）

做完后在 Covey 这边打开网页工作台：服务清单里设 `COVEY_WEB=1` 和 `COVEY_WEB_CONFIG=<脚本打印的 web.json 路径>`，再重新注册服务（Covey `docs/configuration.md`「改开关三步」）。一两分钟内网页上就有你私聊里最近的话题。

## 生成的文件

默认都在 `<Covey 状态目录>/web/` 下（`--out-dir` 可改）：

| 文件 | 内容 |
| --- | --- |
| `miaoda-deploy.json` | 进度：应用 ID、做完了哪几步、最近一次发布。不含密钥 |
| `web-openapi.key` | 开放接口密钥，权限 600 |
| `web.json` | Covey 的网页配置 |
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
