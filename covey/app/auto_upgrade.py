"""定时自动升级 (docs/deploy.md 定时自动升级): with COVEY_AUTO_UPGRADE=HH:MM (Asia/Shanghai, as the 早晚汇总) and an upgrader set
up (``<data home>/upgrade.json``, app/self_upgrade.py), the Bridge upgrades itself and the web page once a day at that time, the
safe way only:

- it checks first (the upgrader's ``status``) and upgrades only to a newer version, when nothing blocks it (``blocked``: a person
  has to do something first; said once, tried again the next day);
- while a task runs or a restart would interrupt one (app/detached.py: live runners, ``restart_blockers``) it waits RETRY_SECONDS
  and looks again, RETRIES times at most, then leaves it for the next day: it never forces a restart;
- the upgrade itself is the page's (SelfUpgrade.start: the upgrader's ``run``, whose deploy pre-check comes before anything changes);
  one that did not go through is said, never rolled back: another deploy running (exit 3) or a task found at its pre-check waits
  like a busy Bridge, anything else is left as it is for a person to read the log.

Each day's attempt is ``<state>/upgrade/auto.json``, so the Bridge the upgrade restarted carries it on: it reads how the run
ended (``run.json``) and tells the owner in the private chat in one text message, out of the quiet hours (core/quiet_hours.py).
Nothing is said for a day with nothing newer. Without the switch or without an upgrader there is no thread (AGENTS.md rule 4)."""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from covey.app import detached, self_upgrade
from covey.core import env as cenv
from covey.core import quiet_hours
from covey.core.locks import resource_lock

ENV = "COVEY_AUTO_UPGRADE"
RECORD = "auto.json"  # Under <state>/upgrade/, beside app/self_upgrade.py's status.json and run.json.
TICK_SECONDS = 60
WINDOW_SECONDS = 2 * 3600  # A day's attempt starts in this long after its time: a Bridge down then does not upgrade at noon.
RETRY_SECONDS = 15 * 60
RETRIES = 3  # Looks again after the first, RETRY_SECONDS apart, while busy (or another deploy runs).
CHANGES_SAID = 5
# A day's states. WAITING: a look is due at ``next_at``; STARTED: the upgrade of ``op_id`` runs. The others end the day.
WAITING, STARTED = "waiting", "started"
DONE, PARTIAL, FAILED, BLOCKED, CURRENT, GAVE_UP, OTHER = "done", "partial", "failed", "blocked", "current", "gave_up", "other"
ENDED = (DONE, PARTIAL, FAILED, BLOCKED, CURRENT, GAVE_UP, OTHER)
SILENT = (CURRENT, OTHER)  # Nothing to tell: nothing newer; the page's own upgrade took over.
# What a run's tail says when its pre-check found a task a restart would interrupt (scripts/upgrade.sh, the extension's installer).
BUSY_WORDS = ("restart_blockers", "有任务重启会被打断")


def at(environ=None):
    """(hour, minute) of COVEY_AUTO_UPGRADE, None when unset, off or not HH:MM."""
    raw = str(cenv.get(ENV, "", environ) or "").strip()
    match = quiet_hours.TIME.fullmatch(raw)
    return (int(match.group(1)), int(match.group(2))) if match else None


def enabled(environ=None) -> bool:
    return at(environ) is not None


def slot(now, hour, minute) -> float:
    """The day's time ``hour``:``minute`` of the day ``now`` is in (Asia/Shanghai), epoch seconds."""
    local = datetime.datetime.fromtimestamp(now, quiet_hours.ZONE)
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def day_of(now) -> str:
    return datetime.datetime.fromtimestamp(now, quiet_hours.ZONE).strftime("%Y-%m-%d")


def clock_words(hour, minute) -> str:
    return f"{hour:02d}:{minute:02d}"


def busy_words(state_dir) -> str:
    """Why a restart now is not for an unattended upgrade: tasks running (their task runners alive), or jobs a restart would
    interrupt (app/detached.py restart_blockers); '' when neither."""
    state_dir = Path(state_dir)
    running, blockers = len(detached.live_keys(state_dir)), len(detached.restart_blockers(state_dir))
    if blockers:
        return f"{blockers} 个任务重启会被打断"
    if running:
        return f"{running} 个任务在跑"
    return ""


