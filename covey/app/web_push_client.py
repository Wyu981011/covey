"""网页工作台同步的客户端 (app/web_sync.py): the page's /openapi over HTTP (``Client``, ``WebError``) and the thread a push step runs in, left behind when it
is stuck (``Worker``, ``Stuck``). No records are read here."""

from __future__ import annotations

import json
import os
import queue
import threading
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


class Stuck(Exception):
    """A step that did not end within its time."""


class Worker:
    """A thread that runs the steps it is handed, one at a time. A step stuck in a system call is left to it: the caller hands the
    next steps to a new Worker, and this thread ends when the stuck step does."""

    def __init__(self, name) -> None:
        self.steps, self.ends = queue.Queue(), queue.Queue()
        self.thread = threading.Thread(target=self.run, name=name, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while True:
            step = self.steps.get()
            if step is None:
                return
            try:
                self.ends.put((step(), None))
            except Exception as exc:  # noqa: BLE001 - raised in the caller's thread
                self.ends.put((None, exc))

    def call(self, step, seconds, moved=None):
        """``step``'s value (its exception is raised here). Stuck when it has not ended ``seconds`` after it began, or, with ``moved`` (the
        monotonic time of the step's last progress), ``seconds`` after its last progress: a long first push that keeps sending is not stuck."""
        self.steps.put(step)
        last = time.monotonic()
        while True:
            try:
                value, exc = self.ends.get(timeout=max(0.0, last + seconds - time.monotonic()))
                break
            except queue.Empty:
                newer = moved() if moved is not None else 0.0
                if newer <= last:
                    self.steps.put(None)
                    raise Stuck from None
                last = newer
        if exc is not None:
            raise exc
        return value


class Client:
    """The page's /openapi, with the key of the config's key_file. The config is read again when its file changed (a stat at most
    every CHECK_SECONDS) or the page refused a request (a replaced key, a fixed address), not opened again every 10 seconds:
    an NFS open that hung held the push for minutes (2026-11-23 T673)."""

    def __init__(self) -> None:
        self.opener = http_upstream.opener()
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
        try:
            status, response = http_upstream.send(self.opener, method, config.base_url + path, data, headers, TIMEOUT)
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
