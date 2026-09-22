"""Mutation-sandbox preparation — isolation contract (C-16 + C-39 wiring).

1. Module under mutation: mirrored into its package layout inside the sandbox
   (tests import `zft.spec.lint` from the installed package; a flat copy
   would never be imported and kill counts would be fake). Flat modules are
   copied to the sandbox root.
2. Test DIRS are copied intact (explicit test_paths point at sandbox/<name>);
   single test FILES flatten to the root.
3. conftest.py pins the sandbox at sys.path[0] (the mirrored mutated package
   shadows the installed one) and scrubs parent-env channels at startup, so
   gate verdicts cannot be steered by the launching shell.
4. Minimal mutmut-compatible pyproject (paths_to_mutate/also_copy).

Isolation rules enforced here:
- stateful dirs (__pycache__, .hypothesis, .pytest_cache, tool caches, .git,
  .zft) are never copied IN — a copied hypothesis database or verdict
  cache would smuggle prior runs' state into the campaign;
- gate_env() is the launch environment for gate subprocesses: parent
  addopts/plugins/path/coverage channels stripped, PYTHONHASHSEED pinned;
- the sandbox may not contain a copied source, nor sit inside a mirrored
  package — preparation would rmtree or self-copy real files (checked BEFORE
  any deletion).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# state that must never cross the sandbox boundary in either direction
IGNORED_STATE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".hypothesis",
    ".mypy_cache", ".ruff_cache", ".git", ".zft", ".coverage*",
)

# parent-env channels that alter pytest verdicts or write outside the sandbox
STRIPPED_ENV_VARS = (
    "PYTEST_ADDOPTS",          # parent addopts change what is collected/executed
    "PYTEST_PLUGINS",          # auto-loaded plugins, same effect
    "PYTHONPATH",              # could shadow the sandbox mirror with real-repo modules
    "PYTHONOPTIMIZE",          # strips asserts — silently guts test verdicts
    "PYTHONSTARTUP",
    "COVERAGE_FILE",           # coverage subprocesses would write into the real repo
    "COVERAGE_PROCESS_START",
)


def gate_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Launch env for gate subprocesses: parent leaks stripped, hash seed pinned."""
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV_VARS}
    env["PYTHONHASHSEED"] = "0"  # stable hash ordering — reproducible verdicts
    # size-preserving mutants restore within the same mtime second as the
    # original; a cached .pyc would then keep executing mutant bytecode
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def place_tests(sandbox: Path, tests: Path, root: Path) -> Path:
    """Copy a single-file --tests arg into the sandbox and return the path to
    run pytest on.

    Repo convention: test modules load golden fixtures via
    `Path(__file__).resolve().parents[1] / "golden"` (tests/unit/x.py ->
    tests/golden/). The legacy root flatten breaks that lookup — the sandboxed
    module resolves parents[1] outside the sandbox and every pytest run dies
    at import, counting every mutant as killed. So files under the repo root
    keep their repo-relative layout and tests/golden is mirrored next to them;
    files outside the repo (fixtures in tmp dirs) keep the legacy flatten.
    """
    tests = Path(tests).resolve()
    sandbox = Path(sandbox)
    root = Path(root).resolve()
    if tests.is_dir():                      # dirs are copied intact by prepare_sandbox
        return sandbox / tests.name
    try:
        rel = tests.relative_to(root)
    except ValueError:
        shutil.copy2(tests, sandbox / tests.name)
        return sandbox / tests.name
    dest = sandbox / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tests, dest)
    golden = root / "tests" / "golden"
    if golden.is_dir():
        shutil.copytree(golden, sandbox / "tests" / "golden",
                        ignore=IGNORED_STATE, dirs_exist_ok=True)
    return dest


def _package_layout(module: Path) -> tuple[Path, Path] | None:
    """If module is <src>/<pkg>/.../<file> with a real package, return (src_root, pkg).

    Validated: <src>/<pkg> must be a directory containing __init__.py.
    """
    module = Path(module)
    parts = module.parts
    if "src" not in parts:
        return None
    src_idx = len(parts) - parts[::-1].index("src")
    if src_idx + 1 >= len(parts):
        return None
    src_root = Path(*parts[:src_idx])
    top_pkg = parts[src_idx]
    if not (src_root / top_pkg / "__init__.py").exists():
        return None
    return src_root, Path(top_pkg)


def _validate_placement(sandbox: Path, mutate_paths: list[Path],
                        also_copy: list[Path]) -> None:
    """Refuse layouts where preparation would delete or self-copy real files."""
    sb = sandbox.resolve()
    for src in (p for p in [*mutate_paths, *also_copy] if p is not None):
        s = src.resolve()
        if s == sb or s.is_relative_to(sb):
            raise ValueError(
                f"sandbox {sandbox} contains source {src}: "
                "preparation would delete real files")
    for src in mutate_paths:
        layout = _package_layout(src)
        if layout is None:
            continue
        src_root, top_pkg = layout
        pkg = (src_root / top_pkg).resolve()
        if sb == pkg or sb.is_relative_to(pkg):
            raise ValueError(
                f"sandbox {sandbox} sits inside mirrored package {pkg}: "
                "generated files would leak into the real package")


def prepare_sandbox(
    sandbox: Path, mutate_paths: list[Path], also_copy: list[Path],
) -> Path:
    sandbox = Path(sandbox)
    _validate_placement(sandbox, mutate_paths, also_copy)
    if sandbox.is_dir():
        shutil.rmtree(sandbox)
    elif sandbox.exists():
        sandbox.unlink()
    sandbox.mkdir(parents=True)

    mirrored: dict[Path, Path] = {}
    test_dirs: list[Path] = []

    for path in mutate_paths:
        layout = _package_layout(path)
        if layout is not None:
            src_root, top_pkg = layout
            shutil.copytree(
                src_root / top_pkg, sandbox / top_pkg,
                ignore=IGNORED_STATE, dirs_exist_ok=True,
            )
            mirrored[path] = sandbox / path.relative_to(src_root)
        else:
            shutil.copy2(path, sandbox / path.name)
            mirrored[path] = sandbox / path.name

    for path in also_copy:
        if path is None:
            continue
        if path.is_dir():
            dest = sandbox / path.name
            shutil.copytree(path, dest, ignore=IGNORED_STATE)
            test_dirs.append(dest)
        else:
            shutil.copy2(path, sandbox / path.name)

    # conftest paths must be absolute: the subprocess cwd is already the sandbox,
    # so a relative sandbox arg would resolve inside itself
    sandbox_abs = sandbox.resolve()
    (sandbox / "conftest.py").write_text(
        "import os\n"
        "import sys\n"
        f"for _k in {STRIPPED_ENV_VARS!r}:\n"
        "    os.environ.pop(_k, None)\n"
        f"os.chdir({str(sandbox_abs)!r})\n"
        f"sys.path.insert(0, {str(sandbox_abs)!r})\n"
    )

    names = ", ".join(
        f'"{m.relative_to(sandbox).as_posix()}"' for m in mirrored.values())
    copies = ", ".join(repr(p.name) for p in also_copy if p is not None)
    config = [
        "[tool.mutmut]",
        f"paths_to_mutate = [{names}]",
        f"also_copy = [{copies}]",
        "",
        "[tool.pytest.ini_options]",
        'norecursedirs = ["mutants"]',
        'addopts = "-q"',
    ]
    (sandbox / "pyproject.toml").write_text("\n".join(config) + "\n")
    return sandbox
