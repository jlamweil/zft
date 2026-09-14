"""A2 (P-006a): per-file extraction cache.

`extract_bindings` caches per-file bindings at
`<root>/.zft/cache/extract.json`, keyed (mtime_ns, size) per file and
gated by `CACHE_VERSION`. A warm run must not re-parse any unchanged file;
an edit invalidates exactly the edited file; a version mismatch invalidates
the whole cache (cold re-parse of every file).
"""
import json

import traceagent.lineage.extract as extract
from traceagent.lineage.extract import extract_bindings

PY_A = '# @trace("ALPHA-X")\ndef alpha():\n    return 1\n'
PY_B = '# @trace("BETA-Y")\ndef beta():\n    return 2\n'
PY_A_EDITED = PY_A + '# @trace("GAMMA-Z")\ndef gamma():\n    return 3\n'


def _build_tree(tmp_path):
    (tmp_path / "a.py").write_text(PY_A)
    (tmp_path / "b.py").write_text(PY_B)
    return tmp_path


def _counting_parse(monkeypatch):
    """Spy on the `_parse_file` seam: delegates to the real parser, records rels."""
    real = extract._parse_file
    calls = []

    def spy(path, rel, lang):
        calls.append(rel)
        return real(path, rel, lang)

    monkeypatch.setattr(extract, "_parse_file", spy)
    return calls


def test_warm_reuses_cache(tmp_path, monkeypatch):
    root = _build_tree(tmp_path)
    cold = extract_bindings(root)
    assert {b["alias"] for b in cold} == {"ALPHA-X", "BETA-Y"}

    cache = root / ".traceagent" / "cache" / "extract.json"
    assert cache.exists(), "cold run must write the cache"
    data = json.loads(cache.read_text())
    assert data["version"] == extract.CACHE_VERSION
    assert set(data["files"]) == {"a.py", "b.py"}
    for entry in data["files"].values():
        assert "mtime_ns" in entry and "size" in entry and "bindings" in entry

    calls = _counting_parse(monkeypatch)
    warm = extract_bindings(root)
    assert calls == [], f"warm run must not re-parse any file, re-parsed: {calls}"
    assert warm == cold


def test_edit_invalidates(tmp_path, monkeypatch):
    root = _build_tree(tmp_path)
    first = extract_bindings(root)
    assert extract_bindings(root) == first  # warm run is stable

    (root / "a.py").write_text(PY_A_EDITED)  # mtime_ns + size change, new binding
    calls = _counting_parse(monkeypatch)
    warm = extract_bindings(root)
    assert calls == ["a.py"], f"only the edited file may re-parse, re-parsed: {calls}"
    assert {b["alias"] for b in warm} == {"ALPHA-X", "GAMMA-Z", "BETA-Y"}


def test_cache_version_invalidates(tmp_path, monkeypatch):
    root = _build_tree(tmp_path)
    cold = extract_bindings(root)
    cache = root / ".traceagent" / "cache" / "extract.json"
    data = json.loads(cache.read_text())
    data["version"] = extract.CACHE_VERSION - 1  # cache from an older format
    cache.write_text(json.dumps(data))

    calls = _counting_parse(monkeypatch)
    warm = extract_bindings(root)
    assert calls == ["a.py", "b.py"], "version mismatch must force full cold re-parse"
    assert warm == cold
    assert json.loads(cache.read_text())["version"] == extract.CACHE_VERSION
