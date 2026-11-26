"""额度来源 (docs/quota.md): who gives the snapshots core/quota.py keeps, and reading one. Standard library only.

- The gateway Claude Code signs in to (``gateway``): its ``ANTHROPIC_BASE_URL`` and key, from the process's environment,
  else the ``env`` of its user settings.json (as core/same_account.py reads them). Only an https address is asked, and
  only its own origin: ``https://<host>/covey/quota`` with that key in ``x-api-key`` and ``Authorization: Bearer``; no
  redirect is followed, and the answer is read up to quota.MAX_BYTES. A 404 means the gateway has no such address:
  nothing is said and it is asked again ABSENT_SECONDS later. Nobody configures it.
- ``quota-sources.json`` in the data home (``configured``): ``{"sources": [{"id", "kind": "command", "argv": [...],
  "interval", "timeout"}, {"id", "kind": "url", "url": "https://…", "token_file": "/absolute/…", "interval",
  "timeout"}]}``. It names commands to run, so it is read only when it is this user's and nobody else may write it
  (``owned``); a url source sends its token (read from its file) to its own address alone, and never the model's key.
- ``read(source)``: the snapshot, parsed; SourceError says why not (a command's exit status, its timeout, after which its
  whole process group is killed, an answer too large or not a snapshot).
- ``refresh(state_dir, ...)``: the sources that are due read and their snapshots (or why not) kept; each under a lock file
  of its own that is not waited on, so a source another process is reading is left to it. COVEY_QUOTA=0 (or off) turns
  every source off: nothing is read and nothing is asked.

agy's accounts are a source of their own (backends/agy/accounts.py ``snapshots``): written from the accounts' state,
never asked here.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from covey.core import env as cenv
from covey.core import quota
from covey.core.file_lock import file_lock
from covey.core.paths import data_home
from covey.core.state import ensure_private_dir

SWITCH = "COVEY_QUOTA"  # On unset; 0, off, false or no turns every quota source off.
CONFIG_FILE = "quota-sources.json"  # Under the data home.
GATEWAY_PATH = "/covey/quota"
INTERVAL, MIN_INTERVAL = 300, 60  # Seconds between reads of a source.
TIMEOUT, MAX_TIMEOUT = 30, 120
GATEWAY_TIMEOUT = 10
ABSENT_SECONDS = 6 * 3600  # A gateway without /covey/quota is asked again after this long.
FAILED_SECONDS = 60  # A source that failed is read again no sooner than this (unless asked to).
MAX_SOURCES = 20
USER_AGENT = "covey-quota/1"


class SourceError(RuntimeError):
    """A read that gave no snapshot. ``absent``: the source has none at all (a gateway's 404)."""

    def __init__(self, why, *, absent=False):
        super().__init__(why)
        self.absent = absent


@dataclasses.dataclass(frozen=True)
class Source:
    id: str
    kind: str  # quota.SOURCE_KINDS but agy.
    argv: tuple = ()
    url: str = ""
    token_file: str = ""
    interval: int = INTERVAL
    timeout: int = TIMEOUT
    title: str = ""
    key: str = dataclasses.field(default="", repr=False)  # A gateway's: the model key Claude Code signs in with.


def enabled(environ=None) -> bool:
    return str(cenv.get(SWITCH, "1", environ) or "1").strip().lower() not in ("0", "off", "false", "no")


def config_path() -> Path:
    return data_home() / CONFIG_FILE


def owned(path) -> str:
    """'' when ``path`` is this user's and nobody else may write it (nor the directory it is in), else why not."""
    try:
        for each in (Path(path), Path(path).parent):
            info = each.stat()
            if info.st_uid != os.geteuid():
                return f"{each} 不是你的"
            if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return f"{each} 别人也能写（chmod go-w）"
    except OSError as exc:
        return f"{path} 读不了：{type(exc).__name__}"
    return ""


def _number(row, key, default, low, high, where):
    value = row.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{where}.{key} 要是 {low} 到 {high} 的整数")
    return value


def configured(path=None) -> list:
    """The sources ``quota-sources.json`` names; [] without the file. ValueError when it may not be used (``owned``) or
    is not right; the message names the source and the field."""
    path = Path(path) if path is not None else config_path()
    if not path.exists():
        return []
    problem = owned(path)
    if problem:
        raise ValueError(problem)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} 读不了：{type(exc).__name__}") from None
    rows = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_SOURCES:
        raise ValueError(f"{path} 要有不超过 {MAX_SOURCES} 个的 sources 列表")
    found, ids = [], set()
    for number, row in enumerate(rows):
        where = f"sources[{number}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where} 要是对象")
        source = str(row.get("id") or "")
        if not quota.SOURCE_ID.fullmatch(source) or source.startswith(("agy", "gateway")) or source in ids:
            raise ValueError(f"{where}.id 要是不重复的小写字母、数字、点、横线（不以 agy、gateway 开头）")
        ids.add(source)
        interval = _number(row, "interval", INTERVAL, MIN_INTERVAL, 86400, where)
        timeout = _number(row, "timeout", TIMEOUT, 1, MAX_TIMEOUT, where)
        title = quota.scrub(row.get("title"), quota.TITLE_CHARS) if row.get("title") else ""
        kind = row.get("kind")
        if kind == "command":
            argv = row.get("argv")
            if (not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv)
                    or not Path(argv[0]).is_absolute()):
                raise ValueError(f"{where}.argv 要是列表，第一项是绝对路径")
            found.append(Source(source, "command", argv=tuple(argv), interval=interval, timeout=timeout, title=title))
        elif kind == "url":
            url, token = str(row.get("url") or ""), str(row.get("token_file") or "")
            if not quota.link_ok(url):
                raise ValueError(f"{where}.url 要是 https 地址")
            if token and not Path(token).is_absolute():
                raise ValueError(f"{where}.token_file 要是绝对路径")
            found.append(Source(source, "url", url=url, token_file=token, interval=interval, timeout=timeout,
                                title=title))
        else:
            raise ValueError(f"{where}.kind 要是 command 或 url")
    return found


