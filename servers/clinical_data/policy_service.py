"""Payer policy lookup for clinical-data tools."""

from __future__ import annotations

from schemas.policies import PayerPolicy
from schemas.seed_data import POLICIES


def get_payer_policy(drug: str, condition: str) -> PayerPolicy:
    """Return the payer policy for a drug/condition pair."""
    drug_key = drug.strip().lower()
    condition_key = condition.strip().lower()

    for policy in POLICIES.values():
        if (drug_key in policy.drug.lower() or policy.drug.lower() in drug_key) and (
            condition_key in policy.condition.lower()
            or policy.condition.lower() in condition_key
        ):
            return policy.model_copy(deep=True)

    msg = f"No payer policy found for drug={drug!r}, condition={condition!r}"
    raise ValueError(msg)
