"""Payer policy models for prior-authorization criteria."""

from pydantic import BaseModel, Field, field_validator


class PayerPolicy(BaseModel):
    """Payer coverage policy for a specialty drug and condition."""

    drug: str = Field(
        ...,
        min_length=1,
        description="Brand or generic name of the specialty medication.",
    )
    condition: str = Field(
        ...,
        min_length=1,
        description="Indication the policy covers (e.g., rheumatoid arthritis).",
    )
    required_criteria_fields: list[str] = Field(
        ...,
        min_length=1,
        description="Structured field names that must be present and unambiguous.",
    )
    rules: str = Field(
        ...,
        min_length=20,
        description="Human-readable payer criteria the clinical note must satisfy.",
    )

    @field_validator("required_criteria_fields")
    @classmethod
    def validate_unique_fields(cls, fields: list[str]) -> list[str]:
        if len(fields) != len(set(fields)):
            msg = "required_criteria_fields must not contain duplicates"
            raise ValueError(msg)
        return fields
