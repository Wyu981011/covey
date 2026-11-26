"""A Claude turn that failed on its model's limit, put right by the gateway's quota snapshot (docs/quota.md 失败说明, T831).

A gateway in front of Claude Code says a spent pool on a 429 (its words say so: core/limit_reset.py ``quota_spent``),
but a pool whose accounts all need a sign-in only as a 503, which Claude Code calls "a server-side issue, usually
temporary" (measured 11-26 on the owner's gateway: three minutes of its own retries, then three more of the Bridge's).
The gateway's snapshot (core/quota_sources.py ``gateway``, read again first when it is older than RECHECK seconds) says
which: with no account it can use,

- some coming back by themselves: 额度用完 (``quota_exhausted``), with when the first is back (``limit.reset_at``, for
  app/auto_retry.py QUOTA: within six hours the turn goes on then), whatever the status said;
- none (each needs a sign-in, has expired or is paused): 网关里没有能用的号 (``authentication_error``): no retry helps
  until the gateway's owner sees to it.

Only a turn on the account Claude Code signs in to (its own provider's model, or one an extension declares the same
account: core/providers.py ``own_login``) and not on a device; with COVEY_QUOTA=0, without a gateway, or a snapshot that
cannot be had, the result stays as it was. The read is a GET of a few KB in the task runner after the turn, no lock held.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import time

from covey.core import providers, quota, quota_sources

CODES = ("rate_limited", "server_fault", "quota_exhausted")
RECHECK = 30  # Seconds: a snapshot older than this is read again before it decides.
NO_ACCOUNT = "网关里没有能用的号（都要重新登录、已到期或已暂停），要网关的主人处理；重试不会成功"


def clock(at, now) -> str:
    moment = _dt.datetime.fromtimestamp(at)
    today = _dt.datetime.fromtimestamp(now).date()
    return f"{moment:%H:%M}" if moment.date() == today else f"{moment.month}月{moment.day}日 {moment:%H:%M}"


def own_login(ctx) -> bool:
    """Whether ``ctx``'s turn signs in as Claude Code itself does (the gateway's snapshot is its pool's)."""
    provider = providers.provider_of("claude", getattr(ctx, "model", ""))
    return provider is None or not provider.prefix or bool(provider.own_login)


def snapshot(ctx, now):
    """The gateway's snapshot as it is now (read again when older than RECHECK seconds), None without one."""
    source = quota_sources.gateway()
    if source is None:
        return None
    store = quota.Store(ctx.state_dir)
    entry = store.read(source.id)
    if entry.get("absent") and now - float(entry.get("read_at") or 0) < quota_sources.ABSENT_SECONDS:
        return None
    if now - float(entry.get("read_at") or 0) > RECHECK:
        entry = quota_sources.take(store, source, now)
    found = entry.get("snapshot")
    if not isinstance(found, dict) or now - float(entry.get("ok_at") or 0) > RECHECK * 2:
        return None  # None read just now: what it said before may no longer be so.
    return found


def refine(harness, ctx, result, now=None):
    """``result`` (a RunResult) as the gateway's snapshot says of its failure (see the module docstring); a spent quota
    whose words said when it is back (``limit.reset_at``) says it on its card."""
    outcome = getattr(result, "outcome", None)
    if (harness != "claude" or outcome is None or outcome.status != "failed" or outcome.error_code not in CODES
            or not quota_sources.enabled()):
        return result
    now = time.time() if now is None else now
    found = None
    if not getattr(ctx, "device", "") and own_login(ctx):
        try:
            found = snapshot(ctx, now)
        except Exception:  # Only words on a card: the turn's result stands.
            found = None
    limit = dict(result.limit or {})
    if found is not None and not quota.pool(found).get("usable"):
        if quota.none_signed_in(found):
            changed = dataclasses.replace(outcome, error_code="authentication_error")
            return dataclasses.replace(result, text=changed.summary(NO_ACCOUNT), outcome=changed,
                                       failure_detail=NO_ACCOUNT, limit=None)
        back = float(quota.pool(found).get("next_available_at") or 0)
        if back > now:
            limit["reset_at"] = back  # The source's: it knows its reserves and exclusions.
        head = "网关里的号额度都用完了"
    elif outcome.error_code == "quota_exhausted" and not result.failure_detail:
        head = "模型服务的额度用完了"
    else:
        return result
    reset = float(limit.get("reset_at") or 0)
    detail = head + (f"，最早 {clock(reset, now)} 恢复" if reset > now else "")
    changed = dataclasses.replace(outcome, error_code="quota_exhausted")
    return dataclasses.replace(result, text=changed.summary(detail), outcome=changed, failure_detail=detail,
                               limit=limit or None)
