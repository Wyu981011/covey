"""网页工作台同步的上限与节流 (app/web_push_client.py, core/web_sync.py, data contract v44): a page that says what it takes (``limits`` in
its answers) gets batches of up to 5 MB and images of up to 3 MB, a page that says nothing gets 1 MB and 700 KB as before, another page
starts from nothing again; requests to an https:// page go through one token bucket for all the threads of a client (8 a second, 10 at
once, waiting 2 s at most) and a 429 holds them all back 1.5 s; a self-hosted page on loopback (http://) is not paced."""
from __future__ import annotations

import json
import os
import random
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from covey.app import web_images
from covey.app import web_sync as app_web
from covey.app.web_push_client import Client, Gate, WebError
from covey.core import http_upstream, web_sync
from covey.core.serving import LoopbackServer
from covey.core.state import write_json

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the machine
    Image = None

from test_web_sync import T0, TOPIC, WebCase

MB8 = 8 * 1024 * 1024
NEW = {"body_bytes": MB8, "image_bytes": 7 * 1024 * 1024, "store": "file", "heap_limit_mb": 704, "rss_mb": 180, "mem_limit_mb": 1024}


class FakeClock:
    """A clock that moves only when slept on."""

    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


FAST = 50_000_000  # Bytes a second of a way to the page fast enough that only the page's limits count.


class LimitsTest(unittest.TestCase):
    def test_a_page_that_says_nothing_gets_what_it_got_before(self):
        for answer in ({}, {"ok": True}, {"limits": None}, {"limits": "8mb"}, {"limits": {"body_bytes": "8mb"}},
                       {"limits": {"body_bytes": True}}, {"limits": {"body_bytes": 0}}, {"limits": {"image_bytes": MB8}}):
            limits = web_sync.limits_of(answer)
            self.assertIsNone(limits, answer)
            self.assertEqual((web_sync.batch_bytes(limits), web_sync.image_bytes(limits)), (1_000_000, 700_000))

    def test_the_batch_is_six_tenths_of_the_body_limit_and_five_mb_at_most(self):
        self.assertEqual(web_sync.batch_bytes(web_sync.limits_of({"limits": {"body_bytes": MB8}}), FAST), 5_000_000)
        self.assertEqual(web_sync.batch_bytes({"body_bytes": 4_000_000}, FAST), 2_400_000)
        self.assertEqual(web_sync.batch_bytes({"body_bytes": 1024 * 1024}, FAST), 1_000_000)  # A page left at the old 1 MB: as before.
        self.assertEqual(web_sync.batch_bytes({"body_bytes": 64 * 1024 * 1024}, FAST), 5_000_000)

    def test_an_image_is_what_the_page_takes_less_a_margin_and_three_mb_at_most(self):
        self.assertEqual(web_sync.image_bytes({"body_bytes": MB8, "image_bytes": 2_000_000}, FAST), 2_000_000 - 65_536)
        self.assertEqual(web_sync.image_bytes(NEW, FAST), 3_000_000)
        self.assertEqual(web_sync.image_bytes({"body_bytes": MB8, "image_bytes": 760 * 1024}, FAST), 700_000)  # What an older page takes.
        self.assertEqual(web_sync.image_bytes({"body_bytes": MB8}, FAST), 700_000)

    def test_the_way_to_the_page_bounds_a_batch_and_an_image_by_a_few_seconds_of_it(self):
        """T876: through the dev machine's proxy (0.1 MB/s) a 5 MB batch took 52 s and the quick look took it for stuck."""
        self.assertEqual((web_sync.batch_bytes(NEW), web_sync.image_bytes(NEW)), (1_000_000, 700_000), "not measured yet: the old sizes")
        self.assertEqual((web_sync.batch_bytes(NEW, 100_000), web_sync.image_bytes(NEW, 100_000)), (400_000, 800_000))
        self.assertEqual((web_sync.batch_bytes(NEW, 10_000), web_sync.image_bytes(NEW, 10_000)), (250_000, 700_000), "never under the floor")
        self.assertEqual((web_sync.batch_bytes(NEW, 5_000_000), web_sync.image_bytes(NEW, 5_000_000)), (5_000_000, 3_000_000))
        self.assertEqual(web_sync.batch_bytes(None, 10_000), 250_000)
        self.assertEqual(web_sync.batch_bytes(None, FAST), 1_000_000, "an older page: never over its 1 MB")

    def test_batches_are_cut_at_the_limit_given(self):
        items = [web_sync.item("turn", str(n), {"body": "y" * 400_000}) for n in range(12)]
        self.assertEqual([len(batch) for batch in web_sync.batches(items)], [2] * 6)
        self.assertEqual([len(batch) for batch in web_sync.batches(items, 5_000_000)], [12])
        for batch in web_sync.batches(items, 2_400_000):
            self.assertLessEqual(len(json.dumps({"items": batch, "deleted": []}, ensure_ascii=False).encode()), 2_400_000 + 100)


