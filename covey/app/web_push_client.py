"""网页工作台同步的客户端 (app/web_sync.py): the page's /openapi over HTTP (``Client``, ``WebError``); the thread a push step runs in, left
behind when it is stuck, is core/loops.py ``Worker``. No records are read here.

- What the page says it takes (data contract v44, ``limits`` in its answers) is kept, and the batches and images are as large as that
  allows (``Client.batch_bytes``, ``Client.image_bytes``); a page that says nothing gets what it got before.
- Requests to an https:// page (on the full-stack app platform, behind Feishu's gateway: about 10 a second a key, then 429 with no Retry-After, T874) go through
  one ``Gate`` for all the threads of a Client: RATE a second, BURST at once; after a 429 every thread waits COOL_SECONDS. A request
  waits WAIT_MOST seconds at most and then goes anyway. A page on this machine's loopback (http://, self-hosted) has no gateway: no gate.
- How fast the way to the page carries a request is measured on each one of RATE_MIN_BYTES or more (``Client.rate``, an average that
  follows the last few), and a batch or an image is no larger than a few seconds of it (core/web_sync.py ``batch_bytes``): through the
  dev machine's proxy 5 MB took 52 s and the quick look took it for stuck (2026-11-27 T876). The config's ``direct`` reaches the page
  without the environment's proxy."""

from __future__ import annotations

import json
import os
import threading
import time

from covey.core import env as cenv
from covey.core import http_upstream, web_sync

TIMEOUT = 20
CHECK_SECONDS = 10  # How often the config file's stat is looked at (Client.settings).
RATE, BURST = 8.0, 10.0  # Requests a second to an https:// page, and at once (the gateway lets about 10 a second through, T874).
COOL_SECONDS = 1.5  # After a 429 no request goes for this long.
WAIT_MOST = 2.0  # A request waits for the gate this long at most, then goes anyway: the gate paces, it never stops the push.
RATE_MIN_BYTES = 200_000  # A request this large or larger tells how fast the way to the page carries one (Client.rate).
RATE_WEIGHT = 0.5  # Of each new measurement in the average.


def config_stamp():
    """The stat of the config file COVEY_WEB_CONFIG names; None when it cannot be had."""
    path = str(cenv.get(web_sync.CONFIG_ENV, "") or "").strip()
    try:
        stat = os.stat(path) if path else None
    except OSError:
        return None
    return (stat.st_ino, stat.st_mtime_ns, stat.st_size) if stat else None


class WebError(Exception):
    """A request the page did not take: its HTTP status, or the connection."""

    def __init__(self, text, status=0) -> None:
        super().__init__(text)
        self.status = status


class Gate:
    """A token bucket shared by the threads of one Client: ``take`` waits until a request may go (WAIT_MOST at most), ``cool`` holds
    every request back COOL_SECONDS after the page's gateway said 429. ``clock`` and ``sleep`` are time's, tests pass their own."""

    def __init__(self, rate=RATE, burst=BURST, clock=time.monotonic, sleep=time.sleep) -> None:
        self.rate, self.burst, self.clock, self.sleep = rate, burst, clock, sleep
        self.lock = threading.Lock()
        self.tokens, self.at = burst, clock()  # ``at``: tokens are counted up to it; later than now while cooling.

    def take(self, most=WAIT_MOST) -> float:
        """Wait for a token, ``most`` seconds at most (then go without one, leaving a debt of at most a burst); the seconds waited."""
        began = self.clock()
        while True:
            with self.lock:
                now = self.clock()
                if now > self.at:
                    self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
                    self.at = now
                if now >= self.at and self.tokens >= 1:
                    self.tokens -= 1
                    return now - began
                left = most - (now - began)
                if left <= 0:
                    self.tokens = max(self.tokens - 1, -self.burst)
                    return now - began
                wait = max(self.at - now, 0.0) + max(1 - self.tokens, 0.0) / self.rate
            self.sleep(min(wait, left))

    def cool(self, seconds=COOL_SECONDS) -> None:
        """The gateway said 429: no request for ``seconds``, then the tokens come back from none."""
        with self.lock:
            self.at = max(self.at, self.clock() + seconds)
            self.tokens = 0.0


