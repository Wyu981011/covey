"""A Claude profile's quota command (--claude-quota-cmd): after a rate-limited turn on a gateway of several
subscription accounts, whether the session moves to another account at once, the owner is asked, or the retry
waits for the account's reset (app/auto_retry.py plans and fires it).

Off unless the Claude Harness names the command; then only for a topic on a configured profile (backends/claude/
profiles.py) whose session is known. The command is the administrator's: it reads the gateway's quotas and keeps
which account each session uses. It is run as ``CMD advise --profile ID --session SID`` and ``CMD switch --profile ID
--session SID``, each printing one JSON object on stdout within TIMEOUT seconds:

- advise: {"action": "switch"|"ask"|"wait"|"retry", "account": the session's account, "other": the account a
  switch goes to, "resets_at": when the session's account renews, "at": when the retry runs, "switch": whether
  the session moves before it}; "retry" (or any failure) leaves the usual rate-limit retry.
- switch: {"ok": true, "to": the account the session uses now}.

Neither is run under a record lock: advise in the worker as the turn ends, switch there or on a card click.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import subprocess
import time

from covey.backends.claude import profiles

OPTION = "quota_cmd"
TIMEOUT = 20
ACTIONS = ("switch", "ask", "wait")
SWITCH_KIND = "bridge_job_quota_switch"  # 换账号，马上继续 on an "ask" card.
WAIT_KIND = "bridge_job_quota_wait"  # 等恢复后自动继续 on it.
ASK_SECONDS = 600  # Owner's rule (T22 2026-11-17): a reset within 10 minutes asks, a later one switches at once.


def _run(cmd, verb, profile, session, log=None):
    try:
        done = subprocess.run([cmd, verb, "--profile", profile, "--session", session], capture_output=True,
                              text=True, timeout=TIMEOUT, check=False, stdin=subprocess.DEVNULL)
        data = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if log:
            log(f"quota command {verb} failed: {type(exc).__name__}")
        return None
    if not isinstance(data, dict):
        if log:
            log(f"quota command {verb} exited {done.returncode}")
        return None
    return data


def _label(value):
    return value if isinstance(value, str) and 0 < len(value) <= 40 and value.isprintable() else ""


def _epoch(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value > 0 else None


def profile_of(ctx):
    """The configured profile id of ``ctx``'s topic, or ""."""
    model = profiles.selected(ctx)
    parts = model.split("/", 2) if model else []
    return parts[1] if len(parts) == 3 and parts[1] else ""


def advise(ctx, session, log=None, now=None):
    """What the quota command says of ``ctx``'s rate-limited ``session``: the record's ``auto_retry_quota`` (its
    action, accounts, times, profile and session), with ``moved`` the account the session went to when it says to
    switch at once; None for the usual retry."""
    cmd, profile = (getattr(ctx, "options", None) or {}).get(OPTION), profile_of(ctx)
    if not cmd or not profile or not session:
        return None
    data = _run(cmd, "advise", profile, session, log)
    now = time.time() if now is None else now
    if not data or data.get("action") not in ACTIONS:
        return None
    at, resets_at = _epoch(data.get("at")), _epoch(data.get("resets_at"))
    account, other = _label(data.get("account")), _label(data.get("other"))
    if at is None or resets_at is None or not account or (
            (data["action"] != "wait" or data.get("switch")) and not other):
        return None
    quota = {"action": data["action"], "account": account, "other": other, "resets_at": resets_at,
             "at": max(at, now), "switch": data.get("switch") is True or data["action"] == "switch",
             "profile": profile, "session": session}
    if quota["switch"]:
        moved = switch(cmd, quota, log)
        if not moved:
            return None  # Not moved: the usual retry, rather than one that waits on the wrong account.
        quota["moved"] = moved
    return quota


def switch(cmd, quota, log=None):
    """Move ``quota``'s session to another account: the account it uses now, or "" when that failed."""
    if not cmd:
        return ""
    data = _run(cmd, "switch", quota["profile"], quota["session"], log)
    return _label((data or {}).get("to")) if (data or {}).get("ok") is True else ""


def _hm(epoch):
    return _dt.datetime.fromtimestamp(epoch).astimezone().strftime("%H:%M")


def line(quota, due_at, now=None):
    """What a pending retry's status says of ``quota`` (without the attempt count)."""
    account, other, moved = quota["account"], quota.get("other", ""), quota.get("moved", "")
    if quota["action"] == "switch":
        return f"{account} 账号额度用满，{_hm(quota['resets_at'])} 才恢复；已换到 {moved or other} 账号，将于 {_hm(due_at)} 自动继续"
    if quota["action"] == "ask" and not quota.get("chosen"):
        left = max(1, math.ceil((quota["resets_at"] - (time.time() if now is None else now)) / 60))
        return (f"{account} 账号额度用满，{_hm(quota['resets_at'])} 恢复（约 {left} 分钟后）；"
                f"不选的话 {_hm(due_at)} 自动继续，也可以换到 {other} 账号马上继续")
    if quota["action"] == "ask":
        if quota.get("chosen") == "switch":
            return f"{account} 账号额度用满，已换到 {moved or other} 账号，将于 {_hm(due_at)} 自动继续"
        return f"{account} 账号额度用满，等它 {_hm(quota['resets_at'])} 恢复，将于 {_hm(due_at)} 自动继续"
    if quota.get("switch"):
        return f"所有账号额度都用满，{moved or other} 账号先恢复，已换过去，将于 {_hm(due_at)} 自动继续"
    return f"所有账号额度都用满，{account} 账号 {_hm(quota['resets_at'])} 先恢复，将于 {_hm(due_at)} 自动继续"
