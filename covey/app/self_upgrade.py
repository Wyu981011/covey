"""网页上点一下就升级 (docs/web.md 版本与更新, data contract v39): whether this deployment has a newer version, and its upgrade
started from the page and carried on through the Bridge's own restart.

The core does not know how a deployment is upgraded (a release with extensions is upgraded by the extension's installer, docs/deploy.md
升级与回滚). The installer that can upgrade it writes ``<data home>/upgrade.json``, ``{"by", "status": [argv], "run": [argv]}``:
``status`` prints one line of JSON at its end and changes nothing (``{live, latest, bridge, web, count, changes, blocked}``: the
release the service runs and the one an upgrade would deploy, whether the Bridge and the web page would change, the new commits, why
an upgrade cannot start now); ``run`` upgrades (pulls the checkouts, the deploy pre-check, the deploy, the web page) and exits 0 all
done, 4 the Bridge upgraded and the page not, 3 another deploy running, anything else not done. Without the file (a core-only
install, an extension's installer before it wrote one) nothing here runs: no thread, no ``upgrade`` in the page's ``ops``, no item
(AGENTS.md rule 4).

``check`` runs ``status`` (at most STATUS_SECONDS, one at a time) and keeps its answer in ``<state>/upgrade/status.json``; the
``web-upgrade`` thread (app/web_sync.py) checks CHECK_SECONDS apart, and soon after an upgrade from the page ended. ``start`` runs
``run`` in a process of its own session (app/runner_spawn.py's way: the Bridge's restart, which is the upgrade's own deploy, never
reaches it) under a wrapper that writes its end into ``<state>/upgrade/run.json``; the new Bridge reads it there. ``view`` is the
``settings`` item ``upgrade`` the page draws. ``shared`` is the one SelfUpgrade of a state directory: the page's and the daily automatic
upgrade's (app/auto_upgrade.py, COVEY_AUTO_UPGRADE) checks never run at once. No Feishu call, no model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from covey.core.paths import data_home

CONFIG = "upgrade.json"  # Under the data home: written by the installer that can upgrade this deployment.
FOLDER = "upgrade"  # Under the state dir: status.json (the last check), run.json (the last upgrade from the page).
CHECK_SECONDS = 6 * 3600  # Between two checks of the thread.
FIRST_CHECK_SECONDS = 120  # After the Bridge starts: not in the minute a deploy checks it is up.
AFTER_RUN_SECONDS = 30  # After an upgrade from the page ended: what is new now, so the page stops offering it.
STATUS_SECONDS = 180  # A check fetches two repositories.
SPAWN_SECONDS = 30  # A run whose wrapper has not written its pid yet counts as under way this long after its start.
CHANGES = 20  # The newest commits the page lists.
TAIL = 8  # The last lines of an upgrade's output kept for the page.
DONE, PARTIAL, FAILED = "done", "partial", "failed"
RUNNING = "running"
WEB_UNDONE, DEPLOY_RUNNING = 4, 3  # The exit codes ``run`` gives meaning to (the extension's dev/install.py upgrade).
# The wrapper of ``run``: its output into the log, then its end written over ``<state>/upgrade/run.json`` (stdlib only, no file of
# this release needed: the release it started from may be gone from the service by the time it ends).
WRAPPER = r"""
import json, os, subprocess, sys, time
record, log, argv = sys.argv[1], sys.argv[2], sys.argv[3:]


def update(**fields):
    try:
        with open(record) as got:
            row = json.load(got)
    except (OSError, ValueError):
        row = {}
    row.update(fields)
    with open(record + ".tmp", "w") as out:
        json.dump(row, out, ensure_ascii=False)
    os.replace(record + ".tmp", record)


update(pid=os.getpid())
with open(log, "ab") as out:
    try:
        code = subprocess.call(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    except OSError as exc:
        out.write(f"{type(exc).__name__}: {exc}\n".encode())
        code = 127
try:
    with open(log, errors="replace") as got:
        tail = [line.rstrip() for line in got.read().splitlines() if line.strip()][-%d:]
except OSError:
    tail = []
update(code=code, finished_at=time.time(), tail=tail)
""" % TAIL


_shared: dict = {}
_shared_lock = threading.Lock()


def shared(state_dir, log=lambda text: None) -> "SelfUpgrade":
    """The SelfUpgrade of ``state_dir`` this process shares (made at the first call, with that call's ``log``)."""
    key = str(Path(state_dir).resolve())
    with _shared_lock:
        found = _shared.get(key)
        if found is None:
            found = _shared[key] = SelfUpgrade(state_dir, log)
        return found


def config(home=None) -> dict | None:
    """``{"by", "status", "run"}`` of ``<data home>/upgrade.json`` when both are commands (lists of words, the first an absolute
    path); None when there is none or it is not that."""
    try:
        found = json.loads((Path(home) if home else data_home()).joinpath(CONFIG).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict):
        return None
    for name in ("status", "run"):
        argv = found.get(name)
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv) and os.path.isabs(argv[0])):
            return None
    return {"by": str(found.get("by") or ""), "status": list(found["status"]), "run": list(found["run"])}


