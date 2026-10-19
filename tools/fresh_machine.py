"""Fresh-machine acceptance: install the wheel into a new venv, use it, remove it.

    python tools/fresh_machine.py dist/memory_fabric-*.whl

Runs outside the repository so nothing imports the source tree: the venv is
created in a temporary directory, the quickstart and the reference agent
are copied there and run against the *installed* package, `doctor` checks
the installed store, and `pip uninstall` must leave no importable package
and no console script. CI runs it on Linux, macOS and Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    print(done.stdout[-2000:], done.stderr[-2000:], sep="", flush=True)
    if check and done.returncode != 0:
        raise SystemExit(f"failed ({done.returncode}): {' '.join(cmd)}")
    return done


def main(wheel: str) -> int:
    work = Path(tempfile.mkdtemp(prefix="mf-fresh-"))
    venv = work / "venv"
    run(sys.executable, "-m", "venv", str(venv), cwd=work)
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    py = str(bindir / ("python.exe" if os.name == "nt" else "python"))
    cli = str(bindir / ("memory-fabric.exe" if os.name == "nt" else "memory-fabric"))
    run(py, "-m", "pip", "install", "--quiet", str(Path(wheel).resolve()), cwd=work)
    for example in ("quickstart.py", "reference_agent.py"):
        shutil.copy(ROOT / "examples" / example, work / example)
    run(py, str(work / "quickstart.py"), str(work / "q.db"), cwd=work)
    run(py, str(work / "reference_agent.py"), cwd=work)
    run(cli, "init", str(work / "memory"), cwd=work)
    doctor = run(cli, "--db", str(work / "memory" / "store.db"), "--keys",
                 str(work / "memory" / "keys"), "doctor", cwd=work, check=False)
    if doctor.returncode not in (0,):
        raise SystemExit("doctor did not report the fresh store sound")
    run(py, "-m", "pip", "uninstall", "--yes", "memory-fabric", cwd=work)
    left = run(py, "-c", "import memory_fabric", cwd=work, check=False)
    if left.returncode == 0 or Path(cli).exists():
        raise SystemExit("uninstall left the package or its console script behind")
    print("fresh-machine acceptance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
