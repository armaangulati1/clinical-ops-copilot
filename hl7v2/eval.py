"""Exact-match eval harness for the HL7 v2 subset.

For each well-formed fixture this checks two things against committed goldens:

* **parsed** golden: the structured :class:`~hl7v2.parser.HL7Message`.
* **mapped** golden: the boundary mapping (ADT -> ``PatientContext``,
  ORU -> ``FhirClinicalBundle`` observation resources).

Both are exact dictionary matches, so the number is reproducible offline with no
API keys. Run ``python -m hl7v2.eval`` for the per-fixture table, or
``python -m hl7v2.eval --update`` to regenerate the goldens after an
intentional change.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hl7v2.mapper import map_adt, map_oru
from hl7v2.parser import HL7Message, parse_message

PACKAGE_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = PACKAGE_ROOT / "fixtures"
PARSED_GOLDENS = FIXTURES_DIR / "goldens" / "parsed"
MAPPED_GOLDENS = FIXTURES_DIR / "goldens" / "mapped"


def well_formed_fixtures() -> list[Path]:
    return sorted(
        p for p in FIXTURES_DIR.glob("*.hl7") if not p.name.startswith("malformed_")
    )


def parsed_view(message: HL7Message) -> dict[str, Any]:
    """Deterministic dict view of a parsed message (property added explicitly)."""
    view = asdict(message)
    view["message_type"] = message.message_type
    return view


def mapped_view(message: HL7Message) -> dict[str, Any]:
    """Deterministic dict view of the boundary mapping for a message."""
    if message.message_type == "ADT^A01":
        return {"boundary": "patient_context", "value": map_adt(message).to_dict()}
    return {"boundary": "fhir_clinical_bundle", "value": map_oru(message).to_dict()}


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_goldens() -> None:
    PARSED_GOLDENS.mkdir(parents=True, exist_ok=True)
    MAPPED_GOLDENS.mkdir(parents=True, exist_ok=True)
    for fixture in well_formed_fixtures():
        message = parse_message(fixture.read_text(encoding="utf-8"))
        stem = fixture.stem
        (PARSED_GOLDENS / f"{stem}.json").write_text(
            _dump(parsed_view(message)), encoding="utf-8"
        )
        (MAPPED_GOLDENS / f"{stem}.json").write_text(
            _dump(mapped_view(message)), encoding="utf-8"
        )


class EvalRow:
    """Per-fixture exact-match outcome."""

    def __init__(self, name: str, parsed_ok: bool, mapped_ok: bool) -> None:
        self.name = name
        self.parsed_ok = parsed_ok
        self.mapped_ok = mapped_ok

    @property
    def ok(self) -> bool:
        return self.parsed_ok and self.mapped_ok


def run_eval() -> list[EvalRow]:
    rows: list[EvalRow] = []
    for fixture in well_formed_fixtures():
        stem = fixture.stem
        message = parse_message(fixture.read_text(encoding="utf-8"))
        parsed_gold = json.loads(
            (PARSED_GOLDENS / f"{stem}.json").read_text(encoding="utf-8")
        )
        mapped_gold = json.loads(
            (MAPPED_GOLDENS / f"{stem}.json").read_text(encoding="utf-8")
        )
        rows.append(
            EvalRow(
                name=stem,
                parsed_ok=parsed_view(message) == parsed_gold,
                mapped_ok=mapped_view(message) == mapped_gold,
            )
        )
    return rows


def main() -> None:
    argp = argparse.ArgumentParser(description="HL7 v2 subset eval harness")
    argp.add_argument(
        "--update",
        action="store_true",
        help="regenerate goldens from current parser/mapper output",
    )
    args = argp.parse_args()
    if args.update:
        write_goldens()
        print("goldens regenerated")
        return

    rows = run_eval()
    width = max(len(row.name) for row in rows)
    print(f"{'fixture'.ljust(width)}  parsed  mapped")
    print(f"{'-' * width}  ------  ------")
    for row in rows:
        parsed = "ok" if row.parsed_ok else "DIFF"
        mapped = "ok" if row.mapped_ok else "DIFF"
        print(f"{row.name.ljust(width)}  {parsed:<6}  {mapped:<6}")
    passed = sum(1 for row in rows if row.ok)
    total = len(rows)
    pct = passed / total if total else 0.0
    print(
        f"\nexact-match: {passed}/{total} fixtures "
        f"({pct:.0%}) on the self-authored HL7 v2 set"
    )


if __name__ == "__main__":
    main()
