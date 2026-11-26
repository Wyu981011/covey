"""A topic hears that another topic works in the same git repository.

At the start of an ordinary topic's turn ``note`` finds the repository of its workdir (``repo_of``: the nearest ancestor
holding ``.git``, a linked worktree counting as the repository its ``.git`` file points to; cached for ``TTL`` seconds, at
most ``DEPTH`` levels up, nothing for a device) and the other topics with a running or queued task whose workdir is in the
same repository and whose record changed within ``WINDOW`` seconds. With any it is one line naming them (T number and title)
and the rule for pushing, merging and deploying; without, ''. Never blocks and never raises: a path that cannot be read is
no repository.
"""
from __future__ import annotations

import time
from pathlib import Path

from covey.core import topic_repos
from covey.core.butler import is_butler_topic
from covey.core.jobs import running_job_records
from covey.core.state import epoch_seconds
from covey.core.topics import label_title, proxy_topic
from covey.core.topic_repos import repo_of

TTL, DEPTH = topic_repos.TTL, topic_repos.DEPTH  # Of repo_of (core/topic_repos.py since the overhaul's A0), as named here before.
_cache = topic_repos.cache  # The same dict: the tests clear it between cases.

WINDOW = 30 * 60
SHOWN = 3
TITLE = 20
SIMILAR = 0.3  # Of titles, in the same repository.
SEEN = 50  # Records looked at per turn.
RULE = ("推送、合并、部署之前先 git fetch，落后就 rebase 并重测；只提交自己改的文件，推送前看 git diff origin/main...HEAD --stat。")


def others(state_dir, topic_id, workdir, now=None) -> list[tuple[str, str]]:
    """(``named``, title) of each other topic with a running or queued task in ``workdir``'s repository, newest first."""
    now = time.time() if now is None else now
    repo = repo_of(workdir, now)
    if not repo:
        return []
    found, seen = [], set()
    for record in running_job_records(Path(state_dir))[:SEEN]:
        other = record.get("topic_id")
        if not other or other == topic_id or other in seen or record.get("device") or record.get("kind", "chat") != "chat":
            continue
        changed = epoch_seconds(str(record.get("updated_at") or record.get("created_at") or ""))
        if changed is None or now - changed > WINDOW or repo_of(record.get("workdir"), now) != repo:
            continue
        if is_butler_topic(other, record.get("chat_id")):
            continue
        seen.add(other)
        number, title = label_title(state_dir, other)
        title = " ".join(str(title).split())
        found.append((f"{number}《{title[:TITLE]}{'…' if len(title) > TITLE else ''}》" if title else number or "另一个话题", title))
    return found


def _grams(text):
    text = "".join(ch for ch in str(text).lower() if ch.isalnum())
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def similar(a, b) -> float:
    """How alike two titles are, 0 to 1: the share of their character pairs they have in common."""
    left, right = _grams(a), _grams(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def duplicates(state_dir, topic_id, workdir, title, now=None) -> list[str]:
    """``named`` of the topics working in ``workdir``'s repository with a title like ``title`` (SIMILAR), for the butler's
    topic_start to say 可能重复; [] for none and on any failure. It only says so, never refuses."""
    try:
        return [named for named, other in others(state_dir, topic_id, workdir, now) if similar(title, other) >= SIMILAR][:SHOWN]
    except Exception:  # noqa: BLE001 - a hint
        return []


def note(ctx, job, now=None) -> str:
    """The turn's line about the topics working in the same repository, '' for none; an ordinary topic's own turn, not a
    device's, a 代答 topic's or the butler's."""
    try:
        topic = job.topic_id or ctx.topic_id
        if (not topic or ctx.device or proxy_topic(ctx) or is_butler_topic(topic, job.chat_id)
                or getattr(job, "read_only", False)):
            return ""
        names = others(ctx.state_dir, topic, ctx.workdir, now)
    except Exception:  # noqa: BLE001 - a hint, never a failed turn
        return ""
    if not names:
        return ""
    names = [named for named, _ in names]
    more = f"等 {len(names)} 个话题" if len(names) > SHOWN else ""
    return "同一个仓库里还有话题在做：" + "、".join(names[:SHOWN]) + more + "。" + RULE
