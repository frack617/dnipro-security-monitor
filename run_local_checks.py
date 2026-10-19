"""Run offline regression checks in a disposable repository copy.

Some tests deliberately emulate GitHub Actions and write provider diagnostics.
Those writes must never replace production drafts or quota/delivery state.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CHECK_SCRIPT = r'''
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, '.')
sys.path.insert(0, 'tests')
with patch('requests.sessions.Session.request', side_effect=AssertionError(
        'Real HTTP requests are disabled during local checks')):
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('tests'))
sys.exit(not result.wasSuccessful())
'''


def run_checks(source=None):
    source = Path(source or __file__).resolve()
    if source.is_file():
        source = source.parent
    env = {k: v for k, v in os.environ.items()
           if not (k.endswith('_API_KEY') or k.endswith('_TOKEN')
                   or k in {'TELEGRAM_CHAT_ID', 'PYTHONPATH'})}
    with tempfile.TemporaryDirectory(prefix='dnipro-checks-') as folder:
        snapshot = Path(folder) / 'snapshot'
        shutil.copytree(source, snapshot,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', '.venv', 'venv', '*.pyc'))
        print('Локальні тести: тимчасова копія, реальні HTTP-запити заблоковані.', flush=True)
        return subprocess.run([sys.executable, '-c', CHECK_SCRIPT], cwd=snapshot, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(run_checks())
