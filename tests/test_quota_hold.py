"""A gateway's spent daily quota held until it resets (core/quota_hold.py): the relay answers Codex itself, a turn on
the quota or on a route sharing it fails before it starts, the card says when it is back and where to go instead."""
from __future__ import annotations

import dataclasses
import json
import os
import time
import unittest
import zlib
from types import SimpleNamespace
from unittest import mock

from support.records import state_dir
from support.world import UnifiedCase
from test_gateway_relay import Upstream, post

from covey.backends.codex import turn as codex_turn
from covey.backends.gateway.relay import BusyRelay
from covey.core import failure, gateways, quota_hold
from covey.core.harness import JobCancelled, RunResult
from covey.core.result import ExecutionOutcome
from covey.core.state import write_json

GW = {"display": "MyGW", "prefix": "mygw/", "base_url": "https://gw.example/", "key_env": "MYGW_KEY",
      "harnesses": ["codex", "dsh"], "quota_pattern": r"quota exceeded|daily limits? exceeded"}
# The routes this machine has, as harnesses.json's gateway_quotas says them: one more on the same key, and the ones
# that are not (an unprefixed account model, two other routes, another Harness).
SHARES = {"mygw": {"shared": ["mygw-personal/"], "instead": ["", "other/", "missing/", "Claude"]}}
CATALOG = {"gpt-6-luna": {"display_name": "GPT-6-Luna"}, "mygw-personal/gpt-x": {"display_name": "GPT X · MyGW Personal"},
           "other/seed": {"display_name": "Seed · Other Route（OR）"}}


def iso(at):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


def spent_text(reset_at):
    """The gateway's own words for a spent quota (Acme's, 2026-11-25), with a reset ``reset_at``."""
    return f"quota exceeded: Daily Limits exceeded. Resets at {iso(reset_at)}. See https://example.invalid/doc for details."