def read(path) -> dict:
    try:
        found = json.loads(Path(path).read_text())
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def write(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, path)


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def last_json(text) -> dict:
    """The last line of ``text`` that is a JSON object; {} when none is."""
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict):
                return found
    return {}


def clean_status(found) -> dict:
    """What the page reads of ``status``'s answer, each field of its type (a newer installer's extra fields are dropped)."""
    web = found.get("web") if isinstance(found.get("web"), dict) else None
    changes = []
    for each in found.get("changes") or ():
        if isinstance(each, dict) and each.get("subject"):
            at = each.get("at")
            changes.append({"repo": str(each.get("repo") or "")[:60], "sha": str(each.get("sha") or "")[:12],
                            "subject": str(each["subject"])[:300],
                            "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else 0})
    count = found.get("count")
    return {"live": str(found.get("live") or ""), "latest": str(found.get("latest") or ""),
            "bridge": found.get("bridge") is True,
            "web": None if web is None else {"kind": str(web.get("kind") or ""), "current": web.get("current") is True,
                                             "manual": web.get("manual") is True},
            "count": count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else len(changes),
            "changes": changes[:CHANGES], "blocked": str(found.get("blocked") or "")[:300]}


def available(status) -> bool:
    """Whether an upgrade would change something: the Bridge, or a page the upgrade updates that is not at the latest yet."""
    web = status.get("web") or {}
    return bool(status.get("latest")) and (status.get("bridge") is True
                                           or (bool(web) and not web.get("current") and not web.get("manual")))


def outcome(run) -> tuple:
    """(state, message) of an upgrade from the page that ended, by its exit code and the last lines it said. The message is the
    detail only: the page says the state itself (上次更新好了, 只更新了机器人, 没更新成)."""
    code, tail = run.get("code"), [str(line).strip() for line in run.get("tail") or ()]

    def said(*starts):
        return next((line for line in reversed(tail) if line.startswith(starts)), "")
    if code == 0:
        return DONE, "Bridge 和网页都是新版" + ("，网页刷新一下就能看到" if said("[网页] 更新好了") else "")
    if code == WEB_UNDONE:
        why = said("[网页] 没更新上", "[网页]").removeprefix("[网页]").strip()
        if why.startswith("没更新上") and "：" in why:
            why = why.split("：", 1)[1].strip()  # "没更新上（Bridge 已经是新版，不用回滚）：<原因>"
        return PARTIAL, why or "原因看日志"
    if code == DEPLOY_RUNNING:
        return FAILED, "另一个部署正在跑，什么都没换：等它结束再点一次"
    why = said("停在这里", "预检没过", "部署没有全部通过") or (tail[-1] if tail else "")
    return FAILED, why or f"退出码 {code}，原因看日志"


class SelfUpgrade:
    """This deployment's upgrade from the page. ``state_dir``: the Bridge's; ``home``: the data home (``data_home()`` by default);
    ``log(text)``: the Bridge's log."""

    def __init__(self, state_dir, log=lambda text: None, home=None, popen=subprocess.Popen, run=subprocess.run,
                 clock=time.time) -> None:
        self.folder = Path(state_dir) / FOLDER
        self.home = Path(home) if home else None
        self.log, self.popen, self.run_status, self.clock = log, popen, run, clock
        self.check_lock = threading.Lock()  # One check at a time: the thread's, the page's 检查更新, the one before an upgrade.
        self.checking = False
        self.started = clock()

    def config(self) -> dict | None:
        return config(self.home)

    def on(self) -> bool:
        return self.config() is not None

    @property
    def status_path(self) -> Path:
        return self.folder / "status.json"

    @property
    def run_path(self) -> Path:
        return self.folder / "run.json"

    # -- checking --------------------------------------------------------------------------------------------------------

    def check(self) -> dict:
        """Run ``status`` once (or wait for the one running) and keep its answer; the status kept, with ``error`` when this one failed
        (the fields of the check before stay). Never raises."""
        cfg = self.config()
        if cfg is None:
            return {}
        if not self.check_lock.acquire(blocking=False):
            with self.check_lock:  # Another one runs: its answer is this one's.
                return read(self.status_path)
        self.checking = True
        try:
            if self.running():
                return read(self.status_path)  # It pulls the checkouts: a check now would read them half way.
            kept = read(self.status_path)
            try:
                done = self.run_status(cfg["status"], capture_output=True, text=True, timeout=STATUS_SECONDS,
                                       stdin=subprocess.DEVNULL, cwd=str(self.home or data_home()))
                found = last_json(done.stdout)
                error = "" if found else (" ".join((done.stderr or done.stdout or "").split())[-300:]
                                          or f"检查没有结果（退出码 {done.returncode}）")
            except subprocess.TimeoutExpired:
                found, error = {}, f"检查超过 {STATUS_SECONDS} 秒没结束（取不到两个库的新提交？）"
            except OSError as exc:
                found, error = {}, f"检查没能运行：{type(exc).__name__}"
            status = {**kept, **clean_status(found)} if found else dict(kept)
            status.update(checked_at=self.clock(), error=error[:300])
            write(self.status_path, status)
            if error:
                self.log(f"self upgrade: check failed: {error[:200]}")
            return status
        finally:
            self.checking = False
            self.check_lock.release()

    def due(self, now=None) -> bool:
        """Whether the thread checks now: the first time FIRST_CHECK_SECONDS after the start, then CHECK_SECONDS apart, and
        AFTER_RUN_SECONDS after an upgrade from the page ended later than the last check."""
        now = self.clock() if now is None else now
        checked = read(self.status_path).get("checked_at") or 0
        run = read(self.run_path)
        if run.get("finished_at") and run["finished_at"] > checked and now - run["finished_at"] >= AFTER_RUN_SECONDS:
            return True
        if self.running():
            return False
        if now - self.started < FIRST_CHECK_SECONDS:
            return False
        return now - checked >= CHECK_SECONDS

    # -- the upgrade -----------------------------------------------------------------------------------------------------

    def running(self) -> dict | None:
        """The upgrade from the page under way: ``run.json`` with no end and its wrapper alive."""
        run = read(self.run_path)
        if run.get("state") != RUNNING or "code" in run:
            return None
        if run.get("pid"):
            return run if alive(run["pid"]) else None
        return run if self.clock() - (run.get("started_at") or 0) < SPAWN_SECONDS else None

    def start(self, op_id, status=None, by="page") -> str:
        """Check (or take ``status``, a check made just now), then start ``run`` for the operation ``op_id``: the page's, or
        ``by`` "auto" the daily automatic upgrade's (app/auto_upgrade.py); what the ack says. ValueError: nothing started, and why."""
        cfg = self.config()
        if cfg is None:
            raise ValueError("这台 Covey 没配网页上升级（数据根里没有 upgrade.json）：在终端里按安装说明升级")
        if self.running():
            raise ValueError("已经在升级了：等它做完")
        status = self.check() if status is None else status
        if status.get("error") and not status.get("latest"):
            raise ValueError(f"查不到新版本：{status['error']}")
        if status.get("blocked"):
            raise ValueError(f"现在不能升级：{status['blocked']}")
        if not available(status):
            raise ValueError("已经是最新，不用升级")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
        log = (self.home or data_home()) / "deploy-runs" / f"{stamp}-{'auto' if by == 'auto' else 'page'}" / "upgrade.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        record = {"state": RUNNING, "op_id": str(op_id), "by": str(by), "started_at": self.clock(), "log": str(log),
                  "from": status.get("live") or "", "to": status.get("latest") or ""}
        write(self.run_path, record)
        argv = [sys.executable, "-B", "-I", "-c", WRAPPER, str(self.run_path), str(log), *cfg["run"]]
        try:
            # Its own session: the deploy it does restarts this Bridge, and stopping the Bridge's process group never reaches it.
            process = self.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 cwd=str(log.parent), start_new_session=True)
        except OSError as exc:
            write(self.run_path, {**record, "code": 127, "finished_at": self.clock(), "tail": [f"{type(exc).__name__}: {exc}"]})
            raise ValueError(f"升级没能开始：{type(exc).__name__}") from None
        threading.Thread(target=process.wait, daemon=True, name="self-upgrade-reaper").start()
        self.log(f"self upgrade: started pid={process.pid} {record['from']} -> {record['to']}")
        to = f" {record['to']}" if record["to"] else ""
        return f"开始升级到{to}：机器人会重启几秒（在跑的任务不中断），网页要重新部署，几分钟后刷新页面"

    # -- what the page reads ---------------------------------------------------------------------------------------------

    def view(self) -> dict:
        """The ``settings`` item ``upgrade`` (data contract v39, docs/web.md 版本与更新)."""
        status, run = read(self.status_path), read(self.run_path)
        shown = clean_status(status)
        running = self.running()
        last = None
        if "code" in run:
            state, message = outcome(run)
            last = {"state": state, "message": message, "at": run.get("finished_at") or 0, "release": run.get("to") or "",
                    "log": run.get("log") or "", "tail": [str(line)[:300] for line in run.get("tail") or ()][-TAIL:]}
        elif run.get("state") == RUNNING and running is None:
            last = {"state": FAILED, "message": "升级进程不见了，没有留下结果（结果不确定）：看日志", "at": run.get("started_at") or 0,
                    "release": run.get("to") or "", "log": run.get("log") or "", "tail": []}
        return {**shown, "available": available(shown) and running is None,
                "checked_at": status.get("checked_at") or 0, "checking": self.checking, "error": str(status.get("error") or ""),
                "running": None if running is None else {"op_id": running.get("op_id") or "",
                                                          "started_at": running.get("started_at") or 0,
                                                          "log": running.get("log") or ""},
                "last": last}

    def stamps(self) -> tuple:
        """What ``view`` reads, by stat: the page's item is built again only when one changed (or a full look)."""
        out = [self.checking]
        for path in (self.status_path, self.run_path):
            try:
                info = path.stat()
                out.append((info.st_mtime_ns, info.st_size, info.st_ino))
            except OSError:
                out.append(None)
        out.append(self.running() is not None)
        return tuple(out)
