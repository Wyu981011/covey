"""Several Google accounts for Antigravity on this machine (docs/quota.md agy 多账号): when a turn's account has spent
its 5-hour or weekly quota of the model's group, or its login stopped working, the turn goes on in the same
conversation on another account (backends/agy/bridge.py ``switch``).

Off unless the data home's ``agy-accounts.json`` (or the file COVEY_AGY_ACCOUNTS names) lists two accounts or more::

    {"accounts": [{"name": "主号"}, {"name": "副号", "home": "/absolute/.agy-accounts/b"}]}

The account without ``home`` is this machine's own login (the real HOME); each ``home`` is an account directory signed
in with ``agy-as`` (backends/agy/account_homes.py), whose turns run in a HOME made for the turn (``AccountHome``: the
real home's entries linked, the login the account's, the conversations shared). The list's order is the order accounts
are tried in; ``"enabled": false`` turns the whole file off with it kept, ``"enabled": false`` on a row that account.

Which account a turn starts on (``pick``): the one 只用这个号 names when there is one (its quota spent, the turn fails and
waits for it); else the group's active one (Gemini and Claude/GPT each have their own: a model's group, ``group_of``),
unless it is held out (``held``: spent until its bucket resets, its login failed, paused, or an account directory not
signed in); then the first in order that is not, which becomes the group's active one. An account stays the active one
until it fails, so accounts change only on a failure, never back and forth.

A failure (``Turn.switch``, under the group's switch lock: one topic picks, those failing beside it take its pick) is
the account's quota only when ``agy -p /usage --output-format json`` (no token spent) shows the group's 5-hour or weekly
bucket at SPENT or below, or agy's own words say a spent quota (QUOTA_WORDS) and /usage shows NEAR or less or says
nothing (it may lag a request behind); a passing 429 with quota left changes nothing (the core's retry takes it). The
account is then held out until that bucket resets and the next one in order that is not held out becomes the group's
active one: the turn goes on there, its 执行过程 saying whose bucket, until when. An account /usage says nothing of is
not taken for signed out (``unknown``: asked again the next time); an account whose own turn says its login failed is
held out until it signs in again (its login file changes) or a 重新检查 finds it working (``recheck``). With none left
the turn fails as 额度用完 (``Turn.settle``), with when the first comes back: within six hours the core's retry waits for
it (app/auto_retry.py QUOTA), later only the card says when.

Every snapshot of the page (``snapshots``, one a model group, core/quota.py's format) is made from the state alone:
which account is active, spent until when, signed out or paused, and the last /usage read of each (taken at a switch or
when the owner asks, ``probe_accounts``); a spare account is never asked on a timer (Google may link accounts seen
taking turns from one machine).

All of it is fail-open: a configuration, state or probe that fails never fails a turn, it is written to the log.

Records under ``<state>/agy-accounts/``: ``state.json`` ({"active": {group: name}, "spent": {name: {group: epoch}},
"login": {name: {"at", "mark"}}, "unknown": {name: epoch}, "groups": {model: group}, "usage": {name: {"at", "groups"}},
"paused": {name: epoch}, "only": name, "switched": {group: {"at", "from", "to", "why"}}}; an older file's one ``active``
name is every group's, its ``login`` epochs hold until then), written under ``state.lock``; ``accounts.log`` (each
switch and probe; no token, no answer, no prompt) and ``turns.jsonl`` (which account each turn ran on, its run id).
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from covey.backends.agy.account_homes import CLI, GEMINI, PREFIX, TOKEN, AccountHome, signed_in, sweep
from covey.core import env as cenv
from covey.core import quota
from covey.core.file_lock import file_lock
from covey.core.logs import line_log
from covey.core.paths import data_home
from covey.core.state import ensure_private_dir, read_json, write_json

ACCOUNTS_CONFIG_ENV = "COVEY_AGY_ACCOUNTS"
CONFIG_FILE = "agy-accounts.json"
FOLDER = "agy-accounts"  # Under the state directory.
NAME_LIMIT = 20
SPENT = 0.01  # A bucket with this fraction left or less is spent.
NEAR = 0.1  # When agy's own words say a spent quota, /usage may lag by a request or two: this much left is spent too.
UNKNOWN_HOLD = 3600  # Seconds a spent account is held out when /usage says no reset.
PROBE_SECONDS = 30
LOG_LIMIT = 1024 * 1024
TURNS_LIMIT = 1024 * 1024
SNAPSHOT_TTL = 600  # How long the page takes an agy snapshot for current (its windows say when each was read).
# agy's own words for a spent quota (1.5.14's strings: "You have exhausted your quota on this model.", "… your capacity
# on this model. Your quota will reset after 4h12m."), and how long until it is back.
QUOTA_WORDS = re.compile(r"exhausted your (?:quota|capacity)|out of quota|quota.?exhausted|individual quota reached",
                         re.I)
RESET_WORDS = re.compile(r"reset after\s+((?:\d+\s*[dhms]\s*)+)", re.I)
GROUPS = ("gemini", "3p")  # The groups agy's /usage has (its buckets' ids: gemini-5h, 3p-weekly), in the page's order.
GROUP_LABELS = {"gemini": "Gemini", "3p": "Claude/GPT"}
WINDOW_LABELS = {"5h": "5 小时额度", "weekly": "周额度"}
WINDOW_KINDS = {"5h": ("5h", "5 小时"), "weekly": ("7d", "周")}  # /usage's window -> the snapshot's kind and label.


@dataclass(frozen=True)
class Account:
    name: str
    home: Path | None  # None: this machine's own login, the real HOME.


def config_path(environ=None) -> Path:
    value = str(cenv.get(ACCOUNTS_CONFIG_ENV, "", environ) or "").strip()
    return Path(value).expanduser() if value else data_home() / CONFIG_FILE


def load(environ=None) -> list[Account]:
    """The configured accounts; [] when there is no file, it is turned off or lists fewer than two (one account is
    the machine's own login: nothing to switch to). ValueError when it cannot be used."""
    path = config_path(environ)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} 读不了：{type(exc).__name__}") from None
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise ValueError(f"{path} 要有 accounts 列表")
    if data.get("enabled") is False:
        return []
    accounts, names = [], set()
    for row in data["accounts"]:
        name = str(row.get("name") or "").strip() if isinstance(row, dict) else ""
        home = row.get("home") if isinstance(row, dict) else None
        if not name or len(name) > NAME_LIMIT or name in names:
            raise ValueError(f"{path}：每个账号要有不重复的 name（{NAME_LIMIT} 字以内）")
        if home is not None and (not isinstance(home, str) or not Path(home).expanduser().is_absolute()):
            raise ValueError(f"{path}：{name} 的 home 要是绝对路径")
        names.add(name)
        if row.get("enabled") is not False:
            accounts.append(Account(name, Path(home).expanduser() if home else None))
    if sum(account.home is None for account in accounts) > 1:
        raise ValueError(f"{path}：只能有一个账号不写 home（本机原来的登录）")
    return accounts if len(accounts) >= 2 else []