def configure(test):
    gateways.configure({"mygw": GW})
    gateways.configure_quotas(SHARES)

    def undo():
        gateways.configure(None)
        gateways.configure_quotas(None)
        gateways.forget()
    test.addCleanup(undo)
    return gateways.named("mygw")


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.state = state_dir(self)
        self.gateway = configure(self)

    def test_a_spent_quota_is_held_until_its_reset_and_not_after(self):
        now = time.time()
        reset = int(now) + 3600
        record = quota_hold.note(self.state, self.gateway, spent_text(reset), now=now)
        self.assertEqual(record["reset_at"], reset)
        self.assertEqual(quota_hold.read(self.state, self.gateway, now)["reset_at"], reset)
        self.assertIsNotNone(quota_hold.blocks(self.state, "codex", "mygw/gpt-x", now))
        # At the reset the hold is over: the next turn starts again.
        self.assertIsNone(quota_hold.read(self.state, self.gateway, reset))
        self.assertIsNone(quota_hold.blocks(self.state, "codex", "mygw/gpt-x", reset + 1))
        # Words without a reset, or one already past, hold nothing.
        self.assertIsNone(quota_hold.note(self.state, gateways.named("mygw"), "quota exceeded", now=reset + 1))
        self.assertIsNone(quota_hold.note(self.state, self.gateway, spent_text(now - 60), now=now))

    def test_the_routes_on_one_quota_share_its_hold_and_others_do_not(self):
        now = time.time()
        quota_hold.note(self.state, self.gateway, spent_text(now + 3600), now=now)
        for model in ("mygw/gpt-x", "mygw-personal/gpt-x"):
            found = quota_hold.blocks(self.state, "codex", model, now)
            self.assertIsNotNone(found, model)
            self.assertEqual(found[0].name, "mygw")
        self.assertIs(gateways.quota_gateway("dsh", "any-model"), gateways.dsh_gateway())  # dsh's model has no prefix.
        for harness, model in (("codex", "gpt-6-luna"), ("codex", "other/seed"), ("claude", "mygw/gpt-x")):
            self.assertIsNone(quota_hold.held(self.state, harness, model, now), (harness, model))
        # A turn of the sharing route that failed on the quota holds it too: Codex's words carry the gateway's.
        quota_hold.path(self.state, self.gateway).unlink()
        said = f"unexpected status 403 Forbidden: MyGW Personal: {spent_text(now + 1800)}, url: http://127.0.0.1:1/x"
        ctx = SimpleNamespace(state_dir=self.state, model="mygw-personal/gpt-x", options={})
        codex_turn.note_spent(ctx, {"message": said})
        self.assertEqual(quota_hold.read(self.state, self.gateway)["reset_at"], int(now + 1800))

    def test_one_request_a_recheck_goes_upstream_and_a_later_answer_ends_the_hold(self):
        now = time.time()
        quota_hold.note(self.state, self.gateway, spent_text(now + 7200), now=now)
        self.assertEqual(quota_hold.claim(self.state, self.gateway, now + 1)[1], False)
        later = now + quota_hold.RECHECK
        self.assertIsNone(quota_hold.blocks(self.state, "codex", "mygw/gpt-x", later))  # The turn starts and checks.
        self.assertEqual(quota_hold.claim(self.state, self.gateway, later)[1], True)  # The first one goes,
        self.assertEqual(quota_hold.claim(self.state, self.gateway, later + 1)[1], False)  # the others still wait.
        self.assertIsNotNone(quota_hold.blocks(self.state, "codex", "mygw/gpt-x", later + 1))
        # An answer to a request sent before the hold began says nothing of now; one sent after ends it.
        self.assertFalse(quota_hold.clear(self.state, self.gateway, now - 1))
        self.assertTrue(quota_hold.clear(self.state, self.gateway, later))
        self.assertIsNone(quota_hold.read(self.state, self.gateway))

    def test_the_words_say_it_is_shared_when_it_is_back_and_where_to_go(self):
        now = time.time()
        record = quota_hold.note(self.state, self.gateway, spent_text(now + 3600), now=now)
        words = quota_hold.failure_words(self.gateway, record, now=now, catalog=CATALOG)
        self.assertIn("MyGW 的每日额度用完了，北京时间 ", words)
        self.assertIn("MyGW 的所有模型共用这一份额度，换 mygw/、mygw-personal/ 下的别的模型也没用", words)
        # From the catalog: a prefix it has no model of is left out; another Harness is said as configured.
        self.assertTrue(words.endswith("可以换到 Codex 账号的模型（不带前缀）、Other Route（other/）或 Claude"), words)
        self.assertNotIn("missing", words)
        head, rest = failure.split_title(words)
        self.assertLessEqual(len(head), failure.HEADLINE_CHARS)
        self.assertTrue(head.endswith("恢复"), head)
        self.assertTrue(rest.startswith("MyGW 的所有模型共用"), rest)
        # Midnight in Beijing is said with its date when it is another day.
        midnight = 1_795_622_400.0  # 2026-11-25T16:00:00Z, 11-26 00:00 in Beijing.
        self.assertEqual(quota_hold.clock(midnight, now=midnight - 11 * 3600), "北京时间 11-26 00:00")
        self.assertEqual(quota_hold.clock(midnight - 3600, now=midnight - 11 * 3600), "北京时间 23:00")
        # Nothing configured to go to: the words still say where not to.
        gateways.configure_quotas(None)
        bare = quota_hold.failure_words(self.gateway, None, catalog={})
        self.assertEqual(bare, "MyGW 的每日额度用完了，恢复时间不知道；MyGW 的所有模型共用这一份额度，换 mygw/ 下的别的模型也没用，"
                               "可以换到不走 MyGW 的模型或 Harness")

    def test_gateway_quotas_is_checked_for_shape(self):
        for bad in ([], {"mygw": []}, {"mygw": {"shared": "x/"}}, {"mygw": {"shared": ["no-slash"]}},
                    {"mygw": {"instead": [1]}}, {"mygw": {"other": []}}):
            with self.assertRaises(ValueError, msg=bad):
                gateways.configure_quotas(bad)
        gateways.configure_quotas({"unknown": {"instead": ["Claude"]}})  # A gateway enabled later: kept.
        self.assertEqual(gateways.quota_share("unknown").instead, ("Claude",))
        self.assertEqual(gateways.quota_share("mygw"), gateways.QuotaShare())


