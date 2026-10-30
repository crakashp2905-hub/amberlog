"""Check an installed wheel's PEP 561 API with positive and negative consumers.

Requires mypy in the invoking development environment, never in the core wheel.
Runs outside the checkout and clears source-path overrides for every subprocess.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="memory_fabric-types-") as directory:
        root = Path(directory)
        venv = root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, env=env, cwd=root)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
                       check=True, env=env, cwd=root, capture_output=True)
        check = "import memory_fabric; from pathlib import Path; "
        check += f"assert Path(memory_fabric.__file__).resolve().is_relative_to(Path({str(venv)!r}).resolve())"
        subprocess.run([str(python), "-c", check], check=True, env=env, cwd=root)
        positive = root / "positive.py"
        positive.write_text(
            'from typing import assert_type\nfrom memory_fabric import MemoryFabric\n'
            'from memory_fabric.sdk import agent\n'
            'with MemoryFabric(":memory:") as store:\n'
            '    assert_type(store.remember("agent", "A reviewed fact."), str)\n'
            '    assert_type(agent(store, "agent").agent_id, str)\n', encoding="utf-8")
        negative = root / "negative.py"
        negative.write_text(
            'from memory_fabric import MemoryFabric\nwith MemoryFabric(":memory:") as store:\n'
            '    wrong: int = store.remember("agent", "A reviewed fact.")\n', encoding="utf-8")
        command = [sys.executable, "-m", "mypy", "--strict", "--follow-imports=silent",
                   "--python-executable", str(python)]
        passed = subprocess.run([*command, str(positive)], cwd=root, env=env,
                                capture_output=True, text=True)
        rejected = subprocess.run([*command, str(negative)], cwd=root, env=env,
                                  capture_output=True, text=True)
        if passed.returncode or rejected.returncode != 1 or "[assignment]" not in rejected.stdout:
            print(passed.stdout, passed.stderr, rejected.stdout, rejected.stderr)
            return 1
    print("Installed-wheel typed consumer: positive accepted, incompatible assignment rejected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
