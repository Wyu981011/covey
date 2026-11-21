"""The image key of an avatar (core/avatars.py): the picture's file uploaded to Feishu the first time a card needs it,
the key kept in <state>/avatars.json after. The upload is a call of its own, made where a card is made, never under a
record's lock (docs/architecture.md 最容易改坏的规则 1, 2). Without a key the card has its speaker's name alone."""
from __future__ import annotations

import time

from covey.core import avatars, env as cenv
from covey.feishu.outgoing_images import upload_image

SWITCH = "COVEY_AVATARS"  # "0": no pictures on the cards, nothing uploaded (the test suite's default, tests/support).
RETRY_SECONDS = 600  # After a failed upload, the same picture is not tried again for this long (an upload waits up to 60 s).
_failed: dict = {}


def image_key(state_dir, profile, name, log=None, *, upload=None) -> str:
    """The image key of ``name``'s picture for ``profile``'s app: the kept one, else the file uploaded now; '' when
    there is no such picture or it could not be uploaded (said to ``log``, tried again after RETRY_SECONDS). Never
    raises."""
    try:
        path = avatars.asset(name)
        if not name or path is None or not state_dir or cenv.get(SWITCH, "1").strip() == "0":
            return ""
        key = avatars.cached_key(state_dir, profile, name)
        if key:
            return key
        tried = (str(state_dir), str(profile or ""), name, avatars.digest(name))
        if time.monotonic() - _failed.get(tried, -RETRY_SECONDS) < RETRY_SECONDS:
            return ""
        key = (upload or upload_image)(path, profile)
        if not key:
            _failed[tried] = time.monotonic()
            if log is not None:
                log(f"avatar {name} not uploaded: the card goes without its picture")
            return ""
        avatars.remember_key(state_dir, profile, name, key)
        return key
    except Exception as exc:  # noqa: BLE001 - the card goes without its picture
        if log is not None:
            log(f"avatar {name} unavailable: {type(exc).__name__}")
        return ""
