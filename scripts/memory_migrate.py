#!/usr/bin/env python3
"""The memory's migration by hand (docs/operations.md 记忆的存储与迁移): what ``memory_v2`` would do, doing it now, the counts
of every scope and kind, and writing back for an older release what it would not see.

    python3 -B scripts/memory_migrate.py --state "$STATE_DIR" --dry-run        # what the next run would take (reads only)
    python3 -B scripts/memory_migrate.py --state "$STATE_DIR" --apply          # run memory_v2 now, with its time
    python3 -B scripts/memory_migrate.py --state "$STATE_DIR" --stats          # entries by scope, kind and status
    python3 -B scripts/memory_migrate.py --state "$STATE_DIR" --seed-topics    # make memory/topics.json from the topic folders
    python3 -B scripts/memory_migrate.py --state "$STATE_DIR" --export-legacy  # before a rollback, the service stopped

``--apply`` and ``--export-legacy`` write the state directory: stop the service first (the Bridge runs the migration
itself at its start). ``--json`` prints one JSON object instead of lines.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from covey.core import memstore, migrate  # noqa: E402


def stats(state: Path) -> dict:
    """{scope: {kind: {status: n}}} of every entry (the indexed topics only), and the queue's and the codes' sizes."""
    found = {}
    for entry in memstore.entries(state, statuses=None):
        found.setdefault(entry.scope, Counter())[f"{entry.kind}/{entry.status}/{entry.said}"] += 1
    return {"entries": {scope: dict(sorted(counts.items())) for scope, counts in sorted(found.items())},
            "review_open": len(memstore.review_items(state)),
            "review_by_type": dict(Counter(item.get("type") for item in memstore.review_items(state))),
            "codes": len(memstore.codes(state)["codes"]), "topics_indexed": len(memstore.topics(state))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="memory_migrate.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True, help="the state directory")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="what the next memory_v2 run would take; reads only")
    group.add_argument("--apply", action="store_true", help="run memory_v2 now")
    group.add_argument("--stats", action="store_true", help="the entries by scope, kind and status")
    group.add_argument("--seed-topics", action="store_true", help="make memory/topics.json from the topic folders")
    group.add_argument("--export-legacy", action="store_true", help="write back for an older release what it would not see")
    parser.add_argument("--json", action="store_true", help="one JSON object")
    args = parser.parse_args(argv)
    state = args.state.resolve()
    if not state.is_dir():
        parser.error(f"no state directory {state}")
    started = time.monotonic()
    if args.dry_run:
        out = {"would_take": migrate.pending(state).get(migrate.MEMORY_V2, 0), "legacy_changed": memstore.legacy_changed(state),
               "projects": memstore.project_sources(state)}
    elif args.apply:
        written, failed = migrate.memory_v2(state)
        out = {"written": written, "failed": failed, **stats(state)}
    elif args.stats:
        out = stats(state)
    elif args.seed_topics:
        out = {"topics": memstore.seed_topics(state)}
    else:
        out = memstore.export_legacy(state)
    out["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for key, value in out.items():
            print(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return 1 if out.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
