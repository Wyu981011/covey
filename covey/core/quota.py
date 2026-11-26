"""额度快照 (docs/quota.md): every quota source (agy's accounts, the gateway Claude Code signs in to, a command or an
address the owner names) gives Covey one JSON of the same shape (format 1); the 账号与额度 page, the reminders, the
failure cards and the retry times read it and nothing else. Pure functions and the files under ``<state>/quota/``;
standard library only (backends read it).

- ``parse(data)``: a snapshot as a source gave it, checked and kept to the fields the format names (others dropped), its
  texts scrubbed (``scrub``: an e-mail, an address, a path, an IP or a key-like run becomes …): ValueError says why not.
  Whether an account can be used and when it can again are the source's to say (``state``, ``available_at``: a gateway
  has per-key reserves and exclusions); Covey never works it out from a percentage.
- ``Store(state_dir)``: one file a source, ``<state>/quota/<source>.json`` {source, kind, title, snapshot, read_at,
  ok_at, error, absent}. A failed read keeps the last snapshot and says why (``failed``): the page marks it 读数过旧,
  never 0.
- ``freshness``: FRESH within the snapshot's ``ttl``, STALE within twice it, OLD beyond (no figures shown then).
- ``pool``: how many accounts of a snapshot can be used, of how many, and when one can again when none can;
  ``none_signed_in``: none can, and none will by itself (each needs a sign-in, has expired or is paused).
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

from covey.core.state import ensure_private_dir, read_json, write_json

SCHEMA = 1
FOLDER = "quota"  # Under the state directory.
MAX_BYTES = 64 * 1024  # A snapshot as the source gives it.
MAX_ACCOUNTS, MAX_WINDOWS = 50, 8
TITLE_CHARS, ALIAS_CHARS, LABEL_CHARS = 20, 20, 12
MIN_TTL, MAX_TTL = 30, 7 * 86400
OK, SPENT, COOLING, PAUSED, LOGIN, EXPIRED, UNKNOWN = ("ok", "spent", "cooling", "paused", "login_required", "expired",
                                                       "unknown")
STATES = (OK, SPENT, COOLING, PAUSED, LOGIN, EXPIRED, UNKNOWN)
# States that end by themselves at ``available_at``; the others wait on someone (a sign-in, a renewal, the owner).
WAITING = (SPENT, COOLING, UNKNOWN)
WINDOW_KINDS = ("5h", "7d", "day", "other")
SOURCE_KINDS = ("agy", "gateway", "command", "url")
FRESH, STALE, OLD, NONE = "fresh", "stale", "old", "none"
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}")
CUT = "…"
# What may not leave a source's texts (QUOTA-FORMAT: no e-mail, IP, address, key or token), in the order replaced.
SCRUB = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # An e-mail (an agy account named after one).
    re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I),  # An address.
    re.compile(r"(?:~|\.{0,2})/[\w.@-]+(?:/[\w.@-]*)+"),  # A path of two parts or more.
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"),  # An IPv4 address.
    re.compile(r"\b[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){3,}\b", re.I),  # An IPv6 one.
    re.compile(r"\b(?:sk|ak|pk|key|tok|token)[-_][\w-]{6,}", re.I),  # A key's or a token's spelling.
    re.compile(r"[A-Za-z0-9_+/=-]{24,}"),  # Any long run a key or an id would be.
)


def scrub(text, limit) -> str:
    """``text`` with what may not leave a source replaced by CUT (SCRUB), on one line, at most ``limit`` characters."""
    text = " ".join(str(text or "").split())
    for pattern in SCRUB:
        text = pattern.sub(CUT, text)
    text = re.sub(re.escape(CUT) + r"(?:\s*" + re.escape(CUT) + ")+", CUT, text)
    return text[:limit].strip()


def _time(value, what):
    """Epoch seconds of ``value`` (a number; None for none); ValueError for anything else."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{what} 要是 epoch 秒")
    return float(value) or None


