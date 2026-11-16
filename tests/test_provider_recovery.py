import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from covey.backends.claude.bridge import ClaudeBackend

class ConfiguredProviderRecoveryTest(unittest.TestCase):
    def test_configured_providers_are_visible_without_network(self):
        backend = ClaudeBackend()
        parser = argparse.ArgumentParser()
        backend.add_cli_args(parser)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profiles.json"
            path.write_text(json.dumps({"version": 1, "profiles": [
                {"id": "fixture_a", "name": "Fixture A", "status": "ready", "command": ["/bin/false"], "models": [{"id": "opus", "display_name": "Fixture Opus", "efforts": ["high"]}]},
                {"id": "fixture_b", "name": "Fixture B", "status": "ready", "command": ["/bin/false"], "models": [{"id": "claude/fixture", "display_name": "Fixture Model", "efforts": ["high"]}]}
            ]}))
            ctx = backend.build_config(parser.parse_args(["--claude-profiles", str(path)]))
            with patch.object(backend, "child_env", return_value={}), patch("covey.backends.claude.bridge.model_catalog", return_value={}):
                catalog = backend.model_catalog(ctx)
            self.assertIn("profile/fixture_a/opus", catalog)
            self.assertIn("profile/fixture_b/claude/fixture", catalog)
