"""Regenerate the committed vendor-blocklist digest file.

The plaintext blocklist (``tests/vendor_blocklist.local.txt``) is gitignored on
purpose: enumerating real company names inside a public repo is the leak the
guards exist to prevent. This script turns that file into
``tests/vendor_blocklist.digests.txt``, which carries SHA-256 digests only,
sorted so the original grouping and ordering are not recoverable.

Run after editing the local blocklist:

    uv run python scripts/regen_vendor_digests.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.company_name_guard import (  # noqa: E402
    DIGEST_FILE,
    LOCAL_BLOCKLIST,
    MAX_GRAM,
    digest,
    read_plaintext_terms,
)

HEADER = (
    "# SHA-256 digests of blocked vendor/company terms, sorted.\n"
    "# Plaintext source of truth is the gitignored tests/vendor_blocklist.local.txt.\n"
    "# Regenerate with: uv run python scripts/regen_vendor_digests.py\n"
)


def main() -> int:
    terms = read_plaintext_terms(LOCAL_BLOCKLIST)
    if not terms:
        print(
            f"no terms found in {LOCAL_BLOCKLIST}; refusing to write an empty "
            "digest file, which would disarm the guards",
            file=sys.stderr,
        )
        return 1

    too_long = [t for t in terms if len(t.split()) > MAX_GRAM]
    if too_long:
        print(
            f"{len(too_long)} term(s) exceed MAX_GRAM={MAX_GRAM} words and would "
            "never match; raise MAX_GRAM or shorten them",
            file=sys.stderr,
        )
        return 1

    digests = sorted({digest(term) for term in terms})
    DIGEST_FILE.write_text(HEADER + "\n".join(digests) + "\n", encoding="utf-8")
    print(f"wrote {len(digests)} digests to {DIGEST_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
