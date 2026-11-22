"""协作卡 at the Bridge (docs/architecture.md 多参与者协作 · 两端, COVEY_COLLAB=1; off: no card, no click taken): the card of
cards/collab_card.py in the integrator's thread, sent when a collaboration starts and redrawn whole each time its record
says something new. The record (core/collab_records.py) is the truth and the web page reads the same one: the card only
projects it, and its 停止这次协作 and the page's go through ``Collaboration.stop``, so a click on either side stops it once.

- ``refresh`` (app/collab_flow.py calls it after each change of a record, its thread now and then for a card that missed a
  write): draws the card from ``records.view``; a digest the record keeps says whether it differs from what is on the chat,
  so a refresh that changed nothing sends nothing. The first send goes to the integrator's thread where ``tell`` puts its
  lines (at the top level for the butler); the card id is kept in the record before the message is sent, so a send that
  did not land is sent again as the same card under the same key. A later write is one whole-card write with a sequence
  from ``reserve``, saved before the request goes out (rule 3). The record's lock is only held to read and to save
  (rule 1); the card's own lock serialises the writers of one collaboration's card.
- ``claim`` (a feature of app/unified.py PANELS): the owner's 停止这次协作. A collaboration already ended is only redrawn;
  ``stop`` runs once, the second click finds it ended."""
from __future__ import annotations

import time

from covey.app.card_lanes import after_ack
from covey.app.card_publish import digest_of
from covey.cards import collab_card as view
from covey.core import collab, turn_source
from covey.core import collab_records as records
from covey.core.card_sequence import CardHandle, reserve
from covey.core.locks import resource_lock

OWNER_ONLY = "owner_only"
OUTCOMES = {"stopped": "collab_stop", "ended": "collab_ended", "unknown": "collab_unknown"}


def enabled() -> bool:
    return turn_source.enabled()


class CollabCards:
    """The collaboration's cards. ``flow``: the Collaboration (app/collab_flow.py), whose ``stop`` and thread root it uses."""

    def __init__(self, runtime, messenger, voice, flow) -> None:
        self.runtime, self.messenger, self.voice, self.flow = runtime, messenger, voice, flow

    # -- drawing -------------------------------------------------------------------------------------------------------

    def refresh(self, ctx, collab_id, *, create=True) -> bool:
        """Bring the card of ``collab_id`` up to its record: send it when it was never sent (``create``), write it whole
        when the record says something new. Whether the card is on the chat now. Never raises; nothing with the switch off."""
        if not enabled():
            return False
        try:
            with resource_lock("collab-card", collab_id):
                return self._refresh(ctx, collab_id, create)
        except Exception as exc:  # noqa: BLE001 - the record says it all the same
            self.runtime.log(f"collab card not drawn collab={str(collab_id)[:8]}: {type(exc).__name__}: {str(exc)[:120]}")
            return False

    def _refresh(self, ctx, cid, create) -> bool:
        state = ctx.state_dir
        record = records.read(state, cid)
        if not record:
            return False
        saved = record.get("card") if isinstance(record.get("card"), dict) else {}
        built = view.collab_card(records.view(record))
        digest = digest_of(built)
        if saved.get("message_id"):
            if saved.get("digest") != digest:
                self.write(ctx, cid, saved, built, digest)
            return True
        return create and self.send(ctx, record, saved, built, digest)

    def keep(self, ctx, cid, **fields):
        """The card's record fields changed under the record's lock: a short write, never around a request."""
        def edit(current):
            if not current:
                return None
            return {**current, "card": {**(current.get("card") or {}), **fields}}
        return records.change(ctx.state_dir, cid, edit)

    def send(self, ctx, record, saved, built, digest) -> bool:
        cid, chat = record["id"], record["chat_id"]
        topic = (record.get("integrator") or {}).get("key", "")
        reused = bool(saved.get("card_id"))
        key = self.voice.key("collab-card", cid)
        card_id, message = self.messenger.create_and_send_card(
            ctx.profile, chat, built, key, voice=self.voice, card_id=saved.get("card_id") or "",
            on_created=lambda made: self.keep(ctx, cid, card_id=made),
            reply_to_message_id=self.flow.thread_root(ctx, chat, topic))
        if not message:
            self.runtime.log(f"collab card not sent collab={cid[:8]}")
            return False
        # A card made before and sent now may hold an older drawing: its digest is left empty so the next refresh writes.
        self.keep(ctx, cid, card_id=card_id, message_id=message, sequence=int((saved or {}).get("sequence") or 0),
                  digest="" if reused else digest, sent_at=time.time())
        self.runtime.log(f"collab card sent collab={cid[:8]} message={message[-8:]}")
        return True

    def write(self, ctx, cid, saved, built, digest) -> bool:
        """One whole-card write: the sequence reserved and saved first, never reused (rule 3)."""
        card_id = str(saved.get("card_id") or "")
        handle = CardHandle(card_id, lambda sequence: self.keep(ctx, cid, sequence=sequence), saved.get("sequence"),
                            shared=False)
        with handle.lock:
            number = reserve(handle)
            result = self.messenger.put_card(ctx.profile, card_id, built, sequence=number,
                                             key=f"collab-card-{cid[:12]}-{number}", timeout=3)
        if result is None:
            self.runtime.log(f"collab card not written collab={cid[:8]}")
            return False
        self.keep(ctx, cid, digest=digest, wrote_at=time.time())
        return True

    # -- a click -------------------------------------------------------------------------------------------------------

    def matches(self, raw) -> bool:
        return isinstance(raw, dict) and raw.get("kind") == view.KIND

    def claim(self, ctx, event, raw, owner):
        """A click on 停止这次协作 (app/unified.py PANELS), else None. The owner's only (rule 11). A collaboration that is no
        longer open is only drawn again; one open is stopped by ``Collaboration.stop`` (by="card") after the click is
        acknowledged, and drawn again."""
        if not self.matches(raw) or not enabled():
            return None
        if not owner:
            return OWNER_ONLY
        cid, chat = str(raw.get("collab") or ""), str(event.get("chat_id") or "")
        record = records.read(ctx.state_dir, cid)
        if not record or record.get("chat_id") != chat:
            return OUTCOMES["unknown"]
        if record.get("state") != collab.OPEN:
            after_ack(lambda: self.refresh(ctx, cid))
            return OUTCOMES["ended"]

        def stop():
            if records.read(ctx.state_dir, cid).get("state") == collab.OPEN:  # A click delivered twice, or the page's first.
                self.flow.stop(ctx, cid, by="card")
            self.refresh(ctx, cid)
        after_ack(stop)
        return OUTCOMES["stopped"]
