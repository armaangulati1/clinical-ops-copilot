"""Tests for chart path access boundaries."""

from pathlib import Path

import pytest

from servers.clinical_data.path_security import (
    PathNotAccessibleError,
    assert_path_allowed,
    is_path_allowed,
)


@pytest.fixture
def chart_root(tmp_path: Path) -> Path:
    root = tmp_path / "charts"
    root.mkdir()
    allowed = root / "case-001-note.txt"
    allowed.write_text("sample chart note", encoding="utf-8")
    return root


def test_legitimate_path_inside_root_is_allowed(chart_root: Path) -> None:
    target = chart_root / "case-001-note.txt"
    assert is_path_allowed(target, [chart_root]) is True


def test_path_traversal_outside_root_is_rejected(chart_root: Path) -> None:
    roots = [chart_root]
    assert is_path_allowed("../../etc/passwd", roots) is False
    assert is_path_allowed("../../../etc/passwd", roots) is False
    assert is_path_allowed("/etc/passwd", roots) is False


def test_assert_path_allowed_raises_clear_error(chart_root: Path) -> None:
    with pytest.raises(PathNotAccessibleError, match="path not accessible"):
        assert_path_allowed("../../etc/passwd", [chart_root])


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    chart_root = tmp_path / "charts"
    chart_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = chart_root / "escape-link.txt"
    link.symlink_to(outside)
    assert is_path_allowed(link, [chart_root]) is False