class Client:
    """The page's /openapi, with the key of the config's key_file. The config is read again when its file changed (a stat at most
    every CHECK_SECONDS) or the page refused a request (a replaced key, a fixed address), not opened again every 10 seconds:
    an NFS open that hung held the push for minutes (2026-11-23 T673)."""

    def __init__(self, gate=None) -> None:
        self.opener = http_upstream.opener()  # http:// (a self-hosted page on loopback): a request a connection, as before.
        self.kept = http_upstream.KeepAlive()  # https://: one kept connection per thread (2026-11-25 T765: 203 -> 137 ms a request).
        self.kept_direct = http_upstream.KeepAlive(direct=True)  # https:// with the config's ``direct``: not through the proxy.
        self.loaded, self.config, self.stamp = 0.0, None, None
        self.gate = gate or Gate()  # https:// requests only.
        self.limits_lock, self.limits = threading.Lock(), None  # What the page last said it takes (web_sync.limits_of); None: nothing.
        self.rate = None  # Bytes a second a large request to the page went at (RATE_MIN_BYTES); None: not measured yet.

    def settings(self) -> web_sync.Config:
        now = time.monotonic()
        if self.config is None or now - self.loaded > CHECK_SECONDS:
            stamp = config_stamp()
            if self.config is None or stamp != self.stamp:
                old = self.config
                self.config, self.stamp = web_sync.load_config(), stamp
                if old is not None and (old.base_url != self.config.base_url or old.direct != self.config.direct):
                    with self.limits_lock:
                        self.limits = None  # Another page: what the old one took says nothing of it.
                        self.rate = None  # Another way to it: measured again.
            self.loaded = now
        return self.config

    def batch_bytes(self) -> int:
        """The bytes of one batch of items to this page (core/web_sync.py ``batch_bytes``)."""
        with self.limits_lock:
            return web_sync.batch_bytes(self.limits, self.rate)

    def image_bytes(self) -> int:
        """The bytes of one encoded image to this page (core/web_sync.py ``image_bytes``)."""
        with self.limits_lock:
            return web_sync.image_bytes(self.limits, self.rate)

    def measured(self, size, seconds) -> None:
        """A request of ``size`` bytes took ``seconds`` there and back: into the average rate (the page's own time is in it, so the
        rate is what a request takes as a whole, which is what a batch is sized by)."""
        now = size / max(seconds, 0.05)
        with self.limits_lock:
            self.rate = now if self.rate is None else self.rate + RATE_WEIGHT * (now - self.rate)

    def known(self, name, default):
        """The config's ``name`` (push_seconds, poll_seconds) as last read, ``default`` before the first read: no file is touched,
        for the loops' own threads, which no stuck check watches (WebSync.loop)."""
        return getattr(self.config, name, default) if self.config is not None else default

    def request(self, method, path, body=None) -> dict:
        try:
            config = self.settings()
        except ValueError as exc:
            raise WebError(f"config: {exc}") from None
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        headers = {"Authorization": "Bearer " + config.key, **({"Content-Type": "application/json"} if data is not None else {})}
        url = config.base_url + path
        large = data is not None and len(data) >= RATE_MIN_BYTES
        if url.startswith("https://"):
            self.gate.take()
        began = time.monotonic()  # After the gate: only the request itself is timed.
        try:
            if url.startswith("https://"):
                status, raw = (self.kept_direct if config.direct else self.kept).send(method, url, data, headers, TIMEOUT)
            else:
                status, response = http_upstream.send(self.opener, method, url, data, headers, TIMEOUT)
                raw = response.read()
        except OSError as exc:
            if large:  # A large request that timed out or broke: it took at least this long, so the way is at most this fast.
                self.measured(len(data), time.monotonic() - began)
            raise WebError(type(exc).__name__) from None
        if large and status < 300:
            self.measured(len(data), time.monotonic() - began)
        if status == 429 and url.startswith("https://"):
            self.gate.cool()  # Every thread of this client holds back a moment; the caller's loop still backs off as for any failure.
        if status >= 300:
            self.loaded, self.stamp = 0.0, None  # The config or its key may have been fixed meanwhile: read it again.
            raise WebError(f"http {status}", status)
        try:
            value = json.loads(raw or b"{}")
        except ValueError:
            raise WebError("answer is not JSON", status) from None
        value = value if isinstance(value, dict) else {}
        limits = web_sync.limits_of(value)
        if limits is not None:
            with self.limits_lock:
                self.limits = limits
        return value
