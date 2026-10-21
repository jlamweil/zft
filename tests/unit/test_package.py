"""C-01: package is importable and exposes its public surface (plan §2).

The version-stamp checks exist because ``zft.__version__`` froze at 0.2.0a1
across the a2-a5 cuts while wheel METADATA moved on: the only assertion was
truthiness, so nothing failed when the stamps drifted. They pin every stamp
to the same source of truth (pyproject.toml) so the drift is a red test, not
a receipt finding.
"""

import pathlib
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def _npm_version(pkg: str) -> str:
    import json

    package_json = REPO_ROOT / "packages" / pkg / "package.json"
    return json.loads(package_json.read_text())["version"]

def _npm_version_opencode() -> str:
    return _npm_version("opencode-zft")


def test_package_imports():
    import zft

    assert zft.__version__


def test_version_stamp_matches_pyproject():
    import zft

    assert zft.__version__ == _pyproject_version()


def test_citation_cff_version_matches_pyproject():
    cff = (REPO_ROOT / "CITATION.cff").read_text()
    declared = next(
        line.split(":", 1)[1].strip()
        for line in cff.splitlines()
        if line.startswith("version:")
    )
    assert declared == _pyproject_version()


def test_npm_package_version_aligned():
    # Anti-regression history: at the 0.2.0a6-era public tree this
    # package was absent by the npm-packaging decision and the
    # alignment test had no surface to check (phase-1 smoke: REAL fail).
    # The tree carries packages/opencode-zft again since b580fcb /
    # f0ef81d ("0.2.0 STABLE"), so the alignment assert below runs —
    # this skip branch exists only so the absent-shape, should it ever
    # return, is a SKIP CITING the decision, never a silent pass or a
    # bare FileNotFoundError.
    package_json = REPO_ROOT / "packages" / "opencode-zft" / "package.json"
    if not package_json.exists():
        import pytest

        pytest.skip(
            "packages/opencode-zft absent from this tree — the "
            "npm-packaging decision has kept the npm package "
            "out of the public repo before (npm opencode-zft "
            "0.2.0-alpha.N distribution); nothing to align-check here")
    # house convention (a4 receipt): the npm package stays version-aligned
    # with the CLI — PEP 440 ``0.2.0aN`` renders as npm ``0.2.0-alpha.N``.
    pep = _pyproject_version()
    assert _npm_version_opencode() == pep.replace("a", "-alpha.")


def test_pi_zft_version_aligned():
    # House convention (peer of test_npm_package_version_aligned): pi-zft,
    # the pi extension adapter, must stay version-aligned with the CLI too.
    # Silently drifting it would let a pi release ship a version the Python
    # side no longer matches. It ships as a copied extension (no registry
    # guard), so the pin here is the only oracle for its version.
    package_json = REPO_ROOT / "packages" / "pi-zft" / "package.json"
    if not package_json.exists():
        import pytest

        pytest.skip(
            "packages/pi-zft absent from this tree — nothing to align-check")
    pep = _pyproject_version()
    assert _npm_version("pi-zft") == pep.replace("a", "-alpha.")
