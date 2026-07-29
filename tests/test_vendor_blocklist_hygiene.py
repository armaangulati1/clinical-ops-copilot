"""Meta-guard: the blocklist mechanism cannot leak the list it protects.

The 2026-07-20 incident across three other public repos was not a company name
appearing in a demo. It was the DENY-LIST itself, committed in plaintext, in the
file whose job was to prevent exactly that. These tests exist so that failure
cannot recur here quietly:

* the committed digest file must be digests and nothing else;
* the plaintext blocklist must stay untracked;
* the guards themselves must carry no plaintext blocked term;
* the digest file must not have drifted behind the local plaintext list;
* an empty or unreadable digest file must fail loudly rather than disarm the
  guards silently.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.company_name_guard import (
    DIGEST_FILE,
    DIGESTS,
    EXAMPLE_BLOCKLIST,
    LOCAL_BLOCKLIST,
    count_hits,
    digest,
    read_plaintext_terms,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent

HEX64 = re.compile(r"^[0-9a-f]{64}$")

# The guard surface: every file that participates in name blocking. None of them
# has any legitimate reason to contain a REAL blocked term in plaintext.
#
# EXAMPLE_BLOCKLIST is deliberately excluded. It exists to list invented
# placeholder tokens in plaintext, and their digests are committed so the
# planted-name control test can run in CI, where the gitignored real list is
# absent. That makes the placeholders blocked terms, so the example file would
# otherwise flag itself. Its safety is enforced instead by
# test_example_blocklist_holds_only_placeholders below, which asserts every
# term in it is one of the committed placeholders and never a real name.
GUARD_FILES = [
    TESTS_DIR / "company_name_guard.py",
    TESTS_DIR / "test_vendor_blocklist_hygiene.py",
    DIGEST_FILE,
    *sorted(TESTS_DIR.glob("test_*no_company_names*.py")),
    PROJECT_ROOT / "scripts" / "regen_vendor_digests.py",
]

# Digests of the invented placeholders that EXAMPLE_BLOCKLIST is allowed to
# name in plaintext. Anything else appearing there is a real leak.
#
# PINNED LITERALS, deliberately. Deriving these from EXAMPLE_BLOCKLIST would
# make the check below self-referential: pasting a real name into that file
# would add it to its own allowlist and the test would pass. That is the
# self-exempting-guard defect this suite exists to prevent, and it was caught
# here by a control that planted a real name and watched the test wrongly pass.
# Regenerating these requires editing this file, which is the point.
PLACEHOLDER_DIGESTS = frozenset(
    {
        "5f1434003fb83a808d1a6a2b2c4da0f3b502a035ba6d746f2829eafbde989f2c",
        "79f5b8c36b20f8c7c9b8b686e736dfc6224bfa3516f7eff56dcef8cd795dd589",
        "88bf547fca53e967cb9f1cab629550f999c39a6b468789411d56019c13fbbbb9",
    }
)


def test_example_blocklist_holds_only_placeholders() -> None:
    """The one guard file allowed plaintext terms may hold ONLY invented ones.

    Excluding EXAMPLE_BLOCKLIST from the plaintext scan buys a hole unless
    something else closes it. This is that something: every term in the example
    file must be a placeholder, and a real name pasted there fails here.
    """
    terms = read_plaintext_terms(EXAMPLE_BLOCKLIST)
    assert terms, "example blocklist is empty; the control test has nothing to plant"
    unexpected = [t for t in terms if digest(t) not in PLACEHOLDER_DIGESTS]
    assert not unexpected, (
        f"{len(unexpected)} non-placeholder term(s) in the example blocklist"
    )


def test_digest_file_contains_only_digests() -> None:
    """One plaintext line here would re-create the original leak."""
    lines = [
        line.strip()
        for line in DIGEST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, "digest file is empty; the guards would match nothing"
    non_digest = [line for line in lines if not HEX64.match(line)]
    assert not non_digest, f"{len(non_digest)} non-digest line(s) in the digest file"


def test_blocklist_is_non_empty() -> None:
    """A guard compiled from an empty set always passes, which is worse than none."""
    assert len(DIGESTS) >= 20


def test_guard_files_carry_no_plaintext_blocked_term() -> None:
    """The guards are inside their own scan. That is the whole lesson."""
    offenders = []
    for path in GUARD_FILES:
        if not path.is_file():
            continue
        hits = count_hits(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            name = path.relative_to(PROJECT_ROOT)
            offenders.append(f"{name}: {hits} blocked term(s)")
    assert not offenders, (
        "plaintext blocked term(s) in the guard surface: " + "; ".join(offenders)
    )


def test_plaintext_blocklist_is_never_tracked() -> None:
    """Untracked is the entire point. Checked against git, with a real fallback.

    If git is unavailable this does NOT skip: it falls back to asserting the
    .gitignore rule, because a check that vanishes when its tool is missing is
    how the 2026-07-18 self-exempting-guard defect happened.
    """
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "tests/vendor_blocklist.local.txt" in gitignore

    try:
        tracked = subprocess.run(
            ["git", "ls-files", "tests/vendor_blocklist.local.txt"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return
    if tracked.returncode == 0:
        assert not tracked.stdout.strip(), "the plaintext blocklist is TRACKED by git"


def test_committed_digests_are_not_stale() -> None:
    """Every local plaintext term must already be represented in the digest file.

    Skipped-by-absence is honest here: a fresh clone has no local list, and the
    committed digests carry the guard on their own.
    """
    terms = read_plaintext_terms(LOCAL_BLOCKLIST)
    if not terms:
        return
    committed = {
        line.strip()
        for line in DIGEST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [t for t in terms if digest(t) not in committed]
    assert not missing, (
        f"{len(missing)} local term(s) missing from the committed digests; "
        "run scripts/regen_vendor_digests.py"
    )


def test_matcher_handles_separators_and_word_boundaries() -> None:
    """Positive and negative controls on the matcher, using placeholders only."""
    example_terms = read_plaintext_terms(EXAMPLE_BLOCKLIST)
    assert example_terms, "example blocklist is empty"
    example_digests = frozenset(digest(t) for t in example_terms)

    multiword = next(t for t in example_terms if " " in t)
    single = next(t for t in example_terms if " " not in t)

    # Separators between the words of a multi-word term must not defeat it.
    for rendered in (multiword, multiword.replace(" ", "-"), multiword.upper()):
        assert count_hits(f"we integrate with {rendered} today", example_digests) == 1

    # A blocked token inside a longer word must not trip.
    assert count_hits(f"{single}ish behaviour", example_digests) == 0
    assert count_hits(f"prefix{single}", example_digests) == 0
    assert count_hits(f"the {single} adapter", example_digests) == 1

    # Ordinary vocabulary stays quiet.
    for benign in ("message", "usage", "passage", "claim", "segment", "payer"):
        assert count_hits(benign, example_digests) == 0
