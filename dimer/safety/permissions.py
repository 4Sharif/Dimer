"""Path and action permission checks."""

from __future__ import annotations

from pathlib import Path

from dimer.data_context.dimerignore import is_path_ignored, is_path_ignored_lexically

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


def enforce_workspace_path(
    path: str | Path,
    workspace: Path,
    *,
    allowed_outside_paths: tuple[Path, ...] = (),
) -> Path:
    """Resolve a tool path and enforce workspace/ignore boundaries."""

    ws = workspace.resolve()
    candidate = Path(path).expanduser()
    lexical = candidate if candidate.is_absolute() else ws / candidate
    if is_path_ignored_lexically(lexical, ws):
        raise PermissionError(f"Path is ignored by .dimerignore: {lexical}")
    resolved = lexical.resolve(strict=False)
    allowed = {item.resolve(strict=False) for item in allowed_outside_paths}
    if not is_within_workspace(resolved, ws):
        if resolved in allowed:
            return resolved
        raise PermissionError(f"Path outside workspace: {resolved}")
    if is_path_ignored(resolved, ws):
        raise PermissionError(f"Path is ignored by .dimerignore: {resolved}")
    return resolved


def requires_approval_for_read(path: Path) -> bool:
    name = path.name.lower()
    return any(p in name for p in BLOCKED_READ_PATTERNS)


def is_dangerous_command(command: str) -> bool:
    cmd = command.strip().lower()
    return any(d in cmd for d in DANGEROUS_COMMANDS)
