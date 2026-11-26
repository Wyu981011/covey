#!/usr/bin/env python3
"""测试用的假 lark-cli：只认 deploy.py 用到的命令，状态记在 FAKE_LARK_STATE 指的 JSON 里，每次调用记一行到 calls（--as、--format 及其值 user、json 不记；bot 会留下）。

环境变量：
  FAKE_LARK_STATE  状态文件（必需）
  FAKE_OWNER       auth status 里登录用户的 open_id
  FAKE_FAIL        create：+create 报 feature_not_available
  FAKE_RELEASE     pending：发布停在审批
  FAKE_MULTIENV    1：库是 dev/online 两套，建表后 +db-env-diff 有变更
  FAKE_APP_ID      auth status 里的 appId（测 profile 对不对得上机器人）
  FAKE_TABS_READ   deny：list_tabs 报缺权限
  FAKE_TABS_WRITE  deny：建/改标签报缺权限；error：报别的错
  FAKE_TABS_NOLIST 1：建/更新的响应里不带标签列表
  FAKE_TABS_SORT   error：排序报错
  FAKE_OLD_CLI     1：旧版本 lark-cli（1.0.50）：+release-create 的 --help 里没有 --apply-reason，带了就报 unknown flag
  FAKE_TABS_SEED   1：会话里已有一个旧的「工作台」标签（没有 is_built_in）
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_LARK_STATE"])
APP = "app_demo01"
UID = "100000000042"


def load():
    return json.loads(STATE.read_text()) if STATE.exists() else {"calls": [], "tables": [], "keys": [], "db": False, "env": {}, "polls": 0}


def save(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1))


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def fail(subtype, message, code=1):
    out({"ok": False, "error": {"type": "api", "subtype": subtype, "message": message, "hint": ""}}, code)


def opt(args, name, default=""):
    return args[args.index(name) + 1] if name in args else default


def git(*a, cwd=None):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def init_repo(target: Path):
    remote = STATE.parent / "remote.git"
    if not remote.exists():
        seed = STATE.parent / "seed"
        seed.mkdir()
        files = {
            ".spark/meta.json": json.dumps({"stack": "nestjs-react-fullstack", "app_id": APP}),
            ".spark_project": "run = [\"npm\", \"run\", \"dev\"]\n",
            "README.md": "模板自带的说明\n",
            "scripts/build.sh": "#!/usr/bin/env bash\n# 模板的旧构建脚本\n",
            "client/src/app.tsx": "// 模板的入口\n",
            "client/src/components/business-ui/old.tsx": "// 模板残留\n",
            "server/modules/hello/hello.module.ts": "// 模板残留\n",
            "package.json": "{\"name\": \"fullstack-nestjs-template\"}\n",
        }
        for rel, text in files.items():
            p = seed / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git("init", "-q", "-b", "sprint/default", cwd=seed)
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A", cwd=seed)
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "模板", cwd=seed)
        git("clone", "-q", "--bare", str(seed), str(remote))
    git("clone", "-q", "-b", "sprint/default", str(remote), str(target))
    return remote


def tabs_api(s, args):
    """会话标签页的三个接口：建、更新、拉取。标签记在 s["tabs"]（初始只有消息和 Pin 两个内置的）。"""
    method, path = args[1], args[2]
    body = json.loads(opt(args, "--data", "{}"))
    if "tabs" not in s:
        s["tabs"] = [{"tab_id": "1", "tab_type": "message"}, {"tab_id": "2", "tab_type": "pin"}, {"tab_id": "3", "tab_type": "file"}]
        if os.environ.get("FAKE_TABS_SEED"):
            s["tabs"].append({"tab_id": "77", "tab_name": "工作台", "tab_type": "url", "tab_content": {"url": "https://old.example.com/"}})
    m = re.match(r"^/open-apis/im/v1/chats/(oc_\w+)/chat_tabs(/list_tabs|/update_tabs|/sort_tabs)?$", path)
    if not m:
        fail("unknown", f"假 lark-cli 不认识这个接口：{path}", 2)
    s["tab_calls"] = s.get("tab_calls", []) + [f"{method} {path.split('/chats/')[1].split('/', 1)[1]}"]
    if method == "GET" and m.group(2) == "/list_tabs":
        if os.environ.get("FAKE_TABS_READ") == "deny":
            out({"ok": False, "error": {"type": "api", "subtype": "missing_scope", "code": 99991672, "message": "missing im:chat.tabs:read"}}, 1)
        out({"code": 0, "msg": "ok", "data": {"chat_tabs": s["tabs"]}})
    if method != "POST":
        fail("unknown", "bad method", 2)
    if os.environ.get("FAKE_TABS_WRITE") == "deny":
        out({"ok": False, "error": {"type": "api", "subtype": "missing_scope", "code": 99991672, "message": "need im:chat.tabs:write_only"}}, 1)
    if os.environ.get("FAKE_TABS_WRITE") == "error":
        out({"code": 232006, "msg": "invalid chat_id"}, 0)
    if m.group(2) == "/sort_tabs":
        if os.environ.get("FAKE_TABS_SORT") == "error":
            out({"code": 232001, "msg": "sort failed"}, 0)
        ids = body["tab_ids"]
        if sorted(ids) != sorted(t["tab_id"] for t in s["tabs"]):
            out({"code": 232001, "msg": "tab_ids must hold every tab"}, 0)
        s["tabs"] = [next(t for t in s["tabs"] if t["tab_id"] == i) for i in ids]
        out({"code": 0, "msg": "ok", "data": {"chat_tabs": s["tabs"]}})
    for tab in body["chat_tabs"]:
        if m.group(2) == "/update_tabs":
            old = next((t for t in s["tabs"] if t["tab_id"] == tab["tab_id"]), None)
            if old is None:
                out({"code": 232001, "msg": "tab not found"}, 0)
            old.update({k: v for k, v in tab.items() if k != "tab_id"})
        else:
            s["tabs"].append({**tab, "tab_id": str(100 + len(s["tabs"]))})
    out({"code": 0, "msg": "ok", "data": {} if os.environ.get("FAKE_TABS_NOLIST") else {"chat_tabs": s["tabs"]}})


def main():
    args = sys.argv[1:]
    s = load()
    s["calls"].append(" ".join(a for a in args if a not in ("--as", "user", "--format", "json")))
    if args == ["--version"]:
        print("lark-cli version " + ("1.0.50" if os.environ.get("FAKE_OLD_CLI") else "1.0.120"))
        sys.exit(0)
    stdin = sys.stdin.read() if "-" in args and not sys.stdin.isatty() else ""
    try:
        if args[:2] == ["auth", "status"]:
            st = {"verified": True, "identities": {"user": {"openId": os.environ.get("FAKE_OWNER", ""), "status": "ready"}}}
            if os.environ.get("FAKE_APP_ID"):
                st["appId"] = os.environ["FAKE_APP_ID"]
            out(st)
        if args[:1] == ["api"]:
            tabs_api(s, args)
        cmd = args[1] if args[:1] == ["apps"] else ""
        if cmd == "+create":
            if os.environ.get("FAKE_FAIL") == "create":
                fail("feature_not_available", "tenant has no miaoda full_stack")
            s["created"] = True
            out({"ok": True, "data": {"app": {"app_id": APP, "name": opt(args, "--name")}}})
        if cmd == "+get":
            out({"ok": True, "data": {"app": {"app_id": opt(args, "--app-id"), "app_type": "full_stack"}}})
        if cmd == "+features":
            out({"ok": True, "data": {"features": [{"name": "database", "enabled": s["db"]}]}})
        if cmd == "+feature-enable":
            s["db"] = True
            out({"ok": True, "data": {"feature": {"name": "database", "enabled": True}}})
        if cmd == "+init":
            target = Path.cwd() / opt(args, "--dir")
            init_repo(target)
            out({"ok": True, "data": {"clone_path": str(target), "branch": "sprint/default"}})
        if cmd == "+git-credential-init":
            out({"ok": True, "data": {}})
        if cmd == "+user-id-convert":
            ids = opt(args, "--ids").split(",")
            out({"ok": True, "data": {"items": [{"index": 0, "source_id": ids[0], "target_id": UID}], "missed": []}})
        if cmd == "+db-table-list":
            out({"ok": True, "data": {"items": [{"name": t} for t in s["tables"]]}})
        if cmd == "+db-execute":
            s["sql"] = stdin
            s["tables"] = sorted(set(s["tables"]) | set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", stdin)))
            s["pending"] = 25 if os.environ.get("FAKE_MULTIENV") else 0
            out({"ok": True, "data": [{"command": "BEGIN"}, {"command": "COMMIT"}]})
        if cmd == "+db-env-diff":
            if not os.environ.get("FAKE_MULTIENV"):
                fail("failed_precondition", "应用未开启多环境")
            out({"ok": True, "data": {"changes": [{"type": "DDL", "table": "projects", "statement": "CREATE TABLE …"}] * s.get("pending", 0)}})
        if cmd == "+db-env-migrate":
            s["migrated"] = s.get("pending", 0)
            s["pending"] = 0
            out({"ok": True, "data": {"count": s["migrated"]}})
        if cmd == "+env-set":
            s["env"][opt(args, "--environment") + ":" + opt(args, "--key")] = stdin
            out({"ok": True, "data": {}})
        if cmd == "+openapi-key-list":
            out({"ok": True, "data": {"items": s["keys"]}})
        if cmd == "+openapi-key-create":
            s["keys"].append({"name": opt(args, "--name"), "key_preview": "****abcd", "scope_all": "--scope-all" in args})
            out({"ok": True, "data": {"api_key": "fake-secret-abcd"}})
        if cmd == "+release-create" and "--help" in args:
            flags = "  --app-id string\n  --branch string\n" + ("" if os.environ.get("FAKE_OLD_CLI") else "  --apply-reason string\n")
            print("Usage:\n  lark-cli apps +release-create [flags]\n\nFlags:\n" + flags)
            sys.exit(0)
        if cmd == "+release-create":
            if os.environ.get("FAKE_OLD_CLI") and "--apply-reason" in args:
                print("Error: unknown flag: --apply-reason", file=sys.stderr)
                sys.exit(1)
            s["polls"] = 0
            if os.environ.get("FAKE_RELEASE") == "pending":
                out({"ok": True, "data": {"release_id": "rel1", "status": "pending",
                                          "current_node_info": {"current_status": "PENDING", "result": {"approval_url": "https://approve.example.com/x"}}}})
            out({"ok": True, "data": {"release_id": "rel1", "status": "publishing", "sync": False}})
        if cmd == "+release-get":
            s["polls"] += 1
            out({"ok": True, "data": {"release": {"release_id": "rel1", "status": "finished", "online_url": f"https://fake.example.com/app/{APP}"}}})
        if cmd == "+access-scope-set":
            s["scope"] = {"scope": opt(args, "--scope"), "targets": json.loads(opt(args, "--targets", "[]"))}
            out({"ok": True, "data": {}})
        fail("unknown", f"假 lark-cli 不认识：{' '.join(args)}", 2)
    finally:
        save(s)


if __name__ == "__main__":
    main()
