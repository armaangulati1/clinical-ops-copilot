"""Shared machinery for the "this demo names no real company" guards.

WHY THE BLOCKLIST IS NOT COMMITTED IN PLAINTEXT
-----------------------------------------------
Earlier versions of these guards hard coded a list of real company names, one of
them under a comment that named the list's purpose. That is self defeating. In a
repo that is otherwise deliberately vendor neutral, an enumerated list of
companies is the single artifact that reveals which companies the author had in
mind, and a public repo publishes it to exactly the people it names. The guard
against leaking became the leak.

So the plaintext list is not in the repo. What is committed is
``vendor_blocklist.digests.txt``: SHA-256 digests of the lowercased terms, one
per line, sorted, with no grouping, no comments, and no counts per category.

WHAT THAT DOES AND DOES NOT BUY, stated honestly
------------------------------------------------
It defeats the real exposure: reading the file, grepping the repo, or a search
engine indexing a name next to this author's handle. It does NOT defeat an
offline dictionary attack, because SHA-256 of a short known string is cheap to
confirm. Someone who already holds a candidate list can test membership. That is
an accepted limit: a party holding that list already has the information the
plaintext would have handed them, and the digest form removes the far more
likely accident of a casual reader or a grep.

Full detection power is retained everywhere, including a fresh clone and CI,
because the digests are committed. That is the one thing a purely externalized
(gitignored) plaintext blocklist cannot do: on a fresh CI checkout it would fall
back to placeholder tokens and quietly stop detecting anything real.

MATCHING
--------
Scanned text is lowercased and split into ``[a-z0-9]+`` tokens; every contiguous
run of one to ``MAX_GRAM`` tokens is hashed and looked up. Multi word names are
therefore caught regardless of the punctuation or whitespace between the words,
and single word names never trip on a longer word that merely contains them.

Failure messages report file paths and hit COUNTS only. They never echo the term
that matched: a guard that prints the name into a public CI log has moved the
leak rather than closed it.

MAINTENANCE
-----------
``tests/vendor_blocklist.local.txt`` is the gitignored plaintext source of truth
on the author's machine. ``scripts/regen_vendor_digests.py`` regenerates the
committed digest file from it. ``tests/vendor_blocklist.example.txt`` is
committed and holds invented placeholder tokens only, so the format is
documented and a fresh clone can still exercise the tooling.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

DIGEST_FILE = TESTS_DIR / "vendor_blocklist.digests.txt"
LOCAL_BLOCKLIST = TESTS_DIR / "vendor_blocklist.local.txt"
EXAMPLE_BLOCKLIST = TESTS_DIR / "vendor_blocklist.example.txt"

# Longest blocked term measured in whitespace separated words.
MAX_GRAM = 3

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def digest(term: str) -> str:
    """SHA-256 of a term after the same normalisation the scanner applies."""
    normalised = " ".join(_TOKEN_RE.findall(term.lower()))
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def read_plaintext_terms(path: Path) -> list[str]:
    """Terms from a plaintext blocklist file, ignoring blanks and ``#`` comments."""
    if not path.exists():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            terms.append(stripped.lower())
    return terms


def load_digests() -> frozenset[str]:
    """Committed digests, unioned with the local plaintext list when present.

    The union means a term added to the untracked local list protects the repo
    immediately, before the digest file is regenerated. On a fresh clone or in
    CI the committed digests carry the guard on their own.
    """
    committed = {
        line.strip()
        for line in DIGEST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    local = {digest(term) for term in read_plaintext_terms(LOCAL_BLOCKLIST)}
    return frozenset(committed | local)


DIGESTS = load_digests()


def count_hits(text: str, digests: frozenset[str] = DIGESTS) -> int:
    """Number of distinct blocked terms present in ``text``.

    Returns a count, never the terms themselves, so a caller cannot accidentally
    echo a blocked name into a failure message or a CI log.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    found: set[str] = set()
    for size in range(1, MAX_GRAM + 1):
        for start in range(len(tokens) - size + 1):
            gram = " ".join(tokens[start : start + size])
            gram_digest = hashlib.sha256(gram.encode("utf-8")).hexdigest()
            if gram_digest in digests:
                found.add(gram_digest)
    return len(found)


def scan_paths(paths: list[Path], root: Path) -> list[str]:
    """Scan files and return one leak-free offender line per offending file."""
    offenders: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        hits = count_hits(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            try:
                shown = path.relative_to(root)
            except ValueError:
                shown = path
            offenders.append(f"{shown}: {hits} blocked term(s)")
    return offenders
