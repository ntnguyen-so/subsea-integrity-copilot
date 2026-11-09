from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from subsea_copilot import cli


def test_console_startup_builds_current_sources(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "node")
    run = Mock(return_value=CompletedProcess([], 0))
    monkeypatch.setattr(cli.subprocess, "run", run)
    cli.build_console()
    arguments, options = run.call_args
    assert arguments[0] == ["node", str(options["cwd"] / "scripts" / "build-console.cjs")]


def test_console_build_failure_prevents_startup(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "node")
    monkeypatch.setattr(cli.subprocess, "run", Mock(return_value=CompletedProcess([], 1)))
    with pytest.raises(ValueError, match="dashboard was not started"):
        cli.build_console()
