from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class P018ShellDocumentationTests(unittest.TestCase):
    def test_posix_and_zsh_examples_parse_without_execution(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_p018_docs_shell.py")],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("commands_executed=no", result.stdout)
        self.assertIn("zsh_syntax", result.stdout)


if __name__ == "__main__":
    unittest.main()
