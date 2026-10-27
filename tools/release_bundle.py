"""Build the release evidence bundle for the exact commit checked out.

    python tools/release_bundle.py [--out dist/release-evidence] [--wheel dist/*.whl]

Writes `<out>/<sha>/`:

- `manifest.json`: commit, dirty flag, package and schema versions, Python,
  platform, timestamps, and the sha256 of every file in the bundle;
- `sbom.cdx.json`: a CycloneDX 1.5 SBOM. The core has no runtime
  dependencies; optional extras are listed as optional components;
- `secret-scan.txt`: `tools/scan_secrets.py` output and exit code;
- `adversarial-gate.json`: `tools/adversarial_gate.py` per-family results;
- `tests.json`: the unit suite's counts and failures;
- `wheel.sha256`: the hash of each wheel passed with `--wheel`;
- `product-bench.json`: `experiments.product_bench` (quality, latency,
  throughput, growth, false blocks), with `--bench quick|full`;
- `RELEASE_REPORT.md`: all of the above as one page (`tools/release_report.py`);
- `LIMITATIONS.md`, `STABILITY.md`: what this release does not claim.

It exits non-zero if the tree is dirty, the scan finds anything, the gate
fails or any test fails: a bundle exists only for a releasable commit.
`--allow-dirty` builds one anyway, marked dirty, for rehearsal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT,
                          check=True).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sbom(project: dict) -> dict:
    components = []
    for extra, deps in sorted(project.get("optional-dependencies", {}).items()):
        for dep in deps:
            name = dep.split(">")[0].split("=")[0].split("<")[0].strip()
            components.append({"type": "library", "name": name, "version": dep[len(name):],
                               "scope": "optional",
                               "properties": [{"name": "extra", "value": extra}]})
    for dep in project.get("dependencies", []):
        name = dep.split(">")[0].split("=")[0].strip()
        components.append({"type": "library", "name": name, "version": dep[len(name):],
                           "scope": "required"})
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "component": {"type": "library", "name": project["name"],
                                       "version": project["version"]}},
            "components": components}


def run_tests() -> dict:
    sys.path.insert(0, str(ROOT))
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TestResult()
    suite.run(result)
    return {"run": result.testsRun, "skipped": len(result.skipped),
            "failures": [str(t) for t, _ in result.failures],
            "errors": [str(t) for t, _ in result.errors],
            "passed": result.wasSuccessful()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "release-evidence")
    parser.add_argument("--wheel", type=Path, nargs="*", default=[])
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-tests", action="store_true",
                        help="when CI has just run the suite on this commit")
    parser.add_argument("--bench", choices=["none", "quick", "full"], default="none",
                        help="run experiments.product_bench into the bundle")
    args = parser.parse_args(argv)

    sha = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    if dirty and not args.allow_dirty:
        print("the tree is dirty; commit first, or pass --allow-dirty to rehearse")
        return 2
    out = args.out / sha[:12]
    out.mkdir(parents=True, exist_ok=True)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    sys.path.insert(0, str(ROOT))
    from memory_fabric.model import SCHEMA_VERSION

    (out / "sbom.cdx.json").write_text(json.dumps(sbom(project), indent=2), encoding="utf-8")
    scan = subprocess.run([sys.executable, str(ROOT / "tools" / "scan_secrets.py")],
                          capture_output=True, text=True, cwd=ROOT)
    (out / "secret-scan.txt").write_text(f"exit {scan.returncode}\n{scan.stdout}{scan.stderr}",
                                         encoding="utf-8")
    gate = subprocess.run([sys.executable, str(ROOT / "tools" / "adversarial_gate.py"),
                           "--report", str(out / "adversarial-gate.json")],
                          capture_output=True, text=True, cwd=ROOT)
    tests = {"skipped_here": True} if args.skip_tests else run_tests()
    (out / "tests.json").write_text(json.dumps(tests, indent=2), encoding="utf-8")
    if args.wheel:
        (out / "wheel.sha256").write_text(
            "".join(f"{sha256(w)}  {w.name}\n" for w in args.wheel), encoding="utf-8")
    bench_ok = True
    if args.bench != "none":
        bench = subprocess.run([sys.executable, "-m", "experiments.product_bench",
                                "--out", str(out / "product-bench.json"),
                                *(["--quick"] if args.bench == "quick" else [])],
                               capture_output=True, text=True, cwd=ROOT)
        bench_ok = bench.returncode == 0
    status = subprocess.run([sys.executable, str(ROOT / "tools" / "status_at_head.py"), "--sha", sha],
                            capture_output=True, text=True, cwd=ROOT)
    (out / "STATUS_AT_HEAD.md").write_text(status.stdout, encoding="utf-8")
    consistent = subprocess.run([sys.executable, str(ROOT / "tools" / "status_at_head.py"), "--check"],
                                capture_output=True, text=True, cwd=ROOT).returncode == 0
    for doc in ("docs/LIMITATIONS.md", "STABILITY.md"):
        shutil.copy(ROOT / doc, out / Path(doc).name)

    checks = {"clean tree": not dirty, "secret scan": scan.returncode == 0,
              "adversarial gate": gate.returncode == 0,
              "tests": bool(tests.get("passed", args.skip_tests)), "benchmark": bench_ok,
              "versions consistent": consistent}
    manifest = {"commit": sha, "dirty": dirty, "package_version": project["version"],
                "schema_version": SCHEMA_VERSION, "python": platform.python_version(),
                "platform": platform.platform(),
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "checks": checks,
                "files": {p.name: sha256(p) for p in sorted(out.iterdir())
                          if p.name != "manifest.json"}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    from release_report import render  # tools/ is this script's directory

    (out / "RELEASE_REPORT.md").write_text(render(out), encoding="utf-8")
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    print(f"bundle: {out}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
