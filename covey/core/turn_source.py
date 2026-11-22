"""轮次来源 (docs/architecture.md 多参与者协作): what started a turn, as a field only the Bridge writes, so no reader guesses it
from a message id or a sender, and what a turn of each source may do to the owner's things.

A job without ``turn_source`` (every job before this field, and every one this release makes) is ``LEGACY``: each reader goes
on as before (the message id's prefix, the sender, the topic's role), so nothing a job does changes. A job with one carries
``{"v": 1, "kind": …, "asserted_by": …, "recorded_by": "bridge", "origin": {…}, "collab": …, "ask": …}`` (``make``) in its record,
its queued file and its handoff's extras; a model's tool argument never sets it.

- ``behavior``: one row of ``BEHAVIOR`` a kind (owner's words or not, may answer a waiting question, may go in as a 补充, held to
  reading, is its topic's own delivery, may draft a 代发): every consumer asks it, none reads the kind itself. A kind this
  release does not know, or a malformed field, gets ``NOTHING``.
- ``refusal``: why this release does not run a job ('' when it does). Outside ``RUNS`` (a newer release's kind, a newer
  version, a malformed field) it never runs, whatever the switch: app/job_dispatch.py and
  app/worker.py record it cancelled and never started instead of running its text as the owner's message. A kind in
  ``RUNS`` that ``SWITCHED`` lists runs only with COVEY_COLLAB=1, and only on a Harness that declares ``NEEDS`` of it
  (core/harness.py HarnessCapabilities ``collab``, ``read_only``).
- ``provenance``: who said it (``asserted_by``) and who wrote it down (``recorded_by``), two fields, never one; the level is the
  Bridge's, from where the words came in: ``owner`` only with an origin it took in (a message id, a question token).

Standard library and core only: cards, the MCP server and an extension's isolated interpreter may read it.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from covey.core import env as cenv

SWITCH = "COVEY_COLLAB"  # ``1``: 协作 turns may be dispatched where all three sides support them; anything else: off.
FIELD = "turn_source"
VERSION = 1  # The field's version this release reads: a higher one is a newer release's and is not run.

LEGACY = "legacy"  # What ``kind`` says of a job without the field: as before.
OWNER = "owner"  # The owner's own message, stamped (no release stamps it yet: the owner's messages are LEGACY).
ASK = "collab_ask"  # 协作咨询: one participant asks another, which answers in its own session, held to reading.
REPLY = "collab_reply"  # 协作答复续接: the integrator's turn that goes on once the answers are in; its own delivery.
HANDOVER = "handover"  # A butler turn for an owner's request a topic could not do (开专项, 停别的话题, 收进专项).
MALFORMED = "?"  # A field that is not an object, or whose kind is not a string.
KINDS = frozenset({OWNER, ASK, REPLY, HANDOVER})
# The kinds this release runs, LEGACY aside. A package that runs another adds it here: ``handover`` since 话题转交管家
# (app/butler_asks.py) queues such a turn of the butler's; the two of 协作 since app/collab_flow.py queues them (with the
# switch, on a Harness that declares NEEDS: its consumers ask ``behavior``).
RUNS = frozenset({OWNER, HANDOVER, ASK, REPLY})
SWITCHED = frozenset({ASK, REPLY})  # Run only with SWITCH on.
# HarnessCapabilities fields each kind needs: an ask runs in a fork of its helper's session held to CONSULT
# (app/collab_channel.py; with no session to fork, from the helper's record), a continuation is the integrator's own turn.
NEEDS = {ASK: ("collab", "read_only"), REPLY: ("collab",)}

# Who said it or wrote it down (``asserted_by``, ``recorded_by``).
PARTY_OWNER, PARTY_BUTLER, PARTY_LEAD, PARTY_TOPIC, PARTY_BRIDGE = "owner", "butler", "lead", "topic", "bridge"
PARTIES = frozenset({PARTY_OWNER, PARTY_BUTLER, PARTY_LEAD, PARTY_TOPIC, PARTY_BRIDGE})
# The level the Bridge gives a statement: the owner's words it took in itself, or anybody else's (a model's summary,
# a reply, an owner's word carried on without the origin that shows it).
LEVEL_OWNER, LEVEL_AGENT = "owner", "agent"
ORIGIN_KEYS = ("message_id", "question")  # What an origin may point at; ``topic`` and ``chat`` say where.

NOT_RUN = "这一轮的来源（{kind}）这个版本不执行，没有按主人的消息跑"
SWITCH_OFF = "协作没有打开（COVEY_COLLAB），这一轮没有跑"
NOT_DECLARED = "这个 Harness 没有声明协作要的能力（{names}），这一轮没有跑"


@dataclasses.dataclass(frozen=True)
class Behavior:
    """What a turn of one source may do to the owner's things (docs/architecture.md 轮次来源)."""

    owner_words: bool  # Its text is the owner's: memory and 记一下 are taken from it, a lead's owner turn counts it.
    answers_questions: bool  # It may be the answer to a question waiting in its topic.
    steers: bool  # It may go into a running task of its topic as a 补充.
    read_only: bool  # Held to reading, where its Harness can hold it (core/harness.py TOOL_LIMIT); False: as the job says.
    # Its result is its topic's own: the answer card, the board, the relay, the lead's receipt, a revisit, the library. False
    # (an ask's): nothing of it is in the chat, no task card, no recovery card, no automatic retry; what became of it is
    # its collaboration record's (app/collab_flow.py), which settles it, queues it again or ends it.
    own_delivery: bool
    owner_send: bool  # Its checkpoint's send_as_owner drafts are offered (the owner confirms each on its card).


