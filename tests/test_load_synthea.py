"""Tests for Synthea FHIR bundle loader."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fhir_loader.load_synthea import (
    bundle_load_order,
    load_bundle_file,
    load_bundles,
)


def test_bundle_load_order_places_metadata_before_patients(tmp_path: Path) -> None:
    (tmp_path / "zpatient.json").write_text("{}")
    (tmp_path / "hospitalInformation123.json").write_text("{}")
    (tmp_path / "practitionerInformation456.json").write_text("{}")
    (tmp_path / "apatient.json").write_text("{}")

    ordered = bundle_load_order(tmp_path)
    names = [p.name for p in ordered]
    assert names.index("hospitalInformation123.json") < names.index(
        "practitionerInformation456.json"
    )
    assert names.index("practitionerInformation456.json") < names.index("apatient.json")
    assert names.index("practitionerInformation456.json") < names.index("zpatient.json")


def test_load_bundle_file_success(tmp_path: Path) -> None:
    bundle = tmp_path / "patient.json"
    bundle.write_text('{"resourceType":"Bundle","type":"transaction"}')

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://example.test/fhir"
        assert request.headers["content-type"] == "application/fhir+json"
        return httpx.Response(200, json={"resourceType": "Bundle"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = load_bundle_file(
        bundle, client=client, base_url="http://example.test/fhir"
    )
    assert result.ok is True
    assert result.status_code == 200


def test_load_bundles_continues_after_failure(tmp_path: Path) -> None:
    (tmp_path / "hospitalInformation1.json").write_text('{"a":1}')
    (tmp_path / "patient1.json").write_text('{"b":2}')

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"resourceType": "Bundle"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    results = load_bundles(tmp_path, base_url="http://example.test/fhir", client=client)
    assert len(results) == 2
    assert results[0].ok is False
    assert results[1].ok is True


def test_bundle_load_order_missing_dir() -> None:
    with pytest.raises(FileNotFoundError):
        bundle_load_order(Path("/nonexistent/bundle/dir"))
