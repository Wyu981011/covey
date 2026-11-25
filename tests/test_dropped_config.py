"""One account, one provider; an upgrade says what it drops (T786): core/dropped_config.py, core/same_account.py,
app/launch_models.py fold_same_account, core/providers.py menu_name, and the doctor's line."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from covey.app.launch_models import fold_same_account
from covey.core import dropped_config, gateways, providers, same_account
from covey.core.roster import NAMES
from covey.service import doctor_words

GATEWAY = {"display": "MyGW", "prefix": "mygw/", "base_url": "https://GW.example/v1/", "key_env": "MYGW_KEY",
           "harnesses": ["codex"]}


class DroppedTest(unittest.TestCase):
    def test_each_kind_of_configuration_a_release_no_longer_reads_is_listed_with_a_stable_key(self):
        other = next(name for name in ("claude", "codex") if name != NAMES[0])
        option = next(o for o, (h, _w, _i) in dropped_config.RETIRED_OPTIONS.items() if h == other)
        first = next((o for o, (h, _w, _i) in dropped_config.RETIRED_OPTIONS.items() if h == NAMES[0]), None)
        config = {"harnesses": {other: {"args": ["--keep", "x", option, "/somewhere"]}, "pi": {"args": []}},
                  "enabled_harnesses": [NAMES[0], "neeko-next"],
                  "gateways": {"old": {"harnesses": ["pi"]}, "live": {"harnesses": ["codex"]}}}
        argv = [first, "http://m"] if first else []
        items = dropped_config.dropped(config, argv, {"LARK_BRIDGE_CODEX_MODEL": "m"})
        keys = [item["key"] for item in items]
        self.assertIn(f"option:{other}:{option}", keys)
        if first:
            self.assertIn(f"option:{NAMES[0]}:{first}", keys)
        self.assertIn("harness:neeko-next", keys)
        self.assertIn("harness:pi", keys)
        self.assertIn("gateway:old", keys)
        self.assertNotIn("gateway:live", keys)
        self.assertIn("env:LARK_BRIDGE_CODEX_MODEL", keys)
        self.assertTrue(all(item["what"] and item["instead"] for item in items))

    def test_an_empty_value_or_the_default_harnesss_entry_in_harnesses_json_is_nothing(self):
        option = next(iter(dropped_config.RETIRED_OPTIONS))
        harness = dropped_config.RETIRED_OPTIONS[option][0]
        place = {"harnesses": {harness: {"args": [option + "="]}}}
        self.assertEqual(dropped_config.dropped(place, [option + "="], {}), [])
        self.assertEqual(dropped_config.dropped({}, [], {}), [])
        self.assertEqual(dropped_config.option_value(["--a", "--b"], "--a"), "")
        self.assertEqual(dropped_config.option_value(["--a=1"], "--a"), "1")

    def test_only_what_the_live_release_did_not_list_is_new_and_none_without_its_list(self):
        items = [{"key": "a"}, {"key": "b"}]
        self.assertEqual(dropped_config.newly(items, ["a"]), [{"key": "b"}])
        self.assertEqual(dropped_config.newly(items, None), [])

    def test_the_doctor_says_it_as_something_to_know(self):
        rows = doctor_words.service_rows({"status": "ready", "dropped_config": ["甲；乙"]}, "/s", "")
        found = [row for row in rows if "不再用" in row[1]]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], doctor_words.NOTE)
        self.assertIn("甲；乙", found[0][1])


class SameAccountTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        gateways.configure({"mygw": GATEWAY})
        self.addCleanup(gateways.configure, None)
        same_account.forget()
        self.addCleanup(same_account.forget)

    def codex(self, url, key_name="OWN_KEY"):
        (self.root / "config.toml").write_text(
            f'model_provider = "p"\n[model_providers.p]\nbase_url = "{url}"\nenv_key = "{key_name}"\n')
        return {"CODEX_HOME": str(self.root)}

    def test_codexs_own_login_at_a_gateways_address_with_its_key_is_that_gateway(self):
        env = {**self.codex("https://gw.example/v1"), "OWN_KEY": "sk-same", "MYGW_KEY": "sk-same"}
        self.assertEqual(same_account.folded("codex", env), ("mygw",))
        self.assertEqual(same_account.folded("codex", {**env, "MYGW_KEY": "sk-other"}), ())  # Another key: another account.
        self.assertEqual(same_account.folded("codex", {**env, **self.codex("https://else.example/v1")}), ())

    def test_a_login_that_names_no_address_folds_nothing(self):
        (self.root / "config.toml").write_text('model = "gpt"\n')
        self.assertEqual(same_account.folded("codex", {"CODEX_HOME": str(self.root), "MYGW_KEY": "k"}), ())
        self.assertIsNone(same_account.own_login("agy", {}))

    def test_claudes_settings_env_is_its_login(self):
        (self.root / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://a.example/",
                                                                     "ANTHROPIC_AUTH_TOKEN": "tok-secret"}}))
        found = same_account.own_login("claude", {"CLAUDE_CONFIG_DIR": str(self.root)})
        self.assertEqual(found, ("https://a.example", same_account.digest("tok-secret")))
        self.assertNotIn("tok-secret", json.dumps(found))  # Only its digest.


class FoldTest(unittest.TestCase):
    def setUp(self):
        gateways.configure({"mygw": GATEWAY})
        self.addCleanup(gateways.configure, None)

    @staticmethod
    def entries():
        own = {"harness": "codex", "provider": "openai", "provider_title": "Codex 自带", "title": "Codex"}
        return {"codex:gpt-6": {**own, "model": "gpt-6", "display_name": "GPT-6", "label": "Codex · GPT-6"},
                "codex:only-own": {**own, "model": "only-own", "display_name": "Only Own", "label": "Codex · Only Own"},
                "codex:mygw/gpt-6": {"harness": "codex", "model": "mygw/gpt-6", "display_name": "GPT-6 (MyGW)",
                                     "provider": "mygw", "provider_title": "MyGW", "source": "MyGW", "title": "Codex",
                                     "label": "Codex · MyGW · GPT-6 (MyGW)"}}

    def test_one_account_is_one_provider_on_the_menu(self):
        with mock.patch.object(same_account, "folded", return_value=("mygw",)):
            result = fold_same_account(self.entries())
            name = providers.menu_name(providers.provider_of("codex", "gpt-6"), "Codex")
        self.assertNotIn("codex:gpt-6", result)  # The gateway offers it: listed once, the gateway's.
        self.assertEqual({entry["provider"] for entry in result.values()}, {"mygw"})
        self.assertEqual(result["codex:only-own"]["label"], "Codex · MyGW · Only Own")
        self.assertEqual(result["codex:only-own"]["model"], "only-own")  # Still the own login's id: it runs as before.
        self.assertEqual(name, "MyGW")

    def test_without_one_nothing_changes(self):
        with mock.patch.object(same_account, "folded", return_value=()):
            self.assertEqual(fold_same_account(self.entries()), self.entries())
            self.assertEqual(providers.menu_name(providers.provider_of("codex", "gpt-6"), "Codex"), "Codex 自带")


if __name__ == "__main__":
    unittest.main()