def configured(environ=None) -> bool:
    """Whether the accounts are on (two or more); False for a file that cannot be used too."""
    try:
        return bool(load(environ))
    except ValueError:
        return False


def epoch(value) -> float:
    """Seconds of an RFC 3339 time (agy's ``2026-11-30T02:53:56Z``; 3.10's fromisoformat takes no Z); 0 for none."""
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def buckets(text) -> dict | None:
    """Every bucket of ``agy -p /usage --output-format json``'s output (1.5.14: ``command.data.groups[].buckets[]`` with
    ``remaining_fraction``, ``reset_time``, ``window``): ``{group: {"name", "models", "buckets": [{"window", "left",
    "reset"}]}}``, a group's key its buckets' id before the window (``gemini``, ``3p``); an unused bucket resets at 1970
    (0). None when it is not such an output."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    groups = (((data.get("command") or {}).get("data") or {}).get("groups")
              if isinstance(data, dict) and data.get("status") == "SUCCESS" else None)
    if not isinstance(groups, list):
        return None
    found = {}
    for group in groups:
        rows = [b for b in (group.get("buckets") or ()) if isinstance(b, dict)
                and isinstance(b.get("remaining_fraction"), (int, float))] if isinstance(group, dict) else []
        if not rows:
            continue
        key = str(rows[0].get("id") or "").rpartition("-")[0] or str(group.get("name") or "")
        found[key] = {"name": str(group.get("name") or key), "models": str(group.get("description") or ""),
                      "buckets": [{"window": str(b.get("window") or ""), "left": float(b["remaining_fraction"]),
                                   "reset": epoch(b.get("reset_time"))} for b in rows]}
    return found or None


def tightest(group) -> dict:
    """``{"name", "models", "left", "reset", "window"}`` of a ``buckets`` group: ``left`` its lowest bucket, ``reset``
    and ``window`` those of its spent bucket that resets last, else of the lowest."""
    rows = group["buckets"]
    lowest = min(rows, key=lambda b: b["left"])
    spent = [b for b in rows if b["left"] <= SPENT]
    last = max(spent, key=lambda b: b["reset"]) if spent else None
    return {"name": group["name"], "models": group["models"], "left": lowest["left"], "reset": (last or lowest)["reset"],
            "window": (last or lowest)["window"]}


def parse_usage(text) -> dict | None:
    """``{group: tightest(...)}`` of /usage's output, None when it is not one: what the switch judges a group by."""
    found = buckets(text)
    return None if found is None else {key: tightest(group) for key, group in found.items()}


