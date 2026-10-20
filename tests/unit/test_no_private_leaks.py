import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_files():
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    for line in out.splitlines():
        p = ROOT / line
        if line.startswith(".venv/"):
            continue
        yield p


def _patterns():
    cod = "trace" + "agent"
    zdrv = "zcode-" + "remote-driver"
    loc = "<" + "LOCAL>"
    yield re.compile(r"/ho" + r"me/[A-Za-z0-9._-]+")
    yield re.compile(re.escape("dev-" + cod + "-zcode"))
    yield re.compile(r"\b" + re.escape(cod) + r"\b", re.IGNORECASE)
    yield re.compile(re.escape("teth" + "ys"), re.IGNORECASE)
    yield re.compile(re.escape("yug" + "uer" + "ten"), re.IGNORECASE)
    yield re.compile(re.escape("ntfy") + r"\.sh")
    yield re.compile(re.escape(zdrv), re.IGNORECASE)
    yield re.compile(re.escape(loc))
    yield re.compile(r"\b(?:INT|WQ)-0[0-9]{2,}\b")


def test_no_private_identifiers_in_tracked_sources():
    bad = [
        (str(f), m.group(0))
        for f in _tracked_files()
        if f.is_file()
        for p in _patterns()
        for m in p.finditer(f.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not bad, "private identifiers leaked in tracked files: %r" % bad[:10]
