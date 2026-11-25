"""A model gateway's spent daily quota, held until it resets so that new requests on it fail here at once.

A gateway (core/gateways.py) that answers 403 with its ``quota_pattern`` and says when the quota is back ("Resets at
2026-11-25T16:00:00Z", Acme's words) is held in <state>/<gateway>/quota-hold.json until then:

- its relay (backends/gateway/relay.py, ``Hold``) answers Codex's requests itself instead of sending them upstream, as
  a spent quota Codex gives up on at once: a 403 or a 402 it retries ten times, about 205 s (codex-cli 0.172.0 against a
  local stand-in upstream), a 429 ``insufficient_quota`` not at all;
- a new turn on it, or on a route sharing its quota (harnesses.json ``gateway_quotas`` shared: another route with the
  same key), fails before it starts (app/runs.py), and a turn that failed on it says so (``failure_words``): every model
  on the quota shares it, when it is back, and where to go instead (``gateway_quotas`` instead);
- a lead handing work to a topic on it is told so instead (app/project_tools.py project_topic_send, ``send_words``).

A turn of a sharing route that fails on the quota holds it too: Codex's error carries the gateway's words
(backends/codex/turn.py). One request RECHECK seconds after the quota was last found spent still goes upstream, so a
quota raised before its reset (extra quota takes effect at once) is seen: a 200 to a request sent after the hold began
ends it, another 403 renews it. Standard library only, besides core/gateways.py and core/state.py.
"""
from __future__ import annotations

import datetime as _dt
import re
import threading
import time
from pathlib import Path

from covey.core import gateways
from covey.core.protocol import RESETS_AT
from covey.core.state import read_json, write_json

FILE = "quota-hold.json"  # In the gateway's own folder of the state directory, beside its relay.log.
RECHECK = 600  # Seconds after the quota was last found spent before one request goes upstream again.
READ_EVERY = 5  # A relay reads the hold at most this often: it answers many requests a turn, the folder may be on NFS.
BEIJING = _dt.timezone(_dt.timedelta(hours=8))  # The reset is said in Beijing time (no daylight saving).
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SAID_CHARS = 300
PAREN_END = re.compile(r"\s*(?:（[^（）]*）|\([^()]*\))$")  # A display name's trailing gloss: 某线路（Route）.
ASCII_EDGE = re.compile(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z])|(?<=[A-Za-z/])(?=[\u4e00-\u9fff])")  # 或Claude -> 或 Claude.


def path(state_dir, gateway) -> Path:
    return Path(state_dir) / gateway.name / FILE


def reset_of(message):
    """Epoch seconds of the reset a spent quota's ``message`` says, or None."""
    found = RESETS_AT.search(str(message or ""))
    try:
        return _dt.datetime.fromisoformat(found[1].replace("Z", "+00:00")).timestamp() if found else None
    except ValueError:
        return None


def said(message):
    """The upstream's words for the record: one line, emails masked, at most SAID_CHARS."""
    return EMAIL.sub("<email>", " ".join(str(message or "").split()))[:SAID_CHARS]


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _record(state_dir, gateway):
    """The saved hold as it is, over or not; None when there is none or it cannot be read."""
    try:
        record = read_json(path(state_dir, gateway))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not all(_number(record.get(k)) for k in ("reset_at", "seen_at", "checked_at")):
        return None
    return record


def read(state_dir, gateway, now=None):
    """``gateway``'s hold, or None: none, unreadable, or over (its reset has come)."""
    record = _record(state_dir, gateway)
    now = time.time() if now is None else now
    return record if record is not None and record["reset_at"] > now else None


def note(state_dir, gateway, message, now=None):
    """Hold ``gateway`` until the reset its spent quota's ``message`` says: the record, or None when it says none (or
    one already past). Every note restarts the RECHECK wait."""
    now = time.time() if now is None else now
    reset = reset_of(message)
    if reset is None or reset <= now:
        return None
    record = {"reset_at": reset, "seen_at": now, "checked_at": now, "said": said(message)}
    write_json(path(state_dir, gateway), record, ensure_ascii=False)
    return record