def reset_in(words) -> int:
    """Seconds until the quota is back, as agy's words say it ("reset after 1h2m3s"); 0 when they do not."""
    found = RESET_WORDS.search(str(words or ""))
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * units[u.lower()] for n, u in re.findall(r"(\d+)\s*([dhms])", found.group(1), re.I)) if found else 0


def display_name(state_dir, model) -> str:
    """The launch catalog's name of ``model`` (backends/agy/bridge.py model_catalog's file), '' when it has none."""
    try:
        row = read_json(Path(state_dir) / "launch-models" / "agy.json").get("models", {}).get(model)
    except (OSError, ValueError, AttributeError):
        return ""
    return str(row.get("display_name") or "") if isinstance(row, dict) else ""


def group_of(state_dir, model, usage=None) -> str:
    """The quota group of ``model``: the one of ``usage`` whose description names the model's catalog name, else by
    the id: ``claude-*`` and ``gpt-*`` are ``3p``, anything else (agy's own default too) ``gemini``."""
    name = display_name(state_dir, model) if model else ""
    for key, group in (usage or {}).items():
        if name and re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w.])", group["models"], re.I):
            return key
    return "3p" if str(model or "").lower().startswith(("claude", "gpt")) else "gemini"


def login_mark(account, real=None):
    """What the account's login file is now ((mtime_ns, size)), None without one: a new login changes it."""
    home = account.home if account.home is not None else Path(real or Path.home())
    try:
        info = (Path(home) / GEMINI / CLI / TOKEN).stat()
    except OSError:
        return None
    return [info.st_mtime_ns, info.st_size]


def active_of(state, group) -> str:
    """The group's active account's name; an older file's one name is every group's."""
    active = state.get("active")
    if isinstance(active, str):
        return active
    return str(active.get(group) or "") if isinstance(active, dict) else ""


def signed_out(state, account, now, real=None) -> bool:
    """Whether ``account``'s login is known not to work: its own turn said so and it has not signed in since (its login
    file unchanged); an older file's epoch holds until then. An account directory without a login is too."""
    row = (state.get("login") or {}).get(account.name)
    if isinstance(row, (int, float)) and not isinstance(row, bool):
        if row > now:
            return True
    elif isinstance(row, dict) and row.get("mark", False) == login_mark(account, real):
        return True
    return account.home is not None and not signed_in(account.home)


def held(state, account, group, now, real=None) -> bool:
    """Whether ``account`` is held out of ``group`` now: spent until later, signed out, or paused."""
    if (state.get("spent", {}).get(account.name) or {}).get(group, 0) > now:
        return True
    if account.name in (state.get("paused") or {}):
        return True
    return signed_out(state, account, now, real)


