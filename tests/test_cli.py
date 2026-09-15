"""Exercise the public CLI; the subprocess double represents Codex's RPC boundary."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CLIModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)
        self.codex = self.path / "codex"
        self.codex.write_text("""#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    result = {}
    if request['method'] == 'model/list':
        result = {'data': [
            {'model': 'gpt-example', 'displayName': 'GPT Example', 'hidden': False,
             'supportedReasoningEfforts': [{'reasoningEffort': x} for x in ['low', 'high', 'ultra']],
             'defaultReasoningEffort': 'high'},
            {'model': 'gpt-hidden', 'hidden': True, 'supportedReasoningEfforts': []}
        ], 'nextCursor': None}
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
""")
        self.codex.chmod(0o755)

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-m", "src", "--codex", str(self.codex), "--state-dir", str(self.path / 'state'), *args], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}, capture_output=True, text=True, timeout=15)

    def install_args(self):
        return ['--state-dir', str(self.path / 'state'), '--claude-dir', str(self.path / 'claude'), '--bin-dir', str(self.path / 'bin'), '--proxy-binary', str(self.codex), '--no-service']

    def test_models_show_account_models_and_supported_efforts_without_ultra(self):
        result = self.run_cli("models", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [{"id": "gpt-example", "name": "GPT Example", "efforts": ["low", "high"], "default_effort": "high"}])

    def test_install_and_reinstall_preserve_user_settings_and_create_picker(self):
        claude_dir = self.path / 'claude'
        claude_dir.mkdir()
        original = {'model': 'opus', 'hooks': {'Stop': []}, 'env': {'KEEP_ME': 'yes'}}
        (claude_dir / 'settings.json').write_text(json.dumps(original))
        args = [*self.install_args(), 'install']
        first = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        settings = json.loads((claude_dir / 'settings.json').read_text())
        self.assertEqual(settings['model'], 'opus')
        self.assertEqual(settings['hooks'], {'Stop': []})
        self.assertEqual(settings['env']['KEEP_ME'], 'yes')
        self.assertEqual([r['model'] for r in settings['modelPicker']['options']], ['gpt-example'])
        self.assertIn('ANTHROPIC_BASE_URL', settings['env'])
        self.assertNotIn('ANTHROPIC_API_KEY', settings['env'])
        second = self.run_cli(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads((claude_dir / 'settings.json').read_text()), settings)
        self.assertTrue((self.path / 'bin' / 'gpt-in-claude').is_file())

    def test_uninstall_removes_our_settings_and_preserves_later_user_edits(self):
        self.assertEqual(self.run_cli(*self.install_args(), 'install').returncode, 0)
        path = self.path / 'claude' / 'settings.json'
        settings = json.loads(path.read_text())
        settings['theme'] = 'new-theme'
        settings['env']['MY_NEW_VARIABLE'] = 'keep'
        path.write_text(json.dumps(settings))
        result = self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text()), {'theme': 'new-theme', 'env': {'MY_NEW_VARIABLE': 'keep'}})
        self.assertFalse((self.path / 'bin' / 'gpt-in-claude').exists())

    def test_reinstall_keeps_an_existing_custom_row_for_the_same_model(self):
        path = self.path / 'claude' / 'settings.json'
        path.parent.mkdir()
        custom = {'model': 'gpt-example', 'label': 'My existing label'}
        path.write_text(json.dumps({'modelPicker': {'options': [custom]}}))
        for _ in range(2):
            result = self.run_cli(*self.install_args(), 'install')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text())['modelPicker']['options'], [custom])

    def test_sync_discovers_a_new_model_without_reinstalling(self):
        self.assertEqual(self.run_cli(*self.install_args(), 'install').returncode, 0)
        self.codex.write_text(self.codex.read_text().replace('gpt-example', 'gpt-new-release').replace('GPT Example', 'GPT New Release'))
        result = self.run_cli('--state-dir', str(self.path / 'state'), 'sync')
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((self.path / 'claude' / 'settings.json').read_text())
        self.assertEqual([r['model'] for r in settings['modelPicker']['options']], ['gpt-new-release'])
        self.assertNotIn('gpt-example', settings['modelSettings'])

    def test_reinstall_after_removal_uses_the_new_upstream_and_recovery_baseline(self):
        self.assertEqual(self.run_cli(*self.install_args(), 'install').returncode, 0)
        self.assertEqual(self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall').returncode, 0)
        path = self.path / 'claude' / 'settings.json'
        new_settings = {'model': 'sonnet', 'env': {'ANTHROPIC_BASE_URL': 'https://new-gateway.example.com', 'ANTHROPIC_AUTH_TOKEN': 'new-provider-token'}}
        path.write_text(json.dumps(new_settings))
        result = self.run_cli(*self.install_args(), 'install')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.path / 'state' / 'config.json').read_text())
        self.assertEqual(config['claude_base_url'], 'https://new-gateway.example.com')
        self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall')
        self.assertEqual(json.loads(path.read_text()), new_settings)

    def test_installer_preserves_an_upstream_configured_in_the_shell(self):
        result = self.run_cli(*self.install_args(), 'install', env={'ANTHROPIC_BASE_URL': 'https://shell-gateway.example.com'})
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.path / 'state' / 'config.json').read_text())
        self.assertEqual(config['claude_base_url'], 'https://shell-gateway.example.com')

    def test_sync_replaces_a_retired_selected_model_and_uninstall_restores_default(self):
        self.assertEqual(self.run_cli(*self.install_args(), 'install').returncode, 0)
        path = self.path / 'claude' / 'settings.json'
        settings = json.loads(path.read_text())
        settings['model'] = 'gpt-example'
        path.write_text(json.dumps(settings))
        self.codex.write_text(self.codex.read_text().replace('gpt-example', 'gpt-new-release'))
        self.assertEqual(self.run_cli('--state-dir', str(self.path / 'state'), 'sync').returncode, 0)
        self.assertEqual(json.loads(path.read_text())['model'], 'gpt-new-release')
        self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall')
        self.assertNotIn('model', json.loads(path.read_text()))

    def test_sync_keeps_the_installed_codex_home_in_a_different_shell(self):
        home_a = self.path / 'account-a'
        home_b = self.path / 'account-b'
        script = self.codex.read_text().replace('import json, sys', 'import json, sys, os')
        script = script.replace("'gpt-example'", "'gpt-account-a' if os.environ.get('CODEX_HOME', '').endswith('account-a') else 'gpt-account-b'")
        self.codex.write_text(script)
        self.assertEqual(self.run_cli(*self.install_args(), 'install', env={'CODEX_HOME': str(home_a)}).returncode, 0)
        result = self.run_cli('--state-dir', str(self.path / 'state'), 'sync', env={'CODEX_HOME': str(home_b)})
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.path / 'state' / 'config.json').read_text())
        self.assertEqual(config['models'][0]['id'], 'gpt-account-a')

    def test_reinstall_and_background_sync_cannot_overwrite_each_others_state(self):
        self.assertEqual(self.run_cli(*self.install_args(), 'install').returncode, 0)
        marker = self.path / 'sync-ready'
        release = self.path / 'sync-release'
        script = self.codex.read_text().replace('import json, sys', 'import json, sys, os, pathlib, time')
        script = script.replace("    print(json.dumps", "    if request['method'] == 'model/list' and os.environ.get('PAUSE_SYNC'):\n        pathlib.Path(os.environ['PAUSE_SYNC']).write_text('ready')\n        while not pathlib.Path(os.environ['RELEASE_SYNC']).exists(): time.sleep(0.02)\n    print(json.dumps")
        self.codex.write_text(script)
        base = [sys.executable, '-m', 'src', '--codex', str(self.codex), '--state-dir', str(self.path / 'state')]
        sync = subprocess.Popen([*base, 'sync'], cwd=ROOT, env={**os.environ, 'PAUSE_SYNC': str(marker), 'RELEASE_SYNC': str(release)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: sync.poll() is None and sync.kill())
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), 'sync never reached its external model query')
        self.codex.write_text(script.replace('gpt-example', 'gpt-new-release'))
        install = subprocess.Popen([*base, *self.install_args(), 'install'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: install.poll() is None and install.kill())
        try:
            install.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        finally:
            release.touch()
        sync.communicate(timeout=10)
        stdout, stderr = install.communicate(timeout=10)
        self.assertEqual(install.returncode, 0, stderr)
        config = json.loads((self.path / 'state' / 'config.json').read_text())
        self.assertEqual(config['models'][0]['id'], 'gpt-new-release')
        self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall')
        settings = json.loads((self.path / 'claude' / 'settings.json').read_text())
        self.assertNotIn('modelPicker', settings)

    def test_install_generates_selectable_subagents_for_every_model_effort(self):
        result = self.run_cli(*self.install_args(), 'install')
        self.assertEqual(result.returncode, 0, result.stderr)
        agents = self.path / 'claude' / 'agents'
        self.assertEqual(sorted(p.name for p in agents.glob('*.md')), ['codex-gpt-example-high.md', 'codex-gpt-example-low.md'])
        definition = (agents / 'codex-gpt-example-high.md').read_text()
        self.assertIn('model: gpt-example\n', definition)
        self.assertIn('effort: high\n', definition)
        self.run_cli('--state-dir', str(self.path / 'state'), 'uninstall')
        self.assertEqual(list(agents.glob('*.md')), [])


if __name__ == "__main__":
    unittest.main()
