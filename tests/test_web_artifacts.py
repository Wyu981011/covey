"""网页工作台的产物 (data contract v32, app/web_turns.py artifacts_of, app/web_collect.py Collector.artifacts): an answer turn carries the
files its answer card lists, each by its own name only (no local path goes to the page), with its cloud-space link and size once up, why it
could not go up, or that it is going up; configuration and credential paths are left off as on the card; a finished upload goes to the
page again; the upload's ledger is found for a long job key too (core/checkpoint.py upload_ledger)."""
from __future__ import annotations

import hashlib
from unittest import mock

from support.records import write_job

from covey.app import web_collect as app_collect, web_turns
from covey.core import web_sync
from covey.core.checkpoint import UPLOADS, artifact_key, upload_ledger
from covey.core.state import epoch_seconds, write_json

from test_web_sync import T0, TOPIC, WebCase

REPORT, PATCH, SECRET = "/abs/work/out/REPORT.md", "out/diff.patch", "/abs/work/.ssh/id_rsa"
LINK = "https://example.feishu.cn/file/boxcnREPORT"


class ArtifactsTest(WebCase):
    def answered(self, artifacts=(REPORT, PATCH, SECRET), **fields):
        """T7 with one answered turn whose checkpoint lists ``artifacts``; its job record."""
        self.topic()
        checkpoint = self.state / "checkpoint.json"
        write_json(checkpoint, {"phase": "做完", "artifacts": list(artifacts)})
        return write_job(self.state, f"k-{TOPIC[:4]}", checkpoint_path=str(checkpoint), workdir="/abs/work", **fields)

    def ledger(self, record, **fields):
        write_json(self.state / UPLOADS / f"{record['key']}.json", fields)

    def pushed(self, now=T0):
        self.sync.push_once(now)
        return {item["key"]: item["data"] for item in self.web.items("turn")}

    def test_an_answer_carries_its_files_by_name_with_their_links(self):
        record = self.answered()
        self.ledger(record, status="done", folder_url="https://example.feishu.cn/drive/folder/x",
                    files={artifact_key(REPORT): {"name": "REPORT.md", "size": 3400, "sha256": "0" * 64, "token": "t", "url": LINK}},
                    errors={artifact_key(PATCH): "产物文件不存在"})
        turns = self.pushed()
        self.assertEqual(turns[f"{TOPIC}:2"]["artifacts"], [{"name": "REPORT.md", "link": LINK, "size": 3400},
                                                            {"name": "diff.patch", "error": "产物文件不存在"}])
        self.assertEqual(turns[f"{TOPIC}:1"]["artifacts"], [])  # The owner's words have none.
        # Names only: the page never sees where a file is, nor the credential the checkpoint listed.
        sent = str(turns[f"{TOPIC}:2"])
        self.assertNotIn("/abs/work", sent)
        self.assertNotIn("id_rsa", sent)

    def test_while_the_upload_runs_they_read_uploading_and_a_finished_upload_goes_again(self):
        record = self.answered(artifacts=(REPORT,))
        self.ledger(record, status="uploading", files={}, errors={})
        self.assertEqual(self.pushed()[f"{TOPIC}:2"]["artifacts"], [{"name": "REPORT.md", "uploading": True}])
        self.ledger(record, status="done", files={artifact_key(REPORT): {"name": "REPORT.md", "size": 3400, "url": LINK}}, errors={})
        # The upload ends after the turn: its record does not change, the next full look (FULL_SECONDS, longer than FILES_GOING) reads
        # the ledger again and the page gets the link.
        self.assertGreater(web_sync.FULL_SECONDS, app_collect.FILES_GOING)
        self.assertEqual(self.pushed(T0 + web_sync.FULL_SECONDS + 1)[f"{TOPIC}:2"]["artifacts"], [{"name": "REPORT.md", "link": LINK, "size": 3400}])

    def test_a_settled_upload_is_read_again_only_after_a_while_and_only_when_its_ledger_changed(self):
        record = self.answered(artifacts=(REPORT,))
        self.ledger(record, status="done", files={artifact_key(REPORT): {"name": "REPORT.md", "size": 3400, "url": LINK}}, errors={})
        collector = self.sync.collector
        collector.now = T0
        with mock.patch.object(web_turns, "artifacts_of", wraps=web_turns.artifacts_of) as read:
            first = collector.artifacts(self.state, record)
            collector.now = T0 + app_collect.FILES_SETTLED - 1
            self.assertIs(collector.artifacts(self.state, record), first)
            self.assertEqual(read.call_count, 1)
            # Its ledger as it was: what it lists is not read again (T678: every 产物's paths resolved again every FILES_SETTLED were
            # 197 thousand lstats a pass of the live topics).
            collector.now = T0 + app_collect.FILES_SETTLED + 1
            self.assertIs(collector.artifacts(self.state, record), first)
            self.assertEqual(read.call_count, 1)
            again = LINK + "-again"
            self.ledger(record, status="done", files={artifact_key(REPORT): {"name": "REPORT.md", "size": 3400, "url": again}}, errors={})
            collector.now = T0 + 2 * app_collect.FILES_SETTLED + 2  # 重新上传 on a card rewrites the ledger alone: it is read again.
            self.assertEqual(collector.artifacts(self.state, record), [{"name": "REPORT.md", "link": again, "size": 3400}])
            self.assertEqual(read.call_count, 2)

    def test_without_a_ledger_a_file_is_uploading_only_just_after_its_turn(self):
        record = self.answered(artifacts=(REPORT,))
        at = epoch_seconds(record["updated_at"])
        self.assertEqual(web_turns.artifacts_of(self.state, record, at + 5), [{"name": "REPORT.md", "uploading": True}])
        self.assertEqual(web_turns.artifacts_of(self.state, record, at + web_turns.UPLOAD_WAIT + 1), [{"name": "REPORT.md"}])

    def test_a_turn_without_artifacts_has_none_and_is_read_once(self):
        record = self.answered(artifacts=())
        with mock.patch.object(web_turns, "artifacts_of", wraps=web_turns.artifacts_of) as read:
            self.assertEqual(self.pushed()[f"{TOPIC}:2"]["artifacts"], [])
            self.pushed(T0 + app_collect.FILES_SETTLED + 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(web_turns.artifacts_of(self.state, dict(record, checkpoint_path=str(self.state / "gone.json")), T0), [])

    def test_a_link_that_is_not_https_is_not_sent(self):
        record = self.answered(artifacts=(REPORT,))
        self.ledger(record, status="done", files={artifact_key(REPORT): {"name": "REPORT.md", "size": 1, "url": "javascript:alert(1)"}})
        self.assertEqual(web_turns.artifacts_of(self.state, record, T0 + web_turns.UPLOAD_WAIT * 10), [{"name": "REPORT.md"}])


class UploadLedgerTest(WebCase):
    def test_a_long_job_key_is_found_by_its_digest_after_any_harness_prefix(self):
        key = "collab-" + "a" * 24 + "-reply-1-" + "b" * 30
        name = "co-" + hashlib.sha1(key.encode()).hexdigest()[:24]
        write_json(self.state / UPLOADS / f"{name}.json", {"status": "done"})
        self.assertEqual(upload_ledger(self.state, key), {"status": "done"})
        self.assertEqual(upload_ledger(self.state, "om_short"), {})
