#!/usr/bin/env python3
"""Syntax-check P018 shell examples with POSIX sh and interactive zsh parsers."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = (ROOT / "docs/v0.2")
LANGUAGES = {"sh", "shell", "bash", "zsh"}
FORBIDDEN = re.compile(
    r"\bdpkg\s+(?:-i|--remove)\b|\blaunchctl\s+(?:load|bootstrap|enable|kickstart|start|restart|bootout)\b|"
    r"\b(?:reboot|respring|killall|pkill)\b|\b(?:ssh|tailscale)\b",
    re.I,
)


def blocks(path: Path):
    text = path.read_text(encoding="utf-8")
    for match in re.finditer(r"^```([A-Za-z0-9_-]*)\s*\n(.*?)^```\s*$", text,
                             flags=re.M | re.S):
        language = match.group(1).lower()
        if language in LANGUAGES:
            yield match.group(2)


def main() -> int:
    shell = shutil.which("zsh")
    if not shell:
        print("ERROR: zsh is required to validate interactive-shell examples", file=sys.stderr)
        return 1
    paths = sorted(DOCS.glob("P018-*.md")) + [DOCS / "OPERATOR-GUIDE.md"]
    checked = 0
    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-p018-shell-") as temporary:
        for path in paths:
            for index, body in enumerate(blocks(path), 1):
                for line in body.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if FORBIDDEN.search(stripped):
                        raise SystemExit(f"ERROR: unsafe command example in {path.name}:{index}")
                fixture = Path(temporary) / f"example-{checked}.sh"
                fixture.write_text(body, encoding="utf-8")
                for executable, label in (("/bin/sh", "POSIX sh"), (shell, "zsh")):
                    result = subprocess.run([executable, "-n", str(fixture)],
                                            capture_output=True, text=True, check=False)
                    if result.returncode:
                        raise SystemExit(f"ERROR: {label} syntax error in {path.name} example {index}: {result.stderr.strip()}")
                checked += 1
    print(f"p018_shell_examples_checked={checked}")
    print("shell_modes=POSIX_sh,zsh_syntax")
    print("commands_executed=no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
