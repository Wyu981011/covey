"""额度恢复了的一句话 (T831): a turn that failed on a spent quota whose reset is known but further off than
auto_retry.MAX_RESET_WAIT gets no automatic retry (its card says when the quota is back); when that time comes the owner is
told in one line which topic stopped there, that the time has come, and that it can go on.

- ``register`` (the worker, after auto_retry.plan said none): writes ``<state>/quota/returns.json``, one entry a topic and reset
  time, so a Bridge restart keeps it. ``tick`` (the Bridge's outbox loop, as app/limit_notice.py) looks at them every TICK seconds.
- Once: an entry is ``waiting``, then ``said`` (written before the send, so a send that may have gone out is not repeated;
  one that failed outright, or had no chat to go to, is tried again). Topics due together are one message.
- Not said when the topic has had a newer task since, or the owner clicked 检查并继续 (the failed job's ``retried_by``): the
  entry is dropped. In the quiet hours (core/quiet_hours.py) nothing is sent: the first look after them says it.
- Entries that were said or dropped are forgotten after KEEP seconds.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from covey.app import auto_retry
from covey.backends.agy import accounts as agy_accounts
from covey.core import quiet_hours, quota, quota_sources, turn_source
from covey.core.jobs import find_job_record, job_key, select_job_records
from covey.core.locks import resource_lock
from covey.core.state import ensure_private_dir, read_json, write_json
from covey.core.topics import label_title

FILE = "returns.json"
TICK = 30  # Seconds between two looks of the outbox loop.
KEEP = 7 * 86400  # How long an entry that is over is kept.
MAX_LISTED = 8
_last = {}  # state dir -> when ``tick`` last looked.


def path(state_dir) -> Path:
    return Path(state_dir) / quota.FOLDER / FILE


def read(state_dir) -> dict:
    try:
        saved = read_json(path(state_dir), None)
    except (OSError, ValueError):
        saved = None
    entries = saved.get("entries") if isinstance(saved, dict) else None
    return entries if isinstance(entries, dict) else {}


def write(state_dir, entries) -> None:
    ensure_private_dir(path(state_dir).parent)
    write_json(path(state_dir), {"entries": entries}, ensure_ascii=False, indent=1)


def source_name(job, limit) -> str:
    """Which quota source ran out, as the line names it: the pool behind Claude Code's login (its title), agy with the model
    group when the limit says it (``limit.group``), else the Harness's own name."""
    backend = str(getattr(job, "backend", "") or "")
    if backend == "claude":
        found = quota_sources.claude_source()
        return (found.title if found is not None else "") or "Claude"
    if backend == "agy":
        group = limit.get("group") if isinstance(limit, dict) else ""
        return f"agy {agy_accounts.label_of(group)}" if group else "agy"
    return backend


def register(ctx, job, turn, retry, now=None) -> bool:
    """Record the return of the quota ``turn`` (of ``job``) ended on, when it is one that is told of (see the module
    docstring) and ``retry`` (auto_retry.plan's) is None; True when recorded. Never raises."""
    try:
        outcome = getattr(turn, "outcome", None)
        if (retry is not None or outcome is None or (outcome.status, outcome.error_code) != auto_retry.KINDS[auto_retry.QUOTA].outcome
                or getattr(outcome, "policy_event", None) is not None or turn.verified_delivery is not None
                or not job.topic_id or job.cancel_event.is_set() or not quota_sources.enabled()
                or not turn_source.behavior(job).own_delivery):
            return False
        now = time.time() if now is None else now
        said = getattr(turn, "limit", None)
        reset = said.get("reset_at") if isinstance(said, dict) else None
        if isinstance(reset, bool) or not isinstance(reset, (int, float)) or reset - now <= auto_retry.MAX_RESET_WAIT:
            return False  # None known, or one the automatic retry waits for itself.
        key = f"{job.chat_id}|{job.topic_id}|{int(reset)}"
        with resource_lock("record", Path(ctx.state_dir) / quota.FOLDER):
            entries = read(ctx.state_dir)
            if key in entries:
                return False
            entries[key] = {"topic_id": job.topic_id, "chat_id": job.chat_id, "job_id": int(job.job_id),
                            "job_key": job_key(job.message_id, job.job_id), "backend": getattr(job, "backend", "") or "",
                            "reset_at": float(reset), "state": "waiting", "noted_at": now,
                            "source": source_name(job, said)}
            write(ctx.state_dir, entries)
        return True
    except Exception:  # noqa: BLE001 - a line the owner would have had; the turn's delivery does not depend on it
        return False


