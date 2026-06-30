"""FHIR Bundle parsing and paging helpers."""

from __future__ import annotations

from typing import TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from fhir_client.models import Bundle

T = TypeVar("T", bound=BaseModel)


def resources_from_bundle(payload: dict[str, object], model: type[T]) -> list[T]:
    """Parse a searchset Bundle into validated resources of ``model``."""
    bundle = Bundle.model_validate(payload)
    if not bundle.entry:
        return []

    expected_type = model.__name__
    items: list[T] = []
    for entry in bundle.entry:
        if entry.resource is None:
            continue
        data = entry.resource.model_dump(mode="json")
        if data.get("resourceType") != expected_type:
            continue
        try:
            items.append(model.model_validate(data))
        except ValidationError:
            continue
    return items


def next_page_url(payload: dict[str, object], *, base_url: str) -> str | None:
    """Return the absolute URL for the Bundle ``next`` link, if present."""
    bundle = Bundle.model_validate(payload)
    if not bundle.link:
        return None

    for link in bundle.link:
        if link.relation != "next" or not link.url:
            continue
        parsed = urlparse(link.url)
        if parsed.scheme and parsed.netloc:
            return link.url
        return f"{base_url.rstrip('/')}/{link.url.lstrip('/')}"
    return None
