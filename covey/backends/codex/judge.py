"""One question to Codex and nothing else (CodexBackend.ask_once, core/harness.py HarnessCapabilities.ask_once): the small
model's questions (app/track_judge.py) where no Claude Code is enabled.

``codex exec --ephemeral`` (no session written) in a CODEX_HOME of its own (``JudgeHome``: backends/codex/consult.py's
ConsultHome without the owner's AGENTS.md either: the login and the model's provider, no MCP server, hook, rule, plugin,
skill, memory or history), the read-only sandbox, the tools a question does not need off (``FLAGS``: no shell, no
subagent, no web search), the question's system prompt as the developer instructions and its JSON on standard input (never
in argv), in an empty directory of its own. Its JSONL events are read until the turn completes; the answer is its last agent
message, and the process group is killed then (Codex takes about a second more to exit) or at the limit (core/one_shot.py).
Seen on codex-cli 0.171.0: 5 to 7 s a question (up to 11), about 3 of them the model's over some 15k input tokens of Codex's
own instructions and tools.

The model (``choose``): COVEY_JUDGE_CODEX_MODEL when the account's catalog lists it (core/model_settings.py model_catalog);
else for a light question (the track router, the patrol, the memory candidates, 看看) the first model the catalog lists whose
id or description says it is a light one (``LIGHT``: gpt-6-luna, "Fast and affordable model for easier tasks"), for a heavy
one (整理专项) the owner's own default (no ``-m``). The effort is the lowest the model has for a light question, ``medium``
for a heavy one.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from covey.backends.codex.consult import FLAGS as CONSULT_FLAGS, LEFT_OUT, ConsultHome, real_home
from covey.core import env as cenv
from covey.core.harness import AskFailed
from covey.core.model_settings import model_catalog
from covey.core.one_shot import run_lines
from covey.core.process_env import child_process_env
from covey.core.state import ensure_private_dir

MODEL_ENV = "COVEY_JUDGE_CODEX_MODEL"
# A model the catalog calls light: a word of its id, or its description ("Fast and affordable model for easier tasks").
LIGHT = re.compile(r"(?<![a-z0-9])(luna|mini|nano|lite|small)(?![a-z])|affordable|easier tasks|simpler tasks", re.I)
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
HEAVY_EFFORT = "medium"
# On top of a consult's (apps, plugins, memories, hooks, goals, image generation, web search, the question off): the
# shell, subagents and the other tools a one-line answer has no use for. The app server and exec ignore a key they do not
# know (codex-cli 0.171.0).
FLAGS = (*CONSULT_FLAGS, "features.shell_tool=false", "features.multi_agent=false", "features.browser_use=false",
         "features.computer_use=false", "features.in_app_browser=false", "features.sleep_tool=false",
         "features.tool_suggest=false", "features.skill_search=false", "features.shell_snapshot=false")


class JudgeHome(ConsultHome):
    """A consult's home (backends/codex/consult.py ConsultHome) without the owner's global AGENTS.md too: the question
    reads only its own words. <state>/tmp/codex-judge-*, removed with the question."""

    PREFIX = "codex-judge-"

    @staticmethod
    def leaves_out(name: str) -> bool:
        return name in LEFT_OUT or name.startswith("memories") or name == "AGENTS.md"


def choose(env, *, heavy: bool, environ=None) -> tuple:
    """(model, effort) of a question: '' for Codex's own default (see the module docstring)."""
    catalog = model_catalog(real_home(env))
    wanted = str(cenv.get(MODEL_ENV, "", environ) or "").strip()
    if wanted and (not catalog or wanted in catalog):
        model = wanted
    elif heavy:
        model = ""
    else:
        model = next((slug for slug, row in catalog.items()
                      if LIGHT.search(slug) or LIGHT.search(str(row.get("description") or ""))), "")
    levels = [level.get("effort") for level in (catalog.get(model) or {}).get("supported_reasoning_levels") or ()
              if isinstance(level, dict)]
    levels = [effort for effort in EFFORTS if effort in levels]
    if heavy:
        effort = HEAVY_EFFORT if not levels or HEAVY_EFFORT in levels else levels[0]
    else:
        effort = levels[0] if levels else "low"
    return model, effort


def argv(ctx, system: str, model: str, effort: str) -> list:
    """The ``codex exec`` command line of one question (its words come on standard input: ``-``)."""
    flags = [part for flag in FLAGS for part in ("-c", flag)]
    return [*ctx.backend_cmd, "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "--color", "never",
            "--json", *(["-m", model] if model else []), *(["-c", f'model_reasoning_effort="{effort}"'] if effort else []),
            *flags, "-c", "developer_instructions=" + json.dumps(system), "-"]


def answer_of(rows) -> str:
    """The last agent message of a completed turn; AskFailed otherwise."""
    failed = next((row for row in rows if row.get("type") in ("turn.failed", "error")), None)
    if failed is not None:
        error = failed.get("error") if isinstance(failed.get("error"), dict) else {}
        raise AskFailed("model_error", str(error.get("code") or error.get("type") or failed.get("type"))[:60])
    texts = [(row.get("item") or {}).get("text") for row in rows if row.get("type") == "item.completed"
             and (row.get("item") or {}).get("type") in ("agent_message", "assistant_message")]
    text = next((text for text in reversed(texts) if isinstance(text, str) and text.strip()), "")
    if not text:
        raise AskFailed("bad_output")
    return text


def ask_once(ctx, system: str, data: str, *, heavy: bool = False, limit: float, cwd=None, environ=None) -> str:
    """The answer's text to ``data`` under ``system``, within ``limit`` seconds; AskFailed with the reason otherwise. ``cwd``:
    the empty directory it runs in (made; default <state>/codex-judge)."""
    folder = Path(cwd) if cwd is not None else Path(ctx.state_dir) / "codex-judge"
    ensure_private_dir(folder)
    env = child_process_env(folder)
    model, effort = choose(env, heavy=heavy, environ=environ)
    with JudgeHome(ctx.state_dir, env) as home_env:
        rows = run_lines(argv(ctx, system, model, effort), data, env=home_env, cwd=str(folder), limit=limit,
                         done=lambda row: row.get("type") in ("turn.completed", "turn.failed", "error"))
    return answer_of(rows)
