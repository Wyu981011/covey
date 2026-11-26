"""Before a question reaches the owner, look for the same question answered before (FINAL-SPEC 修订 6).

The check runs in app/native_questions.py ``NativeQuestions.dispatch``, strictly before ``register`` (a registered
question that is never shown holds the topic). A project's question that triage routes to its lead goes there with the
old answer attached, no extra turn. One for the owner: on Claude Code and MASO the backend's ``reject_question`` hands
the old answer back in the same turn, at most ``MAX_REJECTS`` time per (topic, question hash), kept on disk; on Codex,
agy and dsh the card only shows a grey line “上次你答过：…” and is never held. The five high-risk classes
(``HIGH_RISK``) are only noted, never held. The third same-class answer adds a question of its own (``class3``), kept in
the record's ``extra_questions`` and never in ``questions`` (live_question_proof hashes those); only the owner's own
submit writes a rule from it, a lead answering never does, and “还要问” keeps it away for ``CLASS3_QUIET_DAYS``.
A0: no question is ever matched (package M3).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

MAX_REJECTS = 1
CLASS3_AFTER = 3
CLASS3_QUIET_DAYS = 30
HIGH_RISK = ("deploy", "delete", "spend", "send", "occupy")  # 部署上线、删除与撤不回、花钱、对外发送、占机器.
EXTRA_KEY = "extra_questions"


@dataclass(frozen=True)
class Hit:
    ref: str
    code: str
    answer: str
    topic_number: int | None
    at: float
    sim: float


def q_hash(question: dict) -> str:
    """A question's fingerprint: its text and its options' labels, whitespace folded."""
    text = " ".join(str(question.get("question") or question.get("header") or "").split())
    labels = "\0".join(" ".join(str(option.get("label") or "").split()) for option in question.get("options") or ()
                       if isinstance(option, dict))
    return hashlib.sha1(f"{text}\0{labels}".encode("utf-8")).hexdigest()[:16]


def check(ctx, record: dict, questions) -> dict:
    """{question id: Hit} of ``questions`` answered before: none yet."""
    return {}