AS_BEFORE = Behavior(owner_words=True, answers_questions=True, steers=True, read_only=False, own_delivery=True,
                     owner_send=True)
NOTHING = Behavior(owner_words=False, answers_questions=False, steers=False, read_only=True, own_delivery=False,
                   owner_send=False)
BEHAVIOR = {
    LEGACY: AS_BEFORE,
    OWNER: AS_BEFORE,
    ASK: Behavior(owner_words=False, answers_questions=False, steers=False, read_only=True, own_delivery=False,
                  owner_send=False),
    REPLY: Behavior(owner_words=False, answers_questions=False, steers=False, read_only=False, own_delivery=True,
                    owner_send=True),
    HANDOVER: Behavior(owner_words=True, answers_questions=False, steers=False, read_only=False, own_delivery=True,
                       owner_send=False),
}


def enabled() -> bool:
    """Whether COVEY_COLLAB=1 (only ``1``; read on every call)."""
    return str(cenv.get(SWITCH, "")).strip() == "1"


def of(*items):
    """The ``turn_source`` of the first of ``items`` (jobs, records, mappings) that has one; None when none has (LEGACY).
    An empty value counts as none: the job's declared default is ``{}``."""
    for item in items:
        if item is None:
            continue
        value = item.get(FIELD) if isinstance(item, Mapping) else getattr(item, FIELD, None)
        if value:
            return value
    return None


def kind(*items) -> str:
    """LEGACY without the field, else its kind as written (a string), MALFORMED when it cannot be read."""
    value = of(*items)
    if value is None:
        return LEGACY
    if not isinstance(value, Mapping) or not isinstance(value.get("kind"), str):
        return MALFORMED
    return value["kind"]


def _newer(value) -> bool:
    version = value.get("v", VERSION) if isinstance(value, Mapping) else VERSION
    return not isinstance(version, int) or isinstance(version, bool) or version > VERSION


def behavior(*items) -> Behavior:
    """The row of the first of ``items`` that has a source; AS_BEFORE without one; NOTHING for a kind or version this
    release does not know."""
    value = of(*items)
    if value is not None and _newer(value):
        return NOTHING
    return BEHAVIOR.get(kind(*items), NOTHING)


def refusal(*items, capabilities=None, runs=RUNS) -> str:
    """Why this release does not run the job of ``items`` ('' when it does): see the module docstring. ``capabilities``:
    the Harness's (core/harness.py HarnessCapabilities), for a kind that NEEDS some. ``runs``: the kinds run (a test, or a
    later package, passes more)."""
    found, value = kind(*items), of(*items)
    if found == LEGACY:
        return ""
    if found not in runs or found not in KINDS or _newer(value):
        return NOT_RUN.format(kind=found)
    if found in SWITCHED and not enabled():
        return SWITCH_OFF
    missing = [name for name in NEEDS.get(found, ()) if not getattr(capabilities, name, False)]
    return NOT_DECLARED.format(names="、".join(missing)) if missing else ""


def origin_of(origin) -> dict:
    """The parts of ``origin`` kept (``ORIGIN_KEYS``, ``topic``, ``chat``), as strings; {} for none."""
    if not isinstance(origin, Mapping):
        return {}
    return {key: str(origin[key]) for key in (*ORIGIN_KEYS, "topic", "chat") if origin.get(key)}


def provenance(asserted_by, recorded_by, origin=None) -> dict:
    """{asserted_by, recorded_by, origin, level}: ``level`` is LEVEL_OWNER only when the owner said it and ``origin`` names
    where the Bridge took it in (``message_id`` or ``question``); anything else is LEVEL_AGENT, so a model writing "主人同意了"
    without the owner's message gains nothing. A party outside PARTIES raises ValueError."""
    if asserted_by not in PARTIES or recorded_by not in PARTIES:
        raise ValueError(f"unknown party: {asserted_by!r} / {recorded_by!r}")
    kept = origin_of(origin)
    level = LEVEL_OWNER if asserted_by == PARTY_OWNER and any(key in kept for key in ORIGIN_KEYS) else LEVEL_AGENT
    return {"asserted_by": asserted_by, "recorded_by": recorded_by, "origin": kept, "level": level}


def make(kind_, *, asserted_by, origin=None, collab="", ask="") -> dict:
    """The field the Bridge writes on a job it makes: ``kind_`` one of KINDS, recorded by the Bridge, with ``collab`` and
    ``ask`` (a collaboration's id and its ask's) when it is one of 协作's. A kind outside KINDS raises ValueError."""
    if kind_ not in KINDS:
        raise ValueError(f"unknown turn source: {kind_!r}")
    made = {"v": VERSION, "kind": kind_, **provenance(asserted_by, PARTY_BRIDGE, origin)}
    if collab:
        made["collab"] = str(collab)
    if ask:
        made["ask"] = str(ask)
    return made