def clear(state_dir, gateway, sent_at) -> bool:
    """End ``gateway``'s hold: a request sent at ``sent_at``, after the hold began, was answered, so the quota is back.
    False when there was none to end (or the request was sent before it began, its answer saying nothing of now)."""
    record = _record(state_dir, gateway)
    if record is None or sent_at <= record["seen_at"]:
        return False
    try:
        path(state_dir, gateway).unlink()
    except FileNotFoundError:
        return False
    return True


def claim(state_dir, gateway, now=None):
    """For the relay: (the hold as saved now, whether this request goes upstream). It goes when there is no hold, or
    as the first request RECHECK after the quota was last found spent: the hold then says so, so the others still wait."""
    now = time.time() if now is None else now
    record = read(state_dir, gateway, now)
    if record is None:
        return None, True
    if now - record["checked_at"] < RECHECK:
        return record, False
    record = {**record, "checked_at": now}
    write_json(path(state_dir, gateway), record, ensure_ascii=False)
    return record, True


def held(state_dir, harness, model, now=None):
    """(gateway, hold) of the quota a turn of ``harness`` on ``model`` draws on while it is held, else None."""
    gateway = gateways.quota_gateway(harness, model)
    record = read(state_dir, gateway, now) if gateway is not None else None
    return (gateway, record) if record is not None else None


def blocks(state_dir, harness, model, now=None):
    """``held``, when a new turn is to fail before it starts: the quota was found spent less than RECHECK ago. Past
    that the turn starts, and its first request (the relay's ``claim``) or its failure checks the quota again."""
    now = time.time() if now is None else now
    found = held(state_dir, harness, model, now)
    return found if found is not None and now - found[1]["checked_at"] < RECHECK else None


def note_failure(state_dir, harness, model, message, provider=""):
    """A turn that failed on a spent quota, in its Harness's ``message``: hold the gateway it drew on, the one named
    ``provider`` (a gateway turn's, whose model has lost its prefix) or the one its model shares a quota with."""
    gateway = (gateways.named(provider) if provider else None) or gateways.quota_gateway(harness, model)
    if gateway is None or not gateway.quota_text(message):
        return None
    return note(state_dir, gateway, message)


class Hold:
    """One gateway's hold as its relay uses it, read again at most every READ_EVERY seconds. A record that cannot be
    written (OSError) never stops a request: it then goes upstream, or is answered, as if there were no record."""

    def __init__(self, state_dir, gateway, read_every=READ_EVERY):
        self.state_dir, self.gateway, self.read_every = state_dir, gateway, read_every
        self.lock = threading.Lock()
        self.cached, self.read_at = None, None

    def spent(self, message) -> bool:
        return self.gateway.quota_text(message)

    def _current(self, now):
        if self.read_at is None or now - self.read_at >= self.read_every:
            self.cached, self.read_at = read(self.state_dir, self.gateway, now), now
        elif self.cached is not None and self.cached["reset_at"] <= now:
            self.cached = None
        return self.cached

    def claim(self):
        """The hold to answer a request with here, or None to send it upstream (``claim``)."""
        with self.lock:
            now = time.time()
            record = self._current(now)
            if record is None:
                return None
            if now - record["checked_at"] < RECHECK:
                return record
            try:
                (self.cached, go), self.read_at = claim(self.state_dir, self.gateway, now), now
            except OSError:
                return None
            return None if go else self.cached

    def note(self, message):
        with self.lock:
            try:
                self.cached = note(self.state_dir, self.gateway, message)
            except OSError:
                self.cached = None
            self.read_at = time.time()
            return self.cached

    def clear(self, sent_at) -> bool:
        """After a 200: end the hold when the request was sent after it began. Reads nothing when none is known."""
        with self.lock:
            try:
                if self._current(time.time()) is None or not clear(self.state_dir, self.gateway, sent_at):
                    return False
            except OSError:
                return False
            self.cached = None
            return True


