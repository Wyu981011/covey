"""A handoff summary from a Codex thread the topic is leaving (🔁 换配置, app/switch_handoff.py), as
backends/claude/handoff.py writes Claude Code's.

The first run after a switch asks the old model, on an ephemeral fork of its thread (``thread/fork`` with
``ephemeral``: nothing of the fork is written, the thread it came from is left as it was), for a short summary the new
model starts from. The fork runs on an app server of its own in a home of its own (``HandoffHome``: backends/codex/
consult.py's ConsultHome, the login and the model's provider and nothing else of the owner's: no MCP server, hook, rule,
plugin, skill, memory or history), in the read-only sandbox, with the tools a summary has no use for off (``FLAGS``: the
shell, subagents, web search, apps, the question …), no Bridge tool and no workspace reader; a request the app server
sends (an approval, a question) is refused. Its prompt cache is not the thread's (the tools differ), so the old thread
is read once more in full. It never raises: ``summarize`` gives ``(text, outcome)``, ``text`` empty unless it succeeded;
past ``seconds``, or when the task is stopped, the app server is closed and its process group stopped. A gateway that is
down does not hold the new turn that long: the app server's answers to initialize, thread/fork and turn/start each come
within HANDSHAKE_SECONDS, and the old model's first sign of output (``first_sign``: a reasoning or answer item started, a
tool call, the turn's end) within FIRST_SECONDS of turn/start; past either the summary is given up at once.
"""
from __future__ import annotations

import queue
import subprocess
import time

from covey.backends.codex import consult
from covey.backends.codex.rpc import AppServer, RpcError
from covey.backends.codex.turn import output_item_started, tool_call_started
from covey.core.harness import UUID_RE, JobCancelled
from covey.core.result import is_identifier

SUMMARY_SECONDS = 180  # The new turn waits at most this long for the summary, then starts without it.
HANDSHAKE_SECONDS = 30  # Each of initialize, thread/fork and turn/start: the app server answers them itself.
FIRST_SECONDS = 30  # From turn/start to the model's first sign (``first_sign``): none by then, its gateway is down.
# On top of a consult's (apps, plugins, memories, hooks, goals, image generation, web search and the question off): both
# shells (shell_tool and unified_exec, its exec_command and write_stdin), subagents and the other tools a summary has no
# use for. Every key is one `codex features list` of codex-cli 0.171.0 shows (it ignores a key it does not know).
FLAGS = (*consult.FLAGS, "features.shell_tool=false", "features.unified_exec=false", "features.multi_agent=false",
         "features.browser_use=false", "features.computer_use=false", "features.in_app_browser=false",
         "features.sleep_tool=false", "features.tool_suggest=false", "features.skill_search=false",
         "features.shell_snapshot=false", "features.view_image=false")
DENIED = "Bridge 交接摘要只要文字回答，不能调用工具。"


class HandoffHome(consult.ConsultHome):
    """A consult's home for one summary: <state>/tmp/codex-handoff-*, removed with it."""

    PREFIX = "codex-handoff-"


def fork_params(ctx, session_id):
    """thread/fork's parameters: ``session_id`` forked and never written, in the read-only sandbox, asking nobody, with
    the old binding's model, budget and workdir (and a gateway model's provider, backends/codex/gateway.py bind)."""
    config = {**ctx.options.get("thread_config", {}), **({"model_reasoning_effort": ctx.effort} if ctx.effort else {})}
    params = {"threadId": session_id, "ephemeral": True, "excludeTurns": True, "cwd": str(ctx.workdir),
              "approvalPolicy": "never", "sandbox": "read-only", "config": config,
              **({"model": ctx.model} if ctx.model else {})}
    if ctx.options.get("model_provider"):
        params["modelProvider"] = ctx.options["model_provider"]
    return params


def final_text(items) -> str:
    """The answer of the summary's turn from its agent messages ((phase, text) in order): the final-answer ones where
    Codex marks them, else the unmarked ones; commentary never."""
    finals = [text for phase, text in items if phase == "final_answer"]
    return "\n\n".join(finals or [text for phase, text in items if phase is None]).strip()


def agent_messages(items) -> dict:
    """{id: (phase, text)} of the agent messages among a turn's ``items``."""
    return {item["id"]: (item.get("phase"), item["text"]) for item in items
            if isinstance(item, dict) and item.get("type") == "agentMessage" and is_identifier(item.get("id"))
            and isinstance(item.get("text"), str)}


def first_sign(method, p) -> bool:
    """Whether the notification ``method`` (its params ``p``, of the fork's turn) shows the model answering: an output
    item started or done (backends/codex/turn.py output_item_started, tool_call_started), an agent message's text, the
    turn's end."""
    done = method == "item/completed" and isinstance(p.get("item"), dict) and p["item"].get("type") in (
        "reasoning", "agentMessage")
    return (done or output_item_started(method, p) or tool_call_started(method, p) or method == "turn/completed"
            or method in ("item/agentMessage/delta", "item/reasoning/textDelta", "item/reasoning/summaryTextDelta"))


