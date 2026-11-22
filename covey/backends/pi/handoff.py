"""A handoff summary from a Pi session the topic is leaving (🔁 换配置, app/switch_handoff.py), as
backends/claude/handoff.py writes Claude Code's.

One ``pi --mode json -p`` on a fork of the session's file (``--fork <file>``) into a session directory of its own,
<state>/tmp/pi-handoff-* (removed afterwards: the session it came from is read, never written), with no tool at all
(``--no-tools``; pi 1.6.0 takes a history of tool calls without them, checked), no MCP server, extension, skill, prompt
template or context file, in a home of its own (backends/pi/home.py TurnHome: the old binding's model and budget, pi's
own retries; a gateway model through a relay of its own, as a turn). Its prompt cache is not the session's (the tools
differ), so the session is read once more in full. It never raises: ``summarize`` gives ``(text, outcome)``, ``text``
empty unless it succeeded; past ``seconds``, or when the task is stopped, pi's process group is killed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from covey.backends.pi import home
from covey.backends.pi.events import message_texts
from covey.core import gateways
from covey.core.harness import JobCancelled
from covey.core.process import stream_subprocess_lines
from covey.core.process_env import child_process_env
from covey.core.state import ensure_private_dir

SUMMARY_SECONDS = 180  # The new turn waits at most this long for the summary, then starts without it.
# Nothing but the conversation and the request: no tool (built-in, extension or MCP), no skill, template or AGENTS.md.
QUIET = ("--no-tools", "--no-mcp", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files")


def summary_argv(ctx, source, folder, prompt):
    """The ``pi -p`` command line of the summary: ``source`` (the session's file) forked into ``folder``."""
    gateway = gateways.for_model("pi", ctx.model)
    return [*ctx.backend_cmd, "--mode", "json", "--session-dir", str(folder), "--fork", str(source), *QUIET,
            "--provider", gateway.name if gateway else home.CODEX_PROVIDER,
            "--model", ctx.model[len(gateway.prefix):] if gateway else ctx.model,
            "--thinking", home.thinking(ctx.effort), "-p", "--", prompt]


class SummaryRows:
    """What ``pi --mode json`` printed: its last assistant message is the answer (pi's retries print one per try)."""

    def __init__(self):
        self.last = None

    def on_line(self, line):
        try:
            row = json.loads(line)
        except ValueError:
            return
        message = row.get("message") if isinstance(row, dict) else None
        if row.get("type") == "message_end" and isinstance(message, dict) and message.get("role") == "assistant":
            self.last = message

    def outcome(self, rc):
        """(text, outcome words) once pi has exited with ``rc``."""
        if self.last is None:
            return "", "Pi 没有回答"
        if self.last.get("stopReason") == "error":
            return "", "Pi 报告失败"
        if self.last.get("stopReason") != "stop" or rc != 0:
            return "", "Pi 没有正常结束"
        text = message_texts(self.last).strip()
        return (text, "写好了") if text else ("", "回答为空")


def summarize(ctx, source, prompt, account, relay_url, token, *, cancel=None, seconds=SUMMARY_SECONDS):
    """(summary text, outcome words) from a fork of ``source`` run in ``ctx`` (the old binding's workdir, model and
    budget): ``token`` the Codex login's access token for the account's models, ``relay_url`` a gateway model's relay."""
    tmp = Path(ctx.state_dir) / "tmp"
    ensure_private_dir(tmp)
    folder = Path(tempfile.mkdtemp(prefix="pi-handoff-", dir=str(tmp)))  # mkdtemp is 0700.
    try:
        rows = SummaryRows()
        with home.TurnHome(ctx.state_dir, ctx.model, ctx.effort, account, relay_url) as turn_home:
            env = home.environment(child_process_env(ctx.workdir), ctx.model, turn_home.path, token)
            rc, _ = stream_subprocess_lines(summary_argv(ctx, source, folder, prompt), stdin_text=None, timeout=seconds,
                                            on_line=rows.on_line, env=env, cwd=str(ctx.workdir), cancel_event=cancel)
        return rows.outcome(rc)
    except JobCancelled:
        return "", "已停止"
    except subprocess.TimeoutExpired:
        return "", f"超过 {seconds} 秒"
    except (OSError, ValueError) as exc:
        return "", f"出错（{type(exc).__name__}）"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
