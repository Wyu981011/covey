#!/usr/bin/env python3
"""How much the turns asked the owner: question cards and their questions, per window of days, to compare before and after
a change of the asking rules (core/checkpoint.py ASK_RULE, PLAN_RULE).

    python3 -B scripts/question_stats.py --state "$STATE_DIR" [--window 2026-11-11:2026-11-25 ...] [--daily] [--json]
    ssh <host> python3 - --state <state> --window ... < scripts/question_stats.py     # another machine, read only

Reads ``questions/*.json`` and ``jobs/*.json`` of the state directory and writes nothing. A window is ``SINCE:UNTIL``
(local dates, both days in); without one, the last 7 days up to today. Per window:

- 轮次: jobs created in it; 问题卡: question records created in it (one record is one card, however many questions);
  卡/天, 卡/百轮 (cards per 100 turns, so a busier week does not look like more asking);
- 题: the questions of those cards; 带推荐: those with an option labelled 推荐; 选推荐: those answered with one;
  选推荐率 = 选推荐 / 题; 不回答: answered 不回答此题 (不处理 too); 负责人替答: cards a project's lead answered;
- 第一轮就问: cards asked in the first turn of their topic (a plan asked about before it was given);
- 按类别: each question by the words of its header and text, the first that matches of KINDS, else 其他. The kinds are
  ASK_SHORT's, the ones still asked; 其他 is what the rules now do the recommended way.

Standard library only, so it runs where only a ``python3`` is (a colleague's machine through ssh). Records are read by a
few threads with a deadline (``--seconds``): a file stuck on a network mount is counted as unread, not waited on.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
from collections import Counter

# The first that matches a question's header and text. Rough on purpose: the same words before and after.
KINDS = (
    ("部署", re.compile(r"部署|发布|上线|发版|现网|deploy|release|rollout", re.I)),
    ("删除", re.compile(r"删|清理|清空|移除|回收|delete|drop", re.I)),
    ("花钱", re.compile(r"花钱|费用|付费|购买|采购|充值|预算|计费|账单|买")),
    ("对外发送", re.compile(r"发给|发送|通知|打电话|代发|对外|邮件|转发给|发到群")),
    ("占机器", re.compile(r"GPU|显卡|卡时|集群|占用|占机器|长期运行|常驻|配额", re.I)),
)
OTHER = "其他"
RECOMMENDED = "推荐"
SKIPPED = "不回答此题"
LEAD_ANSWERED = "answered_by_lead"  # core/triage.py ANSWERED.


def day(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def epoch(value) -> float | None:
    """A record's time: epoch seconds, or an ISO string (a job's ``created_at``)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def window(text: str) -> tuple[str, str]:
    since, _, until = text.partition(":")
    for each in (since, until):
        dt.date.fromisoformat(each)
    if until < since:
        raise ValueError(text)
    return since, until


def read_records(directory: str, since: float, seconds: float) -> tuple[list[dict], int]:
    """(the records of ``directory`` changed since ``since``, how many could not be read in ``seconds``). A file changed
    before ``since`` was created before it too, so it is skipped without being opened."""
    try:
        names = [name for name in os.listdir(directory) if name.endswith(".json")]
    except OSError:
        return [], 0

    def one(name):
        path = os.path.join(directory, name)
        try:
            if os.stat(path).st_mtime < since:
                return None
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    pool = cf.ThreadPoolExecutor(16)
    futures = [pool.submit(one, name) for name in names]
    done, stuck = cf.wait(futures, timeout=seconds)
    pool.shutdown(wait=False, cancel_futures=True)
    return [record for future in done if (record := future.result())], len(stuck)


def kind(question: dict) -> str:
    text = f"{question.get('header') or ''} {question.get('question') or ''}"
    return next((name for name, words in KINDS if words.search(text)), OTHER)


def items(card: dict):
    """(kind, has a 推荐 option, answered with one, answered 不回答此题) of each question of ``card``."""
    answers = card.get("answers") if isinstance(card.get("answers"), dict) else {}
    for question in card.get("questions") or ():
        if not isinstance(question, dict):
            continue
        answer = answers.get(question.get("id"))
        given = [str(each) for each in (answer.get("answers") or () if isinstance(answer, dict) else ())]
        offered = any(RECOMMENDED in str((option or {}).get("label") or "") for option in question.get("options") or ()
                      if isinstance(option, dict))
        yield kind(question), offered, any(RECOMMENDED in each for each in given), any(SKIPPED in each for each in given)


def first_jobs(jobs: list[dict]) -> set:
    """The job id of each topic's first turn among ``jobs``."""
    first = {}
    for job in jobs:
        topic, number = job.get("topic_id"), job.get("job_id")
        if topic and isinstance(number, int) and (topic not in first or number < first[topic]):
            first[topic] = number
    return set(first.values())