def claude_login(environ=None):
    """(base URL, key) Claude Code signs in with: the process's environment first, then its user settings.json's
    ``env``; None when it names no address of its own (the vendor's sign-in) or no key."""
    from covey.core.claude_retention import settings_path

    environ = os.environ if environ is None else environ
    env = {}
    with contextlib.suppress(OSError, ValueError, AttributeError):
        found = json.loads(settings_path(environ).read_text()).get("env")
        env = found if isinstance(found, dict) else {}
    url = str(environ.get("ANTHROPIC_BASE_URL") or env.get("ANTHROPIC_BASE_URL") or "").strip()
    key = str(environ.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_AUTH_TOKEN") or environ.get("ANTHROPIC_API_KEY")
              or env.get("ANTHROPIC_API_KEY") or "").strip()
    return (url, key) if url and key else None


def gateway_url(base_url) -> str:
    """``https://<host>/covey/quota`` of an https ``base_url``; '' for any other (the key goes to its own origin alone)."""
    parts = urlsplit(str(base_url or "").strip())
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        return ""
    return f"https://{parts.netloc.lower()}{GATEWAY_PATH}"


def gateway_id(url) -> str:
    return "gateway-" + hashlib.sha256(url.encode()).hexdigest()[:10]


def gateway(environ=None):
    """The Source of the gateway Claude Code signs in to (see the module docstring), None when there is none to ask."""
    login = claude_login(environ)
    url = gateway_url(login[0]) if login else ""
    if not url:
        return None
    return Source(gateway_id(url), "gateway", url=url, interval=INTERVAL, timeout=GATEWAY_TIMEOUT,
                  title="Claude · 网关", key=login[1])


def sources(environ=None) -> tuple:
    """(sources, problem): the gateway's (when there is one) and the configured ones; ``problem`` says why the file's
    could not be used ('' when they could)."""
    if not enabled(environ):
        return [], ""
    found = [s for s in (gateway(environ),) if s is not None]
    try:
        found += configured()
    except ValueError as exc:
        return found, str(exc)
    return found, ""


