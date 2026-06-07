"""Load and match .dimerignore patterns."""

from __future__ import annotations

import fnmatch
from pathlib import Path

DIMERIGNORE_FILENAME = ".dimerignore"

# Always ignored — internal/tooling paths, not user data.
BUILTIN_IGNORE_PARTS = {
    ".git",
    "__pycache__",
    ".dimer",
}

DEFAULT_DIMERIGNORE = """\
# Dimer workspace ignore patterns (gitignore-style)
# Lines starting with # are comments.
# Use trailing / for directories, * for wildcards, /prefix to anchor to workspace root.
#
# Examples:
# agents/
# node_modules/
# .venv/
# *.log
# /data/raw/

agents/
node_modules/
.venv/
venv/
.pytest_cache/
"""

ARTIFACTS_PREFIX = ".dimer/artifacts/"


def dimerignore_path(workspace: Path) -> Path:
    return workspace.resolve() / DIMERIGNORE_FILENAME


def load_dimerignore_patterns(workspace: Path | None = None) -> list[str]:
    ws = (workspace or Path.cwd()).resolve()
    path = dimerignore_path(ws)
    if not path.exists():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def ensure_dimerignore(workspace: Path | None = None) -> Path:
    ws = (workspace or Path.cwd()).resolve()
    path = dimerignore_path(ws)
    if not path.exists():
        path.write_text(DEFAULT_DIMERIGNORE, encoding="utf-8")
    return path


class DimerIgnoreMatcher:
    def __init__(self, patterns: list[str] | None = None, workspace: Path | None = None) -> None:
        self.patterns = patterns if patterns is not None else load_dimerignore_patterns(workspace)

    def is_ignored(self, rel_path: str) -> bool:
        rel = rel_path.replace("\\", "/").lstrip("./")
        if rel.startswith(ARTIFACTS_PREFIX):
            return False

        ignored = False
        for pattern in self.patterns:
            if pattern.startswith("!"):
                if _matches_pattern(pattern[1:].strip(), rel):
                    ignored = False
            elif _matches_pattern(pattern, rel):
                ignored = True
        return ignored


def _matches_pattern(pattern: str, rel_path: str) -> bool:
    pat = pattern.strip()
    if not pat:
        return False

    rel = rel_path.replace("\\", "/")
    anchored = pat.startswith("/")
    if anchored:
        pat = pat[1:]

    dir_only = pat.endswith("/")
    if dir_only:
        pat = pat.rstrip("/")

    if anchored:
        if fnmatch.fnmatch(rel, pat):
            return True
        if fnmatch.fnmatch(rel, f"{pat}/*") or rel.startswith(f"{pat}/"):
            return True
        return False

    if fnmatch.fnmatch(rel, pat):
        return True
    if fnmatch.fnmatch(rel, f"*/{pat}") or fnmatch.fnmatch(rel, f"**/{pat}"):
        return True

    name = Path(rel).name
    if fnmatch.fnmatch(name, pat):
        return True

    parts = rel.split("/")
    for i, part in enumerate(parts):
        if fnmatch.fnmatch(part, pat):
            if dir_only:
                return True
            if i < len(parts) - 1 and fnmatch.fnmatch("/".join(parts[i:]), pat):
                return True
            if fnmatch.fnmatch(part, pat):
                return True
        subpath = "/".join(parts[i:])
        if fnmatch.fnmatch(subpath, pat):
            return True
        if dir_only and (part == pat or fnmatch.fnmatch(part, pat)):
            return True

    return False


def is_path_ignored(path: Path, workspace: Path, matcher: DimerIgnoreMatcher | None = None) -> bool:
    ws = workspace.resolve()
    resolved = path.resolve()
    try:
        rel = str(resolved.relative_to(ws)).replace("\\", "/")
    except ValueError:
        return True

    if matcher is None:
        matcher = DimerIgnoreMatcher(workspace=ws)

    if matcher.is_ignored(rel):
        return True

    return any(part in BUILTIN_IGNORE_PARTS for part in resolved.parts)
