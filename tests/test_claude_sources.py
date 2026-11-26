"""Own model sources through extensions: every package's ``claude_turn`` nested in the order enabled, and the
``claude_models`` hook's rows joined to the Claude catalog (prefix check, a failing hook leaves the native one)."""
from __future__ import annotations

import contextlib
import dataclasses
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from covey.backends.claude import bridge, models
from covey.core import extensions

PROVIDER = {"key": "acme", "harness": "claude", "name": "Acme", "prefix": "acme/", "access": "wrapper"}


def extension(package, hooks=("claude_models",), providers=(PROVIDER,)):
    return extensions.Extension(package, {}, tuple(providers), {}, {}, hooks={name: f"{package}.{name}" for name in hooks})


def row(slug):
    return models.catalog_row(slug, slug, "", ["low", "high"], "")


class NestingTests(unittest.TestCase):
    def hook(self, tag, seen):
        @contextlib.contextmanager
        def turn(ctx, env, *, run_id=""):
            seen.append(("enter", tag, ctx.model))
            try:
                yield dataclasses.replace(ctx, model=f"{ctx.model}+{tag}"), {**env, tag: "1"}
            finally:
                seen.append(("exit", tag))
        return SimpleNamespace(turn=turn)

    def test_every_package_wraps_the_turn_first_enabled_outermost(self):
        seen = []
        ctx = dataclasses.make_dataclass("C", [("model", str), ("options", dict)])("m", {})  # as BridgeContext
        pairs = [("a", self.hook("a", seen)), ("b", self.hook("b", seen))]
        with mock.patch.object(extensions, "hooks", return_value=pairs):
            with bridge._extension_turn(ctx, {}, run_id="r") as (inner, env):
                self.assertEqual((inner.model, sorted(env)), ("m+a+b", ["a", "b"]))
        self.assertEqual(seen, [("enter", "a", "m"), ("enter", "b", "m+a"), ("exit", "b"), ("exit", "a")])

    def test_one_package_or_none_behaves_as_before(self):
        seen = []
        ctx = dataclasses.make_dataclass("C", [("model", str), ("options", dict)])("m", {})  # as BridgeContext
        with mock.patch.object(extensions, "hooks", return_value=[("a", self.hook("a", seen))]):
            with bridge._extension_turn(ctx, {}) as (inner, _env):
                self.assertEqual(inner.model, "m+a")
        with mock.patch.object(extensions, "hooks", return_value=[]):
            with bridge._extension_turn(ctx, {"k": "v"}) as (inner, env):
                self.assertEqual((inner, env), (ctx, {"k": "v"}))


class ModelsTests(unittest.TestCase):
    def setUp(self):
        models._REPORTED.clear()

    def patch(self, *exts, mods):
        def hook_module(package, name):
            return SimpleNamespace(models=mods[package])
        return mock.patch.multiple(extensions, manifests=mock.Mock(return_value=tuple(exts)), hook_module=hook_module)

    def test_rows_with_a_declared_prefix_join_the_catalog_and_native_rows_win(self):
        native = {"opus": row("opus"), "acme/x": row("acme/x")}
        with self.patch(extension("one"), mods={"one": lambda: [row("acme/x"), row("acme/y")]}):
            merged = models.with_extension_models(native)
        self.assertEqual(sorted(merged), ["acme/x", "acme/y", "opus"])
        self.assertIs(merged["acme/x"], native["acme/x"])

    def test_a_row_outside_the_packages_own_prefix_is_dropped_and_logged_once(self):
        other = dict(PROVIDER, prefix="other/", key="other")
        exts = (extension("one"), extension("two", providers=(other,)))
        mods = {"one": lambda: [row("other/z"), row("plain"), {"slug": 3}], "two": lambda: [row("other/z")]}
        with self.patch(*exts, mods=mods), self.assertLogs(models.LOG, "WARNING") as logs:
            self.assertEqual(sorted(models.extension_models()), ["other/z"])
            models.extension_models()
        self.assertEqual(len(logs.records), 3)  # other/z of one, plain, 3: once each across two calls.

    def test_a_non_claude_provider_does_not_declare_a_prefix(self):
        codex = dict(PROVIDER, harness="codex")
        with self.patch(extension("one", providers=(codex,)), mods={"one": lambda: [row("acme/x")]}), \
                self.assertLogs(models.LOG, "WARNING"):
            self.assertEqual(models.extension_models(), {})

    def test_a_failing_or_slow_hook_leaves_the_native_catalog(self):
        def slow():
            time.sleep(1)
            return [row("acme/late")]

        def boom():
            raise RuntimeError("down")
        native = {"opus": row("opus")}
        with mock.patch.object(models, "EXTENSION_MODELS_TIMEOUT", 0.05):
            for hook in (boom, slow):
                models._REPORTED.clear()
                with self.patch(extension("one"), mods={"one": hook}), self.assertLogs(models.LOG, "WARNING"):
                    self.assertEqual(models.with_extension_models(native), native)

    def test_no_extension_changes_nothing(self):
        native = {"opus": row("opus")}
        with mock.patch.object(extensions, "manifests", return_value=()):
            self.assertIs(models.with_extension_models(native), native)

    def test_the_backend_catalog_carries_the_rows(self):
        backend = bridge.ClaudeBackend()
        with mock.patch.object(bridge, "model_catalog", return_value={"opus": row("opus")}), \
                self.patch(extension("one"), mods={"one": lambda: [row("acme/x")]}), \
                mock.patch.object(backend, "child_env", return_value={}):
            self.assertEqual(sorted(backend.model_catalog(SimpleNamespace())), ["acme/x", "opus"])


if __name__ == "__main__":
    unittest.main()
