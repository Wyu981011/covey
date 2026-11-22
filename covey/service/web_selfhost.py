"""自托管网页工作台的准备和托管参数 (docs/web.md 自托管, docs/operations.md 服务托管): what ``COVEY_WEB_SELFHOST=1`` asks of the Manager
(``wanted``, ``spec``: the command and environment of the page's own Node process) and the one-time preparation a person or
./install runs (``prepare``): the open-interface key file, ``web.json`` and the switches to set in the service manifest.

With ``COVEY_WEB_SELFHOST_PUBLIC`` (addresses) the page process also listens for HTTPS on a public port, with a self-signed certificate it
makes itself or the owner's own (``spec``'s ``public``, ``ensure_cert``); ``check`` is the doctor's look at it all (service/doctor.py) and
``restore_db`` puts a backup of its database back (core/web_backup.py).

Standard library and covey.core only. From a terminal: ``python3 -B -m covey.service.web_selfhost [--data-root D] [--port P] [--dir DIR]
[--public ADDR] [--restore-db PATH]``; it writes nothing that exists (a key file is never overwritten) and prints the switches for the manifest.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from covey.core import env as cenv
from covey.core import paths, web_backup, web_sync
from covey.core.state import read_json, read_object, write_json

ENV = "COVEY_WEB_SELFHOST"  # ``1``: the Manager runs the page's Node process; anything else, unset too: it does not.
DIR_ENV = "COVEY_WEB_SELFHOST_DIR"  # The built page (web/dist-selfhost, node_modules beside it): server/selfhost/main.js in it is what runs.
PORT_ENV = "COVEY_WEB_SELFHOST_PORT"
DEFAULT_PORT = 18650
PUBLIC_ENV = "COVEY_WEB_SELFHOST_PUBLIC"  # Addresses (IPv4, IPv6, domain; comma apart) the page is reached at from outside: non-empty turns on HTTPS.
PUBLIC_PORT_ENV = "COVEY_WEB_SELFHOST_PUBLIC_PORT"
BIND_ENV = "COVEY_WEB_SELFHOST_BIND"
TLS_CERT_ENV = "COVEY_WEB_SELFHOST_TLS_CERT"  # The owner's own certificate chain and key (PEM, absolute paths, both or neither).
TLS_KEY_ENV = "COVEY_WEB_SELFHOST_TLS_KEY"
DEFAULT_PUBLIC_PORT = 18443
DEFAULT_BIND = "0.0.0.0"
TLS_DIR = "tls"  # <web home>/tls/: cert.pem (0644), key.pem (0600) of the self-signed certificate the page makes (the directory 0700).
TLS_CLI = Path("server") / "selfhost" / "tls-cli.js"  # Makes sure the self-signed certificate is there; prints one JSON line.
RENEW_DAYS = 30  # A certificate with fewer days left is replaced by the page, and the doctor says so.
NAME = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)*[A-Za-z0-9-]{1,63}$")
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


def valid_name(name) -> bool:
    """Whether ``name`` may be a public address: an IPv4 or IPv6 address (no brackets, no zone) or a domain name."""
    name = str(name)
    if ":" in name or name.replace(".", "").isdigit():
        try:
            ipaddress.ip_address(name)
            return "%" not in name
        except ValueError:
            return False
    return bool(NAME.match(name))


def public_problem(environ=None) -> str:
    """Why COVEY_WEB_SELFHOST_PUBLIC does not turn the public listener on, in words; '' when it is unset or fine."""
    text = str(cenv.get(PUBLIC_ENV, "", environ)).strip()
    if not text:
        return ""
    bad = [name for name in (part.strip() for part in text.split(",")) if not valid_name(name)]
    if bad:
        return "公网地址不合法：" + "、".join(bad[:3])[:80] + "（只认 IPv4、IPv6 不带方括号、域名）"
    return ""


def public_names(environ=None) -> list:
    """The addresses of COVEY_WEB_SELFHOST_PUBLIC (in order, no repeats), all of them valid; [] when unset or any of them is not
    (the whole setting counts as off, ``public_problem`` says why)."""
    text = str(cenv.get(PUBLIC_ENV, "", environ)).strip()
    if not text or public_problem(environ):
        return []
    return list(dict.fromkeys(part.strip() for part in text.split(",")))


def public_port_of(environ=None) -> int:
    text = str(cenv.get(PUBLIC_PORT_ENV, "", environ)).strip()
    return int(text) if text.isdigit() and 0 < int(text) < 65536 else DEFAULT_PUBLIC_PORT


def bind_of(environ=None) -> str:
    text = str(cenv.get(BIND_ENV, "", environ)).strip()
    try:
        return str(ipaddress.ip_address(text)) if text else DEFAULT_BIND
    except ValueError:
        return DEFAULT_BIND


def own_tls(environ=None) -> tuple:
    """(cert, key) of the owner's own certificate when both settings are absolute paths, else ("", "")."""
    cert, key = str(cenv.get(TLS_CERT_ENV, "", environ)).strip(), str(cenv.get(TLS_KEY_ENV, "", environ)).strip()
    return (cert, key) if cert and key and Path(cert).is_absolute() and Path(key).is_absolute() else ("", "")