def only_of(state, accounts):
    """The account 只用这个号 names, when it is one of ``accounts``."""
    name = state.get("only")
    return next((a for a in accounts if a.name == name), None) if name else None


def pick(state, accounts, group, now, real=None) -> Account:
    """The account a turn of ``group`` starts on (see the module docstring)."""
    only = only_of(state, accounts)
    if only is not None:
        return only
    active = next((a for a in accounts if a.name == active_of(state, group)), accounts[0])
    if not held(state, active, group, now, real):
        return active
    return next((a for a in accounts if not held(state, a, group, now, real)), active)


def back_at(state, accounts, group, now, real=None) -> float:
    """When the first account of ``group`` that comes back by itself does (spent until then; not one signed out or
    paused); 0 when none will."""
    only = only_of(state, accounts)
    times = [(state.get("spent", {}).get(a.name) or {}).get(group, 0) for a in ([only] if only else accounts)
             if a.name not in (state.get("paused") or {}) and not signed_out(state, a, now, real)]
    times = [t for t in times if t > now]
    return min(times) if times else 0.0


def when(seconds, now=None) -> str:
    """A reset time as the owner reads it: 14:20 today, else 11月28日 16:49."""
    moment = dt.datetime.fromtimestamp(seconds)
    today = dt.datetime.fromtimestamp(time.time() if now is None else now).date()
    return f"{moment:%H:%M}" if moment.date() == today else f"{moment.month}月{moment.day}日 {moment:%H:%M}"


def label_of(group) -> str:
    return GROUP_LABELS.get(group) or group


class Records:
    """``<state>/agy-accounts/``: the state every task runner shares, the log and the turns' accounts."""

    def __init__(self, state_dir):
        self.folder = Path(state_dir) / FOLDER
        self.log = line_log(self.folder / "accounts.log", max_bytes=LOG_LIMIT, keep=2, live=True)

    def read(self) -> dict:
        try:
            state = read_json(self.folder / "state.json", {})
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def change(self, change) -> dict:
        """``change(state)`` under the lock, then written; the state as written."""
        ensure_private_dir(self.folder)
        with file_lock(self.folder / "state.lock"):
            state = self.read()
            for key in ("spent", "login", "groups", "unknown", "usage", "paused", "switched"):
                if not isinstance(state.get(key), dict):
                    state[key] = {}
            if not isinstance(state.get("active"), dict):
                old = state.get("active")
                state["active"] = {group: old for group in GROUPS} if isinstance(old, str) and old else {}
            change(state)
            write_json(self.folder / "state.json", state, ensure_ascii=False, indent=1)
        return state

    @contextlib.contextmanager
    def switching(self, group):
        """The group's switch lock: one topic picks the next account, the others wait and take its pick."""
        ensure_private_dir(self.folder)
        with file_lock(self.folder / f"switch-{re.sub(r'[^a-z0-9]', '', group.lower()) or 'group'}.lock"):
            yield

    def turn(self, row) -> None:
        """Note which account a turn ran on (``turns.jsonl``, kept to TURNS_LIMIT bytes and one older file)."""
        path = self.folder / "turns.jsonl"
        try:
            ensure_private_dir(self.folder)
            with contextlib.suppress(FileNotFoundError):
                if path.stat().st_size > TURNS_LIMIT:
                    os.replace(path, path.with_suffix(".jsonl.1"))
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as out:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.log(f"turns-error {type(exc).__name__}")


def probe(command, home, cwd, environ) -> dict | None:
    """``buckets`` of ``agy -p /usage`` with HOME ``home``; None when it does not answer one in PROBE_SECONDS (its
    process group is killed then)."""
    try:
        process = subprocess.Popen([*command, "-p", "/usage", "--output-format", "json"], cwd=str(cwd),
                                   env={**environ, "HOME": str(home)}, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   start_new_session=True)
    except OSError:
        return None
    try:
        out, _ = process.communicate(timeout=PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)  # Its group, while it still leads it.
        process.communicate()
        return None
    return buckets(out)


