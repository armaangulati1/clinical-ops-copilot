"""POST Synthea FHIR transaction bundles to a HAPI server in dependency order."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_FHIR_BASE_URL = "http://localhost:8080/fhir"
FHIR_BASE_URL_ENV = "FHIR_BASE_URL"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
HOSPITAL_PREFIX = "hospitalInformation"
PRACTITIONER_PREFIX = "practitionerInformation"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadResult:
    """Summary of a bundle upload attempt."""

    path: Path
    ok: bool
    status_code: int | None
    detail: str


def fhir_base_url() -> str:
    return os.environ.get(FHIR_BASE_URL_ENV, DEFAULT_FHIR_BASE_URL).rstrip("/")


def bundle_load_order(bundle_dir: Path) -> list[Path]:
    """Return bundle files in HAPI-safe dependency order."""
    if not bundle_dir.is_dir():
        msg = f"bundle directory does not exist: {bundle_dir}"
        raise FileNotFoundError(msg)

    hospital = sorted(bundle_dir.glob(f"{HOSPITAL_PREFIX}*.json"))
    practitioners = sorted(bundle_dir.glob(f"{PRACTITIONER_PREFIX}*.json"))
    metadata_names = {p.name for p in (*hospital, *practitioners)}
    patients = sorted(
        p for p in bundle_dir.glob("*.json") if p.name not in metadata_names
    )
    return [*hospital, *practitioners, *patients]


@retry(
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
def _post_bundle(client: httpx.Client, base_url: str, bundle_bytes: bytes) -> httpx.Response:
    return client.post(
        base_url,
        content=bundle_bytes,
        headers={"Content-Type": "application/fhir+json"},
    )


def load_bundle_file(
    path: Path,
    *,
    client: httpx.Client,
    base_url: str,
) -> LoadResult:
    """POST one Synthea transaction bundle; never raise on HTTP errors."""
    try:
        bundle_bytes = path.read_bytes()
        response = _post_bundle(client, base_url, bundle_bytes)
        if response.is_success:
            return LoadResult(path=path, ok=True, status_code=response.status_code, detail="ok")
        detail = response.text[:500] if response.text else response.reason_phrase
        return LoadResult(
            path=path,
            ok=False,
            status_code=response.status_code,
            detail=detail or "request failed",
        )
    except httpx.HTTPError as exc:
        return LoadResult(path=path, ok=False, status_code=None, detail=str(exc))


def load_bundles(
    bundle_dir: Path,
    *,
    base_url: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> list[LoadResult]:
    """Upload all bundles in dependency order, continuing after individual failures."""
    target = base_url or fhir_base_url()
    paths = bundle_load_order(bundle_dir)
    results: list[LoadResult] = []

    if client is not None:
        for path in paths:
            result = load_bundle_file(path, client=client, base_url=target)
            results.append(result)
            _log_result(result)
        return results

    with httpx.Client(timeout=timeout_seconds) as owned_client:
        for path in paths:
            result = load_bundle_file(path, client=owned_client, base_url=target)
            results.append(result)
            _log_result(result)
    return results


def _log_result(result: LoadResult) -> None:
    if result.ok:
        logger.info(
            "loaded %s (%s)",
            result.path.name,
            result.status_code,
        )
        return
    logger.error(
        "failed %s status=%s detail=%s",
        result.path.name,
        result.status_code,
        result.detail,
    )


def _summarize(results: Sequence[LoadResult]) -> int:
    ok = sum(1 for r in results if r.ok)
    failed = len(results) - ok
    logger.info("load complete: %s succeeded, %s failed", ok, failed)
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load Synthea FHIR transaction bundles into HAPI.",
    )
    parser.add_argument(
        "bundle_dir",
        nargs="?",
        type=Path,
        default=Path("synthea/output/fhir"),
        help="Directory containing Synthea FHIR JSON bundles (default: synthea/output/fhir)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"FHIR base URL (default: env {FHIR_BASE_URL_ENV} or {DEFAULT_FHIR_BASE_URL})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = load_bundles(args.bundle_dir, base_url=args.base_url)
    return _summarize(results)


if __name__ == "__main__":
    sys.exit(main())
