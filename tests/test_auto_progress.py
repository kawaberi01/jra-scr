from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path("/home/main/.codex/skills/addon-superpowers-auto-progress/scripts/update_progress_summary.py")


def _run_update(target: Path, agent: str, status: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--file",
            str(target),
            "--agent",
            agent,
            "--status",
            status,
            "--completed",
            f"{agent} completed",
            "--remaining",
            f"{agent} remaining",
            "--next-step",
            f"{agent} next",
            "--verification",
            f"{agent} verification",
            "--doc-sync",
            f"{agent} doc sync",
        ],
        check=True,
    )


def test_auto_progress_records_agent(tmp_path: Path) -> None:
    summary = tmp_path / "progress.md"

    _run_update(summary, "agent-a", "session-a")

    text = summary.read_text(encoding="utf-8")
    assert "- agent: agent-a" in text
    assert "session-a" in text


def test_auto_progress_serializes_parallel_updates(tmp_path: Path) -> None:
    summary = tmp_path / "progress.md"

    proc_a = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--file",
            str(summary),
            "--agent",
            "agent-a",
            "--status",
            "session-a",
            "--completed",
            "agent-a completed",
            "--remaining",
            "agent-a remaining",
            "--next-step",
            "agent-a next",
            "--verification",
            "agent-a verification",
            "--doc-sync",
            "agent-a doc sync",
        ]
    )
    proc_b = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--file",
            str(summary),
            "--agent",
            "agent-b",
            "--status",
            "session-b",
            "--completed",
            "agent-b completed",
            "--remaining",
            "agent-b remaining",
            "--next-step",
            "agent-b next",
            "--verification",
            "agent-b verification",
            "--doc-sync",
            "agent-b doc sync",
        ]
    )

    assert proc_a.wait() == 0
    assert proc_b.wait() == 0

    text = summary.read_text(encoding="utf-8")
    assert text.count("### ") == 2
    assert "- agent: agent-a" in text
    assert "- agent: agent-b" in text
