"""Golden exact-match tests for the HL7 v2 subset eval harness."""

from __future__ import annotations

from hl7v2.eval import run_eval, well_formed_fixtures


def test_eval_covers_every_well_formed_fixture() -> None:
    rows = run_eval()
    assert len(rows) == len(well_formed_fixtures())
    assert len(rows) >= 6


def test_all_goldens_match() -> None:
    rows = run_eval()
    failed = [row.name for row in rows if not row.ok]
    assert not failed, f"golden mismatch: {failed}"


def test_both_boundaries_are_exercised() -> None:
    rows = run_eval()
    names = {row.name for row in rows}
    assert any(name.startswith("adt_") for name in names)
    assert any(name.startswith("oru_") for name in names)
