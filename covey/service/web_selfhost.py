"""自托管网页工作台的准备和托管参数 (docs/web.md 自托管, docs/operations.md 服务托管): what ``COVEY_WEB_SELFHOST=1`` asks of the Manager
(``wanted``, ``spec``: the command and environment of the page's own Node process) and the one-time preparation a person or
./install runs (``prepare``): the open-interface key file, ``web.json`` and the switches to set in the service manifest.

Standard library and covey.core only. From a terminal: ``python3 -B -m covey.service.web_selfhost [--data-root D] [--port P] [--dir DIR]``;
it writes nothing that exists (a key file is never overwritten) and prints the switches for the manifest.
"""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from covey.core import env as cenv
from covey.core import web_sync
from covey.core import paths
from covey.core.state import read_json, read_object, write_json

ENV = "COVEY_WEB_SELFHOST"  # ``1``: the Manager runs the page's Node process; anything else, unset too: it does not.
DIR_ENV = "COVEY_WEB_SELFHOST_DIR"  # The built page (web/dist-selfhost, node_modules beside it): server/selfhost/main.js in it is what runs.
PORT_ENV = "COVEY_WEB_SELFHOST_PORT"
DEFAULT_PORT = 18650
FOLDER = "web"  # <data home>/web/: web.json, the key file, db/, logs/ (the Bridge's own records are <state>/web/).
KEY_FILE = "web-openapi.key"
CONFIG_FILE = "web.json"
DB_DIR = "db"
# A file whose one line is an external Postgres's connection string: the page uses that database instead of its own (PGlite in
# DB_DIR). A file, not a manifest setting: the string may carry a password.
DATABASE_URL_FILE = "database-url"
LOG_DIR = "logs"
LOG_FILE = "selfhost.log"
ENTRY = Path("server") / "selfhost" / "main.js"  # Not server/main.js beside it: that one is the hosted platform's entry.


def enabled(environ=None) -> bool:
    return str(cenv.get(ENV, "", environ)).strip() == "1"


def port_of(environ=None) -> int:
    """The port COVEY_WEB_SELFHOST_PORT says (DEFAULT_PORT when unset or not a port number)."""
    text = str(cenv.get(PORT_ENV, "", environ)).strip()
    return int(text) if text.isdigit() and 0 < int(text) < 65536 else DEFAULT_PORT


def web_home(data_home) -> Path:
    return Path(data_home) / FOLDER


def spec(environ, data_home) -> dict | None:
    """What to run for the settings in ``environ`` (a service manifest's, over the Manager's): {argv, env, path, log, dir, port, home},
    or None when the switch is off or ``COVEY_WEB_SELFHOST_DIR`` is not an absolute path. ``env`` is only what this process adds
    (the Manager's environment goes under it); ``path`` is the service's PATH, where ``node`` is looked for."""
    if not enabled(environ):
        return None
    folder = str(cenv.get(DIR_ENV, "", environ)).strip()
    if not folder or not Path(folder).is_absolute():
        return None
    home, port = web_home(data_home), port_of(environ)
    return {"argv": ["node", str(Path(folder) / ENTRY)], "dir": folder, "port": port, "home": str(home),
            "path": str((environ or {}).get("PATH") or ""),
            "env": {"COVEY_WEB_HOST": "127.0.0.1", "COVEY_WEB_PORT": str(port), "COVEY_WEB_DB_DIR": str(home / DB_DIR),
                    "COVEY_WEB_KEY_FILE": str(home / KEY_FILE), "COVEY_WEB_DATABASE_URL_FILE": str(home / DATABASE_URL_FILE)},
            "log": str(home / LOG_DIR / LOG_FILE)}


