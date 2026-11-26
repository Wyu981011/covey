#!/usr/bin/env python3
"""把 web/ 一键部署成你自己飞书里的一个妙搭全栈应用，并写好 Covey 的网页配置。只用标准库。

一次做完（每步做过就记进进度文件，重跑时跳过；不记任何密钥）：
  1. 建全栈应用（+create），或接着用进度文件里那个
  2. 开数据库（+features / +feature-enable）
  3. 拉应用的代码仓库（+init），把 web/ 覆盖进去，提交并推到 sprint/default
  4. 建表（schema.sql，主人 ID 用 +user-id-convert 换出来填进去）；多环境的应用在 dev 建好后发布到 online
  5. 写应用环境变量 COVEY_OWNER_USER_ID（dev 和 online）
  6. 建开放接口密钥（+openapi-key-create），只写进密钥文件（权限 600），不打印
  7. 发布（+release-create / +release-get），拿到线上地址
  8. 可见范围设成只有你（+access-scope-set）
  9. 写 Covey 的网页配置（web.json：base_url、key_file、page_url），告诉你怎么在 Covey 里打开 COVEY_WEB
  10. 在你和机器人的私聊顶栏建（或原地更新）「工作台」标签，飞书内嵌打开网页；这一步以机器人身份做，失败只提示、不影响前面的结果

用法：
  python3 web/deploy/miaoda/deploy.py --covey-state <Covey 状态目录> --dry-run     # 先看要做什么，不调任何接口
  python3 web/deploy/miaoda/deploy.py --covey-state <Covey 状态目录> --yes         # 真做
常用参数：--profile（lark-cli 的 profile，默认用 lark-cli 的默认 profile）、--out-dir（web.json、密钥和进度文件放哪，默认 <状态目录>/web）、
  --name（应用名）、--app-id + --adopt-existing（接手一个已有的应用；会覆盖它的代码，慎用）。
只补建私聊标签（老部署、或第 10 步当时没做成）：加 --only-chat-tab（见 main 里的参数说明）。
退出码：0 做完；1 某一步失败；2 前提不满足（没登录、缺命令、lark-cli 太旧不认发布的 --apply-reason、参数不对）；3 发布在等审批。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE.parent.parent                      # web/
SCHEMA = HERE / "schema.sql"
BRANCH = "sprint/default"
KEY_NAME = "covey-sync"
TABLES = ("projects", "topics", "turns", "questions", "outbox", "sync_state", "images", "uploads", "upload_parts", "collabs")
# 覆盖进应用仓库时不带的：部署脚本自己、依赖和构建产物
OVERLAY_SKIP = ("deploy", "node_modules", "dist", "README.md", "licenses")
# 头像和 .env：.gitignore 把它们挡在 git 之外（头像从核心拷来，.env 从 .env.example 生成），但应用仓库里要有，所以强制 add
FORCED = ("client/src/cv/avatars", ".env")
# 这几个目录是网页自己的代码，应用仓库里多出来的文件（模板残留）删掉；其余目录只覆盖不删，平台的文件留着
MIRROR_DIRS = ("client", "server", "shared")
RELEASE_WAIT_SECONDS = 900
OWNER_UID_RE = re.compile(r"^\d{6,32}$")


class StepFailed(Exception):
    """某一步失败：message 给人看，code 是退出码。"""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class Ctx:
    args: argparse.Namespace
    out_dir: Path
    state_path: Path
    state: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    bot_profile: str = ""  # 建标签用的机器人 profile，只在内存里

    def save(self) -> None:
        if self.args.dry_run:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1))
        os.replace(tmp, self.state_path)


def say(msg: str) -> None:
    print(msg, flush=True)


# ---------- lark-cli ----------

def cli(ctx: Ctx, *argv: str, stdin: str | None = None, write: bool = False, cwd: Path | None = None) -> dict:
    """跑一条 lark-cli apps 命令，返回 JSON 信封。写命令在 --dry-run 下只打印不跑。"""
    cmd = ["lark-cli", *argv, "--as", "user", "--format", "json"]
    if ctx.args.profile:
        cmd += ["--profile", ctx.args.profile]
    shown = " ".join(cmd)
    ctx.log.append(shown)
    if ctx.args.dry_run and write:
        say(f"  [不执行] {shown}")
        return {"ok": True, "data": {}, "dry_run": True}
    proc = subprocess.run(cmd, input=stdin, text=True, capture_output=True, cwd=cwd)
    env = parse_envelope(proc.stdout) or parse_envelope(proc.stderr) or {}
    if proc.returncode != 0 or env.get("ok") is False:
        raise StepFailed(explain(argv, env, proc), 2 if is_auth_error(env) else 1)
    return env


def parse_envelope(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):  # +init 的 stderr 是进度行，最后一行才是 JSON
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def is_auth_error(env: dict) -> bool:
    err = env.get("error") or {}
    return err.get("subtype") in {"missing_scope", "token_expired", "not_logged_in", "unauthorized"}


def explain(argv: tuple, env: dict, proc: subprocess.CompletedProcess) -> str:
    err = env.get("error") or {}
    sub = err.get("subtype") or ""
    what = " ".join(a for a in argv[:2])
    if sub == "missing_scope" or is_auth_error(env):
        return f"{what}：没有妙搭权限或登录过期。先运行 `lark-cli auth login --domain apps`（用你自己的飞书账号），再重跑本脚本。"
    if sub == "feature_not_available":
        return (f"{what}：这个飞书企业现在用不了这项妙搭能力（{err.get('message') or '服务端说不支持'}）。"
                "多半是没开通妙搭全栈应用或数据库；可以找管理员开通，或者改用自托管（见 web/README.md）。")
    msg = err.get("message") or (proc.stderr or proc.stdout or "").strip()[-400:]
    hint = err.get("hint") or ""
    return f"{what} 失败：{msg}" + (f"（提示：{hint}）" if hint else "")


def data(env: dict) -> dict:
    d = env.get("data")
    return d if isinstance(d, dict) else {}


# ---------- 步骤 ----------

def step_preflight(ctx: Ctx) -> None:
    for tool in ("lark-cli", "git"):
        if not shutil.which(tool):
            raise StepFailed(f"找不到 {tool}：先装好它（lark-cli 用 `npm i -g @larksuite/cli`）。", 2)
    if not (WEB / "package.json").is_file() or not SCHEMA.is_file():
        raise StepFailed(f"{WEB} 不像 covey 仓库的 web/ 目录。", 2)
    require_release_reason()  # 第 7 步的发布命令要认 --apply-reason：旧 lark-cli 在这里停，别等代码推上去了才报 unknown flag
    status = subprocess.run(["lark-cli", "auth", "status", "--json"] + (["--profile", ctx.args.profile] if ctx.args.profile else []),
                            text=True, capture_output=True)
    st = parse_envelope(status.stdout) or {}
    user = ((st.get("identities") or {}).get("user") or {})
    me = user.get("openId") or user.get("open_id") or ""
    if not me:
        raise StepFailed("lark-cli 还没用你的飞书账号登录：运行 `lark-cli auth login --domain apps`（用了 --profile 就两处都加）后重跑。", 2)
    if ctx.args.owner_open_id and ctx.args.owner_open_id != me:
        raise StepFailed("lark-cli 登录的不是 Covey 的主人（和 --owner-open-id 不一致）：妙搭应用属于登录的人，请用主人的账号登录。", 2)
    ident = read_identity(ctx.args.covey_state)
    if ident.get("owner") and ident.get("app_id") == st.get("appId") and ident["owner"] != me:
        raise StepFailed("lark-cli 登录的不是 Covey 的主人：妙搭应用属于登录的人，请用主人的账号登录。", 2)
    if ident.get("owner") and ident.get("app_id") != st.get("appId"):
        say("提示：lark-cli 用的飞书应用和 Covey 的不是同一个，open_id 没法直接对；按 lark-cli 登录的人当主人，请确认这就是你自己。")
    owner = me
    ctx.state["owner_open_id"] = owner


def lark_cli_output(*argv: str, timeout: int = 10) -> str | None:
    """跑一条 lark-cli 命令，返回 stdout 加 stderr；起不来或超时返回 None。"""
    try:
        proc = subprocess.run(["lark-cli", *argv], text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def require_release_reason() -> None:
    """发布命令（apps +release-create）不认 --apply-reason 的旧 lark-cli，在任何写操作之前停下（退出码 2）。
    看 --help 里有没有这个参数，不比版本号。核心的 covey/feishu/transport.py release_reason_support 有同样的探测
    （诊断用，这个脚本要能脱离 covey 包单独跑，所以各留一份）：改一处要改两处。"""
    shown = lark_cli_output("apps", "+release-create", "--help", timeout=30)
    if shown is None:  # Not an old lark-cli: one that did not answer (a busy machine), so say that, not "too old".
        raise StepFailed("lark-cli 30 秒内没回答 `lark-cli apps +release-create --help`，没法确认它的发布命令认不认 --apply-reason，"
                         "所以停在最前面，什么都没做。机器不忙时重跑这条命令。", 2)
    if "--apply-reason" in shown:
        return
    found = re.search(r"\d+(?:\.\d+)+\S*", lark_cli_output("--version") or "")
    raise StepFailed(f"本机 lark-cli（版本 {found.group(0) if found else '未知'}）的发布命令不支持 --apply-reason，第 7 步发布会失败，所以停在最前面，什么都没做。"
                     "运行 `lark-cli update`（或 `npm i -g @larksuite/cli@latest`）后重跑这条命令。", 2)


def read_identity(state_dir: str | None) -> dict:
    """Covey 记的主人和飞书应用（<状态目录>/bot-identity.json 的 owner、app_id）；open_id 按应用区分，只有同一个应用才能直接比。"""
    if not state_dir:
        return {}
    try:
        data = json.loads((Path(state_dir) / "bot-identity.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def step_app(ctx: Ctx) -> None:
    a = ctx.args
    if a.app_id and a.app_id != ctx.state.get("app_id"):
        if not a.adopt_existing:
            raise StepFailed("给了 --app-id，但进度文件里没有它：这个应用不是本脚本建的。要接手它（会覆盖它的代码、改它的库和可见范围），"
                             "再加 --adopt-existing。", 2)
        ctx.state["app_id"] = a.app_id
        ctx.state["adopted"] = True
    if ctx.state.get("app_id"):
        if not a.dry_run:
            app = (data(cli(ctx, "apps", "+get", "--app-id", ctx.state["app_id"])).get("app") or {})
            if app.get("app_type") not in (None, "", "full_stack"):
                raise StepFailed(f"应用 {ctx.state['app_id']} 不是全栈应用（{app.get('app_type')}）。", 2)
        say(f"1. 应用：用已有的 {ctx.state['app_id']}")
        return
    env = cli(ctx, "apps", "+create", "--app-type", "full_stack", "--name", a.name,
              "--description", "Covey 的网页工作台：在网页上看专项、话题和每一轮，也能说话、答题、改设置", write=True)
    app_id = (data(env).get("app") or {}).get("app_id") or ("app_dryrun" if a.dry_run else "")
    if not app_id:
        raise StepFailed("建应用成功了但没拿到 app_id，去妙搭后台看一眼再用 --app-id … --adopt-existing 接着做。")
    ctx.state["app_id"] = app_id
    ctx.state["created_at"] = int(time.time())
    ctx.save()
    say(f"1. 应用：新建了 {app_id}")


def step_database(ctx: Ctx) -> None:
    app = ctx.state["app_id"]
    if ctx.state.get("database"):
        say("2. 数据库：已开")
        return
    if not ctx.args.dry_run:
        feats = data(cli(ctx, "apps", "+features", "--app-id", app)).get("features") or []
        db = next((f for f in feats if isinstance(f, dict) and f.get("name") == "database"), None)
        if db is None:
            raise StepFailed("这个应用没有数据库能力（+features 里没有 database）：去妙搭后台给它加上数据库，或改用自托管。")
        if db.get("enabled"):
            ctx.state["database"] = True
            ctx.save()
            say("2. 数据库：原来就开着")
            return
    cli(ctx, "apps", "+feature-enable", "--feature", "database", "--app-id", app, write=True)
    ctx.state["database"] = True
    ctx.save()
    say("2. 数据库：开好了")


def step_code(ctx: Ctx) -> None:
    app = ctx.state["app_id"]
    work = ctx.out_dir / "repo"
    repo = work / app
    if ctx.args.dry_run:
        say(f"3. 代码：[不执行] 在 {work} 下 lark-cli apps +init --app-id {app} --dir {app}，覆盖 web/，git commit，git push origin {BRANCH}")
        return
    if not (repo / ".spark" / "meta.json").is_file():
        major = npm_major()
        if major >= 12:
            raise StepFailed(f"本机是 npm {major}：妙搭的初始化（lark-cli apps +init 里用 npx 拉模板）还不认 npm 12 起的 `npm pack --json` 输出，"
                             "会报“npm pack 未返回 filename”。先临时换 npm 11 或更低（如 `npm i -g npm@11`，或把 npm 11 放到 PATH 前面）再重跑，"
                             "已建好的应用会接着用。", 2)
        if repo.exists():  # 上次 +init 半路失败留下的目录：挪开，不删
            repo.rename(repo.with_name(f"{app}.failed-{int(time.time())}"))
        work.mkdir(parents=True, exist_ok=True)
        cli(ctx, "apps", "+init", "--app-id", app, "--dir", app, write=True, cwd=work)
    git(repo, "checkout", BRANCH)
    git(repo, "pull", "--ff-only", "origin", BRANCH, retry_credentials=ctx)
    sync_avatars()
    overlay(WEB, repo)
    git(repo, "add", "-A")
    git(repo, "add", "-f", "--", *FORCED)
    if git(repo, "status", "--porcelain").strip():
        # 应用仓库自带的提交前检查用的是模板装的依赖（+init 只装模板的），我们多出来的依赖（@tiptap 等）会被当成找不到而误报；
        # 同样的 lint、类型检查和单测已在 web/ 上跑过，所以这里跳过它。妙搭构建时会按我们的 package.json 装全依赖。
        git(repo, "-c", "user.name=Covey 部署", "-c", "user.email=covey-deploy@users.noreply.github.com",
            "commit", "-q", "--no-verify", "-m", f"部署 Covey 网页工作台（web/ {web_revision()}）")
        git(repo, "push", "origin", f"HEAD:{BRANCH}", retry_credentials=ctx)
        ctx.state["code_changed"] = True
    else:
        ctx.state["code_changed"] = False
    ctx.state["commit"] = git(repo, "rev-parse", "HEAD").strip()
    ctx.save()
    say(f"3. 代码：{'推上去了' if ctx.state['code_changed'] else '没有变化'}（{ctx.state['commit'][:8]}）")


def npm_major() -> int:
    try:
        out = subprocess.run(["npm", "--version"], text=True, capture_output=True, timeout=30).stdout.strip()
        return int(out.split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def web_revision() -> str:
    try:
        return subprocess.run(["git", "-C", str(WEB), "rev-parse", "--short", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "本地"


def git(repo: Path, *argv: str, retry_credentials: Ctx | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *argv], text=True, capture_output=True)
    if proc.returncode != 0 and retry_credentials is not None:  # 平台的 git 凭证过期：刷新一次再试
        cli(retry_credentials, "apps", "+git-credential-init", "--app-id", retry_credentials.state["app_id"], write=True)
        proc = subprocess.run(["git", "-C", str(repo), *argv], text=True, capture_output=True)
    if proc.returncode != 0:
        raise StepFailed(f"git {' '.join(argv[:2])} 失败：{(proc.stderr or proc.stdout).strip()[-400:]}")
    return proc.stdout


def sync_avatars() -> None:
    """头像只有核心 covey/assets/avatars/ 一份，web/client/src/cv/avatars/ 是从它拷来的；覆盖进应用仓库前先拷一遍。"""
    proc = subprocess.run(["node", str(WEB / "scripts" / "sync-avatars.mjs")], text=True, capture_output=True)
    if proc.returncode != 0:
        raise StepFailed(f"拷头像失败：{(proc.stderr or proc.stdout).strip()[-400:]}（要在 covey 仓库里的 web/ 跑本脚本）", 2)


def overlay(src: Path, repo: Path) -> None:
    """把 web/ 覆盖进应用仓库：client、server、shared 三个目录照 web/ 镜像（删模板残留），其余只覆盖不删。
    .env 不拷 web/ 里的（本机的 .env 是各人自己的），用 .env.example 生成应用仓库的 .env。"""
    for top in MIRROR_DIRS:
        ours = {p.relative_to(src).as_posix() for p in (src / top).rglob("*") if p.is_file()}
        theirs = [p for p in (repo / top).rglob("*") if p.is_file()] if (repo / top).is_dir() else []
        for p in theirs:
            if p.relative_to(repo).as_posix() not in ours:
                p.unlink()
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if rel.parts[0] in OVERLAY_SKIP or rel.parts[0].startswith("dist") or not path.is_file():
            continue
        if rel.parts[0].startswith(".env"):
            continue
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
    example = src / ".env.example"
    if example.is_file():
        shutil.copy2(example, repo / ".env")
    for top in MIRROR_DIRS:
        for d in sorted((p for p in (repo / top).rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()


def render_schema(owner_uid: str) -> str:
    if not OWNER_UID_RE.match(owner_uid):
        raise StepFailed("换出来的妙搭用户 ID 不像一个 ID（应是一串数字），停下没建表。")
    lines = [ln for ln in SCHEMA.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("--")]
    sql = "\n".join(lines).replace("<OWNER_UID>", owner_uid) + "\n"
    if not sql.startswith("BEGIN;") or not sql.rstrip().endswith("COMMIT;"):
        raise StepFailed("schema.sql 去掉注释后第一句要是 BEGIN、最后一句要是 COMMIT（平台只这样才整段一个事务）。")
    if re.search(r"<[A-Z_]+>", sql):
        raise StepFailed("schema.sql 里还有没填的占位符。")
    return sql


def owner_uid(ctx: Ctx) -> str:
    if ctx.state.get("owner_uid_known") and ctx.args.dry_run:
        return "0" * 16
    if ctx.args.dry_run:
        say("  [不执行] lark-cli apps +user-id-convert --convert-type open-id-to-miaoda --ids <主人的 open_id>")
        return "0" * 16
    env = cli(ctx, "apps", "+user-id-convert", "--convert-type", "open-id-to-miaoda", "--ids", ctx.state["owner_open_id"])
    items = data(env).get("items") or []
    uid = str((items[0] or {}).get("target_id") or "") if items else ""
    if not uid:
        raise StepFailed("没换出主人的妙搭用户 ID（+user-id-convert 落到了 missed）：确认 lark-cli 登录的是主人本人。")
    return uid


def step_schema(ctx: Ctx, uid: str) -> None:
    app = ctx.state["app_id"]
    if ctx.state.get("schema"):
        say("4. 建表：已建")
        return
    sql = render_schema(uid)
    if not ctx.args.dry_run:
        listed = data(cli(ctx, "apps", "+db-table-list", "--app-id", app, "--page-size", "100"))
        names = {str(t.get("name") or t.get("table_name") or "") for t in (listed.get("items") or listed.get("tables") or []) if isinstance(t, dict)}
        have = [t for t in TABLES if t in names]
        if len(have) == len(TABLES) and not ctx.args.reapply_schema:
            ctx.state["schema"] = True
            ctx.save()
            say("4. 建表：10 张表都在了，跳过（要按 schema.sql 重新套一遍策略，加 --reapply-schema）")
            return
        if have and not ctx.state.get("adopted") and not ctx.args.reapply_schema:
            raise StepFailed(f"库里已经有一部分表（{', '.join(have)}），不像新应用：先去妙搭后台看一眼；确认要按 schema.sql 补齐，加 --reapply-schema。")
    cli(ctx, "apps", "+db-execute", "--app-id", app, "--sql", "-", "--yes", stdin=sql, write=True)
    migrated = publish_schema(ctx)
    ctx.state["schema"] = True
    ctx.save()
    say("4. 建表：建好了" + ("，已从 dev 发布到 online" if migrated else ""))


def publish_schema(ctx: Ctx) -> bool:
    """多环境的应用：建表落在 dev，要发布到 online。单库应用 +db-env-diff 会报不支持，当作不用发布。"""
    if ctx.args.dry_run:
        say(f"  [不执行] lark-cli apps +db-env-diff / +db-env-migrate --app-id {ctx.state['app_id']} --yes（只有多环境的应用才需要）")
        return False
    try:
        diff = cli(ctx, "apps", "+db-env-diff", "--app-id", ctx.state["app_id"])
    except StepFailed as exc:
        if re.search(r"多环境|multi.?env|single|not.*(enabled|initiali[sz]ed)|单库", str(exc), re.I):
            return False
        raise
    changes = data(diff).get("changes") or diff.get("changes") or []
    if not changes:
        return False
    cli(ctx, "apps", "+db-env-migrate", "--app-id", ctx.state["app_id"], "--yes", write=True)
    return True


def step_env(ctx: Ctx, uid: str) -> None:
    app = ctx.state["app_id"]
    if ctx.state.get("env"):
        say("5. 环境变量：已写")
        return
    cli(ctx, "apps", "+env-set", "--app-id", app, "--environment", "dev", "--key", "COVEY_OWNER_USER_ID", "--value", "-", stdin=uid, write=True)
    cli(ctx, "apps", "+env-set", "--app-id", app, "--environment", "online", "--key", "COVEY_OWNER_USER_ID", "--value", "-", "--yes",
        stdin=uid, write=True)
    ctx.state["env"] = True
    ctx.save()
    say("5. 环境变量：COVEY_OWNER_USER_ID 写好了（dev、online）")


def step_key(ctx: Ctx) -> None:
    app = ctx.state["app_id"]
    key_file = Path(ctx.args.key_file) if ctx.args.key_file else ctx.out_dir / "web-openapi.key"
    ctx.state["key_file"] = str(key_file)
    if ctx.state.get("key") and key_file.is_file():
        say(f"6. 开放接口密钥：已有（{key_file}）")
        return
    if not ctx.args.dry_run:
        keys = data(cli(ctx, "apps", "+openapi-key-list", "--app-id", app)).get("items") or []
        if any(isinstance(k, dict) and k.get("name") == KEY_NAME for k in keys) and not key_file.is_file():
            raise StepFailed(f"应用里已有名为 {KEY_NAME} 的密钥，但本机的密钥文件 {key_file} 不在了（密钥只在创建时给一次）。"
                             f"要么找回那个文件，要么在妙搭后台重置这个密钥后，把新密钥写进 {key_file}（权限 600）。")
    env = cli(ctx, "apps", "+openapi-key-create", "--app-id", app, "--name", KEY_NAME, "--scope-all", write=True)
    secret = str(data(env).get("api_key") or "")
    if ctx.args.dry_run:
        say(f"6. 开放接口密钥：[不执行] 建好后只写进 {key_file}（权限 600），不打印")
        return
    if not secret:
        raise StepFailed("建了密钥但没拿到原文（只在创建时给一次）：去妙搭后台重置这个密钥，把新密钥写进密钥文件。")
    write_secret(key_file, secret)
    ctx.state["key"] = True
    ctx.save()
    say(f"6. 开放接口密钥：建好了，只写进了 {key_file}（权限 600）")


def write_secret(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".key-")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, secret.encode() + b"\n")
    finally:
        os.close(fd)
    os.replace(tmp, path)


def step_release(ctx: Ctx) -> None:
    app = ctx.state["app_id"]
    done = ctx.state.get("release") or {}
    if done.get("status") == "finished" and done.get("commit") == ctx.state.get("commit") and not ctx.args.dry_run:
        say(f"7. 发布：这一版已发布过（{done.get('online_url') or '地址见妙搭后台'}）")
        return
    env = cli(ctx, "apps", "+release-create", "--app-id", app, "--branch", BRANCH,
              "--apply-reason", "部署 Covey 网页工作台：专项、话题、每一轮和问题的网页视图", write=True)
    if ctx.args.dry_run:
        say(f"7. 发布：[不执行] 之后 lark-cli apps +release-get --app-id {app} --release-id <id> 轮询到 finished")
        return
    rel = data(env)
    release_id = str(rel.get("release_id") or "")
    status, info = str(rel.get("status") or ""), rel
    deadline = time.time() + ctx.args.release_wait
    while status not in ("finished", "failed") and release_id:
        node = (info.get("current_node_info") or {}) if isinstance(info, dict) else {}
        if node.get("current_status") == "PENDING":
            url = ((node.get("result") or {}).get("approval_url") or "")
            ctx.state["release"] = {"release_id": release_id, "status": "pending_approval", "commit": ctx.state.get("commit")}
            ctx.save()
            raise StepFailed("7. 发布在等审批负责人处理（这个企业的妙搭发布要审批）。" + (f"审批入口：{url}（点之前核对域名）。" if url.startswith("https://") else "")
                             + "审批通过后重跑本脚本，会接着往下做。", 3)
        if time.time() > deadline:
            raise StepFailed(f"7. 发布 {release_id} 超过 {ctx.args.release_wait} 秒还没完成；稍后重跑本脚本会接着查。")
        time.sleep(ctx.args.poll_seconds)
        got = data(cli(ctx, "apps", "+release-get", "--app-id", app, "--release-id", release_id))
        info = got.get("release") if isinstance(got.get("release"), dict) else got
        status = str(info.get("status") or "")
    if status != "finished":
        logs = info.get("error_logs") if isinstance(info, dict) else None
        raise StepFailed(f"7. 发布失败（{release_id}）：" + (json.dumps(logs, ensure_ascii=False)[:600] if logs else "服务端没给原因，去妙搭后台看发布记录。"))
    online_url = str(info.get("online_url") or "")
    ctx.state["release"] = {"release_id": release_id, "status": "finished", "online_url": online_url, "commit": ctx.state.get("commit")}
    ctx.save()
    say(f"7. 发布：完成（{online_url or '地址见妙搭后台'}）")


def step_scope(ctx: Ctx) -> None:
    if ctx.state.get("scope"):
        say("8. 可见范围：已是只有你")
        return
    targets = json.dumps([{"type": "user", "id": ctx.state["owner_open_id"]}])
    cli(ctx, "apps", "+access-scope-set", "--app-id", ctx.state["app_id"], "--scope", "specific", "--targets", targets, write=True)
    ctx.state["scope"] = True
    ctx.save()
    say("8. 可见范围：设成了只有你")


def base_url(online_url: str, app_id: str) -> str:
    m = re.match(r"^(https://[^/]+)(/.*)?$", online_url or "")
    if not m:
        return ""
    return f"{m.group(1)}/app/{app_id}/openapi"


def step_config(ctx: Ctx) -> None:
    path = Path(ctx.args.web_config) if ctx.args.web_config else ctx.out_dir / "web.json"
    online = (ctx.state.get("release") or {}).get("online_url") or ""
    url = base_url(online, ctx.state["app_id"])
    if ctx.args.dry_run:
        say(f"9. Covey 配置：[不执行] 写 {path}：base_url 由发布后的线上地址推出（https://<域名>/app/<应用 ID>/openapi），page_url 是线上地址本身，key_file 指向密钥文件")
        return
    if not url:
        raise StepFailed("发布完成了，但没拿到线上地址，推不出 base_url：在妙搭后台看应用地址，按 web/README.md 手写 web.json。")
    # page_url：飞书卡片上「打开网页」按钮打开的地址（Covey core/web_sync.py 的 page_url）
    cfg = {"base_url": url, "key_file": ctx.state["key_file"], "push_seconds": 1, "poll_seconds": 1, "page_url": online}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    ctx.state["web_config"] = str(path)
    ctx.save()
    say(f"9. Covey 配置：写好了 {path}")
    say("\n最后一步（在 Covey 这边）：服务清单里设 COVEY_WEB=1 和 COVEY_WEB_CONFIG=" + str(path)
        + "，再重新注册服务（docs/configuration.md「改开关三步」）。一两分钟内网页上就有你私聊里最近的话题。")
    say(f"网页地址：{online}")


# ---------- 私聊顶栏的「工作台」标签 ----------
# 接口（飞书开放平台「会话标签页」，以机器人身份调；下面的结论来自官方文档，未在现网会话上实测）：
#   POST /open-apis/im/v1/chats/{chat_id}/chat_tabs              添加；权限 im:chat 或 im:chat.tabs:write_only
#   POST /open-apis/im/v1/chats/{chat_id}/chat_tabs/update_tabs  更新（要 tab_id）；同上
#   GET  /open-apis/im/v1/chats/{chat_id}/chat_tabs/list_tabs    拉取；权限 im:chat、im:chat.tabs:read 或 im:chat:readonly 之一
# 建和更新的响应里都带会话当前的全部标签（含 tab_id、tab_content.url），所以最小权限只加 im:chat.tabs:write_only，
# 不另加 im:chat.tabs:read：幂等靠三层——先试拉取（机器人已有 im:chat:read 之类能读群的权限时多半能读）；
# 读不了就用进度文件里记的 tab_id（或 --tab-id）直接更新；两样都没有才建，建完看响应里有没有同名的旧标签并提醒。
#   POST /open-apis/im/v1/chats/{chat_id}/chat_tabs/sort_tabs   排序；权限同上。请求体 {"tab_ids": [...]} 必须含会话里全部标签的 ID，
#        顺序就是从左到右；「消息」标签固定第一、不参与排序，但 ID 也要在里面。建/更新的响应里的标签列表是按当前顺序给的完整列表，
#        所以排序不需要读权限：把响应里的 ID 取出来，只把「工作台」挪到「消息」后面（第 2 位），其余相对顺序不变。已经在第 2 位就不调。
# 标签是网址类型，tab_config.is_built_in 必须是 true，飞书才在客户端内嵌打开，不跳外部浏览器。
TAB_NAME = "工作台"
TAB_SCOPE = "im:chat.tabs:write_only"
TAB_PATH = "/open-apis/im/v1/chats/{chat}/chat_tabs"


class TabSkip(Exception):
    """建标签这一步做不下去：message 给人看。不是错误，不改退出码。"""


def tab_rerun(ctx: Ctx) -> str:
    a = ctx.args
    parts = ["python3 web/deploy/miaoda/deploy.py"]
    parts.append(f"--covey-state {a.covey_state}" if a.covey_state else "--covey-state <Covey 状态目录>")
    if a.bot_profile:
        parts.append(f"--bot-profile {a.bot_profile}")
    parts.append("--only-chat-tab --yes")
    return " ".join(parts)


def tab_error(env: dict, proc: subprocess.CompletedProcess) -> tuple[str, bool]:
    """(给人看的原因, 是不是缺权限)。"""
    err = env.get("error") or {}
    code = err.get("code") if err else env.get("code")
    msg = str(err.get("message") or env.get("msg") or (proc.stderr or proc.stdout or "").strip()[-300:])
    low = (msg + " " + str(err.get("subtype") or "")).lower()
    scope = err.get("subtype") == "missing_scope" or code in (99991672, 99991679) or "scope" in low or "permission" in low or "权限" in msg
    return (f"{msg}（错误码 {code}）" if code else msg), scope


def bot_api(ctx: Ctx, method: str, path: str, body: dict | None = None) -> dict:
    """以机器人身份调一次飞书接口，返回响应里的 data；失败抛 TabFailed（带是否缺权限）。"""
    cmd = ["lark-cli", "api", method, path, "--as", "bot", "--format", "json"]
    if body is not None:
        cmd += ["--data", json.dumps(body, ensure_ascii=False)]
    if ctx.bot_profile:
        cmd += ["--profile", ctx.bot_profile]
    ctx.log.append(" ".join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True)
    env = parse_envelope(proc.stdout) or parse_envelope(proc.stderr) or {}
    code = env.get("code")
    if proc.returncode != 0 or env.get("ok") is False or env.get("error") or (code not in (None, 0)):
        reason, scope = tab_error(env, proc)
        raise TabFailed(reason, scope)
    d = env.get("data")
    return d if isinstance(d, dict) else {}


class TabFailed(Exception):
    def __init__(self, reason: str, scope: bool = False):
        super().__init__(reason)
        self.scope = scope


def tab_page_url(ctx: Ctx) -> str:
    a = ctx.args
    if a.page_url:
        return a.page_url.strip()
    online = (ctx.state.get("release") or {}).get("online_url") or ""
    if online:
        return online
    path = Path(a.web_config) if a.web_config else ctx.out_dir / "web.json"
    try:
        return str(json.loads(path.read_text()).get("page_url") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def tab_chat_id(ctx: Ctx) -> str:
    a = ctx.args
    if a.chat_id:
        return a.chat_id.strip()
    if not a.covey_state:
        raise TabSkip("没给 --covey-state（或 --chat-id），不知道你和机器人的私聊是哪一个。")
    path = Path(a.covey_state) / "owner-chat.json"
    try:
        chat = str(json.loads(path.read_text()).get("chat_id") or "")
    except (OSError, ValueError, AttributeError):
        chat = ""
    if not chat:
        raise TabSkip(f"{path} 还不存在或里面没有 chat_id：你还没和机器人私聊过。先在飞书里给机器人发一句话。")
    return chat


def tab_bot_profile(ctx: Ctx) -> str:
    """Covey 机器人自己的 lark-cli profile（bot-identity.json 的 profile，或 --bot-profile）。它可能不是妙搭部署用的
    那个（--profile，你本人的登录）：标签要用机器人所在的应用，用错了会建到别的应用名下或报没在会话里。"""
    a = ctx.args
    ident = read_identity(a.covey_state)
    profile = a.bot_profile or str(ident.get("profile") or "")
    if not profile:
        raise TabSkip("认不出 Covey 机器人用的 lark-cli profile（bot-identity.json 里没有 profile）：用 --bot-profile <名字> 指定。")
    if not shutil.which("lark-cli"):
        raise TabSkip("找不到 lark-cli。")
    proc = subprocess.run(["lark-cli", "auth", "status", "--json", "--profile", profile], text=True, capture_output=True)
    st = parse_envelope(proc.stdout) or {}
    want = str(ident.get("app_id") or "")
    if want and st.get("appId") and st["appId"] != want:
        raise TabSkip(f"profile {profile} 的飞书应用和 Covey 的机器人不是同一个：用 --bot-profile 指定机器人那个。")
    return profile


def tab_body(url: str, tab_id: str = "", icon_key: str = "") -> dict:
    config = {"is_built_in": True}
    if icon_key:
        config["icon_key"] = icon_key
    tab = {"tab_name": TAB_NAME, "tab_type": "url", "tab_content": {"url": url}, "tab_config": config}
    if tab_id:
        tab["tab_id"] = tab_id
    return {"chat_tabs": [tab]}


def find_tab(tabs: list, wanted_id: str = "") -> dict | None:
    named = [t for t in tabs if isinstance(t, dict) and t.get("tab_type") == "url" and t.get("tab_name") == TAB_NAME]
    for t in named:
        if wanted_id and t.get("tab_id") == wanted_id:
            return t
    if wanted_id:
        for t in tabs:
            if isinstance(t, dict) and t.get("tab_id") == wanted_id and t.get("tab_type") == "url":
                return t
    return named[0] if named else None


def tab_ok(tab: dict, url: str) -> bool:
    return ((tab.get("tab_content") or {}).get("url") == url and (tab.get("tab_config") or {}).get("is_built_in") is True)


def step_chat_tab(ctx: Ctx) -> None:
    """10. 私聊顶栏的「工作台」标签。做不成只打印原因和补救命令，不抛、不改 web.json、不改退出码。"""
    try:
        chat_tab(ctx)
    except TabSkip as exc:
        say(f"10. 私聊「{TAB_NAME}」标签：这次没建。{exc}\n    补上以后单独做这一步：{tab_rerun(ctx)}")
    except TabFailed as exc:
        extra = (f"机器人缺 {TAB_SCOPE} 权限：等 Covey 的「飞书应用待补」卡点「扫码自动补齐」，或在开发者后台给这个应用加上并发布新版本。"
                 if exc.scope else "")
        say(f"10. 私聊「{TAB_NAME}」标签：这次没建，飞书接口说：{exc}\n    {extra}\n    处理好以后单独做这一步：{tab_rerun(ctx)}")


def tab_order(tabs: list, mine: str) -> list:
    """把 mine 挪到「消息」标签后面（第 2 位），其余保持原来的相对顺序。没有「消息」标签就挪到最前。"""
    ids = [str(t.get("tab_id")) for t in tabs if isinstance(t, dict) and t.get("tab_id")]
    rest = [i for i in ids if i != mine]
    first = next((n for n, t in enumerate(tabs) if isinstance(t, dict) and t.get("tab_type") == "message"), None)
    head = [str(tabs[first]["tab_id"])] if first is not None and str(tabs[first].get("tab_id")) in rest else []
    return head + [mine] + [i for i in rest if i not in head]


def sort_chat_tab(ctx: Ctx, path: str, tabs: list, mine: str) -> None:
    """让「工作台」紧挨着「消息」。排序失败只提示，不影响别的。"""
    order = tab_order(tabs, mine)
    if order == [str(t.get("tab_id")) for t in tabs if isinstance(t, dict) and t.get("tab_id")]:
        say("    标签顺序：「工作台」已经在第 2 位，没动")
        return
    try:
        bot_api(ctx, "POST", path + "/sort_tabs", {"tab_ids": order})
    except TabFailed as exc:
        say(f"    标签顺序：没排成，飞书接口说：{exc}\n    标签已经建好，只是不在第 2 位；之后单独补排：{tab_rerun(ctx)}")
        return
    say("    标签顺序：「工作台」排到了「消息」后面（第 2 位）")


def chat_tab(ctx: Ctx) -> None:
    a = ctx.args
    if a.skip_chat_tab:
        say("10. 私聊「工作台」标签：按 --skip-chat-tab 跳过")
        return
    url = tab_page_url(ctx)
    if a.dry_run:
        # 不调标签的任何接口（包括拉取），只说明会怎么做
        chat = ""
        try:
            chat = tab_chat_id(ctx)
        except TabSkip as exc:
            say(f"10. 私聊「{TAB_NAME}」标签：[不执行] 现在做不了：{exc}（补上后再做：{tab_rerun(ctx)}）")
            return
        say(f"10. 私聊「{TAB_NAME}」标签：[不执行] 以机器人身份（profile 取 bot-identity.json 里的，或 --bot-profile）对会话 {chat} 先试拉取标签；"
            f"没有同名标签就 POST {TAB_PATH.format(chat=chat)} 建，有就 .../update_tabs 原地更新，已一致就不动；"
            "然后用 .../sort_tabs 把它排到「消息」后面（第 2 位：消息、工作台、其余标签保持原顺序，已经在就不调）。"
            f"标签网址：{url or '发布后的线上地址'}，tab_config.is_built_in=true（飞书内嵌打开）。")
        return
    if not url:
        raise TabSkip("还没有网页地址（没发布、web.json 里也没有 page_url）：给 --page-url，或先把前面几步做完。")
    if not url.startswith(("https://", "http://")):
        raise TabSkip(f"网页地址 {url} 不是 http(s) 开头，飞书不收。")
    chat = tab_chat_id(ctx)
    ctx.bot_profile = tab_bot_profile(ctx)
    path = TAB_PATH.format(chat=chat)
    ledger = ctx.state.get("chat_tab") or {}
    known_id = a.tab_id or (ledger.get("tab_id") if ledger.get("chat_id") in (None, "", chat) else "")
    tabs, listed = [], False
    try:
        tabs = bot_api(ctx, "GET", path + "/list_tabs").get("chat_tabs") or []
        listed = True
    except TabFailed as exc:
        say(f"    （读不了现有标签：{exc}；改用记下的 tab_id 判断）")
    tab = find_tab(tabs, known_id) if listed else ({"tab_id": known_id} if known_id else None)
    try:
        if tab and (not listed or not tab_ok(tab, url)):
            result = bot_api(ctx, "POST", path + "/update_tabs", tab_body(url, tab["tab_id"], (tab.get("tab_config") or {}).get("icon_key") or ""))
            action = "已更新"
        elif tab:
            result, action = {"chat_tabs": tabs}, "已经是最新的，没动"
        else:
            result = bot_api(ctx, "POST", path, tab_body(url))
            action = "已创建"
    except TabFailed as exc:
        if tab and not listed and not exc.scope:
            raise TabFailed(f"{exc}（记下的 tab_id {tab['tab_id']} 可能已被删；去飞书里确认有没有「{TAB_NAME}」标签，没有就清掉进度文件里的 chat_tab 后重跑，有就用 --tab-id 指定）", False) from exc
        raise
    after = result.get("chat_tabs") or []
    mine = find_tab(after, (tab or {}).get("tab_id", ""))
    if not mine:
        mine = next((t for t in after if isinstance(t, dict) and tab_ok(t, url) and t.get("tab_name") == TAB_NAME), None)
    if mine and mine.get("tab_id"):
        ctx.state["chat_tab"] = {"tab_id": mine["tab_id"], "url": url, "chat_id": chat}
        ctx.save()
    twins = [t for t in after if isinstance(t, dict) and t.get("tab_type") == "url" and t.get("tab_name") == TAB_NAME
             and t.get("tab_id") != (mine or {}).get("tab_id")]
    flag = (mine or {}).get("tab_config") or {}
    say(f"10. 私聊「{TAB_NAME}」标签：{action}（{url}，飞书内嵌打开）")
    if mine and "is_built_in" in flag and flag["is_built_in"] is not True:
        say("    注意：飞书返回的标签 is_built_in 不是 true，客户端可能会跳外部浏览器；去飞书里看一眼。")
    if a.keep_tab_order:
        pass
    elif mine and mine.get("tab_id"):
        sort_chat_tab(ctx, path, after, mine["tab_id"])
    else:
        say("    标签顺序：飞书这次没返回完整的标签列表，不知道全部标签的 ID（排序要全部），没排；"
            f"能读标签后补排：{tab_rerun(ctx)}")
    if twins:
        say(f"    注意：会话里还有 {len(twins)} 个同名标签（tab_id {', '.join(str(t.get('tab_id')) for t in twins)}），"
            "可以在飞书里手动删掉多的；之后更新用 --tab-id 指定要留的那个。")


def homepage_hint(ctx: Ctx) -> None:
    """11. 想把工作台固定到飞书左侧主导航：机器人的飞书应用要有「网页应用」能力并把主页设成网页地址。
    这一步没有开放接口（应用管理的官方接口里没有「添加应用能力」「设主页」），本脚本也不替你点开发者后台，只提示手工步骤。"""
    url = tab_page_url(ctx) or "<网页地址>"
    say(f"\n可选（要把工作台固定到飞书左侧主导航时才做；私聊顶栏的标签不依赖它）：在 Covey 机器人那个飞书应用的开发者后台\n"
        f"  1. 应用能力 → 添加应用能力 → 添加「网页应用」\n"
        f"  2. 应用能力 → 网页应用：「桌面端主页」和「移动端主页」都填 {url}（不要加 lk_jump_to_browser 参数，否则会跳外部浏览器）\n"
        f"  3. 版本管理与发布 → 创建版本并发布（租户要审核时等管理员通过）；可用范围至少含你自己\n"
        f"  详见 web/deploy/miaoda/README.md 的「固定到飞书主导航」。")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把 web/ 一键部署成你自己飞书里的妙搭全栈应用")
    ap.add_argument("--covey-state", help="Covey 的状态目录（读 bot-identity.json 里的主人；默认把 web.json、密钥和进度放到它下面的 web/）")
    ap.add_argument("--owner-open-id", default="", help="可选：主人的 open_id，给了就核对 lark-cli 登录的是不是这个人")
    ap.add_argument("--out-dir", help="web.json、密钥文件和进度文件放哪（默认 <covey-state>/web）")
    ap.add_argument("--profile", default=None, help="lark-cli 的 profile（不给用 lark-cli 的默认 profile）；要用你本人登录过、有妙搭权限的那个")
    ap.add_argument("--name", default="Covey 网页工作台", help="新建应用的名字")
    ap.add_argument("--app-id", help="接着用一个已有的应用（不是本脚本建的要再加 --adopt-existing）")
    ap.add_argument("--adopt-existing", action="store_true", help="允许接手不是本脚本建的应用：会覆盖它的代码、改它的库和可见范围")
    ap.add_argument("--reapply-schema", action="store_true", help="表已在也按 schema.sql 再套一遍（表用 IF NOT EXISTS，策略先删后建）")
    ap.add_argument("--key-file", help="开放接口密钥写到哪（默认 <out-dir>/web-openapi.key）")
    ap.add_argument("--web-config", help="Covey 的网页配置写到哪（默认 <out-dir>/web.json）")
    ap.add_argument("--release-wait", type=int, default=RELEASE_WAIT_SECONDS, help="发布最多等多少秒")
    ap.add_argument("--poll-seconds", type=float, default=10, help="查发布进度的间隔")
    ap.add_argument("--only-chat-tab", action="store_true", help="只做第 10 步：给私聊顶栏建/更新「工作台」标签（老部署补建用；网址取进度文件、web.json 或 --page-url）")
    ap.add_argument("--skip-chat-tab", action="store_true", help="不建私聊顶栏的「工作台」标签")
    ap.add_argument("--keep-tab-order", action="store_true", help="建/更新「工作台」标签后不调整它的位置（默认排到「消息」后面，第 2 位）")
    ap.add_argument("--bot-profile", default=None, help="Covey 机器人用的 lark-cli profile（建标签用机器人身份；默认读 <covey-state>/bot-identity.json 的 profile）")
    ap.add_argument("--chat-id", default=None, help="你和机器人的私聊 chat_id（默认读 <covey-state>/owner-chat.json）")
    ap.add_argument("--page-url", default=None, help="标签要打开的网页地址（默认用发布后的线上地址或 web.json 的 page_url）")
    ap.add_argument("--tab-id", default=None, help="已有的「工作台」标签的 tab_id（机器人读不了现有标签、又没记录时用，避免建出第二个）")
    ap.add_argument("--dry-run", action="store_true", help="只列出要做的事和命令，不调用任何会写入的接口")
    ap.add_argument("--yes", action="store_true", help="确认真做（会建应用、改库、建密钥、发布）")
    a = ap.parse_args(argv)
    if not a.dry_run and not a.yes:
        say(("这会在你和机器人的私聊顶栏建或更新「工作台」标签。" if a.only_chat_tab else "这会在你的飞书里建一个妙搭应用并发布。") + "先加 --dry-run 看看要做什么，确认后加 --yes 真做。")
        return 2
    out_dir = Path(a.out_dir) if a.out_dir else (Path(a.covey_state) / "web" if a.covey_state else None)
    if out_dir is None:
        say("要 --out-dir 或 --covey-state（放 web.json、密钥和进度文件）。")
        return 2
    ctx = Ctx(args=a, out_dir=out_dir, state_path=out_dir / "miaoda-deploy.json")
    if ctx.state_path.is_file():
        ctx.state = json.loads(ctx.state_path.read_text())
    if a.only_chat_tab:
        say(("【只看不做】" if a.dry_run else "") + "只补建私聊顶栏的「工作台」标签")
        step_chat_tab(ctx)
        homepage_hint(ctx)
        return 0
    say(("【只看不做】" if a.dry_run else "") + f"部署 web/ 到妙搭（进度记在 {ctx.state_path}）")
    try:
        step_preflight(ctx)
        step_app(ctx)
        step_database(ctx)
        step_code(ctx)
        uid = owner_uid(ctx)
        step_schema(ctx, uid)
        step_env(ctx, uid)
        step_key(ctx)
        step_release(ctx)
        step_scope(ctx)
        step_config(ctx)
        step_chat_tab(ctx)
        homepage_hint(ctx)
    except StepFailed as exc:
        say(str(exc))
        return exc.code
    say("全部做完。" if not a.dry_run else "以上是要做的事；确认后把 --dry-run 换成 --yes。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
