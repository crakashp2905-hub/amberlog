"""Resolve a historical checkout's actual declared package without import aliases."""
from __future__ import annotations

import importlib
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from types import ModuleType


def namespace_at(checkout: Path) -> str:
    data = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    includes = data["tool"]["setuptools"]["packages"]["find"]["include"]
    candidates = [name.rstrip("*") for name in includes]
    candidates = [name for name in candidates if name.isidentifier() and (checkout / name).is_dir()]
    if len(candidates) != 1:
        raise ValueError("checkout must declare exactly one implementation package")
    return candidates[0]


@lru_cache(maxsize=32)
def load_from_checkout(checkout: Path, suffix: str) -> ModuleType:
    checkout = checkout.resolve()
    if str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    module = importlib.import_module(namespace_at(checkout) + "." + suffix)
    if not module.__file__ or not Path(module.__file__).resolve().is_relative_to(checkout):
        raise RuntimeError("historical baseline resolved outside the selected checkout")
    return module