def stats(cards: list[dict], jobs: list[dict], since: str, until: str, firsts: set) -> dict:
    def inside(record):
        at = epoch(record.get("created_at"))
        return at is not None and since <= day(at) <= until

    cards = [card for card in cards if inside(card)]
    turns = sum(1 for job in jobs if inside(job))
    days = (dt.date.fromisoformat(until) - dt.date.fromisoformat(since)).days + 1
    count, offered, picked, skipped = Counter(), Counter(), Counter(), Counter()
    for card in cards:
        for name, has, chose, skip in items(card):
            count[name] += 1
            offered[name] += has
            picked[name] += chose
            skipped[name] += skip
    total = sum(count.values())
    lead = sum(1 for card in cards if isinstance(card.get("triage"), dict) and card["triage"].get("state") == LEAD_ANSWERED)
    first = sum(1 for card in cards if card.get("job_id") in firsts)

    def share(part, whole):
        return round(100 * part / whole, 1) if whole else None

    return {
        "since": since, "until": until, "days": days, "turns": turns, "cards": len(cards),
        "cards_per_day": round(len(cards) / days, 1), "cards_per_100_turns": share(len(cards), turns),
        "questions": total, "offered_recommended": sum(offered.values()), "picked_recommended": sum(picked.values()),
        "picked_recommended_pct": share(sum(picked.values()), total), "skipped": sum(skipped.values()),
        "skipped_pct": share(sum(skipped.values()), total), "lead_answered_cards": lead,
        "first_turn_cards": first, "first_turn_pct": share(first, len(cards)),
        "kinds": {name: {"questions": count[name], "picked_recommended": picked[name], "skipped": skipped[name]}
                  for name in [*(name for name, _ in KINDS), OTHER]},
    }


def show(row: dict) -> str:
    def pct(value):
        return "—" if value is None else f"{value}%"

    lines = [f"{row['since']} ~ {row['until']}（{row['days']} 天）",
             f"  轮次 {row['turns']}，问题卡 {row['cards']}：{row['cards_per_day']} 张/天，每百轮 {row['cards_per_100_turns'] or '—'} 张",
             f"  题 {row['questions']}：带推荐 {row['offered_recommended']}，选推荐 {row['picked_recommended']}（{pct(row['picked_recommended_pct'])}），"
             f"不回答 {row['skipped']}（{pct(row['skipped_pct'])}）",
             f"  第一轮就问的卡 {row['first_turn_cards']}（{pct(row['first_turn_pct'])}），负责人替答的卡 {row['lead_answered_cards']}",
             "  按类别（题 / 选推荐 / 不回答）：" + "，".join(
                 f"{name} {each['questions']}/{each['picked_recommended']}/{each['skipped']}" for name, each in row["kinds"].items())]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="问题卡问得多不多：按时间窗统计问题卡、选推荐和类别（只读）")
    parser.add_argument("--state", required=True, help="状态目录（有 questions/ 和 jobs/ 的那个）")
    parser.add_argument("--window", action="append", default=[], help="SINCE:UNTIL，本地日期、两头都算；可给多个对比")
    parser.add_argument("--daily", action="store_true", help="再按天各列一行")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--seconds", type=float, default=60.0, help="读记录的总时限（秒），超时没读到的算未读")
    args = parser.parse_args(argv)
    today = dt.date.today()
    try:
        windows = [window(text) for text in args.window] or [((today - dt.timedelta(days=6)).isoformat(), today.isoformat())]
    except ValueError as exc:
        parser.error(f"--window 要写成 2026-11-11:2026-11-25：{exc}")
    since = dt.datetime.fromisoformat(min(each[0] for each in windows)).timestamp()
    cards, cards_unread = read_records(os.path.join(args.state, "questions"), since, args.seconds)
    # Each topic's first turn may be older than the windows: every job is read for it, not only those since.
    jobs, jobs_unread = read_records(os.path.join(args.state, "jobs"), 0.0, args.seconds)
    firsts = first_jobs(jobs)
    rows = [stats(cards, jobs, a, b, firsts) for a, b in windows]
    if args.daily:
        rows += [stats(cards, jobs, each, each, firsts) for a, b in windows
                 for each in (str(dt.date.fromisoformat(a) + dt.timedelta(days=n))
                              for n in range((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1))]
    unread = {"questions": cards_unread, "jobs": jobs_unread}
    if args.json:
        print(json.dumps({"windows": rows, "unread": unread}, ensure_ascii=False, indent=1))
    else:
        print("\n\n".join(map(show, rows)))
        if cards_unread or jobs_unread:
            print(f"\n未读（超时）：问题记录 {cards_unread}，任务记录 {jobs_unread}；结果偏少")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # A thread stuck on a network file must not keep the process.
