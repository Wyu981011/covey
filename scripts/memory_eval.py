#!/usr/bin/env python3
"""查记忆的离线测评 (docs/butler.md 记忆): a set of queries, each with the entries it should find (or none), run against a state
directory's memory the way a turn looks it up (core/memory_search.py eval_search), with the figures the thresholds were set by.

    python3 -B scripts/memory_eval.py --state <状态目录> --set <查询.jsonl> [--tau 0.3] [--json]
    python3 -B scripts/memory_eval.py --seed tests/fixtures/memory_eval/seed.json --set tests/fixtures/memory_eval/set.jsonl

A query line: ``{"id", "query", "context": {"project"?, "topic"?, "owner"?}, "relevant": {<key>: 2 | 1}, "group"?}``; a key
is an entry's ref, short code or old id (memstore.find), or with ``--seed`` the ``id`` of an entry of the seed file; no
``relevant`` (or an empty one) is a query that should find nothing. ``--seed`` builds a state directory of its own first
(a temporary one, removed after): ``{"projects": [{id, name}], "entries": [{id, kind, scope, project?, text, title?, said?,
question?, answer?}]}``.

The figures (2 = the answer, 1 = also related): Recall@1 and @5 and MRR of the first answer among the hits shown (sim ≥ τ,
at most 5), noise@5 (the share of the hits shown that are neither), negative_fp_rate (the share of the queries that should
find nothing and show a hit), and the τ with the best F1 over the queries' top 5. Reads only, but for ``--seed``'s own
directory."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from covey.core import memory_search, memstore, projects  # noqa: E402

K = 5
GRID = [round(i * 0.025, 3) for i in range(41)]


def load_set(path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def seed(state_dir, fixture) -> dict:
    """The entries of ``fixture`` written into ``state_dir``: {fixture id: ref}."""
    data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    for project in data.get("projects") or ():
        projects.create(state_dir, projects.new_record(chat_id="oc_eval", name=project["name"], project_id=project["id"],
                                                       now=1_800_000_000.0))
    refs = {}
    for i, row in enumerate(data.get("entries") or ()):
        now = 1_800_000_000.0 + i
        owner_key = row.get("project") or row.get("topic") or ""
        if row["kind"] == "decision":
            made = memstore.add_decision(state_dir, scope=row["scope"], owner_key=owner_key, question=row["question"],
                                         answer=row["answer"], question_ref=f"eval{i:04d}-1", said="owner", now=now)
        else:
            made = memstore.add(state_dir, kind=row["kind"], scope=row["scope"], owner_key=owner_key, text=row["text"],
                                title=row.get("title", ""), said=row.get("said", "owner"),
                                by="owner" if row.get("said", "owner") == "owner" else "lead", now=now)
        refs[row["id"]] = made.ref
    return refs


def resolve(state_dir, key, seeded) -> str:
    if key in seeded:
        return seeded[key]
    found = memstore.find(state_dir, key)
    return found.ref if found is not None else ""


def run(state_dir, queries, *, tau, seeded=None) -> dict:
    seeded = seeded or {}
    per, ranked_all = {}, {}
    for query in queries:
        gold = {resolve(state_dir, key, seeded): grade for key, grade in (query.get("relevant") or {}).items()}
        gold.pop("", None)
        context = {"owner": True, **(query.get("context") or {}), "tau": 0.0}
        hits = memory_search.eval_search(state_dir, query["query"], context, limit=20)
        refs = [(hit["ref"], set(hit.get("aliases") or ()), hit["sim"]) for hit in hits]
        ranked_all[query["id"]] = (refs, gold)
        shown = [item for item in refs if item[2] >= tau][:K]

        def grade(item):
            return max((gold.get(ref, 0) for ref in (item[0], *item[1])), default=0)

        row = {"group": query.get("group", ""), "top": [(ref, round(sim, 4)) for ref, _, sim in refs[:K]]}
        if gold:
            want = 2 if 2 in gold.values() else 1
            first = next((i + 1 for i, item in enumerate(shown) if grade(item) >= want), None)
            row.update(hit1=int(first == 1), hit5=int(first is not None), rr=1 / first if first else 0.0,
                       noise5=(sum(1 for item in shown if not grade(item)) / len(shown)) if shown else 0.0)
        else:
            row["false_positive"] = int(bool(shown))
        per[query["id"]] = row

    def mean(key):
        values = [row[key] for row in per.values() if key in row]
        return round(sum(values) / len(values), 4) if values else None

    summary = {"queries": len(queries), "tau": tau, "Recall@1": mean("hit1"), "Recall@5": mean("hit5"), "MRR": mean("rr"),
               "noise@5": mean("noise5"), "negative_fp_rate": mean("false_positive"), "best_tau": sweep(ranked_all)}
    return {"summary": summary, "per_query": per}


def sweep(ranked_all) -> dict:
    best = None
    for tau in GRID:
        tp = fp = fn = 0
        for refs, gold in ranked_all.values():
            picked = {ref for ref, aliases, sim in refs[:K] if sim >= tau and (ref in gold or aliases & set(gold))}
            wrong = sum(1 for ref, aliases, sim in refs[:K] if sim >= tau and not (ref in gold or aliases & set(gold)))
            tp += len(picked)
            fp += wrong
            fn += max(min(len(gold), K) - len(picked), 0)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if best is None or f1 >= best["F1"]:
            best = {"tau": tau, "F1": round(f1, 4), "P": round(precision, 4), "R": round(recall, 4)}
    return best or {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="查记忆的离线测评：召回、噪声、负例误报和各阈值的 F1")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--state", help="状态目录（只读）")
    where.add_argument("--seed", help="合成夹具 JSON：先建一个临时状态目录")
    parser.add_argument("--set", required=True, help="查询集 JSONL")
    parser.add_argument("--tau", type=float, default=memory_search.DEFAULT_TAU, help="运行阈值（默认 DEFAULT_TAU）")
    parser.add_argument("--json", action="store_true", help="整份结果 JSON 输出")
    args = parser.parse_args(argv)
    queries = load_set(args.set)
    made = None
    try:
        if args.seed:
            made = tempfile.mkdtemp(prefix="memory-eval-")
            state, seeded = Path(made), seed(Path(made), args.seed)
        else:
            state, seeded = Path(args.state), {}
        report = run(state, queries, tau=args.tau, seeded=seeded)
    finally:
        if made:
            shutil.rmtree(made, ignore_errors=True)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        s = report["summary"]
        print(f"{s['queries']} 条  τ={s['tau']}  R@1={s['Recall@1']}  R@5={s['Recall@5']}  MRR={s['MRR']}  "
              f"noise@5={s['noise@5']}  负例误报={s['negative_fp_rate']}  F1 最优 τ={s['best_tau']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
