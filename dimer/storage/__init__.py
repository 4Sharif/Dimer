"""Local storage for sessions, artifacts, and workspace state."""

from dimer.storage.artifacts import ensure_workspace_dirs, get_workspace_root

__all__ = ["ensure_workspace_dirs", "get_workspace_root"]