def read_usage(records, command, account, real, environ, run="") -> dict | None:
    """/usage of ``account`` (``buckets``), kept in the state as its last read; None when it said nothing (then it
    is ``unknown``, never taken for signed out)."""
    cwd = records.folder / "probe"
    ensure_private_dir(cwd)
    started = time.monotonic()
    found = probe(command, real if account.home is None else account.home, cwd, environ)
    now = time.time()
    left = ",".join("%s:%.3f" % (key, tightest(group)["left"]) for key, group in (found or {}).items())
    records.log(f"probe run={run} account={account.name} ok={int(found is not None)} "
                f"ms={round((time.monotonic() - started) * 1000)} left={left}")

    def keep(state):
        if found is None:
            state["unknown"][account.name] = now
            return
        state["unknown"].pop(account.name, None)
        state["usage"][account.name] = {"at": now, "groups": found}
        login = state["login"].get(account.name)
        if isinstance(login, dict) or isinstance(login, (int, float)):
            state["login"].pop(account.name, None)  # /usage answered: its login works.
        for key, group in found.items():
            low = tightest(group)
            if low["left"] <= SPENT:
                until = low["reset"] if low["reset"] > now else now + UNKNOWN_HOLD
                state["spent"].setdefault(account.name, {})[key] = max(
                    until, (state["spent"].get(account.name) or {}).get(key, 0))
            elif (state["spent"].get(account.name) or {}).get(key, 0) > now:
                state["spent"][account.name].pop(key, None)  # Back before its time (more quota, a reset).
    records.change(keep)
    return found