class RelayHoldTests(unittest.TestCase):
    """The relay of a gateway with a hold: a spent quota's 403 goes to Codex as an insufficient_quota 429 (Codex ends
    the turn on it at once; a 403 it retries for about 205 s), and later requests are answered here until the reset."""

    def setUp(self):
        self.state = state_dir(self)
        self.gateway = configure(self)
        self.logs = []

    def upstream(self, replies, then=(200, {}, b"data: x\n\n")):
        upstream = Upstream(replies, then)
        self.addCleanup(upstream.close)
        return upstream

    def relay(self, upstream):
        return BusyRelay(upstream.url, name="mygw", display="MyGW", log=self.logs.append,
                         hold=quota_hold.Hold(self.state, self.gateway, read_every=0))

    def test_a_spent_quota_fails_at_once_and_the_next_requests_never_go_upstream(self):
        reset = int(time.time()) + 3600
        body = json.dumps({"error": {"message": spent_text(reset), "type": "forbidden"}}).encode()
        upstream = self.upstream([(403, {"Content-Type": "application/json"}, body)])
        with self.relay(upstream) as relay:
            status, headers, answer = post(relay.base_url)
        self.assertEqual(status, 429)
        self.assertIsNone(headers.get("Retry-After"))
        error = json.loads(answer)["error"]
        self.assertEqual((error["type"], error["code"]), ("insufficient_quota", "insufficient_quota"))
        self.assertEqual(quota_hold.read(self.state, self.gateway)["reset_at"], reset)
        # Another turn's relay (a relay lives one turn) answers from the hold, the upstream never asked.
        with self.relay(upstream) as relay:
            again = post(relay.base_url)
        self.assertEqual((again[0], json.loads(again[2])["error"]["code"]), (429, "insufficient_quota"))
        self.assertEqual(len(upstream.seen), 1)
        self.assertTrue(self.logs[0].startswith(f"mygw quota spent, until {iso(reset)} code= message=quota exceeded"),
                        self.logs)
        self.assertEqual(self.logs[1], "mygw quota held, answered here")
        self.assertNotIn("sk-unit", "".join(self.logs))

    def test_the_words_as_plain_text_are_a_spent_quota_too(self):
        upstream = self.upstream([(403, {}, spent_text(time.time() + 600).encode())])
        with self.relay(upstream) as relay:
            self.assertEqual(post(relay.base_url)[0], 429)
        self.assertIsNotNone(quota_hold.read(self.state, self.gateway))

    def test_after_the_reset_requests_go_upstream_again(self):
        now = time.time()
        write_json(quota_hold.path(self.state, self.gateway),
                   {"reset_at": now + 0.6, "seen_at": now, "checked_at": now, "said": "x"})
        upstream = self.upstream([])
        with self.relay(upstream) as relay:
            self.assertEqual(post(relay.base_url)[0], 429)
            self.assertEqual(upstream.seen, [])
            time.sleep(0.7)
            self.assertEqual(post(relay.base_url)[:3:2], (200, b"data: x\n\n"))
        self.assertEqual(len(upstream.seen), 1)

    def test_a_recheck_that_gets_through_ends_the_hold_and_one_that_does_not_renews_it(self):
        long_ago = time.time() - quota_hold.RECHECK - 5
        held = {"reset_at": time.time() + 3600, "seen_at": long_ago, "checked_at": long_ago, "said": "x"}
        write_json(quota_hold.path(self.state, self.gateway), held)
        upstream = self.upstream([])
        with self.relay(upstream) as relay:
            self.assertEqual(post(relay.base_url)[0], 200)  # Extra quota came before the reset: seen at once.
        self.assertFalse(quota_hold.path(self.state, self.gateway).exists())
        write_json(quota_hold.path(self.state, self.gateway), held)
        reset = int(time.time()) + 7200
        upstream = self.upstream([(403, {}, spent_text(reset).encode())])
        with self.relay(upstream) as relay:
            self.assertEqual([post(relay.base_url)[0] for _ in range(2)], [429, 429])
        self.assertEqual(len(upstream.seen), 1)  # The recheck went; the request after it was answered here.
        record = quota_hold.read(self.state, self.gateway)
        self.assertEqual(record["reset_at"], reset)
        self.assertGreater(record["checked_at"], long_ago + quota_hold.RECHECK)

    def test_a_compressed_spent_quota_is_read_as_one(self):
        # Codex asks for gzip, so a gateway may compress its 403 (a real one's spent quota came gzipped).
        def gzip_body(data):
            packer = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
            return packer.compress(data) + packer.flush()
        def raw_deflate(data):
            packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            return packer.compress(data) + packer.flush()
        for encoding, pack in (("gzip", gzip_body), ("deflate", zlib.compress), ("deflate", raw_deflate)):
            with self.subTest(encoding=encoding, pack=pack.__name__):
                quota_hold.path(self.state, self.gateway).unlink(missing_ok=True)
                self.logs.clear()
                reset = int(time.time()) + 3600
                body = json.dumps({"error": {"message": spent_text(reset), "type": "forbidden"}}).encode()
                upstream = self.upstream([(403, {"Content-Type": "application/json", "Content-Encoding": encoding},
                                           pack(body))])
                with self.relay(upstream) as relay:
                    status, _, answer = post(relay.base_url, headers={"Accept-Encoding": "gzip, deflate"})
                self.assertEqual((status, json.loads(answer)["error"]["code"]), (429, "insufficient_quota"))
                self.assertEqual(quota_hold.read(self.state, self.gateway)["reset_at"], reset)
                self.assertIn("message=quota exceeded", self.logs[0])

    def test_a_compressed_403_that_is_not_a_spent_quota_passes_byte_for_byte(self):
        packer = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
        packed = packer.compress(b'{"error":{"message":"no access"}}') + packer.flush()
        upstream = self.upstream([(403, {"Content-Encoding": "gzip"}, packed)])
        with self.relay(upstream) as relay:
            status, headers, answer = post(relay.base_url)
        self.assertEqual((status, headers.get("Content-Encoding"), answer), (403, "gzip", packed))
        self.assertFalse(quota_hold.path(self.state, self.gateway).exists())

    def test_a_403_that_is_not_a_spent_quota_passes_as_it_came(self):
        upstream = self.upstream([(403, {}, b'{"error":{"message":"no access"}}')])
        with self.relay(upstream) as relay:
            self.assertEqual(post(relay.base_url)[:3:2], (403, b'{"error":{"message":"no access"}}'))
        self.assertFalse(quota_hold.path(self.state, self.gateway).exists())

    def test_codex_reads_the_relays_answer_as_a_spent_quota(self):
        # What codex-cli 0.172.0 made of a 429 insufficient_quota from a local stand-in upstream: no retry, this error.
        error = {"message": "Quota exceeded. Check your plan and billing details.", "codexErrorInfo": "usageLimitExceeded"}
        self.assertEqual(codex_turn.codex_failure_code(error), "quota_exhausted")
        ctx = SimpleNamespace(state_dir=self.state, model="gpt-x", options={"model_provider": "mygw"})
        codex_turn.note_spent(ctx, error)  # No reset in Codex's own words: nothing written, nothing raised.
        self.assertFalse(quota_hold.path(self.state, self.gateway).exists())


