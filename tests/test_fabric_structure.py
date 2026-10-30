"""Amberlog's structure: one facade over a core and cohesive services, public API unchanged.

`amberlog/fabric.py` composes `amberlog/_fabric/`: a `FabricCore`
(identity, log, refresh, transactions, replay) and one mixin per service
(federation, sealing, retrieval, lifecycle, sharing, access, writes). These
tests keep that shape honest:

- the public API is exactly the one recorded before the split
  (`tests/data/amberlog_api.json`, generated from the original class);
- the methods `FabricCore` declares for the type checker match their
  implementations, so the declarations cannot drift;
- services depend on the core, never on each other;
- no module grows back into a monolith.
"""

from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from amberlog import Amberlog

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "amberlog" / "_fabric"
SERVICES = ("federation", "sealing", "retrieval", "lifecycle", "sharing", "access", "writes")


def _args(fn: object) -> str:
    source = inspect.getsource(fn).lstrip()
    if source.startswith("@"):
        source = source[source.index("def "):]
    node = ast.parse(inspect.cleandoc("\n" + source) if source.startswith(" ") else source)
    func = node.body[0]
    assert isinstance(func, ast.FunctionDef)
    return ast.unparse(func.args)


class PublicApi(unittest.TestCase):
    def test_the_public_api_is_the_recorded_one(self) -> None:
        recorded = json.loads((ROOT / "tests/data/amberlog_api.json").read_text(encoding="utf-8"))
        current = {}
        for name in recorded:
            member = getattr(Amberlog, name, None)
            self.assertIsNotNone(member, f"{name} is gone from Amberlog")
            if isinstance(member, property):
                member = member.fget
            current[name] = _args(inspect.unwrap(member))
        self.assertEqual(current, recorded)

    def test_no_public_member_was_added_unrecorded(self) -> None:
        recorded = set(json.loads((ROOT / "tests/data/amberlog_api.json")
                                  .read_text(encoding="utf-8")))
        public = {n for n, v in vars(Amberlog).items() if callable(v) and not n.startswith("_")}
        for base in Amberlog.__mro__[1:]:
            if base.__module__.startswith("amberlog._fabric"):
                public |= {n for n, v in vars(base).items()
                           if callable(v) and not n.startswith("_")}
        self.assertEqual(sorted(public - recorded), [],
                         "a new public method: add it to tests/data/amberlog_api.json")


class Structure(unittest.TestCase):
    def test_type_checking_declarations_match_their_implementations(self) -> None:
        tree = ast.parse((PKG / "core.py").read_text(encoding="utf-8"))
        core = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FabricCore")
        guard = next(n for n in core.body if isinstance(n, ast.If))
        declared = {f.name: ast.unparse(f.args) for f in guard.body if isinstance(f, ast.FunctionDef)}
        self.assertTrue(declared)
        for name, args in declared.items():
            with self.subTest(method=name):
                self.assertEqual(args, _args(inspect.unwrap(getattr(Amberlog, name))))

    def test_services_depend_on_the_core_not_on_each_other(self) -> None:
        for service in SERVICES:
            source = (PKG / f"{service}.py").read_text(encoding="utf-8")
            others = [s for s in SERVICES if s != service
                      and (f"from .{s} import" in source or f"from ._fabric.{s}" in source)]
            self.assertEqual(others, [], f"{service} imports {others}")

    def test_no_module_grows_back_into_a_monolith(self) -> None:
        sizes = {p.name: len(p.read_text(encoding="utf-8").splitlines())
                 for p in [ROOT / "src" / "amberlog" / "fabric.py", *PKG.glob("*.py")]}
        self.assertLess(sizes["fabric.py"], 300, sizes)
        self.assertEqual({k: v for k, v in sizes.items() if v > 1200}, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
