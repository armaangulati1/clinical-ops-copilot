"""Generate SYNTHETIC scanned prior-authorization decision letters.

Renders letter text to PNG images with Pillow, varying fonts and sizes and
applying mild noise/rotation to a few images so the OCR pipeline is exercised
on imperfect scans. The generation is fully deterministic (seeded per letter),
so the committed PNGs and ground-truth file are reproducible.

Every letter is SYNTHETIC. Names and identifiers are invented for the demo and
carry no PHI. Each rendered page is stamped as a synthetic demo document.

Run:
    uv run python -m ocr.generate_fixtures
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GROUND_TRUTH_PATH = FIXTURES_DIR / "ground_truth.json"

# TrueType fonts available on macOS. Chosen for legible digits so the OCR
# accuracy reflects parsing/noise handling rather than font pathologies.
_FONT_DIR = Path("/System/Library/Fonts/Supplemental")
_FONT_FILES = [
    "Arial.ttf",
    "Times New Roman.ttf",
    "Georgia.ttf",
    "Verdana.ttf",
    "Tahoma.ttf",
]

_STAMP = "[SYNTHETIC DEMO LETTER - NOT A REAL PAYER DOCUMENT]"


@dataclass(frozen=True)
class GroundTruth:
    """Known field values for one generated letter (the eval reference)."""

    image: str
    case_id: str
    patient_name: str
    decision: str  # APPROVED | DENIED | PENDED
    drug: str
    condition: str
    auth_number: str | None
    decision_date: str
    valid_through: str | None


# Source content for the letters. Synthetic throughout.
_LETTERS: list[GroundTruth] = [
    GroundTruth(
        "letter_01.png",
        "PA-2026-0042",
        "Jordan Rivera",
        "APPROVED",
        "Adalimumab",
        "Rheumatoid Arthritis",
        "AUTH-8871245",
        "03/14/2026",
        "09/14/2026",
    ),
    GroundTruth(
        "letter_02.png",
        "PA-2026-0117",
        "Casey Nguyen",
        "DENIED",
        "Semaglutide",
        "Type 2 Diabetes",
        None,
        "03/18/2026",
        None,
    ),
    GroundTruth(
        "letter_03.png",
        "PA-2026-0205",
        "Morgan Patel",
        "PENDED",
        "Infliximab",
        "Crohn Disease",
        None,
        "03/21/2026",
        None,
    ),
    GroundTruth(
        "letter_04.png",
        "PA-2026-0263",
        "Taylor Brooks",
        "APPROVED",
        "Etanercept",
        "Psoriatic Arthritis",
        "AUTH-9042318",
        "03/25/2026",
        "09/25/2026",
    ),
    GroundTruth(
        "letter_05.png",
        "PA-2026-0341",
        "Riley Okafor",
        "DENIED",
        "Dupilumab",
        "Atopic Dermatitis",
        None,
        "04/02/2026",
        None,
    ),
    GroundTruth(
        "letter_06.png",
        "PA-2026-0388",
        "Avery Santos",
        "APPROVED",
        "Ustekinumab",
        "Plaque Psoriasis",
        "AUTH-7719004",
        "04/06/2026",
        "10/06/2026",
    ),
    GroundTruth(
        "letter_07.png",
        "PA-2026-0455",
        "Quinn Delgado",
        "PENDED",
        "Vedolizumab",
        "Ulcerative Colitis",
        None,
        "04/09/2026",
        None,
    ),
    GroundTruth(
        "letter_08.png",
        "PA-2026-0512",
        "Sydney Marsh",
        "APPROVED",
        "Tocilizumab",
        "Giant Cell Arteritis",
        "AUTH-8330671",
        "04/12/2026",
        "10/12/2026",
    ),
    GroundTruth(
        "letter_09.png",
        "PA-2026-0579",
        "Devon Ellis",
        "DENIED",
        "Secukinumab",
        "Ankylosing Spondylitis",
        None,
        "04/15/2026",
        None,
    ),
    GroundTruth(
        "letter_10.png",
        "PA-2026-0634",
        "Harper Malik",
        "APPROVED",
        "Golimumab",
        "Rheumatoid Arthritis",
        "AUTH-9518420",
        "04/19/2026",
        "10/19/2026",
    ),
    GroundTruth(
        "letter_11.png",
        "PA-2026-0701",
        "Emerson Cho",
        "PENDED",
        "Risankizumab",
        "Crohn Disease",
        None,
        "04/23/2026",
        None,
    ),
    GroundTruth(
        "letter_12.png",
        "PA-2026-0768",
        "Reese Ibrahim",
        "APPROVED",
        "Certolizumab",
        "Psoriatic Arthritis",
        "AUTH-7204993",
        "04/27/2026",
        "10/27/2026",
    ),
]

# Letters that get degraded (rotation + speckle + blur) to test noise handling.
# These simulate lower-quality scans/faxes so the eval exercises the tolerant
# parser and code-field normalization rather than only clean renders.
_NOISY_INDICES = {2, 5, 8, 10}


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / name), size)


def _render_letter(gt: GroundTruth, index: int) -> Image.Image:
    """Render one letter to an image, deterministically per index."""
    rng = random.Random(1000 + index)
    font_file = _FONT_FILES[index % len(_FONT_FILES)]
    body_size = 22 + (index % 3) * 2  # 22, 24, or 26 px

    title_font = _load_font("Arial.ttf", body_size + 4)
    body_font = _load_font(font_file, body_size)

    lines: list[tuple[str, ImageFont.FreeTypeFont]] = [
        ("UTILIZATION MANAGEMENT DECISION NOTICE", title_font),
        (_STAMP, body_font),
        ("", body_font),
        (f"Date: {gt.decision_date}", body_font),
        (f"Case ID: {gt.case_id}", body_font),
        (f"Member: {gt.patient_name}", body_font),
        (f"Medication: {gt.drug}", body_font),
        (f"Condition: {gt.condition}", body_font),
        ("", body_font),
        (f"Decision: {gt.decision}", body_font),
    ]
    if gt.auth_number is not None:
        lines.append((f"Authorization Number: {gt.auth_number}", body_font))
    if gt.valid_through is not None:
        lines.append((f"Valid Through: {gt.valid_through}", body_font))
    lines.append(("", body_font))
    lines.append(("Generated for demonstration purposes only.", body_font))

    width = 760
    margin = 30
    line_h = body_size + 12
    height = margin * 2 + line_h * len(lines)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    y = margin
    for text, font in lines:
        draw.text((margin, y), text, font=font, fill=(15, 15, 15))
        y += line_h

    if index in _NOISY_INDICES:
        img = _degrade(img, rng)
    return img


def _degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    """Simulate a low-quality scan: speckle, blur, and rotation.

    Deterministic given the seeded rng. Tuned to be heavy enough that raw
    tesseract output picks up real character errors on some code-shaped fields,
    so the eval measures the tolerant parser doing genuine recovery work rather
    than reading pristine renders.
    """
    px = img.load()
    assert px is not None
    w, h = img.size
    n_speckles = (w * h) // 120
    for _ in range(n_speckles):
        x = rng.randrange(w)
        y = rng.randrange(h)
        shade = rng.randrange(70, 165)
        px[x, y] = (shade, shade, shade)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    angle = rng.choice([-2.0, -1.5, 1.5, 2.0])
    return img.rotate(angle, expand=True, fillcolor=(255, 255, 255))


def generate(out_dir: Path = FIXTURES_DIR) -> list[GroundTruth]:
    """Generate all fixtures and the ground-truth file. Returns ground truth.

    Writes ``ground_truth.json`` into ``out_dir`` alongside the images so a run
    against a scratch directory is self-contained and reproducible.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, gt in enumerate(_LETTERS):
        img = _render_letter(gt, index)
        img.save(out_dir / gt.image, format="PNG")
    ground_truth = [asdict(gt) for gt in _LETTERS]
    (out_dir / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8"
    )
    return list(_LETTERS)


def main() -> None:
    gts = generate()
    print(f"Generated {len(gts)} synthetic letters in {FIXTURES_DIR}")
    print(f"Ground truth written to {GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    main()