def url_host(name) -> str:
    """``name`` as the host of a URL: an IPv6 address in brackets."""
    return f"[{name}]" if ":" in str(name) else str(name)


def public_block(home, names, port, bind, cert="", key="") -> dict:
    """The ``public`` part of a spec or of ``prepare``'s result."""
    own = bool(cert and key)
    return {"names": list(names), "port": port, "bind": bind, "tls": "provided" if own else "self-signed",
            "cert": cert if own else str(Path(home) / TLS_DIR / "cert.pem"), "key": key if own else str(Path(home) / TLS_DIR / "key.pem")}


def spec(environ, data_home) -> dict | None:
    """What to run for the settings in ``environ`` (a service manifest's, over the Manager's): {argv, env, path, log, dir, port, home,
    public}, ``public`` None unless COVEY_WEB_SELFHOST_PUBLIC names valid addresses (``public_block``), or None when the switch is off or ``COVEY_WEB_SELFHOST_DIR`` is not an absolute path. ``env`` is only what this process adds
    (the Manager's environment goes under it); ``path`` is the service's PATH, where ``node`` is looked for."""
    if not enabled(environ):
        return None
    folder = str(cenv.get(DIR_ENV, "", environ)).strip()
    if not folder or not Path(folder).is_absolute():
        return None
    home, port = web_home(data_home), port_of(environ)
    env = {"COVEY_WEB_HOST": "127.0.0.1", "COVEY_WEB_PORT": str(port), "COVEY_WEB_DB_DIR": str(home / DB_DIR),
           "COVEY_WEB_KEY_FILE": str(home / KEY_FILE), "COVEY_WEB_DATABASE_URL_FILE": str(home / DATABASE_URL_FILE)}
    names, public = public_names(environ), None
    if names:
        cert, key = own_tls(environ)
        public = public_block(home, names, public_port_of(environ), bind_of(environ), cert, key)
        env.update(COVEY_WEB_PUBLIC_NAMES=",".join(names), COVEY_WEB_PUBLIC_PORT=str(public["port"]), COVEY_WEB_PUBLIC_HOST=public["bind"],
                   COVEY_WEB_TLS_DIR=str(home / TLS_DIR))
        if cert and key:
            env.update(COVEY_WEB_TLS_CERT=cert, COVEY_WEB_TLS_KEY=key)
    return {"argv": ["node", str(Path(folder) / ENTRY)], "dir": folder, "port": port, "home": str(home),
            "path": str((environ or {}).get("PATH") or ""), "env": env, "log": str(home / LOG_DIR / LOG_FILE), "public": public}


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


