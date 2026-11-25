"""The state directory's disk at the Bridge (core/storage_watch.py): its watcher of slow locks and reads started, and one
message to the owner when writes are refused for want of space.

Once the disk under the state directory is full (a quota: "Disk quota exceeded") every record write fails: the outbox
step that saves the record indexes failed 130 times a day and the log said "OSError" alone, the task cards and the
records stopped keeping up, and no one was told (T784). Now ``tick`` (every POLL seconds) sends the owner's private chat
(``Access.notify_chat``) one line when a refused write was seen since the last one it sent, at most once in EVERY
seconds; the diagnostics (service/doctor_words.py, the 设置 card's 诊断 tab) say it as long as it is recent. A send that
fails (its own receipt may need the full disk) is tried again RETRY seconds on.
"""
from __future__ import annotations

import time

from covey.app import pins
from covey.core import storage_watch
from covey.core.loops import every
from covey.core.text import cut, stamp

POLL = 30
EVERY = 6 * 3600
RETRY = 600


def alert_text(found) -> str:
    """The owner's line for ``found`` (storage_watch.snapshot()["full"])."""
    where = f"（{cut(found.get('directory'), 60)}）" if found.get("directory") else ""
    times = f"，{found['count']} 次" if int(found.get("count") or 0) > 1 else ""
    return (f"⚠️ 状态目录的磁盘写不进了：{found.get('error') or '空间不足'}{where}。最近一次 {stamp(found.get('at'), '%H:%M')}"
            f"{times}。任务记录、卡片进度和结果可能存不下；清出空间或扩大配额后会自己恢复，不用重启。")


class StorageAlerts:
    def __init__(self, runtime, messenger, voice) -> None:
        self.runtime, self.messenger, self.voice = runtime, messenger, voice
        self.sent_at = self.tried_at = 0.0
        self.told = 0.0  # The ``at`` of the refused write the last alert said.

    def threads(self):
        return (("storage-alerts", self.run),)

    def run(self, ctx) -> None:
        storage_watch.start(self.runtime.log)
        every(self.runtime, POLL, self.tick, args=(ctx,), isolate="storage")

    def tick(self, ctx, now=None) -> bool:
        """Send the alert when a refused write was seen since the last one and EVERY has passed; whether it went."""
        now = time.time() if now is None else now
        found = storage_watch.snapshot(now).get("full")
        if (not found or found.get("at", 0) <= self.told or now - self.sent_at < EVERY
                or now - self.tried_at < RETRY):
            return False
        self.tried_at = now
        chat = self.runtime.access.notify_chat()
        if not chat:
            return False
        key = self.voice.safe_key(f"storage-full-{int(found['at'])}")
        # At the top level: a reply to it is the butler's (app/pins.py remember_notice).
        sent = self.messenger.send_message(ctx.profile, chat, alert_text(found), key, voice=self.voice,
                                           on_sent=lambda message: pins.remember_notice(ctx.state_dir, chat, message))
        if sent:
            self.sent_at, self.told = now, found["at"]
            self.runtime.log("storage alert sent: writes refused for want of space")
        return bool(sent)
