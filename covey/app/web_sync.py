"""网页工作台同步 (docs/web.md, COVEY_WEB=1 and COVEY_WEB_CONFIG): pushes the state of the owner's projects, topics, turns and
questions to the web page (网页应用) and fetches what the page sent, which app/web_ops.py does. Off by default: without the switch
there is no thread and no request.

- ``WebSync`` (app/unified.py PARTS ``web_sync``, a feature object: ``threads()``, none without the switch): three supervised threads.
  ``web-push`` (the quick looks, ``push_hot``) builds the hot items (``Collector.collect_hot``, app/web_collect.py), keeps those whose ``rev``
  (core/web_sync.py) differs from what was sent, and posts them to /sync/upsert in batches, then a batch of what the pass read; ``web-pass``
  (``pass_once``) reads the full pass a slice a step into that backlog; ``web-inbox`` asks /sync/inbox, writes each operation's seq and op_id
  into the ledger before it is done, does it (``Ops.run``) and acknowledges it at /sync/ack. A failed request backs off (2, 4 ... 30 seconds)
  and touches no other thread.
- What is read, and how often: every ``push_seconds``, and at once when this process wrote a job or a question (core/store.py listen: an
  answer on a card), only the running tasks, the pending questions and the tasks waiting for 开始 on a launch card (three index queries, the
  records they name; core/board_read.py starts), plus the topics that stopped running a moment ago or that the page just acted on, and the
  projects that changed; FULL_SECONDS after the last pass ended a full pass of all topics of the last TOPIC_DAYS days, PASS_SLICE of them a
  step in its own thread (2026-11-23 T673: in the one push thread a pass's read stuck on the network disk held the hot topics up a minute at
  a time), the deletions once it ends. Each topic's read has a seq: a read older than what the page has of a topic is never sent after it.
  A topic's state and "做完没看" are the board's reading (core/board_read.py, app/pins.py
  board_results), not a scan of every job record each second. The butler's conversation (core/butler.py butler_topic_id; the other tracks
  of the family and the leads are not) is one more topic item, ``kind`` "butler", number 0, title 管家, no project, never unseen: its
  turns are its history's (the owner's top-level words, the butler's answers), looked at while its task runs, after an operation of the page
  touched it and in the full look. A running turn's body is its progress notes as the trace file has them, each time it changes.
- A project's lead (COVEY_PROJECTS=1) is looked at the same way and is a topic of ``kind`` "lead" (title 负责人, number 0, its project's id as
  ``project_key``): the owner's words and its answers, a wake-up turn left out (its reply only when the lead meant it for the owner), and
  a line of the page's own (role event) for a member's end and for what a silent wake-up started; ``started_topics`` says which turn started
  which member. A turn's process, plan and figures (app/web_turns.py) and a question's times ride on the items; the memory and library rows
  say who wrote them (data contract v3).
- The key is read from the config's key_file and appears in no log line and no record.

Rule 1 (AGENTS.md): no lock is held across a request; records are read, not locked."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from covey.app import web_images
from covey.app.web_collect import Collector, Shared
from covey.app.web_ops import Ops
from covey.app.web_push_client import Client, Stuck, WebError, Worker
from covey.core import avatars, store, web_sync
from covey.core.state import read_object, write_json

FULL_SECONDS = web_sync.FULL_SECONDS  # A full pass starts this long after the last one ended (its own thread reads it a slice a step).
STEP_BYTES = web_sync.BATCH_BYTES  # What a quick look sends of the pass's items (the backlog) after its own: one batch.
SENT_FILE = "sent.json"  # <state>/web/: what the page took (key -> rev), so a restart sends only what changed since.
SENT_SAVE_SECONDS = 30.0  # It is written at most this often, and when a pass ends.
SENT_KEEP_SECONDS = 86400.0  # Once a day ``sent`` starts empty again, so everything goes once (a page whose database was emptied fills again).
MAX_BACKOFF = 30
STUCK_SECONDS = 60  # A step with no progress in this long is left behind (an NFS read can hold its thread for good); the next runs in a new thread.
# The quick look's own limit: what runs, asks or just ended waits no longer than this for a read stuck on the network disk
# (2026-11-23 T673: an open of a running topic's topic.json held its thread over 2 minutes while other processes read the file in 5 ms).
HOT_STUCK_SECONDS = 15
HOT_WAIT = 5.0  # Seconds a quick look waits for a store's lock (core/store.py bounded) before it gives its step up: another thread's scan may be stuck.
HOT_GAP = 0.25  # The least time between two quick looks, however often this process writes a record.
PASS_PAUSE = 1.0  # Seconds between two steps of a pass (each a slice of PASS_SLICE topics), and between two checks whether one is due.
BUSY_EVERY = 60  # A quick look given up for a busy store is logged the first time, then every this many.
MAX_LEFT = 3  # Left-behind steps still stuck: with this many no new thread is started until one of them ends, or LEFT_WAIT has passed.
LEFT_WAIT = 300  # Seconds waited at MAX_LEFT; then the next step runs in a new thread anyway (an open stuck for good must not stop the push).
IMAGES_WAIT = 300  # Seconds images are held back after the page did not take one (push_images).


class WebSync:
    """The feature object (``threads()``). ``runtime``: app/runtime.py Runtime; ``env``: app/butler_env.py ButlerEnv; ``hear``: app/unified.py
    web_message, how the owner's words to the butler get in (None: none can); ``login``: app/web_login.py WebLogin, which the ``login`` operation hands its card to (None: it is ``failed``)."""
    name = "web-sync"

    def __init__(self, runtime, env, hear=None, login=None) -> None:
        self.runtime, self.env = runtime, env
        self.client = Client()
        self.shared = Shared()  # The caches and what the page has, shared by the two collectors and kept by a new one (start_over).
        self.images = None  # web_images.WebImages, made once the state directory is known (images_ready)
        self.collector = Collector(env, None, runtime.log, shared=self.shared)  # The quick looks' (push_hot).
        self.passer = Collector(env, None, runtime.log, shared=self.shared)  # The pass's (pass_once).
        self.images_ready()
        self.ops = Ops(env, hear, fetch=self.client.request, login=login)
        self.sent = {}  # (type, key) -> the rev pushed last.
        # (type, key) -> (item, whose, seq): what a pass read and the page has not got, the newest read of each; sent a batch a quick look.
        self.backlog, self.backlog_lock = {}, threading.Lock()
        # whose (a topic id, "project:<id>", "collab:<id>") -> the seq of its newest read handed to the page: an older read of it is
        # never sent after it (a pass that read a topic before the owner's answer must not put 等你 back on the page).
        self.fresh = {}
        self.deletions = []  # [(seq, [{type, key}])] of the passes that ended, for the next quick look to send.
        self.pass_ended = False  # A pass ended since the last quick look: that one posts, an empty batch too, so 最后同步 moves on.
        self.wake = threading.Event()  # Set when this process wrote a job or a question (core/store.py listen) or the page acted: look now.
        self.busy = 0  # Quick looks given up in a row because a store was busy.
        self.sent_loaded, self.sent_saved, self.sent_changed = False, 0.0, False  # <state>/web/sent.json (load_sent, save_sent).
        self.sent_since = None  # When ``sent`` last started empty (wall clock).
        self.last_full = 0.0
        self.settings_due, self.settings_stamps = True, None  # The 设置 item: built on a full look, after the page changed one, or when its files did.
        self.settings_lock = threading.Lock()  # push_settings runs in both threads.
        self.tidy_stamps, self.tidy_lock, self.tidy_failed = None, threading.Lock(), 0  # The 整理专项 item (push_tidy).
        self.asks_failed, self.asks_tried, self.asks_full = 0, None, False  # The 要你处理 item (push_asks): failures in a row, the rev tried last, a pass began.
        self.ledger = None
        self.down = {}  # thread name -> failures in a row.
        self.images_wait, self.images_down = 0.0, 0  # push_images: no sending before this time; failures in a row.

    @property
    def stuck(self) -> dict:
        return self.shared.stuck

    def threads(self):
        if not web_sync.enabled():
            return ()
        return (("web-push", lambda ctx: self.run_push()),
                ("web-pass", lambda ctx: self.loop("pass", self.pass_once, lambda: PASS_PAUSE, self.start_over_pass,
                                                   lambda: self.passer.moved, where=lambda: self.passer.doing)),
                ("web-inbox", lambda ctx: self.loop("inbox", self.inbox_once, lambda: self.client.settings().poll_seconds, again=True)))

    def run_push(self) -> None:
        """The quick looks' thread: every push_seconds, and at once (HOT_GAP apart at most) when this process wrote a job or a question."""
        store.listen(self.heard)
        try:
            self.loop("push", self.push_hot, lambda: self.client.settings().push_seconds, self.start_over_hot,
                      lambda: self.collector.moved, stuck=HOT_STUCK_SECONDS, wake=self.wake, where=lambda: self.collector.doing)
        finally:
            store.unlisten(self.heard)

    def heard(self, folder, name) -> None:
        """core/store.py listen: this process wrote record ``name`` in ``folder`` (a card's answer, a job's start or end)."""
        if folder in ("jobs", "questions"):
            self.wake.set()

    def loop(self, label, step, seconds, reset=None, moved=None, again=False, stuck=None, wake=None, where=None) -> None:
        """``step`` every ``seconds()``, in a Worker; a failure is logged (the first, then every tenth) and waited out 2, 4 ... MAX_BACKOFF
        seconds. A step with no progress in ``stuck`` seconds (STUCK_SECONDS without; ``moved()``: the monotonic time of its last; without
        it, the step's start) is logged and left behind: ``reset()`` drops what it was building and the next step runs in a new Worker
        (none while MAX_LEFT left-behind ones are still stuck). With ``again``, a step that returned something (the inbox's new operations)
        is followed by the next at once: the page's next click is waiting. With ``wake`` (an Event), setting it ends the wait between two
        steps that went well early, HOT_GAP after the last at the least. ``where()``: what a step left behind was at, for its log line."""
        limit = STUCK_SECONDS if stuck is None else stuck
        worker, left = Worker(f"web-{label}-step"), []
        while not self.runtime.shutdown.is_set():
            backing = False
            try:
                got = worker.call(step, limit, moved)
                if self.down.pop(label, 0):
                    self.runtime.log(f"web sync {label} recovered")
                wait = 0 if again and got else seconds()
            except Stuck:
                left = [each for each in (*left, worker) if each.thread.is_alive()]
                at = f", at: {where() or 'its end'}" if where is not None else ""
                self.runtime.log(f"web sync {label} stuck: a step has not moved in {limit} s{at}; left behind ({len(left)} so far)")
                began = time.monotonic()
                while len(left) >= MAX_LEFT and time.monotonic() - began < LEFT_WAIT and not self.runtime.shutdown.wait(
                        min(limit, LEFT_WAIT)):
                    left = [each for each in left if each.thread.is_alive()]
                if len(left) >= MAX_LEFT:
                    self.runtime.log(f"web sync {label}: {len(left)} left-behind steps still stuck after {LEFT_WAIT} s; going on in a new thread")
                if reset is not None:
                    reset()
                worker, wait = Worker(f"web-{label}-step"), 0
            except Exception as exc:  # noqa: BLE001 - a failing page must not stop anything else
                failed = self.down[label] = self.down.get(label, 0) + 1
                if failed == 1 or failed % 10 == 0:
                    self.runtime.log(f"web sync {label} failed ({failed}): {type(exc).__name__}: {self.why(exc)}")
                wait, backing = min(MAX_BACKOFF, 2 ** min(failed, 5)), True
            if wake is None or backing:
                if self.runtime.shutdown.wait(wait):
                    break
                continue
            ended = time.monotonic()
            wake.wait(wait)
            wake.clear()
            rest = HOT_GAP - (time.monotonic() - ended)
            if self.runtime.shutdown.wait(rest) if rest > 0 else self.runtime.shutdown.is_set():
                break
        worker.steps.put(None)

    @staticmethod
    def why(exc) -> str:
        return str(exc)[:80] if isinstance(exc, (WebError, ValueError)) else ""

    # -- push -----------------------------------------------------------------------------------------------------------

    def leave_out(self, old, label) -> None:
        """The topic ``old`` (a collector left behind) was reading when it got stuck is left out of every look while its thread lives,
        so the next look does not get stuck on it again (an NFS open of its topic.json that never returned, say)."""
        if old.at and old.thread is not None and old.thread.is_alive():
            with self.shared.lock:
                self.shared.stuck[old.at] = old.thread
            self.runtime.log(f"web sync {label} leaves topic {old.at[:12]} out while its read is stuck")

    def start_over_hot(self) -> None:
        """After a quick look was left behind: a new collector for the quick looks. The caches stay (``Shared``): nothing is read again
        that has not changed, and no pass starts for it. The left-behind look writes only to the old collector and sends nothing (one
        that comes back an hour late must not put a topic back to 在做 on the page)."""
        old = self.collector
        self.leave_out(old, "push")
        fresh = Collector(self.env, None, self.runtime.log, self.images, shared=self.shared)
        fresh.hot, fresh.left, fresh.projects_due = set(old.hot), set(old.left), old.projects_due
        self.collector = fresh

    def start_over_pass(self) -> None:
        """After a step of the pass was left behind: a new collector for the pass, which starts a new one at once (the topics of the
        slice it was building were taken off the old pass: a pass that ended without them would delete them from the page). The caches
        stay; the quick looks go on all the while in their own thread."""
        old = self.passer
        old.retired = True
        self.leave_out(old, "pass")
        fresh = Collector(self.env, None, self.runtime.log, self.images, shared=self.shared)
        fresh.backfill = old.backfill or old.backfilling
        self.passer, self.last_full = fresh, 0.0

    def start_over(self) -> None:
        """Both collectors made again (start_over_hot, start_over_pass): ``push_once``'s, which does a step of each in one thread."""
        self.start_over_hot()
        self.start_over_pass()

    def push_once(self, now=None) -> int:
        """A step of the pass and a quick look, one after the other in this thread (the threads run them each in its own): how many
        items went out. Raises WebError when the page did not take a batch (the batches before it count)."""
        self.pass_once(now)
        count = self.push_hot(now)
        self.save_due(now)
        return count

    def push_hot(self, now=None) -> int:
        """One quick look (Collector.collect_hot) and one push: its items that changed, then a batch of what the pass read (the backlog,
        each an item not older than what the page has of its topic), then the deletions of a pass that ended (an empty batch when there
        is nothing else, so the page's 最后同步 moves on in a quiet minute), then 要你处理. How many items went out. A store whose lock
        another thread holds HOT_WAIT seconds (a scan stuck on the network disk) gives the step up: nothing is sent, the next look tries
        again. Raises WebError when the page did not take a batch (the batches before it count)."""
        chat = self.runtime.access.owner_chat()
        if not chat or not self.env.state_dir:
            return 0
        if not self.sent_loaded:
            self.load_sent(now)
        self.images_ready()
        collector, sent = self.collector, self.sent
        now = time.time() if now is None else now
        try:
            with store.bounded(HOT_WAIT):
                items = collector.collect_hot(chat, now)
        except store.Busy as exc:
            self.busy += 1
            if self.busy == 1 or self.busy % BUSY_EVERY == 0:
                self.runtime.log(f"web sync push waits: the {exc} index is held by a read that has not ended ({self.busy} looks given up)")
            return 0
        if self.busy:
            self.runtime.log(f"web sync push goes on: the index is free again after {self.busy} looks given up")
            self.busy = 0
        if collector is not self.collector:
            return 0  # Left behind while it looked: what it read is old.
        collector.mark("posting")
        # Keep avatar allocation outside the read-only Collector and finish its lock before any HTTP call.
        # Feishu and the web share this ledger, including collision handling and assignments already made.
        for each in items:
            if each["type"] == "project" and "avatar" not in each["data"]:
                name = avatars.lead_name(self.env.state_dir, chat, each["key"])
                if name:
                    each["data"]["avatar"] = name
                    each["rev"] = web_sync.rev(each["data"])
        urgent = []
        with self.backlog_lock:
            for whose, seq, mine in collector.groups:
                self.fresh[whose] = max(self.fresh.get(whose, 0), seq)
                for each in mine:
                    name = (each["type"], each["key"])
                    self.backlog.pop(name, None)
                    if sent.get(name) != each["rev"]:
                        urgent.append(each)
            later, size = [], 0
            for name, (each, whose, seq) in list(self.backlog.items()):
                if seq < self.fresh.get(whose, 0) or sent.get(name) == each["rev"]:
                    del self.backlog[name]  # A newer read of its topic went out, or the page has it already.
                    continue
                weight = len(json.dumps(each, ensure_ascii=False).encode())
                if later and size + weight > STEP_BYTES:
                    break
                later.append(each)
                size += weight
                self.fresh[whose] = max(self.fresh.get(whose, 0), seq)
            deletions, self.deletions = self.deletions, []
            ended, self.pass_ended = self.pass_ended, False
        count, posted = 0, False
        try:
            for batch in web_sync.batches(urgent + later):
                if collector is not self.collector:
                    return count  # Left behind (start_over) while it looked: what it read is old, the page would go back to it.
                self.client.request("POST", "/sync/upsert", {"items": batch, "deleted": []})
                collector.moved = time.monotonic()  # The first push of a big chat is many batches: each one taken is progress.
                with self.backlog_lock:
                    for each in batch:
                        name = (each["type"], each["key"])
                        sent[name] = each["rev"]
                        if (self.backlog.get(name) or (None,))[0] is each:
                            del self.backlog[name]
                count += len(batch)
                self.sent_changed = True
            if collector is not self.collector:
                return count
            # A topic a pass did not see but a quick look built since (an old topic written to again) stays.
            deleted = [each for seq, rows in deletions for each in rows
                       if self.fresh.get(each["key"] if each["type"] == "topic" else f"{each['type']}:{each['key']}", 0) < seq]
            if deleted or (ended and not count):
                self.client.request("POST", "/sync/upsert", {"items": [], "deleted": deleted})
            posted = True
        finally:
            if not posted:  # Failed or left behind: the page took none of them, the next quick look sends the deletions.
                with self.backlog_lock:
                    self.deletions[:0] = deletions
                    self.pass_ended = self.pass_ended or ended
        if deleted or (ended and not count):
            gone = {each["key"] for each in deleted if each["type"] == "topic"}
            with self.backlog_lock:
                for each in deleted:
                    sent.pop((each["type"], each["key"]), None)
                for name, (each, whose, _) in list(self.backlog.items()):  # Nothing of a topic deleted goes after it.
                    if whose in gone or each["key"] in gone or str((each.get("data") or {}).get("topic_key") or "") in gone:
                        del self.backlog[name]
            self.sent_changed = True
        if collector is self.collector:
            full, self.asks_full = self.asks_full, False
            self.push_asks(collector, full)
            collector.mark("")
        return count

    def pass_once(self, now=None) -> int:
        """One step of the full pass (Collector.collect_pass), in its own thread: when one is due (FULL_SECONDS after the last ended) it
        starts, with the 设置 and 整理专项 items built again; each step reads PASS_SLICE topics into the backlog, which the
        quick looks send a batch at a time after their own items; one that ended leaves its deletions to the next quick look. Then some
        images (push_images) and, now and then, what the page has (save_sent). How many items it put in the backlog."""
        chat = self.runtime.access.owner_chat()
        if not chat or not self.env.state_dir:
            return 0
        if not self.sent_loaded:
            self.load_sent(now)
        self.images_ready()
        passer, sent = self.passer, self.sent
        now = time.time() if now is None else now
        full = not passer.pass_left and now - self.last_full >= FULL_SECONDS  # A full pass is due and none is under way.
        if full and (self.sent_since is None or now - self.sent_since >= SENT_KEEP_SECONDS):
            if self.sent_since is not None:
                sent.clear()  # A day on: everything once more, a step's worth at a time behind the hot topics.
                self.sent_changed = True
            self.sent_since = now
        items, deleted = passer.collect_pass(chat, now, full, skip=self.collector.hot | self.collector.dirty)
        if passer is not self.passer:
            return 0  # Left behind while it looked: what it read is old, and must not wait in the backlog either.
        put = 0
        with self.backlog_lock:
            for whose, seq, mine in passer.groups:
                if seq < self.fresh.get(whose, 0):
                    continue  # A quick look sent a newer read of it already.
                for each in mine:
                    name = (each["type"], each["key"])
                    if sent.get(name) != each["rev"]:
                        self.backlog[name] = (each, whose, seq)
                        put += 1
                    else:
                        self.backlog.pop(name, None)
            if passer.pass_done:
                self.deletions.append((self.shared.next_seq(), deleted))
                self.pass_ended = True
                self.last_full = max(self.last_full, now)
        if full:
            self.collector.projects_due, self.asks_full = True, True  # Every project built again, 要你处理 sent again if it was refused.
            passer.mark("settings")
            self.push_settings(chat, now, full=True)
            passer.mark("tidy")
            self.push_tidy(now, full=True)
            self.last_full = now
        passer.mark("images")
        self.push_images(passer, now)
        passer.mark("saving")
        self.save_due(now)
        passer.mark("")
        return put

    def save_due(self, now=None) -> None:
        """``save_sent`` when what the page has changed, at most every SENT_SAVE_SECONDS, and when a pass ended."""
        if self.sent_changed and (self.passer.pass_done or time.monotonic() - self.sent_saved >= SENT_SAVE_SECONDS):
            self.save_sent(now)

    def images_ready(self) -> None:
        """The images' ledger, once the state directory is known: the unified Bridge builds this object before build_context fills
        the butler env's state directory in."""
        if self.images is not None or not self.env.state_dir:
            return
        self.images = web_images.WebImages(self.env.state_dir, self.runtime.log)
        self.collector.images = self.passer.images = self.images
        self.passer.backfill = not self.images.backfilled

    def push_images(self, collector, now) -> None:
        """Some of the images the turns asked for (web_images.WebImages.upload), from the pass's thread; their topics are built again
        on the next quick look, now with them. A page that does not take them (an older page without /sync/image, a refusal) only holds
        the images back IMAGES_WAIT seconds: the items go on as before."""
        if self.images is None or now < self.images_wait:
            return
        try:
            topics = self.images.upload(self.client, now, lambda: setattr(collector, "moved", time.monotonic()))
        except WebError as exc:
            self.images_down += 1
            if self.images_down == 1 or self.images_down % 10 == 0:
                self.runtime.log(f"web sync images failed ({self.images_down}): {self.why(exc)}")
            self.images_wait = now + IMAGES_WAIT
            return
        self.images_down = 0
        for topic in topics:
            self.collector.touch(topic)
        if topics:
            self.wake.set()

    def sent_path(self) -> Path:
        return Path(self.env.state_dir) / web_sync.FOLDER / SENT_FILE

    def load_sent(self, now=None) -> None:
        """What the page took before this process (save_sent), when it was saved for the same page less than SENT_KEEP_SECONDS ago:
        a restart sends only what changed since, not every item again. Anything else (none, another page, too old, unreadable):
        nothing, so everything goes once, as before."""
        self.sent_loaded = True
        now = time.time() if now is None else now
        try:
            base = self.client.settings().base_url
        except ValueError:
            return
        data = read_object(self.sent_path())
        since = data.get("since")
        rows = data.get("sent")
        if data.get("base_url") != base or not isinstance(since, (int, float)) or not 0 <= now - since < SENT_KEEP_SECONDS or not isinstance(rows, list):
            return
        self.sent_since = since
        for row in rows:
            if isinstance(row, list) and len(row) == 3 and all(isinstance(part, str) for part in row):
                self.sent.setdefault((row[0], row[1]), row[2])

    def save_sent(self, now=None) -> None:
        """``sent`` to <state>/web/sent.json for the next process (load_sent); a failure to write is only a slower next start."""
        self.sent_saved, self.sent_changed = time.monotonic(), False
        try:
            base = self.client.settings().base_url
            rows = [[kind, key, rev] for (kind, key), rev in list(self.sent.items())]
            path = self.sent_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {"base_url": base, "since": self.sent_since, "saved_at": time.time() if now is None else now, "sent": rows},
                       ensure_ascii=False)
        except (OSError, ValueError):
            pass

    def settings_items(self, chat, now, full) -> list:
        """The ``settings`` item (app/web_settings.py) when it is due: on a full look, after the page changed a setting, when main-thread.json
        or the workspace list or the term list changed (three stats); else none. Never raises (a 设置 that cannot be read stops nothing)."""
        if getattr(self.env, "settings", None) is None:
            return []
        builder = self.ops.web_settings
        try:
            stamps = builder.stamps()
            if not (full or self.settings_due or stamps != self.settings_stamps):
                return []
            self.settings_due, self.settings_stamps = False, stamps
            items = [web_sync.item("settings", web_sync.SETTINGS_KEY, builder.snapshot(chat, now))]
            if full:  # 本周用量 as the card counts it (data contract v15): once a full look, its rev changes as tasks run.
                items.append(web_sync.item("settings", web_sync.USAGE_KEY, builder.usage(now)))
            return items
        except Exception as exc:  # noqa: BLE001 - logged; the next look tries again
            self.runtime.log(f"web settings not built: {type(exc).__name__}")
            return []

    def push_settings(self, chat, now, full=False) -> int:
        """The ``settings`` item posted on its own when it is due and changed (``settings_items``): from the inbox thread each second, so a
        change the page made is on the page before its ack, and a change on the card a second later, however long the push thread's full look
        takes (minutes in a big chat on a network disk); and from the push
        thread's full look. One at a time (``settings_lock``). How many went (0 or 1); a failed post is logged and tried on the next look."""
        if not self.settings_lock.acquire(blocking=False):
            return 0  # The other thread posts it, or a look left behind still holds it (a read on the network disk that hangs).
        try:
            due = [each for each in self.settings_items(chat, now, full)
                   if self.sent.get((each["type"], each["key"])) != each["rev"]]
            if not due:
                return 0
            try:
                self.client.request("POST", "/sync/upsert", {"items": due, "deleted": []})
            except Exception as exc:  # noqa: BLE001 - the inbox goes on; the settings are due again
                self.settings_due = True
                self.runtime.log(f"web settings not pushed: {type(exc).__name__}: {self.why(exc)}")
                return 0
            for each in due:
                self.sent[(each["type"], each["key"])] = each["rev"]
            return len(due)
        finally:
            self.settings_lock.release()

    def push_asks(self, collector, full=False) -> int:
        """The ``settings`` item ``asks`` (data contract v34): 要你处理 as every card counts it ({waiting, stopped, stuck},
        core/board_read.py Asks.counts, the collector's last look), posted on its own right after the step's topics, when it
        changed. A page older than v34 refuses the key: that is logged (the first time, then every tenth) and the same counts are
        tried again only on a full look, never holding up the topics, which went in their own request. How many went (0 or 1)."""
        if collector.asks is None:
            return 0
        each = web_sync.item("settings", web_sync.ASKS_KEY, collector.asks)
        name = (each["type"], each["key"])
        if self.sent.get(name) == each["rev"] or (self.asks_tried == each["rev"] and not full):
            return 0
        self.asks_tried = each["rev"]
        try:
            self.client.request("POST", "/sync/upsert", {"items": [each], "deleted": []})
        except Exception as exc:  # noqa: BLE001 - logged; a change or the next full look tries again
            self.asks_failed += 1
            if self.asks_failed == 1 or self.asks_failed % 10 == 0:
                self.runtime.log(f"web asks not pushed ({self.asks_failed}): {type(exc).__name__}: {self.why(exc)}")
            return 0
        self.asks_failed = 0
        self.sent[name] = each["rev"]
        self.sent_changed = True
        return 1

    def push_tidy(self, now, full=False) -> int:
        """The ``settings`` item ``tidy`` (整理专项's suggestions, app/project_tidy.py web_view, data contract v16), posted on its own: when
        the runs or the proposals changed (a stat of two folders, from the inbox thread each second) and on a full look. A page older than
        v16 refuses the key: that is logged (the first time, then every tenth) and tried again only on the next full look or change, and
        never holds up the settings, which go in a request of their own. How many went (0 or 1)."""
        tidy = getattr(self.env, "tidy", None)
        if tidy is None or not getattr(self.env, "state_dir", None) or not self.tidy_lock.acquire(blocking=False):
            return 0
        try:
            stamps = tidy.web_stamps()
            if not full and stamps == self.tidy_stamps:
                return 0
            self.tidy_stamps = stamps
            data = tidy.web_view(now)
            if data is None:
                return 0
            each = web_sync.item("settings", web_sync.TIDY_KEY, data)
            if self.sent.get((each["type"], each["key"])) == each["rev"]:
                return 0
            try:
                self.client.request("POST", "/sync/upsert", {"items": [each], "deleted": []})
            except Exception as exc:  # noqa: BLE001 - logged; the next full look or change tries again
                self.tidy_failed += 1
                if self.tidy_failed == 1 or self.tidy_failed % 10 == 0:
                    self.runtime.log(f"web tidy not pushed ({self.tidy_failed}): {type(exc).__name__}: {self.why(exc)}")
                return 0
            self.tidy_failed = 0
            self.sent[(each["type"], each["key"])] = each["rev"]
            return 1
        except Exception as exc:  # noqa: BLE001 - a 整理专项 that cannot be read stops nothing
            self.runtime.log(f"web tidy not built: {type(exc).__name__}")
            return 0
        finally:
            self.tidy_lock.release()

    # -- inbox ----------------------------------------------------------------------------------------------------------

    def inbox_once(self) -> int:
        """Fetch, do and acknowledge the page's operations; how many were new."""
        if not self.env.state_dir:
            return 0
        if self.ledger is None:
            self.ledger = web_sync.Ledger(self.env.state_dir)
        ledger = self.ledger
        data = self.client.request("GET", f"/sync/inbox?after={ledger.after()}&limit=100")
        results, fresh = [], 0

        def flush(timing=None) -> None:
            """What the page reads before it sees done (the new settings, the tidy list), then the ack of the results so far: one
            operation's ack does not wait for the ones after it in the same batch."""
            nonlocal results
            began = time.monotonic()
            chat = self.runtime.access.owner_chat()
            if chat:
                self.push_settings(chat, time.time())
                self.push_tidy(time.time())
            pushed = time.monotonic()
            if results:
                self.client.request("POST", "/sync/ack", {"results": results})
                ledger.acked([each["op_id"] for each in results])
                if timing is not None:  # Content-free: where the seconds of a page's change go (docs/web.md).
                    self.runtime.log(f"web op {timing[0]} seq={timing[1]} run={timing[2]:.0f}ms push={(pushed - began) * 1000:.0f}ms "
                                     f"ack={(time.monotonic() - pushed) * 1000:.0f}ms")
            results = []

        for row in data.get("items") or ():
            op_id, seq = str(row.get("op_id") or ""), row.get("seq")
            if not op_id or not isinstance(seq, int) or isinstance(seq, bool):
                continue
            known = ledger.get(op_id)
            timing = None
            if known is None:
                fresh += 1
                ledger.take(op_id, seq)
                ran = time.monotonic()
                state, message = self.ops.run(row)
                ledger.finish(op_id, state, message)
                timing = (str(row.get("kind") or ""), seq, (time.monotonic() - ran) * 1000)
                if row.get("topic_key"):
                    self.collector.touch(row["topic_key"])
                opened = self.ops.opened_topic(row)
                if opened:  # Else the page waits a minute for the topic it has just opened.
                    self.collector.touch(opened)
                self.wake.set()  # The quick look builds what the operation touched now, not at its next tick.
                if row.get("kind") in ("settings", "launch"):  # A launch changes what the next one preselects.
                    self.settings_due = True  # Pushed below, before the ack: the page reads the new settings when it sees done.
                if row.get("kind") == "tidy_decide":
                    self.tidy_stamps = None  # Pushed below, before the ack, as the settings are.
            elif known.get("state") == "received":
                ledger.finish(op_id, "failed", "这条执行到一半没有结果（Covey 重启或卡住了），结果不确定，没有重发")
            saved = ledger.get(op_id)
            results.append({"seq": seq, "op_id": op_id, "state": saved["state"], "message": saved["message"]})
            if timing is not None and timing[0] in ("settings", "launch", "tidy_decide"):
                flush(timing)  # Acked at once, not after the rest of the batch.
        flush()
        return fresh
