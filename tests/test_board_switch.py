"""菜单「看板」 in every deployment, 早晚汇总 off too (T813: COVEY_BOARD, which T604 added for a board without the
digest, is retired; a manifest that still sets it changes nothing). Before T604 看板 came only with COVEY_DIGEST_TIMES."""
from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

from support.world import UnifiedCase
from covey.app.digest import RECORD, Digest
from covey.core import app_manifest as manifest

CHAT = "oc_dm"


def menu(env):
    return [need.name for need in manifest.required(env, bottom_menu=True) if need.kind == "menu"]


def slash(env):
    return [item.key for item in manifest.slash_commands(env)]


class ManifestTest(unittest.TestCase):
    def test_the_app_always_needs_the_item(self):
        board = ["weekly_usage", "digest_board", "bridge_settings"]
        with mock.patch.object(manifest, "proxy_sender", return_value=False):
            for reader in (slash, menu):
                for env in ({}, {"COVEY_BOARD": "0"}, {"COVEY_DIGEST_TIMES": "off"}, {"COVEY_DIGEST_TIMES": "09:30"}):
                    with self.subTest(reader=reader.__name__, env=env):
                        self.assertEqual(reader(env), board)


class BoardMenuTest(UnifiedCase):
    def test_with_the_digest_off_the_menu_has_the_board_and_no_digest_runs(self):
        self.assertIn("digest_board", self.app.menu.actions)
        with mock.patch.dict(os.environ, {"COVEY_DIGEST_TIMES": "off"}):
            app = type(self.app)(script_path=self.app.runtime.script_path)
            self.assertEqual(app.digest.threads(), ())  # No 早晚汇总: no thread, nothing sent at any time.
        self.assertEqual((app.menu.actions["digest_board"].__func__, app.menu.folds["digest_board"].__func__),
                         (Digest.board, Digest.fold_board))

    def test_a_click_sends_the_board_of_the_last_day_and_writes_no_digest_record(self):
        puts = []
        messenger = self.app.messenger
        messenger.create_and_send_card = mock.Mock(side_effect=lambda profile, chat, card, key, **kw: (
            puts.append(card), ("bcard", f"om_board{len(puts)}"))[1])
        self.app.runtime.access.remember_owner_chat(CHAT)
        self.app.digest.link = lambda ctx, chat, text, cards=None: text  # No T links to look up.
        now = time.time()
        with mock.patch.dict(os.environ, {"COVEY_DIGEST_TIMES": "off"}):
            self.assertEqual(self.app.digest.board_view(self.ctx, CHAT, now=now)["since"], now - 86400)
            self.app.handle_menu_event({"event_id": "ev1", "event_key": "digest_board", "operator_open_id": "owner"},
                                       self.ctx)
        outcomes = [line.split("outcome=")[1] for line in self.logs if line.startswith("bot menu key=")]
        self.assertEqual((outcomes, len(puts)), (["digest_board"], 1))
        self.assertIn("还没有话题", json.dumps(puts[0], ensure_ascii=False))  # A chat that never had a topic (cards/board.py empty_state).
        self.assertFalse((self.ctx.state_dir / RECORD).exists())


if __name__ == "__main__":
    unittest.main()
