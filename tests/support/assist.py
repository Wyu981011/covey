"""The Bridge's topics as app/assist.py (辅助模型) reads them, for the tests of its callers."""
from __future__ import annotations

from types import SimpleNamespace

from covey.app import assist


def harness_app(backend, ctx):
    """A Harness app of the Bridge as app/assist.py and app/butler_harness.py read it."""
    return SimpleNamespace(harness=SimpleNamespace(backend=backend, context=ctx), backend=backend)


def topics_with(state, apps=None, *, default="", health=None):
    """``apps``: {name: app with .harness.backend and .harness.context}; ``default`` the Bridge's default Harness (the first
    of ``apps`` when not given); ``health``: runtime.availability_health. The settings and records of app/assist.py are
    read afresh."""
    assist.forget()
    apps = dict(apps or {})
    runtime = SimpleNamespace(state_dir=state, availability_health=health or {}, log=lambda line: None)
    return SimpleNamespace(apps=apps, default=default or next(iter(apps), ""), runtime=runtime)


def claude_topics(state, backend, ctx):
    """One Claude Code Harness: the 辅助模型 (自动) goes to it."""
    return topics_with(state, {"claude": harness_app(backend, ctx)})
