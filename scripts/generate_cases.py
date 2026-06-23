#!/usr/bin/env python3
"""Generate prior-auth case candidates for human label review."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from schemas.dataset_io import write_review_candidates
from schemas.seed_data import SEED_SPECS, spec_to_review_candidate

DEFAULT_OUTPUT = Path("data/_review/candidates.json")


def generate_deterministic(output: Path, count: int) -> int:
    """Write curated synthetic candidates for review."""
    specs = SEED_SPECS[:count]
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = [spec_to_review_candidate(spec) for spec in specs]
    payload = [candidate.model_dump(mode="json") for candidate in candidates]
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return len(candidates)


def generate_with_anthropic(output: Path, count: int) -> int:
    """Draft candidate notes via Anthropic API.

    Proposed labels require human review.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    import importlib

    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError:
        print("Install anthropic: uv add anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    # Draft a small batch; full scaling still requires human review per rubric.
    prompt = (
        "Draft one synthetic prior-auth clinical note for specialty medication "
        "with fictional patient data. Return JSON with keys: clinical_note, drug, "
        "condition, payer_policy (object), proposed_action, proposed_rationale, "
        "difficulty, required_fields_present, fields_missing."
    )
    candidates: list[dict[str, object]] = []
    for index in range(count):
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        block = message.content[0]
        if block.type != "text":
            continue
        drafted = json.loads(block.text)
        drafted["case"] = {
            "case_id": f"case-{index + 1:03d}",
            "clinical_note": drafted.pop("clinical_note"),
            "drug": drafted.pop("drug"),
            "condition": drafted.pop("condition"),
            "payer_policy": drafted.pop("payer_policy"),
        }
        drafted["review_status"] = "pending"
        candidates.append(drafted)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")
    return len(candidates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Review queue output path",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=48,
        help="Number of candidates to generate (deterministic mode)",
    )
    parser.add_argument(
        "--use-anthropic",
        action="store_true",
        help="Draft candidates with Anthropic API instead of curated seed data",
    )
    parser.add_argument(
        "--also-write-review-from-seed",
        action="store_true",
        help="Write full seed candidates via dataset_io helper",
    )
    args = parser.parse_args()

    if args.also_write_review_from_seed:
        count = len(write_review_candidates(args.output))
    elif args.use_anthropic:
        count = generate_with_anthropic(args.output, args.count)
    else:
        count = generate_deterministic(args.output, args.count)

    print(f"Wrote {count} candidate(s) to {args.output}")
    print("Next: uv run python scripts/review_labels.py")


if __name__ == "__main__":
    main()