def wanted(root, environ, service_environment) -> dict | None:
    """The spec (``spec``) of the first service of the Manager's root ``root`` that is meant to run and has COVEY_WEB_SELFHOST=1 in its
    manifest; None when none does. ``service_environment(base, saved)``: service/manager.py, the environment a service gets. The data
    home is the one that service's settings name, else the default (core/paths.py)."""
    for path in sorted((Path(root) / "services").glob("*.json")):
        manifest = read_json(path, None)
        if not isinstance(manifest, dict) or manifest.get("desired_state") != "running":
            continue
        env = service_environment(environ, manifest.get("environment") or {})
        override = str(cenv.get("COVEY_DATA_HOME", "", env)).strip()
        found = spec(env, Path(override).expanduser() if override else paths.data_home())
        if found:
            return found
    return None


def prepare(data_home, port=DEFAULT_PORT, folder="", page_url="") -> dict:
    """Make the data root ready for a self-hosted page: <data home>/web/ (0700), the key file (0600, a new random key; one that is
    there is kept), ``web.json`` (base_url on the loopback, key_file, push_seconds 1, poll_seconds 1; other fields of an existing one,
    ``page_url`` is ``page_url`` when given, else the one that is there, else ``http://127.0.0.1:<port>/``: the address the 打开网页 buttons of the
    Feishu cards open, core/web_sync.py ``page_url``). Returns {key_file, config, created_key, switches}: ``switches`` are the lines for the service manifest."""
    home = web_home(data_home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    key = home / KEY_FILE
    created = False
    if not key.exists() or not key.read_text().strip():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(secrets.token_urlsafe(32) + "\n")
        created = True
    os.chmod(key, 0o600)
    config = home / CONFIG_FILE
    old = read_object(config)
    kept = str(old.get("page_url") or "").strip()
    page = page_url or (kept if web_sync.page_url_ok(kept) else f"http://127.0.0.1:{port}/")
    write_json(config, {**old, "base_url": f"http://127.0.0.1:{port}/openapi", "key_file": str(key), "push_seconds": 1, "poll_seconds": 1,
                        "page_url": page}, ensure_ascii=False, indent=2)
    os.chmod(config, 0o600)
    switches = ["COVEY_WEB=1", f"COVEY_WEB_CONFIG={config}", f"{ENV}=1"]
    if folder:
        switches.append(f"{DIR_ENV}={folder}")
    if port != DEFAULT_PORT:
        switches.append(f"{PORT_ENV}={port}")
    return {"key_file": str(key), "config": str(config), "page_url": page, "created_key": created, "switches": switches}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -B -m covey.service.web_selfhost",
                                     description="准备自托管网页工作台：开放接口密钥文件、web.json，并打印要在服务清单里设的开关")
    parser.add_argument("--data-root", help="数据根（默认 COVEY_DATA_HOME，没设时按代码目录推算）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"网页进程监听的本机端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--page-url", default="", help="你在浏览器里打开网页的地址（写进 web.json 的 page_url，飞书卡片的「打开网页」按钮用它）；"
                        "默认 http://127.0.0.1:<端口>/，已有的 page_url 不给这个参数时保留")
    parser.add_argument("--dir", default="", help="自托管构建产物目录（web/dist-selfhost，里面有 server/selfhost/main.js）；给了就写进要设的开关")
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port 要在 1 到 65535 之间")
    if args.page_url and not web_sync.page_url_ok(args.page_url):
        parser.error("--page-url 要以 http:// 或 https:// 开头，不含空白")
    if args.dir and not Path(args.dir).is_absolute():
        parser.error("--dir 要写绝对路径")
    data_home = Path(args.data_root).expanduser().resolve() if args.data_root else paths.data_home()
    result = prepare(data_home, args.port, args.dir, args.page_url)
    print(("已生成新的开放接口密钥文件：" if result["created_key"] else "密钥文件已存在，没有覆盖：") + result["key_file"])
    print("已写网页配置：" + result["config"])
    print("网页地址 page_url：" + result["page_url"] + "（飞书看板、手上的事、早晚汇总卡片上的「打开网页」按钮打开它；从别的设备访问时用 --page-url 改成那边能打开的地址）")
    print("在服务清单里设这些开关，然后重新注册服务（docs/configuration.md「改开关三步」）：")
    for line in result["switches"]:
        print("  " + line)
    if not args.dir:
        print(f"  {DIR_ENV}=<自托管构建产物目录的绝对路径>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
