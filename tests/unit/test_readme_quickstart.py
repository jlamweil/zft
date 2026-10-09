"""Install-path pins: the README quickstart stays runnable as written.

Every pin encodes a dead end a fresh consumer actually hit: the 2026-09-27
probe installed zft 0.2.0a6 from PyPI into a clean CPython 3.12.13 venv and
executed the README quickstart verbatim on a fresh directory. Each failing
assertion here corresponded to a step that either failed on first run or
left the consumer with no documented way forward (the full command-by-command
record lives in verdicts/fresh-consumer-traceagent-hq-20260927.json). The
README is the contract for the documented path; these tests hold it to what
was proven to work.
"""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def _quickstart_text() -> str:
    """The Quickstart section, up to the next section heading."""
    text = README.read_text()
    start = text.index("## Quickstart")
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt]


def _quickstart_block() -> str:
    """The section's first fenced bash block, comments stripped per line."""
    section = _quickstart_text()
    start = section.index("```bash") + len("```bash")
    end = section.index("```", start)
    lines = []
    for line in section[start:end].splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code.rstrip())
    return "\n".join(lines)


def _quickstart_commands() -> list[str]:
    """zft subcommands in block order, with line continuations joined."""
    joined = _quickstart_block().replace("\\\n", " ")
    return re.findall(r"\bzft ([a-z][a-z-]*)", joined)


def test_quickstart_first_command_is_create_not_lint():
    # On a fresh directory `zft lint` exits 1 with "no clause store found";
    # the documented path must start at the command that seeds the store.
    assert _quickstart_commands()[0] == "create"


def test_quickstart_documents_the_binding_idiom():
    # `zft check` rejects an unbound clause with "uncovered clauses (no valid
    # binding)" — with no documented way to write a binding, that message is
    # a dead end; the README must carry the trace-comment convention itself.
    # (keep the pattern out of THIS comment: the extractor regexes comments,
    # and a commented example here would phantom-bind — the md-anchor guard
    # caught exactly that on the first pass)
    assert '@trace("EXPORT-413")' in _quickstart_text()


def test_quickstart_states_the_gate_package_requirement():
    # The gate sandbox mirrors the module as an importable package; a module
    # that only exists as a file path red-baselines the sandbox and the
    # verdict is a bare ok:false with fake 1/1 kills.
    assert "__init__.py" in _quickstart_text()


def test_quickstart_impact_example_targets_a_traced_test_symbol():
    # Bindings resolve on traced test symbols; the source-symbol form prints
    # "no bindings" on every store that only binds tests.
    block = _quickstart_block()
    assert re.search(r"zft impact\s+\S*tests/", block), block


def test_quickstart_task_gate_examples_carry_a_contract_reference():
    # task-gate refuses descriptions without an existing [contract: ...]
    # reference (ENF_WRITER_REQUIRES_CONTRACT, rc 1).
    assert "[contract: " in _quickstart_text()


def test_quickstart_names_the_contract_manifest_prerequisite():
    # Both `zft negotiate` and `zft task-gate` need a contract manifest under
    # .zft/contracts/; the refusals are typed but the requirement must be
    # documented before the consumer hits them.
    assert ".zft/contracts" in _quickstart_text()


def test_quickstart_subcommands_exist_on_the_cli_surface():
    from zft.cli.main import _GLOBAL_USAGE

    surface = set(re.search(r"<([a-z-]+(?:\|[a-z-]+)+)>", _GLOBAL_USAGE).group(1).split("|"))
    commands = set(_quickstart_commands())
    assert commands <= surface, sorted(commands - surface)


def test_documented_pypi_installs_resolve_stable():
    # Premise inverted 2026-10-01: 0.2.0 STABLE is live on PyPI (uploaded
    # from the receipted cut 2d92f82d — verdicts/release-0.2.0-executed-*),
    # so the honest documented first step is bare `pip install zft`. The
    # a8-era --pre pin (INT-014, when PyPI carried only a1..a8) taught a
    # flag a fresh consumer no longer needs. Every documented install of
    # the PyPI package must be the bare stable install; a --pre remnant is
    # stale documentation.
    text = README.read_text()
    bare = [
        line
        for line in text.splitlines()
        if re.search(r"pip install +zft\b", line)
    ]
    assert bare, "README must document the PyPI install"
    assert all("--pre" not in line for line in bare), bare
    assert "pip install zft" in text
