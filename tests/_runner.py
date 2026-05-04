"""Sandbox-only test runner.

Pytest isn't always available offline. This module:
  1. Installs a minimal `pytest` shim in `sys.modules` (raises, parametrize)
  2. Walks tests/ for `test_*.py`, imports each, and runs every `test_*`
     function within. Class-based tests not supported (we don't need them).
  3. Collects pass/fail/skip counts and prints a summary.

Run:
    python tests/_runner.py

When real pytest is installed, prefer:
    pytest tests/
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path
from types import ModuleType


# --- minimal pytest shim ---------------------------------------------------

class _Raises:
    def __init__(self, exc_type: type, match: str | None = None) -> None:
        self.exc_type = exc_type
        self.match = match
        self.value: BaseException | None = None

    def __enter__(self) -> "_Raises":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            raise AssertionError(f"DID NOT RAISE {self.exc_type.__name__}")
        if not isinstance(exc, self.exc_type):
            return False  # propagate unexpected
        if self.match is not None:
            import re
            if not re.search(self.match, str(exc)):
                raise AssertionError(
                    f"raised {exc_type.__name__}({exc!s}) does not match {self.match!r}"
                )
        self.value = exc
        return True


class _Approx:
    def __init__(self, expected: float, abs_tol: float = 1e-9) -> None:
        self.expected = expected
        self.abs_tol = abs_tol

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return abs(other - self.expected) <= self.abs_tol
        return NotImplemented

    def __repr__(self) -> str:
        return f"approx({self.expected})"


def _install_pytest_shim() -> None:
    if "pytest" in sys.modules:
        return
    mod = ModuleType("pytest")

    def raises(exc_type, match=None):
        return _Raises(exc_type, match)

    def parametrize(argnames, argvalues, ids=None):
        """Decorator that fans a single test out into multiple by stashing
        param data; our runner expands these.
        """
        def deco(fn):
            existing = getattr(fn, "_param_cases", [])
            cases = []
            arg_names = [a.strip() for a in argnames.split(",")] if isinstance(argnames, str) else list(argnames)
            for vals in argvalues:
                if not isinstance(vals, tuple):
                    vals = (vals,)
                cases.append(dict(zip(arg_names, vals)))
            fn._param_cases = existing + cases
            return fn
        return deco

    mark = ModuleType("pytest.mark")
    mark.parametrize = parametrize

    mod.raises = raises
    mod.approx = _Approx
    mod.mark = mark
    mod.fixture = lambda fn=None, **kw: (fn if fn else (lambda f: f))
    sys.modules["pytest"] = mod
    sys.modules["pytest.mark"] = mark


# --- runner ----------------------------------------------------------------

def _import_test_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_tests.{path.stem}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_func(mod: ModuleType, name: str) -> tuple[int, int, list[str]]:
    """Returns (passed, failed, errors)."""
    fn = getattr(mod, name)
    cases = getattr(fn, "_param_cases", None) or [None]
    passed = failed = 0
    errors: list[str] = []
    for case in cases:
        label = f"{mod.__name__}::{name}"
        if case is not None:
            label += f"[{','.join(f'{k}={v!r}' for k, v in case.items())}]"
        try:
            if case is None:
                fn()
            else:
                fn(**case)
            passed += 1
        except Exception:
            failed += 1
            tb = traceback.format_exc()
            errors.append(f"FAIL {label}\n{tb}")
    return passed, failed, errors


def main() -> int:
    _install_pytest_shim()

    here = Path(__file__).parent
    repo = here.parent
    sys.path.insert(0, str(repo))     # so `import fmlwc` works
    sys.path.insert(0, str(repo))     # and `import tests.fakes`

    test_files = sorted(p for p in here.glob("test_*.py"))
    print(f"discovered {len(test_files)} test modules")

    total_pass = total_fail = 0
    all_errors: list[str] = []

    for tf in test_files:
        try:
            mod = _import_test_module(tf)
        except Exception:
            total_fail += 1
            all_errors.append(f"IMPORT ERROR {tf.name}\n{traceback.format_exc()}")
            print(f"  {tf.name}: IMPORT FAILED")
            continue

        names = [n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))]
        mod_pass = mod_fail = 0
        for name in names:
            p, f, errs = _run_func(mod, name)
            mod_pass += p
            mod_fail += f
            all_errors.extend(errs)
        marker = "ok" if mod_fail == 0 else "FAIL"
        print(f"  {tf.name}: {mod_pass} passed, {mod_fail} failed [{marker}]")
        total_pass += mod_pass
        total_fail += mod_fail

    print()
    print(f"TOTAL: {total_pass} passed, {total_fail} failed")
    if all_errors:
        print("\n=== Failures ===")
        for e in all_errors:
            print(e)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
