"""The bot's Feishu slash commands (/usage, /board, /proxy, /settings), synced as the bot through the official API (no browser).

Feishu exposes slash commands over OpenAPI (``application/v7/app_slash_commands``) using the bot's own
``application:app_slash_command:read`` and ``application:app_slash_command:write`` scopes — no developer
console login, no headless Chromium and no version publish. ``sync`` lists the app's current commands,
creates or updates only Covey's missing or changed ones (``--force`` keeps an existing ``command_id``),
and never removes other commands on the app.
"""
from __future__ import annotations

import subprocess

from covey.core import app_manifest
from covey.feishu.app_config import ApiError
from covey.feishu.transport import CliFailed, cli_json, lark_argv, last_json

TIMEOUT = 30
UNSUPPORTED_HINTS = ("unknown command", "unknown flag", "unknown shorthand")


class UnsupportedError(RuntimeError):
    """This lark-cli binary does not provide ``application +slash-command-*`` yet."""


def _run_json(argv, *, runner=None):
    """Run one lark-cli slash-command shortcut and return its ``data`` dict."""
    try:
        payload = cli_json(argv, timeout=TIMEOUT, runner=runner or subprocess.run, expect=dict)
    except CliFailed as exc:
        payload = last_json(exc.proc.stdout) or last_json(exc.proc.stderr)
        if not payload:
            combined = f"{exc.proc.stderr or ''} {exc.proc.stdout or ''}".lower()
            if any(hint in combined for hint in UNSUPPORTED_HINTS):
                raise UnsupportedError(exc.reason()) from None
            raise
    if payload.get("ok") is False or payload.get("code") not in (None, 0):
        error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        raise ApiError(error.get("code"), str(error.get("message") or error.get("msg") or ""))
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def list_commands(profile, *, runner=None):
    """The app's registered slash commands (list of dicts) via ``lark-cli application +slash-command-list``."""
    argv = lark_argv(profile, "application", "+slash-command-list", "--as", "bot", "--format", "json")
    data = _run_json(argv, runner=runner)
    return [item for item in (data.get("items") or []) if isinstance(item, dict)]


def icon_of(item):
    """An existing slash-command item's icon_key (handles both nested ``icon.icon_key`` and flat ``icon_key``)."""
    icon = item.get("icon")
    if isinstance(icon, dict) and icon.get("icon_key"):
        return str(icon["icon_key"])
    return str(item.get("icon_key") or "")


def matches(item, spec):
    """Whether an online slash-command item already matches ``spec`` (no write call needed)."""
    if str(item.get("command") or "") != spec.command:
        return False
    desc = item.get("description") if isinstance(item.get("description"), dict) else {}
    if str(desc.get("default_value") or "") != spec.description:
        return False
    i18n = desc.get("i18n") if isinstance(desc.get("i18n"), dict) else {}
    if str(i18n.get("zh_cn") or "") != spec.description:
        return False
    if spec.en_description and str(i18n.get("en_us") or "") != spec.en_description:
        return False
    return (icon_of(item) or app_manifest.SLASH_ICON) == spec.icon_key


def upsert_command(profile, spec, *, runner=None):
    """Create or update one slash command in place (``--force`` preserves ``command_id`` on name collision)."""
    argv = lark_argv(
        profile, "application", "+slash-command-create",
        "--as", "bot", "--force",
        "--command", spec.command,
        "--description", spec.description,
        "--description-i18n", f"zh_cn={spec.description}",
        *(["--description-i18n", f"en_us={spec.en_description}"] if spec.en_description else []),
        "--icon-key", spec.icon_key,
        "--format", "json",
    )
    return _run_json(argv, runner=runner)


def _error_result(wanted, error, detail):
    return {"ok": False, "error": error, "detail": str(detail)[:200], "wanted": [s.command for s in wanted],
            "synced": [], "unchanged": [], "failed": []}


def missing(profile, env=None, *, runner=None):
    """Read-only check: ``(missing_specs, error_code)`` against the app's registered slash commands."""
    wanted = app_manifest.slash_commands(env)
    try:
        current = list_commands(profile, runner=runner)
    except ApiError as exc:
        return [], ("no_scope" if exc.scope else "failed")
    except UnsupportedError:
        return [], "unsupported"
    except (CliFailed, ValueError, OSError, subprocess.SubprocessError):
        return [], "failed"
    by_name = {str(item.get("command") or ""): item for item in current if item.get("command")}
    return [spec for spec in wanted if spec.command not in by_name or not matches(by_name[spec.command], spec)], ""


def sync(profile, env=None, *, runner=None):
    """Idempotently register/update this deployment's Covey slash commands. Never raises; never removes other commands."""
    wanted = app_manifest.slash_commands(env)
    try:
        current = list_commands(profile, runner=runner)
    except ApiError as exc:
        return _error_result(wanted, "no_scope" if exc.scope else "failed", exc)
    except UnsupportedError as exc:
        return _error_result(wanted, "unsupported", exc)
    except (CliFailed, ValueError, OSError, subprocess.SubprocessError) as exc:
        detail = exc.reason() if isinstance(exc, CliFailed) else f"{type(exc).__name__}: {exc}"
        return _error_result(wanted, "failed", detail)

    by_name = {str(item.get("command") or ""): item for item in current if item.get("command")}
    synced, unchanged, failed = [], [], []
    scope_missing = False
    for spec in wanted:
        existing = by_name.get(spec.command)
        if existing is not None and matches(existing, spec):
            unchanged.append(spec.command)
            continue
        try:
            upsert_command(profile, spec, runner=runner)
            synced.append(spec.command)
        except ApiError as exc:
            if exc.scope:
                scope_missing = True
            failed.append((spec.command, str(exc)[:200]))
        except UnsupportedError as exc:
            return _error_result(wanted, "unsupported", exc)
        except (CliFailed, ValueError, OSError, subprocess.SubprocessError) as exc:
            detail = exc.reason() if isinstance(exc, CliFailed) else f"{type(exc).__name__}: {exc}"
            failed.append((spec.command, detail[:200]))

    error = "no_scope" if scope_missing else ("failed" if failed else "")
    detail = "; ".join(f"/{cmd}: {msg}" for cmd, msg in failed[:4])
    return {"ok": not failed, "error": error, "detail": detail[:200],
            "wanted": [s.command for s in wanted], "synced": synced, "unchanged": unchanged, "failed": failed}
