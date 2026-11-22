"""A HOME of its own for one Antigravity (``agy``) run that must leave nothing behind: a probe (core/harness_probe.py) or
one of the small model's questions (backends/agy/judge.py).

agy keeps its login, conversations and settings under ``~/.gemini``: ``antigravity-cli/`` (the login token, the
conversations, their summaries, the logs) and ``config/`` (MCP servers, hooks, the global rules GEMINI.md, plugins). Every
``agy -p`` run saves a conversation there (about 0.5 MB, listed by ``/resume``), and loads the owner's MCP servers, hooks and
rules. ``ScratchHome`` (``with ScratchHome(parent) as home``) is a directory under ``parent`` (owner-only, removed on the way
out, its links removed and never followed) whose ``.gemini/antigravity-cli/`` links only ``KEPT`` of the real one, the
login and the CLI's own files, so the conversation, its log and its summaries land in the scratch home and go with it;
``.gemini/config/`` and ``.gemini/settings.json`` are not there at all: no MCP server, hook, rule, plugin or setting of the
owner's. Seen on agy 1.5.14. Standard library and core/state only.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from covey.core.state import ensure_private_dir

GEMINI, CLI = ".gemini", "antigravity-cli"
TOKEN = "antigravity-oauth-token"
# Of the real ~/.gemini/antigravity-cli: the login and what the CLI installs and checks for itself. Not linked: the
# conversations, brain, implicit, conversation_summaries.db*, jetbox_summaries_proto.pb, log, cli.log, crashes, presence,
# persistent_terminals, daemon and mcp, which a run writes or reads as the owner's.
KEPT = (TOKEN, "bin", "builtin", "cache", "installation_id", "jetski_state.pbtxt", "updater", "last_check.timestamp")
# Ways agy is signed in without the token file: an API key or Application Default Credentials.
SIGN_IN_ENV = ("GEMINI_API_KEY", "AGY_ADC_AUTH")


def real_home(env=None) -> Path:
    home = str((env if env is not None else os.environ).get("HOME") or "").strip()
    return Path(home).expanduser() if home else Path.home()


def signed_in(env=None) -> bool:
    """Whether agy has a sign-in to run with in ``env`` (default this process's): the token file of its Google login, or
    one of SIGN_IN_ENV. Without one ``agy -p`` waits a minute for a browser sign-in before it fails."""
    source = env if env is not None else os.environ
    if any(str(source.get(name) or "").strip() for name in SIGN_IN_ENV):
        return True
    return (real_home(env) / GEMINI / CLI / TOKEN).is_file()


class ScratchHome:
    """``with ScratchHome(parent, env) as home``: the run's HOME (a Path), ``env`` the environment whose HOME is the real
    one."""

    PREFIX = "agy-scratch-"

    def __init__(self, parent, env=None):
        self.parent, self.env = Path(parent), env
        self.path = None

    def __enter__(self) -> Path:
        ensure_private_dir(self.parent)
        self.path = Path(tempfile.mkdtemp(prefix=self.PREFIX, dir=str(self.parent)))  # mkdtemp is 0700.
        try:
            cli = self.path / GEMINI / CLI
            cli.mkdir(parents=True, mode=0o700)
            real = real_home(self.env) / GEMINI / CLI
            for name in KEPT:
                if os.path.lexists(real / name):
                    os.symlink(real / name, cli / name)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self.path

    def __exit__(self, *exc) -> None:
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)
            self.path = None
