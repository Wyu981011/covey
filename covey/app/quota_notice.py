"""账号与额度's two notices to the owner: when a state turns true, once, in the notify chat, in a line or two and the web page's
address (W1b, docs/quota.md 页面和提醒; core/web_sync.py ``page_url``, none without COVEY_WEB). Read from the page's own view
(app/web_quota.py), so what the page shows and what the owner is told cannot differ.

- a source has no account that can be used and some come back by themselves (``dry``): "Claude · 我的 VPS 现在没有能用的号，最早 17:10 恢复";
- an account needs a sign-in again (``relogin``): "agy 的 a@example.com 要重新登录".

The same thing is never said twice: ``<state>/quota/notices.json`` keeps what has been said and drops it when it stops being true,
so it is news again if it comes back. The first look of a state directory only records what is already so (a deployment does
not announce an old state). In the quiet hours (core/quiet_hours.py) nothing is sent and nothing recorded: the first look after
them says what is still so, in one message. What is recorded before it is sent is not sent again if the send fails halfway (rule 1 of
AGENTS.md: a write is not replayed), but a send that failed outright, or had no chat to go to, is tried again at the next look.
"""
from __future__ import annotations

import time
from pathlib import Path

from covey.app import web_quota
from covey.core import quiet_hours, quota, web_sync
from covey.core.state import ensure_private_dir, read_json, write_json

FILE = "notices.json"
PAGE_PATH = "/settings/quota"


def facts(view) -> dict:
    """{"dry": {source id: words}, "login": {"source id|name": words}} that are so in ``view`` (app/web_quota.py view)."""
    found = {"dry": {}, "login": {}}
    for source in view.get("sources") or ():
        if source.get("dry"):
            back = source.get("next_available_at")
            found["dry"][source["id"]] = f"{source['title']} 现在没有能用的号" + (f"，最早 {web_quota.clock(back)} 恢复" if back else "")
        for name in source.get("relogin") or ():
            found["login"][f"{source['id']}|{name}"] = f"{source['title']} 的 {name} 要重新登录"
    return found


def words(new) -> str:
    """The message for the facts in ``new`` (``facts``' shape, only the new ones)."""
    parts = [*new["dry"].values(), *new["login"].values()]
    url = web_sync.page_url()
    return "；".join(parts) + "。" + (f"去网页看：{url.rstrip('/')}{PAGE_PATH}" if url else "")


class Notice:
    """``state_dir``; ``send(text)``: True when the message went, False when it failed, None with no chat to send it to; ``log(line)``."""

    def __init__(self, state_dir, send, log=lambda text: None, environ=None, clock=time.time) -> None:
        self.path = Path(state_dir) / quota.FOLDER / FILE
        self.state_dir, self.send, self.log, self.environ, self.clock = state_dir, send, log, environ, clock

    def read(self):
        try:
            saved = read_json(self.path, None)
        except (OSError, ValueError):
            saved = None
        return saved if isinstance(saved, dict) else None

    def write(self, saved) -> None:
        ensure_private_dir(self.path.parent)
        write_json(self.path, saved, ensure_ascii=False, indent=1)

    def step(self, now=None) -> str:
        """One look; the text sent ('' when none)."""
        now = self.clock() if now is None else now
        found = facts(web_quota.view(self.state_dir, now))
        saved = self.read()
        first = saved is None
        saved = saved or {}
        for kind in found:  # What stopped being so is forgotten: it is news again if it comes back.
            saved[kind] = {key: at for key, at in (saved.get(kind) or {}).items() if key in found[kind]}
        new = {kind: {key: text for key, text in found[kind].items() if key not in saved[kind]} for kind in found}
        if first:  # A state directory's first look: the state as it is is not news.
            for kind in found:
                saved[kind] = {key: now for key in found[kind]}
            self.write(saved)
            return ""
        if not any(new.values()):
            self.write(saved)
            return ""
        if quiet_hours.quiet(now, self.environ):
            self.write(saved)
            self.log(f"quota notice held {quiet_hours.words(now, self.environ)} {sum(len(v) for v in new.values())}")
            return ""
        before = {kind: dict(saved[kind]) for kind in saved}
        for kind in new:
            saved[kind].update({key: now for key in new[kind]})
        self.write(saved)  # Before it is sent: not sent again after a send that may have gone out.
        text = words(new)
        try:
            sent = self.send(text)
        except Exception as exc:  # noqa: BLE001 - tried again at the next look
            self.log(f"quota notice failed: {type(exc).__name__}")
            sent = False
        if not sent:
            self.write(before)
            return ""
        self.log(f"quota notice sent dry={len(new['dry'])} login={len(new['login'])}")
        return text