def summarize(ctx, session_id, prompt, env, *, cancel=None, seconds=SUMMARY_SECONDS, first_seconds=None,
              handshake_seconds=None):
    """(summary text, outcome words) from an ephemeral fork of ``session_id`` run in ``ctx`` (the old binding's workdir,
    model and budget) with ``env`` (a HandoffHome's). ``first_seconds``, ``handshake_seconds``: FIRST_SECONDS and
    HANDSHAKE_SECONDS unless given."""
    first_seconds = FIRST_SECONDS if first_seconds is None else first_seconds
    handshake = HANDSHAKE_SECONDS if handshake_seconds is None else handshake_seconds
    if not isinstance(session_id, str) or not UUID_RE.fullmatch(session_id):
        return "", "原会话标识不对"
    deadline = time.monotonic() + seconds
    rpc = None

    def left():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("codex app-server", seconds)
        return remaining

    def short():
        return min(left(), handshake)

    try:
        rpc = AppServer([*ctx.backend_cmd, "app-server", "--stdio", *[part for flag in FLAGS for part in ("-c", flag)]],
                        ctx.workdir, env)
        rpc.request("initialize", {"clientInfo": {"name": "feishu_bridge", "version": "1.0"},
                                   "capabilities": {"experimentalApi": True}}, timeout=short())
        rpc.send({"method": "initialized"})
        reply = rpc.request("thread/fork", fork_params(ctx, session_id), timeout=short())
        fork = (reply.get("thread") or {}).get("id") if isinstance(reply, dict) else None
        if not is_identifier(fork) or fork == session_id:
            return "", "Codex 没有给出分叉"
        rpc.thread_id = fork
        reply = rpc.request("turn/start", {
            "threadId": fork, "input": [{"type": "text", "text": prompt}], "sandboxPolicy": {"type": "readOnly"},
            **({"model": ctx.model} if ctx.model else {}), **({"effort": ctx.effort} if ctx.effort else {})},
            timeout=short())
        rpc.turn_id = (reply.get("turn") or {}).get("id") if isinstance(reply, dict) else None
        if not is_identifier(rpc.turn_id):
            return "", "Codex 没有开始这一轮"
        return read_summary(rpc, cancel, left, first_by=time.monotonic() + first_seconds)
    except JobCancelled:
        return "", "已停止"
    except Silent:
        return "", f"原模型 {first_seconds} 秒没有回应（网关可能断开）"
    except subprocess.TimeoutExpired:
        return "", f"超过 {seconds} 秒"
    except RpcError as exc:
        if "timed out" in str(exc) and time.monotonic() < deadline:  # An answer of its own past HANDSHAKE_SECONDS.
            return "", f"Codex {handshake} 秒没有回应"
        return "", f"出错（{type(exc).__name__}）"
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return "", f"出错（{type(exc).__name__}）"
    finally:
        if rpc is not None:
            try:
                rpc.close()
            except Exception:  # noqa: BLE001 - its process group was signalled; nothing else to do
                pass


class Silent(Exception):
    """The fork's model gave no sign of output by ``read_summary``'s ``first_by``."""


def read_summary(rpc, cancel, left, first_by=None):
    """Read the fork's turn to its end: (text, outcome). Raises JobCancelled on a stop (the turn interrupted first),
    TimeoutExpired past the deadline (``left``) and Silent when the model shows no sign of output (``first_sign``) by
    ``first_by`` (time.monotonic(); None: no such limit)."""
    items, heard = {}, first_by is None
    while True:
        if not heard and time.monotonic() >= first_by:
            raise Silent()
        if cancel is not None and cancel.is_set():
            try:
                rpc.request("turn/interrupt", {"threadId": rpc.thread_id, "turnId": rpc.turn_id}, timeout=5)
            except RpcError:
                pass
            raise JobCancelled("已停止")
        try:
            row = rpc.events.get(timeout=min(0.25, left()))
        except queue.Empty:
            continue
        method, p = row.get("method", ""), row.get("params", {})
        if method == "bridge/closed":
            return "", "Codex 进程提前结束"
        if "id" in row:  # An approval or a question: the summary asks nobody.
            rpc.send({"id": row["id"], "error": {"code": -32601, "message": DENIED}})
            continue
        if not isinstance(p, dict) or p.get("threadId") != rpc.thread_id:
            continue
        heard = heard or first_sign(method, p)
        if method == "item/completed" and p.get("turnId") == rpc.turn_id:
            items.update(agent_messages([p.get("item")]))
            continue
        if method != "turn/completed":
            continue
        turn = p.get("turn")
        if not isinstance(turn, dict) or turn.get("id") != rpc.turn_id:
            continue
        if turn.get("status") != "completed" or turn.get("error") is not None:
            return "", "Codex 报告失败"
        if turn.get("itemsView") == "full" and isinstance(turn.get("items"), list):
            items = agent_messages(turn["items"])
        text = final_text(items.values())
        return (text, "写好了") if text else ("", "回答为空")
