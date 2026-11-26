"""The repositories' part of a turn (FINAL-SPEC 修订 9): the dynamic repository block at the prompt's tail, and settling a task's requests.

``tail`` is the block app/runs.py puts after the checkpoint note each turn (修订 4: never in the cached rules): the
repositories the topic uses, whether their rules were read, a repository a declared write still has to read the rules
of (its first lines inlined, ≤4 KB, and again the next turn when they were not read), and a reminder when the main
checkout was changed. ``settle`` folds a task's ``runs/<任务键>/repos.json`` into ``topic.json`` when its turn ends.
A0: ``tail`` is empty and ``settle`` does nothing (package W1).
"""
from __future__ import annotations

RULES_INLINE_BYTES = 4096


def tail(ctx, job) -> str:
    """The repository block of ``job``'s turn: none yet."""
    return ""


def settle(ctx, job, task_dir) -> None:
    """Fold the ``covey repo use`` requests of ``job``'s task (core/topic_repos.py requests) into its topic: not yet."""
    return None