def no_redirect():
    """An opener handler that follows no redirect: the 3xx raises as an HTTPError, so a key never follows an address
    elsewhere. urllib is imported here, when a source is read: a task runner that never reads one never loads it."""
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    return NoRedirect


def _decode(raw) -> dict:
    if len(raw) > quota.MAX_BYTES:
        raise SourceError(f"快照超过 {quota.MAX_BYTES // 1024} KB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SourceError("输出不是 JSON") from None
    try:
        return quota.parse(data)
    except ValueError as exc:
        raise SourceError(f"不是额度快照：{exc}") from None


def _get(source) -> bytes:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if source.kind == "gateway":
        headers.update({"x-api-key": source.key, "Authorization": f"Bearer {source.key}"})
    elif source.token_file:
        try:
            token = Path(source.token_file).read_text().strip()
        except OSError as exc:
            raise SourceError(f"令牌文件读不了：{type(exc).__name__}") from None
        if token:
            headers["Authorization"] = f"Bearer {token}"
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(no_redirect())
    request = urllib.request.Request(source.url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=source.timeout) as response:
            return response.read(quota.MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SourceError(f"HTTP {exc.code}", absent=source.kind == "gateway" and exc.code == 404) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SourceError(f"连不上：{type(reason).__name__}") from None


def _run(source) -> bytes:
    try:
        process = subprocess.Popen(list(source.argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True, cwd="/")
    except OSError as exc:
        raise SourceError(f"命令不能运行：{exc.strerror or type(exc).__name__}") from None
    try:
        out, _ = process.communicate(timeout=source.timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)  # The command's whole group, which it leads.
        process.communicate()
        raise SourceError(f"命令 {source.timeout} 秒没有结束") from None
    if process.returncode != 0:
        raise SourceError(f"命令退出码 {process.returncode}")
    return out


def read(source) -> dict:
    """The snapshot ``source`` gives now (parsed); SourceError when it gives none."""
    return _decode(_run(source) if source.kind == "command" else _get(source))


def due(entry, source, now) -> bool:
    """Whether ``source`` (its last ``entry``) is to be read at ``now``."""
    last = float(entry.get("read_at") or 0)
    if entry.get("absent"):
        return now - last >= ABSENT_SECONDS
    wait = source.interval if not entry.get("error") else max(FAILED_SECONDS, min(source.interval, 300))
    return now - last >= wait


def refresh(state_dir, found=None, *, only=(), force=False, now=None) -> list:
    """Read the sources ``found`` (default ``sources()``'s) that are due (all of ``only`` when it names ids, each one
    whatever its time with ``force``), keeping each snapshot or why not; the ids read. Never raises for a source."""
    if found is None:
        found, _problem = sources()
    store, done = quota.Store(state_dir), []
    for source in found:
        if only and source.id not in only:
            continue
        now_ = time.time() if now is None else now
        if not force and not due(store.read(source.id), source, now_):
            continue
        ensure_private_dir(store.folder)
        try:
            with file_lock(store.folder / f".{source.id}.lock", operation=fcntl.LOCK_EX | fcntl.LOCK_NB):
                take(store, source, now)
        except BlockingIOError:
            continue  # Another process is reading it.
        except OSError:
            continue
        done.append(source.id)
    return done


def take(store, source, now=None) -> dict:
    """Read ``source`` once and keep what it gave in ``store``; the entry as written."""
    try:
        snapshot = read(source)
    except SourceError as exc:
        return store.failed(source.id, source.kind, str(exc), title=source.title, absent=exc.absent, now=now)
    except Exception as exc:  # Never a source's failure beyond its own entry.
        return store.failed(source.id, source.kind, f"读取出错：{type(exc).__name__}", title=source.title, now=now)
    return store.saved(source.id, source.kind, snapshot, title=source.title, now=now)


def forget_gone(state_dir, found) -> None:
    """Drop the entries of command, url and gateway sources no longer there (agy's are its own)."""
    ids = {s.id for s in found}
    store = quota.Store(state_dir)
    for entry in store.entries():
        if entry.get("kind") in ("command", "url", "gateway") and entry.get("source") not in ids:
            store.forget(entry["source"])
