"""Which providers of a Harness are one account (T786: 「Claude 自带」 and a gateway set up for the very account Claude Code
signs in with were two providers on the cards, and the owner asked why one account was shown twice).

A Harness's own login goes somewhere (``own_login``): Claude Code to its ``ANTHROPIC_BASE_URL`` with ``ANTHROPIC_AUTH_TOKEN`` or
``ANTHROPIC_API_KEY`` (the process's environment, else the ``env`` of its user settings.json, core/claude_retention.py
``settings_path``); Codex to the ``model_providers`` entry its config.toml's ``model_provider`` names (its ``base_url``, the key in
the variable its ``env_key`` names). A gateway of the Harness (core/gateways.py) at the same address with the same key is that
account (``folded``): the model selects show it once (app/launch_models.py ``fold_same_account``), under the gateway's name.

Addresses are compared without a trailing slash and the case of the scheme and host; keys by their SHA-256, never kept or shown.
A login that names no address of its own (the vendor's sign-in) is no gateway's, and a key that cannot be read folds nothing.
What is read is kept ``FRESH`` seconds: the menus are drawn often. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

FRESH = 30.0
_cache: dict = {}
_lock = threading.Lock()


def address(url) -> str:
    """``url`` as compared: scheme and host lower-cased, no trailing slash; '' for none."""
    text = str(url or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def digest(key) -> str:
    key = str(key or "").strip()
    return hashlib.sha256(key.encode()).hexdigest() if key else ""


def _claude(environ):
    from covey.core.claude_retention import settings_path

    env = {}
    try:
        found = json.loads(settings_path(environ).read_text()).get("env")
        env = found if isinstance(found, dict) else {}
    except (OSError, ValueError, AttributeError):
        pass

    url = address(environ.get("ANTHROPIC_BASE_URL") or env.get("ANTHROPIC_BASE_URL"))
    key = str(environ.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_AUTH_TOKEN") or environ.get("ANTHROPIC_API_KEY")
              or env.get("ANTHROPIC_API_KEY") or "").strip()
    return (url, digest(key)) if url and key else None


def _codex(environ):
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10.
        from covey.core import toml_compat as tomllib
    home = str(environ.get("CODEX_HOME") or "").strip()
    path = (Path(home).expanduser() if home else Path.home() / ".codex") / "config.toml"
    try:
        config = tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return None
    name = config.get("model_provider")
    entry = (config.get("model_providers") or {}).get(name) if isinstance(name, str) else None
    if not isinstance(entry, dict):
        return None
    url = address(entry.get("base_url"))
    variable = entry.get("env_key")
    key = str(environ.get(variable) or "").strip() if isinstance(variable, str) and variable else ""
    return (url, digest(key)) if url and key else None


READERS = {"claude": _claude, "codex": _codex}


def own_login(harness, environ=None):
    """(address, key digest) of ``harness``'s own login, None when it names none (or a Harness READERS does not know)."""
    reader = READERS.get(harness)
    return reader(os.environ if environ is None else environ) if reader else None


def gateway_login(gateway, environ=None):
    """(address, key digest) of ``gateway`` (core/gateways.py Gateway): its key from its variable, else its file."""
    environ = os.environ if environ is None else environ
    key = str(environ.get(gateway.key_env) or "").strip()
    if not key:
        try:
            key = gateway.key_path().read_text().strip()
        except OSError:
            key = ""
    url = address((str(environ.get(gateway.base_url_env) or "").strip() if gateway.base_url_env else "") or gateway.base_url)
    return (url, digest(key)) if url and key else None


def folded(harness, environ=None) -> tuple:
    """The names of ``harness``'s gateways that are its own login's account, in the gateways' order; () for none."""
    from covey.core import gateways

    now = time.monotonic()
    key = (harness, id(environ) if environ is not None else None)
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < FRESH and environ is None:
            return hit[1]
    own = own_login(harness, environ)
    names = tuple(g.name for g in gateways.for_harness(harness) if own and gateway_login(g, environ) == own) if own else ()
    if environ is None:
        with _lock:
            _cache[key] = (now, names)
    return names


def forget() -> None:
    """Read again at the next call (tests)."""
    with _lock:
        _cache.clear()