class AutoUpgrade:
    """The daily automatic upgrade of one Bridge. ``upgrader``: its SelfUpgrade (self_upgrade.shared); ``busy()``: why not now ('' when
    nothing runs, ``busy_words``); ``notify(text)``: sends one message to the owner, True when it went out, None when there is no
    owner's chat to send it to (nothing sent); ``log(line)``."""

    def __init__(self, upgrader, *, busy, notify, log=lambda text: None, clock=time.time, environ=None) -> None:
        self.upgrader, self.busy, self.notify, self.log, self.clock, self.environ = upgrader, busy, notify, log, clock, environ

    @property
    def path(self) -> Path:
        return self.upgrader.folder / RECORD

    def read(self) -> dict:
        return self_upgrade.read(self.path)

    def write(self, record) -> None:
        with resource_lock("record", self.upgrader.folder):
            self_upgrade.write(self.path, record)

    # -- one look ---------------------------------------------------------------------------------------------------------

    def step(self, now=None) -> str:
        """One look of the thread: carry today's attempt on, then tell the owner what ended, out of the quiet hours. What it did, for
        the log and the tests ('' nothing)."""
        now = self.clock() if now is None else now
        when = at(self.environ)
        if when is None:
            return ""
        record = self.read()
        did = self.advance(record, now, when)
        record = self.read()
        if record.get("state") in ENDED and record.get("state") not in SILENT and not record.get("told"):
            self.tell(record, now, when)
        return did

    def advance(self, record, now, when) -> str:
        today, start = day_of(now), slot(now, *when)
        if record.get("state") == STARTED:
            return self.settle(record, now)
        if record.get("day") != today:
            if not start <= now < start + WINDOW_SECONDS:
                return ""
            record = {"day": today, "state": WAITING, "tries": 0, "next_at": start}
            self.write(record)
        if record.get("state") != WAITING or now < float(record.get("next_at") or 0):
            return ""
        if now >= start + WINDOW_SECONDS:  # The Bridge was down since the last look: not in the middle of the day.
            self.write({**record, "state": GAVE_UP, "why": str(record.get("why") or "错过了时间"), "ended_at": now})
            return GAVE_UP
        if self.upgrader.running():
            return self.later(record, now, "网页上点的升级正在跑")
        status = self.upgrader.check()
        if status.get("error") and not status.get("latest"):
            return self.later(record, now, f"查不到新版本：{status['error']}")
        if not self_upgrade.available(status):
            self.write({**record, "state": CURRENT, "ended_at": now})
            self.log("auto upgrade: already the newest")
            return CURRENT
        if status.get("blocked"):
            self.write({**record, "state": BLOCKED, "why": str(status["blocked"])[:300], "ended_at": now})
            self.log(f"auto upgrade: blocked: {str(status['blocked'])[:200]}")
            return BLOCKED
        busy = self.busy()
        if busy:
            return self.later(record, now, busy)
        op_id = f"auto-{record['day']}-{int(record.get('tries') or 0)}"
        try:
            self.upgrader.start(op_id, status=status, by="auto")
        except ValueError as exc:  # Blocked, newest, running: what the check before said, changed in between.
            return self.later(record, now, str(exc))
        changes = [str(row.get("subject") or "") for row in status.get("changes") or () if isinstance(row, dict)]
        self.write({**record, "state": STARTED, "op_id": op_id, "started_at": now, "from": status.get("live") or "",
                    "to": status.get("latest") or "", "count": status.get("count") or len(changes),
                    "changes": changes[:CHANGES_SAID]})
        self.log(f"auto upgrade: started {op_id} {status.get('live') or '?'} -> {status.get('latest') or '?'}")
        return STARTED

    def later(self, record, now, why) -> str:
        """Look again RETRY_SECONDS from now, or give the day up after RETRIES."""
        tries = int(record.get("tries") or 0) + 1
        if tries > RETRIES:
            self.write({**record, "state": GAVE_UP, "tries": tries, "why": str(why)[:300], "ended_at": now})
            self.log(f"auto upgrade: gave up for today: {str(why)[:200]}")
            return GAVE_UP
        self.write({**record, "state": WAITING, "tries": tries, "why": str(why)[:300], "next_at": now + RETRY_SECONDS})
        self.log(f"auto upgrade: later ({tries}/{RETRIES}): {str(why)[:200]}")
        return WAITING

    def settle(self, record, now) -> str:
        """The upgrade this started: still running, or how it ended (``run.json``)."""
        if self.upgrader.running():
            return ""
        run = self_upgrade.read(self.upgrader.run_path)
        if run.get("op_id") != record.get("op_id"):
            self.write({**record, "state": OTHER, "ended_at": now})  # The page's upgrade came after it: that one says its end.
            return OTHER
        if "code" not in run:
            self.write({**record, "state": FAILED, "why": "升级进程不见了，没有留下结果（结果不确定）", "log": run.get("log") or "",
                        "ended_at": now})
            return FAILED
        state, message = self_upgrade.outcome(run)
        tail = " ".join(str(line) for line in run.get("tail") or ())
        if run.get("code") == self_upgrade.DEPLOY_RUNNING or (state == self_upgrade.FAILED and any(w in tail for w in BUSY_WORDS)):
            return self.later({**record, "state": WAITING, "op_id": ""}, now, message)  # Nothing changed: like a busy Bridge.
        ended = {self_upgrade.DONE: DONE, self_upgrade.PARTIAL: PARTIAL}.get(state, FAILED)
        self.write({**record, "state": ended, "why": message[:300], "log": run.get("log") or "", "code": run.get("code"),
                    "ended_at": now})
        self.log(f"auto upgrade: {ended} code={run.get('code')}")
        return ended

    # -- telling the owner ------------------------------------------------------------------------------------------------

    def tell(self, record, now, when) -> None:
        """The day's end in one message, out of the quiet hours; written as being sent first, never sent again (AGENTS.md rule 1)."""
        if quiet_hours.quiet(now, self.environ):
            return
        text = words(record, clock_words(*when))
        self.write({**record, "told": "sending"})
        ok = False
        try:
            ok = self.notify(text)
        finally:
            told = "sent" if ok else "no_chat" if ok is None else "uncertain"
            self.write({**self.read(), "told": told, "told_at": now})
        self.log(f"auto upgrade: notice {told} state={record.get('state')}")


