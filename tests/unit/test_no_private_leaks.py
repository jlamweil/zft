import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_files():
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    for line in out.splitlines():
        if line.startswith(".venv/"):
            continue
        if line == "tools/export-cut-check.sh":
            continue
        yield ROOT / line


def _patterns():
    cod = "trace" + "agent"
    yield re.compile(r"/home/[A-Za-z0-9._-]+")
    yield re.compile(re.escape("dev-" + cod + "-zcode"))
    yield re.compile(r"\b" + re.escape(cod) + r"\b", re.IGNORECASE)
    yield re.compile(r"HOST-A", re.IGNORECASE)
    yield re.compile(r"HOST-B", re.IGNORECASE)
    yield re.compile(r"ntfy\.sh")


def test_no_private_identifiers_in_tracked_sources():
    bad = [
        (str(f), m.group(0))
        for f in _tracked_files()
        if f.is_file()
        for p in _patterns()
        for m in p.finditer(f.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not bad, "private identifiers leaked in tracked files: %r" % bad[:10]
