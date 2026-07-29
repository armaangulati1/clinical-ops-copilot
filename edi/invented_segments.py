"""Invented carrier segments for the demo EDI layers, and why they cannot collide.

The 271 and 277 responders in this repo have to put *something* on the wire to
carry their self-authored vocabularies. They deliberately do not reuse the real
X12 segments that would normally carry that content (``EB``, ``AAA``, ``STC``),
because those segments imply externally maintained code lists this project does
not reproduce. So the responders emit invented carrier segments instead.

Why the IDs are four characters
-------------------------------
An earlier revision of this layer used three-character IDs and asserted in the
source and the README that they were "not a real X12 segment". That assertion is
an unverifiable universal negative, and for one of them it was simply **wrong**:
``CSI`` *is* a real X12 segment ("Claim Status Information", transaction set
260). Publishing a false claim about a standard is worse than publishing no
claim at all, so the negative assertion has been replaced with a positive,
checkable rule:

    An X12 segment ID is two or three characters. A four-character ID is
    therefore not a valid X12 segment ID and cannot collide with any segment in
    any X12 transaction set, present or future.

That is a structural guarantee, not a lookup. It does not depend on anybody
having checked a directory correctly, which is exactly the failure that produced
the ``CSI`` mistake.

Evidence for the two-or-three-character rule (checked 2026-07-28): every one of
the segment IDs published in a public X12 segment directory is two
or three characters; none is four or more. ``CSI`` appears in that directory
(which is how the mistake was caught); ``ZEBC``, ``ZCSI`` and ``ZRJC`` cannot,
by length.

Consequences, stated plainly
----------------------------
A four-character segment ID is **invalid X12 by construction**. That is
intentional and is the honest outcome: this repo emits demo-shaped interchanges,
not conformant EDI, and an ID that no parser can mistake for a standard segment
makes the non-conformance visible on the wire rather than only in a README. This
output is not clearinghouse-ready and must never be presented as such.

The leading ``Z`` follows the usual convention for a locally defined extension.

Not covered here: the 835 layer's ``DRC`` denial carrier predates this module,
ships on ``main``, and keeps its three-character ID. ``DRC`` was verified absent
from the same published segment directory on 2026-07-28, so its "invented" framing
is accurate; it is simply evidenced by a lookup rather than guaranteed by
length. See :data:`LEGACY_THREE_CHAR_CARRIERS`.
"""

from __future__ import annotations

from typing import Final

#: The maximum length of a real X12 segment identifier. Segment IDs are two or
#: three characters, so anything longer cannot name a standard segment.
X12_SEGMENT_ID_MAX_LEN: Final = 3

#: Carries a self-authored ``EB-*`` benefit outcome in the 271 responder.
#: Stands in for the real ``EB`` segment, whose code list is not reproduced.
BENEFIT_SEGMENT: Final = "ZEBC"

#: Carries a self-authored ``CS-*`` claim status in the 277 responder.
#: Stands in for the real ``STC`` segment, whose code lists are not reproduced.
STATUS_SEGMENT: Final = "ZCSI"

#: Carries a self-authored ``RJ-*`` reject reason in both responders.
#: Stands in for the real ``AAA`` segment, whose code list is not reproduced.
REJECT_SEGMENT: Final = "ZRJC"

#: Every invented carrier introduced by the 270/271 and 276/277 layers. The
#: guard test in ``tests/test_invented_segment_ids.py`` asserts each one is long
#: enough that it cannot be a real X12 segment ID.
INVENTED_CARRIERS: Final = frozenset({BENEFIT_SEGMENT, STATUS_SEGMENT, REJECT_SEGMENT})

#: Three-character invented carriers that predate the length rule and remain in
#: use on layers already published. Each is evidenced by directory lookup rather
#: than guaranteed by length, so each must stay individually verified.
LEGACY_THREE_CHAR_CARRIERS: Final = frozenset({"DRC"})

#: Real X12 segments whose externally maintained code lists this repo refuses to
#: reproduce. The invented carriers above exist so these never have to be
#: emitted with invented content inside them.
DISPLACED_REAL_SEGMENTS: Final = frozenset({"AAA", "EB", "STC"})


def cannot_be_an_x12_segment_id(segment_id: str) -> bool:
    """Return True when ``segment_id`` is too long to be a real X12 segment ID.

    This is the whole safety argument for the invented carriers, expressed as
    one function so it can be asserted in tests rather than believed:

    >>> cannot_be_an_x12_segment_id("ZCSI")
    True
    >>> cannot_be_an_x12_segment_id("CSI")   # a real segment: transaction set 260
    False
    """
    return len(segment_id) > X12_SEGMENT_ID_MAX_LEN
