"""Standard package loader for skill scripts.

Directories stay named ``scripts/`` but are registered in ``sys.modules``
under the skill's unique name (e.g. ``monitoring_alerts``) so package
names never collide across skills.

Bootstrap from any skills/{skill}/scripts/*.py:

    import importlib.util as _ilu
    from pathlib import Path
    _s = _ilu.spec_from_file_location(
        "_loader", Path(__file__).resolve().parent.parent.parent / "lib" / "loader.py")
    _l = _ilu.module_from_spec(_s); _s.loader.exec_module(_l)
    _load = _l.make_loader(__file__)

Usage:
    _mod = _load("balance_checker")                        # same skill sibling
    _mod = _load("facebook.client")                        # same skill sub-package
    _mod = _load("ads-channel", "facebook", "client")      # cross-skill
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SKILLS_DIR = Path(__file__).resolve().parent.parent


def _ensure_package(scripts_dir: Path, pkg_name: str) -> None:
    """Register scripts/ as a package under pkg_name if not already loaded."""
    if pkg_name in sys.modules:
        return

    init_file = scripts_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        str(init_file) if init_file.exists() else None,
        submodule_search_locations=[str(scripts_dir)],
    )
    if spec is None:
        return
    pkg = importlib.util.module_from_spec(spec)
    pkg.__path__ = [str(scripts_dir)]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    if spec.loader and init_file.exists():
        spec.loader.exec_module(pkg)


def _register_subpackages(scripts_dir: Path, pkg_name: str) -> None:
    """Register immediate sub-packages (e.g. facebook/, common/) so relative imports work."""
    for child in scripts_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            sub_name = f"{pkg_name}.{child.name}"
            if sub_name not in sys.modules:
                _ensure_package(child, sub_name)


def _import_as(scripts_dir: Path, pkg_name: str, module_path: str) -> ModuleType:
    """Import a module from scripts_dir registered under pkg_name."""
    full_path = f"{pkg_name}.{module_path}" if module_path else pkg_name

    if full_path in sys.modules:
        return sys.modules[full_path]

    _ensure_package(scripts_dir, pkg_name)
    _register_subpackages(scripts_dir, pkg_name)

    return importlib.import_module(full_path)


def _skill_pkg_name(skill_name: str) -> str:
    """Convert skill name to valid Python package name."""
    return skill_name.replace("-", "_")


def make_loader(caller_file: str):
    """Return a single load() function.

    1 arg:  load("module")                       — own scripts/ package
    2+ args: load("other-skill", "sub", "module") — cross-skill import
    """
    scripts_dir = Path(caller_file).resolve().parent
    skill_name = scripts_dir.parent.name
    own_pkg = _skill_pkg_name(skill_name)

    # Register own package on creation
    _ensure_package(scripts_dir, own_pkg)
    _register_subpackages(scripts_dir, own_pkg)

    def load(*args: str) -> ModuleType:
        if len(args) == 1:
            return _import_as(scripts_dir, own_pkg, args[0])
        skill, *parts = args
        target = SKILLS_DIR / skill / "scripts"
        pkg = _skill_pkg_name(skill)
        return _import_as(target, pkg, ".".join(parts))

    return load
