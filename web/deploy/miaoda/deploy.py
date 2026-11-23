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

用法：
  python3 web/deploy/miaoda/deploy.py --covey-state <Covey 状态目录> --dry-run     # 先看要做什么，不调任何接口
  python3 web/deploy/miaoda/deploy.py --covey-state <Covey 状态目录> --yes         # 真做
常用参数：--profile（lark-cli 的 profile，默认用 lark-cli 的默认 profile）、--out-dir（web.json、密钥和进度文件放哪，默认 <状态目录>/web）、
  --name（应用名）、--app-id + --adopt-existing（接手一个已有的应用；会覆盖它的代码，慎用）。
退出码：0 做完；1 某一步失败；2 前提不满足（没登录、缺命令、参数不对）；3 发布在等审批。
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
    ap.add_argument("--dry-run", action="store_true", help="只列出要做的事和命令，不调用任何会写入的接口")
    ap.add_argument("--yes", action="store_true", help="确认真做（会建应用、改库、建密钥、发布）")
    a = ap.parse_args(argv)
    if not a.dry_run and not a.yes:
        say("这会在你的飞书里建一个妙搭应用并发布。先加 --dry-run 看看要做什么，确认后加 --yes 真做。")
        return 2
    out_dir = Path(a.out_dir) if a.out_dir else (Path(a.covey_state) / "web" if a.covey_state else None)
    if out_dir is None:
        say("要 --out-dir 或 --covey-state（放 web.json、密钥和进度文件）。")
        return 2
    ctx = Ctx(args=a, out_dir=out_dir, state_path=out_dir / "miaoda-deploy.json")
    if ctx.state_path.is_file():
        ctx.state = json.loads(ctx.state_path.read_text())
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
    except StepFailed as exc:
        say(str(exc))
        return exc.code
    say("全部做完。" if not a.dry_run else "以上是要做的事；确认后把 --dry-run 换成 --yes。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