def words(record, clock) -> str:
    """The owner's message for a day's attempt that ended."""
    state, why, log = record.get("state"), str(record.get("why") or ""), str(record.get("log") or "")
    to = str(record.get("to") or "")
    tail = f"\n日志：{log}" if log else ""
    later = f"明天 {clock} 再试；要现在升级：网页「设置 → 更新」，或在终端照安装说明升级。"
    if state == DONE:
        changes = [f"- {subject[:80]}" for subject in record.get("changes") or () if subject]
        count = record.get("count") or len(changes)
        head = f"定时自动升级好了：Bridge 和网页都到了 {to}" + (f"，{count} 个新提交" if count else "") + "。"
        return head + ("\n" + "\n".join(changes) if changes else "")
    if state == PARTIAL:
        return (f"定时自动升级：Bridge 已到 {to}，网页没更新上（{why}）。Bridge 不用回滚；网页在「设置 → 更新」或终端里再更新一次。"
                + tail)
    if state == BLOCKED:
        return f"定时自动升级没做：{why}。要人处理一下；处理好后{later}"
    if state == GAVE_UP:
        return f"今天的定时自动升级没做：推迟了 {RETRIES} 次仍不能升（{why}），没有强行重启。{later}"
    return f"定时自动升级没成：{why}。没有自动回滚，看过日志再升级。" + tail


def targets(app) -> list:
    """The ``auto-upgrade`` worker of the Bridge ``app`` (app/unified.py worker_targets), [] without the switch."""
    if not enabled():
        return []
    return [("auto-upgrade", lambda ctx: loop(app, ctx))]


def loop(app, ctx) -> None:
    runtime = app.runtime
    if self_upgrade.config() is None:
        runtime.log(f"auto upgrade: {ENV} is set but the data home has no {self_upgrade.CONFIG}: off")
        return
    when = at()
    runtime.log(f"auto upgrade: daily at {clock_words(*when)} (Asia/Shanghai)")

    def notify(text):
        chat = runtime.access.owner_chat()
        if not chat:
            return None
        key = app.voice.safe_key(f"auto-upgrade-{int(time.time())}")
        return app.messenger.send_message(ctx.profile, chat, text, key, voice=app.voice)

    auto = AutoUpgrade(self_upgrade.shared(ctx.state_dir, runtime.log), busy=lambda: busy_words(ctx.state_dir), notify=notify,
                       log=runtime.log)
    while not runtime.shutdown.is_set():
        try:
            auto.step()
        except Exception as exc:  # noqa: BLE001 - the next look tries again; the Bridge goes on
            runtime.log(f"auto upgrade: step failed: {type(exc).__name__}")
        if runtime.shutdown.wait(TICK_SECONDS):
            break
