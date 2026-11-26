"""The write gate of a memory entry (FINAL-SPEC 修订 8): what is refused or rewritten, what is only flagged.

Hard refusals (or a rewrite offered) are kept to two things that go wrong whatever the context: a time reference that
stops being true (``TIME_WORDS``: 今天、刚才、目前…) and an explicit live state (``DYNAMIC_RES``: 现网第 N 代 and the
like; such a state goes nowhere in memory, the entry says where to look). Vague pointers (``SOFT_WORDS``: 这个、这类、
那个、上面) and ordinary commit hashes or clock times are flagged only, never refused. A0: the words and the shape of
the verdict; ``check`` is package M2's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TIME_WORDS = ("今天", "明天", "昨天", "刚才", "刚刚", "目前", "现在", "本周", "这周", "今晚", "今早", "上周", "下周")
DYNAMIC_RES = (re.compile(r"现网(?:是|在|为)?第\s*\d+\s*代"), re.compile(r"(?:当前|现在)(?:版本|部署)(?:是|为)\s*\S+"))
SOFT_WORDS = ("这个", "这类", "那个", "上面")
FLAGS = ("vague", "dynamic", "repeat", "old_repo")


@dataclass(frozen=True)
class Verdict:
    ok: bool  # False: refused; ``text`` is the rewrite offered, '' when there is none.
    text: str
    flags: tuple = ()  # Of FLAGS.
    reason: str = ""


def check(text: str, *, kind: str, title: str = "") -> Verdict:
    """The verdict on a new entry's ``text`` of ``kind``: M2."""
    raise NotImplementedError("M2")
