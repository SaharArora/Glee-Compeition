"""Guard the packaging declaration against silent omissions.

`pip install -e '.[live]'` was documented in docs/LIVE_INTEGRATION.md but never
run -- the local venv had been built with a bare `pip install glee-sdk` instead --
so setuptools' flat-layout autodiscovery error shipped unnoticed. These tests
check the declaration itself, which is cheap, and a fresh-environment install is
verified separately since only that exercises the build backend for real.

The failure mode they protect against is a new top-level package being added and
quietly not making it into the distribution: importable in the repo, missing once
installed. That is the same shape as the bug class the schema contracts exist for.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Top-level packages deliberately left out of the distribution, with the reason.
INTENTIONALLY_UNPACKAGED = {
    "eval": (
        "compatibility shim forwarding to main functions the glee_eval CLI already "
        "exposes; works from the repo root without installation, and `eval` is too "
        "generic a name to own in site-packages"
    ),
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _top_level_packages() -> set[str]:
    """Directories in the repo root that Python would treat as packages."""

    return {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").exists() and not path.name.startswith(".")
    }


def _include_patterns() -> list[str]:
    return _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]


def _matches(name: str, patterns: list[str]) -> bool:
    return any(name == p or (p.endswith("*") and name.startswith(p[:-1])) for p in patterns)


class BuildDeclarationTests(unittest.TestCase):
    def test_a_build_system_is_declared(self) -> None:
        """Without this, the backend is implicit and behaves differently across pip versions."""

        build = _pyproject().get("build-system", {})

        self.assertEqual(build.get("build-backend"), "setuptools.build_meta")
        self.assertTrue(build.get("requires"))

    def test_package_discovery_is_explicit(self) -> None:
        """Flat-layout autodiscovery refuses to build a root with several packages."""

        self.assertTrue(_include_patterns())

    def test_the_two_shipped_packages_are_covered(self) -> None:
        patterns = _include_patterns()

        for package in ("glee_eval", "my_agents"):
            self.assertTrue(_matches(package, patterns), f"{package} is not covered by {patterns}")

    def test_subpackages_are_covered_by_a_wildcard(self) -> None:
        """A flat list would omit a subpackage added later; a wildcard will not."""

        patterns = _include_patterns()

        for subpackage in ("glee_eval.live", "glee_eval.diagnostics", "glee_eval.theory"):
            top = subpackage.split(".")[0]
            self.assertTrue(
                any(p.endswith("*") and top.startswith(p[:-1]) for p in patterns),
                f"{subpackage} relies on a wildcard for {top}, which {patterns} does not provide",
            )


class NoSilentOmissionTests(unittest.TestCase):
    def test_every_top_level_package_is_packaged_or_explicitly_excluded(self) -> None:
        """The actual guard: a new top-level package must be a deliberate decision."""

        patterns = _include_patterns()
        for package in sorted(_top_level_packages()):
            with self.subTest(package=package):
                if _matches(package, patterns):
                    continue
                self.assertIn(
                    package,
                    INTENTIONALLY_UNPACKAGED,
                    f"{package!r} is a top-level package but is neither included by {patterns} "
                    f"nor listed in INTENTIONALLY_UNPACKAGED with a reason",
                )

    def test_the_exclusion_list_has_not_gone_stale(self) -> None:
        """An entry naming a directory that no longer exists is misleading."""

        existing = _top_level_packages()
        for package in INTENTIONALLY_UNPACKAGED:
            self.assertIn(package, existing, f"{package!r} is listed as excluded but no longer exists")

    def test_every_exclusion_states_a_reason(self) -> None:
        for package, reason in INTENTIONALLY_UNPACKAGED.items():
            self.assertGreater(len(reason), 40, f"{package!r} needs a real reason, not a placeholder")

    def test_the_excluded_shim_is_still_fully_superseded(self) -> None:
        """`eval` may only stay unpackaged while the CLI covers all of it."""

        import re

        cli = (ROOT / "glee_eval" / "cli.py").read_text(encoding="utf-8")
        commands = set(re.findall(r'^\s+"([a-z-]+)",\s*$', cli, re.M))
        shims = [p.stem for p in (ROOT / "eval").glob("*.py") if p.stem != "__init__"]

        self.assertTrue(shims)
        for shim in shims:
            self.assertTrue(
                shim in commands or shim.replace("_", "-") in commands,
                f"eval/{shim}.py has no glee_eval CLI equivalent, so excluding eval/ would lose it",
            )


if __name__ == "__main__":
    unittest.main()
