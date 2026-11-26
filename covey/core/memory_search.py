"""按需查记忆 (COVEY_MEMORY_LEARN=1, docs/butler.md 记忆自己长): what a turn's memory block could not carry, looked up by its
words from the turn itself: ``bin/covey_memory.py search --state <dir> --topic <id> [--owner] [--redacted] "<一句话>"``
(app/memory_turn.py search_command writes the line into the block). Read only: nothing here writes a file.

What it looks through (``corpus``), as the turn may read it: the owner's principles (通用 with ``--owner``, the workspace's
always), the knowledge entries that hold (通用 with ``--owner``), the open and saved candidates (app/memory_candidates.py's
record, read here as plain JSON; 全局 ones with ``--owner``), the topic's own memory, and of the topic's project every line (its
history too: done or superseded), what a full memory let go (memory-archive.json) and each answered question kept whole
(answers/<token>.json, a line a question: 问…→答…). A line from a topic with redaction on only with ``--redacted``; a 代答
topic reads nothing. The workspace is the topic's own unless ``--workspace`` names one.

How it ranks (``score``): the query's words (a run of Latin letters or digits, and every two characters of a run of Chinese)
found in a line, each weighed by how few lines have it (a word every question has, 要不要, counts for little), as a share of the
query's; at a tie what still holds before the history, the newest first; at most ``--limit``. An answered question whose line
the project's memory still has is listed once. Standard library and core only."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

from covey.core import knowledge, memory, principles, project_memory, projects, topic_memory
from covey.core.state import read_object
from covey.core.topics import load_topic

LIMIT = 8
MIN_SCORE = 0.15  # Below it a line shares only a word or two of little weight with the query.
TEXT = 300  # Characters of a line printed.
WORD = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff\uf900-\ufaff]+")
CANDIDATES = "memory-candidates.json"
HELD, HISTORY = "有效", "历史"


def tokens(text) -> set:
    """The words ``score`` matches: each run of Latin letters or digits (two or more), every two characters of a Chinese
    run (a one-character run as it is)."""
    found = set()
    for run in WORD.findall(str(text or "").lower()):
        if run.isascii():
            if len(run) >= 2:
                found.add(run)
        else:
            found |= {run[i:i + 2] for i in range(len(run) - 1)} or {run}
    return found


def weights(rows) -> dict:
    """word -> its weight among ``rows`` (``_line``s): log(1 + lines / (1 + lines with it))."""
    seen = {}
    for row in rows:
        for word in row["words"]:
            seen[word] = seen.get(word, 0) + 1
    return {word: math.log(1 + len(rows) / (1 + count)) for word, count in seen.items()}


def score(wanted, words, weight) -> float:
    """The weighed share of the query's words ``wanted`` that a line's ``words`` hold (an unknown word weighs most)."""
    top = math.log(1 + 1 + len(weight))
    total = sum(weight.get(word, top) for word in wanted)
    return sum(weight.get(word, top) for word in wanted & words) / total if total else 0.0


def _line(where, kind, by, text, at, state=HELD, extra="") -> dict:
    return {"where": where, "kind": kind, "by": by, "state": state, "text": " ".join(str(text or "").split()),
            "at": float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else 0.0, "extra": extra}


def _topic(state_dir, topic_id) -> dict:
    try:
        return load_topic(Path(state_dir), topic_id) if topic_id else {}
    except (OSError, ValueError):
        return {}


def _project_lines(state_dir, project_id, redacted) -> list:
    found = []
    for row in project_memory.stored(state_dir, project_id):
        if row["deleted"] or row["kind"] == "style" or (row.get("redacted") and not redacted):
            continue
        facts = memory.describe(row)
        state = HISTORY if facts["layer"] == memory.HISTORY else HELD
        kind = memory.PART_WORDS.get(memory.describe({**row, "valid": "active"})["part"], "")  # What it was, put away or not.
        found.append(_line("专项", kind, memory.OWNER_WORDS[memory.OWNER if facts["asserted_by"] == "owner" else memory.LEAD],
                           row["text"], row["at"], state, "做完了" if facts["valid"] == "done" else
                           "被替代了" if facts["valid"] == "superseded" else ""))
    for row in project_memory.archived(state_dir, project_id):
        if not (row.get("redacted") and not redacted):
            found.append(_line("专项", "放不下时移出的", memory.OWNER_WORDS[memory.by_source(row["source"])], row["text"],
                               row["at"], HISTORY))
    folder = project_memory.memory_path(state_dir, project_id).parent / project_memory.ANSWERS_DIR
    noted = " ".join(row["text"] for row in found)
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        record = read_object(path)
        answers = record.get("answers") if isinstance(record.get("answers"), dict) else {}
        for question in record.get("questions") or ():
            if not isinstance(question, dict) or not question.get("question"):
                continue
            given = (answers.get(str(question.get("id"))) or {}).get("answers") if isinstance(answers, dict) else None
            said = "；".join(str(a) for a in given or () if a)
            if said and " ".join(str(question["question"]).split())[:40] not in noted:  # Its line is still there.
                found.append(_line("专项", "答过的问题", memory.OWNER_WORDS[memory.OWNER], f"问：{question['question']} → 答：{said}",
                                   record.get("noted_at"), HELD))
    return found


def corpus(state_dir, topic_id="", *, owner=False, redacted=False, workspace="") -> list:
    """Every line the turn may look up (the module's docstring), as ``_line``s."""
    state = Path(state_dir)
    topic = _topic(state, topic_id)
    if topic.get("proxy"):
        return []
    workspace = workspace or str(topic.get("workspace_name") or "")
    mine, space = principles.for_turn(state, workspace)
    found = [_line("全局" if group is mine else "工作区", "原则", memory.OWNER_WORDS[memory.OWNER], row["text"], row.get("at"))
             for group in ((mine if owner else []), space) for row in group]
    if (state / "knowledge").is_dir():
        general, local = knowledge.for_turn(state, workspace)
        found += [_line("全局" if group is general else "工作区", "知识条目", memory.OWNER_WORDS[memory.OWNER],
                        f"{knowledge.KINDS.get(row.get('kind'), '')}：{row['text']}", row.get("at"))
                  for group in ((general if owner else []), local) for row in group]
    for row in read_object(state / CANDIDATES).get("rows") or ():
        if not isinstance(row, dict) or row.get("state") not in ("open", "saved") or not isinstance(row.get("text"), str):
            continue
        where = str(row.get("workspace") or "")
        if (where and where != workspace) or (not where and not owner):
            continue
        found.append(_line("工作区" if where else "全局", "候选", memory.OWNER_WORDS[memory.LEAD], row["text"], row.get("at"),
                           HELD if row.get("state") == "open" else HISTORY, "已记成原则" if row.get("state") == "saved" else ""))
    found += [_line("话题", "话题的记忆", memory.OWNER_WORDS[memory.by_source(row.get("source"))], row["text"], row.get("at"))
              for row in topic_memory.live(state, topic_id) if redacted or not row.get("redacted")]
    belongs = projects.topic_project(state, topic_id) if topic_id else None
    if belongs is not None:
        found += _project_lines(state, belongs.id, redacted)
    return [row for row in found if row["text"]]


def search(state_dir, query, topic_id="", *, owner=False, redacted=False, workspace="", limit=LIMIT) -> list:
    """The lines of ``corpus`` that ``query`` finds, the best first (the module's docstring)."""
    wanted = tokens(query)
    rows = corpus(state_dir, topic_id, owner=owner, redacted=redacted, workspace=workspace)
    for row in rows:
        row["words"] = tokens(f"{row['kind']} {row['text']}")
    weight = weights(rows)
    scored = [(score(wanted, row.pop("words"), weight), row) for row in rows]
    scored = [pair for pair in scored if pair[0] >= MIN_SCORE]
    scored.sort(key=lambda pair: (-pair[0], pair[1]["state"] != HELD, -pair[1]["at"]))
    return [row for _, row in scored[:max(1, int(limit))]]


def render(rows, query) -> str:
    if not rows:
        return f"没有查到和“{query}”有关的记忆。"
    lines = []
    for row in rows:
        day = time.strftime("%m-%d", time.localtime(row["at"])) if row["at"] else ""
        tags = " · ".join(part for part in (row["where"], row["kind"], row["by"], row["state"] if row["state"] != HELD else "",
                                            row["extra"], day) if part)
        text = row["text"] if len(row["text"]) <= TEXT else row["text"][:TEXT - 1] + "…"
        lines.append(f"- [{tags}] {text}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="covey_memory.py", description="按需查记忆：记忆块放不下的、整理时收起的、答过的问题")
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("search", help="按一句话查")
    find.add_argument("query", help="要查的一句话")
    find.add_argument("--state", required=True, help="这个部署的状态目录")
    find.add_argument("--topic", default="", help="这一轮的话题 id")
    find.add_argument("--workspace", default="", help="按这个工作区查（默认：话题自己的）")
    find.add_argument("--owner", action="store_true", help="主人自己的一轮：带上全局的")
    find.add_argument("--redacted", action="store_true", help="开了脱敏的话题：带上来自脱敏话题的")
    find.add_argument("--limit", type=int, default=LIMIT, help=f"最多列几条（默认 {LIMIT}）")
    find.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)
    rows = search(args.state, args.query, args.topic, owner=args.owner, redacted=args.redacted, workspace=args.workspace,
                  limit=args.limit)
    print(json.dumps(rows, ensure_ascii=False) if args.json else render(rows, args.query))
    return 0


if __name__ == "__main__":
    sys.exit(main())