def ensure_cert(folder, data_home, names, *, node=None, timeout=60) -> dict | None:
    """Make sure the self-signed certificate for ``names`` is in <web home>/tls/ by the page's own command line
    (``<folder>/server/selfhost/tls-cli.js``, the rules of the page's certificate): its JSON line {cert, key, fingerprint, not_after,
    names, generated}; None when the build has no such command, no ``node`` is found or it failed (the page makes the certificate
    itself when it starts)."""
    cli = Path(folder or "") / TLS_CLI
    node = node or shutil.which("node")
    if not folder or not names or not node or not cli.is_file():
        return None
    try:
        done = subprocess.run([node, str(cli), "--dir", str(web_home(data_home) / TLS_DIR), "--names", ",".join(names)],
                              capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            return None
        found = json.loads(done.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return found if isinstance(found, dict) else None


def suggest_address() -> str:
    """This machine's address towards the internet when it is a global one, else ''. A UDP connect sends no packet."""
    for family, target in ((socket.AF_INET, "203.0.113.1"), (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 9))
                found = sock.getsockname()[0]
            if ipaddress.ip_address(found.split("%")[0]).is_global:
                return found
        except (OSError, ValueError):
            continue
    return ""


def pem_der(text) -> bytes:
    """The first certificate of the PEM ``text`` as DER; b'' when there is none."""
    found = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", text, re.S)
    try:
        return base64.b64decode("".join(found.group(1).split())) if found else b""
    except ValueError:
        return b""


def fingerprint_of(cert_file) -> str:
    """The SHA-256 of the certificate in ``cert_file`` as AB:CD:..., the way browsers show it; '' when it cannot be read."""
    try:
        der = pem_der(Path(cert_file).read_text(errors="replace"))
    except OSError:
        return ""
    return ":".join(f"{byte:02X}" for byte in hashlib.sha256(der).digest()) if der else ""


def cert_facts(cert_file) -> dict | None:
    """{not_after (epoch seconds), names (DNS names lowercased, IPs normalized)} of the certificate in ``cert_file``, by CPython's own
    decoder (a private interface: None when it is not there or cannot read the file)."""
    try:
        info = ssl._ssl._test_decode_cert(str(cert_file))  # noqa: SLF001 - no public way to read a PEM without a dependency
        names = set()
        for kind, value in info.get("subjectAltName", ()):
            if kind == "DNS":
                names.add(value.lower())
            elif kind == "IP Address":
                names.add(str(ipaddress.ip_address(value)))
        return {"not_after": ssl.cert_time_to_seconds(info["notAfter"]), "names": names}
    except Exception:  # noqa: BLE001 - a private interface: whatever it raises, it only means "cannot read"
        return None


def covers(names, name) -> bool:
    """Whether the certificate names ``names`` (``cert_facts``) cover the public address ``name``."""
    if ":" in name or name.replace(".", "").isdigit():
        return str(ipaddress.ip_address(name)) in names
    name = name.lower()
    return name in names or any(n.startswith("*.") and name.split(".", 1)[-1] == n[2:] and "." in name for n in names)


def _iso(epoch) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(url, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # The loopback never goes through a proxy.
    with opener.open(url, timeout=timeout) as response:
        value = json.loads(response.read(1 << 20))
    return value if isinstance(value, dict) else {}


def check(environ, data_home, *, timeout=3) -> dict:
    """The doctor's look at a self-hosted page (service/doctor.py, docs/web.md 体检): {status: ready|degraded, url, page_url, public,
    problems: [{what, next, level}], ...}. ``public``: None, or {names, port, bind, tls, listening, error, fingerprint, not_after}. Reads
    files and asks the page's /healthz on the loopback, nothing else; the key file's content and the TLS key's are never read."""
    found = spec(environ, data_home)
    port = found["port"] if found else port_of(environ)
    home = web_home(data_home)
    problems = []

    def add(what, next_step, level="fault"):
        problems.append({"what": what, "next": next_step, "level": level})

    report = {"status": "ready", "url": f"http://127.0.0.1:{port}/", "page_url": "", "public": None, "problems": problems,
              "home": str(home)}
    if found is None:
        add("没设构建产物目录 COVEY_WEB_SELFHOST_DIR（或不是绝对路径）", "按 docs/web.md「自托管」构建网页，把 dist-selfhost 的绝对路径设进服务清单并重新注册")
    else:
        if not (Path(found["dir"]) / ENTRY).is_file():
            add(f"网页的构建产物不在：{Path(found['dir']) / ENTRY}", "重新构建：bash web/deploy/selfhost/build.sh <目录>，再重新注册服务")
        if not shutil.which("node", path=found["path"] or None):
            add("node 不在服务的 PATH 里，Manager 起不了网页进程", "装 Node.js 22 以上，或把它所在目录加进服务清单的 PATH，重新注册服务")
    key = home / KEY_FILE
    try:
        mode = stat.S_IMODE(key.stat().st_mode)
        if not key.read_text().strip():
            add("开放接口密钥文件是空的", f"删掉 {key} 后重新运行 python3 -B -m covey.service.web_selfhost 生成")
        elif mode & 0o077:
            add(f"开放接口密钥文件权限是 {mode:o}，别人读得到", f"chmod 600 {key}")
    except OSError:
        add("开放接口密钥文件不在", "运行 python3 -B -m covey.service.web_selfhost --dir <dist-selfhost> 生成")
    config = home / CONFIG_FILE
    try:
        data = read_object(config)
        report["page_url"] = str(data.get("page_url") or "")
        base = urlsplit(str(data.get("base_url") or ""))
        if not data:
            raise ValueError("empty")
        if base.hostname not in web_sync.LOOPBACK_HOSTS or (base.port or 80) != port:
            add(f"web.json 的 base_url 没指向本机 {port} 端口", "重新运行 python3 -B -m covey.service.web_selfhost（会改正它），再重新注册服务")
    except (OSError, ValueError, TypeError):
        add("web.json 不在或读不出来", "运行 python3 -B -m covey.service.web_selfhost --dir <dist-selfhost> 生成")
    health = None
    try:
        health = _get_json(report["url"] + "healthz", timeout)
        if health.get("ok") is not True:
            health = None
    except (OSError, ValueError, urllib.error.URLError):
        health = None
    if health is None:
        add(f"网页进程没有回应（{report['url']}healthz）",
            f"Manager 在跑时几秒内会拉起它；看 {home / LOG_DIR / LOG_FILE} 的最后几行，和 manager.log 里的 web selfhost 行")
    else:
        report.update(pid=health.get("pid"), db=health.get("db"))
    names = public_names(environ)
    if not names:
        reason = public_problem(environ)
        if reason:
            add(reason + "；公网监听没开", f"改 {PUBLIC_ENV} 后重新注册服务")
        elif any(str(value).strip() for value in (cenv.get(PUBLIC_PORT_ENV, "", environ), cenv.get(BIND_ENV, "", environ),
                                                  cenv.get(TLS_CERT_ENV, "", environ), cenv.get(TLS_KEY_ENV, "", environ))):
            add(f"设了公网的端口、监听地址或证书，但没设 {PUBLIC_ENV}，公网监听没开", f"要开就设 {PUBLIC_ENV}=<地址>，不要就去掉那几项", "note")
    else:
        _check_public(report, environ, health, names, add, timeout)
    report["status"] = "degraded" if any(p["level"] == "fault" for p in problems) else "ready"
    return report


def _check_public(report, environ, health, names, add, timeout):
    public = public_block(report["home"], names, public_port_of(environ), bind_of(environ), *own_tls(environ))
    seen = (health or {}).get("public") if isinstance((health or {}).get("public"), dict) else {}
    cert, key = Path(public["cert"]), Path(public["key"])
    given = [str(cenv.get(TLS_CERT_ENV, "", environ)).strip(), str(cenv.get(TLS_KEY_ENV, "", environ)).strip()]
    if bool(given[0]) != bool(given[1]) or (all(given) and public["tls"] == "self-signed"):
        add("自己的证书没用上：证书和私钥要一起给，并且是绝对路径，现在用的是自签证书", f"补全 {TLS_CERT_ENV}、{TLS_KEY_ENV} 后重新注册服务", "note")
    info = {"names": names, "port": public["port"], "bind": public["bind"], "tls": public["tls"],
            "listening": bool(seen.get("listening")), "error": str(seen.get("error") or ""),
            "fingerprint": str(seen.get("fingerprint") or ""), "not_after": str(seen.get("not_after") or "")}
    report["public"] = info
    if health is not None and not info["listening"]:
        add("公网 HTTPS 监听没开：" + (info["error"] or "网页进程没说原因"),
            f"看 {report['home']}/{LOG_DIR}/{LOG_FILE}；自己的证书要写绝对路径且读得到，端口 {public['port']} 不能被占用")
    if not cert.is_file():
        add(f"证书文件不在：{cert}", "自签证书由网页进程启动时生成，起来后再体检；自己的证书检查路径")
    else:
        info["fingerprint"] = info["fingerprint"] or fingerprint_of(cert)
        facts = cert_facts(cert)
        if facts is None:
            add("证书文件读不出内容（或这个 Python 没有读证书的接口）", "用 openssl x509 -in <证书> -noout -dates -ext subjectAltName 自己看", "note")
        else:
            info["not_after"] = _iso(facts["not_after"])
            left = (facts["not_after"] - time.time()) / 86400
            if left < 0:
                add(f"证书已过期（{info['not_after']}）", "自签证书：重启网页进程会重新生成；自己的证书请换新" if public["tls"] == "self-signed" else "换新证书")
            elif left < RENEW_DAYS:
                add(f"证书 {int(left)} 天后过期（{info['not_after']}）",
                    "自签证书：重启网页进程会重新生成" if public["tls"] == "self-signed" else "换新证书", "note")
            lacking = [name for name in names if not covers(facts["names"], name)]
            if lacking:
                add("证书没盖住这些公网地址：" + "、".join(lacking),
                    "自签证书：重启网页进程会按现在的地址重新生成" if public["tls"] == "self-signed" else "给这些地址重新签发证书")
    try:
        mode = stat.S_IMODE(key.stat().st_mode)  # Only the mode; the key is never read.
        if mode & 0o077:
            add(f"私钥文件权限是 {mode:o}，别人读得到", f"chmod 600 {key}")
    except OSError:
        add(f"私钥文件不在：{key}", "自签证书由网页进程生成；自己的证书检查路径")
    host = "127.0.0.1" if public["bind"] in ("0.0.0.0", "") else "::1" if public["bind"] == "::" else public["bind"]
    try:
        with socket.create_connection((host, public["port"]), timeout=timeout):
            pass
    except OSError:
        if health is not None:
            add(f"公网端口 {public['port']} 连不上", "看是不是被别的程序占用；云服务器要在安全组和防火墙放行这个 TCP 端口")


def restore_db(source, data_home) -> dict:
    """Put the page's database back from ``source``: a daily backup (``bridge-*.tar.gz``, its ``selfhost-web/pglite.tar.gz``) or a
    pglite.tar.gz itself. It is unpacked safely into <web home>/db.restore (an old one removed first) and the marker written last; the
    page process, when /healthz answers, gets a SIGTERM and the Manager starts it again, which swaps the folder in (the old database
    stays as db.before-restore-<time>). Returns {restored, files, pid, message}; ValueError says what is wrong."""
    source, home = Path(source), web_home(data_home)
    if not source.is_file():
        raise ValueError(f"找不到备份文件：{source}")
    if (home / DATABASE_URL_FILE).is_file() and (home / DATABASE_URL_FILE).read_text().strip():
        raise ValueError("这个网页用的是外部 Postgres，要用 pg_restore 恢复")
    data = None
    try:
        with tarfile.open(source, "r:gz") as tar:
            names = tar.getnames()
            if web_backup.MEMBER in names:
                data = tar.extractfile(web_backup.MEMBER).read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ValueError(f"不是有效的 tar.gz：{type(exc).__name__}") from None
    if data is None and any(name.startswith(web_backup.PREFIX) for name in names):
        raise ValueError("这份备份里没有网页数据库")
    if data is None and not any(name.lstrip("/") in ("PG_VERSION", "base") or name.lstrip("/").startswith("base/") for name in names):
        raise ValueError("这份备份里没有网页数据库（要每日备份包，或 PGlite 的 tar.gz）")
    target = home / (DB_DIR + ".restore")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = web_backup.unpack(data if data is not None else source, target)
    (target / web_backup.MARKER).write_text(_iso(time.time()) + "\n")
    port = port_of_config(home)
    pid = None
    try:
        health = _get_json(f"http://127.0.0.1:{port}/healthz", 3)
        found = health.get("pid") if health.get("ok") is True else None
        if isinstance(found, int) and found > 1 and _is_page(found):
            os.kill(found, signal.SIGTERM)
            pid = found
    except (OSError, ValueError, urllib.error.URLError):
        pass
    message = (f"已给网页进程 {pid} 发 SIGTERM，Manager 几秒内拉起它，它会换上恢复的数据库（旧库留作 db.before-restore-<时间>）"
               if pid else "网页进程没在跑：已放好，下次它起来时换上恢复的数据库（旧库留作 db.before-restore-<时间>）")
    return {"restored": str(target), "files": files, "pid": pid, "message": message}


def port_of_config(home) -> int:
    """The loopback port web.json's base_url names (DEFAULT_PORT when it does not)."""
    try:
        return urlsplit(str(read_object(Path(home) / CONFIG_FILE).get("base_url") or "")).port or DEFAULT_PORT
    except (OSError, ValueError, TypeError):
        return DEFAULT_PORT


def _is_page(pid) -> bool:
    """Whether process ``pid`` is a page process (its command line has server/selfhost/main.js); True where /proc cannot say."""
    try:
        return str(ENTRY) in Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except FileNotFoundError:
        return not Path("/proc/self").exists()
    except OSError:
        return False


def prepare(data_home, port=DEFAULT_PORT, folder="", page_url="", *, public=(), public_port=DEFAULT_PUBLIC_PORT, bind=DEFAULT_BIND,
            tls_cert="", tls_key="") -> dict:
    """Make the data root ready for a self-hosted page: <data home>/web/ (0700), the key file (0600, a new random key; one that is
    there is kept), ``web.json`` (base_url on the loopback, key_file, push_seconds 1, poll_seconds 1; other fields of an existing one,
    ``page_url`` is ``page_url`` when given, else with ``public`` https://<its first address>:<public_port>/, else the one that is there, else
    ``http://127.0.0.1:<port>/``: the address the 打开网页 buttons of the Feishu cards open, core/web_sync.py ``page_url``). ``public``:
    addresses for the public HTTPS listener (ValueError for one that is not valid, or a certificate given without its key);
    the self-signed certificate is made now when ``folder`` has the page's command for it (``ensure_cert``). Returns {key_file, config,
    page_url, created_key, switches, public (``public_block`` or None), open_ports, fingerprint}: ``switches`` are the lines for the service manifest."""
    names = list(dict.fromkeys(str(name).strip() for name in public if str(name).strip()))
    for name in names:
        if not valid_name(name):
            raise ValueError(f"公网地址不合法：{name}（只认 IPv4、IPv6 不带方括号、域名）")
    if bool(tls_cert) != bool(tls_key):
        raise ValueError("证书和私钥要一起给")
    if tls_cert and not (Path(tls_cert).is_absolute() and Path(tls_key).is_absolute()):
        raise ValueError("证书和私钥要写绝对路径")
    if not 0 < int(public_port) < 65536:
        raise ValueError("公网端口要在 1 到 65535 之间")
    try:
        bind = str(ipaddress.ip_address(bind))
    except ValueError:
        raise ValueError(f"监听地址不合法：{bind}") from None
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
    block = public_block(home, names, int(public_port), bind, tls_cert, tls_key) if names else None
    if page_url:
        page = page_url
    elif block:
        page = f"https://{url_host(names[0])}:{block['port']}/"
    else:
        page = kept if web_sync.page_url_ok(kept) else f"http://127.0.0.1:{port}/"
    write_json(config, {**old, "base_url": f"http://127.0.0.1:{port}/openapi", "key_file": str(key), "push_seconds": 1, "poll_seconds": 1,
                        "page_url": page}, ensure_ascii=False, indent=2)
    os.chmod(config, 0o600)
    switches = ["COVEY_WEB=1", f"COVEY_WEB_CONFIG={config}", f"{ENV}=1"]
    if folder:
        switches.append(f"{DIR_ENV}={folder}")
    if port != DEFAULT_PORT:
        switches.append(f"{PORT_ENV}={port}")
    fingerprint = ""
    if block:
        switches.append(f"{PUBLIC_ENV}={','.join(names)}")
        if block["port"] != DEFAULT_PUBLIC_PORT:
            switches.append(f"{PUBLIC_PORT_ENV}={block['port']}")
        if bind != DEFAULT_BIND:
            switches.append(f"{BIND_ENV}={bind}")
        if tls_cert:
            switches += [f"{TLS_CERT_ENV}={tls_cert}", f"{TLS_KEY_ENV}={tls_key}"]
            fingerprint = fingerprint_of(tls_cert)
        else:
            made = ensure_cert(folder, data_home, names)
            fingerprint = str((made or {}).get("fingerprint") or "")
    return {"key_file": str(key), "config": str(config), "page_url": page, "created_key": created, "switches": switches,
            "public": block, "open_ports": [block["port"]] if block else [], "fingerprint": fingerprint}


def public_lines(result) -> list:
    """What a person is told once the page is reachable from outside: the port to open, the address, the certificate's fingerprint and
    how a browser trusts it the first time, and the three steps of 用飞书登录. [] without ``public``."""
    block = result.get("public")
    if not block:
        return []
    lines = ["", "公网直连（HTTPS）：",
             f"  1. 在防火墙和云服务器的安全组里放行 TCP 端口 {'、'.join(str(p) for p in result['open_ports'])}（监听地址 {block['bind']}）",
             "  2. 网页地址：" + "、".join(f"https://{url_host(name)}:{block['port']}/" for name in block["names"])]
    if block["tls"] == "self-signed":
        lines.append("  3. 用的是自签证书，浏览器第一次会警告“不安全”：" + (f"核对证书指纹 {result['fingerprint']}，" if result.get("fingerprint")
                     else "网页进程起来后在 /healthz（本机）里看证书指纹，") + "一致就点“高级”→“继续访问”（不同的话别继续）；有域名的话换成自己的证书（--tls-cert、--tls-key）就不会警告")
    else:
        lines.append("  3. 用的是你自己的证书" + (f"，指纹 {result['fingerprint']}" if result.get("fingerprint") else "") + "：证书到期前自己换新")
    lines += ["用飞书确认登录：",
              "  1. 在浏览器打开上面的网页地址，点“用飞书登录”，页面上会显示 4 位对照码",
              "  2. 在飞书和机器人的私聊里会收到「网页登录确认」卡，核对对照码、浏览器和来源地址",
              "  3. 对得上就点「允许」，网页随即进入；不是你发起的点「不是我」"]
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -B -m covey.service.web_selfhost",
                                     description="准备自托管网页工作台：开放接口密钥文件、web.json，并打印要在服务清单里设的开关")
    parser.add_argument("--data-root", help="数据根（默认 COVEY_DATA_HOME，没设时按代码目录推算）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"网页进程监听的本机端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--page-url", default="", help="你在浏览器里打开网页的地址（写进 web.json 的 page_url，飞书卡片的「打开网页」按钮用它）；"
                        "默认 http://127.0.0.1:<端口>/，公网直连时是第一个公网地址，已有的 page_url 不给这个参数时保留")
    parser.add_argument("--dir", default="", help="自托管构建产物目录（web/dist-selfhost，里面有 server/selfhost/main.js）；给了就写进要设的开关")
    parser.add_argument("--public", default="", metavar="ADDR[,ADDR]", help="公网直连：网页另开 HTTPS 监听，用这些地址（IPv4、IPv6、域名，逗号分隔）访问；"
                        "auto 在终端里用本机的公网地址问一次确认")
    parser.add_argument("--public-port", type=int, default=DEFAULT_PUBLIC_PORT, help=f"公网 HTTPS 端口（默认 {DEFAULT_PUBLIC_PORT}）")
    parser.add_argument("--bind", default=DEFAULT_BIND, help=f"公网监听地址（默认 {DEFAULT_BIND}）")
    parser.add_argument("--tls-cert", default="", help="自己的证书链（PEM，绝对路径，要和 --tls-key 一起给）；不给就用自签证书")
    parser.add_argument("--tls-key", default="", help="自己证书的私钥（PEM，绝对路径）")
    parser.add_argument("--restore-db", default="", metavar="PATH", help="只做恢复：从每日备份包（bridge-*.tar.gz）或 pglite.tar.gz 恢复网页数据库，"
                        "网页进程在跑就重启它换上")
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port 要在 1 到 65535 之间")
    if not 0 < args.public_port < 65536:
        parser.error("--public-port 要在 1 到 65535 之间")
    if args.page_url and not web_sync.page_url_ok(args.page_url):
        parser.error("--page-url 要以 http:// 或 https:// 开头，不含空白")
    if args.dir and not Path(args.dir).is_absolute():
        parser.error("--dir 要写绝对路径")
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert 和 --tls-key 要一起给")
    if args.tls_cert and not (Path(args.tls_cert).is_absolute() and Path(args.tls_key).is_absolute()):
        parser.error("--tls-cert、--tls-key 要写绝对路径")
    data_home = Path(args.data_root).expanduser().resolve() if args.data_root else paths.data_home()
    if args.restore_db:
        try:
            done = restore_db(args.restore_db, data_home)
        except ValueError as exc:
            print(f"恢复失败：{exc}", file=sys.stderr)
            return 1
        print(f"已解到 {done['restored']}（{done['files']} 个文件）")
        print(done["message"])
        return 0
    names = [name.strip() for name in args.public.split(",") if name.strip()]
    if names == ["auto"]:
        guess = suggest_address()
        if not guess:
            parser.error("--public auto：这台机器没有公网地址，请写明地址（IP 或域名）")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.error(f"--public auto 要在终端里确认；这里请写明地址（这台机器的公网地址像是 {guess}）")
        if input(f"用 {guess} 作为公网地址？[Y/n] ").strip().lower() in ("n", "no"):
            parser.error("请用 --public <地址> 写明")
        names = [guess]
    for name in names:
        if not valid_name(name):
            parser.error(f"--public 的地址不合法：{name}（只认 IPv4、IPv6 不带方括号、域名）")
    try:
        result = prepare(data_home, args.port, args.dir, args.page_url, public=names, public_port=args.public_port, bind=args.bind,
                         tls_cert=args.tls_cert, tls_key=args.tls_key)
    except ValueError as exc:
        parser.error(str(exc))
    print(("已生成新的开放接口密钥文件：" if result["created_key"] else "密钥文件已存在，没有覆盖：") + result["key_file"])
    print("已写网页配置：" + result["config"])
    print("网页地址 page_url：" + result["page_url"] + "（飞书看板、手上的事、早晚汇总卡片上的「打开网页」按钮打开它；从别的设备访问时用 --page-url 改成那边能打开的地址）")
    print("在服务清单里设这些开关，然后重新注册服务（docs/configuration.md「改开关三步」）：")
    for line in result["switches"]:
        print("  " + line)
    if not args.dir:
        print(f"  {DIR_ENV}=<自托管构建产物目录的绝对路径>")
    if result["public"]:
        print("\n".join(public_lines(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