class Turn:
    """One turn's accounts: the one it starts on (``first``), the one it goes on in (``__call__``, the core's switch)
    and its result when none was left (``settle``)."""

    def __init__(self, ctx, env, accounts, stack, records, run_id=""):
        self.ctx, self.env, self.accounts, self.stack, self.records = ctx, env, accounts, stack, records
        self.real = Path(env.get("HOME") or Path.home())
        self.group = group_of(ctx.state_dir, ctx.model)
        self.run = str(run_id or "")
        self.current = None
        self.exhausted = None  # {"group", "back", "count", "only"} once none was left.

    def first(self) -> dict:
        now = time.time()
        state = self.records.read()
        self.group = str((state.get("groups") or {}).get(self.ctx.model or "") or self.group)
        self.current = pick(state, self.accounts, self.group, now, self.real)
        if active_of(state, self.group) != self.current.name and only_of(state, self.accounts) is None:
            self.records.change(lambda s: s["active"].__setitem__(self.group, self.current.name))
        self.records.log(f"turn run={self.run[:8]} account={self.current.name} group={self.group}")
        self.records.turn({"at": round(now), "run": self.run, "account": self.current.name, "group": self.group,
                           "model": str(self.ctx.model or "")})
        return self.env_of(self.current)

    def env_of(self, account) -> dict:
        if account.home is None:
            return self.env
        tmp = Path(self.ctx.state_dir) / "tmp"
        sweep(tmp)
        home = self.stack.enter_context(AccountHome(tmp, self.real, account.home, prefix=f"{PREFIX}{os.getpid()}-"))
        return {**self.env, "HOME": str(home)}

    def usage(self, account) -> dict | None:
        found = read_usage(self.records, self.ctx.backend_cmd, account, self.real, self.env, self.run[:8])
        return None if found is None else {key: tightest(group) for key, group in found.items()}

    def __call__(self, failure):
        """The core's ``switch``: ``(env, note)`` of the account the turn goes on in, or None."""
        try:
            return self._switch(failure if isinstance(failure, dict) else {})
        except Exception as exc:  # Fail-open: the turn fails as it would have.
            self.records.log(f"switch-error run={self.run[:8]} {type(exc).__name__}: {str(exc)[:200]}")
            return None

    switch = __call__

    def _spent(self, failure, now):
        """Whether the current account's failure is its own (its quota spent, its login gone), noted in the state; the
        head of the 执行过程 line, or None (a passing limit with quota left: the core's retry takes it)."""
        current, code = self.current, str(failure.get("code") or "")
        if code == "authentication_error":
            mark = login_mark(current, self.real)
            self.records.change(lambda s: s["login"].__setitem__(current.name, {"at": now, "mark": mark}))
            return f"{current.name}的登录用不了了，要重新登录"
        usage, words = self.usage(current), str(failure.get("error") or "")
        if usage is not None:
            self.group = group_of(self.ctx.state_dir, self.ctx.model, usage)
            spent = [key for key, group in usage.items() if group["left"] <= SPENT]
            if self.group not in usage and len(spent) == 1:
                self.group = spent[0]
            if self.group in usage:
                self.records.change(lambda s: s["groups"].__setitem__(self.ctx.model or "", self.group))
        group = (usage or {}).get(self.group) or {}
        by_usage = usage is not None and group.get("left", 1.0) <= SPENT
        by_words = bool(QUOTA_WORDS.search(words)) and (usage is None or group.get("left", 1.0) <= NEAR)
        if not (by_usage or by_words):
            why = "quota-left" if usage is not None else "no-usage"
            self.records.log(f"stay run={self.run[:8]} account={current.name} code={code} group={self.group} why={why}")
            return None
        back = group.get("reset", 0) if by_usage else (now + reset_in(words) if reset_in(words) else
                                                      group.get("reset", 0))
        until = back if back > now else now + UNKNOWN_HOLD
        self.records.change(lambda s: s["spent"].setdefault(current.name, {}).__setitem__(
            self.group, max(until, (s["spent"].get(current.name) or {}).get(self.group, 0))))
        window = WINDOW_LABELS.get(group.get("window"), "额度")
        label = label_of(self.group)
        return (f"{current.name}的 {label} {window}用完了（{when(until, now)} 恢复）" if back > now
                else f"{current.name}的 {label} 额度用完了")

    def _switch(self, failure):
        now, current, code = time.time(), self.current, str(failure.get("code") or "")
        with self.records.switching(self.group):
            state = self.records.read()
            only = only_of(state, self.accounts)
            moved = next((a for a in self.accounts if a.name == active_of(state, self.group)), None)
            if (only is None and moved is not None and moved != current and not held(state, moved, self.group, now,
                                                                                    self.real)
                    and held(state, current, self.group, now, self.real)):
                # Another topic found this account out and picked the next one meanwhile: go on there, nothing asked.
                return self._go(moved, self.why_held(state, now), code, now, "followed")
            head = self._spent(failure, now)
            if head is None:
                return None
            if only is not None:
                return self._none_left(code, now, head)
            order = self.accounts.index(current) if current in self.accounts else -1
            for candidate in self.accounts[order + 1:] + self.accounts[:max(order, 0)]:
                if candidate == current or held(self.records.read(), candidate, self.group, now, self.real):
                    continue
                usage = self.usage(candidate)
                group = (usage or {}).get(self.group)
                if group is not None and group["left"] <= SPENT:
                    continue  # read_usage noted it spent until its reset.
                if usage is None and held(self.records.read(), candidate, self.group, now, self.real):
                    continue
                # /usage said nothing of it: not taken for signed out; agy's own answer will say.
                return self._go(candidate, head, code, now, "switch")
            return self._none_left(code, now, head)

    def why_held(self, state, now) -> str:
        """Why the current account is held out of the group, as the 执行过程 line says it."""
        name, until = self.current.name, (state.get("spent", {}).get(self.current.name) or {}).get(self.group, 0)
        if until > now:
            return f"{name}的 {label_of(self.group)} 额度用完了（{when(until, now)} 恢复）"
        if name in (state.get("paused") or {}):
            return f"{name}暂停了"
        return f"{name}的登录用不了了，要重新登录"

    def _go(self, candidate, head, code, now, why):
        env = self.env_of(candidate)
        current = self.current

        def note(state):
            state["active"][self.group] = candidate.name
            state["switched"][self.group] = {"at": now, "from": current.name, "to": candidate.name, "why": head}
        self.records.change(note)
        self.records.log(f"{why} run={self.run[:8]} from={current.name} to={candidate.name} code={code} "
                         f"group={self.group}")
        self.records.turn({"at": round(now), "run": self.run, "account": candidate.name, "group": self.group,
                           "model": str(self.ctx.model or ""), "from": current.name})
        self.current = candidate
        return env, f"{head}，换{candidate.name}接着做"

    def _none_left(self, code, now, head):
        state = self.records.read()
        only = only_of(state, self.accounts)
        self.exhausted = {"group": self.group, "back": back_at(state, self.accounts, self.group, now, self.real),
                          "count": len(self.accounts), "only": only.name if only else "", "head": head}
        self.records.log(f"stay run={self.run[:8]} account={self.current.name} code={code} group={self.group} "
                         f"why={'only' if only else 'none-left'}")
        return None

    def settle(self, result):
        """``result`` (the turn's RunResult) as 额度用完 when the turn failed with no account left: when the first comes
        back (``limit.reset_at``, for the core's retry) and in whose words; any other result as it is."""
        found, outcome = self.exhausted, getattr(result, "outcome", None)
        if (found is None or outcome is None or outcome.status != "failed"
                or outcome.error_code not in ("quota_exhausted", "rate_limited", "authentication_error")):
            return result
        import dataclasses

        label, back = label_of(found["group"]), found["back"]
        whom = (f"只用{found['only']}：它的 {label} 额度用完了" if found["only"]
                else f"{found['count']} 个号的 {label} 额度都用完了或要重新登录")
        detail = whom + (f"，最早 {when(back)} 恢复" if back else "，没有会自己恢复的号（要重新登录的号登录后再试）")
        code = "quota_exhausted" if back or outcome.error_code != "authentication_error" else "authentication_error"
        changed = dataclasses.replace(outcome, error_code=code)
        limit = {**(result.limit or {}), "reset_at": back} if back else result.limit
        return dataclasses.replace(result, text=changed.summary(detail), outcome=changed, failure_detail=detail,
                                   limit=limit)