class GateTest(unittest.TestCase):
    def gate(self, **kw):
        clock = FakeClock()
        return Gate(clock=clock, sleep=clock.sleep, **kw), clock

    def test_a_burst_goes_at_once_and_the_rest_at_the_rate(self):
        gate, clock = self.gate()
        waits = [gate.take() for _ in range(10)]
        self.assertEqual(waits, [0.0] * 10)
        began = clock.now
        for _ in range(16):
            gate.take()
        self.assertAlmostEqual(clock.now - began, 16 / 8, places=6)  # 8 a second after the first 10.

    def test_a_request_waits_two_seconds_at_most_and_then_goes(self):
        gate, clock = self.gate(rate=0.01, burst=1)
        self.assertEqual(gate.take(), 0.0)
        self.assertAlmostEqual(gate.take(), 2.0)
        self.assertLessEqual(max(clock.slept), 2.0)
        self.assertGreaterEqual(gate.tokens, -gate.burst)  # Going anyway leaves a debt of a burst at most.
        for _ in range(5):
            gate.take()
        self.assertGreaterEqual(gate.tokens, -gate.burst)

    def test_a_429_holds_every_request_back_a_moment_then_they_go_from_no_tokens(self):
        gate, clock = self.gate()
        gate.take()
        gate.cool()
        began = clock.now
        gate.take()
        self.assertGreaterEqual(clock.now - began, 1.5)
        self.assertLess(clock.now - began, 1.5 + 2 / 8)
        again = clock.now
        gate.take()
        self.assertAlmostEqual(clock.now - again, 1 / 8, places=6)  # No burst saved up while cooling.

    def test_threads_share_one_bucket(self):
        gate = Gate(rate=100.0, burst=1.0)
        began = time.monotonic()
        threads = [threading.Thread(target=lambda: [gate.take() for _ in range(5)]) for _ in range(4)]
        for each in threads:
            each.start()
        for each in threads:
            each.join(10)
        self.assertGreaterEqual(time.monotonic() - began, 19 / 100 - 0.01)  # 20 requests, one at once, 100 a second.


class Kept:
    """KeepAlive's place: hands out the answers given, records what was sent."""

    def __init__(self, *answers):
        self.answers, self.sent = list(answers), []

    def send(self, method, url, body, headers, timeout):
        self.sent.append((method, url))
        if not self.answers:
            raise OSError("timed out")  # Nothing answers.
        return self.answers.pop(0)


class Recorder:
    """A Gate that records what it was asked."""

    def __init__(self):
        self.calls = []

    def take(self, most=2.0):
        self.calls.append("take")
        return 0.0

    def cool(self, seconds=1.5):
        self.calls.append("cool")


class ClientTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        folder = Path(self.dir.name)
        self.key = folder / "key.txt"
        self.key.write_text("fake-key\n")
        self.config = folder / "web.json"
        self.write("https://page-one.example/openapi")
        patch = mock.patch.dict(os.environ, {web_sync.CONFIG_ENV: str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)
        self.gate = Recorder()
        self.client = Client(gate=self.gate)

    def write(self, base):
        write_json(self.config, {"base_url": base, "key_file": str(self.key)})

    def answer(self, value, status=200):
        return status, json.dumps(value).encode()

    def test_the_client_learns_the_limits_from_an_answer_and_keeps_them(self):
        self.client.kept = Kept(self.answer({"ok": True, "limits": NEW}), self.answer({"items": []}), self.answer({"limits": {"x": 1}}))
        self.assertEqual((self.client.batch_bytes(), self.client.image_bytes()), (1_000_000, 700_000))
        self.client.request("POST", "/sync/upsert", {"items": []})
        self.client.rate = FAST
        self.assertEqual((self.client.batch_bytes(), self.client.image_bytes()), (5_000_000, 3_000_000))
        self.client.request("GET", "/sync/inbox?after=0")  # An answer without limits (the inbox) leaves them as they were.
        self.client.request("POST", "/sync/images/have", {"ids": []})  # Limits not of the shape: left as they were too.
        self.assertEqual(self.client.batch_bytes(), 5_000_000)
        self.assertEqual(self.client.limits["store"], "file")

    def test_another_page_starts_from_nothing(self):
        self.client.kept = Kept(self.answer({"limits": NEW}), self.answer({"ok": True}))
        self.client.request("POST", "/sync/upsert", {"items": []})
        self.client.rate = FAST
        self.assertEqual(self.client.batch_bytes(), 5_000_000)
        time.sleep(0.01)
        self.write("https://page-two.example/openapi")
        os.utime(self.config, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
        self.client.loaded = 0.0  # The next request looks at the config file again (CHECK_SECONDS passed).
        self.client.request("GET", "/sync/inbox?after=0")
        self.assertEqual(self.client.kept.sent[-1][1], "https://page-two.example/openapi/sync/inbox?after=0")
        self.assertEqual((self.client.batch_bytes(), self.client.image_bytes()), (1_000_000, 700_000))

    def test_the_same_page_read_again_keeps_its_limits(self):
        self.client.kept = Kept(self.answer({"limits": NEW}), self.answer({"ok": True}))
        self.client.request("POST", "/sync/upsert", {"items": []})
        self.client.rate = FAST
        os.utime(self.config, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))  # Touched, same address.
        self.client.loaded = 0.0
        self.client.request("GET", "/sync/inbox?after=0")
        self.assertEqual(self.client.batch_bytes(), 5_000_000)

    def test_every_https_request_takes_from_the_gate_and_a_429_cools_it(self):
        self.client.kept = Kept(self.answer({"ok": True}), (429, b""), self.answer({"ok": True}))
        self.client.request("POST", "/sync/upsert", {"items": []})
        with self.assertRaises(WebError) as caught:
            self.client.request("POST", "/sync/upsert", {"items": []})
        self.assertEqual(caught.exception.status, 429)
        self.client.request("POST", "/sync/upsert", {"items": []})
        self.assertEqual(self.gate.calls, ["take", "take", "cool", "take"])

    def test_a_503_does_not_cool_the_gate(self):
        self.client.kept = Kept((503, b""))
        with self.assertRaises(WebError):
            self.client.request("GET", "/sync/inbox?after=0")
        self.assertEqual(self.gate.calls, ["take"])

    def test_a_self_hosted_page_on_loopback_is_not_paced(self):
        statuses = [200, 429, 200]
        seen = []

        def handle(handler, body):
            seen.append(handler.path)
            status = statuses.pop(0)
            payload = json.dumps({"ok": True, "limits": NEW} if status == 200 else {}).encode()
            handler.send_response(status)
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
        with LoopbackServer(handle, "web-limits-fake") as server:
            self.write(server.base_url)
            self.client.config = None
            self.client.opener = http_upstream.opener(direct=True)
            self.client.request("POST", "/sync/upsert", {"items": []})
            with self.assertRaises(WebError):
                self.client.request("POST", "/sync/upsert", {"items": []})
            self.client.request("POST", "/sync/upsert", {"items": []})
        self.assertEqual(len(seen), 3)
        self.assertEqual(self.gate.calls, [])
        self.client.rate = FAST
        self.assertEqual(self.client.batch_bytes(), 5_000_000)  # A self-hosted page of v44 says its limits too.

    def test_a_large_request_tells_how_fast_the_way_is_and_a_slow_way_gets_smaller_batches(self):
        """T876: each request of RATE_MIN_BYTES or more is timed, a failed one too; the average follows the last few."""
        self.client.limits = NEW
        self.client.measured(1_000_000, 10.0)  # 0.1 MB/s, as the dev machine's proxy carried it.
        self.assertEqual(self.client.rate, 100_000)
        self.assertEqual((self.client.batch_bytes(), self.client.image_bytes()), (400_000, 800_000))
        self.client.measured(1_000_000, 2.0)  # Halfway to 0.5 MB/s.
        self.assertEqual(self.client.rate, 300_000)
        big, small = {"items": [{"body": "y" * 300_000}]}, {"items": []}
        self.client.kept = Kept(self.answer({"ok": True}), self.answer({"ok": True}))
        with mock.patch.object(self.client, "measured") as measured:
            self.client.request("POST", "/sync/upsert", small)
            self.client.request("POST", "/sync/upsert", big)
            with self.assertRaises(WebError):
                self.client.request("POST", "/sync/upsert", big)  # Nothing answers: timed all the same.
        self.assertEqual([call.args[0] > 300_000 for call in measured.call_args_list], [True, True])

    def test_the_configs_direct_goes_round_the_proxy(self):
        write_json(self.config, {"base_url": "https://page-one.example/openapi", "key_file": str(self.key), "direct": True})
        os.utime(self.config, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
        self.client.loaded, self.client.config = 0.0, None
        self.client.kept = Kept()  # Through the proxy: must not be used.
        self.client.kept_direct = Kept(self.answer({"ok": True}))
        self.client.request("GET", "/sync/inbox?after=0")
        self.assertEqual(len(self.client.kept_direct.sent), 1)
        self.assertEqual(self.client.kept.sent, [])
        with mock.patch("urllib.request.getproxies", return_value={"https": "http://proxy.invalid:8118"}), \
                mock.patch("http.client.HTTPSConnection") as conn:
            http_upstream.KeepAlive(direct=True).connect(("page-one.example", 443), 5)
            http_upstream.KeepAlive().connect(("page-one.example", 443), 5)
        self.assertEqual([call.args[0] for call in conn.call_args_list], ["page-one.example", "proxy.invalid"])


class PushTest(WebCase):
    def test_an_older_page_gets_batches_of_one_mb(self):
        self.topic()
        with mock.patch.object(app_web.web_sync, "batches", wraps=web_sync.batches) as cut:
            self.sync.push_once(T0)
            self.sync.push_once(T0 + 1)
        self.assertTrue(cut.call_args_list)
        self.assertEqual({call.args[1] for call in cut.call_args_list}, {1_000_000})

    def test_a_page_that_says_it_takes_eight_mb_gets_batches_of_five(self):
        """The first batch goes at 1 MB (nothing said yet); once the page's answer said 8 MB and the way to it is fast, five a batch
        (not measured yet, still 1 MB: T876)."""
        self.web.limits = NEW
        self.topic()
        self.sync.push_once(T0)
        self.assertEqual(self.sync.client.batch_bytes(), 1_000_000)
        self.sync.client.rate = FAST
        self.assertEqual(self.sync.client.batch_bytes(), 5_000_000)
        with mock.patch.object(app_web.web_sync, "batches", wraps=web_sync.batches) as cut:
            self.sync.collector.touch(TOPIC)
            self.sync.push_once(T0 + 1)
            self.sync.pass_once(T0 + 2)
            self.sync.push_once(T0 + 3)
        self.assertTrue(cut.call_args_list)
        self.assertEqual({call.args[1] for call in cut.call_args_list}, {5_000_000})


@unittest.skipUnless(Image, "needs Pillow (optional)")
class EncodeTest(unittest.TestCase):
    def test_the_large_image_is_kept_under_the_size_given(self):
        import tempfile
        rng = random.Random(7)
        image = Image.frombytes("RGB", (700, 700), bytes(rng.getrandbits(8) for _ in range(700 * 700 * 3)))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "noise.png")
            image.save(path)
            _w, _h, _thumb, small, _mime = web_images.encode(path, 120_000)
            _w, _h, _thumb, large, _mime = web_images.encode(path, 3_000_000)
        self.assertLessEqual(len(small), 120_000)
        self.assertGreater(len(large), 120_000)
        self.assertLessEqual(len(large), 3_000_000)

    def test_the_default_is_the_old_part(self):
        self.assertEqual(web_images.MAX_PART, 700_000)
        self.assertIs(web_images.encode.__defaults__[0], web_images.MAX_PART)


class WithoutPillowTest(unittest.TestCase):
    def test_without_pillow_the_size_given_decides_what_goes_as_it_is(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(web_images, "Image", None):
            path = os.path.join(folder, "big.png")
            with open(path, "wb") as f:
                f.write(b"\x89PNG" + b"0" * 800_000)
            with self.assertRaises(web_images.BadImage):
                web_images.encode(path)
            self.assertEqual(len(web_images.encode(path, 3_000_000)[3]), 800_004)

    def test_a_client_without_image_bytes_gets_the_old_part(self):
        sent = []
        client = SimpleNamespace(request=lambda method, path, body=None: sent.append(body) or {})
        images = SimpleNamespace(ids={}, changed=False)
        with mock.patch.object(web_images, "encode", return_value=(1, 1, b"t", b"f", "image/png")) as encode:
            web_images.WebImages.send(images, client, "/x.png", "a" * 32, T0, None)
        self.assertEqual(encode.call_args.args[1], 700_000)
        self.assertEqual([each["v"] for each in sent], ["thumb", "full"])


if __name__ == "__main__":
    unittest.main()