def superseded(gateway, state_dir, entry) -> bool:
    """Whether the topic has gone on since the stop: a newer task in it, or the owner's retry of the stopped one."""
    record = find_job_record(state_dir, entry["job_key"]) or {}
    if record.get("retried_by"):
        return True
    topic, chat, number = entry["topic_id"], entry["chat_id"], int(entry["job_id"])
    newer = select_job_records(Path(state_dir), lambda r: r.get("topic_id") == topic and r.get("chat_id") == chat
                               and int(r.get("job_id") or 0) > number
                               and str(r.get("merged_into_job_id")) != str(number))
    return bool(newer) or any(int(j.job_id) > number for j in gateway.runtime.jobs.topic_jobs(topic, chat))


def words(state_dir, due, profile=None) -> str:
    """The message for the ``due`` entries, a part for each source (an old entry has none, and no name): "Claude 网关额度已恢复
    （17:10）：[T5 修登录接口](url) 停在额度用完，可以接着做。"; with several topics of a source, one line each under it."""
    from covey.app.relay_send import topic_url

    groups = {}
    for entry in due:
        groups.setdefault(entry.get("source") or "", []).append(entry)
    parts = []
    for source, entries in groups.items():
        links = []
        for entry in entries[:MAX_LISTED]:
            label, title = label_title(state_dir, entry["topic_id"], "")
            name = " ".join(part for part in (label, title) if part) or f"任务 #{entry['job_id']}"
            url = topic_url(state_dir, entry["topic_id"], profile=profile)
            links.append(f"[{name}]({url})" if url else name)
        head = f"{source}额度已恢复（{auto_retry.clock(min(e['reset_at'] for e in entries))}）："
        if len(entries) == 1:
            parts.append(f"{head}{links[0]} 停在额度用完，可以接着做。")
        else:
            parts.append(f"{head}{len(entries)} 个话题停在额度用完，可以接着做：\n" + "\n".join(f"- {line}" for line in links)
                         + (f"\n- …另有 {len(entries) - MAX_LISTED} 个" if len(entries) > MAX_LISTED else ""))
    return "\n".join(parts)


def tick(gateway, ctx, *, now=None):
    """An outbox-loop step. Never raises."""
    now = time.time() if now is None else now
    if now - _last.get(str(ctx.state_dir), 0) < TICK:
        return
    _last[str(ctx.state_dir)] = now
    try:
        step(gateway, ctx, now)
    except Exception as exc:  # noqa: BLE001 - tried again at the next look
        gateway.runtime.log(f"quota return notice failed: {type(exc).__name__}")


def step(gateway, ctx, now) -> str:
    """One look; the text sent ('' when none)."""
    state = Path(ctx.state_dir)
    if not read(state):
        return ""
    with resource_lock("record", state / quota.FOLDER):
        entries = read(state)
        for key, entry in entries.items():
            if entry.get("state") == "waiting" and entry["reset_at"] <= now and superseded(gateway, state, entry):
                entry["state"] = "dropped"
                entry["at"] = now
        entries = {key: entry for key, entry in entries.items()
                   if entry.get("state") == "waiting" or now - float(entry.get("at") or now) < KEEP}
        due = [(key, entry) for key, entry in entries.items() if entry.get("state") == "waiting" and entry["reset_at"] <= now]
        chat = gateway.runtime.access.notify_chat()
        held = bool(due) and quiet_hours.quiet(now)
        if not due or not chat or held:
            write(state, entries)
            if held:
                gateway.runtime.log(f"quota return notice held {quiet_hours.words(now)} {len(due)}")
            return ""
        due.sort(key=lambda item: item[1]["reset_at"])
        for _key, entry in due:
            entry.update(state="said", at=now)
        write(state, entries)  # Before it is sent: not sent again after a send that may have gone out.
    text = words(state, [entry for _key, entry in due], ctx.profile)
    digest = hashlib.sha256("|".join(key for key, _entry in due).encode()).hexdigest()[:12]
    try:
        sent = gateway.messenger.send_message(ctx.profile, chat, text, gateway.voice.safe_key(f"quota-return-{digest}"),
                                              voice=gateway.voice)
    except Exception as exc:  # noqa: BLE001 - it may have gone out: not repeated (rule 1 of AGENTS.md)
        gateway.runtime.log(f"quota return notice failed: {type(exc).__name__}")
        return ""
    if not sent:  # Failed outright, or no chat: tried again at the next look.
        with resource_lock("record", state / quota.FOLDER):
            entries = read(state)
            for key, _entry in due:
                if key in entries:
                    entries[key].update(state="waiting")
            write(state, entries)
        return ""
    gateway.runtime.log(f"quota return notice sent topics={len(due)}")
    return text