@contextlib.contextmanager
def turn(ctx, env, *, run_id=""):
    """``(env, switch)`` of one turn on this machine (backends/agy/bridge.py); ``(env, None)`` when it is off."""
    records = Records(ctx.state_dir)
    try:
        accounts = load()
    except ValueError as exc:
        records.log(f"off: {exc}")
        accounts = []
    if not accounts:
        yield env, None
        return
    with contextlib.ExitStack() as stack:
        session = Turn(ctx, env, accounts, stack, records, run_id)
        try:
            found = session.first(), session
        except Exception as exc:  # Fail-open: the turn runs as it would have.
            records.log(f"first-error run={session.run[:8]} {type(exc).__name__}: {str(exc)[:200]}")
            found = env, None
        yield found


def recheck(state_dir, command, environ, name) -> bool:
    """重新检查 one account: /usage asked once; when it answers, the account is signed in again (back in turn). Whether
    it answered."""
    accounts = load(environ)
    account = next((a for a in accounts if a.name == name), None)
    if account is None:
        return False
    real = Path(environ.get("HOME") or Path.home())
    return read_usage(Records(state_dir), command, account, real, environ) is not None


def probe_accounts(state_dir, command, environ, *, which="active", fresh=0, now=None) -> list:
    """Read /usage of the active accounts (one a group; ``which`` "all": every account), but not of one read less
    than ``fresh`` seconds ago; the names read. For the page's 刷新 and 查全部账号 alone, never on a timer."""
    accounts = load(environ)
    if not accounts:
        return []
    records = Records(state_dir)
    state, now = records.read(), time.time() if now is None else now
    real = Path(environ.get("HOME") or Path.home())
    names = ({active_of(state, g) or accounts[0].name for g in GROUPS} if which == "active"
             else {a.name for a in accounts})
    done = []
    for account in accounts:
        last = float(((state.get("usage") or {}).get(account.name) or {}).get("at") or 0)
        if account.name in names and now - last >= fresh and not (account.home and not signed_in(account.home)):
            read_usage(records, command, account, real, environ)
            done.append(account.name)
    return done


def alias_of(account, number) -> str:
    """The account's name as the page shows it: an e-mail or a path in it is no name (core/quota.py scrub)."""
    alias = quota.scrub(account.name, quota.ALIAS_CHARS)
    return alias if alias and alias != quota.CUT else f"号 {number}"


