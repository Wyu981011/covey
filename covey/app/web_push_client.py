"""网页工作台同步的客户端 (app/web_sync.py): the page's /openapi over HTTP (``Client``, ``WebError``); the thread a push step runs in, left
behind when it is stuck, is core/loops.py ``Worker``. No records are read here."""

from __future__ import annotations

import json
import os
import time

from covey.core import env as cenv
from covey.core import http_upstream, web_sync

TIMEOUT = 20
CHECK_SECONDS = 10  # How often the config file's stat is looked at (Client.settings).


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


class Client:
    """The page's /openapi, with the key of the config's key_file. The config is read again when its file changed (a stat at most
    every CHECK_SECONDS) or the page refused a request (a replaced key, a fixed address), not opened again every 10 seconds:
    an NFS open that hung held the push for minutes (2026-11-23 T673)."""

    def __init__(self) -> None:
        self.opener = http_upstream.opener()  # http:// (a self-hosted page on loopback): a request a connection, as before.
        self.kept = http_upstream.KeepAlive()  # https://: one kept connection per thread (2026-11-25 T765: 203 -> 137 ms a request).
        self.loaded, self.config, self.stamp = 0.0, None, None

    def settings(self) -> web_sync.Config:
        now = time.monotonic()
        if self.config is None or now - self.loaded > CHECK_SECONDS:
            stamp = config_stamp()
            if self.config is None or stamp != self.stamp:
                self.config, self.stamp = web_sync.load_config(), stamp
            self.loaded = now
        return self.config

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
        try:
            if url.startswith("https://"):
                status, raw = self.kept.send(method, url, data, headers, TIMEOUT)
            else:
                status, response = http_upstream.send(self.opener, method, url, data, headers, TIMEOUT)
                raw = response.read()
        except OSError as exc:
            raise WebError(type(exc).__name__) from None
        if status >= 300:
            self.loaded, self.stamp = 0.0, None  # The config or its key may have been fixed meanwhile: read it again.
            raise WebError(f"http {status}", status)
        try:
            value = json.loads(raw or b"{}")
        except ValueError:
            raise WebError("answer is not JSON", status) from None
        return value if isinstance(value, dict) else {}