def _fraction(value, what):
    """A fraction 0..1 (clamped), None for none (a window not read: never 0); ValueError for anything else."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} 要是 0 到 1 的数")
    return min(1.0, max(0.0, float(value)))


def _window(row, where) -> dict:
    if not isinstance(row, dict):
        raise ValueError(f"{where} 要是对象")
    kind = row.get("kind")
    if not isinstance(kind, str):
        raise ValueError(f"{where}.kind 缺了")
    if "used" not in row:
        raise ValueError(f"{where}.used 缺了（读不到写 null，不要写 0）")
    window = {"kind": kind if kind in WINDOW_KINDS else "other",
              "used": _fraction(row.get("used"), f"{where}.used")}
    label = scrub(row.get("label"), LABEL_CHARS) if row.get("label") is not None else ""
    if label:
        window["label"] = label
    for key in ("resets_at", "checked_at"):
        at = _time(row.get(key), f"{where}.{key}")
        if at:
            window[key] = at
    ceiling = _fraction(row.get("ceiling"), f"{where}.ceiling")
    if ceiling is not None:
        window["ceiling"] = ceiling
    return window


def _account(row, number) -> dict:
    where = f"accounts[{number}]"
    if not isinstance(row, dict):
        raise ValueError(f"{where} 要是对象")
    alias = scrub(row.get("alias"), ALIAS_CHARS)
    if not alias or alias == CUT:
        raise ValueError(f"{where}.alias 缺了，或只有不能显示的内容（邮箱、地址、密钥）")
    state = row.get("state")
    if state not in STATES:
        raise ValueError(f"{where}.state 要是 {'、'.join(STATES)} 之一")
    windows = row.get("windows", [])
    if not isinstance(windows, list) or len(windows) > MAX_WINDOWS:
        raise ValueError(f"{where}.windows 要是不超过 {MAX_WINDOWS} 个的列表")
    account = {"alias": alias, "state": state,
               "available_at": None if state == OK else _time(row.get("available_at"), f"{where}.available_at"),
               "windows": [_window(w, f"{where}.windows[{n}]") for n, w in enumerate(windows)]}
    if row.get("active") is True:
        account["active"] = True
    expires = _time(row.get("expires_at"), f"{where}.expires_at")
    if expires:
        account["expires_at"] = expires
    return account


def _pool(row) -> dict | None:
    if row is None:
        return None
    if not isinstance(row, dict):
        raise ValueError("pool 要是对象")
    counts = {}
    for key in ("usable", "total"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"pool.{key} 要是非负整数")
        counts[key] = value
    return {**counts, "next_available_at": _time(row.get("next_available_at"), "pool.next_available_at")}


def link_ok(url) -> bool:
    url = str(url or "")
    return url.startswith("https://") and len(url) <= 300 and not any(ch.isspace() for ch in url)


def parse(data) -> dict:
    """The snapshot in ``data`` (the source's JSON, decoded), as Covey keeps it; ValueError says why it is not one."""
    if not isinstance(data, dict):
        raise ValueError("快照要是 JSON 对象")
    if data.get("schema") != SCHEMA:
        raise ValueError(f"schema 要是 {SCHEMA}")
    collected = _time(data.get("collected_at"), "collected_at")
    if not collected:
        raise ValueError("collected_at 缺了")
    ttl = data.get("ttl")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
        raise ValueError("ttl 要是正数（秒）")
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        raise ValueError("accounts 要是列表")
    if len(accounts) > MAX_ACCOUNTS:
        raise ValueError(f"号不能超过 {MAX_ACCOUNTS} 个")
    snapshot = {"schema": SCHEMA, "collected_at": collected, "ttl": min(MAX_TTL, max(MIN_TTL, float(ttl))),
                "accounts": [_account(row, n) for n, row in enumerate(accounts)]}
    title = scrub(data.get("title"), TITLE_CHARS) if data.get("title") is not None else ""
    if title and title != CUT:
        snapshot["title"] = title
    pool = _pool(data.get("pool"))
    if pool is not None:
        snapshot["pool"] = pool
    if data.get("link") is not None and link_ok(data.get("link")):
        snapshot["link"] = str(data["link"])
    return snapshot


def freshness(snapshot, now=None) -> str:
    """FRESH, STALE or OLD as the snapshot's ``ttl`` says of its age; NONE without one."""
    if not isinstance(snapshot, dict) or not snapshot.get("collected_at"):
        return NONE
    age = (time.time() if now is None else now) - float(snapshot["collected_at"])
    ttl = float(snapshot.get("ttl") or MIN_TTL)
    return FRESH if age <= ttl else STALE if age <= 2 * ttl else OLD


def pool(snapshot) -> dict:
    """{usable, total, next_available_at}: the source's ``pool`` when it gave one, else counted from its accounts (the
    earliest ``available_at`` of those that come back by themselves, when none can be used)."""
    given = snapshot.get("pool") if isinstance(snapshot, dict) else None
    if isinstance(given, dict):
        return dict(given)
    accounts = snapshot.get("accounts") or [] if isinstance(snapshot, dict) else []
    usable = sum(1 for a in accounts if a.get("state") == OK)
    times = [a["available_at"] for a in accounts if a.get("state") in WAITING and a.get("available_at")]
    return {"usable": usable, "total": len(accounts), "next_available_at": min(times) if times and not usable else None}


def none_signed_in(snapshot) -> bool:
    """Whether no account of ``snapshot`` can be used and none will be by itself: each needs a sign-in, has expired or is
    paused (a gateway's 503 no_account: no retry helps until its owner sees to it)."""
    accounts = snapshot.get("accounts") or [] if isinstance(snapshot, dict) else []
    return bool(accounts) and all(a.get("state") in (LOGIN, EXPIRED, PAUSED) for a in accounts)


class Store:
    """``<state>/quota/``: one file a source (see the module docstring)."""

    def __init__(self, state_dir):
        self.folder = Path(state_dir) / FOLDER

    def path(self, source) -> Path:
        if not SOURCE_ID.fullmatch(str(source or "")):
            raise ValueError(f"来源 id 不对：{source!r}")
        return self.folder / f"{source}.json"

    def read(self, source) -> dict:
        try:
            entry = read_json(self.path(source), {})
        except (OSError, ValueError):
            return {}
        return entry if isinstance(entry, dict) else {}

    def entries(self) -> list:
        """Every source's entry, by its id."""
        try:
            names = sorted(p.stem for p in self.folder.glob("*.json"))
        except OSError:
            return []
        found = []
        for name in names:
            entry = self.read(name) if SOURCE_ID.fullmatch(name) else {}
            if entry.get("source") == name:
                found.append(entry)
        return found

    def _write(self, source, entry) -> dict:
        ensure_private_dir(self.folder)
        write_json(self.path(source), entry, ensure_ascii=False, indent=1)
        return entry

    def saved(self, source, kind, snapshot, *, title="", now=None, **extra) -> dict:
        """Keep ``snapshot`` (parsed) as ``source``'s latest; the entry as written."""
        now = time.time() if now is None else now
        entry = {"source": source, "kind": kind, "title": title or snapshot.get("title") or "", "snapshot": snapshot,
                 "read_at": now, "ok_at": now, "error": "", "absent": False, **extra}
        return self._write(source, entry)

    def failed(self, source, kind, why, *, title="", absent=False, now=None, **extra) -> dict:
        """A read of ``source`` that gave no snapshot: the last one stays, with ``why`` (no secret in it)."""
        now = time.time() if now is None else now
        entry = {**self.read(source), "source": source, "kind": kind, "read_at": now,
                 "error": scrub(why, 120), "absent": bool(absent), **extra}
        entry.setdefault("snapshot", None)
        entry.setdefault("ok_at", 0)
        if title:
            entry["title"] = title
        return self._write(source, entry)

    def forget(self, source) -> None:
        try:
            self.path(source).unlink()
        except (OSError, ValueError):
            pass
