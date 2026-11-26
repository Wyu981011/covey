"""What the Bridge sees of a turn's use of the memory (FINAL-SPEC 修订 8): the strong signals the ranking counts, nothing else.

After a turn ``observe`` adds to each entry's ``hits`` (core/memory_rank.py SIGNAL_WEIGHTS): the turn ran ``covey memory
show`` for it, question_dedup answered a question with it, the owner confirmed it, or the checkpoint's ``memory_used``
named it (half weight). Restating an entry's words is not a signal. A0: nothing is counted yet (package M2).
"""
from __future__ import annotations


def observe(ctx, job, result) -> None:
    """Count the signals of ``job``'s finished turn ``result``: not yet."""
    return None
