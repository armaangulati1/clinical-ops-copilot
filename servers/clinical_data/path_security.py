"""Filesystem access boundaries for clinical-data MCP server."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class PathNotAccessibleError(PermissionError):
    """Raised when a requested path is outside allowed roots."""

    def __init__(self, requested_path: str | Path) -> None:
        self.requested_path = Path(requested_path)
        super().__init__(f"path not accessible: {self.requested_path}")


def is_path_allowed(requested_path: str | Path, allowed_roots: Sequence[Path]) -> bool:
    """Return True when ``requested_path`` resolves inside an allowed root.

    Resolves symlinks and normalizes paths so traversal tricks such as
    ``../../etc/passwd`` or absolute paths outside the root are rejected.
    """
    if not allowed_roots:
        return False

    try:
        resolved = Path(requested_path).resolve()
    except (OSError, RuntimeError):
        return False

    for root in allowed_roots:
        try:
            root_resolved = root.resolve()
        except (OSError, RuntimeError):
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        return True

    return False


def assert_path_allowed(
    requested_path: str | Path, allowed_roots: Sequence[Path]
) -> Path:
    """Resolve ``requested_path`` when allowed; otherwise raise."""
    if not is_path_allowed(requested_path, allowed_roots):
        raise PathNotAccessibleError(requested_path)
    return Path(requested_path).resolve()
