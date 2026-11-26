"""The deployment's home (主目录): where every topic starts, and where its outputs go (``<state>/home.json``).

The home is the service's ``--workdir`` (FINAL-SPEC 修订 9: one way to start, no second path). A taken-over
directory gets no file written into it; a new install's default home has a short AGENTS.md (and CLAUDE.md), the
rendered repo map and ``tasks/``. ``home.json`` holds the templates of a topic's run and session directories and
whether the Harness's cache variables point into the run directory. A0: the shape and its read with defaults; nothing
calls it yet (package W1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

HOME_FILE = "home.json"
RUN_SCOPES = ("topic_day", "turn")
TEMPLATE_VARS = ("home", "date", "no", "slug", "topic8", "run")


@dataclass(frozen=True)
class HomeConfig:
    runs_template: str = "{home}/tasks/runs/{date}-T{no}-{slug}/{run}"
    sessions_template: str = "{home}/tasks/sessions/{date}-T{no}-{slug}"
    cache_env: bool = False
    run_scope: str = "topic_day"  # RUN_SCOPES


def path(state_dir) -> Path:
    return Path(state_dir) / HOME_FILE


def read(state_dir) -> HomeConfig:
    """``home.json``'s settings over the defaults; the defaults when it is missing or unreadable."""
    try:
        data = json.loads(path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return HomeConfig()
    if not isinstance(data, dict):
        return HomeConfig()
    known = {key: data[key] for key in HomeConfig.__dataclass_fields__ if key in data}
    if not all(isinstance(known.get(key, ""), str) for key in ("runs_template", "sessions_template", "run_scope")):
        return HomeConfig()
    if known.get("run_scope", "topic_day") not in RUN_SCOPES:
        known.pop("run_scope")
    known["cache_env"] = bool(known.get("cache_env", False))
    return HomeConfig(**known)


def home_dir(workdir) -> Path:
    """The home of a deployment whose service runs with ``--workdir`` ``workdir``."""
    return Path(workdir)


def render(template: str, **values) -> str:
    """``template`` with ``TEMPLATE_VARS`` filled; a variable not given stays as written."""
    out = str(template)
    for name in TEMPLATE_VARS:
        if name in values:
            out = out.replace("{" + name + "}", str(values[name]))
    return out
