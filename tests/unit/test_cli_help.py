"""Tests for CLI help flag behavior."""
import sys
from io import StringIO

# Byte-exact CLI contract for the usage block; every help path prints it and
# nothing else. The three call shapes pin all three copies of the string in
# main() separately (bare-argv, -h, --help), so a mutation of any one copy —
# XX-wrap, case swap, None render — dies here, as do the exit-code literals.
USAGE = ("usage: zft <lint|extract|check|impact|gate|repro|attest|verify|export|"
         "negotiate|create|baseline|driver-gate|mutation-bar|task-gate> [root]")


def _run_cli(args):
    from zft.cli.main import main
    saved_stdout = sys.stdout
    try:
        sys.stdout = StringIO()
        exit_code = main(args)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = saved_stdout
    return exit_code, output


def test_help_flag_shows_usage_and_returns_zero():
    exit_code, output = _run_cli(["--help"])
    assert exit_code == 0
    # Ensure common subcommand is mentioned (e.g., 'check')
    assert "check" in output


def test_long_help_prints_exact_usage_and_exits_zero():
    exit_code, output = _run_cli(["--help"])
    assert (exit_code, output) == (0, USAGE + "\n")


def test_short_help_flag_prints_exact_usage_and_exits_zero():
    exit_code, output = _run_cli(["-h"])
    assert (exit_code, output) == (0, USAGE + "\n"), \
        "-h must take the global help path, not fall through to unknown-command"


def test_bare_invocation_prints_exact_usage_and_exits_two():
    exit_code, output = _run_cli([])
    assert (exit_code, output) == (2, USAGE + "\n")


def test_unknown_command_returns_error_and_message():
    exit_code, output = _run_cli(["nonexistent"])
    assert exit_code != 0
    assert "unknown command" in output
