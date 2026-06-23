#!/usr/bin/env python3
"""Print label distribution and difficulty breakdown for the dataset."""

from __future__ import annotations

from collections import Counter

from schemas.cases import Difficulty
from schemas.loader import decision_class_counts, load_dataset, load_labels


def main() -> None:
    dataset = load_dataset()
    labels = load_labels()

    print(f"Total cases: {len(dataset)}")
    print("\nDecision class distribution:")
    for action, count in sorted(
        decision_class_counts(labels).items(),
        key=lambda item: item[0].value,
    ):
        print(f"  {action.value}: {count}")

    difficulty_counts = Counter(entry.label.difficulty for entry in dataset)
    print("\nDifficulty breakdown:")
    for difficulty in Difficulty:
        print(f"  {difficulty.value}: {difficulty_counts[difficulty]}")

    condition_counts = Counter(entry.case.condition for entry in dataset)
    print("\nCondition mix:")
    for condition, count in sorted(condition_counts.items()):
        print(f"  {condition}: {count}")


if __name__ == "__main__":
    main()
