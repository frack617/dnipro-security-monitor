import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_local_checks import run_checks


class CheckIsolationTests(unittest.TestCase):
    def test_actions_diagnostics_and_state_remain_unchanged_and_http_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'data').mkdir()
            names = ('gemini_debug.json', 'gemini_backup_debug.json', 'groq_debug.json',
                     'gemini_usage.json', 'alert_state.json')
            for name in names:
                (root / 'data' / name).write_bytes(b'production sentinel\n')
            (root / 'tests' / 'test_probe.py').write_text('''
import os
from pathlib import Path
import unittest
import requests
class Probe(unittest.TestCase):
    def test_probe(self):
        self.assertEqual(os.environ.get('GITHUB_ACTIONS'), 'true')
        self.assertNotIn('GEMINI_API_KEY', os.environ)
        self.assertNotIn('TELEGRAM_BOT_TOKEN', os.environ)
        for p in Path('data').iterdir():
            p.write_text('simulated test overwrite')
        Path('data/new_debug.json').write_text('test-only')
        with self.assertRaisesRegex(AssertionError, 'Real HTTP'):
            requests.get('https://example.invalid', timeout=1)
''')
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GEMINI_API_KEY': 'dummy',
                                         'TELEGRAM_BOT_TOKEN': 'dummy'}):
                self.assertEqual(run_checks(root), 0)
            for name in names:
                self.assertEqual((root / 'data' / name).read_bytes(), b'production sentinel\n')
            self.assertFalse((root / 'data/new_debug.json').exists())

    def test_failed_check_returns_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_probe.py').write_text(
                'import unittest\nclass Probe(unittest.TestCase):\n'
                '    def test_failure(self): self.fail("intentional probe")\n')
            real_run = subprocess.run
            with patch('run_local_checks.subprocess.run', side_effect=lambda *a, **kw:
                       real_run(*a, **kw, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)):
                self.assertEqual(run_checks(root), 1)
