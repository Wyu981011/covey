"""One question to Antigravity and nothing else (AntigravityBackend.ask_once, core/harness.py HarnessCapabilities.ask_once):
the small model's questions (app/track_judge.py) where neither Claude Code nor Codex is enabled.

``agy --input-format stream-json --output-format stream-json`` in a HOME of its own (core/agy_home.py ScratchHome: the
login and the CLI's own files linked; the conversation, its log and its summaries stay there and go with it; no MCP server,
hook, rule, plugin or setting of the owner's), without --dangerously-skip-permissions (a step that asks is skipped) and with a
lead's deny rules on top (backends/agy/bridge.py READ_ONLY_SETTINGS: no file written, no command, no URL read), slash
commands off, in an empty directory of its own. The question (its system prompt, then its JSON) is one user line on
standard input, never in argv; the answer is the result's response, and the process group is killed then or at the limit
(core/one_shot.py). Without a sign-in (core/agy_home.py signed_in) nothing starts: agy would wait a minute for a browser.

The model (``choose``): COVEY_JUDGE_AGY_MODEL when set (an id ``agy models`` lists, its budget in it: gemini-3.8-flash-low);
else for a light question the first model of the saved catalog (backends/agy/bridge.py model_catalog, the launch card's)
whose id or name says it is a light one (``LIGHT``) at its lowest budget, for a heavy one (整理专项) agy's own default.
Seen on agy 1.5.14: 4 s to start, a few more for the model.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from covey.core import env as cenv
from covey.core.agy_home import ScratchHome, signed_in
from covey.core.harness import AskFailed
from covey.core.one_shot import run_lines
from covey.core.process_env import child_process_env
from covey.core.state import ensure_private_dir

MODEL_ENV = "COVEY_JUDGE_AGY_MODEL"
# A light model, by a word of its id or name (never inside another word: "gemini" holds "mini").
LIGHT = re.compile(r"(?<![a-z0-9])(flash|lite|mini|nano|small|haiku|luna)(?![a-z])", re.I)


def choose(catalog, *, heavy: bool, environ=None) -> tuple:
    """(model, effort) of a question from ``catalog`` ({model: {display_name, supported_reasoning_levels}}): '' for agy's
    own (see the module docstring)."""
    wanted = str(cenv.get(MODEL_ENV, "", environ) or "").strip()
    if wanted:
        return wanted, ""
    if heavy:
        return "", ""
    for model, row in (catalog or {}).items():
        if LIGHT.search(model) or LIGHT.search(str(row.get("display_name") or "")):
            levels = [level.get("effort") for level in row.get("supported_reasoning_levels") or () if isinstance(level, dict)]
            return model, (levels[0] if levels else "")
    return "", ""


def argv(ctx, model: str, effort: str, settings) -> list:
    """The ``agy`` command line of one question (its words come on standard input)."""
    return [*ctx.backend_cmd, "--output-format", "stream-json", "--input-format", "stream-json",
            "--disable-slash-commands", *(["--model", model] if model else []), *(["--effort", effort] if effort else []),
            "--settings", json.dumps(settings, separators=(",", ":"))]


def answer_of(rows) -> str:
    """The response of a successful result; AskFailed otherwise."""
    result = next((row.get("result") for row in rows if row.get("event") == "result"), None)
    if not isinstance(result, dict):
        raise AskFailed("bad_output")
    if result.get("status") != "SUCCESS":
        raise AskFailed("model_error", str(result.get("status") or "")[:40])
    text = result.get("response")
    if not isinstance(text, str) or not text.strip():
        raise AskFailed("bad_output")
    return text


def ask_once(backend, ctx, system: str, data: str, *, heavy: bool = False, limit: float, cwd=None, settings,
             environ=None) -> str:
    """The answer's text to ``data`` under ``system``, within ``limit`` seconds; AskFailed with the reason otherwise.
    ``settings``: the deny rules (backends/agy/bridge.py READ_ONLY_SETTINGS); ``cwd``: the empty directory it runs in
    (made; default <state>/agy-judge)."""
    folder = Path(cwd) if cwd is not None else Path(ctx.state_dir) / "agy-judge"
    ensure_private_dir(folder)
    env = child_process_env(folder)
    if not signed_in(env):
        raise AskFailed("not_signed_in")
    model, effort = choose(backend.model_catalog(ctx), heavy=heavy, environ=environ)
    line = json.dumps({"event": "user", "message": {"content": f"{system}\n\n{data}"}}, ensure_ascii=False) + "\n"
    with ScratchHome(Path(ctx.state_dir) / "tmp", env) as home:
        rows = run_lines(argv(ctx, model, effort, settings), line, env={**env, "HOME": str(home)}, cwd=str(folder),
                         limit=limit, done=lambda row: row.get("event") == "result", skip=("oauth2",))
    return answer_of(rows)
