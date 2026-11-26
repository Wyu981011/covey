"""账号与额度 at the Bridge (docs/quota.md): one thread that keeps the quota snapshots (core/quota.py) current, unless
COVEY_QUOTA=0. Every TICK seconds the sources that are due are read (core/quota_sources.py ``refresh``: the gateway
Claude Code signs in to, the commands and addresses of quota-sources.json, each at its own interval) and the agy
snapshots are written from the accounts' state (backends/agy/accounts.py ``snapshots``: no account is asked). The page,
the reminders and the failure cards read the files; nothing is sent from here.

A Bridge with nothing to read (no https gateway, no quota-sources.json, fewer than two agy accounts) starts no thread
(``wanted``, asked when the threads are listed: a source added later is read after the next restart). A
quota-sources.json that may not be used (another user's, or others may write it) is written to the log once a change.
"""
from __future__ import annotations

from covey.backends.agy import accounts
from covey.core import quota_sources

TICK = 60  # Seconds between looks.
START_WAIT = 20  # Seconds after the Bridge starts before the first.


def wanted(environ=None) -> bool:
    """Whether there is anything to read (see the module docstring)."""
    if not quota_sources.enabled(environ):
        return False
    found, problem = quota_sources.sources(environ)
    return bool(found or problem or accounts.configured(environ))


class QuotaWatch:
    """The feature object (app/unified.py): its thread, none when ``wanted`` says there is nothing to read."""
    name = "quota"

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.problem = ""

    def threads(self):
        return ((self.name, self.run),) if wanted() else ()

    def run(self, ctx) -> None:
        from covey.core.loops import every

        if self.runtime.shutdown.wait(START_WAIT):
            return
        every(self.runtime, TICK, self.tick, args=(ctx,), isolate=self.name)

    def tick(self, ctx) -> list:
        """One look: the due sources read and the agy snapshots written; the source ids written."""
        if not quota_sources.enabled():
            return []
        found, problem = quota_sources.sources()
        if problem != self.problem:
            self.problem = problem
            if problem:
                self.runtime.log(f"quota: {quota_sources.CONFIG_FILE} not used: {problem}")
        quota_sources.forget_gone(ctx.state_dir, found)
        done = quota_sources.refresh(ctx.state_dir, found)
        return done + accounts.snapshots(ctx.state_dir)