def snapshot(state, accounts, group, now, real=None) -> dict:
    """The snapshot of ``group`` (core/quota.py's format) made from ``state`` alone."""
    only = only_of(state, accounts)
    active = only.name if only else active_of(state, group) or accounts[0].name
    rows = []
    for number, account in enumerate(accounts, 1):
        spent_until = (state.get("spent", {}).get(account.name) or {}).get(group, 0)
        if account.name in (state.get("paused") or {}):
            row = {"state": quota.PAUSED}
        elif signed_out(state, account, now, real):
            row = {"state": quota.LOGIN}
        elif spent_until > now:
            row = {"state": quota.SPENT, "available_at": spent_until}
        else:
            read = ((state.get("usage") or {}).get(account.name) or {})
            unknown = (state.get("unknown") or {}).get(account.name, 0) > float(read.get("at") or 0)
            row = {"state": quota.UNKNOWN if unknown and not read else quota.OK}
        read = (state.get("usage") or {}).get(account.name) or {}
        windows = []
        for bucket in ((read.get("groups") or {}).get(group) or {}).get("buckets") or ():
            kind, label = WINDOW_KINDS.get(bucket.get("window"), ("other", str(bucket.get("window") or "")[:12]))
            window = {"kind": kind, "label": label, "used": round(1 - float(bucket.get("left", 0)), 4),
                      "checked_at": float(read.get("at") or now)}
            if float(bucket.get("reset") or 0) > 0:
                window["resets_at"] = float(bucket["reset"])
            windows.append(window)
        windows.sort(key=lambda w: quota.WINDOW_KINDS.index(w["kind"]))
        rows.append({"alias": alias_of(account, number), **row, "windows": windows,
                     **({"active": True} if account.name == active else {})})
    data = {"schema": quota.SCHEMA, "title": f"agy · {label_of(group)}", "collected_at": now, "ttl": SNAPSHOT_TTL,
            "accounts": rows}
    return quota.parse(data)


def snapshots(state_dir, environ=None, now=None) -> list:
    """Write the agy snapshots (one a group, sources ``agy.<group>``) from the accounts' state; the source ids written.
    Off, every agy snapshot is removed."""
    store = quota.Store(state_dir)
    try:
        accounts = load(environ)
    except ValueError:
        accounts = []
    if not accounts:
        for entry in store.entries():
            if entry.get("kind") == "agy":
                store.forget(entry["source"])
        return []
    records, now = Records(state_dir), time.time() if now is None else now
    state = records.read()
    environ = os.environ if environ is None else environ
    real = Path(environ.get("HOME") or Path.home())
    written = []
    for group in GROUPS:
        source = f"agy.{group}"
        moved = (state.get("switched") or {}).get(group) or {}
        last = ({"at": moved.get("at"), "from": quota.scrub(moved.get("from"), quota.ALIAS_CHARS),
                 "to": quota.scrub(moved.get("to"), quota.ALIAS_CHARS),
                 "why": quota.scrub(moved.get("why"), 80)} if moved.get("at") else None)
        store.saved(source, "agy", snapshot(state, accounts, group, now, real), title=f"agy · {label_of(group)}",
                    now=now, group=group, switched=last)
        written.append(source)
    return written


def set_choice(state_dir, *, pause=None, resume=None, only=None, clear_only=False, environ=None) -> dict:
    """The owner's 暂停, 恢复, 只用这个号 and its undo on the page: kept in the state (a restart keeps them)."""
    names = {a.name for a in load(environ)}
    for name in (pause, resume, only):
        if name is not None and name not in names:
            raise ValueError("没有这个账号")

    def choose(state):
        if pause is not None:
            state["paused"][pause] = time.time()
            if state.get("only") == pause:
                state.pop("only", None)
        if resume is not None:
            state["paused"].pop(resume, None)
        if only is not None:
            state["only"] = only
            state["paused"].pop(only, None)
        if clear_only:
            state.pop("only", None)
    return Records(state_dir).change(choose)
