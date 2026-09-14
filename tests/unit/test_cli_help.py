"""Tests for CLI help flag behavior."""
import sys
from io import StringIO


def _run_cli(args):
    from traceagent.cli.main import main
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


def test_unknown_command_returns_error_and_message():
    exit_code, output = _run_cli(["nonexistent"])
    assert exit_code != 0
    assert "unknown command" in output
