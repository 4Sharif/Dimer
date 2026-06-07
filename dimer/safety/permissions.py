"""Path and action permission checks."""

from __future__ import annotations

from pathlib import Path

BLOCKED_READ_PATTERNS = (
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    ".pem",
    ".key",
)

DANGEROUS_COMMANDS = (
    "rm -rf /",
    "sudo ",
    "curl | bash",
    "git reset --hard",
    "git push",
)


def is_within_workspace(path: Path, workspace: Path) -> bool:
    try:
        path.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


def requires_approval_for_read(path: Path) -> bool:
    name = path.name.lower()
    return any(p in name for p in BLOCKED_READ_PATTERNS)


def is_dangerous_command(command: str) -> bool:
    cmd = command.strip().lower()
    return any(d in cmd for d in DANGEROUS_COMMANDS)
