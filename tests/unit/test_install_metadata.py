"""Install metadata: declared extras must exist upstream.

securesystemslib 1.x publishes no extras — pip warns on every fresh install:
"WARNING: securesystemslib 1.5.1 does not provide the extra 'cryptography'".
cryptography itself stays a direct runtime dependency, which is what the DSSE
path actually imports.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _runtime_dependencies():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]["dependencies"]


def test_securesystemslib_declared_without_stale_extra():
    deps = _runtime_dependencies()
    assert "securesystemslib[cryptography]>=1.0" not in deps
    assert "securesystemslib>=1.0" in deps


def test_cryptography_stays_a_direct_dependency():
    assert any(d.startswith("cryptography>=") for d in _runtime_dependencies())
