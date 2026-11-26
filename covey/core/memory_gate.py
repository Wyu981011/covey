"""The write gate of a memory entry (docs/butler.md 记忆): what is refused or rewritten, what is only flagged.

Hard refusals (or a rewrite offered) are kept to two things that go wrong whatever the context: a time reference that
stops being true (``TIME_WORDS``: 今天、刚才、目前…) and an explicit live state (``DYNAMIC_RES``: 现网第 N 代 and the
like; such a state goes nowhere in memory, the entry says where to look). Vague pointers (``SOFT_WORDS``: 这个、这类、
那个、上面) and ordinary commit hashes or clock times are flagged only, never refused. Memory entries are
written through it (docs/butler.md 记忆); ``check`` is a pure function.
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


_FROM = "|".join(map(re.escape, TIME_WORDS))
# A leading time word that can go without the sentence breaking: 从今天起 / 今天开始 / 目前，/ 现在，/ 目前 and 现在 (adverbs) before words.
_PREFIX = re.compile(rf"^(?:从\s*(?:{_FROM})\s*(?:起|开始)|(?:{_FROM})\s*(?:起|开始)|(?:目前|现在)(?:[，,、：:\s]+|(?=只|都|先|不|要|必须|统一|默认|一律)))[，,、：:\s]*")
MIN_REWRITE = 4  # A rewrite shorter than this is no sentence: the verdict gives none.


def check(text: str, *, kind: str, title: str = "") -> Verdict:
    """The verdict on a new entry's ``text`` of ``kind`` (pure: no state is read).

    A live state (``DYNAMIC_RES``) is refused with no rewrite; a time word (``TIME_WORDS``) is refused with the sentence
    rewritten when a leading 从今天起 / 目前 / 现在 can simply go, else with no rewrite. Vague pointers (``SOFT_WORDS``) are
    only flagged ``vague``, a live state in a decision only ``dynamic``; a decision (kind ``decision``: the question and the
    answer as given) is never refused. Commit hashes and clock times are neither flagged nor refused. ``title`` is read with
    the text for the flags only."""
    body = str(text or "").strip()
    seen = f"{title or ''} {body}"
    flags = []
    if any(word in seen for word in SOFT_WORDS):
        flags.append("vague")
    dynamic = any(pattern.search(body) for pattern in DYNAMIC_RES)
    if dynamic:
        flags.append("dynamic")
    if kind == "decision":
        return Verdict(True, body, tuple(flags))
    if dynamic:
        return Verdict(False, "", tuple(flags), "含会变的现状说法，别把现状写进记忆，写成去哪里查或按什么原则办")
    hit = next((word for word in TIME_WORDS if word in body), "")
    if not hit:
        return Verdict(True, body, tuple(flags))
    rewritten = _PREFIX.sub("", body, count=1).strip()
    if rewritten != body and len(rewritten) >= MIN_REWRITE and not any(word in rewritten for word in TIME_WORDS):
        return Verdict(False, rewritten, tuple(flags), f"含会过时的说法“{hit}”，已改成不依赖时间的写法")
    return Verdict(False, "", tuple(flags), f"含会过时的说法“{hit}”，写成不依赖时间的说法")


def accept(text: str, *, kind: str, title: str = "") -> tuple[str, Verdict]:
    """(what an automatic write keeps, the verdict): the text when it passes, the rewrite the verdict offers when that one
    passes in its turn, '' when neither does (the write is dropped)."""
    verdict = check(text, kind=kind, title=title)
    if verdict.ok:
        return verdict.text, verdict
    if verdict.text:
        again = check(verdict.text, kind=kind, title=title)
        if again.ok:
            return again.text, again
    return "", verdict
