#!/usr/bin/env python3
"""The concepts the core has, against the list tests/golden/concepts.json keeps, so a new one is never added unseen.

    python3 -B scripts/concepts.py            # print what differs from the list (nothing when it matches)
    python3 -B scripts/concepts.py --check    # the same, exit 1 when something differs
    python3 -B scripts/concepts.py --write    # take the removed ones off the list; add the new ones after the freeze

A concept is what a person who uses or develops Covey has to learn: a setting (an environment variable or a command-line
option of docs/configuration.md 环境变量与选项一览), a card button kind (app/card_actions.py ACTIONS), a Bridge tool the
butler or a lead calls (core/butler_tool_specs.py), a Harness (core/roster.py CORE_HARNESSES), a provider
(core/providers.py CORE_PROVIDERS), a word of docs/glossary.md (名词, 状态词). Only the core's: an extension's are its own.

The list has three parts. ``freeze``, when there is one, is a 收敛期 (AGENTS.md 概念清单: no new concept until ``until``;
the one of 2026-11-25 to 12-09 was called off on 11-27), ``concepts`` what the core had, ``approved`` what was added in a
收敛期, each with who allowed it (``by``) and why (``why``). In a 收敛期 ``--write`` refuses a new one that ``approved`` does
not name; outside one, ``--write`` takes every new one onto ``concepts`` and folds ``approved`` into it.
tests/test_structure.py ConceptFreezeTest runs ``--check``'s comparison.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIST = REPO / "tests" / "golden" / "concepts.json"
INVENTORY_DOC = REPO / "docs" / "configuration.md"
INVENTORY_HEADING = "## 环境变量与选项一览"
GLOSSARY = REPO / "docs" / "glossary.md"
GLOSSARY_SECTIONS = ("## 名词", "## 状态词")  # The second cell of each row is the word.
KINDS = {  # Each kind of concept, with its words in what the check says.
    "settings": "环境变量或命令行参数（docs/configuration.md 一览）",
    "card_kinds": "卡片按钮 kind（app/card_actions.py ACTIONS）",
    "tools": "管家或负责人的 Bridge 工具（core/butler_tool_specs.py）",
    "harnesses": "Harness（core/roster.py CORE_HARNESSES）",
    "providers": "模型来源（core/providers.py CORE_PROVIDERS）",
    "terms": "名词表里的词（docs/glossary.md 名词、状态词）",
}
TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))  # The 收敛期's dates are Asia/Shanghai's.


def table_cells(path: Path, heading: str) -> list[list[str]]:
    """The cells of each row of the table under ``heading`` (until the next heading), the header and rule rows left out."""
    lines = path.read_text().splitlines()
    rows = []
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("#"):
            break
        if line.startswith("|") and not re.match(r"\|\s*-", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows[1:]  # The first is the header.


def settings() -> set:
    """What docs/configuration.md 环境变量与选项一览 lists in the first cell's backticks (tests/test_structure.py
    InventoryTest keeps it equal to what the code reads)."""
    names = set()
    for cells in table_cells(INVENTORY_DOC, INVENTORY_HEADING):
        names.update(re.findall(r"`([^`]+)`", cells[0]))
    return names


def terms() -> set:
    words = set()
    for heading in GLOSSARY_SECTIONS:
        for cells in table_cells(GLOSSARY, heading):
            words.add(cells[1])
    return words


def current() -> dict:
    """{kind: sorted names} of the core as it is now."""
    sys.path.insert(0, str(REPO))
    from covey.app.card_actions import ACTIONS
    from covey.core import butler_tool_specs as specs
    from covey.core import extensions
    from covey.core.providers import CORE_PROVIDERS
    from covey.core.roster import CORE_HARNESSES

    tools = {tool["name"] for name, value in vars(specs).items() if name.endswith("TOOLS") and isinstance(value, tuple)
             for tool in value if isinstance(tool, dict) and "name" in tool}
    tools.add(specs.TIDY_TOOL["name"])
    found = {
        "settings": settings(),
        "card_kinds": set(ACTIONS) - set(extensions.card_kinds()),
        "tools": tools,
        "harnesses": set(CORE_HARNESSES),
        "providers": {provider.key for provider in CORE_PROVIDERS},
        "terms": terms(),
    }
    return {kind: sorted(found[kind]) for kind in KINDS}


def load() -> dict:
    return json.loads(LIST.read_text())


def approved_names(listed: dict) -> dict:
    """{kind: names} of ``approved``."""
    names = {kind: set() for kind in KINDS}
    for entry in listed.get("approved", []):
        names.setdefault(entry["kind"], set()).add(entry["name"])
    return names


def frozen(listed: dict, today: datetime.date | None = None) -> bool:
    """Whether ``today`` (default: today in Asia/Shanghai) is in the 收敛期."""
    today = today or datetime.datetime.now(TIMEZONE).date()
    freeze = listed.get("freeze") or {}
    return bool(freeze) and freeze["since"] <= today.isoformat() <= freeze["until"]


def compare(listed: dict, now: dict) -> dict:
    """{"added": {kind: names}, "removed": {kind: names}, "stale": {kind: names}}: what the core has and the list does not
    (``concepts`` nor ``approved``), what ``concepts`` has and the core does not, what ``approved`` names and the core does
    not have. Empty kinds left out."""
    approved = approved_names(listed)
    result = {"added": {}, "removed": {}, "stale": {}}
    for kind in KINDS:
        have, base, allowed = set(now.get(kind, ())), set(listed["concepts"].get(kind, ())), approved.get(kind, set())
        for key, names in (("added", have - base - allowed), ("removed", base - have), ("stale", allowed - have)):
            if names:
                result[key][kind] = sorted(names)
    return result


def report(listed: dict, diff: dict, in_freeze: bool) -> str:
    """What differs, in words, with what to do; "" when nothing does."""
    lines = []
    until = (listed.get("freeze") or {}).get("until", "")
    for kind, names in diff["added"].items():
        lines.append(f"新的{KINDS[kind]}：{'、'.join(names)}")
    if diff["added"]:
        if in_freeze:
            lines.append(f"收敛期（到 {until}，AGENTS.md「收敛期」）不加新概念：先问主人；主人同意了，"
                         f"在 {LIST.relative_to(REPO)} 的 approved 里每个加一项 {{kind, name, by: 谁在哪批准（T 号或工作包）, why}}。")
        else:
            lines.append("收敛期已过：python3 -B scripts/concepts.py --write 把它们加进清单，和改动一起提交。")
    for kind, names in diff["removed"].items():
        lines.append(f"已经没有的{KINDS[kind]}：{'、'.join(names)}（python3 -B scripts/concepts.py --write 从清单去掉）")
    for kind, names in diff["stale"].items():
        lines.append(f"approved 里登记了、代码里没有的{KINDS[kind]}：{'、'.join(names)}（删掉那几项）")
    return "\n".join(lines)


def written(listed: dict, now: dict, in_freeze: bool) -> tuple[dict, list]:
    """(the list ``--write`` saves, the new names it refused). In the 收敛期 a new name ``approved`` lacks is refused
    and nothing is added to ``concepts``; after it ``concepts`` takes every name the core has and ``approved`` empties."""
    diff = compare(listed, now)
    refused = [f"{kind}:{name}" for kind, names in diff["added"].items() for name in names] if in_freeze else []
    out = dict(listed)
    if in_freeze:
        out["concepts"] = {kind: sorted(set(listed["concepts"].get(kind, ())) & set(now[kind])) for kind in KINDS}
        out["approved"] = [entry for entry in listed.get("approved", []) if entry["name"] in now.get(entry["kind"], ())]
    else:
        out["concepts"] = {kind: list(now[kind]) for kind in KINDS}
        out["approved"] = []
    return out, refused


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="exit 1 when the core differs from the list")
    group.add_argument("--write", action="store_true", help="bring the list up to the core (see the docstring)")
    args = parser.parse_args(argv)
    listed, now = load(), current()
    in_freeze = frozen(listed)
    if args.write:
        out, refused = written(listed, now, in_freeze)
        LIST.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
        if refused:
            print(report(listed, {"added": compare(listed, now)["added"], "removed": {}, "stale": {}}, True))
            return 1
        return 0
    text = report(listed, compare(listed, now), in_freeze)
    if text:
        print(text)
    return 1 if text and args.check else 0


if __name__ == "__main__":
    sys.exit(main())
