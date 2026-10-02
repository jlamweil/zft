"""Pin the README's documented PyPI install lines to measured reality.

WQ-REDACTED (INT-REDACTED) anti-regression pin — with the direction the opposite
of the 0.2.0a6-era one: on 2026-10-02 the index carried ONLY PEP 440
pre-releases (0.2.0a1..a6), so d560548 documented ``pip install --pre
zft``; 0eec2ef then dropped ``--pre`` because 0.2.0 final shipped, and
first-hand ``pip index versions zft`` on 2026-10-03 confirms the bare
form resolves (zft (0.2.0); --pre additionally lists 0.2.0a8..a1 — pip
still prefers the 0.2.0 final either way, so ``--pre`` would change
nothing today).

The contract pinned here: the README's install instructions are the
BARE form, exactly while a non-pre release exists on PyPI. If this test
goes red because someone re-added ``--pre``, that editor must either
have a fresh pip-index measurement showing pre-only reality again (then
restore the bare-form expectation AND the why-note) or be reverting the
honest-state paragraph — both are doc-truth regressions, not style.
"""

import pathlib
import re

README = pathlib.Path(__file__).resolve().parents[2] / "README.md"


def _install_lines() -> list:
    text = README.read_text()
    return [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^\s*pip install .*zft", line)
    ]


def test_readme_documents_the_bare_pypi_install():
    lines = _install_lines()
    assert lines, "README lost its pip install zft instructions entirely"
    for line in lines:
        assert line == "pip install zft" or line.startswith(
            "pip install zft "), (
            f"install line drifted from the bare form: {line!r}; "
            "0.2.0 final is on PyPI (first-hand pip index 2026-10-03, "
            "commit 0eec2ef) — bare resolves, --pre adds nothing")


def test_readme_keeps_the_pre_release_history_note():
    # The honest-state paragraph explains WHY the bare form works only
    # since 0.2.0 — the flip-condition record for the pin above.
    text = README.read_text()
    assert "0.2.0 is the first release installable without" in text, (
        "the --pre history note vanished; restore it (it is the recorded "
        "reason the bare install line is correct)")


def test_no_stale_pre_flag_on_documented_installs():
    for line in _install_lines():
        assert "--pre" not in line, (
            f"--pre is back on an install line ({line!r}): correct ONLY "
            "with a fresh pip-index measurement showing pre-only reality "
            "(the pre-0.2.0 state of 2026-10-02); otherwise it suggests "
            "an alpha to users whose bare install would get the final")