def clock(reset_at, now=None):
    """When the quota is back, in Beijing time: "北京时间 18:00", with the date when it is another day."""
    now = time.time() if now is None else now
    when = _dt.datetime.fromtimestamp(reset_at, BEIJING)
    same_day = when.date() == _dt.datetime.fromtimestamp(now, BEIJING).date()
    return "北京时间 " + when.strftime("%H:%M" if same_day else "%m-%d %H:%M")


def routes(gateway):
    """The model prefixes on ``gateway``'s quota: its own (a Codex gateway's) and the routes sharing it."""
    own = (gateway.prefix,) if gateway.prefix else ()
    return own + tuple(p for p in gateways.quota_share(gateway.name).shared if p not in own)


def instead_words(gateway, catalog):
    """Where to go instead, from ``gateway_quotas`` instead, named as Codex's model ``catalog`` (slug -> row) names
    them; a prefix the catalog has no model of is left out. "" when there is none."""
    names = []
    for item in gateways.quota_share(gateway.name).instead:
        if item == "":
            if any("/" not in slug for slug in catalog):
                names.append("Codex 账号的模型（不带前缀）")
        elif item.endswith("/"):
            row = next((row for slug, row in catalog.items() if slug.startswith(item)), None)
            if row is not None:
                display = str((row or {}).get("display_name") or "")
                # "Model · route" names its route after the last " · ", "Model · 某线路（Route）" with a gloss.
                name = PAREN_END.sub("", display.rsplit(" · ", 1)[1]).strip() if " · " in display else ""
                same = name.lower().replace(" ", "") == item.rstrip("/").lower()
                names.append(f"{name}（{item}）" if name and not same else item)
        elif item.strip():
            names.append(item.strip())
    text = "、".join(names[:-1]) + "或" + names[-1] if len(names) > 1 else "".join(names)
    return ASCII_EDGE.sub(" ", text)


def _catalog(catalog):
    if catalog is not None:
        return catalog
    from covey.core.model_settings import model_catalog  # Here: only a held quota's words read Codex's directory.
    return model_catalog()


def failure_words(gateway, record, now=None, catalog=None):
    """A turn's failure on ``gateway``'s spent quota (core/failure.py shows it as the card's line): when it is back
    (``record``, the hold; None when no reset is known), that every model on it shares it, and where to go instead."""
    name = gateway.display
    when = f"{clock(record['reset_at'], now)} 恢复" if record else "恢复时间不知道"
    lines = "、".join(routes(gateway))
    useless = f"换 {lines} 下的别的模型也没用" if lines else "换它的别的模型也没用"
    instead = instead_words(gateway, _catalog(catalog))
    go = ASCII_EDGE.sub(" ", f"可以换到{instead}") if instead else f"可以换到不走 {name} 的模型或 Harness"
    return f"{name} 的每日额度用完了，{when}；{name} 的所有模型共用这一份额度，{useless}，{go}"


def send_words(gateway, record, label, model, now=None, catalog=None):
    """What a lead hears instead of its work going to topic ``label`` on ``model`` while ``gateway``'s quota is held."""
    instead = instead_words(gateway, _catalog(catalog))
    go = ASCII_EDGE.sub(" ", f"换到{instead}") if instead else f"换到不走 {gateway.display} 的模型"
    return (f"没有发给 {label}：它用的 {model} 走 {gateway.display}，{gateway.display} 额度在{clock(record['reset_at'], now)}"
            f" 恢复（所有模型共用这一份），先换配置：请主人在 {label} 的话题卡上点“🔁 换配置”{go}，"
            "或者用 project_topic_start 开新话题、选这些线路的模型。")
