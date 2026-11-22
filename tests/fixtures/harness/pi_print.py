"""A scripted ``pi --mode json -p`` (backends/pi/handoff.py): records its argv, cwd and environment in
``FAKE_PI_RECORD``, forks the ``--fork`` file into ``--session-dir`` as pi 1.6.0 does and prints the rows of
``FAKE_PI_SCENARIO``: ok (a summary), error (pi's retries spent), empty, slow."""
import json, os, sys, time
args = sys.argv[1:]
def flag(name):
    return args[args.index(name) + 1] if name in args else None
source, folder = flag("--fork"), flag("--session-dir")
fork = os.path.join(folder, "2026-11-23T00-00-00-000Z_01a1a21e-5b23-7308-9dd0-f72c93ca797c.jsonl")
with open(fork, "w") as handle:
    handle.write(open(source).read())
json.dump({"argv": args, "cwd": os.getcwd(), "fork": fork,
           "env": {k: os.environ.get(k) for k in ("PI_CODEX_ACCESS_TOKEN", "ACME_API_KEY", "PI_OFFLINE", "PI_TELEMETRY")}},
          open(os.environ["FAKE_PI_RECORD"], "w"))
scenario = os.environ.get("FAKE_PI_SCENARIO", "ok")
def emit(row):
    sys.stdout.write(json.dumps(row) + "\n")
    sys.stdout.flush()
SIGNATURE = json.dumps({"v": 1, "id": "msg_1", "phase": "final_answer"}, separators=(",", ":"))
def assistant(text, reason, **extra):
    content = [{"type": "text", "text": text, "textSignature": SIGNATURE}] if text else []
    return {"role": "assistant", "content": content, "api": "openai-codex-responses", "provider": "openai-codex",
            "stopReason": reason, **extra}
emit({"type": "session", "version": 3, "id": "01a1a21e-5b23-7308-9dd0-f72c93ca797c", "parentSession": source})
emit({"type": "agent_start"})
emit({"type": "turn_start"})
if scenario == "slow":
    time.sleep(30)
if scenario == "error":
    for _ in range(2):  # pi prints one failed message per try.
        message = assistant("", "error", errorMessage="503 Service Unavailable")
        emit({"type": "message_start", "message": message})
        emit({"type": "message_end", "message": message})
    emit({"type": "agent_end", "messages": [message]})
    sys.exit(1)
message = assistant("" if scenario == "empty" else "### 目标\n交接测试\n\n### 当前状态\n做完了", "stop")
emit({"type": "message_start", "message": assistant("", "stop")})
emit({"type": "message_end", "message": message})
emit({"type": "turn_end", "message": message})
emit({"type": "agent_end", "messages": [message]})
emit({"type": "agent_settled"})
