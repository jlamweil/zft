"""C-16: mutation sandbox prep — oracle + fixtures copied into the campaign sandbox.

The V5 lesson: mutmut runs in a sandbox where only mutated modules exist;
the oracle artifact must be copied in or every campaign dies on import.
"""

import pytest

from traceagent.gates.sandbox import _package_layout, gate_env, place_tests, prepare_sandbox


def test_prepare_copies_module_oracle_and_tests(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "m.py").write_text("def f(t):\n    return t\n")
    oracle = tmp_path / "oracles" / "oracle_GATE.py"
    oracle.parent.mkdir(parents=True)
    oracle.write_text("def expired(t):\n    return t > 100\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_g.py").write_text("def test_g():\n    assert True\n")

    sandbox = tmp_path / "sandbox"
    prepare_sandbox(
        sandbox,
        mutate_paths=[src / "m.py"],
        also_copy=[oracle, tests],
    )
    assert (sandbox / "m.py").exists()
    assert (sandbox / "oracle_GATE.py").exists()        # loose files at root
    assert (sandbox / "tests" / "test_g.py").exists()   # test dirs intact


def test_prepare_is_idempotent(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    sandbox = tmp_path / "sandbox"
    prepare_sandbox(sandbox, mutate_paths=[src], also_copy=[])
    prepare_sandbox(sandbox, mutate_paths=[src], also_copy=[])
    assert (sandbox / "m.py").exists()


def test_generated_config_uses_current_mutmut_keys(tmp_path):
    """mutmut 3.7 renamed keys (paths_to_mutate->source_paths etc.) — pin the new ones."""
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_m.py").write_text("def test_m():\n    assert True\n")
    sandbox = tmp_path / "sandbox"
    prepare_sandbox(sandbox, mutate_paths=[src], also_copy=[tests])
    config = (sandbox / "pyproject.toml").read_text()
    assert "paths_to_mutate" in config
    assert "also_copy" in config


def test_gate_env_strips_parent_channels(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p cov")
    monkeypatch.setenv("PYTHONPATH", "/real/repo/src")
    monkeypatch.setenv("COVERAGE_FILE", "/real/repo/.coverage")
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")
    env = gate_env({"TRACEAGENT_REPO": "/repo", "ZFT_REPO": "/repo"})
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH",
                "COVERAGE_FILE", "PYTHONOPTIMIZE"):
        assert key not in env
    assert env["PYTHONHASHSEED"] == "0"
    assert env["TRACEAGENT_REPO"] == "/repo"
    assert env["ZFT_REPO"] == "/repo"
    assert "PATH" in env, "launcher env must stay usable"


def test_prepare_excludes_state_dirs(tmp_path):
    """Cached state must not be smuggled into the campaign (hypothesis DB, caches)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text("def f():\n    return 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_g.py").write_text("def test_g():\n    assert True\n")
    for state_dir in ("__pycache__", ".hypothesis", ".pytest_cache", ".traceagent"):
        d = tests / state_dir
        d.mkdir()
        (d / "junk.bin").write_text("stale state")
    sandbox = prepare_sandbox(tmp_path / "sandbox", mutate_paths=[src / "m.py"],
                              also_copy=[tests])
    assert (sandbox / "tests" / "test_g.py").exists()
    for state_dir in ("__pycache__", ".hypothesis", ".pytest_cache", ".traceagent"):
        assert not (sandbox / "tests" / state_dir).exists()


def test_prepare_refuses_sandbox_containing_sources(tmp_path):
    # --sandbox tests/ would rmtree the real test tree — must raise BEFORE deletion
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    with pytest.raises(ValueError, match="delete real files"):
        prepare_sandbox(tmp_path, mutate_paths=[src], also_copy=[])


def test_prepare_refuses_sandbox_inside_mirrored_package(tmp_path):
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    with pytest.raises(ValueError, match="leak into the real package"):
        prepare_sandbox(pkg / "sandbox", mutate_paths=[pkg / "mod.py"], also_copy=[])


def test_place_tests_mirrors_repo_layout_and_golden(tmp_path):
    """Regression (L3 survivor triage): a flattened test module resolves
    Path(__file__).parents[1]/golden outside the sandbox and every pytest run
    died at import — all mutants were counted killed without ever executing an
    assertion. In-root test files must keep their repo-relative layout with
    tests/golden mirrored so the parents[1] lookup lands inside the sandbox."""
    root = tmp_path / "repo"
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "golden").mkdir()
    (root / "tests" / "golden" / "fixtures.json").write_text("{}")
    test_file = root / "tests" / "unit" / "test_x.py"
    test_file.write_text("def test_x():\n    assert True\n")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    in_sandbox = place_tests(sandbox, test_file, root)

    assert in_sandbox == sandbox / "tests" / "unit" / "test_x.py"
    assert in_sandbox.exists()
    golden_lookup = in_sandbox.resolve().parents[1] / "golden" / "fixtures.json"
    assert golden_lookup.exists(), "parents[1]/golden must resolve inside the sandbox"


def test_place_tests_flattens_files_outside_root(tmp_path):
    """Test files outside the repo root (tmp fixtures) keep the legacy
    root flatten — there is no repo-relative layout to preserve."""
    root = tmp_path / "repo"
    root.mkdir()
    loose = tmp_path / "fixtures" / "test_loose.py"
    loose.parent.mkdir()
    loose.write_text("def test_loose():\n    assert True\n")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    in_sandbox = place_tests(sandbox, loose, root)

    assert in_sandbox == sandbox / "test_loose.py"
    assert in_sandbox.exists()


def test_place_tests_dir_passthrough(tmp_path):
    """Test dirs are copied intact by prepare_sandbox; place_tests only
    derives the run path."""
    root = tmp_path / "repo"
    root.mkdir()
    tests_dir = root / "mytests"
    tests_dir.mkdir()
    (tests_dir / "test_d.py").write_text("def test_d():\n    assert True\n")

    sandbox = tmp_path / "sandbox"
    prepare_sandbox(sandbox, mutate_paths=[], also_copy=[tests_dir])
    in_sandbox = place_tests(sandbox, tests_dir, root)

    assert in_sandbox == sandbox / "mytests"
    assert (in_sandbox / "test_d.py").exists()


def test_sandbox_conftest_scrubs_dirty_launch_env(tmp_path):
    """Even a launcher that passes the parent env verbatim cannot leak into the run."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text("X = 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_env.py").write_text(
        "import os\n"
        "def test_no_parent_leak():\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
        "    assert 'COVERAGE_FILE' not in os.environ\n"
    )
    sandbox = prepare_sandbox(tmp_path / "sandbox", mutate_paths=[src / "m.py"],
                              also_copy=[tests])
    dirty = dict(__import__("os").environ)
    dirty["PYTEST_ADDOPTS"] = "-p no:randomly"
    dirty["COVERAGE_FILE"] = str(tmp_path / "leak.coverage")
    from traceagent.gates.runners.pytest_runner import run_pytest

    result = run_pytest(sandbox, ["tests/test_env.py"], timeout_s=120, env=dirty)
    assert result.ok, result.tail
    assert not (tmp_path / "leak.coverage").exists()


def test_prepare_accepts_package_layout_outside_the_package(tmp_path):
    # regression pin: _validate_placement must raise only when the sandbox
    # sits INSIDE the mirrored package — a sibling sandbox is the documented
    # gate-campaign layout and must prepare cleanly
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("")
    (tmp_path / "src" / "pkg" / "mod.py").write_text("x = 1\n")
    sandbox = prepare_sandbox(tmp_path / "sandbox",
                              mutate_paths=[tmp_path / "src" / "pkg" / "mod.py"],
                              also_copy=[])
    assert (sandbox / "pkg" / "mod.py").exists()


def test_package_layout_rejects_a_bare_package_path(tmp_path):
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    assert _package_layout(pkg / "__init__.py") is not None   # module in package
    assert _package_layout(pkg) is None                       # the package itself
