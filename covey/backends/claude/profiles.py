"""Configured Claude gateways: named model choices, with pending profiles refused before any command starts."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import re

from covey.core.process import device_of

CONFIG = "claude_profiles"
SELECTED = "claude_profile_model"
PREFIX = "profile/"
DEVICE_REASON = "该供应商仅支持机器人所在主机，不能切换执行设备"
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultracode"})
# A profile wrapper loads its own gateway settings; another gateway's inherited settings must not select it.
GATEWAY_ENV = frozenset({"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
                         "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                         "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_CODE_OAUTH_TOKEN",
                         "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                         "COVEY_CLAUDE_REDACTION_ENDPOINT", "COVEY_CLAUDE_REDACTION_UPSTREAM"})


def _text(value, limit, *, empty=False):
    return (isinstance(value, str) and (empty or bool(value)) and len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def load(path):
    """Read an administrator's explicit catalog; it contains no credentials and never probes a gateway."""
    if not path:
        return []
    try:
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError
        with Path(path).open(encoding="utf-8") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"version", "profiles"} or type(data["version"]) is not int or data["version"] != 1
                or not isinstance(data["profiles"], list) or len(data["profiles"]) > 128):
            raise ValueError
        seen = set()
        for profile in data["profiles"]:
            if not isinstance(profile, dict) or set(profile) - {"id", "name", "command", "status", "reason", "models"}:
                raise ValueError
            identifier = profile.get("id")
            if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identifier)
                    or identifier in seen or not _text(profile.get("name"), 80)
                    or profile.get("status") not in {"ready", "pending"}
                    or not _text(profile.get("reason", ""), 240, empty=True)):
                raise ValueError
            seen.add(identifier)
            command = profile.get("command")
            if (not isinstance(command, list) or not command or len(command) > 64
                    or any(not _text(part, 4096) for part in command) or not Path(command[0]).is_absolute()):
                raise ValueError
            rows, models = profile.get("models"), set()
            if not isinstance(rows, list) or not rows or len(rows) > 1024:
                raise ValueError
            for row in rows:
                if not isinstance(row, dict) or set(row) - {"id", "display_name", "efforts", "default"}:
                    raise ValueError
                model, efforts = row.get("id"), row.get("efforts")
                if (not _text(model, 256) or any(c.isspace() for c in model) or model.startswith(PREFIX)
                        or model in models or not _text(row.get("display_name"), 120)
                        or not isinstance(efforts, list) or any(not isinstance(e, str) or e not in EFFORTS for e in efforts)
                        or len(set(efforts)) != len(efforts)
                        or row.get("default", "") not in ["", *efforts]):
                    raise ValueError
                models.add(model)
        return data["profiles"]
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("Claude profiles 配置无效或无法读取，未使用默认账号替代") from None


def selected(ctx):
    """The saved profile choice, also on the temporary context whose model has become its native id."""
    model = (getattr(ctx, "options", None) or {}).get(SELECTED) or getattr(ctx, "model", "")
    return model if isinstance(model, str) and model.startswith(PREFIX) else ""


def choice(ctx, model):
    """(profile, model row) for a current configured choice; removed or pending choices never execute."""
    profiles = load((getattr(ctx, "options", None) or {}).get(CONFIG))
    if not isinstance(model, str) or not model.startswith(PREFIX):
        return None
    parts = model.split("/", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError("Claude profile 模型标识无效，请重新选择")
    profile = next((p for p in profiles if p["id"] == parts[1]), None)
    row = next((r for r in profile["models"] if r["id"] == parts[2]), None) if profile else None
    if profile is None or row is None:
        raise ValueError("所选 Claude profile 或模型已移除，请重新选择；未使用默认账号替代")
    if profile["status"] != "ready":
        raise ValueError(profile["name"] + "：" + (profile.get("reason") or "尚未就绪") + "，未启动任务")
    return profile, row


def resolve(ctx):
    """A temporary execution context; the persisted job/model, local workspace and session stay as selected."""
    model = selected(ctx)
    found = choice(ctx, model)
    if found is None:
        return ctx
    if device_of(ctx):
        raise ValueError(DEVICE_REASON)
    profile, row = found
    if ctx.options.get(SELECTED) and (ctx.model != row["id"] or list(ctx.backend_cmd) != profile["command"]):
        raise ValueError("Claude profile 配置在准备任务期间已变化，未发送；请重新开始")
    if ctx.effort and ctx.effort not in row["efforts"]:
        raise ValueError("该 Claude profile 模型不支持此推理档位")
    # A default account's interactive shell must not re-inject its gateway settings into another profile.
    options = {key: value for key, value in ctx.options.items() if key != "login_shell"}
    return dataclasses.replace(ctx, model=row["id"], backend_cmd=list(profile["command"]),
                               options={**options, SELECTED: model})


def environment(ctx, env):
    """Selected wrappers set their own gateway credentials while preserving local session paths and proxies."""
    return {key: value for key, value in env.items() if key not in GATEWAY_ENV} if selected(ctx) else env


def catalog(ctx):
    """The configured menu, including clearly marked pending choices; no profile command runs here."""
    rows = {}
    for profile in load((getattr(ctx, "options", None) or {}).get(CONFIG)):
        for model in profile["models"]:
            slug = PREFIX + profile["id"] + "/" + model["id"]
            row = {"slug": slug, "display_name": model["display_name"],
                   "description": "管理员配置的 Claude 网关", "visibility": "list"}
            # Configured budgets are explicit, not inferred from Claude's default account or another profile.
            row.update(supported_reasoning_levels=[{"effort": e} for e in model["efforts"]],
                       default_reasoning_level=model.get("default", ""), source=profile["name"],
                       provider="claude-profile:" + profile["id"], provider_title=profile["name"],
                       unavailable_reason=(DEVICE_REASON if device_of(ctx) else
                                           (profile.get("reason") or "尚未就绪") if profile["status"] == "pending" else ""),
                       catalog_source="configured_profile")
            rows[slug] = row
    return rows