class RunsHoldTests(UnifiedCase):
    """A turn on a held quota fails before its Harness starts; a turn that failed on it says so in the hold's words."""

    def setUp(self):
        super().setUp()  # Its Bridge configured harnesses.json's gateways (none): ours after it.
        self.gateway = configure(self)
        home = self.root / "codex-home"
        home.mkdir()
        (home / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": slug, "visibility": "list", **row} for slug, row in CATALOG.items()]}))
        patcher = mock.patch.dict(os.environ, {"CODEX_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.codex, self.target = self.route("m1")
        self.reset = time.time() + 3600
        quota_hold.note(self.target.state_dir, self.gateway, spent_text(self.reset))

    def turn(self, model, answer=None):
        from support import make_job

        job = make_job(job_id=7, chat_id="chat", message_id="m1", user_text="看下日志", prompt_text="看下日志",
                       topic_id=self.target.topic_id, workdir=self.target.workdir, history_path=self.target.history_path)
        seen = []

        def run(request):
            seen.append(request)
            if answer is None:
                raise JobCancelled("stop here")
            return answer
        with mock.patch.object(self.codex.backend, "run", side_effect=run):
            try:
                result = self.codex.runs.generate_reply_for_worker(dataclasses.replace(self.target, model=model), job,
                                                                   None, None)
            except JobCancelled:
                result = None
        return seen, result

    def test_a_turn_on_the_quota_or_a_route_sharing_it_never_starts_until_the_reset(self):
        for model in ("mygw/gpt-x", "mygw-personal/gpt-x"):
            seen, result = self.turn(model)
            self.assertEqual(seen, [], model)
            self.assertTrue(result.is_error)
            self.assertEqual(result.outcome.error_code, "quota_exhausted")
            self.assertIn("MyGW 的所有模型共用这一份额度", result.failure_detail)
            self.assertIn("可以换到 Codex 账号的模型（不带前缀）、Other Route（other/）或 Claude", result.failure_detail)
            self.assertEqual(result.text, result.failure_detail)
        seen, _ = self.turn("gpt-6-luna")  # Not on the quota: as before.
        self.assertEqual(len(seen), 1)
        with mock.patch.object(quota_hold, "time", SimpleNamespace(time=lambda: self.reset + 1)):
            seen, _ = self.turn("mygw/gpt-x")  # The reset has come: the turn runs.
        self.assertEqual(len(seen), 1)

    def test_a_turn_that_failed_on_the_quota_says_when_it_is_back_and_where_to_go(self):
        quota_hold.path(self.target.state_dir, self.gateway).unlink()  # The turn starts, then fails on it.
        outcome = ExecutionOutcome("failed", "quota_exhausted", cleanup_confirmed=True, protection_confirmed=True)
        failed = RunResult("Codex 模型服务的用量额度已用完，与任务内容无关。", "sid", True, None, outcome)

        def fails(request):
            quota_hold.note(self.target.state_dir, self.gateway, spent_text(self.reset))  # As its relay did.
            return failed
        with mock.patch.object(self.codex.backend, "run", side_effect=fails):
            from support import make_job
            job = make_job(job_id=8, chat_id="chat", message_id="m1", user_text="x", prompt_text="x",
                           topic_id=self.target.topic_id, workdir=self.target.workdir,
                           history_path=self.target.history_path)
            result = self.codex.runs.generate_reply_for_worker(dataclasses.replace(self.target, model="mygw/gpt-x"),
                                                               job, None, None)
        self.assertIn(quota_hold.clock(self.reset) + " 恢复", result.failure_detail)
        view = failure.failure_view({"status": "failed", "failure_code": "quota_exhausted", "topic_id": "t",
                                     "failure_detail": result.failure_detail})
        self.assertEqual(view["title"], result.failure_detail)
        self.assertEqual(view["actions"], [failure.SWITCH_MODEL])
        # Another quota (the Harness's own account) keeps the shared words.
        other = failure.failure_view({"status": "failed", "failure_code": "quota_exhausted", "topic_id": "t"})
        self.assertEqual(other["title"], failure.OWN["quota_exhausted"][0])


if __name__ == "__main__":
    unittest.main()
